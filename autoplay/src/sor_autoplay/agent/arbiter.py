"""Constraint/utility solver for fight, loot, and progress goals."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto

from ..world_map import MapEntity
from .fuzzy import falling
from .knowledge import Relation, TacticalKnowledgeGraph


class GoalKind(Enum):
    FIGHT = auto()
    LOOT = auto()
    PROGRESS = auto()


@dataclass(frozen=True, slots=True)
class GoalCandidate:
    kind: GoalKind
    utility: float
    target_slot: str | None
    explanation: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoalDecision:
    winner: GoalCandidate
    candidates: tuple[GoalCandidate, ...]


@dataclass(slots=True)
class GoalMemory:
    kind: GoalKind | None = None
    target_slot: str | None = None
    age: int = 0

    def clear(self) -> None:
        self.kind = None
        self.target_slot = None
        self.age = 0


_GOAL_PRIORITY = {
    GoalKind.FIGHT: 3,
    GoalKind.LOOT: 2,
    GoalKind.PROGRESS: 1,
}


def _loot_value(item: MapEntity, *, health_percent: float) -> tuple[float, str]:
    if item.kind == "weapon":
        return 0.58, "weapon"
    if item.family == "Health":
        need = falling(health_percent, 30.0, 90.0)
        return 0.35 + 0.60 * need, f"health need={need:.2f}"
    if item.family == "Life":
        return 0.92, "life"
    if item.family == "Special":
        return 0.78, "special"
    return 0.25, "score"


def solve_goal(
    graph: TacticalKnowledgeGraph,
    player: MapEntity,
    *,
    target: MapEntity | None,
    target_utility: float,
    item: MapEntity | None,
    pressure_urgency: float,
    health_percent: float,
    memory: GoalMemory,
) -> GoalDecision:
    """Enumerate legal goals and maximize fuzzy utility with hysteresis.

    This is a small mathematical solver: hard symbolic constraints establish
    feasibility, then a deterministic argmax selects the highest utility.
    """

    candidates: list[GoalCandidate] = []
    dangerous = graph.entities_with(Relation.DANGEROUS)
    bosses = tuple(
        entity
        for entity in graph.entities_with(Relation.BLOCKS_PROGRESS)
        if entity.kind == "boss"
    )

    if target is not None and graph.entity_has(target, Relation.REACHABLE):
        utility = min(1.0, target_utility + 0.25 * pressure_urgency)
        reasons = [f"target={target.label}", f"target={target_utility:.2f}"]
        if target.kind == "boss":
            utility = max(utility, 0.98)
            reasons.append("boss-blocks-progress")
        if graph.entity_has(target, Relation.DANGEROUS):
            utility = max(utility, 0.94)
            reasons.append("dangerous")
        if graph.has(target.slot, Relation.TARGETS_PLAYER, player.slot):
            utility = min(1.0, utility + 0.10)
            reasons.append("targets-player")
        candidates.append(
            GoalCandidate(GoalKind.FIGHT, utility, target.slot, tuple(reasons))
        )

    # Loot is infeasible while a boss blocks the arena or an immediate attack
    # is live.  Otherwise its value fades with travel cost and combat pressure.
    if item is not None and graph.entity_has(item, Relation.COLLECTIBLE):
        hard_threat = bool(bosses) or any(
            graph.entity_has(entity, Relation.NEAR_PLAYER) for entity in dangerous
        )
        if not hard_threat:
            base, value_reason = _loot_value(item, health_percent=health_percent)
            distance = math.hypot(
                item.map_x - player.map_x,
                item.map_y - player.map_y,
            )
            closeness = falling(distance, 8.0, 180.0)
            safety = 1.0 - pressure_urgency
            utility = 0.52 * base + 0.28 * closeness + 0.20 * safety
            candidates.append(
                GoalCandidate(
                    GoalKind.LOOT,
                    utility,
                    item.slot,
                    (
                        value_reason,
                        f"near={closeness:.2f}",
                        f"safe={safety:.2f}",
                    ),
                )
            )

    if not graph.entities_with(Relation.BLOCKS_PROGRESS):
        candidates.append(
            GoalCandidate(GoalKind.PROGRESS, 0.30, None, ("screen-clear",))
        )

    if not candidates:
        # A conservative fight placeholder prevents forward walking when a
        # reachable progression blocker exists but target extraction is stale.
        candidates.append(
            GoalCandidate(GoalKind.FIGHT, 0.50, None, ("blocker-without-target",))
        )

    # Persistence is a symbolic frame axiom: retain the same goal/target unless
    # new evidence makes a challenger materially better.
    adjusted: list[GoalCandidate] = []
    for candidate in candidates:
        utility = candidate.utility
        if candidate.kind == memory.kind and candidate.target_slot == memory.target_slot:
            utility = min(1.0, utility + 0.08)
        adjusted.append(
            GoalCandidate(
                candidate.kind,
                utility,
                candidate.target_slot,
                candidate.explanation,
            )
        )
    winner = max(
        adjusted,
        key=lambda candidate: (candidate.utility, _GOAL_PRIORITY[candidate.kind]),
    )
    if winner.kind == memory.kind and winner.target_slot == memory.target_slot:
        memory.age += 1
    else:
        memory.kind = winner.kind
        memory.target_slot = winner.target_slot
        memory.age = 1
    return GoalDecision(winner=winner, candidates=tuple(adjusted))
