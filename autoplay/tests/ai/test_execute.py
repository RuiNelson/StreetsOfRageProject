import inspect
import unittest
from dataclasses import replace
from unittest.mock import MagicMock

from sor_autoplay.ai import execute as execute_module
from sor_autoplay.ai import loop as loop_module
from sor_autoplay.ai import priority as priority_module
from sor_autoplay.ai.tokens import (
    CounterGrab,
    JumpAttack,
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
from sor_autoplay.ai.execute import execute_decision, press_no_button
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.tokens import Breakable, Pit
from sor_autoplay.ai.tokens import HealthPickup, Weapon
from sor_autoplay.ai.tokens import CallPolice
from sor_autoplay.ai.tokens import (
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
        actor = _myself(world_x=0, world_y=0)
        target = _enemy(world_x=50, world_y=50)
        context = {actor, target}
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT | DOWN, player2=0)

    def test_walks_toward_enemy_to_the_left_and_above(self) -> None:
        actor = _myself(world_x=50, world_y=50)
        target = _enemy(world_x=0, world_y=0)
        context = {actor, target}
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=LEFT | UP, player2=0)

    def test_standing_on_the_enemy_steps_back_to_punch_range(self) -> None:
        # Never walk onto the enemy — stop just inside punch_outer_x.
        actor = _myself(world_x=10, world_y=10)
        target = _enemy(world_x=10, world_y=10)
        context = {actor, target}
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=LEFT, player2=0)

    def test_stops_just_inside_punch_range_instead_of_overlapping_enemy(self) -> None:
        # Axel: punch_outer_x=50, stop buffer 4 -> stop_dx=46. Placing the
        # actor exactly at that stopping x (relative to the enemy at x=50)
        # means it has already arrived and should hold no further movement.
        actor = _myself(world_x=4, world_y=50)
        target = _enemy(world_x=50, world_y=50)
        context = {actor, target}
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)  # start non-zero so a hold(0) call is observable
        client.hold_buttons.reset_mock()

        execute_decision(decision, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=0, player2=0)

    def test_missing_actor_or_target_does_nothing(self) -> None:
        context: set = {_enemy()}
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, context, gamepad)

        client.hold_buttons.assert_not_called()

    def test_sidesteps_a_dangerous_enemys_exact_lane_while_still_far_away(self) -> None:
        actor = _myself(world_x=0, world_y=50)
        target = replace(_enemy(world_x=200, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, context, gamepad)

        # Same lane (dy=0) and far away (dx=200) from an actively attacking
        # enemy -> step off its lane instead of walking straight down it.
        client.hold_buttons.assert_called_once_with(player1=RIGHT | DOWN, player2=0)

    def test_does_not_sidestep_a_dangerous_enemy_once_close_enough_to_punch(self) -> None:
        # dx=46 == stop_dx: already at the stopping point, so the actor
        # aligns for the punch instead of sidestepping.
        actor = _myself(world_x=-6, world_y=50)
        target = replace(_enemy(world_x=40, world_y=50), combat_phase=CombatPhase.ATTACKING)
        context = {actor, target}
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()
        gamepad.hold(RIGHT)  # start non-zero so a hold(0) call is observable
        client.hold_buttons.reset_mock()

        execute_decision(decision, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=0, player2=0)

    def test_does_not_sidestep_an_enemy_that_is_not_dangerous(self) -> None:
        actor = _myself(world_x=0, world_y=50)
        target = _enemy(world_x=200, world_y=50)  # NORMAL phase
        context = {actor, target}
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, context, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)


class ExecuteWalkToAdvanceStageTests(unittest.TestCase):
    def test_direction_right_holds_right(self) -> None:
        decision = WalkToAdvanceStage(actor_slot="P1", direction="right")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)

    def test_direction_left_holds_left(self) -> None:
        decision = WalkToAdvanceStage(actor_slot="P1", direction="left")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.hold_buttons.assert_called_once_with(player1=LEFT, player2=0)


class ExecutePunchTests(unittest.TestCase):
    def test_punch_presses_button_b(self) -> None:
        decision = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_punch_is_unconditional_even_while_holding_an_enemy(self) -> None:
        # Supplex now owns the "already holding" case (see priority.py /
        # execute.py's _execute_supplex); Punch always just presses B.
        actor = replace(_myself(), held_weapon_type=0x20)  # Garcia's type id
        decision = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_still_punches_while_holding_a_weapon(self) -> None:
        # should_punch no longer produces Punch while armed (that's
        # SwingBatOrPipe/StabWithKnifeOrBottle/SprayPepper's job now), but
        # execution itself is unconditional on whatever Decision it's given.
        actor = replace(_myself(), held_weapon_type=0x0A)  # baseball bat
        decision = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteSwingBatOrPipeTests(unittest.TestCase):
    def test_presses_button_b(self) -> None:
        decision = SwingBatOrPipe(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteStabWithKnifeOrBottleTests(unittest.TestCase):
    def test_presses_button_b(self) -> None:
        decision = StabWithKnifeOrBottle(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteSprayPepperTests(unittest.TestCase):
    def test_presses_button_b(self) -> None:
        decision = SprayPepper(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteCallPoliceTests(unittest.TestCase):
    def test_call_police_presses_button_a(self) -> None:
        decision = CallPolice(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=A, player2=0, frames=4)


class ExecuteJumpAttackTests(unittest.TestCase):
    def test_presses_jump_with_direction_when_grounded(self) -> None:
        actor = _myself(world_x=0, world_y=0, is_airborne=False)
        enemy = _enemy(world_x=50, world_y=0)
        decision = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor, enemy}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C | RIGHT, player2=0, frames=3)

    def test_presses_punch_when_airborne(self) -> None:
        actor = _myself(world_x=0, world_y=0, is_airborne=True)
        enemy = _enemy(world_x=50, world_y=0)
        decision = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor, enemy}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B | RIGHT, player2=0, frames=4)

    def test_missing_actor_does_nothing(self) -> None:
        decision = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_not_called()

    def test_no_target_does_not_hop_in_place(self) -> None:
        actor = _myself(is_airborne=False)
        decision = JumpAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor}, gamepad)

        client.press_buttons.assert_not_called()


class ExecuteSupplexTests(unittest.TestCase):
    def test_presses_jump_from_front_hold(self) -> None:
        actor = _myself(action_state=0x60)
        decision = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C, player2=0, frames=4)

    def test_presses_punch_from_back_hold(self) -> None:
        actor = _myself(action_state=0x66)
        decision = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_presses_punch_as_fallback_for_other_action_state(self) -> None:
        actor = _myself(action_state=0x10)
        decision = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_facing_bit_is_cleared_before_comparison(self) -> None:
        actor = _myself(action_state=0x67)  # back hold, facing bit set
        decision = Supplex(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteThrowKnifeTests(unittest.TestCase):
    def test_throw_knife_presses_button_b(self) -> None:
        decision = ThrowKnife(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteThrowPepperTests(unittest.TestCase):
    def test_throw_pepper_presses_button_b(self) -> None:
        decision = ThrowPepper(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)


class ExecuteRearAttackTests(unittest.TestCase):
    def test_presses_b_and_c_together(self) -> None:
        decision = RearAttack(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B | C, player2=0, frames=4)


class ExecuteCounterGrabTests(unittest.TestCase):
    def test_presses_c_from_held_state(self) -> None:
        actor = replace(
            _myself(),
            action_state=0x7A,
            combat_phase=CombatPhase.HELD_BY_ENEMY,
            action_flags=0,
        )
        decision = CounterGrab(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=C, player2=0, frames=3)

    def test_presses_b_when_counter_window_open(self) -> None:
        actor = replace(
            _myself(),
            action_state=0x7A,
            combat_phase=CombatPhase.HELD_BY_ENEMY,
            action_flags=0x80,
        )
        decision = CounterGrab(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=3)


class ExecuteTechRecoverTests(unittest.TestCase):
    def test_presses_c_and_up_together(self) -> None:
        decision = TechRecover(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=C | UP, player2=0, frames=3)


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
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor, target, prop, camera}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT | UP, player2=0)

    def test_ignores_a_breakable_far_outside_the_camera(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        prop = Breakable(slot="obj09", world_x=50, world_y=90, type_id=0x40)
        camera = CameraRange(left=200, right=400, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor, target, prop, camera}, gamepad)

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
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor, target, pit, camera}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT | UP, player2=0)

    def test_ignores_a_pit_far_outside_the_camera(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        pit = Pit(world_x=45, lane_y=84, width=10, height=12)
        camera = CameraRange(left=200, right=400, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor, target, pit, camera}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)

    def test_ignores_a_pit_not_on_the_path(self) -> None:
        actor = _myself(world_x=0, world_y=90)
        # Pit is behind the actor, not between actor and target.
        pit = Pit(world_x=-50, lane_y=84, width=10, height=12)
        camera = CameraRange(left=-100, right=200, top=0, bottom=112)
        target = _enemy(world_x=100, world_y=90)
        decision = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor, target, pit, camera}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=0)


class ExecuteWalkToWeaponTests(unittest.TestCase):
    def test_holds_movement_when_far_from_weapon(self) -> None:
        actor = _myself(world_x=0, world_y=0)
        weapon = Weapon(slot="obj05", world_x=100, world_y=100, weapon_type=0x08)
        decision = WalkToWeapon(actor_slot="P1", target_slot="obj05")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor, weapon}, gamepad)

        client.hold_buttons.assert_called_once_with(player1=RIGHT | DOWN, player2=0)

    def test_presses_punch_when_adjacent(self) -> None:
        actor = _myself(world_x=0, world_y=0)
        weapon = Weapon(slot="obj05", world_x=10, world_y=5, weapon_type=0x08)
        decision = WalkToWeapon(actor_slot="P1", target_slot="obj05")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor, weapon}, gamepad)

        client.press_buttons.assert_called_once_with(player1=B, player2=0, frames=4)

    def test_missing_actor_or_target_does_nothing(self) -> None:
        decision = WalkToWeapon(actor_slot="P1", target_slot="obj05")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.hold_buttons.assert_not_called()
        client.press_buttons.assert_not_called()


class ExecuteWalkToPickupTests(unittest.TestCase):
    def test_presses_punch_when_adjacent(self) -> None:
        actor = _myself(world_x=0, world_y=0)
        food = HealthPickup(
            slot="obj06", world_x=10, world_y=5, pickup_type=0x4B, health_delta=20
        )
        decision = WalkToPickup(actor_slot="P1", target_slot="obj06")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor, food}, gamepad)

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
