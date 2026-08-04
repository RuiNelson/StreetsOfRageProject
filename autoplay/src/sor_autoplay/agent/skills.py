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
from . import twins as twins_ai
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
        return Intent(note="hurt")

    # Leaving exclusive modes: drop enemy-grab commitment so FREE can proceed.
    if commitment.name == EnemyGrabEscapeSkill.name:
        commitment.clear(ctx)

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


class TwinFightSkill:
    """Exclusive seat ownership for the Onihime/Yasha pair (AISpec §9.4b).

    The free-decision ladder has many independent movement controllers, and a
    live twin pair triggers most of them at once. Measured across nine live
    Round-5 episodes, they preempted each other every other decision — 129
    approaches against 82 pressure sidesteps — so the seat never closed to
    punch range and landed **zero** melee hits in hundreds of decisions.

    This skill takes the whole fight instead. Measured ordering:

    1. ROM gate denial (armed leap escape, `$159F8` throw-band exit)
    2. Precise hits: rear band → B+C; punch band + facing → B
    3. Contact range (≤22 px): back-turn + B+C — the punch dead zone; back
       attack's box is body-centred and is the only move that converts here
    4. Feign when she is behind: lane only, never turn toward her (`$15C72`)
    5. Hold ground when she is far — chasing measured strictly worse than
       standing still (0 dealt / 112 taken vs 6 / 80). The twins walk and
       jump onto us; we do not hunt them.

    Attack is the default whenever a body is close enough to hit. A prior
    conjunction of (predicted landing) ∧ (frames ≤ 8) ∧ (under the body)
    threw 0–4 attacks per 700 decisions and did no damage; a scripted B+C
    mash did 6. An agent that does not attack cannot win.

    Grabs are deliberately left to the hold tree: once a twin is held, the
    knee/throw skill owns the seat.
    """

    name = "twin-fight"

    # Back attack box is X -7..+3; add her body half-width. Beyond this it
    # whiffs (12 live swings at up to 96 px dealt nothing). Inside it the
    # punch is also dead (measured miss under 28 px), so B+C is the only move.
    REAR_CONTACT_PX = 22.0

    def valid(self, ctx: DecisionContext) -> bool:
        me = ctx.me
        if me is None or ctx.mode != PlayerMode.FREE:
            return False
        if me.is_grabbing or me.is_holding_weapon:
            return False  # hold tree owns knee / throw
        return bool(twins_ai.live_twins(ctx.snapshot.world_map.entities))

    def cancel(self, ctx: DecisionContext) -> None:
        ctx.walk.clear()

    def step(self, ctx: DecisionContext) -> Intent | None:
        me = ctx.me
        if me is None:
            return None
        entities = ctx.snapshot.world_map.entities
        live = twins_ai.live_twins(entities)
        doctrine = twins_ai.scene(me, entities)
        if doctrine.focus is None or not live:
            return None
        profile = ctx.profile
        level_index = ctx.snapshot.level_index

        # 1) Gate denial outranks damage: a landed throw costs ~40% of the bar.
        if doctrine.retreat_from is not None:
            goal = twins_ai.retreat_goal(
                me, doctrine.retreat_from, level_index=level_index, entities=entities
            )
            return self._move(me, goal, "twin skill leap escape")
        if doctrine.lane_unsafe:
            lane = twins_ai.safe_lane(me, entities, level_index=level_index)
            return self._move(
                me, (float(me.world_x), lane), "twin skill leave throw band"
            )

        # Keep the combo alive. During normal attack action `$18` the ROM
        # accepts the next hit while `+$58` bit 5 is clear; waiting for idle
        # drops the chain and was ~15% of all decisions in live episodes.
        if me.action_base == 0x18 and not (me.action_flags & 0x20):
            return Intent(attack=True, note="twin skill combo")

        if not combat.player_can_start_ground_action(me):
            return Intent(note="twin skill wait anim")

        face_right = not combat.player_facing_left(me)

        # 2) Precise hit windows first — weapon matches the side she is on.
        # A back attack hits *behind* the player; firing it at a twin in front
        # swings at empty air.
        for twin in live:
            if combat.can_rear_hit(me, twin, profile, face_right=face_right):
                return Intent(rear_attack=True, note=f"twin skill rear {twin.label}")
        for twin in live:
            if twins_ai.can_strike(me, twin, profile) and combat.facing_toward(
                me, twin
            ):
                return Intent(attack=True, note=f"twin skill punch {twin.label}")

        nearest = min(live, key=lambda t: abs(float(t.world_x) - float(me.world_x)))
        gap = abs(float(nearest.world_x) - float(me.world_x))
        she_is_right = float(nearest.world_x) > float(me.world_x)
        behind = she_is_right == combat.player_facing_left(me)
        lane_up = float(nearest.world_y) < float(me.world_y) - 4.0
        lane_down = float(nearest.world_y) > float(me.world_y) + 4.0

        # 3) Contact / dead zone: back-turn + B+C. Direction turns our back to
        # her before the button so the rear box covers her and `$15C72` stays
        # closed (it needs us facing and closing).
        if gap <= self.REAR_CONTACT_PX:
            return Intent(
                rear_attack=True,
                left=she_is_right,
                right=not she_is_right,
                note=f"twin skill back-turn attack {nearest.label}",
            )

        # 4) Body on our back outside contact: hold the feign, lane only.
        if behind:
            return Intent(
                up=lane_up,
                down=lane_down,
                note=f"twin skill let her come {nearest.label}",
            )

        # 5) In front and outside the punch band: hold ground. Chasing on X
        # measured 0 dealt / 112 taken against 6 / 80 for standing still; the
        # pair walks and jump-kicks onto us under its own AI. Only track lane
        # so a jump landing shares our depth.
        _, hi = twins_ai.punch_band(profile)
        if gap > hi:
            return Intent(
                up=lane_up,
                down=lane_down,
                note=f"twin skill hold {nearest.label}",
            )

        # 6) Inside the punch band but not cleanly hittable (facing/lane).
        # Face her and match depth — do not walk past the outer edge into
        # the dead zone.
        return Intent(
            left=not she_is_right,
            right=she_is_right,
            up=lane_up,
            down=lane_down,
            note=f"twin skill line up {nearest.label}",
        )

    @staticmethod
    def _move(me: MapEntity, goal: tuple[float, float], note: str) -> Intent:
        """Direct D-pad steering — deliberately not the walk latch.

        The latch is refreshed by other controllers and was a source of the
        approach/evade oscillation this skill exists to end.
        """

        gx, gy = goal
        dx = gx - float(me.world_x)
        dy = gy - float(me.world_y)
        return Intent(
            left=dx < -3.0,
            right=dx > 3.0,
            up=dy < -3.0,
            down=dy > 3.0,
            note=note,
        )


def try_twin_fight(ctx: DecisionContext) -> Intent | None:
    """Own the seat while any type-$58 boss is alive."""

    assert ctx.seat.commitment is not None
    commitment = ctx.seat.commitment
    skill = TwinFightSkill()
    if not skill.valid(ctx):
        if commitment.name == TwinFightSkill.name:
            commitment.clear(ctx)
        return None
    return _continue_or_start(commitment, skill, ctx)
