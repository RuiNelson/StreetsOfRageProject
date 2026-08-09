import unittest

from sor_autoplay.ai.tokens import (
    Abadede,
    Antonio,
    Bongo,
    Boss,
    Enemy,
    Garcia,
    Grunt,
    HakuRo,
    Jack,
    MrX,
    Nora,
    Onihime,
    Signal,
    Souther,
    enemy_class_for_type,
)
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


def _base_kwargs(**overrides) -> dict:
    fields = dict(
        slot="obj00",
        type_id=0x20,
        world_x=900,
        world_y=64,
        health=6,
        combat_phase=CombatPhase.NORMAL,
        targets_player=None,
        facing_left=False,
    )
    fields.update(overrides)
    return fields


class EnemyClassForTypeTests(unittest.TestCase):
    def test_garcia_types(self) -> None:
        for type_id in (0x20, 0x21, 0x22, 0x23):
            self.assertIs(enemy_class_for_type(type_id), Garcia)

    def test_signal(self) -> None:
        self.assertIs(enemy_class_for_type(0x24), Signal)

    def test_hakuro_types(self) -> None:
        self.assertIs(enemy_class_for_type(0x25), HakuRo)
        self.assertIs(enemy_class_for_type(0x2A), HakuRo)

    def test_nora(self) -> None:
        self.assertIs(enemy_class_for_type(0x26), Nora)

    def test_jack(self) -> None:
        self.assertIs(enemy_class_for_type(0x27), Jack)

    def test_bespoke_bosses(self) -> None:
        self.assertIs(enemy_class_for_type(0x30), Abadede)
        self.assertIs(enemy_class_for_type(0x35), MrX)

    def test_later_bosses(self) -> None:
        self.assertIs(enemy_class_for_type(0x55), Souther)
        self.assertIs(enemy_class_for_type(0x56), Antonio)
        self.assertIs(enemy_class_for_type(0x57), Bongo)
        self.assertIs(enemy_class_for_type(0x58), Onihime)

    def test_unknown_type_falls_back_to_enemy(self) -> None:
        self.assertIs(enemy_class_for_type(0x99), Enemy)

    def test_masks_with_0xff(self) -> None:
        self.assertIs(enemy_class_for_type(0x1120), Garcia)


class EnemyHierarchyTests(unittest.TestCase):
    def test_boss_hierarchy(self) -> None:
        self.assertTrue(issubclass(Boss, Enemy))
        for cls in (Abadede, MrX, Souther, Antonio, Bongo, Onihime):
            self.assertTrue(issubclass(cls, Boss))

    def test_grunt_hierarchy(self) -> None:
        for cls in (Garcia, Signal, HakuRo, Nora, Jack):
            self.assertTrue(issubclass(cls, Grunt))
        self.assertTrue(issubclass(Grunt, Enemy))

    def test_jack_has_projectile_field(self) -> None:
        jack_with = Jack(**_base_kwargs(type_id=0x27, has_projectile=True))
        jack_without = Jack(**_base_kwargs(type_id=0x27, has_projectile=False))
        self.assertTrue(jack_with.has_projectile)
        self.assertFalse(jack_without.has_projectile)

    def test_boss_needs_no_extra_fields(self) -> None:
        abadede = Abadede(**_base_kwargs(type_id=0x30, health=100))
        self.assertIsInstance(abadede, Enemy)
        mrx = MrX(**_base_kwargs(type_id=0x35, health=100))
        self.assertIsInstance(mrx, Enemy)
        self.assertEqual(abadede.tactical, 0)
        self.assertIsNone(abadede.ground_z)

    def test_boss_extra_fields_round_trip(self) -> None:
        souther = Souther(
            **_base_kwargs(type_id=0x55, health=200),
            tactical=3,
            pair_role=0,
            boss_dist_x=40,
            boss_dist_lane=5,
            mode_flags=0x02,
            target_unavailable=0,
            phase_timer=12,
            ground_z=160,
            vel_x=1.5,
            vel_z=-0.5,
        )
        self.assertEqual(souther.tactical, 3)
        self.assertEqual(souther.pair_role, 0)
        self.assertEqual(souther.boss_dist_x, 40)
        self.assertEqual(souther.boss_dist_lane, 5)
        self.assertEqual(souther.mode_flags, 0x02)
        self.assertEqual(souther.target_unavailable, 0)
        self.assertEqual(souther.phase_timer, 12)
        self.assertEqual(souther.ground_z, 160)
        self.assertEqual(souther.vel_x, 1.5)
        self.assertEqual(souther.vel_z, -0.5)


if __name__ == "__main__":
    unittest.main()
