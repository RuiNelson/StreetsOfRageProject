"""Scene composition: multi-entity overlays on single-target CounterPlans.

Level-C layer (``AISpec`` scene composition): behaviour that depends on the
*set* of live enemies, not only the selected target's family.

Currently owns **Onihime/Yasha** (type ``$58``):

| Composition | Meaning (ROM) |
| --- | --- |
| ``PAIR`` | Two living type-``$58`` objects (linked roles 1/2) |
| ``SURVIVOR`` | Exactly one living twin (unpaired ``+$5D=0`` after unlink) |
| ``ABSENT`` | No live twin |

**Pair doctrine (normative):** focus-fire the **lowest-HP** twin until it dies.
ROM has no enrage table — once one twin is gone the survivor drops pair
constraints and is much easier. Evade partner jump/grab commits without
retargeting combat away from the focus. Plans and boss tactics branch on this.
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

# Base boss health from ``$17EDC`` (before difficulty transforms). Used when a
# twin has no readable health word so equal-unknown twins stay comparable.
TWIN_BASE_HEALTH = 0x20

# Utility cap for twin_focus_bonus (AISpec §9.4b).
TWIN_FOCUS_BONUS_CAP = 0.18


class TwinComposition(Enum):
    """How many type-$58 bosses are still in the fight."""

    ABSENT = auto()
    PAIR = auto()
    SURVIVOR = auto()


# Normative pair plan: focus-fire one body with grounded punches.
# range_scale MUST stay ≤1.0 so stand-off stays inside measured punch boxes
# (scale>1 parked past strike_range and never pressed B). Never jump into
# grab commit; body-grab between two twins is still a trap.
_TWIN_PAIR_PLAN = CounterPlan(
    ThreatKind.JUMP_GRAB,
    range_scale=1.0,
    prefer_lane_delta=0.0,
    jump_bias=0.0,
    rear_bias=0.40,
    grab_bias=0.05,
    sidestep=True,
    no_jump=True,
    priority=2.9,
    note="twins pair — focus-fire lowest HP, grounded punches",
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


def twin_effective_hp(entity: MapEntity) -> int:
    """Comparable remaining HP for focus-fire ranking (lower = better focus).

    Defeated / lethal health words rank as ``0x7FFF`` so they never win as a
    damage focus. Unknown health uses the ROM base ``$20``.
    """

    if entity.is_defeated:
        return 0x7FFF
    if entity.health is None:
        return TWIN_BASE_HEALTH
    if entity.health >= 0x8000:
        return 0x7FFF
    return int(entity.health)


def twin_focus_bonus(
    entity: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
    *,
    my_seat: int = 1,
) -> float:
    """Extra target-utility when both twins are alive (0..``TWIN_FOCUS_BONUS_CAP``).

    **Doctrine:** finish one twin first. Score rewards the **lowest-HP** body;
    a unique wound gets a stronger lock so damage is not split. DANGEROUS
    phase and grab-role are *not* scored here — partner commits are handled by
    boss lane tactics, not by thrashing the combat target.

    ``my_seat`` is retained for call-site compatibility; pair focus-fire does
    not use sticky player-hunt bias.
    """

    del my_seat  # reserved; pair doctrine is HP-first, not who hunts whom
    if twin_composition(entities) is not TwinComposition.PAIR:
        return 0.0
    if not is_twin(entity) or entity.is_defeated:
        return 0.0

    twins = live_twins(entities)
    if len(twins) < 2:
        return 0.0

    entity_hp = twin_effective_hp(entity)
    other_hps = [
        twin_effective_hp(twin) for twin in twins if twin.slot != entity.slot
    ]
    if not other_hps:
        return 0.0
    min_other = min(other_hps)

    bonus = 0.0
    if entity_hp < min_other:
        # Unique lowest HP — commit hard to finishing this body.
        bonus = 0.18
    elif entity_hp == min_other:
        # Tied for lowest (typical full-health open): mild preference so
        # geometry / stickiness can break the tie without splitting fire.
        bonus = 0.10
    # Higher-HP twin gets 0 — never pull fire off a wounded focus.
    return min(TWIN_FOCUS_BONUS_CAP, bonus)


def twin_pair_should_stick(
    current: MapEntity,
    challenger: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
) -> bool:
    """True when pair focus-fire must keep ``current`` over ``challenger``.

    While both twins live and combat is locked on a living twin:

    * never switch to the other twin unless the challenger has **strictly
      lower** effective HP;
    * never switch to a non-projectile ordinary foe / other boss just because
      they are DANGEROUS (evade handles that);
    * allow projectile threats through (return False).
    """

    if twin_composition(entities) is not TwinComposition.PAIR:
        return False
    if not is_twin(current) or current.is_defeated:
        return False

    if is_twin(challenger) and not challenger.is_defeated:
        return twin_effective_hp(challenger) >= twin_effective_hp(current)

    if challenger.kind == "projectile":
        return False
    # Keep the focus twin over other combatants; pair fight is the phase gate.
    return True


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


def most_urgent_dangerous_twin(
    me: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
) -> MapEntity | None:
    """Nearest nearby twin in a DANGEROUS combat phase, if any.

    Used by boss tactics so a partner jump/grab is evaded on *that* twin's
    lane without retargeting combat focus.
    """

    from ..phases import is_dangerous

    dangerous = tuple(
        twin
        for twin in nearby_twins(me, entities)
        if is_dangerous(twin.combat_phase)
    )
    if not dangerous:
        return None
    return min(
        dangerous,
        key=lambda twin: (
            abs(float(twin.world_x) - float(me.world_x)),
            abs(float(twin.world_y) - float(me.world_y)),
        ),
    )
