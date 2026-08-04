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
from . import twins as twins_ai
from .enemies import CounterPlan, ThreatKind


TWIN_TYPE = 0x58
TWIN_FAMILY = "Onihime/Yasha"

# Geometry used by twin bracket / isolation helpers (matches bosses.py).
TWIN_NEAR_X = 150.0
TWIN_NEAR_Y = 36.0

# Base boss health from ``$17EDC`` (before difficulty transforms). Used when a
# twin has no readable health word so equal-unknown twins stay comparable.
TWIN_BASE_HEALTH = 0x20

# Equal-HP tie-break weight for the reachable body. Large enough to beat
# target hysteresis, which otherwise pinned the seat to a body that had
# walked away.
TWIN_REACH_TIEBREAK = 0.12

# A body this close is worth switching to at equal HP: it is inside every
# character's measured punch box (54-68 px).
TWIN_REACHABLE_DX = 56.0

# Utility cap for twin_focus_bonus (AISpec §9.4b).
TWIN_FOCUS_BONUS_CAP = 0.18


class TwinComposition(Enum):
    """How many type-$58 bosses are still in the fight."""

    ABSENT = auto()
    PAIR = auto()
    SURVIVOR = auto()


# Pair plan: focus-fire lowest HP with the **full** attack toolkit.
# range_scale ≤1.0 keeps stand-off inside measured punch boxes.
# jump/grab/rear enabled — a prior no_jump + grab_bias≈0 plan never mixed.
# no_jump: measured live — 6 jump kicks against the twins landed 0 damage
# while the solver kept selecting them whenever both bodies lined up.
# jump_bias stays < 0.5: coplanar grounded punches are the damage engine
# (they also deny $159F8), and >= 0.5 parked the stand point at jump-kick
# range, out of punch reach. A live handoff scored 0 melee damage there.
# grab_bias stays below 0.5 so punches still win in-range (Nora-level grab
# would starve B punches); back-shield and close walk still elevate grabs.
_TWIN_PAIR_PLAN = CounterPlan(
    ThreatKind.JUMP_GRAB,
    range_scale=1.0,
    prefer_lane_delta=0.0,
    jump_bias=0.15,
    rear_bias=0.55,
    grab_bias=0.35,
    sidestep=True,
    no_jump=True,
    priority=2.9,
    note="twins pair — focus-fire full mix (punch/jump/grab/rear)",
)

# Survivor (unpaired): drop pair constraints; promote grabs + pressure.
_TWIN_SURVIVOR_PLAN = CounterPlan(
    ThreatKind.JUMP_GRAB,
    range_scale=1.0,
    prefer_lane_delta=0.0,
    jump_bias=0.15,
    rear_bias=0.45,
    grab_bias=0.55,
    sidestep=True,
    no_jump=True,
    priority=2.6,
    note="twin survivor — full pressure (grab/punch/jump)",
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
        # Equal HP is the whole opening of the fight, so this tie decides where
        # the damage goes. Expert play alternates onto whichever body is in
        # front rather than chasing one: a mode-based tie-break (grab twin
        # first) is ROM-correct in theory but measured worse — the seat walked
        # past a twin standing in punch range to chase a distant focus and
        # landed nothing in six live episodes. Make reachability decisive.
        bonus = 0.10
        me = next(
            (
                actor
                for actor in entities
                if actor.kind == "player" and actor.slot.upper() == f"P{my_seat}"
            ),
            None,
        )
        if me is not None:
            here = abs(float(entity.world_x) - float(me.world_x))
            nearest = min(
                abs(float(twin.world_x) - float(me.world_x)) for twin in twins
            )
            bonus += TWIN_REACH_TIEBREAK if here <= nearest else -TWIN_REACH_TIEBREAK
    # Higher-HP twin gets 0 — never pull fire off a wounded focus.
    return min(TWIN_FOCUS_BONUS_CAP, bonus)


def twin_pair_should_stick(
    current: MapEntity,
    challenger: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
    me: MapEntity | None = None,
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
        if twin_effective_hp(challenger) < twin_effective_hp(current):
            return False
        # Equal HP is the whole fight (both open at $20), and pure stickiness
        # locked the seat onto a body that had walked away while its partner
        # stood in punch range. Live: 53 decisions inside punch geometry, zero
        # attacks. Release the lock for a challenger that is reachable now and
        # clearly closer than the current focus.
        if me is not None:
            here = abs(float(challenger.world_x) - float(me.world_x))
            there = abs(float(current.world_x) - float(me.world_x))
            if here <= TWIN_REACHABLE_DX and there > here * 2.0:
                return False
        return True

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


# A committed twin beyond this X cannot connect on the decision we are about
# to take, so evading it only cancels our own approach. Measured: the 150 px
# window fired 82 sidesteps against 129 approaches and the seat never closed
# to punch range at all.
TWIN_PRESSURE_REACH_X = 64.0
TWIN_PRESSURE_REACH_Y = 16.0


def most_urgent_dangerous_twin(
    me: MapEntity,
    entities: tuple[MapEntity, ...] | list[MapEntity],
    *,
    max_dx: float = TWIN_PRESSURE_REACH_X,
    max_dy: float = TWIN_PRESSURE_REACH_Y,
) -> MapEntity | None:
    """Nearest nearby twin in a DANGEROUS combat phase, if any.

    Used by boss tactics so a partner jump/grab is evaded on *that* twin's
    lane without retargeting combat focus.
    """

    from ..phases import is_dangerous

    dangerous = tuple(
        twin
        for twin in nearby_twins(me, entities, max_dx=max_dx, max_dy=max_dy)
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
