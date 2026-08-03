"""Two-player cooperation: item fairness, ally safety, and partner assists.

Streets of Rage 1 has friendly fire. Attacks, weapon swings/throws, rear
attacks, and jump kicks that land on another live player damage them. The
agent must never intentionally emit an attack that would hit a co-op partner
(human or AI), even while trying to hit an enemy in the same lane.

Safety layers:

1. Wide body bubble — any partner this close is hit by any B regardless of face.
2. Directional strike / throw / rear cone — partner on the attack side in-lane.
3. Final ``guard_attack_intent`` — strips B/B+C on every seat after policy.

The co-op air assist is the only intentional near-partner attack, and only
when the partner is in a jump **action** family. Standing elevation in
``world_z`` is always large and must never be used for that test.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..state import PlayerSnapshot
from ..world_map import MapEntity
from .controls import Intent

# Live player/weapon boxes connect past the conservative ±12 punch lane.
ALLY_LANE_HALF = 28.0
# Omnidirectional body contact: any B here damages the partner.
ALLY_BODY_X = 24.0
# Front punch / bat-pipe outer reach (Blaze + margin).
ALLY_MELEE_RANGE = 80.0
# Knife/bottle/pepper travel.
ALLY_THROWN_RANGE = 140.0
# Rear (B+C) band with margin past the longest rear profile.
ALLY_REAR_RANGE = 48.0
# Lane step used when the partner blocks a straight-line attack.
ALLY_CLEAR_LANE = 30.0
# Walk-into-grab shell (SoR latch is contact, not only B). Keep a margin past
# ALLY_BODY_X so free progress does not re-plow into a human partner every poll.
# Stage-6 free-path funnel (lane $60) made this constant collision obvious.
ALLY_GRAB_SEPARATE_X = 36.0
ALLY_GRAB_SEPARATE_Y = 22.0
# Horizontal back-off when Y separation is unavailable.
ALLY_GRAB_BACKOFF_X = 40.0


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


def _ally_geometry(
    me: MapEntity, ally: MapEntity | None
) -> tuple[float, float] | None:
    if ally is None or ally.kind != "player":
        return None
    if ally.slot == me.slot:
        return None
    return ally.map_x - me.map_x, ally.map_y - me.map_y


def ally_in_body_range(
    me: MapEntity,
    ally: MapEntity | None,
    *,
    max_x: float = ALLY_BODY_X,
    max_y: float = ALLY_LANE_HALF,
) -> bool:
    """True if the partner is close enough that any B risks body collision."""

    geom = _ally_geometry(me, ally)
    if geom is None:
        return False
    dx, dy = geom
    return abs(dx) <= max_x and abs(dy) <= max_y


def ally_grab_collision_risk(
    me: MapEntity,
    ally: MapEntity | None,
    *,
    max_x: float = ALLY_GRAB_SEPARATE_X,
    max_y: float = ALLY_GRAB_SEPARATE_Y,
) -> bool:
    """True when walking any closer risks a ROM body-grab latch on the partner.

    Co-op gate only strips B; SoR1 grab is contact-based. Progress/combat walks
    that plow into a human partner look like the AI is "trying to grab" them.
    """

    return ally_in_body_range(me, ally, max_x=max_x, max_y=max_y)


def partner_blocks_goal(
    me: MapEntity,
    ally: MapEntity | None,
    goal_x: float,
    goal_y: float,
    *,
    margin_x: float = ALLY_GRAB_SEPARATE_X,
    margin_y: float = ALLY_GRAB_SEPARATE_Y,
) -> bool:
    """True if the straight walk to ``(goal_x, goal_y)`` crosses the partner body."""

    geom = _ally_geometry(me, ally)
    if geom is None or ally is None:
        return False
    wx, wy = float(me.world_x), float(me.world_y)
    ax, ay = float(ally.world_x), float(ally.world_y)
    gx, gy = float(goal_x), float(goal_y)
    samples = 8
    for i in range(samples + 1):
        t = i / samples
        x = wx + (gx - wx) * t
        y = wy + (gy - wy) * t
        if abs(x - ax) <= margin_x and abs(y - ay) <= margin_y:
            return True
    return False


def separate_from_ally_goal(
    me: MapEntity,
    ally: MapEntity,
    *,
    level_index: int = 0,
    camera_bottom: float = 112.0,
    progress_right: bool = True,
) -> tuple[float, float, str]:
    """World goal that leaves the partner's grab shell (prefer lane first).

    Round 6 free floor is lower (larger Y). Prefer separating toward the free
    lower path when both options are legal, so we do not shove the partner into
    upper class-2 walls / presses.
    """

    del progress_right
    lane_min = 14.0
    lane_max = max(lane_min, min(float(camera_bottom) - 12.0, 108.0))
    if level_index == 6:
        lane_max = max(lane_max, 148.0)
    me_y = float(me.world_y)
    ally_y = float(ally.world_y)
    me_x = float(me.world_x)
    ally_x = float(ally.world_x)

    # Prefer vertical separation so progress can resume past them.
    up = max(lane_min, ally_y - ALLY_CLEAR_LANE - 8.0)
    down = min(lane_max, ally_y + ALLY_CLEAR_LANE + 8.0)
    candidates: list[float] = []
    for y in (up, down, lane_min, lane_max):
        if lane_min <= y <= lane_max and abs(y - ally_y) > ALLY_GRAB_SEPARATE_Y:
            candidates.append(y)
    if candidates:
        # Stage 6 (index 5): prefer the lower free floor.
        if level_index == 5:
            lower = [y for y in candidates if y >= ally_y]
            pool = lower if lower else candidates
            goal_y = min(pool, key=lambda y: (abs(y - me_y), -y))
        else:
            # Keep the side we already occupy when possible.
            same_side = (
                [y for y in candidates if (y - ally_y) * (me_y - ally_y) >= 0]
                if me_y != ally_y
                else candidates
            )
            pool = same_side if same_side else candidates
            goal_y = min(pool, key=lambda y: abs(y - me_y))
        if abs(me_y - ally_y) <= ALLY_GRAB_SEPARATE_Y + 2.0:
            return me_x, goal_y, "separate ally lane"
        # Already off-lane enough: hold Y, back off on X if still too close on X.
        if abs(me_x - ally_x) <= ALLY_GRAB_SEPARATE_X:
            away = -1.0 if me_x >= ally_x else 1.0
            return me_x + away * ALLY_GRAB_BACKOFF_X, me_y, "separate ally x"
        return me_x, goal_y, "separate ally lane"

    # No free Y: back away on X.
    away = -1.0 if me_x >= ally_x else 1.0
    return me_x + away * ALLY_GRAB_BACKOFF_X, me_y, "separate ally x"


def ally_in_attack_bubble(
    me: MapEntity,
    ally: MapEntity | None,
    *,
    max_x: float = ALLY_MELEE_RANGE,
    max_y: float = ALLY_LANE_HALF,
) -> bool:
    """True if a partner is nearby in the attack plane (any facing).

    Used for early "clear lane" decisions. The final guard is directional so
    two agents can still fight when one stands safely behind the other.
    """

    geom = _ally_geometry(me, ally)
    if geom is None:
        return False
    dx, dy = geom
    return abs(dx) <= max_x and abs(dy) <= max_y


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
    """True if a player attack from ``me`` is likely to damage ``ally``."""

    geom = _ally_geometry(me, ally)
    if geom is None:
        return False
    dx, dy = geom
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
    # Body contact hits regardless of facing.
    if abs_dx <= ALLY_BODY_X:
        return True

    facing_left = bool(me.action_state & 0x01) if face_left is None else face_left
    if rear:
        return (dx > 0.0) if facing_left else (dx < 0.0)
    return (dx < 0.0) if facing_left else (dx > 0.0)


def ally_clear_lane_delta(
    me: MapEntity,
    ally: MapEntity,
    *,
    lane_min: float = 2.0,
    lane_max: float = 112.0,
) -> float:
    """Signed world-Y step that leaves the ally's friendly-fire lane band."""

    prefer_up = me.map_y >= ally.map_y
    primary = ALLY_CLEAR_LANE if prefer_up else -ALLY_CLEAR_LANE
    secondary = -primary
    for delta in (primary, secondary):
        goal = me.world_y + delta
        if lane_min <= goal <= lane_max:
            if abs((me.map_y + delta) - ally.map_y) > ALLY_LANE_HALF:
                return delta
    return primary


def face_left_from_intent(intent: Intent, me: MapEntity) -> bool:
    """Facing implied by this tick's D-pad, else the ROM action-state bit."""

    if intent.left and not intent.right:
        return True
    if intent.right and not intent.left:
        return False
    return bool(me.action_state & 0x01)


def partner_throw_opportunity(
    me: MapEntity,
    partner: MapEntity | None,
    *,
    x_close: float = 28.0,
    lane_close: float = 14.0,
) -> bool:
    """Rough check for the 2P mid-air grapple assist window.

    Classic co-op: attack near an **airborne** partner for the dual throw.
    Standing partners store elevation near ``$A0`` in ``+$18``, so ``world_z``
    must never be used — only jump action families count.
    """

    if partner is None:
        return False
    if not partner.is_airborne:
        return False
    if abs(me.map_x - partner.map_x) > x_close:
        return False
    if abs(me.map_y - partner.map_y) > lane_close:
        return False
    return True


def is_intentional_air_assist(
    intent: Intent, me: MapEntity, ally: MapEntity | None
) -> bool:
    """True only for the co-op air-throw chord near a truly airborne partner."""

    if ally is None:
        return False
    if intent.rear_attack:
        return False
    if not (intent.attack and intent.jump):
        return False
    return partner_throw_opportunity(me, ally)


def guard_attack_intent(
    me: MapEntity | None,
    ally: MapEntity | None,
    intent: Intent,
    *,
    both_agents: bool = False,
    allow_air_assist: bool = True,
    thrown: bool = False,
) -> Intent:
    """Hard final gate: strip attack buttons that would friendly-fire a partner.

    Every policy path ends here so a missed branch cannot still emit B/B+C
    into the partner. Directional: a partner safely behind the attacker does
    not block a forward punch (needed for dual-agent combat).
    """

    if me is None or ally is None:
        return intent
    if not (intent.attack or intent.rear_attack):
        return intent
    # Menu confirm reuses the attack bit without a combat hitbox.
    if intent.confirm and not intent.rear_attack and not intent.jump:
        return intent
    if (
        allow_air_assist
        and both_agents
        and is_intentional_air_assist(intent, me, ally)
    ):
        return intent
    # Partner vault → high jump-kick (AISpec §1.4.3) is an intentional
    # partner-hold tool; the final gate must not strip its B edge.
    if (intent.note or "").startswith("partner boost"):
        return intent

    face_left = face_left_from_intent(intent, me)
    # Holding a throwable weapon is not always visible on the intent; use the
    # player's held type when present so knife/bottle throws stay gated.
    use_thrown = thrown or me.is_holding_weapon and (
        0x08 <= (me.held_type & 0xFF) <= 0x09 or (me.held_type & 0xFF) == 0x0C
    )
    risky = attack_would_hit_ally(
        me,
        ally,
        face_left=face_left,
        rear=intent.rear_attack,
        thrown=use_thrown,
    )
    if not risky:
        return intent

    note = intent.note
    if note:
        note = f"{note}; ally safe"
    else:
        note = "ally safe"
    return replace(
        intent,
        attack=False,
        rear_attack=False,
        note=note,
    )


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
        return False
    if coop.partner_snap is None or coop.partner_hp is None:
        return True
    if my_hp <= critical_hp:
        return True
    if coop.partner_hp + 8.0 < my_hp:
        return False
    return True


def should_take_special_or_life(
    me_snap: PlayerSnapshot,
    coop: CoopContext,
) -> bool:
    """Extra-life / police-star fairness follows the same health rule."""

    return should_take_health_pickup(me_snap, coop, critical_hp=40.0)


def throw_direction_away_from_ally(
    me: MapEntity,
    ally: MapEntity | None,
    *,
    default_dir: int,
) -> int:
    """Prefer throwing a held foe away from a live co-op partner."""

    if ally is None or ally.kind != "player":
        return default_dir
    if abs(ally.map_y - me.map_y) > ALLY_LANE_HALF + 8.0:
        return default_dir
    if abs(ally.map_x - me.map_x) > 100.0:
        return default_dir
    return -1 if ally.map_x >= me.map_x else 1
