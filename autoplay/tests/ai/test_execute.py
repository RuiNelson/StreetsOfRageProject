import inspect
import unittest
from unittest.mock import MagicMock

from sor_autoplay.ai import execute as execute_module
from sor_autoplay.ai import loop as loop_module
from sor_autoplay.ai import priority as priority_module
from sor_autoplay.ai.attack_decisions import Punch
from sor_autoplay.ai.character import Myself
from sor_autoplay.ai.enemy import Enemy
from sor_autoplay.ai.execute import execute_decision, press_no_button
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.police_decision import CallPolice
from sor_autoplay.ai.walk_decisions import Sidestep, WalkToNearEnemy
from sor_autoplay.phases import CombatPhase

UP = 0x0001
DOWN = 0x0002
LEFT = 0x0004
RIGHT = 0x0008
A = 0x0010
B = 0x0020


def _myself(*, world_x: int = 0, world_y: int = 0) -> Myself:
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


class ExecuteSidestepTests(unittest.TestCase):
    def test_direction_up_holds_up(self) -> None:
        decision = Sidestep(actor_slot="P1", threat_slot="obj01", direction="up")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.hold_buttons.assert_called_once_with(player1=UP, player2=0)

    def test_direction_down_holds_down(self) -> None:
        decision = Sidestep(actor_slot="P1", threat_slot="obj01", direction="down")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.hold_buttons.assert_called_once_with(player1=DOWN, player2=0)


class ExecutePunchTests(unittest.TestCase):
    def test_punch_presses_button_b(self) -> None:
        decision = Punch(actor_slot="P1", target_slot="obj01")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=B, frames=4)


class ExecuteCallPoliceTests(unittest.TestCase):
    def test_call_police_presses_button_a(self) -> None:
        decision = CallPolice(actor_slot="P1")
        gamepad, client = _gamepad()

        execute_decision(decision, set(), gamepad)

        client.press_buttons.assert_called_once_with(player1=A, frames=4)


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
