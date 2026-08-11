import inspect
import unittest
from dataclasses import replace
from unittest.mock import MagicMock

from sor_autoplay.ai import execute as execute_module
from sor_autoplay.ai import loop as loop_module
from sor_autoplay.ai import priority as priority_module
from sor_autoplay.ai.tokens import (
    CounterGrab,
    GrabEnemy,
    JumpAttack,
    OpenBreakable,
    Punch,
    RearAttack,
    SprayPepper,
    StabWithKnifeOrBottle,
    Supplex,
    SwingBatOrPipe,
    TechRecover,
    ThrowKnife,
    ThrowPepper,
)
from sor_autoplay.ai.tokens import Myself
from sor_autoplay.ai.tokens import Enemy
from sor_autoplay.ai.tokens import CameraRange
from sor_autoplay.ai.execute import (
    BREAKABLE_STOP_BUFFER,
    MOVE_DEADBAND_X,
    WALK_TO_ENEMY_LANE_SAFETY_Y,
    _walk_to_near_enemy_target,
    execute_verb,
    press_no_button,
)
from sor_autoplay.ai.decide import BREAKABLE_PUNCH_X, in_smash_range
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.tokens import Breakable, Pit, SafeSpot
from sor_autoplay.ai.tokens import HealthPickup, Weapon
from sor_autoplay.ai.tokens import CallPolice
from sor_autoplay.ai.tokens import (
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from sor_autoplay.phases import CombatPhase

UP = 0x0001
DOWN = 0x0002
LEFT = 0x0004
RIGHT = 0x0008
A = 0x0010
B = 0x0020
C = 0x0040


def _myself(
    *, world_x: int = 0, world_y: int = 0, action_state: int = 0, is_airborne: bool = False
) -> Myself:
    return Myself(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=world_x,
        world_y=world_y,
        health=100,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=False,
        combat_phase=CombatPhase.NORMAL,
        action_state=action_state,
        is_airborne=is_airborne,
    )


def _enemy(*, world_x: int = 0, world_y: int = 0) -> Enemy:
    return Enemy(
        slot="obj01",
        type_id=0x20,
        world_x=world_x,
        world_y=world_y,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
    )


def _gamepad() -> tuple[VirtualGamepad, MagicMock]:
    client = MagicMock()
    state = SharedGamepadState(client)
    return VirtualGamepad(state, player_index=1), client


class PressNoButtonTests(unittest.TestCase):
    def test_press_no_button_releases(self) -> None:
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)
        client.hold_buttons.reset_mock()

        press_no_button(gamepad)

        client.hold_buttons.assert_called_once_with(player1=0, player2=0)
        self.assertEqual(gamepad.held, 0)


class ExecuteWalkToNearEnemyTests(unittest.TestCase):
    def test_walks_toward_enemy_to_the_right_and_below(self) -> None:
        # Enemy far enough right that the stopping point (its x minus Axel's
        # stop_dx of 46) is still well outside MOVE_DEADBAND_X -- otherwise
        # the actor has effectively arrived on X and only the lane component
        # should be held.
        actor = _myself(world_x=0, world_y=0)
        target = _enemy(world_x=100, world_y=50)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT | DOWN, player2=0)

    def test_walks_toward_enemy_to_the_left_and_above(self) -> None:
        actor = _myself(world_x=50, world_y=50)
        target = _enemy(world_x=0, world_y=0)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=LEFT | UP, player2=0)

    def test_turns_toward_an_enemy_at_the_actors_back(self) -> None:
        # Holding a direction is what sets facing, so walking *toward* a
        # behind enemy is the turn-around. Stopping on the near side (the
        # front-enemy rule) would instead hold RIGHT here -- backing away
        # while still facing the wrong way, which leaves the slow $322A
        # chord as the only thing that can reach it. Actor faces right
        # (facing_left=False), enemy sits to its left, so: behind.
        actor = _myself(world_x=100, world_y=100)
        target = _enemy(world_x=70, world_y=100)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=LEFT, player2=0)

    def test_standing_on_the_enemy_steps_back_to_punch_range(self) -> None:
        # Never walk onto the enemy — stop just inside punch_outer_x.
        actor = _myself(world_x=10, world_y=10)
        target = _enemy(world_x=10, world_y=10)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=LEFT, player2=0)

    def test_stops_just_inside_punch_range_instead_of_overlapping_enemy(self) -> None:
        # Axel: punch_outer_x=50, stop buffer 4 -> stop_dx=46. Placing the
        # actor exactly at that stopping x (relative to the enemy at x=50)
        # means it has already arrived and should hold no further movement.
        actor = _myself(world_x=4, world_y=50)
        target = _enemy(world_x=50, world_y=50)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)  # start non-zero so a hold(0) call is observable
        client.hold_buttons.reset_mock()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=0, player2=0)

    def test_missing_actor_or_target_does_nothing(self) -> None:
        context: set = {_enemy()}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_not_called()

    def test_sidesteps_a_dangerous_enemys_exact_lane_while_still_far_away(self) -> None:
        actor = _myself(world_x=0, world_y=50)
        target = replace(_enemy(world_x=200, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        # Same lane (dy=0) and far away (dx=200) from an actively attacking
        # enemy -> step off its lane instead of walking straight down it.
        client.hold_buttons.assert_called_once_with(player1=RIGHT | DOWN, player2=0)

    def test_does_not_sidestep_a_dangerous_enemy_once_close_enough_to_punch(self) -> None:
        # dx=46 == stop_dx: already at the stopping point, so the actor
        # aligns for the punch instead of sidestepping.
        actor = _myself(world_x=-6, world_y=50)
        target = replace(_enemy(world_x=40, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)  # start non-zero so a hold(0) call is observable
        client.hold_buttons.reset_mock()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=0, player2=0)

    def test_offsets_lane_from_a_dangerous_enemy_even_before_reaching_its_exact_lane(self) -> None:
        # Regression (live-diagnosed): gating the offset on already sitting
        # on the enemy's exact lane reacted too late -- the approach
        # converges onto that lane over several ticks regardless (nothing
        # else holds it off), so by the time the old gate opened the enemy
        # had often already reached ATTACKING and landed a hit. Aim for the
        # offset lane for the whole dangerous approach instead.
        #
        # A direction-only movement-mask assertion can't distinguish this
        # from the old behaviour here: with dy=30 (>= the old
        # WALK_TO_ENEMY_LANE_SAFETY_Y=28 "on_lane" threshold), the old code
        # converged straight onto the enemy's exact lane (target_y=50) while
        # the new code aims for an offset lane (target_y=50+28=78) -- both
        # are still below the actor's own world_y=80, so both read as an "UP"
        # step either way. Only the exact target position reveals the fix,
        # so call the private target-computation helper directly.
        actor = _myself(world_x=0, world_y=80)
        target = replace(_enemy(world_x=200, world_y=50), combat_phase=CombatPhase.ATTACKING)

        target_x, target_y = _walk_to_near_enemy_target(actor, target)

        self.assertEqual(target_y, 50 + WALK_TO_ENEMY_LANE_SAFETY_Y)

    def test_does_not_sidestep_an_enemy_that_is_not_dangerous(self) -> None:
        actor = _myself(world_x=0, world_y=50)
        target = _enemy(world_x=200, world_y=50)  # NORMAL phase
        context = {actor, target}
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)

    def test_close_range_side_pick_does_not_glitch_exactly_on_alignment(self) -> None:
        # Regression (live-diagnosed): the old side pick combined a strict
        # enemy_behind_actor() sign test with an *inclusive* <= elsewhere, so
        # for a left-facing actor dx=0 exactly picked the opposite side from
        # dx=+-1 right next to it -- a single-tick, full 2*stop_dx jump to
        # the far side of the enemy whenever an approach's integer rounding
        # briefly landed exactly on alignment. That flip is what set facing
        # the next tick, so it read back as the AI reversing direction
        # against a single, barely-moving enemy. Adjacent ticks a pixel
        # apart, straddling dx=0, must now agree.
        target = _enemy(world_x=100, world_y=40)
        masks = []
        for actor_x in (99, 100, 101):
            actor = replace(_myself(world_x=actor_x, world_y=40), facing_left=True)
            gamepad, _ = _gamepad()
            execute_verb(
                WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
                {actor, target},
                gamepad,
            )
            masks.append(gamepad.held)

        self.assertFalse(
            any(m & LEFT for m in masks) and any(m & RIGHT for m in masks),
            f"opposite horizontal commands straddling exact alignment: {masks}",
        )


class FaceTowardMaskHysteresisTests(unittest.TestCase):
    """``_face_toward_mask`` sets the facing bit pressed alongside an attack.
    Right at melee range the actor and target sit almost on top of each
    other, so a raw, unmargined sign test on their dx flips on every pixel of
    ordinary jitter; adjacent ticks a pixel apart must not command opposite
    facing."""

    def test_straddling_alignment_never_commands_opposite_facing(self) -> None:
        target = _enemy(world_x=100, world_y=40)
        masks = []
        for actor_x in (99, 100, 101):
            actor = _myself(world_x=actor_x, world_y=40)
            gamepad, client = _gamepad()

            execute_verb(Punch(actor_slot="P1", target_slot="obj01"), {actor, target}, gamepad)

            masks.append(client.press_buttons.call_args.kwargs["player1"])

        self.assertFalse(
            any(m & LEFT for m in masks) and any(m & RIGHT for m in masks),
            f"opposite facing commands straddling exact alignment: {masks}",
        )


class ExecuteRetreatFromDangerTests(unittest.TestCase):
    def test_steps_away_from_a_target_to_the_right(self) -> None:
        actor = _myself(world_x=100, world_y=50)
        target = replace(_enemy(world_x=150, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=LEFT, player2=0)

    def test_steps_away_from_a_target_to_the_left(self) -> None:
        actor = _myself(world_x=100, world_y=50)
        target = replace(_enemy(world_x=50, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)

    def test_holds_the_current_lane_while_retreating(self) -> None:
        actor = _myself(world_x=100, world_y=50)
        target = replace(_enemy(world_x=150, world_y=90), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        # Backing away moves on X only -- never toward the enemy's lane too.
        client.hold_buttons.assert_called_once_with(player1=LEFT, player2=0)

    def test_prefers_the_inferred_safe_spot(self) -> None:
        # inference.check_for_safe_spots already weighed the sidesteps
        # against the straight retreat (clearance from every live enemy,
        # lane/camera bounds, pits). When it produced one, the executor must
        # steer there rather than re-deciding "straight back on X".
        actor = _myself(world_x=100, world_y=50)
        target = replace(_enemy(world_x=150, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target, SafeSpot(actor_slot="P1", world_x=100, world_y=74)}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        # Pure sidestep: down the lane, no lateral component.
        client.hold_buttons.assert_called_once_with(player1=DOWN, player2=0)

    def test_ignores_a_safe_spot_belonging_to_the_partner(self) -> None:
        actor = _myself(world_x=100, world_y=50)
        target = replace(_enemy(world_x=150, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target, SafeSpot(actor_slot="P2", world_x=100, world_y=74)}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=LEFT, player2=0)

    def test_missing_actor_or_target_does_nothing(self) -> None:
        context: set = {_enemy()}
        verb = RetreatFromDanger(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, context, gamepad)

        client.hold_buttons.assert_not_called()


class ExecuteWalkToAdvanceStageTests(unittest.TestCase):
    def test_direction_right_holds_right(self) -> None:
        verb = WalkToAdvanceStage(actor_slot="P1", direction="right")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)

    def test_direction_left_holds_left(self) -> None:
        verb = WalkToAdvanceStage(actor_slot="P1", direction="left")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.hold_buttons.assert_called_once_with(player1=LEFT, player2=0)


class MovementDeadbandTests(unittest.TestCase):
    """The controller is a bang-bang actuator sampled every ~33 ms while the
    game walks the actor a couple of px per frame, so an exact-coordinate
    target is stepped over rather than landed on. Without a deadband the
    residual flips sign every tick and the actor vibrates left/right instead
    of travelling -- worst while moving vertically, where the X residual is
    the only thing still oscillating."""

    def test_does_not_steer_for_a_sub_step_x_residual(self) -> None:
        # Actor sits 3px from its stopping point on X (Axel stop_dx=46, enemy
        # at 149 -> stop at 103) but a full lane away: it should travel purely
        # down the lane, with no horizontal component at all.
        actor = _myself(world_x=100, world_y=40)
        target = _enemy(world_x=149, world_y=100)
        gamepad, client = _gamepad()

        execute_verb(
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"), {actor, target}, gamepad
        )

        client.hold_buttons.assert_called_once_with(player1=DOWN, player2=0)

    def test_straddling_the_stop_point_never_commands_opposite_directions(self) -> None:
        # The shake itself: two ticks a few px either side of the same
        # stopping point must not ask for LEFT then RIGHT.
        target = _enemy(world_x=149, world_y=40)
        masks = []
        for actor_x in (101, 105):
            actor = _myself(world_x=actor_x, world_y=40)
            gamepad, _ = _gamepad()
            execute_verb(
                WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
                {actor, target},
                gamepad,
            )
            masks.append(gamepad.held)

        self.assertFalse(
            any(m & LEFT for m in masks) and any(m & RIGHT for m in masks),
            f"opposite horizontal commands across adjacent ticks: {masks}",
        )


class StaleMovementHoldTests(unittest.TestCase):
    """``hold_buttons`` is a sticky latch and ``SharedGamepadState.press``
    re-arms it after the press, so a walk tick followed by an attack tick
    used to leave the actor still walking through the strike -- straight
    past the enemy and out of its own punch band, or over the pickup it had
    just pressed B to collect. Every press-only handler must drop the hold
    first (``execute._press``)."""

    def _assert_clears_hold(self, verb, context) -> None:
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)  # leftover from a previous walk tick
        client.hold_buttons.reset_mock()

        execute_verb(verb, context, gamepad)

        self.assertEqual(gamepad.held, 0)
        # The cleared latch also has to reach the host, not just the cache.
        self.assertIn(
            ((), {"player1": 0, "player2": 0}), client.hold_buttons.call_args_list
        )

    def test_punch_clears_a_leftover_walk_hold(self) -> None:
        self._assert_clears_hold(Punch(actor_slot="P1", target_slot="obj01"), set())

    def test_rear_attack_clears_a_leftover_walk_hold(self) -> None:
        self._assert_clears_hold(RearAttack(actor_slot="P1", target_slot="obj01"), set())

    def test_call_police_clears_a_leftover_walk_hold(self) -> None:
        self._assert_clears_hold(CallPolice(actor_slot="P1"), set())

    def test_collecting_a_pickup_clears_a_leftover_walk_hold(self) -> None:
        actor = _myself(world_x=100, world_y=100)
        pickup = HealthPickup(
            slot="item01", world_x=100, world_y=100, pickup_type=0x01, health_delta=40
        )
        self._assert_clears_hold(
            WalkToPickup(actor_slot="P1", target_slot="item01"), {actor, pickup}
        )

    def test_a_walk_whose_target_vanished_releases_instead_of_coasting(self) -> None:
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)
        client.hold_buttons.reset_mock()

        # Target no longer in the context (killed between verb and
        # execution) -- the handler must stop the actor, not let the stale
        # hold carry it onward indefinitely.
        execute_verb(
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"), set(), gamepad
        )

        self.assertEqual(gamepad.held, 0)
        client.hold_buttons.assert_called_once_with(player1=0, player2=0)


class ExecutePunchTests(unittest.TestCase):
    def test_punch_presses_button_b(self) -> None:
        verb = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_punch_is_unconditional_even_while_holding_an_enemy(self) -> None:
        # Supplex now owns the "already holding" case (see priority.py /
        # execute.py's state_machine_supplex); Punch always just presses B.
        actor = replace(_myself(), held_weapon_type=0x20)  # Garcia's type id
        verb = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_still_punches_while_holding_a_weapon(self) -> None:
        # could_punch no longer produces Punch while armed (that's
        # SwingBatOrPipe/StabWithKnifeOrBottle/SprayPepper's job now), but
        # execution itself is unconditional on whatever Verb it's given.
        actor = replace(_myself(), held_weapon_type=0x0A)  # baseball bat
        verb = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteSwingBatOrPipeTests(unittest.TestCase):
    def test_presses_button_b(self) -> None:
        verb = SwingBatOrPipe(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteStabWithKnifeOrBottleTests(unittest.TestCase):
    def test_presses_button_b(self) -> None:
        verb = StabWithKnifeOrBottle(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteSprayPepperTests(unittest.TestCase):
    def test_presses_button_b(self) -> None:
        verb = SprayPepper(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteCallPoliceTests(unittest.TestCase):
    def test_call_police_presses_button_a(self) -> None:
        verb = CallPolice(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=A, player2=0, frames=4)


class ExecuteJumpAttackTests(unittest.TestCase):
    def test_presses_jump_with_direction_when_grounded(self) -> None:
        actor = _myself(world_x=0, world_y=0, is_airborne=False)
        enemy = _enemy(world_x=50, world_y=0)
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, enemy}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C | RIGHT, player2=0, frames=3)

    def test_presses_punch_when_airborne(self) -> None:
        actor = _myself(world_x=0, world_y=0, is_airborne=True)
        enemy = _enemy(world_x=50, world_y=0)
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, enemy}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B | RIGHT, player2=0, frames=4)

    def test_missing_actor_does_nothing(self) -> None:
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_not_called()

    def test_no_target_does_not_hop_in_place(self) -> None:
        actor = _myself(is_airborne=False)
        verb = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_not_called()


class ExecuteGrabEnemyTests(unittest.TestCase):
    def test_walks_into_the_target_without_pressing_a_button(self) -> None:
        # $AAA0 only reports the grab contact code while the actor's outgoing
        # damage is zero, so pressing B here would produce a hit instead.
        actor = _myself(world_x=100, world_y=100)
        target = _enemy(world_x=130, world_y=100)
        verb = GrabEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, target}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)
        client.press_buttons.assert_not_called()

    def test_aims_at_the_enemy_itself_including_the_lane(self) -> None:
        actor = _myself(world_x=100, world_y=100)
        target = _enemy(world_x=130, world_y=108)
        verb = GrabEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, target}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT | DOWN, player2=0)

    def test_keeps_walking_in_once_inside_the_movement_deadband(self) -> None:
        # The contact test also needs the actor's *walking* attack box: an
        # actor standing still on top of the enemy never takes the hold, so
        # the deadband must fall back to the facing direction, not release.
        actor = _myself(world_x=100, world_y=100)
        target = _enemy(world_x=102, world_y=100)
        verb = GrabEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, target}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)

    def test_releases_when_the_target_is_gone(self) -> None:
        actor = _myself(world_x=100, world_y=100)
        verb = GrabEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)
        client.hold_buttons.reset_mock()

        execute_verb(verb, {actor}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=0, player2=0)


class ExecuteSupplexTests(unittest.TestCase):
    def test_presses_jump_from_front_hold(self) -> None:
        actor = _myself(action_state=0x60)
        verb = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C, player2=0, frames=4)

    def test_presses_punch_from_back_hold(self) -> None:
        actor = _myself(action_state=0x66)
        verb = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_presses_punch_as_fallback_for_other_action_state(self) -> None:
        actor = _myself(action_state=0x10)
        verb = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_facing_bit_is_cleared_before_comparison(self) -> None:
        actor = _myself(action_state=0x67)  # back hold, facing bit set
        verb = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteThrowKnifeTests(unittest.TestCase):
    def test_throw_knife_presses_button_b(self) -> None:
        verb = ThrowKnife(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteThrowPepperTests(unittest.TestCase):
    def test_throw_pepper_presses_button_b(self) -> None:
        verb = ThrowPepper(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteRearAttackTests(unittest.TestCase):
    def test_presses_b_and_c_together(self) -> None:
        verb = RearAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B | C, player2=0, frames=4)


class ExecuteCounterGrabTests(unittest.TestCase):
    def test_presses_c_from_held_state(self) -> None:
        actor = replace(
            _myself(),
            action_state=0x7A,
            combat_phase=CombatPhase.HELD_BY_ENEMY,
            action_flags=0,
        )
        verb = CounterGrab(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C, player2=0, frames=3)

    def test_presses_b_when_counter_window_open(self) -> None:
        actor = replace(
            _myself(),
            action_state=0x7A,
            combat_phase=CombatPhase.HELD_BY_ENEMY,
            action_flags=0x80,
        )
        verb = CounterGrab(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=3)


class ExecuteTechRecoverTests(unittest.TestCase):
    def test_presses_c_and_up_together(self) -> None:
        verb = TechRecover(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=C | UP, player2=0, frames=3)


class ExecuteOpenBreakableTests(unittest.TestCase):
    """One verb spanning the approach and the strike, switching on
    decide.in_smash_range.

    While still approaching: a Breakable is itself a solid obstacle, so
    walking to its exact center means walking into it from whatever angle a
    straight line happens to be, which can mean approaching from directly
    above/below and getting stuck. Stop just inside smash range on whichever
    side the actor already occupies instead."""

    def test_stops_short_of_the_breakables_exact_position(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, prop}, gamepad)

        # BREAKABLE_PUNCH_X=36, BREAKABLE_STOP_BUFFER=12 -> stop_dx=24, so
        # the actor approaches to x=76, never reaching the prop's x=100.
        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)

    def test_approaches_from_whichever_side_the_actor_is_already_on(self) -> None:
        actor = _myself(world_x=200, world_y=90)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, prop}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=LEFT, player2=0)

    def test_presses_b_once_inside_smash_range(self) -> None:
        # dx=32 is inside BREAKABLE_PUNCH_X (36). Under the old split verbs
        # this was where WalkToBreakable stopped holding and the actor had to
        # wait for SmashBreakable to win a later tick; one verb hits now.
        actor = _myself(world_x=68, world_y=90)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, prop}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B | RIGHT, player2=0, frames=4)

    def test_faces_the_prop_before_hitting_it(self) -> None:
        actor = _myself(world_x=120, world_y=90)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, prop}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B | LEFT, player2=0, frames=4)

    def test_missing_actor_or_target_does_nothing(self) -> None:
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)
        verb = OpenBreakable(actor_slot="P1", target_slot="obj09")
        gamepad, client = _gamepad()

        execute_verb(verb, {prop}, gamepad)

        client.hold_buttons.assert_not_called()

    def test_worst_case_deadband_stop_still_lands_in_smash_range(self) -> None:
        # Regression: _movement_mask releases the walk-in hold as soon as the
        # actor is within MOVE_DEADBAND_X of the approach's stop point, not
        # only once it has actually reached it -- so the real resting
        # distance from the prop can be (BREAKABLE_PUNCH_X -
        # BREAKABLE_STOP_BUFFER) + MOVE_DEADBAND_X. A buffer smaller than the
        # deadband (the old value, 4 < 5) let that worst case land one pixel
        # outside BREAKABLE_PUNCH_X: in_smash_range then stayed false
        # forever against a target that never moves to close the gap itself,
        # so the actor arrived and never threw a punch.
        worst_case_dx = (BREAKABLE_PUNCH_X - BREAKABLE_STOP_BUFFER) + MOVE_DEADBAND_X
        actor = _myself(world_x=100 - worst_case_dx, world_y=90)
        prop = Breakable(slot="obj09", world_x=100, world_y=90, type_id=0x40)

        self.assertTrue(in_smash_range(actor, prop))


class ExecuteMovementBreakableAvoidanceTests(unittest.TestCase):
    """Regression: _movement_mask must only dodge on-screen breakables.

    world_map tracks entities up to two screens beyond each camera edge for
    hunt-target lookahead, far past what's actually walkable. Without a
    camera filter, any breakable in that huge tracked radius could trip the
    dodge on a pure horizontal walk -- and since the dodge always steers
    toward smaller Y ("up") when the actor is in the lane's lower half (the
    common case), that made the AI drift up for reasons unrelated to
    anything on screen.
    """

    def test_dodges_a_breakable_that_is_actually_on_screen(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        prop = Breakable(slot="obj09", world_x=50, world_y=90, type_id=0x40)
        camera = CameraRange(left=0, right=200, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, target, prop, camera}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT | UP, player2=0)

    def test_ignores_a_breakable_far_outside_the_camera(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        prop = Breakable(slot="obj09", world_x=50, world_y=90, type_id=0x40)
        camera = CameraRange(left=200, right=400, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, target, prop, camera}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)


class ExecuteMovementPitAvoidanceTests(unittest.TestCase):
    """A Pit sitting on the walk path must be dodged, mirroring the existing
    Breakable-avoidance behavior above -- falling in costs a full life
    (player-health-lives-and-combat.md), so this must never be a no-op."""

    def test_dodges_a_pit_that_is_actually_on_screen(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        pit = Pit(world_x=45, lane_y=84, width=10, height=12)
        camera = CameraRange(left=0, right=200, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, target, pit, camera}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT | UP, player2=0)

    def test_ignores_a_pit_far_outside_the_camera(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        pit = Pit(world_x=45, lane_y=84, width=10, height=12)
        camera = CameraRange(left=200, right=400, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, target, pit, camera}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)

    def test_ignores_a_pit_not_on_the_path(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        # Pit is behind the actor, not between actor and target.
        pit = Pit(world_x=-50, lane_y=84, width=10, height=12)
        camera = CameraRange(left=-100, right=200, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        verb = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, target, pit, camera}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)


class ExecuteWalkToWeaponTests(unittest.TestCase):
    def test_holds_movement_when_far_from_weapon(self) -> None:
        actor = _myself(world_x=0, world_y=0)
        weapon = Weapon(slot="obj05", world_x=100, world_y=100, weapon_type=0x08)
        verb = WalkToWeapon(actor_slot="P1", target_slot="obj05")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, weapon}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT | DOWN, player2=0)

    def test_presses_punch_when_adjacent(self) -> None:
        actor = _myself(world_x=0, world_y=0)
        weapon = Weapon(slot="obj05", world_x=10, world_y=5, weapon_type=0x08)
        verb = WalkToWeapon(actor_slot="P1", target_slot="obj05")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, weapon}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_missing_actor_or_target_does_nothing(self) -> None:
        verb = WalkToWeapon(actor_slot="P1", target_slot="obj05")
        gamepad, client = _gamepad()

        execute_verb(verb, set(), gamepad)

        client.hold_buttons.assert_not_called()
        client.press_buttons.assert_not_called()


class ExecuteWalkToPickupTests(unittest.TestCase):
    def test_presses_punch_when_adjacent(self) -> None:
        actor = _myself(world_x=0, world_y=0)
        food = HealthPickup(
            slot="obj06", world_x=10, world_y=5, pickup_type=0x4B, health_delta=20
        )
        verb = WalkToPickup(actor_slot="P1", target_slot="obj06")
        gamepad, client = _gamepad()

        execute_verb(verb, {actor, food}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class NoRawMemoryWritesTests(unittest.TestCase):
    """execute.py / loop.py / priority.py must only ever steer the gamepad —
    never touch raw RAM writes."""

    def test_forbidden_symbols_absent_from_source(self) -> None:
        for module in (execute_module, loop_module, priority_module):
            source = inspect.getsource(module)
            self.assertNotIn("write_memory", source)
            self.assertNotIn("write_value", source)


if __name__ == "__main__":
    unittest.main()
