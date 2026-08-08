import unittest

from sor_autoplay.ai.pickup_tokens import Weapon
from sor_autoplay.ai.tokens import Information


class WeaponTests(unittest.TestCase):
    def test_is_information(self) -> None:
        self.assertTrue(issubclass(Weapon, Information))

    def test_fields_round_trip(self) -> None:
        weapon = Weapon(slot="obj10", world_x=850, world_y=64, weapon_type=0x08)
        self.assertEqual(weapon.slot, "obj10")
        self.assertEqual(weapon.world_x, 850)
        self.assertEqual(weapon.world_y, 64)
        self.assertEqual(weapon.weapon_type, 0x08)

    def test_frozen_and_hashable(self) -> None:
        weapon = Weapon(slot="obj10", world_x=850, world_y=64, weapon_type=0x0C)
        with self.assertRaises(Exception):
            weapon.weapon_type = 0x09  # type: ignore[misc]
        self.assertIn(weapon, {weapon})


if __name__ == "__main__":
    unittest.main()
