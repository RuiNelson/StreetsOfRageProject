import unittest

from sor_autoplay.ai.tokens import Myself
from sor_autoplay.ai.tokens import Enemy
from sor_autoplay.ai.tokens import Surrounded
from sor_autoplay.ai.inference import (
    check_for_surrounded,
    generate_inference_tokens,
)
from sor_autoplay.ai.tokens import Token
from sor_autoplay.phases import CombatPhase


def make_myself(**overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=100,
        world_y=100,
        health=100,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=False,
        combat_phase=CombatPhase.NORMAL,
        action_state=0,
        is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


def make_enemy(**overrides) -> Enemy:
    fields = dict(
        slot="obj01",
        type_id=0x20,
        world_x=100,
        world_y=100,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
    )
    fields.update(overrides)
    return Enemy(**fields)


class CheckForSurroundedTests(unittest.TestCase):
    def test_a_pincer_counts_even_with_only_two_enemies(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        front = make_enemy(slot="obj01", world_x=130, world_y=100)
        back = make_enemy(slot="obj02", world_x=70, world_y=100)

        result = check_for_surrounded({myself, front, back})

        self.assertEqual(
            result, {Surrounded(actor_slot="P1", in_front=1, behind=1)}
        )

    def test_two_enemies_on_the_same_side_are_a_queue_not_a_crowd(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        near = make_enemy(slot="obj01", world_x=130, world_y=100)
        far = make_enemy(slot="obj02", world_x=150, world_y=100)

        self.assertEqual(check_for_surrounded({myself, near, far}), set())

    def test_three_on_the_same_side_is_a_crowd(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        crowd = [
            make_enemy(slot=f"obj0{i}", world_x=120 + 5 * i, world_y=100)
            for i in range(3)
        ]

        result = check_for_surrounded({myself, *crowd})

        self.assertEqual(result, {Surrounded(actor_slot="P1", in_front=3, behind=0)})

    def test_survives_the_actor_walking_toward_one_of_them(self) -> None:
        # The bug behind "I see no effect": judged with the chord's own
        # REAR_THREAT_X (56), a crowd evaporated after the actor took two
        # steps. Traced on the tick harness -- the actor walked 12px toward
        # one enemy, the third fell out of the box, the count dropped 3 -> 2
        # with both survivors on one side, and every judgment keyed on
        # Surrounded went with it, including a grab already being walked in.
        crowd_x = (246, 250, 152)
        for actor_x in (200, 206, 212, 224, 236):
            with self.subTest(actor_x=actor_x):
                myself = make_myself(world_x=actor_x, world_y=64, facing_left=False)
                crowd = [
                    make_enemy(slot=f"obj{i:02d}", world_x=x, world_y=64)
                    for i, x in enumerate(crowd_x)
                ]

                result = check_for_surrounded({myself, *crowd})

                self.assertTrue(
                    result, f"crowd judgment collapsed at actor_x={actor_x}"
                )


class GenerateInferenceTokensTests(unittest.TestCase):
    def test_unions_context_with_surrounded_check(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        front = make_enemy(slot="obj01", world_x=130, world_y=100, targets_player=1)
        back = make_enemy(slot="obj02", world_x=70, world_y=100, targets_player=1)
        context: set[Token] = {myself, front, back}

        result = generate_inference_tokens(context)

        self.assertIn(myself, result)
        self.assertIn(front, result)
        self.assertIn(back, result)
        self.assertTrue(any(isinstance(t, Surrounded) for t in result))

    def test_does_not_mutate_input_context(self) -> None:
        myself = make_myself()
        context: set[Token] = {myself}
        original = set(context)

        generate_inference_tokens(context)

        self.assertEqual(context, original)


if __name__ == "__main__":
    unittest.main()
