import unittest

from sor_autoplay.ai.pickup_tokens import (
    HealthPickup,
    LifePickup,
    Pickup,
    ScorePickup,
    SpecialPickup,
    Weapon,
    build_pickup_token,
    weapon_rank,
)
from sor_autoplay.ai.tokens import Information


class WeaponTests(unittest.TestCase):
    def test_is_information(self) -> None:
        self.assertTrue(issubclass(Weapon, Information))

    def test_fields_round_trip(self) -> None:
        weapon = Weapon(slot="obj10", world_x=850, world_y=64, weapon_type=0x08, wear=1)
        self.assertEqual(weapon.slot, "obj10")
        self.assertEqual(weapon.world_x, 850)
        self.assertEqual(weapon.world_y, 64)
        self.assertEqual(weapon.weapon_type, 0x08)
        self.assertEqual(weapon.wear, 1)

    def test_frozen_and_hashable(self) -> None:
        weapon = Weapon(slot="obj10", world_x=850, world_y=64, weapon_type=0x0C)
        with self.assertRaises(Exception):
            weapon.weapon_type = 0x09  # type: ignore[misc]
        self.assertIn(weapon, {weapon})

    def test_damage_rank_matches_rom_constants(self) -> None:
        # knife 5 > bat/pipe 4 > bottle 3 > pepper 2
        self.assertEqual(weapon_rank(0x08), 5)
        self.assertEqual(weapon_rank(0x0A), 4)
        self.assertEqual(weapon_rank(0x0B), 4)
        self.assertEqual(weapon_rank(0x09), 3)
        self.assertEqual(weapon_rank(0x0C), 2)
        self.assertEqual(weapon_rank(0), 0)


class PickupTests(unittest.TestCase):
    def test_hierarchy(self) -> None:
        self.assertTrue(issubclass(Pickup, Information))
        self.assertTrue(issubclass(HealthPickup, Pickup))
        self.assertTrue(issubclass(LifePickup, Pickup))
        self.assertTrue(issubclass(SpecialPickup, Pickup))
        self.assertTrue(issubclass(ScorePickup, Pickup))

    def test_build_full_health(self) -> None:
        token = build_pickup_token(slot="obj01", world_x=1, world_y=2, pickup_type=0x47)
        self.assertIsInstance(token, HealthPickup)
        assert isinstance(token, HealthPickup)
        self.assertEqual(token.health_delta, 80)

    def test_build_apple(self) -> None:
        token = build_pickup_token(slot="obj01", world_x=1, world_y=2, pickup_type=0x4B)
        self.assertIsInstance(token, HealthPickup)
        assert isinstance(token, HealthPickup)
        self.assertEqual(token.health_delta, 20)

    def test_build_score(self) -> None:
        token = build_pickup_token(slot="obj01", world_x=1, world_y=2, pickup_type=0x40)
        self.assertIsInstance(token, ScorePickup)
        assert isinstance(token, ScorePickup)
        self.assertEqual(token.points, 10000)


if __name__ == "__main__":
    unittest.main()

