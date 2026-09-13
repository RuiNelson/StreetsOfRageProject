"""Floor items the partner needs more -- the co-op item rules end to end.

User: "A IA só deve usar items de recuperação se estiver sem partner, ou se
tiver partner, a personagem dela precisar mais do item que o partner. O mesmo
para armas [...] (no caso de empate, tentar pegar)". Three pieces meet here:

- ``partner.item_is_the_partners``: who needs a given item more;
- ``reach.item_a_b_press_takes``: which item a grounded B press would pick
  up instead of striking (``$3136``);
- ``execute``'s partner pad, which turns such a press into a step off the
  item whenever that item is the partner's.
"""

import unittest
from unittest.mock import MagicMock

from sor_autoplay.ai import reach
from sor_autoplay.ai.execute import execute_tick
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.partner import item_is_the_partners
from sor_autoplay.ai.tokens import (
    CameraRange,
    Garcia,
    HealthPickup,
    LifePickup,
    Myself,
    Partner,
    Punch,
    ScorePickup,
    SpecialPickup,
    Stage,
    Weapon,
)
from sor_autoplay.phases import CombatPhase

UP = 0x0001
DOWN = 0x0002
LEFT = 0x0004
RIGHT = 0x0008
B = 0x0020
C = 0x0040


def make_myself(**overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=100,
        world_y=60,
        health=80,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=False,
        combat_phase=CombatPhase.NORMAL,
        action_state=0x02,
        is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


def make_partner(**overrides) -> Partner:
    fields = dict(
        slot="P2",
        player_index=2,
        character_id=2,
        character_name="Blaze",
        world_x=300,
        world_y=90,
        health=80,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=True,
        combat_phase=CombatPhase.NORMAL,
        action_state=0x02,
        is_airborne=False,
    )
    fields.update(overrides)
    return Partner(**fields)


def food(**overrides) -> HealthPickup:
    fields = dict(slot="obj05", world_x=100, world_y=60, pickup_type=0x4B, health_delta=20)
    fields.update(overrides)
    return HealthPickup(**fields)


class ItemNeedTests(unittest.TestCase):
    """``item_is_the_partners``: the partner's to take, or the actor's."""

    def test_food_is_the_actors_only_while_it_is_strictly_the_hurter(self):
        cases = [
            (50.0, 25.0, True),  # partner hurter: theirs
            (25.0, 50.0, False),  # actor hurter: the actor's
            (50.0, 50.0, True),  # equally hurt: left for the partner
        ]
        for mine, theirs, partners in cases:
            with self.subTest(mine=mine, theirs=theirs):
                self.assertIs(
                    item_is_the_partners(
                        make_myself(health_percent=mine),
                        make_partner(health_percent=theirs),
                        food(),
                    ),
                    partners,
                )

    def test_a_weapon_is_the_partners_only_while_they_are_strictly_worse_armed(self):
        knife = Weapon(slot="obj04", world_x=100, world_y=60, weapon_type=0x08)
        cases = [
            (0, 0, False),  # both unarmed: a tie is the actor's to try
            (0x0C, 0, True),  # pepper against nothing: the partner needs it more
            (0, 0x0B, False),  # unarmed against a pipe: the actor needs it more
            (0x0A, 0x0B, False),  # bat against pipe: same rank, a tie
            (0x0A, 0x09, True),  # bat against bottle: the partner is worse armed
        ]
        for mine, theirs, partners in cases:
            with self.subTest(mine=hex(mine), theirs=hex(theirs)):
                self.assertIs(
                    item_is_the_partners(
                        make_myself(held_weapon_type=mine),
                        make_partner(held_weapon_type=theirs),
                        knife,
                    ),
                    partners,
                )

    def test_a_1up_goes_to_the_one_with_fewer_lives(self):
        life = LifePickup(slot="obj06", world_x=100, world_y=60, pickup_type=0x4C)
        self.assertTrue(item_is_the_partners(make_myself(), make_partner(lives=1), life))
        self.assertFalse(item_is_the_partners(make_myself(), make_partner(lives=3), life))

    def test_special_and_score_are_nobodys(self):
        special = SpecialPickup(slot="obj07", world_x=100, world_y=60, pickup_type=0x4F)
        score = ScorePickup(slot="obj08", world_x=100, world_y=60, pickup_type=0x3F, points=3000)
        hurt = make_partner(health_percent=10.0, lives=0)
        for item in (special, score):
            with self.subTest(item=type(item).__name__):
                self.assertFalse(item_is_the_partners(make_myself(), hurt, item))


class BPressPickupBoxTests(unittest.TestCase):
    """``reach.item_a_b_press_takes`` -- ``$3136``'s box and slot order."""

    def test_an_item_inside_the_box_is_what_the_press_takes(self):
        for dx, dy in ((0, 0), (20, 0), (-20, 16), (12, -16)):
            with self.subTest(dx=dx, dy=dy):
                item = food(world_x=100 + dx, world_y=60 + dy)
                self.assertIs(reach.item_a_b_press_takes({make_myself(), item}, make_myself()), item)

    def test_an_item_outside_the_box_is_not(self):
        for dx, dy in ((21, 0), (0, 17), (-21, -17)):
            with self.subTest(dx=dx, dy=dy):
                item = food(world_x=100 + dx, world_y=60 + dy)
                self.assertIsNone(reach.item_a_b_press_takes({item}, make_myself()))

    def test_the_first_slot_wins_not_the_nearest(self):
        # No distance ranking in $3136: the object table is scanned in order.
        near = food(slot="obj09", world_x=100, world_y=60)
        far = Weapon(slot="obj03", world_x=118, world_y=70, weapon_type=0x0B)
        self.assertIs(reach.item_a_b_press_takes({near, far}, make_myself()), far)

    def test_a_worn_weapon_is_skipped(self):
        worn = Weapon(slot="obj03", world_x=100, world_y=60, weapon_type=0x0B, wear=3)
        self.assertIsNone(reach.item_a_b_press_takes({worn}, make_myself()))

    def test_an_airborne_b_is_the_kick_not_a_pickup(self):
        self.assertIsNone(reach.item_a_b_press_takes({food()}, make_myself(is_airborne=True)))


class PartnerPadItemGuardTests(unittest.TestCase):
    """A punch thrown over the partner's food becomes a step off it."""

    def _tick(self, *tokens):
        client = MagicMock()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        context = {
            CameraRange(left=0, right=600, top=16, bottom=112),
            Stage(level_index=0, direction="right"),
            Garcia(
                slot="obj01",
                type_id=0x20,
                world_x=130,
                world_y=60,
                health=10,
                combat_phase=CombatPhase.NORMAL,
                targets_player=1,
                facing_left=True,
            ),
            *tokens,
        }
        execute_tick(Punch(actor_slot="P1", target_slot="obj01"), context, gamepad)
        return client

    @staticmethod
    def _pressed_b(client) -> bool:
        return any(call.kwargs["player1"] & B for call in client.press_buttons.call_args_list)

    @staticmethod
    def _held(client) -> int:
        return client.hold_buttons.call_args.kwargs["player1"]

    def test_the_partners_food_underfoot_turns_the_punch_into_a_step(self):
        client = self._tick(make_myself(), make_partner(health_percent=25.0), food())
        self.assertFalse(self._pressed_b(client))
        self.assertTrue(self._held(client) & (UP | DOWN | LEFT | RIGHT))

    def test_the_step_never_carries_b(self):
        client = self._tick(make_myself(), make_partner(health_percent=25.0), food())
        for call in client.hold_buttons.call_args_list:
            self.assertFalse(call.kwargs["player1"] & (B | C))

    def test_food_the_actor_needs_more_is_still_punched_over(self):
        # The press picks it up -- and that is allowed: the actor is the hurter.
        client = self._tick(
            make_myself(health=20, health_percent=25.0), make_partner(), food()
        )
        self.assertTrue(self._pressed_b(client))

    def test_without_a_partner_nothing_changes(self):
        client = self._tick(make_myself(), food())
        self.assertTrue(self._pressed_b(client))

    def test_an_item_nobody_claims_does_not_stop_the_punch(self):
        score = ScorePickup(slot="obj08", world_x=100, world_y=60, pickup_type=0x3F, points=3000)
        client = self._tick(make_myself(), make_partner(health_percent=25.0), score)
        self.assertTrue(self._pressed_b(client))

    def test_food_outside_the_box_does_not_stop_the_punch(self):
        client = self._tick(
            make_myself(), make_partner(health_percent=25.0), food(world_x=70, world_y=60)
        )
        self.assertTrue(self._pressed_b(client))


if __name__ == "__main__":
    unittest.main()
