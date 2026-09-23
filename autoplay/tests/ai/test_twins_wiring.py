"""EngageTwins, wired through the pipeline.

``test_twins`` pins the ROM model and the plan; this pins who owns the twins
in ``decide`` (every generic verb stands down for them), what is refused
while they live (user: "Do not call the police. Do not use recovery items" --
not even as fallbacks), how the engage ranks, and what ``execute`` presses.
"""

import unittest
from unittest.mock import MagicMock

from sor_autoplay.ai import twins as model
from sor_autoplay.ai.decide import (
    could_call_police,
    could_engage_twins,
    could_grab_enemy,
    could_jump_attack,
    could_punch,
    could_rear_attack,
    could_walk_to_near_enemy,
    could_walk_to_pickup,
    live_twins,
)
from sor_autoplay.ai.execute import execute_verb
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import (
    CameraRange,
    EngageTwins,
    HealthPickup,
    Myself,
    Onihime,
    Verb,
    find_all,
)
from sor_autoplay.phases import CombatPhase

CAM_X = 5056
CAMERA = CameraRange(left=CAM_X + 0x20, right=CAM_X + 0x120, top=0, bottom=112)
EDGE = CAM_X + 0x120
UP, DOWN, LEFT, RIGHT, A, B, C = 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040


def _infer(generator):
    return lambda context: generator(generate_inference_tokens(set(context)))


def _myself(world_x: int = EDGE, world_y: int = 60, **overrides) -> Myself:
    fields = dict(
        slot="P1", player_index=1, character_id=2, character_name="Blaze",
        world_x=world_x, world_y=world_y, world_z=160, ground_z=160, health=80,
        health_percent=100.0, lives=3, specials=1, held_weapon_type=0, facing_left=False,
        combat_phase=CombatPhase.NORMAL, action_state=0x02, is_airborne=False,
        fine_x=float(world_x), fine_y=float(world_y),
    )
    fields.update(overrides)
    return Myself(**fields)


def _twin(world_x: int, world_y: int = 60, *, slot: str = "obj01", grab: bool = True, **overrides) -> Onihime:
    fields = dict(
        slot=slot, type_id=0x58, world_x=world_x, world_y=world_y, health=32,
        combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=False,
        primary_state=model.PRIMARY_ACTIVE, tactical=1, pair_role=2 if grab else 1,
        mode_flags=model.MODE_GRAB_BIT if grab else 0, anim=model.ANIM_WALK,
        anim_countdown=5, anim_reload=5, attack_box_id=0x8F, body_box_id=0x51,
        screen_x=world_x - CAM_X + 0x80, fine_x=float(world_x), fine_y=float(world_y),
        fine_z=160.0, ground_z=160, ground_fine=160.0,
    )
    fields.update(overrides)
    return Onihime(**fields)


def _gamepad() -> tuple[VirtualGamepad, MagicMock]:
    client = MagicMock()
    return VirtualGamepad(SharedGamepadState(client), player_index=1), client


class OwnershipTests(unittest.TestCase):
    def test_one_engage_for_the_pair(self) -> None:
        context = {_myself(), _twin(EDGE - 120), _twin(EDGE - 200, slot="obj00", grab=False), CAMERA}
        verbs = _infer(could_engage_twins)(context)
        self.assertEqual([type(v) for v in verbs], [EngageTwins])
        self.assertEqual(next(iter(verbs)).target_slot, "obj01")

    def test_not_when_they_are_dead(self) -> None:
        dead = _twin(EDGE - 120, health=0)
        self.assertEqual(live_twins({dead}), [])
        self.assertEqual(_infer(could_engage_twins)({_myself(), dead, CAMERA}), set())

    def test_no_generic_verb_aims_at_a_twin(self) -> None:
        me = _myself(EDGE - 100, 60, facing_left=True)
        near = _twin(EDGE - 130, 60)
        behind = _twin(EDGE - 70, 60, slot="obj00", grab=False)
        for generator in (could_punch, could_grab_enemy, could_walk_to_near_enemy, could_jump_attack, could_rear_attack):
            with self.subTest(generator=generator.__name__):
                verbs = _infer(generator)({me, near, behind, CAMERA})
                self.assertFalse(
                    [v for v in verbs if getattr(v, "target_slot", None) in ("obj00", "obj01")]
                )

    def test_adams_rear_attack_hop_is_no_jump(self) -> None:
        # $22 -> $24 is the chord's hop: airborne, and a B pressed in it is
        # no kick (the follow-through pressed at the twins through 135 ticks).
        adam = _myself(EDGE, 60, character_id=1, character_name="Adam", action_state=0x24, is_airborne=True, world_z=140)
        self.assertEqual(_infer(could_jump_attack)({adam, _twin(EDGE - 40), CAMERA}), set())

    def test_no_police_and_no_food_while_they_live(self) -> None:
        dying = _myself(health=4, health_percent=5.0, lives=1)
        self.assertEqual(_infer(could_call_police)({dying, _twin(EDGE - 150), CAMERA}), set())
        food = HealthPickup(slot="obj10", world_x=EDGE - 20, world_y=60, pickup_type=0x47, health_delta=80)
        verbs = _infer(could_walk_to_pickup)({_myself(health=20, health_percent=25.0), _twin(EDGE - 150), food, CAMERA})
        self.assertEqual(verbs, set())


class RankingTests(unittest.TestCase):
    def test_the_engage_wins_the_tick(self) -> None:
        from sor_autoplay.ai.decide import generate_verb_tokens

        context = generate_verb_tokens(
            generate_inference_tokens({_myself(), _twin(EDGE - 120), CAMERA})
        )
        verbs = find_all(determine_priority_verb(set(context)), Verb)
        self.assertEqual([type(v) for v in verbs], [EngageTwins])


class ExecuteTests(unittest.TestCase):
    def test_the_chord_is_b_and_c_with_no_direction(self) -> None:
        # The grab twin walking into Blaze's box from behind (it reaches 58
        # px): the plan presses the rear attack.
        me = _myself()
        twin = _twin(EDGE - 58)
        verb = EngageTwins(actor_slot="P1", target_slot=twin.slot)
        gamepad, client = _gamepad()
        execute_verb(verb, {me, twin, CAMERA}, gamepad)
        pressed = [c.kwargs.get("player1") for c in client.press_buttons.call_args_list]
        self.assertIn(B | C, pressed)

    def test_far_twins_hold_a_stick_and_press_nothing(self) -> None:
        me = _myself(EDGE - 60)
        twin = _twin(EDGE - 250)
        verb = EngageTwins(actor_slot="P1", target_slot=twin.slot)
        gamepad, client = _gamepad()
        execute_verb(verb, {me, twin, CAMERA}, gamepad)
        self.assertFalse(client.press_buttons.called)
        held = client.hold_buttons.call_args.kwargs["player1"]
        self.assertEqual(held & RIGHT, RIGHT)  # to the right edge, back to the twin


if __name__ == "__main__":
    unittest.main()
