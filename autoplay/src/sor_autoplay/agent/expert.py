"""Explainable combat expertise built on the generic inference engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from ..phases import CombatPhase
from ..world_map import SCREEN_WIDTH, MapEntity
from .inference import InferenceEngine, Rule
from .knowledge import Relation, TacticalKnowledgeGraph


BACK_THREAT_X = 160.0
BACK_THREAT_LANE = 36.0
BACK_DEADZONE = 8.0


# Crowd size that makes a vault→suplex throw preferable to front knees
# (suplex launches help clear multiple enemies).
CROWD_SUPLEX_THRESHOLD = 2


class TacticalFact(Enum):
    ENEMY_GRABBED = auto()
    FRONT_HOLD = auto()
    BACK_HOLD = auto()
    HOSTILE_BEHIND = auto()
    BACK_EXPOSED = auto()
    CROWD_PRESSURE = auto()
    GOAL_CROSSOVER_SUPLEX = auto()
    GOAL_SUPLEX = auto()


class TacticalGoal(Enum):
    NONE = auto()
    CROSSOVER_SUPLEX = auto()
    SUPLEX = auto()


@dataclass(frozen=True, slots=True)
class ExpertAssessment:
    facts: frozenset[TacticalFact]
    fired_rules: tuple[str, ...]
    goal: TacticalGoal
    held_slot: str | None = None
    rear_threat_slot: str | None = None


_GRAB_RULES = (
    Rule(
        name="infer-back-exposure",
        required=frozenset({TacticalFact.HOSTILE_BEHIND}),
        conclusions=frozenset({TacticalFact.BACK_EXPOSED}),
        salience=100,
    ),
    Rule(
        name="protect-back-with-crossover",
        required=frozenset(
            {
                TacticalFact.ENEMY_GRABBED,
                TacticalFact.FRONT_HOLD,
                TacticalFact.BACK_EXPOSED,
            }
        ),
        conclusions=frozenset({TacticalFact.GOAL_CROSSOVER_SUPLEX}),
        salience=90,
    ),
    Rule(
        name="crowd-suplex-setup",
        required=frozenset(
            {
                TacticalFact.ENEMY_GRABBED,
                TacticalFact.FRONT_HOLD,
                TacticalFact.CROWD_PRESSURE,
            }
        ),
        conclusions=frozenset({TacticalFact.GOAL_CROSSOVER_SUPLEX}),
        salience=85,
    ),
    Rule(
        name="finish-back-hold-with-suplex",
        required=frozenset(
            {TacticalFact.ENEMY_GRABBED, TacticalFact.BACK_HOLD}
        ),
        conclusions=frozenset({TacticalFact.GOAL_SUPLEX}),
        salience=80,
    ),
)


class CombatExpert:
    """Extract tactical facts and select an explainable combat goal."""

    def __init__(self) -> None:
        self.inference = InferenceEngine(_GRAB_RULES)

    def assess(
        self,
        me: MapEntity,
        entities: tuple[MapEntity, ...],
        *,
        held_enemy: MapEntity | None,
        graph: TacticalKnowledgeGraph | None = None,
        crowd: int = 0,
    ) -> ExpertAssessment:
        facts: set[TacticalFact] = set()
        if held_enemy is not None:
            facts.add(TacticalFact.ENEMY_GRABBED)
            if me.action_base == 0x60:
                facts.add(TacticalFact.FRONT_HOLD)
            elif me.action_base == 0x66:
                facts.add(TacticalFact.BACK_HOLD)
            if crowd >= CROWD_SUPLEX_THRESHOLD:
                facts.add(TacticalFact.CROWD_PRESSURE)

        rear = _nearest_hostile_behind(
            me,
            entities,
            held_enemy=held_enemy,
            graph=graph,
        )
        if rear is not None:
            facts.add(TacticalFact.HOSTILE_BEHIND)

        inferred = self.inference.infer(facts)
        if TacticalFact.GOAL_CROSSOVER_SUPLEX in inferred.facts:
            goal = TacticalGoal.CROSSOVER_SUPLEX
        elif TacticalFact.GOAL_SUPLEX in inferred.facts:
            goal = TacticalGoal.SUPLEX
        else:
            goal = TacticalGoal.NONE
        return ExpertAssessment(
            facts=inferred.facts,
            fired_rules=inferred.fired_rules,
            goal=goal,
            held_slot=None if held_enemy is None else held_enemy.slot,
            rear_threat_slot=None if rear is None else rear.slot,
        )


def _nearest_hostile_behind(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    held_enemy: MapEntity | None,
    graph: TacticalKnowledgeGraph | None = None,
) -> MapEntity | None:
    facing_left = bool(me.action_state & 0x01)
    best: MapEntity | None = None
    best_distance = float("inf")
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if graph is not None and not graph.entity_has(entity, Relation.REACHABLE):
            continue
        if held_enemy is not None and entity.slot == held_enemy.slot:
            continue
        if entity.combat_phase in (
            CombatPhase.DEATH,
            CombatPhase.SCRIPTED,
            CombatPhase.GRABBED,
        ):
            continue
        if entity.is_defeated:
            continue
        if not 0.0 <= entity.map_x <= float(SCREEN_WIDTH):
            continue
        dx = entity.map_x - me.map_x
        behind = dx > BACK_DEADZONE if facing_left else dx < -BACK_DEADZONE
        if not behind:
            continue
        if abs(dx) > BACK_THREAT_X:
            continue
        lane_distance = abs(entity.map_y - me.map_y)
        if lane_distance > BACK_THREAT_LANE:
            continue
        distance = abs(dx) + lane_distance * 0.5
        if distance < best_distance:
            best = entity
            best_distance = distance
    return best


DEFAULT_COMBAT_EXPERT = CombatExpert()
