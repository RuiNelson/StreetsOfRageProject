"""Persistent execution plans for multi-step controller tactics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from ..world_map import MapEntity
from .controls import Intent
from .expert import ExpertAssessment, TacticalGoal
from .grabs import GrabContext


CROSSOVER_ACTIONS = frozenset({0x76, 0x80})
FRONT_HOLD_ACTION = 0x60
BACK_HOLD_ACTION = 0x66
SUPLEX_ACTION = 0x68
PLAN_TIMEOUT_TICKS = 24
LOST_HOLD_TOLERANCE = 2


class PlanKind(Enum):
    CROSSOVER_SUPLEX = auto()
    SUPLEX = auto()


class PlanPhase(Enum):
    ISSUE_CROSSOVER = auto()
    WAIT_CROSSOVER = auto()
    WAIT_SUPLEX_FINISH = auto()


@dataclass(slots=True)
class AutoPlanner:
    """Turn an inferred tactical goal into guarded actions across observations."""

    kind: PlanKind | None = None
    phase: PlanPhase | None = None
    target_slot: str | None = None
    age: int = 0
    lost_hold_ticks: int = 0
    saw_crossover: bool = False
    saw_suplex: bool = False

    @property
    def active(self) -> bool:
        return self.kind is not None

    def reset(self) -> None:
        self.kind = None
        self.phase = None
        self.target_slot = None
        self.age = 0
        self.lost_hold_ticks = 0
        self.saw_crossover = False
        self.saw_suplex = False

    def decide(
        self,
        assessment: ExpertAssessment,
        me: MapEntity,
        grab: GrabContext,
        held_enemy: MapEntity | None,
    ) -> Intent | None:
        if not self.active:
            self._start(assessment, me, held_enemy)
        if not self.active:
            return None

        self.age += 1
        if self.age > PLAN_TIMEOUT_TICKS:
            self.reset()
            return None

        # Once B has been accepted, the held-enemy links may disappear before
        # the throw animation finishes. Keep ownership from the player's ROM
        # action instead of cancelling on that expected observation change.
        if self.phase == PlanPhase.WAIT_SUPLEX_FINISH:
            if me.action_base == SUPLEX_ACTION:
                self.saw_suplex = True
                return Intent(note=f"plan suplex active {self.target_slot}")
            if self.saw_suplex:
                self.reset()
                return None

        target_present = (
            grab.enemy_grab
            and held_enemy is not None
            and held_enemy.slot == self.target_slot
        )
        if not target_present:
            self.lost_hold_ticks += 1
            if self.lost_hold_ticks >= LOST_HOLD_TOLERANCE:
                self.reset()
                return None
            return Intent(note="plan hold observation gap")
        self.lost_hold_ticks = 0

        if self.phase == PlanPhase.ISSUE_CROSSOVER:
            if me.action_base != FRONT_HOLD_ACTION:
                self.reset()
                return None
            self.phase = PlanPhase.WAIT_CROSSOVER
            return Intent(
                jump=True,
                note=(
                    f"plan crossover {held_enemy.label} "
                    f"shield {assessment.rear_threat_slot or 'rear'}"
                ),
            )

        if self.phase == PlanPhase.WAIT_CROSSOVER:
            if me.action_base in CROSSOVER_ACTIONS:
                self.saw_crossover = True
                return Intent(note=f"plan vault {held_enemy.label}")
            if self.saw_crossover and me.action_base == BACK_HOLD_ACTION:
                self.phase = PlanPhase.WAIT_SUPLEX_FINISH
                return Intent(attack=True, note=f"plan suplex {held_enemy.label}")
            return Intent(note=f"plan await crossover {held_enemy.label}")

        if self.phase == PlanPhase.WAIT_SUPLEX_FINISH:
            return Intent(note=f"plan await suplex {held_enemy.label}")

        self.reset()
        return None

    def _start(
        self,
        assessment: ExpertAssessment,
        me: MapEntity,
        held_enemy: MapEntity | None,
    ) -> None:
        if held_enemy is None:
            return
        if (
            assessment.goal == TacticalGoal.CROSSOVER_SUPLEX
            and me.action_base == FRONT_HOLD_ACTION
        ):
            self.kind = PlanKind.CROSSOVER_SUPLEX
            self.phase = PlanPhase.ISSUE_CROSSOVER
        elif assessment.goal == TacticalGoal.SUPLEX and me.action_base == BACK_HOLD_ACTION:
            self.kind = PlanKind.SUPLEX
            self.phase = PlanPhase.WAIT_SUPLEX_FINISH
        else:
            return
        self.target_slot = held_enemy.slot
        self.age = 0
        self.lost_hold_ticks = 0
        self.saw_crossover = False
        self.saw_suplex = False

        # A pre-existing back hold needs no cross-over; emit its B edge from
        # ``decide`` immediately by presenting it as the completed vault step.
        if self.kind == PlanKind.SUPLEX:
            self.phase = PlanPhase.WAIT_CROSSOVER
            self.saw_crossover = True
