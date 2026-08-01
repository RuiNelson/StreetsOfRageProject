"""Two-player cooperation: item fairness and simple partner assists."""

from __future__ import annotations

from dataclasses import dataclass

from ..state import PlayerSnapshot
from ..world_map import MapEntity


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
    hp = None
    if partner_snap is not None and partner_snap.health_percent is not None:
        hp = partner_snap.health_percent
    return CoopContext(
        partner=partner,
        partner_snap=partner_snap,
        both_agents=both_agents,
        partner_hp=hp,
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
    and horizontally close.
    """

    if partner is None:
        return False
    if abs(me.map_x - partner.map_x) > x_close:
        return False
    if abs(me.map_y - partner.map_y) > lane_close:
        return False
    # Partner airborne: elevation stored on MapEntity.world_z.
    return partner.world_z >= 8
