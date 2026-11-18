"""Items underfoot: what a press picks up, and when it must not.

``$3136`` turns any grounded B beside a floor item into a pickup, and takes
the first eligible item in object-table slot order, not the one walked to
(``reach.item_a_press_takes``). Four pieces:

- ``decide.item_take_is_harmful``: which takes do harm (the partner's item,
  a weapon no better than the one in hand, food or a 1UP the fight leaves);
- ``execute``'s pad: a strike over such an item steps off it first, with or
  without a partner;
- ``decide.pickup_stand``: where a walk to an item stands so the press takes
  that item and not a harmful lower-slot one beside it;
- ``decide.could_walk_to_weapon``: the nearest weapon of each rank.
"""

import unittest
from unittest.mock import MagicMock

from sor_ai.ai.decide import (
    could_walk_to_pickup,
    could_walk_to_weapon,
    item_take_is_harmful,
    pickup_stand,
)
from sor_ai.ai.execute import execute_tick
from sor_ai.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_ai.ai.tokens import (
    Antonio,
    CameraRange,
    DebugNoFood,
    Garcia,
    HealthPickup,
    MeleeWeaponAttack,
    Myself,
    Partner,
    Punch,
    ScorePickup,
    Stage,
    WalkToPickup,
    WalkToWeapon,
    Weapon,
)
from sor_ai.phases import CombatPhase

LEFT = 0x0004
RIGHT = 0x0008
DIRECTIONS = 0x000F
B = 0x0020

KNIFE, BOTTLE, BAT = 0x08, 0x09, 0x0A
CAMERA = CameraRange(left=0, right=600, top=16, bottom=112)
STAGE = Stage(level_index=0, direction="right")


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
        world_x=400,
        world_y=60,
        health=20,
        health_percent=25.0,
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


def food(slot="obj05", **overrides) -> HealthPickup:
    fields = dict(slot=slot, world_x=100, world_y=60, pickup_type=0x4B, health_delta=20)
    fields.update(overrides)
    return HealthPickup(**fields)


def gem(slot="obj07", **overrides) -> ScorePickup:
    fields = dict(slot=slot, world_x=112, world_y=60, pickup_type=0x4E, points=1000)
    fields.update(overrides)
    return ScorePickup(**fields)


def weapon(slot="obj04", weapon_type=BOTTLE, **overrides) -> Weapon:
    fields = dict(slot=slot, world_x=100, world_y=60, weapon_type=weapon_type)
    fields.update(overrides)
    return Weapon(**fields)


def garcia(world_x=130) -> Garcia:
    return Garcia(
        slot="obj01",
        type_id=0x20,
        world_x=world_x,
        world_y=60,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
    )


class ItemTakeIsHarmfulTests(unittest.TestCase):
    def test_a_weapon_no_better_than_the_one_in_hand(self) -> None:
        actor = make_myself(held_weapon_type=KNIFE)
        for floor in (BOTTLE, KNIFE):
            with self.subTest(floor=hex(floor)):
                self.assertTrue(item_take_is_harmful({actor}, actor, weapon(weapon_type=floor)))

    def test_a_better_weapon_or_any_weapon_bare_handed_is_fine(self) -> None:
        armed = make_myself(held_weapon_type=BOTTLE)
        self.assertFalse(item_take_is_harmful({armed}, armed, weapon(weapon_type=KNIFE)))
        bare = make_myself()
        self.assertFalse(item_take_is_harmful({bare}, bare, weapon(weapon_type=BOTTLE)))

    def test_any_weapon_where_the_plan_refuses_one(self) -> None:
        antonio = Antonio(
            slot="obj02", type_id=0x56, world_x=300, world_y=60, health=40,
            combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=True,
        )
        actor = make_myself()
        self.assertTrue(item_take_is_harmful({actor, antonio}, actor, weapon()))

    def test_food_under_no_food(self) -> None:
        actor = make_myself(health=40, health_percent=50.0)
        self.assertTrue(item_take_is_harmful({actor, DebugNoFood()}, actor, food()))
        self.assertFalse(item_take_is_harmful({actor}, actor, food()))

    def test_the_partners_food(self) -> None:
        actor = make_myself()
        self.assertTrue(item_take_is_harmful({actor, make_partner()}, actor, food()))

    def test_a_score_pickup_never(self) -> None:
        actor = make_myself()
        self.assertFalse(item_take_is_harmful({actor, make_partner(), DebugNoFood()}, actor, gem()))


class StrikeOverAnItemTests(unittest.TestCase):
    """One player: a strike over an item it must not take steps off it."""

    def _tick(self, verb, *tokens) -> MagicMock:
        client = MagicMock()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        execute_tick(verb, {CAMERA, STAGE, garcia(), *tokens}, gamepad)
        return client

    @staticmethod
    def _pressed_b(client) -> bool:
        return any(call.kwargs["buttons"] & B for call in client.queue_press_buttons.call_args_list)

    @staticmethod
    def _held(client) -> int:
        return client.hold_buttons.call_args.kwargs["player1"]

    def test_an_armed_swing_over_a_worse_weapon_steps_off(self) -> None:
        client = self._tick(
            MeleeWeaponAttack(actor_slot="P1", target_slot="obj01", weapon_type=KNIFE),
            make_myself(held_weapon_type=KNIFE),
            weapon(weapon_type=BOTTLE, world_x=104),
        )
        self.assertFalse(self._pressed_b(client))
        self.assertTrue(self._held(client) & DIRECTIONS)

    def test_a_punch_over_food_under_no_food_steps_off(self) -> None:
        client = self._tick(
            Punch(actor_slot="P1", target_slot="obj01"),
            make_myself(health=40, health_percent=50.0),
            food(),
            DebugNoFood(),
        )
        self.assertFalse(self._pressed_b(client))

    def test_a_punch_over_an_item_it_may_take_still_presses(self) -> None:
        client = self._tick(Punch(actor_slot="P1", target_slot="obj01"), make_myself(), gem(world_x=100))
        self.assertTrue(self._pressed_b(client))

    def test_a_held_actor_is_never_redirected(self) -> None:
        # CounterGrab's B comes from a hold, where $3136 is not reached.
        from sor_ai.ai.execute import _redirect_b_press

        actor = make_myself(combat_phase=CombatPhase.HELD_BY_ENEMY, held_weapon_type=KNIFE)
        self.assertIsNone(_redirect_b_press({actor, weapon(weapon_type=BOTTLE)}, actor, B))
        free = make_myself(held_weapon_type=KNIFE)
        self.assertIsNotNone(_redirect_b_press({free, weapon(weapon_type=BOTTLE)}, free, B))


class PickupStandTests(unittest.TestCase):
    def test_no_blocker_is_the_targets_own_reach(self) -> None:
        actor = make_myself(world_x=60)
        target = gem()
        self.assertEqual(pickup_stand({actor, target, CAMERA, STAGE}, actor, target), (94, 60))

    def test_the_partners_food_beside_the_target_moves_the_stand_off_its_box(self) -> None:
        actor = make_myself(world_x=60)
        target = gem(world_x=112)
        context = {actor, make_partner(), food(world_x=96), target, CAMERA, STAGE}
        x, y = pickup_stand(context, actor, target)
        self.assertGreater(abs(x - 96), 20)
        self.assertLessEqual(abs(x - 112), 18)

    def test_a_higher_slot_item_is_no_blocker(self) -> None:
        # $3136 takes the lower slot first: the target is taken before it.
        actor = make_myself(world_x=60)
        target = gem(slot="obj03", world_x=112)
        context = {actor, make_partner(), food(slot="obj09", world_x=96), target, CAMERA, STAGE}
        self.assertEqual(pickup_stand(context, actor, target), (94, 60))

    def test_a_blocker_on_top_of_the_target_leaves_no_stand(self) -> None:
        actor = make_myself(world_x=60)
        target = gem(world_x=100)
        context = {actor, make_partner(), food(world_x=100), target, CAMERA, STAGE}
        self.assertIsNone(pickup_stand(context, actor, target))
        self.assertEqual(could_walk_to_pickup(context), set())

    def test_the_walk_presses_only_where_the_press_takes_the_target(self) -> None:
        client = MagicMock()
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        actor = make_myself(world_x=100)  # the gem in reach, the food in the box too
        context = {actor, make_partner(), food(world_x=96), gem(world_x=112), CAMERA, STAGE}
        for _ in range(4):  # the axis ramps over a few ticks
            execute_tick(WalkToPickup(actor_slot="P1", target_slot="obj07"), context, gamepad)
        self.assertFalse(client.queue_press_buttons.called)
        self.assertTrue(client.hold_buttons.call_args.kwargs["player1"] & RIGHT)


class NearestWeaponOfARankTests(unittest.TestCase):
    def test_two_bats_the_nearer_wins_whatever_the_slot(self) -> None:
        actor = make_myself(world_x=100)
        near = weapon(slot="obj12", weapon_type=BAT, world_x=120)
        far = weapon(slot="obj04", weapon_type=BAT, world_x=400)
        verbs = could_walk_to_weapon({actor, near, far, CAMERA, STAGE})
        self.assertEqual(verbs, {WalkToWeapon(actor_slot="P1", target_slot="obj12")})

    def test_one_per_rank_so_the_better_one_is_still_ranked(self) -> None:
        actor = make_myself(world_x=100)
        bat = weapon(slot="obj12", weapon_type=BAT, world_x=120)
        knife = weapon(slot="obj04", weapon_type=KNIFE, world_x=400)
        verbs = could_walk_to_weapon({actor, bat, knife, CAMERA, STAGE})
        self.assertEqual({verb.target_slot for verb in verbs}, {"obj12", "obj04"})

    def test_equidistant_twins_break_the_tie_by_slot(self) -> None:
        actor = make_myself(world_x=100)
        left = weapon(slot="obj12", weapon_type=BAT, world_x=60)
        right = weapon(slot="obj04", weapon_type=BAT, world_x=140)
        verbs = could_walk_to_weapon({actor, left, right, CAMERA, STAGE})
        self.assertEqual(verbs, {WalkToWeapon(actor_slot="P1", target_slot="obj04")})


if __name__ == "__main__":
    unittest.main()
