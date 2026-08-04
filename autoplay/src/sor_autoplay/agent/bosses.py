"""ROM-backed tactical movement for bosses that punish generic pursuit.

This module deliberately owns *movement mechanics*, not target scoring.  The
fuzzy selector still chooses which enemy to fight; these guards prevent the
chosen Stage-2 Souther from luring the player back into an already committed
attack lane.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..phases import is_dangerous
from ..world_map import LANE_Y_MIN, MapEntity, lane_y_max_for_level


SOUTHER_TYPE = 0x55


@dataclass(frozen=True, slots=True)
class BossTactic:
    """A safe movement waypoint, or an instruction to hold the safe lane.

    ``mandatory`` marks a ROM-gate denial (armed leap / throw band). Those
    outrank free combat: the attack they prevent costs far more than the punch
    they delay.
    """

    goal_x: float
    goal_y: float
    hold: bool
    note: str
    mandatory: bool = False


def tactical_move(
    me: MapEntity,
    target: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    level_index: int,
) -> BossTactic | None:
    """Return a mechanic-specific evasive move for Souther.

    ROM evidence: Souther primary state 2 (``$16118``) is the claw/contact
    sequence. Its target selector explicitly reacts to player jump/facing, so
    the safe response is a grounded lane break, not another jump-in.
    """

    del entities  # kept for signature stability with the free-combat caller
    if target.type_id != SOUTHER_TYPE or target.kind != "boss":
        return None
    if not is_dangerous(target.combat_phase):
        return None
    return _evade_attack_lane(
        me,
        attack_lane=float(target.world_y),
        level_index=level_index,
        family="Souther",
    )


def _evade_if_on_lane(
    me: MapEntity,
    *,
    attack_lane: float,
    level_index: int,
    family: str,
    clearance: float,
) -> BossTactic | None:
    """Sidestep when on the attack depth; return None when already clear.

    Returning a hold tactic here would freeze free combat (no punches) while
    the AI believes it is "safe".
    """

    lane_gap = abs(float(me.world_y) - attack_lane)
    if lane_gap >= clearance - 4.0:
        return None
    return _evade_attack_lane(
        me,
        attack_lane=attack_lane,
        level_index=level_index,
        family=family,
        clearance=clearance,
    )


def _evade_attack_lane(
    me: MapEntity,
    *,
    attack_lane: float,
    level_index: int,
    family: str,
    clearance: float = 28.0,
) -> BossTactic:
    lane_gap = abs(float(me.world_y) - attack_lane)
    if lane_gap >= clearance - 4.0:
        return BossTactic(
            goal_x=float(me.world_x),
            goal_y=float(me.world_y),
            hold=True,
            note=f"hold safe lane {family}",
        )

    lane_min = float(LANE_Y_MIN + 6)
    lane_max = float(lane_y_max_for_level(level_index) - 6)
    candidates = tuple(
        lane
        for lane in (attack_lane - clearance, attack_lane + clearance)
        if lane_min <= lane <= lane_max
    )
    if not candidates:
        # The boss is at an extreme edge.  Use the opposite playable edge;
        # unlike horizontal retreat, this cannot leave the arena.
        goal_y = lane_max if attack_lane <= (lane_min + lane_max) / 2.0 else lane_min
    else:
        goal_y = min(
            candidates,
            key=lambda lane: (abs(lane - float(me.world_y)), lane),
        )
    return BossTactic(
        goal_x=float(me.world_x),
        goal_y=goal_y,
        hold=False,
        note=f"sidestep {family}",
    )
