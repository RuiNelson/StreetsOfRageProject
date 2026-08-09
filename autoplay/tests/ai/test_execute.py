import inspect
import unittest
from dataclasses import replace
from unittest.mock import MagicMock

from sor_autoplay.ai import execute as execute_module
from sor_autoplay.ai import loop as loop_module
from sor_autoplay.ai import priority as priority_module
from sor_autoplay.ai.attack_decisions import (
    CounterGrab,
    JumpAttack,
    Punch,
    RearAttack,
    Supplex,
    ThrowKnife,
)
from sor_autoplay.ai.character import Myself
from sor_autoplay.ai.enemy import Enemy
from sor_autoplay.ai.essential import CameraRange
from sor_autoplay.ai.execute import execute_decision, press_no_button
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.hazard_tokens import Breakable
from sor_autoplay.ai.pickup_tokens import HealthPickup, Weapon
from sor_autoplay.ai.police_decision import CallPolice
from sor_autoplay.ai.walk_decisions import (
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

    def test_same_position_holds_no_direction(self) -> None:
        actor = _myself(world_x=10, world_y=10)
        target = _enemy(world_x=10, world_y=10)
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
        actor = replace(_myself(), held_weapon_type=0x0A)  # baseball bat
        decision = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, {actor}, gamepad)

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
