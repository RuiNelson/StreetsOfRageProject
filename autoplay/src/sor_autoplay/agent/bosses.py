"""ROM-backed tactical movement for bosses that punish generic pursuit.

This module deliberately owns *movement mechanics*, not target scoring.  The
fuzzy selector still chooses which enemy to fight; these guards prevent the
chosen Stage-2 Souther or Stage-5 twin from luring the player back into an
already committed attack lane.

Twin movement branches on Level-C scene composition (``agent/scene.py``):

* **PAIR** — focus-fire lowest HP (scoring). Movement only intervenes on real
  threats: bracket surround, a DANGEROUS jump/grab on our depth, or a partner
  coplanar intrusion. Idle pair proximity must **not** freeze combat — free
  combat owns grounded punches on the focus twin.
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

# Leave a commit lane by this much before free combat may re-enter.
_TWIN_COMMIT_CLEARANCE = 28.0
# Partner body intrusion (grab setup window is ROM X < $90; act earlier).
_TWIN_INTRUDE_X = 56.0
_TWIN_INTRUDE_Y = 14.0


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
    """Movement while both twins live — threats only; else free combat damages.

    Previous behaviour isolated/held whenever two twins were nearby (ΔX≤150),
    which is the entire fight. That blocked ``attack_mix`` punches forever.
    """

    nearby = scene_ai.nearby_twins(me, entities)

    # 1) Bracketed on X: leave the shared depth (real surround).
    if scene_ai.twins_bracket_player(me, entities) and nearby:
        shared_lane = sum(float(twin.world_y) for twin in nearby) / len(nearby)
        return _evade_if_on_lane(
            me,
            attack_lane=shared_lane,
            level_index=level_index,
            family="twins pair surround",
            clearance=_TWIN_COMMIT_CLEARANCE,
        )

    # 2) Any nearby jump/grab commit: leave *that* twin's lane if we share it.
    #    Already clear → None so free combat can keep hitting the focus.
    urgent = scene_ai.most_urgent_dangerous_twin(me, entities)
    if urgent is not None:
        return _evade_if_on_lane(
            me,
            attack_lane=float(urgent.world_y),
            level_index=level_index,
            family="twins pair pressure",
            clearance=_TWIN_COMMIT_CLEARANCE,
        )

    # 3) Non-focus twin coplanar and close (grab setup): step off *their*
    #    lane only. Idle partner far away must not cancel focus-fire.
    partner = _closest_partner_intrusion(me, target, nearby)
    if partner is not None:
        return _evade_if_on_lane(
            me,
            attack_lane=float(partner.world_y),
            level_index=level_index,
            family="twins pair isolate",
            clearance=22.0,
        )

    # Focus alone committing is covered by (2). Idle focus → free combat.
    return None


def _closest_partner_intrusion(
    me: MapEntity,
    focus: MapEntity,
    nearby: tuple[MapEntity, ...],
) -> MapEntity | None:
    """Partner twin on the player's depth inside grab-setup range, if any."""

    candidates = []
    for twin in nearby:
        if twin.slot == focus.slot or twin.is_defeated:
            continue
        if is_dangerous(twin.combat_phase):
            continue  # handled by urgent path
        dx = abs(float(twin.world_x) - float(me.world_x))
        dy = abs(float(twin.world_y) - float(me.world_y))
        if dx <= _TWIN_INTRUDE_X and dy <= _TWIN_INTRUDE_Y:
            candidates.append((dx, twin))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


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
    the AI believes it is "safe" — deadly against a second twin approaching.
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
