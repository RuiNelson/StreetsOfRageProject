import unittest

from sor_autoplay.ai.hazard_tokens import DangerZone, IncomingProjectile, Projectile
from sor_autoplay.ai.tokens import Information


class HazardTokenTests(unittest.TestCase):
    def test_all_are_information(self) -> None:
        self.assertTrue(issubclass(Projectile, Information))
        self.assertTrue(issubclass(IncomingProjectile, Information))
        self.assertTrue(issubclass(DangerZone, Information))

    def test_projectile_fields(self) -> None:
        projectile = Projectile(
            slot="obj09", world_x=900, world_y=64, vel_x=-1.5, vel_z=0.0
        )
        self.assertEqual(projectile.slot, "obj09")
        self.assertEqual(projectile.world_x, 900)
        self.assertEqual(projectile.world_y, 64)
        self.assertEqual(projectile.vel_x, -1.5)
        self.assertEqual(projectile.vel_z, 0.0)

    def test_incoming_projectile_fields(self) -> None:
        incoming = IncomingProjectile(
            slot="obj09", world_x=900, world_y=64, vel_x=-1.5, vel_z=0.0
        )
        self.assertEqual(incoming.slot, "obj09")
        self.assertEqual(incoming.vel_x, -1.5)

    def test_danger_zone_fields(self) -> None:
        zone = DangerZone(
            slot="P1", left=32.0, right=96.0, top=0.0, bottom=112.0, threat_level=3
        )
        self.assertEqual(zone.slot, "P1")
        self.assertEqual(zone.left, 32.0)
        self.assertEqual(zone.right, 96.0)
        self.assertEqual(zone.top, 0.0)
        self.assertEqual(zone.bottom, 112.0)
        self.assertEqual(zone.threat_level, 3)

    def test_frozen_and_hashable(self) -> None:
        projectile = Projectile(
            slot="obj09", world_x=900, world_y=64, vel_x=0.0, vel_z=0.0
        )
        with self.assertRaises(Exception):
            projectile.vel_x = 1.0  # type: ignore[misc]
        self.assertIn(projectile, {projectile})


if __name__ == "__main__":
    unittest.main()
