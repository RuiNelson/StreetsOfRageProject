"""Multi-tick stability: the commanded direction must not chatter.

Every other test in this suite checks one tick in isolation, which is
precisely why a whole class of live-visible bugs got through: the pipeline
is a closed loop -- what it commands this tick becomes part of what it
observes next tick (position, and via the held D-pad, *facing*) -- and a
loop can oscillate even when every individual tick is defensible.

These tests drive the real pipeline over a run of ticks, feed each tick's
output back in the way the game would, and assert on the resulting sequence.
"""

import unittest
from dataclasses import replace

from sor_autoplay.ai.decide import generate_verb_tokens, in_smash_range
from sor_autoplay.ai.execute import execute_verb
from sor_autoplay.ai.gamepad import AXIS_RAMP_TICKS, SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import (
    AttackHeldEnemy,
    Breakable,
    CameraRange,
    DodgeSoutherSlash,
    Enemy,
    FlipHold,
    JumpAttack,
    Myself,
    OpenBreakable,
    Souther,
    Stage,
    Supplex,
    Verb,
    WalkToAdvanceStage,
    find,
    find_all,
)
from sor_autoplay.phases import CombatPhase
from sor_autoplay import prop_solids

UP = 0x0001
DOWN = 0x0002
LEFT = 0x0004
RIGHT = 0x0008
B = 0x0020      # attack
JUMP = 0x0040   # physical C

# Ground walk is a couple of px per frame at a ~2-frame poll.
STEP_X = 4
STEP_Y = 2


class _FakeClient:
    """Records the last commanded mask; the pipeline's only output here."""

    def __init__(self) -> None:
        self.held = 0
        self.pressed = 0

    def hold_buttons(self, player1=0, player2=0):
        self.held = player1

    def press_buttons(self, player1=0, player2=0, frames=1):
        self.pressed = player1
        self.held = player1

    def release_buttons(self, player1=0, player2=0):
        self.held = 0


def _actor(
    world_x: int, world_y: int, facing_left: bool, health_percent: float = 100.0
) -> Myself:
    return Myself(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=world_x,
        world_y=world_y,
        health=int(health_percent),
        health_percent=health_percent,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=facing_left,
        combat_phase=CombatPhase.NORMAL,
        action_state=0,
        is_airborne=False,
    )


def _enemy(world_x: int, world_y: int, phase: CombatPhase) -> Enemy:
    return Enemy(
        slot="obj01",
        type_id=0x20,
        world_x=world_x,
        world_y=world_y,
        health=10,
        combat_phase=phase,
        targets_player=1,
        facing_left=True,
    )


def _run(
    *,
    ticks: int,
    actor_x: int,
    actor_y: int,
    enemy_x: int,
    enemy_y: int,
    phases,
    health_percent: float = 100.0,
) -> list[int]:
    """Drive the pipeline ``ticks`` times, returning each tick's held mask.

    ``phases`` supplies the enemy's combat phase per tick (cycled), so a
    committed enemy can be held committed for exactly as long as the case
    under test needs. The actor is moved by whatever the pipeline commanded,
    including the facing flip a held direction causes -- that feedback is
    the whole point.
    """

    masks: list[int] = []
    ax, ay, facing_left = actor_x, actor_y, False
    # One VirtualGamepad for the whole run, matching production wiring
    # (AgentLoop holds one persistent gamepad per player): its virtual
    # left/right axis (see gamepad.VirtualGamepad.steer_x) only ramps toward
    # full deflection across *consecutive* calls on the same instance, so a
    # fresh gamepad every tick would never reach an edge and every D-pad
    # press in this whole suite would silently vanish.
    client = _FakeClient()
    gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
    for tick in range(ticks):
        context = {
            _actor(ax, ay, facing_left, health_percent),
            _enemy(enemy_x, enemy_y, phases[tick % len(phases)]),
            CameraRange(left=-100, right=500, top=0, bottom=112),
            Stage(level_index=0, direction="right"),
        }
        context |= generate_inference_tokens(context)
        context |= generate_verb_tokens(context)
        context = determine_priority_verb(context)

        verbs = find_all(context, Verb)
        if verbs:
            execute_verb(verbs[0], context, gamepad)
        held = client.held
        masks.append(held)

        if held & RIGHT:
            ax += STEP_X
            facing_left = False
        elif held & LEFT:
            ax -= STEP_X
            facing_left = True
        if held & DOWN:
            ay += STEP_Y
        elif held & UP:
            ay -= STEP_Y
    return masks


def _run_multi(
    *,
    ticks: int,
    actor_x: int,
    actor_y: int,
    enemies,
    phases,
    phase_stagger: int = 5,
) -> tuple[list[int], list[str | None]]:
    """``_run`` with several enemies, returning masks and the chosen target.

    Each enemy is offset into ``phases`` by ``phase_stagger`` ticks, so they
    are committing and recovering independently the way a real group does --
    which is what makes a per-tick target re-decision visible.
    """

    masks: list[int] = []
    targets: list[str | None] = []
    ax, ay, facing_left = actor_x, actor_y, False
    # See _run's comment: one persistent VirtualGamepad for the whole run.
    client = _FakeClient()
    gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
    for tick in range(ticks):
        context = {
            _actor(ax, ay, facing_left),
            CameraRange(left=-200, right=600, top=0, bottom=112),
            Stage(level_index=0, direction="right"),
        }
        for index, (slot, ex, ey) in enumerate(enemies):
            phase = phases[(tick + index * phase_stagger) % len(phases)]
            context.add(replace(_enemy(ex, ey, phase), slot=slot))
        context |= generate_inference_tokens(context)
        context |= generate_verb_tokens(context)
        context = determine_priority_verb(context)

        verbs = find_all(context, Verb)
        if verbs:
            execute_verb(verbs[0], context, gamepad)
        held = client.held
        masks.append(held)
        targets.append(getattr(verbs[0], "target_slot", None) if verbs else None)

        if held & RIGHT:
            ax += STEP_X
            facing_left = False
        elif held & LEFT:
            ax -= STEP_X
            facing_left = True
        if held & DOWN:
            ay += STEP_Y
        elif held & UP:
            ay -= STEP_Y
    return masks, targets


def _reversals(masks: list[int], positive: int, negative: int) -> int:
    """How many times the commanded direction flipped along one axis."""

    flips = 0
    last = 0
    for mask in masks:
        current = 1 if mask & positive else (-1 if mask & negative else 0)
        if current != 0:
            if last != 0 and current != last:
                flips += 1
            last = current
    return flips


def _switches(values) -> int:
    """How many times a per-tick choice changed, ignoring ticks with none."""

    seen = [v for v in values if v is not None]
    return sum(1 for a, b in zip(seen, seen[1:]) if a != b)


class SingleEnemyDirectionStabilityTests(unittest.TestCase):
    """The reported live symptom, as a test: against one enemy the AI
    "changes direction very often, very quickly, in jumps and up/down".

    Two independent limit cycles produced it, both invisible to
    single-tick tests:

    1. Approach and retreat switched on the *same* boundary
       (``reach.too_close_to_keep_approaching``), so one retreat step
       cleared the threat token and the next tick walked straight back in
       (fixed by ``reach.APPROACH_RELEASE_MARGIN``).
    2. Retreating holds the D-pad away from the threat, which sets facing
       away, which made ``reach.enemy_behind_actor`` re-classify that same
       enemy as "behind" -- handing it from ``could_retreat_from_danger``
       (which skipped behind enemies) to ``could_walk_to_near_enemy``'s
       turn-around, which walked back and flipped facing again (fixed by
       making both side-agnostic; see ``could_retreat_from_danger``).
    """

    def test_committed_enemy_does_not_cause_per_tick_reversals(self) -> None:
        # Hurt, so RetreatFromDanger is in play at all (decide.
        # _retreat_is_worth_it) -- that is the configuration both cycles
        # needed, since a healthy actor now simply walks in and never gives
        # the retreat anything to fight over.
        masks = _run(
            ticks=20,
            actor_x=100,
            actor_y=60,
            enemy_x=160,
            enemy_y=60,
            phases=[CombatPhase.ATTACKING],
            health_percent=20.0,
        )

        # The old pipeline alternated retreat/approach on literally every
        # tick. One or two reversals would be a real change of mind; a
        # double-digit count over 20 ticks is the cycle.
        self.assertLessEqual(
            _reversals(masks, RIGHT, LEFT),
            2,
            f"horizontal direction chattered: {[hex(m) for m in masks]}",
        )
        self.assertLessEqual(
            _reversals(masks, DOWN, UP),
            2,
            f"vertical direction chattered: {[hex(m) for m in masks]}",
        )

    def test_retreat_from_a_committed_enemy_is_sustained(self) -> None:
        # Backing off must actually gain ground: the cycle's signature was
        # that it never did, bouncing between the same two x values. Hurt, so
        # the retreat is warranted in the first place.
        masks = _run(
            ticks=6,
            actor_x=100,
            actor_y=60,
            enemy_x=160,
            enemy_y=60,
            phases=[CombatPhase.ATTACKING],
            health_percent=20.0,
        )

        self.assertTrue(
            any(mask & LEFT for mask in masks),
            "never backed off from a committed enemy while hurt",
        )
        self.assertFalse(
            any(mask & RIGHT for mask in masks),
            f"walked back toward the committed enemy mid-retreat: "
            f"{[hex(m) for m in masks]}",
        )

    def test_lane_aim_does_not_follow_the_enemys_phase(self) -> None:
        # The approach used to converge onto the enemy's lane while calm and
        # sidestep off it while committed, so every phase change flipped the
        # lane aim by 2*WALK_TO_ENEMY_LANE_SAFETY_Y (56px) and the whole walk
        # in alternated UP/DOWN. A real enemy cycles phases every few ticks,
        # so this fired constantly.
        masks = _run(
            ticks=24,
            actor_x=100,
            actor_y=60,
            enemy_x=300,
            enemy_y=55,
            phases=(
                [CombatPhase.NORMAL] * 6
                + [CombatPhase.ATTACKING] * 5
                + [CombatPhase.RECOVERY] * 4
            ),
        )

        self.assertLessEqual(
            _reversals(masks, DOWN, UP),
            1,
            f"lane aim chattered with the enemy's phase: {[hex(m) for m in masks]}",
        )

    def test_healthy_actor_walks_into_a_committed_enemy_instead_of_fleeing(self) -> None:
        # The design rule this suite must not let regress: an enemy cannot be
        # defeated without standing in its range, so at full health a
        # committed enemy nearby is something to close on. A general flee
        # reflex made the AI passive *and* supplied both limit cycles above
        # with the verb they oscillated against.
        masks = _run(
            ticks=6,
            actor_x=100,
            actor_y=60,
            enemy_x=160,
            enemy_y=60,
            phases=[CombatPhase.ATTACKING],
        )

        self.assertFalse(
            any(mask & LEFT for mask in masks),
            f"fled a committed enemy at full health: {[hex(m) for m in masks]}",
        )

    def test_closes_in_again_once_the_enemy_is_no_longer_committed(self) -> None:
        # The suppression is gated on the enemy's dangerous phase, so it has
        # to lift by itself -- otherwise the fix would just trade a jitter
        # bug for a passivity bug. The virtual left/right axis (gamepad.
        # AXIS_RAMP_TICKS) means the first couple of ticks legitimately hold
        # nothing yet while it ramps toward RIGHT; what must not happen is
        # ever holding LEFT, or RIGHT still not being reached once the axis
        # has had time to settle.
        masks = _run(
            ticks=6,
            actor_x=100,
            actor_y=60,
            enemy_x=200,
            enemy_y=60,
            phases=[CombatPhase.NORMAL],
        )

        self.assertFalse(
            any(mask & LEFT for mask in masks),
            f"fled instead of closing on a harmless enemy: {[hex(m) for m in masks]}",
        )
        self.assertTrue(
            all(mask & RIGHT for mask in masks[AXIS_RAMP_TICKS - 1 :]),
            f"did not close on a harmless enemy once the axis settled: {[hex(m) for m in masks]}",
        )


class MultipleEnemyTargetStabilityTests(unittest.TestCase):
    """A crowd is the normal case in this game, and it is where the last of
    the reported oscillation lived: several enemies produce one candidate
    verb each (by design -- a ``could_*`` never pre-selects), those candidates
    routinely tie on emergency, and the tie used to be broken with
    ``random.choice`` on every tick. Re-rolling a tie ~15 times a second turns
    "either target is fine" into swapping between them constantly, and since
    the targets sit in different directions, each swap re-aims the D-pad."""

    _PHASES = (
        [CombatPhase.NORMAL] * 6 + [CombatPhase.ATTACKING] * 5 + [CombatPhase.RECOVERY] * 4
    )

    def test_does_not_hunt_between_two_equally_ranked_enemies(self) -> None:
        masks, targets = _run_multi(
            ticks=30,
            actor_x=100,
            actor_y=60,
            enemies=[("obj01", 260, 55), ("obj02", 285, 70)],
            phases=self._PHASES,
        )

        self.assertLessEqual(
            _switches(targets),
            2,
            f"target churned between equally ranked enemies: {targets}",
        )
        self.assertLessEqual(
            _reversals(masks, RIGHT, LEFT),
            1,
            f"horizontal direction chattered in a crowd: {[hex(m) for m in masks]}",
        )
        self.assertLessEqual(
            _reversals(masks, DOWN, UP),
            1,
            f"vertical direction chattered in a crowd: {[hex(m) for m in masks]}",
        )

    def test_enemies_on_opposite_sides_do_not_pull_the_actor_back_and_forth(self) -> None:
        # The worst shape for target churn: swapping target here reverses the
        # commanded direction outright, since the two sit either side of the
        # actor at a near-identical distance.
        masks, targets = _run_multi(
            ticks=30,
            actor_x=200,
            actor_y=60,
            enemies=[("obj01", 340, 60), ("obj02", 62, 60)],
            phases=self._PHASES,
        )

        self.assertLessEqual(
            _switches(targets),
            2,
            f"target churned between enemies on opposite sides: {targets}",
        )
        self.assertLessEqual(
            _reversals(masks, RIGHT, LEFT),
            1,
            f"was pulled back and forth between two enemies: "
            f"{[hex(m) for m in masks]}",
        )


class _EdgeTrackingClient:
    """Like ``_FakeClient``, but keeps a *timed* press the way the host does.

    A ROM input bit is edge-triggered (``+$55``), so "was B pressed" and "is
    B held" are different questions and the jump kick only answers to the
    first. Modelling ``press_buttons(frames=N)`` as a mask that expires is
    what makes that distinction observable here.
    """

    def __init__(self) -> None:
        self.held = 0
        self._pressed = 0
        self._frames = 0

    def hold_buttons(self, player1=0, player2=0):
        self.held = player1

    def press_buttons(self, player1=0, player2=0, frames=1):
        self._pressed = player1
        self._frames = frames

    def release_buttons(self, player1=0, player2=0):
        self.held = 0
        self._pressed = 0
        self._frames = 0

    def advance(self, frames):
        """The mask on the pad right now; expires timed presses."""

        mask = (self._pressed if self._frames > 0 else 0) | self.held
        self._frames = max(0, self._frames - frames)
        if self._frames == 0:
            self._pressed = 0
        return mask


# The ROM's own unarmed jump family, with the facing bit cleared
# (controls-and-input.md "Action state machine"): $10 is the 5-frame crouch,
# $12 free flight, $16 the kick, $14 the landing.
JUMP_START, FREE_FLIGHT, JUMP_KICK, JUMP_LAND = 0x10, 0x12, 0x16, 0x14
CROUCH_FRAMES = 5
FRAMES_PER_TICK = 2


def _run_jump(enemy_x: int, frames: int = 40, enemy_vel: int = 0) -> dict:
    """Drive one whole jump, feeding the ROM's action state machine back in.

    Returns what the flight actually achieved: whether a *fresh* B edge
    arrived while in free flight (the only thing $3914 accepts), and whether
    a direction was held at the moment $384E samples it -- the two failures
    that between them had the AI jumping at enemies and doing nothing.
    """

    client = _EdgeTrackingClient()
    gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
    ax, action, crouch = 100, 0x02, 0
    prev_mask = 0
    result = {"kick_edge_in_flight": False, "direction_at_launch": False,
              "b_pressed_in_crouch": False}

    for frame in range(frames):
        airborne = JUMP_START <= (action & 0xFE) <= 0x17
        if frame % FRAMES_PER_TICK == 0:
            context = {
                _actor(ax, 100, False),
                _enemy(int(enemy_x), 100, CombatPhase.NORMAL),
                CameraRange(left=-100, right=500, top=0, bottom=112),
                Stage(level_index=0, direction="right"),
            }
            context = {
                token
                for token in context
                if not isinstance(token, Myself)
            } | {
                replace(find(context, Myself), action_state=action, is_airborne=airborne)
            }
            context |= generate_inference_tokens(context)
            context |= generate_verb_tokens(context)
            context = determine_priority_verb(context)
            verbs = find_all(context, Verb)
            if verbs:
                execute_verb(verbs[0], context, gamepad)

        mask = client.advance(FRAMES_PER_TICK if frame % FRAMES_PER_TICK == 0 else 0)
        edge = mask & ~prev_mask
        prev_mask = mask
        base = action & 0xFE

        if base == 0x02 and (edge & JUMP) and not (mask & B):
            action, crouch = JUMP_START, CROUCH_FRAMES
        elif base == FREE_FLIGHT and (edge & B):
            action = JUMP_KICK
            result["kick_edge_in_flight"] = True
        elif base == JUMP_START and (mask & B):
            result["b_pressed_in_crouch"] = True

        base = action & 0xFE
        if base == JUMP_START:
            crouch -= 1
            if crouch <= 0:
                action = FREE_FLIGHT
                result["direction_at_launch"] = bool(mask & (LEFT | RIGHT))
        elif base in (FREE_FLIGHT, JUMP_KICK):
            ax += 3
            if ax >= enemy_x:
                action = JUMP_LAND
        elif base == JUMP_LAND:
            action = 0x02
        enemy_x += enemy_vel
    return result


def _souther(world_x: int, world_y: int, primary_state: int, tactical: int) -> Souther:
    return Souther(
        slot="obj11",
        type_id=0x55,
        world_x=world_x,
        world_y=world_y,
        health=32,
        combat_phase=(
            CombatPhase.ATTACKING if primary_state == 2 else CombatPhase.NORMAL
        ),
        targets_player=1,
        facing_left=True,
        primary_state=primary_state,
        tactical=tactical,
    )


def _run_souther(
    *,
    ticks: int,
    actor_x: int,
    actor_y: int,
    souther_x: int,
    souther_y: int,
    states,
) -> tuple[list[int], list[str]]:
    """Drive the pipeline against one Souther, cycling his own ROM states.

    ``states`` supplies ``(primary_state, tactical)`` per tick (cycled), which
    is what decides between the three verbs that can own the tick here: the
    approach, the lane dodge, and -- while the jump counter is armed -- nothing
    at all where a jump used to be. Returns each tick's held mask and the
    winning verb's class name, since *which verb owns the actor* is the thing
    that can chatter.
    """

    masks: list[int] = []
    winners: list[str] = []
    ax, ay, facing_left = actor_x, actor_y, False
    # See _run's comment: one persistent VirtualGamepad for the whole run.
    client = _FakeClient()
    gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
    for tick in range(ticks):
        primary, tactical = states[tick % len(states)]
        context = {
            _actor(ax, ay, facing_left),
            _souther(souther_x, souther_y, primary, tactical),
            CameraRange(left=-100, right=500, top=0, bottom=112),
            Stage(level_index=1, direction="right"),
        }
        context |= generate_inference_tokens(context)
        context |= generate_verb_tokens(context)
        context = determine_priority_verb(context)

        verbs = find_all(context, Verb)
        if verbs:
            execute_verb(verbs[0], context, gamepad)
            winners.append(type(verbs[0]).__name__)
        else:
            winners.append("none")
        held = client.held
        masks.append(held)

        if held & RIGHT:
            ax += STEP_X
            facing_left = False
        elif held & LEFT:
            ax -= STEP_X
            facing_left = True
        if held & DOWN:
            ay += STEP_Y
        elif held & UP:
            ay -= STEP_Y
    return masks, winners


class SoutherStabilityTests(unittest.TestCase):
    """The lane dodge and the X approach are exactly the pair that produced
    the two shipped limit cycles in other verbs: one freezes X and moves Y,
    the other closes X and converges Y, and Souther crosses in and out of his
    committed claw every few ticks in a real fight.
    """

    def test_alternating_commitment_does_not_chatter_the_lane(self) -> None:
        # Four ticks committed, four not -- roughly the real cadence of
        # $16118 (souther_state2_claw_commit) resolving and re-arming.
        masks, _ = _run_souther(
            ticks=40,
            actor_x=100,
            actor_y=60,
            souther_x=180,
            souther_y=60,
            states=[(2, 2)] * 4 + [(1, 0)] * 4,
        )
        self.assertLessEqual(
            _reversals(masks, DOWN, UP),
            4,
            f"lane direction chattered: {[hex(m) for m in masks]}",
        )
        self.assertLessEqual(
            _reversals(masks, RIGHT, LEFT),
            4,
            f"X direction chattered: {[hex(m) for m in masks]}",
        )

    def test_never_jumps_while_the_counter_is_armed(self) -> None:
        # The whole point of the refusal: over a run where Souther stays in
        # state 1, C must never be pressed and no JumpAttack may ever win.
        masks, winners = _run_souther(
            ticks=40,
            actor_x=100,
            actor_y=60,
            souther_x=180,
            souther_y=60,
            states=[(1, 0)],
        )
        self.assertNotIn(JumpAttack.__name__, winners)
        self.assertFalse(
            any(mask & JUMP for mask in masks),
            f"pressed jump inside the counter box: {[hex(m) for m in masks]}",
        )

    def test_never_jumps_into_the_claw(self) -> None:
        """No jump is ever launched over a run against a live Souther.

        A run-level guard, **not** the regression pin for the live-reported
        "salta diretamente para as gadanhas": checked explicitly, this test
        passes against the old, broken gates too, because on those ground ticks
        DodgeSoutherSlash (46) outranks JumpAttack (32) anyway and no jump gets
        launched here regardless. The actual pins are
        `test_decide.JumpRefusedNearSoutherTests`'
        `test_still_refused_once_the_dash_is_launched` and
        `test_off_lane_launches_are_refused_too`, both of which do fail against
        the old gates.

        Kept because it covers the composition those two do not: the whole
        state cycle 1 -> wind-up -> launch -> dash, fed back tick by tick, at
        three lane offsets.
        """

        for lane in (0, 24, 40):
            masks, winners = _run_souther(
                ticks=60,
                actor_x=100,
                actor_y=60,
                souther_x=180,
                souther_y=60 + lane,
                states=[(1, 0)] * 6 + [(2, 0)] * 3 + [(2, 1)] * 3 + [(2, 2)] * 6,
            )
            self.assertNotIn(
                JumpAttack.__name__, winners, f"jumped at Souther, lane {lane}"
            )
            self.assertFalse(
                any(mask & JUMP for mask in masks),
                f"pressed jump near Souther, lane {lane}",
            )

    def test_the_dodge_owns_every_committed_tick(self) -> None:
        masks, winners = _run_souther(
            ticks=20,
            actor_x=100,
            actor_y=60,
            souther_x=180,
            souther_y=60,
            states=[(2, 2)],
        )
        self.assertEqual(set(winners), {DodgeSoutherSlash.__name__})


def _run_hold_sequence(*, ticks: int = 20) -> list[str]:
    """Drive the real hold chain over a run of ticks: knee(s) -> flip -> suplex.

    Bypasses ``observe.py`` like every other harness in this file -- tokens
    are built directly rather than from a ``GameSnapshot`` -- so
    ``Myself.hold_ticks`` is threaded by hand here the same way
    ``observe.HoldTracker`` threads it live: incremented once per tick,
    reset only if the hold itself ends. ``action_state`` is advanced the way
    ``execute.state_machine_flip_hold``'s own docstring describes: front
    hold ``$60`` -> a ``FlipHold`` win crosses to back hold ``$66`` -> a
    ``Supplex`` win finishes it, which is where the run stops.

    Live-reported regression this exists to catch: a single-tick test cannot
    tell "grab, then finish immediately" from "grab, knee a few times, then
    finish" -- only a sequence can, which is why this is here and not in
    ``test_priority.py``.
    """

    winners: list[str] = []
    action_state = 0x60
    hold_ticks = 0
    client = _FakeClient()
    gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
    for _ in range(ticks):
        actor = replace(
            _actor(100, 60, False),
            held_weapon_type=0x20,  # non-weapon type id -> holding an enemy
            action_state=action_state,
            hold_ticks=hold_ticks,
        )
        held = _enemy(120, 60, CombatPhase.GRABBED)
        context = {
            actor,
            held,
            CameraRange(left=-100, right=500, top=0, bottom=112),
            Stage(level_index=0, direction="right"),
        }
        context |= generate_verb_tokens(context)
        context = determine_priority_verb(context)

        verbs = find_all(context, Verb)
        winner = verbs[0] if verbs else None
        winners.append(type(winner).__name__ if winner is not None else "None")
        if winner is not None:
            execute_verb(winner, context, gamepad)

        hold_ticks += 1
        if isinstance(winner, FlipHold):
            action_state = 0x66
        if isinstance(winner, Supplex):
            break
    return winners


class HoldSequenceStabilityTests(unittest.TestCase):
    """The live-reported failure: grab -> flip -> suplex, zero knees milked."""

    def test_knee_is_milked_before_the_finish(self) -> None:
        winners = _run_hold_sequence()

        self.assertGreaterEqual(
            winners.count(AttackHeldEnemy.__name__),
            1,
            f"no knee landed before the finish: {winners}",
        )

    def test_the_sequence_ends_in_a_supplex(self) -> None:
        winners = _run_hold_sequence()

        self.assertEqual(winners[-1], Supplex.__name__)

    def test_every_knee_precedes_the_flip(self) -> None:
        # Once FlipHold wins, the hold has crossed to the back and no further
        # AttackHeldEnemy can legally follow it -- $AttackHeldEnemy is a
        # front-hold-only move.
        winners = _run_hold_sequence()
        if FlipHold.__name__ not in winners:
            self.skipTest("flip did not win in this run")
        flip_index = winners.index(FlipHold.__name__)

        self.assertNotIn(AttackHeldEnemy.__name__, winners[flip_index + 1 :])

    def test_knee_count_matches_hold_knee_ticks(self) -> None:
        # HOLD_KNEE_TICKS is the exact boundary priority.py scores on, so the
        # knee run this produces should be that long, not merely "some".
        from sor_autoplay.ai.priority import HOLD_KNEE_TICKS

        winners = _run_hold_sequence()
        knee_run = 0
        for name in winners:
            if name != AttackHeldEnemy.__name__:
                break
            knee_run += 1

        self.assertEqual(knee_run, HOLD_KNEE_TICKS + 1)


class BossAndGruntTargetStabilityTests(unittest.TestCase):
    """Making the actionable skip per-enemy adds a new way to chatter.

    Before, a grunt in punch range suppressed the approach for everyone, so
    there was only ever one candidate. Now the boss keeps its walk-in while the
    grunt stays punchable, which is the point -- but it also means two verbs
    aimed in different directions are live every tick, and that is exactly the
    shape of the target-swap cycles this file already pins.
    """

    def test_the_boss_is_held_as_the_target_rather_than_swapped(self) -> None:
        masks: list[int] = []
        targets: list[str | None] = []
        ax, ay, facing_left = 100, 60, False
        client = _FakeClient()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        for _ in range(40):
            context = {
                _actor(ax, ay, facing_left),
                _enemy(140, 60, CombatPhase.NORMAL),
                _souther(220, 60, 1, 0),
                CameraRange(left=-100, right=600, top=0, bottom=112),
                Stage(level_index=1, direction="right"),
            }
            context |= generate_inference_tokens(context)
            context |= generate_verb_tokens(context)
            context = determine_priority_verb(context)
            verbs = find_all(context, Verb)
            if verbs:
                execute_verb(verbs[0], context, gamepad)
                targets.append(getattr(verbs[0], "target_slot", None))
            else:
                targets.append(None)
            held = client.held
            masks.append(held)
            if held & RIGHT:
                ax += STEP_X
                facing_left = False
            elif held & LEFT:
                ax -= STEP_X
                facing_left = True
            if held & DOWN:
                ay += STEP_Y
            elif held & UP:
                ay -= STEP_Y

        self.assertLessEqual(
            _switches(targets), 4, f"target chattered: {targets}"
        )
        self.assertLessEqual(
            _reversals(masks, RIGHT, LEFT), 4, f"direction chattered: {masks}"
        )


class BreakableAdvanceStabilityTests(unittest.TestCase):
    """OpenBreakable vs WalkToAdvanceStage must not hand a crate back and
    forth. Reported from play as the HUD flipping WalkToBreakable /
    WalkToAdvanceStage for as long as a prop was on screen: the approach
    score (14 down to 8) used to cross the advance's then-flat 12 around
    30-45px, and the around-path walking left off a same-X crate made the
    hypot distance grow until advance won, walked right, and handed it
    back. Advance now sits at 1 (and scores 0 while a blocking crate
    exists), so the cycle cannot return from ranking alone."""

    def _run_crate(
        self, *, ticks: int, actor_x: int, actor_y: int, prop_x: int, prop_y: int
    ) -> tuple[list[int], list[str]]:
        masks: list[int] = []
        names: list[str] = []
        ax, ay, facing_left = actor_x, actor_y, False
        client = _FakeClient()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        for _ in range(ticks):
            context = {
                _actor(ax, ay, facing_left),
                Breakable(slot="obj09", world_x=prop_x, world_y=prop_y, type_id=0x40),
                CameraRange(left=-100, right=500, top=0, bottom=112),
                Stage(level_index=0, direction="right"),
            }
            context |= generate_inference_tokens(context)
            context |= generate_verb_tokens(context)
            context = determine_priority_verb(context)

            verbs = find_all(context, Verb)
            if verbs:
                execute_verb(verbs[0], context, gamepad)
            held = client.held
            masks.append(held)
            names.append(type(verbs[0]).__name__ if verbs else "")

            if held & RIGHT:
                ax += STEP_X
                facing_left = False
            elif held & LEFT:
                ax -= STEP_X
                facing_left = True
            if held & DOWN:
                ay += STEP_Y
            elif held & UP:
                ay -= STEP_Y
        return masks, names

    def test_does_not_flip_between_opening_and_advancing_at_a_crate(self) -> None:
        # Same-lane crate ~60px ahead: far enough that the old approach
        # score sat at or under WalkToAdvanceStage's then-12, so every
        # other tick swapped the verb and the D-pad reversed.
        masks, names = self._run_crate(
            ticks=24, actor_x=100, actor_y=64, prop_x=160, prop_y=64
        )

        self.assertNotIn(
            WalkToAdvanceStage.__name__,
            names,
            f"WalkToAdvanceStage took ticks while a crate sat ahead: {names}",
        )
        self.assertTrue(
            all(name == OpenBreakable.__name__ for name in names),
            f"expected OpenBreakable throughout, got {names}",
        )
        self.assertLessEqual(
            _reversals(masks, RIGHT, LEFT),
            1,
            f"horizontal direction chattered at a crate: {[hex(m) for m in masks]}",
        )

    def test_does_not_flip_when_the_crate_is_on_a_different_lane(self) -> None:
        # The around-path holds Y and walks out to the smash X, which
        # grows hypot-distance and used to drop the approach score below
        # 12 -- the exact live loop.
        masks, names = self._run_crate(
            ticks=24, actor_x=160, actor_y=40, prop_x=160, prop_y=80
        )

        self.assertNotIn(
            WalkToAdvanceStage.__name__,
            names,
            f"WalkToAdvanceStage interrupted the around-path: {names}",
        )
        self.assertLessEqual(
            _reversals(masks, RIGHT, LEFT),
            1,
            f"around-path chattered left/right: {[hex(m) for m in masks]}",
        )

    def test_a_crate_already_behind_does_not_turn_the_actor_around(self) -> None:
        masks, names = self._run_crate(
            ticks=12, actor_x=200, actor_y=64, prop_x=80, prop_y=64
        )

        self.assertNotIn(
            OpenBreakable.__name__,
            names,
            f"walked back to a crate already behind: {names}",
        )
        self.assertTrue(
            all(name == WalkToAdvanceStage.__name__ for name in names),
            f"expected WalkToAdvanceStage throughout, got {names}",
        )
        self.assertFalse(
            any(mask & LEFT for mask in masks),
            f"turned back toward a passed crate: {[hex(m) for m in masks]}",
        )


class FirstLevelBreakableStallTests(unittest.TestCase):
    """Type-$11 phone booths (round 1) and type-$19 crates share the
    shallowest ROM solid: 14px on lane against a 16px body, walkable in
    front of the feet. Standing legally just in front used to drop that
    wall from the search, after which OpenBreakable held UP into the real
    solid forever."""

    BOOTH_X = 280
    BOOTH_Y = 40

    def _run(
        self, *, actor_x: int, actor_y: int, type_id: int = 0x11, ticks: int = 60
    ) -> tuple[list[tuple[int, int]], list[int], bool]:
        prop = Breakable(
            slot="obj09", world_x=self.BOOTH_X, world_y=self.BOOTH_Y, type_id=type_id
        )
        wall = prop_solids.solid_box(type_id, self.BOOTH_X, self.BOOTH_Y)
        ax, ay, facing_left = actor_x, actor_y, False
        client = _FakeClient()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        trail: list[tuple[int, int]] = []
        masks: list[int] = []
        punched = False
        for _ in range(ticks):
            actor = _actor(ax, ay, facing_left)
            context = {
                actor,
                prop,
                CameraRange(left=0, right=640, top=0, bottom=112),
                Stage(level_index=0, direction="right"),
            }
            context |= generate_inference_tokens(context)
            context |= generate_verb_tokens(context)
            context = determine_priority_verb(context)
            verbs = find_all(context, Verb)
            if verbs:
                execute_verb(verbs[0], context, gamepad)
            held = client.held
            masks.append(held)
            trail.append((ax, ay))
            if client.pressed & B:
                punched = True
                break
            nx = ax + (STEP_X if held & RIGHT else 0) - (STEP_X if held & LEFT else 0)
            ny = ay + (STEP_Y if held & DOWN else 0) - (STEP_Y if held & UP else 0)
            if wall.blocks(nx, ny):
                nx, ny = ax, ay
            if nx != ax:
                facing_left = nx < ax
            ax, ay = nx, ny
        return trail, masks, punched

    def test_does_not_freeze_in_front_of_a_phone_booth(self) -> None:
        # First legal-in-front origin, same X as the booth -- the live stall.
        trail, masks, punched = self._run(actor_x=self.BOOTH_X, actor_y=44)

        self.assertTrue(
            punched or any(
                in_smash_range(_actor(x, y, False), Breakable(
                    slot="obj09",
                    world_x=self.BOOTH_X,
                    world_y=self.BOOTH_Y,
                    type_id=0x11,
                ))
                for x, y in trail
            ),
            f"never reached smash range; trail={trail[-8:]} masks={[hex(m) for m in masks[-8:]]}",
        )
        self.assertLess(
            trail.count((self.BOOTH_X, 44)),
            12,
            f"stood still against the booth: trail={trail[-12:]}",
        )

    def test_does_not_freeze_in_front_of_a_type19_crate(self) -> None:
        trail, _masks, punched = self._run(
            actor_x=self.BOOTH_X, actor_y=44, type_id=0x19
        )

        self.assertTrue(punched or any(
            in_smash_range(_actor(x, y, False), Breakable(
                slot="obj09",
                world_x=self.BOOTH_X,
                world_y=self.BOOTH_Y,
                type_id=0x19,
            ))
            for x, y in trail
        ), f"never reached smash range; trail={trail[-8:]}")

    def test_still_opens_a_booth_approached_from_the_street(self) -> None:
        trail, _masks, punched = self._run(actor_x=200, actor_y=80)

        self.assertTrue(punched, f"never punched; ended at {trail[-1] if trail else None}")


class JumpKickFlightTests(unittest.TestCase):
    """The jump kick is the one move that spans several ticks *and* several
    ROM states, so it can only be checked across a run of them.

    Both failures pinned here were reported from play and then measured on a
    flight harness: 211 of 587 launched jumps produced no kick at all, and
    the first jump of an encounter travelled nowhere because the direction
    was not held when ``$384E`` sampled it."""

    def test_a_launched_jump_lands_a_kick_edge_in_free_flight(self) -> None:
        result = _run_jump(enemy_x=155)

        self.assertTrue(
            result["kick_edge_in_flight"],
            "B never arrived as a fresh edge during free flight -- $3914 "
            "accepts nothing else, so the actor flew the whole arc and did "
            "nothing",
        )

    def test_a_target_leaving_the_band_mid_flight_still_gets_kicked(self) -> None:
        # The flight is committed the moment it starts, but the *verb* used
        # to depend on the reach band still holding -- so a target walking
        # out of it deleted the verb mid-air, and a tick with no verb
        # reaches press_no_button, which releases the hold: no kick, and no
        # carry either if it happens during the crouch.
        result = _run_jump(enemy_x=155, enemy_vel=3)

        self.assertTrue(result["kick_edge_in_flight"])
        self.assertTrue(result["direction_at_launch"])

    def test_no_b_is_pressed_during_the_crouch(self) -> None:
        # A B pressed in the crouch is still *held* when free flight starts
        # (_press holds 4 frames, the AI re-decides every 2), so no edge ever
        # arrives and the kick silently never happens.
        result = _run_jump(enemy_x=155)

        self.assertFalse(result["b_pressed_in_crouch"])

    def test_the_launch_direction_is_held_when_the_rom_samples_it(self) -> None:
        # $384E reads the held direction once, at the end of the crouch. The
        # virtual X axis needs AXIS_RAMP_TICKS to reach an edge -- longer
        # than the crouch lasts -- so this only holds because the jump
        # handler bypasses it.
        result = _run_jump(enemy_x=155)

        self.assertTrue(
            result["direction_at_launch"],
            "no direction held at launch: the jump goes straight up and the "
            "kick lands on empty air where the actor stood",
        )

