"""Scene composition: multi-entity overlays on single-target CounterPlans.

Level-C layer (``AISpec`` scene composition): behaviour that depends on the
*set* of live enemies, not only the selected target's family.

Currently owns **Onihime/Yasha** (type ``$58``):

| Composition | Meaning (ROM) |
| --- | --- |
| ``PAIR`` | Two living type-``$58`` objects (linked roles 1/2) |
| ``SURVIVOR`` | Exactly one living twin (unpaired ``+$5D=0`` after unlink) |
| ``ABSENT`` | No live twin |

Pair play is jump-grab + split grab/approach paths; the survivor drops pair
constraints and can promote to grab AI. Plans and boss tactics branch on this.
"""

from __future__ import annotations

from enum import Enum, auto

from ..world_map import MapEntity
from .enemies import CounterPlan, ThreatKind


TWIN_TYPE = 0x58
TWIN_FAMILY = "Onihime/Yasha"

# Geometry used by twin bracket / isolation helpers (matches bosses.py).
TWIN_NEAR_X = 150.0
TWIN_NEAR_Y = 36.0


class TwinComposition(Enum):
    """How many type-$58 bosses are still in the fight."""

    ABSENT = auto()
    PAIR = auto()
    SURVIVOR = auto()


# Normative pair plan: stay mobile, do not walk into body grabs between two
# jump-grabbers, never jump into grab commit, isolate one twin at range.
_TWIN_PAIR_PLAN = CounterPlan(
    ThreatKind.JUMP_GRAB,
    range_scale=1.25,
    prefer_lane_delta=1.0,
    jump_bias=0.0,
    rear_bias=0.35,
    grab_bias=0.05,
    sidestep=True,
    no_jump=True,
    priority=2.9,
    note="twins pair — isolate, stay mobile",
)

# Survivor (unpaired): pair constraints gone; can promote to grab AI. Pressure
# with grounded tools and optional body grab; light jump only on punish.
_TWIN_SURVIVOR_PLAN = CounterPlan(
    ThreatKind.JUMP_GRAB,
    range_scale=1.05,
    prefer_lane_delta=0.0,
    jump_bias=0.15,
    rear_bias=0.25,
    grab_bias=0.50,
    sidestep=True,
    no_jump=False,
    priority=2.6,
    note="twin survivor — pressure/grab",
)


def is_twin(entity: MapEntity) -> bool:
    """True for a type-$58 boss object (Onihime or Yasha)."""

    return entity.kind == "boss" and entity.type_id == TWIN_TYPE


def live_twins(entities: tuple[MapEntity, ...] | list[MapEntity]) -> tuple[MapEntity, ...]:
    """Living type-$58 bosses (not defeated)."""

    return tuple(
        entity
        for entity in entities
        if is_twin(entity) and not entity.is_defeated
    )


def twin_composition(
    entities: tuple[MapEntity, ...] | list[MapEntity],
) -> TwinComposition:
    """Classify the twin scene from the live object set."""

    count = len(live_twins(entities))
    if count >= 2:
        return TwinComposition.PAIR
    if count == 1:
        return TwinComposition.SURVIVOR
    return TwinComposition.ABSENT


def twin_scene_plan(composition: TwinComposition) -> CounterPlan | None:
    """Return the twin CounterPlan for a composition, or None if absent."""

    if composition is TwinComposition.PAIR:
        return _TWIN_PAIR_PLAN
    if composition is TwinComposition.SURVIVOR:
        return _TWIN_SURVIVOR_PLAN
    return None


def twin_focus_bonus(
    entity: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
    *,
    my_seat: int = 1,
) -> float:
    """Extra target-utility membership when both twins are alive (0..0.12).

    Prefer the twin that is actively attacking or locked on this seat so the
    agent isolates a real threat instead of thrashing between the pair.
    """

    if twin_composition(entities) is not TwinComposition.PAIR:
        return 0.0
    if not is_twin(entity) or entity.is_defeated:
        return 0.0

    bonus = 0.0
    from ..phases import is_dangerous

    if is_dangerous(entity.combat_phase):
        bonus += 0.08
    # pair_role 2 seeds grab/throw AI (+$7B bit1); prioritize that twin.
    if entity.pair_role == 2:
        bonus += 0.04
    if entity.targets_player == my_seat:
        bonus += 0.04
    return min(0.12, bonus)


def nearby_twins(
    me: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
    *,
    max_dx: float = TWIN_NEAR_X,
    max_dy: float = TWIN_NEAR_Y,
) -> tuple[MapEntity, ...]:
    """Live twins within a horizontal/lane window of the player."""

    return tuple(
        twin
        for twin in live_twins(entities)
        if abs(twin.world_x - me.world_x) <= max_dx
        and abs(twin.world_y - me.world_y) <= max_dy
    )


def twins_bracket_player(
    me: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
) -> bool:
    """True when two nearby twins sit on opposite sides of the player on X."""

    nearby = nearby_twins(me, entities)
    if len(nearby) < 2:
        return False
    return (
        min(twin.world_x for twin in nearby) < me.world_x
        and max(twin.world_x for twin in nearby) > me.world_x
    )


