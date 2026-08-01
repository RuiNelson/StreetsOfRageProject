"""ROM-backed tactical movement for bosses that punish generic pursuit.

This module deliberately owns *movement mechanics*, not target scoring.  The
fuzzy selector still chooses which enemy to fight; these guards prevent the
chosen Stage-2 Souther or Stage-5 twin from luring the player back into an
already committed attack lane.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..phases import is_dangerous
from ..world_map import LANE_Y_MIN, MapEntity, lane_y_max_for_level


SOUTHER_TYPE = 0x55
TWIN_TYPE = 0x58


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
) -> BossTactic | None:
    """Return a mechanic-specific evasive move for Souther or the twins.

    ROM evidence:

    * Souther primary state 2 (``$16118``) is the claw/contact sequence.  Its
      target selector explicitly reacts to player jump/facing, so the safe
      response is a grounded lane break, not another jump-in.
    * Onihime/Yasha primary state 2 (``$15D0C``) owns the damaging jump/grab
      choreography.  When both type-$58 objects bracket the player, staying in
      their shared lane exposes the player's back whichever target is chosen.
    """

    if target.type_id == SOUTHER_TYPE and target.kind == "boss":
        if not is_dangerous(target.combat_phase):
            return None
        return _evade_attack_lane(
            me,
            attack_lane=float(target.world_y),
            level_index=level_index,
            family="Souther",
        )

    if target.type_id != TWIN_TYPE or target.kind != "boss":
        return None

    twins = tuple(
        entity
        for entity in entities
        if entity.kind == "boss"
        and entity.type_id == TWIN_TYPE
        and not entity.is_defeated
    )
    nearby = tuple(
        twin
        for twin in twins
        if abs(twin.world_x - me.world_x) <= 150
        and abs(twin.world_y - me.world_y) <= 36
    )
    bracketed = (
        len(nearby) >= 2
        and min(twin.world_x for twin in nearby) < me.world_x
        and max(twin.world_x for twin in nearby) > me.world_x
    )
    if bracketed:
        shared_lane = sum(float(twin.world_y) for twin in nearby) / len(nearby)
        return _evade_attack_lane(
            me,
            attack_lane=shared_lane,
            level_index=level_index,
            family="twins surround",
        )
    if is_dangerous(target.combat_phase):
        return _evade_attack_lane(
            me,
            attack_lane=float(target.world_y),
            level_index=level_index,
            family="twin jump/grab",
        )
    return None


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
