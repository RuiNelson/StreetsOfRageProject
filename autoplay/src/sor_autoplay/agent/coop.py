"""Two-player cooperation: item fairness, ally safety, and partner assists.

Streets of Rage 1 has friendly fire. Attacks, weapon swings/throws, rear
attacks, and jump kicks that land on another live player damage them. The
agent must never intentionally emit an attack that would hit a co-op partner
(human or AI), even while trying to hit an enemy in the same lane.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..state import PlayerSnapshot
from ..world_map import MapEntity

# Conservative friendly-fire bands. Slightly wider than the punch lane so a
# one-frame animation drift cannot still tag the partner after we decide B.
ALLY_LANE_HALF = 14.0
# Body-overlap always collides regardless of facing.
ALLY_BODY_X = 12.0
# Front punch / bat-pipe swing outer reach (covers Blaze strike + margin).
ALLY_MELEE_RANGE = 72.0
# Knife/bottle/pepper travel far enough to tag a partner mid-screen.
ALLY_THROWN_RANGE = 120.0
# Rear (B+C) band with a small margin past the longest rear profile.
ALLY_REAR_RANGE = 40.0
# Lane step used when the partner blocks a straight-line attack.
ALLY_CLEAR_LANE = 22.0


@dataclass(frozen=True, slots=True)
class CoopContext:
    partner: MapEntity | None
    partner_snap: PlayerSnapshot | None
    both_agents: bool
    partner_hp: float | None


def build_coop(
    *,
    me: MapEntity | None,
    me_snap: PlayerSnapshot,
    partner: MapEntity | None,
    partner_snap: PlayerSnapshot | None,
    both_agents: bool,
) -> CoopContext:
    del me, me_snap
    hp = None
    if partner_snap is not None and partner_snap.health_percent is not None:
        hp = partner_snap.health_percent
    # Only treat a partner as an attack-blocking ally while they are still a
    # live seat. Defeated / inactive seats must not freeze combat forever.
    live_partner = partner
    if partner_snap is not None and not (
        partner_snap.is_playable or partner_snap.mode_active
    ):
        live_partner = None
    if partner_snap is not None and partner_snap.health is not None:
        if partner_snap.health <= 0:
            live_partner = None
    return CoopContext(
        partner=live_partner,
        partner_snap=partner_snap,
        both_agents=both_agents,
        partner_hp=hp,
    )


def attack_would_hit_ally(
    me: MapEntity,
    ally: MapEntity | None,
    *,
    face_left: bool | None = None,
    rear: bool = False,
    thrown: bool = False,
    max_range: float | None = None,
    lane_half: float = ALLY_LANE_HALF,
) -> bool:
    """True if a player attack from ``me`` is likely to damage ``ally``.

    SoR1 friendly fire uses the same facing cone and lane band as enemy hits.
    A body-overlap always collides. Front strikes and thrown weapons travel
    along facing; rear attacks hit the opposite side.
    """

    if ally is None or ally.kind != "player":
        return False
    if ally.slot == me.slot:
        return False

    dx = ally.map_x - me.map_x
    dy = ally.map_y - me.map_y
    if abs(dy) > lane_half:
        return False

    if max_range is None:
        if thrown:
            max_range = ALLY_THROWN_RANGE
        elif rear:
            max_range = ALLY_REAR_RANGE
        else:
            max_range = ALLY_MELEE_RANGE
    abs_dx = abs(dx)
    if abs_dx > max_range:
        return False
    if abs_dx <= ALLY_BODY_X:
        return True

    facing_left = bool(me.action_state & 0x01) if face_left is None else face_left
    if rear:
        # Behind relative to current facing.
        return (dx > 0.0) if facing_left else (dx < 0.0)
    # Ahead relative to facing (punches, weapon swings, projectiles).
    return (dx < 0.0) if facing_left else (dx > 0.0)


def ally_clear_lane_delta(
    me: MapEntity,
    ally: MapEntity,
    *,
    lane_min: float = 2.0,
    lane_max: float = 112.0,
) -> float:
    """Signed world-Y step that leaves the ally's friendly-fire lane band."""

    # Prefer the side that already has more separation from the ally.
    prefer_up = me.map_y >= ally.map_y
    primary = ALLY_CLEAR_LANE if prefer_up else -ALLY_CLEAR_LANE
    secondary = -primary
    for delta in (primary, secondary):
        goal = me.world_y + delta
        if lane_min <= goal <= lane_max:
            return delta
    return primary


def should_take_health_pickup(
    me_snap: PlayerSnapshot,
    coop: CoopContext,
    *,
    critical_hp: float = 30.0,
) -> bool:
    """True if this player should claim a health/food/apple pickup.

    Spec: do not be greedy — let the other player take life/special items if
    they have less health. Weapons are always free (handled separately).
    """

    my_hp = me_snap.health_percent if me_snap.health_percent is not None else 100.0
    if my_hp >= 95.0:
        return False  # full enough; leave it
    if coop.partner_snap is None or coop.partner_hp is None:
        return True
    if my_hp <= critical_hp:
        return True
    if coop.partner_hp + 8.0 < my_hp:
        # Partner is meaningfully healthier-worse (lower HP) — yield.
        return False
    return True


def should_take_special_or_life(
    me_snap: PlayerSnapshot,
    coop: CoopContext,
) -> bool:
    """Extra-life / police-star fairness follows the same health rule."""

    return should_take_health_pickup(me_snap, coop, critical_hp=40.0)


def partner_throw_opportunity(
    me: MapEntity,
    partner: MapEntity | None,
    *,
    x_close: float = 28.0,
    lane_close: float = 14.0,
) -> bool:
    """Rough check for the 2P mid-air grapple assist window.

    Classic co-op: jump under/near partner and attack for the dual throw.
    We only signal when the partner is elevated (world_z > small threshold)
    and horizontally close. This is the sole intentional attack near an ally.
    """

    if partner is None:
        return False
    if abs(me.map_x - partner.map_x) > x_close:
        return False
    if abs(me.map_y - partner.map_y) > lane_close:
        return False
    # Partner airborne: elevation stored on MapEntity.world_z.
    return partner.world_z >= 8


def throw_direction_away_from_ally(
    me: MapEntity,
    ally: MapEntity | None,
    *,
    default_dir: int,
) -> int:
    """Prefer throwing a held foe away from a live co-op partner.

    Returns -1 (left) or +1 (right). When the ally is not in a throw-risk
    band, keep the normal away-from-facing choice.
    """

    if ally is None or ally.kind != "player":
        return default_dir
    if abs(ally.map_y - me.map_y) > ALLY_LANE_HALF + 8.0:
        return default_dir
    if abs(ally.map_x - me.map_x) > 90.0:
        return default_dir
    # Throw toward the side opposite the ally.
    return -1 if ally.map_x >= me.map_x else 1
