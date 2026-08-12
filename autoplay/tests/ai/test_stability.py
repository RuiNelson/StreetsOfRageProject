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

from sor_autoplay.ai.decide import generate_verb_tokens
from sor_autoplay.ai.execute import execute_verb
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import CameraRange, Enemy, Myself, Stage, Verb, find_all
from sor_autoplay.phases import CombatPhase

UP = 0x0001
DOWN = 0x0002
LEFT = 0x0004
RIGHT = 0x0008

# Ground walk is a couple of px per frame at a ~2-frame poll.
STEP_X = 4
STEP_Y = 2


class _FakeClient:
    """Records the last commanded mask; the pipeline's only output here."""

    def __init__(self) -> None:
        self.held = 0

    def hold_buttons(self, player1=0, player2=0):
        self.held = player1

    def press_buttons(self, player1=0, player2=0, frames=1):
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

        client = _FakeClient()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
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

        client = _FakeClient()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
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
        # bug for a passivity bug.
        masks = _run(
            ticks=6,
            actor_x=100,
            actor_y=60,
            enemy_x=200,
            enemy_y=60,
            phases=[CombatPhase.NORMAL],
        )

        self.assertTrue(
            all(mask & RIGHT for mask in masks),
            f"did not close on a harmless enemy: {[hex(m) for m in masks]}",
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
