"""ROM-backed tactical movement for bosses that punish generic pursuit.

This module deliberately owns *movement mechanics*, not target scoring.  The
fuzzy selector still chooses which enemy to fight; these guards prevent the
chosen Stage-2 Souther or Stage-5 twin from luring the player back into an
already committed attack lane.

Twin movement branches on Level-C scene composition (``agent/scene.py``):

* **PAIR** — two living type-``$58``: bracket escape, and when not bracketed
  but both nearby, leave a shared attack lane / isolate.
* **SURVIVOR** — one living twin: only leave the lane on a committed jump/grab
  (primary ``$02`` / dangerous phase); otherwise free combat owns the tree.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..phases import is_dangerous
from ..world_map import LANE_Y_MIN, MapEntity, lane_y_max_for_level
from . import scene as scene_ai


SOUTHER_TYPE = 0x55
TWIN_TYPE = scene_ai.TWIN_TYPE


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
      choreography.  When both type-$58 objects are alive they can bracket the
      player; the survivor (unpaired) still has grab commit but no partner.
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

    if not scene_ai.is_twin(target) or target.is_defeated:
        return None

    composition = scene_ai.twin_composition(entities)
    if composition is scene_ai.TwinComposition.ABSENT:
        return None

    if composition is scene_ai.TwinComposition.PAIR:
        return _twin_pair_tactic(me, target, entities, level_index=level_index)

    # SURVIVOR: only react to a committed jump/grab, then pressure via combat.
    if is_dangerous(target.combat_phase):
        return _evade_attack_lane(
            me,
            attack_lane=float(target.world_y),
            level_index=level_index,
            family="twin survivor jump/grab",
        )
    return None


def _twin_pair_tactic(
    me: MapEntity,
    target: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    level_index: int,
) -> BossTactic | None:
    """Movement tree while both Onihime and Yasha are alive."""

    nearby = scene_ai.nearby_twins(me, entities)
    if scene_ai.twins_bracket_player(me, entities):
        shared_lane = sum(float(twin.world_y) for twin in nearby) / len(nearby)
        return _evade_attack_lane(
            me,
            attack_lane=shared_lane,
            level_index=level_index,
            family="twins pair surround",
        )

    # Both nearby (same side or stacked lanes): leave the target's attack lane
    # so the partner cannot finish a rear grab on the same depth.
    if len(nearby) >= 2:
        attack_lane = float(target.world_y)
        if is_dangerous(target.combat_phase) or any(
            is_dangerous(twin.combat_phase) for twin in nearby
        ):
            return _evade_attack_lane(
                me,
                attack_lane=attack_lane,
                level_index=level_index,
                family="twins pair pressure",
            )
        # Non-attacking pair still nearby: hold a lane offset rather than
        # walking between them (isolate stand-off is combat's job).
        lane_gap = abs(float(me.world_y) - attack_lane)
        if lane_gap < 18.0:
            return _evade_attack_lane(
                me,
                attack_lane=attack_lane,
                level_index=level_index,
                family="twins pair isolate",
                clearance=24.0,
            )
        return BossTactic(
            goal_x=float(me.world_x),
            goal_y=float(me.world_y),
            hold=True,
            note="hold safe lane twins pair isolate",
        )

    # Only the focused twin is nearby: leave lane on committed grab/jump.
    if is_dangerous(target.combat_phase):
        return _evade_attack_lane(
            me,
            attack_lane=float(target.world_y),
            level_index=level_index,
            family="twins pair jump/grab",
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
