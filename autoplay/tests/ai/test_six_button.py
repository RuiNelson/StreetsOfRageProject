"""The 6-button layout (``--altControls``): which physical button each press uses.

``SixButtonLayout`` swaps the presses that differ -- the rear attack is A, the
police special X, a pickup Y, the knife throw Z -- and B stops picking things
up. Without the token every press is the original three-button scheme's.
"""

import unittest
from unittest.mock import MagicMock

from sor_ai.ai.execute import execute_verb
from sor_ai.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_ai.ai.reach import item_a_b_press_takes
from sor_ai.ai.tokens import (
    CallPolice,
    HealthPickup,
    RearAttack,
    SixButtonLayout,
    ThrowKnife,
    ThrowPepper,
    WalkToPickup,
    WalkToWeapon,
    Weapon,
)
from tests.ai.test_execute import _enemy, _myself

A, B, C = 0x0010, 0x0020, 0x0040
X, Y, Z = 0x0100, 0x0200, 0x0400


def _pad() -> tuple[VirtualGamepad, MagicMock]:
    client = MagicMock()
    return VirtualGamepad(SharedGamepadState(client), player_index=1), client


def _pressed(verb, context) -> int:
    gamepad, client = _pad()
    execute_verb(verb, context, gamepad)
    client.queue_press_buttons.assert_called_once()
    return client.queue_press_buttons.call_args.kwargs["buttons"]


class SixButtonPressTests(unittest.TestCase):
    def test_rear_attack_is_a_on_six_buttons_and_the_chord_otherwise(self):
        verb = RearAttack(actor_slot="P1", target_slot="obj01")
        self.assertEqual(_pressed(verb, set()), B | C)
        self.assertEqual(_pressed(verb, {SixButtonLayout()}), A)

    def test_police_is_x_on_six_buttons_and_a_otherwise(self):
        verb = CallPolice(actor_slot="P1")
        self.assertEqual(_pressed(verb, set()), A)
        self.assertEqual(_pressed(verb, {SixButtonLayout()}), X)

    def test_pickup_is_y_on_six_buttons_and_b_otherwise(self):
        actor = _myself(world_x=0, world_y=0)
        weapon = Weapon(slot="obj05", world_x=10, world_y=5, weapon_type=0x08)
        verb = WalkToWeapon(actor_slot="P1", target_slot="obj05")
        self.assertEqual(_pressed(verb, {actor, weapon}), B)
        self.assertEqual(_pressed(verb, {actor, weapon, SixButtonLayout()}), Y)

        food = HealthPickup(slot="item01", world_x=0, world_y=0, pickup_type=0x01, health_delta=40)
        verb = WalkToPickup(actor_slot="P1", target_slot="item01")
        self.assertEqual(_pressed(verb, {actor, food}), B)
        self.assertEqual(_pressed(verb, {actor, food, SixButtonLayout()}), Y)

    def test_knife_throw_is_z_but_the_pepper_stays_b(self):
        knife = ThrowKnife(actor_slot="P1", target_slot="obj01")
        pepper = ThrowPepper(actor_slot="P1", target_slot="obj01")
        self.assertEqual(_pressed(knife, set()), B)
        self.assertEqual(_pressed(knife, {SixButtonLayout()}), Z)
        self.assertEqual(_pressed(pepper, {SixButtonLayout()}), B)

    def test_the_knife_throw_still_faces_the_target(self):
        actor = _myself(world_x=100, world_y=0)
        target = _enemy(world_x=300, world_y=0)
        self.assertEqual(
            _pressed(
                ThrowKnife(actor_slot="P1", target_slot=target.slot),
                {actor, target, SixButtonLayout()},
            ),
            Z | 0x0008,
        )


class BPressPickupTests(unittest.TestCase):
    def test_b_takes_an_item_underfoot_only_on_three_buttons(self):
        actor = _myself(world_x=0, world_y=0)
        food = HealthPickup(slot="item01", world_x=2, world_y=0, pickup_type=0x01, health_delta=40)
        self.assertIs(item_a_b_press_takes({actor, food}, actor), food)
        self.assertIsNone(item_a_b_press_takes({actor, food, SixButtonLayout()}, actor))


if __name__ == "__main__":
    unittest.main()
