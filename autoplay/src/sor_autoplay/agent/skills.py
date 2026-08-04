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

    This skill takes the whole fight instead, in one fixed order:

    1. ROM gate denial (armed leap escape, `$159F8` throw-band exit)
    2. back attack when a twin is inside the rear band
    3. feign — hold the back turned to a twin closing from behind, because
       `$15C72` needs us facing and closing (the speedrun tactic)
    4. punch when coplanar, in range and facing
    5. turn to face, when nothing is behind us
    6. converge on coplanar strike distance of the *reachable* body

    Grabs are deliberately left to the hold tree: once a twin is held, the
    knee/throw skill owns the seat.
    """

    name = "twin-fight"

    # One decision is four frames. A twin closing at chase speed covers real
    # ground in that window, so a range check made *now* describes where the
    # body already is, not where the punch will land. Lead it by one decision.
    LEAD_DECISIONS = 1.0
    # Cap the extrapolation so a leaping body cannot pull the swing wildly.
    MAX_LEAD_PX = 26.0

    def __init__(self) -> None:
        # slot -> last observed (x, y). The commitment keeps one instance
        # alive across decisions, so this is a real velocity estimate.
        self._last: dict[str, tuple[float, float]] = {}

    def _velocity(self, twin: MapEntity) -> tuple[float, float]:
        """Per-decision movement of this body, from the previous observation."""

        now = (float(twin.world_x), float(twin.world_y))
        prev = self._last.get(twin.slot)
        if prev is None:
            return 0.0, 0.0
        vx = max(-self.MAX_LEAD_PX, min(self.MAX_LEAD_PX, now[0] - prev[0]))
        vy = max(-self.MAX_LEAD_PX, min(self.MAX_LEAD_PX, now[1] - prev[1]))
        return vx, vy

    def _will_be_in_range(
        self,
        me: MapEntity,
        twin: MapEntity,
        profile,
        vel: dict[str, tuple[float, float]],
    ) -> bool:
        """True when this body arrives inside the strike box next decision.

        Swinging on the prediction is the whole point: reacting to a body that
        is already in range means the ROM applies B after it has moved on.
        """

        vx, vy = vel.get(twin.slot, (0.0, 0.0))
        dx = abs(float(twin.world_x) + vx * self.LEAD_DECISIONS - float(me.world_x))
        dy = abs(float(twin.world_y) + vy * self.LEAD_DECISIONS - float(me.world_y))
        lo, hi = twins_ai.punch_band(profile)
        return lo <= dx <= hi and dy <= combat.LANE_HIT_HALF

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
        # Estimate velocity against the previous decision, then re-baseline.
        vel = {twin.slot: self._velocity(twin) for twin in live}
        self._last = {
            twin.slot: (float(twin.world_x), float(twin.world_y)) for twin in live
        }
        doctrine = twins_ai.scene(me, entities)
        if doctrine.focus is None:
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

        # 2) Back attack: the pair's own geometry hands us this constantly.
        for twin in twins_ai.live_twins(entities):
            if twins_ai.is_airborne(twin, me):
                continue
            if combat.can_rear_hit(me, twin, profile, face_right=face_right):
                return Intent(rear_attack=True, note=f"twin skill rear {twin.label}")

        # 3) Feign: never turn to meet a twin closing on our back.
        bait = twins_ai.rear_bait_target(
            me, entities, face_right=face_right, rear_min=profile.rear_range_max
        )

        # Attack whichever body is grounded and legal right now. The pair
        # alternates jump arcs constantly, so waiting for one chosen focus to
        # land forfeits the openings the other one is handing us.
        for twin in twins_ai.live_twins(entities):
            if twins_ai.is_airborne(twin, me):
                continue
            if not combat.facing_toward(me, twin):
                continue
            if twins_ai.can_strike(me, twin, profile):
                return Intent(attack=True, note=f"twin skill punch {twin.label}")
            if self._will_be_in_range(me, twin, profile, vel):
                return Intent(
                    attack=True, note=f"twin skill lead {twin.label}"
                )

        # A body that has landed *on top of us* is inside the punch dead zone
        # (measured: no damage under 28 px). Swinging there is the whiff that
        # produced hundreds of attack decisions and zero damage. Step back into
        # the band instead — this is also how we leave its grab range.
        crowding = [
            twin
            for twin in twins_ai.live_twins(entities)
            if not twins_ai.is_airborne(twin, me) and twins_ai.too_close(me, twin)
        ]
        if crowding:
            twin = min(
                crowding, key=lambda t: abs(float(t.world_x) - float(me.world_x))
            )
            lo, _ = twins_ai.punch_band(profile)
            side = -1.0 if float(twin.world_x) > float(me.world_x) else 1.0
            goal_x = float(twin.world_x) + side * (lo + 8.0)
            return self._move(
                me, (goal_x, float(me.world_y)), f"twin skill reset {twin.label}"
            )

        focus = doctrine.focus
        if twins_ai.is_airborne(focus, me):
            grounded = [
                twin
                for twin in twins_ai.live_twins(entities)
                if not twins_ai.is_airborne(twin, me)
            ]
            if grounded:
                focus = min(
                    grounded,
                    key=lambda twin: abs(float(twin.world_x) - float(me.world_x)),
                )
        dx = float(focus.world_x) - float(me.world_x)
        dy = float(focus.world_y) - float(me.world_y)

        # 4) Punch a grounded body only. The pair spends much of the fight in
        # jump arcs, and a punch at an airborne twin passes under it.
        grounded_focus = not twins_ai.is_airborne(focus, me)
        if grounded_focus and twins_ai.can_strike(me, focus, profile):
            return Intent(attack=True, note=f"twin skill punch {focus.label}")

        # Its landing is the ROM's own punish window: after the jump attack
        # lands, `$15ABA` resets `+$67 = 0, +$30 = 1` and idles ~10 ticks.
        if not grounded_focus and combat.can_punch(
            me, focus, profile, require_facing=False
        ):
            return Intent(
                left=dx < 0, right=dx > 0, note=f"twin skill await land {focus.label}"
            )

        if bait is not None:
            return Intent(note=f"twin skill feign {bait.label}")

        # 5) In range but facing away (and nothing behind): turn.
        if combat.can_punch(me, focus, profile, require_facing=False):
            return Intent(
                left=dx < 0, right=dx > 0, note=f"twin skill face {focus.label}"
            )

        # 6) Converge — but never into a live commit. `$15A64` arms the jump
        # attack at X < `$60` with no other condition, so walking at a
        # committed body is the one approach the gates cannot protect. Hold
        # spacing until it resolves (measured: engaging through commits cost 9
        # deaths in a single 700-decision episode).
        for threat in doctrine.threats:
            if threat.committed and threat.dx < twins_ai.JUMP_ATTACK_X:
                lane = twins_ai.safe_lane(
                    me, entities, level_index=level_index, prefer=float(me.world_y)
                )
                side = -1.0 if float(threat.twin.world_x) > float(me.world_x) else 1.0
                hold_x = float(me.world_x) + side * 12.0
                return self._move(
                    me, (hold_x, lane), f"twin skill space {threat.twin.label}"
                )

        engage = max(20.0, profile.strike_range - 8.0)
        goal_x = float(focus.world_x) - (engage if dx > 0 else -engage)
        return self._move(
            me, (goal_x, float(focus.world_y)), f"twin skill engage {focus.label}"
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
