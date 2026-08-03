"""ROM-backed tactical movement for bosses that punish generic pursuit.

This module owns *movement mechanics*, not target scoring. Twin (Onihime/Yasha)
logic is delegated to ``twins.py``, which implements focus-fire and routine
windows from ``enemy-ai.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..phases import is_dangerous
from ..world_map import LANE_Y_MIN, MapEntity, lane_y_max_for_level
from . import twins as twin_ai


SOUTHER_TYPE = 0x55
TWIN_TYPE = twin_ai.TWIN_TYPE


@dataclass(frozen=True, slots=True)
class BossTactic:
    """A safe movement waypoint, or an instruction to hold the safe lane."""

    goal_x: float
    goal_y: float
    hold: bool
    note: str


def tactical_move(
    me: MapEntity,
    target: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    level_index: int,
    focus_slot: str | None = None,
) -> BossTactic | None:
    """Return a mechanic-specific evasive move for Souther or the twins."""

    if target.type_id == SOUTHER_TYPE and target.kind == "boss":
        if not is_dangerous(target.combat_phase):
            return None
        return _evade_attack_lane(
            me,
            attack_lane=float(target.world_y),
            level_index=level_index,
            family="Souther",
        )

    if not twin_ai.is_twin(target) or target.is_defeated:
        return None

    move = twin_ai.tactical_move(
        me,
        target,
        entities,
        level_index=level_index,
        focus_slot=focus_slot,
    )
    if move is None:
        return None
    return BossTactic(
        goal_x=move.goal_x,
        goal_y=move.goal_y,
        hold=move.hold,
        note=move.note,
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
        goal_y = (
            lane_max
            if attack_lane <= (lane_min + lane_max) / 2.0
            else lane_min
        )
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
