"""Multi-frame skill protocol and the first ROM-guarded commitments.

A skill owns controller decisions across observations until its preconditions
fail or it returns ``None`` (done). The commitment runtime is the single
multi-frame ownership slot per seat; walk/nav/grab memories remain skill-local
helpers until more free-mode tactics are lifted into skills.

Hard ROM guards stay inside each skill (and the evaluator). Learning may later
choose *which* legal skill to start, not invent illegal button edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..world_map import MapEntity
from . import combat, grabs
from .context import DecisionContext, PlayerMode
from .controls import Intent
from .expert import DEFAULT_COMBAT_EXPERT, TacticalGoal


@runtime_checkable
class Skill(Protocol):
    """Multi-frame tactical unit: valid → step until done."""

    name: str

    def valid(self, ctx: DecisionContext) -> bool:
        """True while this skill may keep owning the seat."""

        ...

    def step(self, ctx: DecisionContext) -> Intent | None:
        """Emit an intent, or ``None`` when the skill has finished cleanly."""

        ...

    def cancel(self, ctx: DecisionContext) -> None:
        """Release skill-local ROM planners / latches when preconditions die."""

        ...


@dataclass(slots=True)
class Commitment:
    """At most one active multi-frame skill per seat."""

    skill: Skill | None = None

    @property
    def active(self) -> bool:
        return self.skill is not None

    @property
    def name(self) -> str:
        return "" if self.skill is None else self.skill.name

    def clear(self, ctx: DecisionContext | None = None) -> None:
        if self.skill is not None and ctx is not None:
            self.skill.cancel(ctx)
        self.skill = None

    def step(self, ctx: DecisionContext) -> Intent | None:
        """Continue the active skill, or clear it when invalid / finished."""

        if self.skill is None:
            return None
        if not self.skill.valid(ctx):
            self.skill.cancel(ctx)
            self.skill = None
            return None
        intent = self.skill.step(ctx)
        if intent is None:
            self.skill.cancel(ctx)
            self.skill = None
            return None
        return intent

    def start(self, skill: Skill, ctx: DecisionContext) -> Intent | None:
        """Replace any prior skill and take the first step."""

        if self.skill is not None:
            self.skill.cancel(ctx)
        self.skill = skill
        return self.step(ctx)


# ---------------------------------------------------------------------------
# Grab-family skills (migration step 1)
# ---------------------------------------------------------------------------


class EnemyGrabEscapeSkill:
    """Own player actions $78-$7E: C to cross, then B in the counter window."""

    name = "enemy_grab_escape"

    def valid(self, ctx: DecisionContext) -> bool:
        me = ctx.me
        if me is None:
            return False
        return me.action_base in grabs.ENEMY_HOLD_ACTIONS

    def step(self, ctx: DecisionContext) -> Intent | None:
        me = ctx.me
        if me is None:
            return None
        ctx.walk.clear()
        ctx.planner.reset()
        ctx.goal_memory.clear()
        ctx.grab_mem.reset()
        return grabs.decide_enemy_grab_escape(
            me,
            ctx.enemy_grab_escape_mem,
            tick=ctx.tick,
        )

    def cancel(self, ctx: DecisionContext) -> None:
        ctx.enemy_grab_escape_mem.reset()


class CrossoverSuplexSkill:
    """Expert-backed plan: front hold + hostile behind → C → wait → B suplex.

    Wraps ``AutoPlanner`` so the existing ROM-confirmed state machine remains
    the source of truth; this skill is the commitment ownership shell.
    """

    name = "crossover_suplex"

    def valid(self, ctx: DecisionContext) -> bool:
        if ctx.me is None:
            return False
        if ctx.planner.active:
            return True
        return self._assessment_wants_plan(ctx)

    def step(self, ctx: DecisionContext) -> Intent | None:
        me = ctx.me
        if me is None:
            return None
        ctx.ensure_perception()
        gctx = grabs.context_from_player(
            me,
            ctx.snapshot.world_map.entities,
            player_index=ctx.player_index,
        )
        held_foe = grabs.held_enemy_entity(me, ctx.snapshot.world_map.entities)
        crowd = ctx.press.enemy_count if ctx.press is not None else 0
        assessment = DEFAULT_COMBAT_EXPERT.assess(
            me,
            ctx.snapshot.world_map.entities,
            held_enemy=held_foe if gctx.enemy_grab else None,
            graph=ctx.graph,
            crowd=crowd,
        )
        intent = ctx.planner.decide(assessment, me, gctx, held_foe)
        if intent is not None:
            ctx.walk.clear()
            ctx.grab_mem.reset()
        return intent

    def cancel(self, ctx: DecisionContext) -> None:
        ctx.planner.reset()

    @staticmethod
    def _assessment_wants_plan(ctx: DecisionContext) -> bool:
        me = ctx.me
        if me is None:
            return False
        ctx.ensure_perception()
        gctx = grabs.context_from_player(
            me,
            ctx.snapshot.world_map.entities,
            player_index=ctx.player_index,
        )
        held_foe = grabs.held_enemy_entity(me, ctx.snapshot.world_map.entities)
        if held_foe is None or not gctx.enemy_grab:
            return False
        crowd = ctx.press.enemy_count if ctx.press is not None else 0
        assessment = DEFAULT_COMBAT_EXPERT.assess(
            me,
            ctx.snapshot.world_map.entities,
            held_enemy=held_foe,
            graph=ctx.graph,
            crowd=crowd,
        )
        if assessment.goal == TacticalGoal.CROSSOVER_SUPLEX and me.action_base == 0x60:
            return True
        if assessment.goal == TacticalGoal.SUPLEX and me.action_base == 0x66:
            return True
        return False


class HoldResolveSkill:
    """Ordinary hold / weapon tree when not in a crossover-suplex plan."""

    name = "hold_resolve"

    def valid(self, ctx: DecisionContext) -> bool:
        me = ctx.me
        if me is None:
            return False
        if me.action_base in grabs.GRAB_ANIMATION_ACTIONS:
            # Closed animations: skill may hold ownership with empty input.
            return True
        gctx = grabs.context_from_player(
            me,
            ctx.snapshot.world_map.entities,
            player_index=ctx.player_index,
        )
        return gctx.holding

    def step(self, ctx: DecisionContext) -> Intent | None:
        me = ctx.me
        if me is None:
            return None
        ctx.ensure_perception()
        assert ctx.graph is not None and ctx.press is not None
        gctx = grabs.context_from_player(
            me,
            ctx.snapshot.world_map.entities,
            player_index=ctx.player_index,
        )
        held_foe = grabs.held_enemy_entity(me, ctx.snapshot.world_map.entities)
        foe_near = held_foe or combat.nearest_foe(
            me,
            ctx.snapshot.world_map.entities,
            graph=ctx.graph,
        )
        if me.action_base in grabs.GRAB_ANIMATION_ACTIONS and not gctx.holding:
            ctx.walk.clear()
            return Intent(note=f"grab anim ${me.action_state:02X}")
        intent = grabs.decide_held(
            me,
            gctx,
            ctx.grab_mem,
            tick=ctx.tick,
            foe=foe_near,
            progress_right=ctx.advice.progress_right,
            crowd=ctx.press.enemy_count,
            profile=ctx.profile,
            ally=ctx.coop.partner,
            both_agents=ctx.both_agents,
        )
        if intent is not None:
            # Keep walk ownership empty for button edges; release-grab walks are
            # pure D-pad and still clear sticky nav so we do not fight it.
            ctx.walk.clear()
        return intent

    def cancel(self, ctx: DecisionContext) -> None:
        ctx.grab_mem.reset()


def _continue_or_start(commitment: Commitment, skill: Skill, ctx: DecisionContext) -> Intent | None:
    """Step an already-active same-named skill; otherwise start fresh.

    Restarting every tick would cancel skill-local latches (for example the
    enemy-grab retry window) and re-fire edges forever.
    """

    if commitment.name == skill.name and commitment.active:
        return commitment.step(ctx)
    return commitment.start(skill, ctx)


def try_start_mode_skill(ctx: DecisionContext) -> Intent | None:
    """Start the exclusive skill for modes that always own the seat.

    Returns an intent when a skill took ownership, else ``None``.
    """

    assert ctx.seat.commitment is not None
    commitment = ctx.seat.commitment

    if ctx.mode == PlayerMode.ENEMY_HELD:
        return _continue_or_start(commitment, EnemyGrabEscapeSkill(), ctx)

    if ctx.mode == PlayerMode.HURT:
        commitment.clear(ctx)
        ctx.walk.clear()
        ctx.planner.reset()
        ctx.goal_memory.clear()
        ctx.grab_mem.reset()
        me = ctx.me
        if me is None:
            return Intent(note="hurt")
        return grabs.decide_hurt_or_throw_reaction(
            me,
            ctx.seat.throw_land_tech,
            tick=ctx.tick,
        )

    # Leaving exclusive modes: drop enemy-grab commitment so FREE can proceed.
    if commitment.name == EnemyGrabEscapeSkill.name:
        commitment.clear(ctx)
    # Clear tech retry when no longer in a locked reaction.
    ctx.seat.throw_land_tech.reset()

    return None


def try_crossover_suplex(ctx: DecisionContext) -> Intent | None:
    """Expert plan before police and ordinary hold (historical priority)."""

    assert ctx.seat.commitment is not None
    commitment = ctx.seat.commitment
    if ctx.me is None:
        return None
    crossover = CrossoverSuplexSkill()
    if not crossover.valid(ctx):
        if commitment.name == crossover.name:
            commitment.clear(ctx)
        return None
    return _continue_or_start(commitment, crossover, ctx)


def try_hold_resolve(ctx: DecisionContext) -> Intent | None:
    """Ordinary hold / weapon tree and closed grab-animation lockout.

    Runs after police special so a hold does not block an eligible A edge.
    """

    assert ctx.seat.commitment is not None
    commitment = ctx.seat.commitment
    if ctx.me is None:
        return None
    # Do not interrupt an active crossover-suplex commitment.
    if commitment.name == CrossoverSuplexSkill.name and commitment.active:
        intent = commitment.step(ctx)
        if intent is not None:
            return intent
    hold = HoldResolveSkill()
    if not hold.valid(ctx):
        if commitment.name == hold.name:
            commitment.clear(ctx)
        return None
    return _continue_or_start(commitment, hold, ctx)
