import unittest

from sor_autoplay.ai.enemy import Enemy
from sor_autoplay.ai.tokens import Information
from sor_autoplay.phases import CombatPhase


class EnemyTests(unittest.TestCase):
    def test_is_information(self) -> None:
        self.assertTrue(issubclass(Enemy, Information))

    def test_fields_round_trip(self) -> None:
        enemy = Enemy(
            slot="obj07",
            type_id=0x20,
            world_x=900,
            world_y=64,
            health=6,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
            facing_left=True,
        )
        self.assertEqual(enemy.slot, "obj07")
        self.assertEqual(enemy.type_id, 0x20)
        self.assertEqual(enemy.world_x, 900)
        self.assertEqual(enemy.world_y, 64)
        self.assertEqual(enemy.health, 6)
        self.assertEqual(enemy.combat_phase, CombatPhase.ATTACKING)
        self.assertEqual(enemy.targets_player, 1)
        self.assertTrue(enemy.facing_left)

    def test_health_and_targets_player_may_be_none(self) -> None:
        enemy = Enemy(
            slot="obj08",
            type_id=0x27,
            world_x=900,
            world_y=64,
            health=None,
            combat_phase=CombatPhase.UNKNOWN,
            targets_player=None,
            facing_left=False,
        )
        self.assertIsNone(enemy.health)
        self.assertIsNone(enemy.targets_player)

    def test_frozen_and_hashable(self) -> None:
        enemy = Enemy(
            slot="obj07",
            type_id=0x20,
            world_x=900,
            world_y=64,
            health=6,
            combat_phase=CombatPhase.NORMAL,
            targets_player=None,
            facing_left=False,
        )
        with self.assertRaises(Exception):
            enemy.health = 0  # type: ignore[misc]
        self.assertIn(enemy, {enemy})


if __name__ == "__main__":
    unittest.main()
