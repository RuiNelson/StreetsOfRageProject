import unittest

from sor_autoplay.ai.tokens import Myself
from sor_autoplay.ai.tokens import ClosingEnemy, Enemy, Garcia
from sor_autoplay.ai.tokens import IncomingProjectile, Projectile
from sor_autoplay.ai.inference import (
    check_for_closing_enemies,
    check_for_incoming_projectiles,
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


def make_garcia(**overrides) -> Garcia:
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
    return Garcia(**fields)


class CheckForIncomingProjectilesTests(unittest.TestCase):
    def test_promotes_only_projectiles_heading_toward_a_player(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        # Closing from the right.
        threat = Projectile(slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0)
        # Flying away / irrelevant lane.
        benign = Projectile(slot="obj11", world_x=30, world_y=200, vel_x=-1.5, vel_z=0.5)
        context: set[Token] = {myself, threat, benign}

        result = check_for_incoming_projectiles(context)

        self.assertEqual(
            result,
            {
                IncomingProjectile(
                    slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0
                ),
            },
        )

    def test_no_projectiles_no_output(self) -> None:
        self.assertEqual(check_for_incoming_projectiles(set()), set())

    def test_no_actors_no_output(self) -> None:
        p = Projectile(slot="obj10", world_x=10, world_y=20, vel_x=1.0, vel_z=0.0)
        self.assertEqual(check_for_incoming_projectiles({p}), set())


class CheckForClosingEnemiesTests(unittest.TestCase):
    def test_promotes_a_grunt_closing_diagonally_beyond_the_rear_band(self) -> None:
        # Axel (character_id=0): rear-attack behind band is 40px.
        myself = make_myself(character_id=0, world_x=100, world_y=100)
        garcia = make_garcia(
            slot="obj20", world_x=160, world_y=110, grunt_vel_x=-10.0, grunt_vel_y=-2.0
        )
        context: set[Token] = {myself, garcia}

        result = check_for_closing_enemies(context)

        self.assertEqual(result, {ClosingEnemy(slot="obj20")})

    def test_no_promotion_when_heading_away(self) -> None:
        myself = make_myself(character_id=0, world_x=100, world_y=100)
        garcia = make_garcia(
            slot="obj20", world_x=160, world_y=110, grunt_vel_x=10.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), set())

    def test_no_promotion_for_a_stationary_grunt(self) -> None:
        myself = make_myself(character_id=0, world_x=100, world_y=100)
        garcia = make_garcia(slot="obj20", world_x=160, world_y=110)
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), set())

    def test_no_promotion_when_already_inside_the_rear_band(self) -> None:
        # decide._in_rear_band already covers this tick without early warning.
        myself = make_myself(character_id=0, world_x=100, world_y=100)
        garcia = make_garcia(
            slot="obj20", world_x=130, world_y=100, grunt_vel_x=-10.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), set())

    def test_no_promotion_when_too_far_off_lane(self) -> None:
        myself = make_myself(character_id=0, world_x=100, world_y=100)
        garcia = make_garcia(
            slot="obj20", world_x=160, world_y=300, grunt_vel_x=-10.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), set())

    def test_no_promotion_when_too_many_ticks_away(self) -> None:
        myself = make_myself(character_id=0, world_x=100, world_y=100)
        garcia = make_garcia(
            slot="obj20", world_x=300, world_y=110, grunt_vel_x=-1.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), set())

    def test_no_actors_no_output(self) -> None:
        garcia = make_garcia(slot="obj20", world_x=160, world_y=110, grunt_vel_x=-10.0)
        self.assertEqual(check_for_closing_enemies({garcia}), set())


class GenerateInferenceTokensTests(unittest.TestCase):
    def test_unions_context_with_incoming_projectile_check(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=105, world_y=100, targets_player=1)
        # Closing projectile so IncomingProjectile is emitted.
        projectile = Projectile(slot="obj10", world_x=150, world_y=100, vel_x=-4.0, vel_z=0.0)
        context: set[Token] = {myself, enemy, projectile}

        result = generate_inference_tokens(context)

        self.assertIn(myself, result)
        self.assertIn(enemy, result)
        self.assertIn(projectile, result)
        self.assertTrue(any(isinstance(t, IncomingProjectile) for t in result))

    def test_unions_context_with_closing_enemy_check(self) -> None:
        myself = make_myself(character_id=0, world_x=100, world_y=100)
        garcia = make_garcia(
            slot="obj20", world_x=160, world_y=110, grunt_vel_x=-10.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        result = generate_inference_tokens(context)

        self.assertIn(garcia, result)
        self.assertIn(ClosingEnemy(slot="obj20"), result)

    def test_does_not_mutate_input_context(self) -> None:
        myself = make_myself()
        context: set[Token] = {myself}
        original = set(context)

        generate_inference_tokens(context)

        self.assertEqual(context, original)


if __name__ == "__main__":
    unittest.main()
