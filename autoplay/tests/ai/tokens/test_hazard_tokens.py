import unittest

from sor_autoplay.ai.tokens import Breakable, IncomingProjectile, Pit, Projectile
from sor_autoplay.ai.tokens import Information, Observed, StageObjects


class HazardTokenTests(unittest.TestCase):
    def test_all_are_information(self) -> None:
        self.assertTrue(issubclass(Projectile, Information))
        self.assertTrue(issubclass(IncomingProjectile, Information))
        self.assertTrue(issubclass(Breakable, Information))
        self.assertTrue(issubclass(Pit, Information))

    def test_stage_objects_hierarchy(self) -> None:
        self.assertTrue(issubclass(StageObjects, Observed))
        self.assertTrue(issubclass(Breakable, StageObjects))
        self.assertTrue(issubclass(Pit, StageObjects))
        self.assertFalse(issubclass(Projectile, StageObjects))

    def test_pit_fields(self) -> None:
        pit = Pit(world_x=1200, lane_y=64, width=128, height=48)
        self.assertEqual(pit.world_x, 1200)
        self.assertEqual(pit.lane_y, 64)
        self.assertEqual(pit.width, 128)
        self.assertEqual(pit.height, 48)

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

    def test_frozen_and_hashable(self) -> None:
        projectile = Projectile(
            slot="obj09", world_x=900, world_y=64, vel_x=0.0, vel_z=0.0
        )
        with self.assertRaises(Exception):
            projectile.vel_x = 1.0  # type: ignore[misc]
        self.assertIn(projectile, {projectile})


if __name__ == "__main__":
    unittest.main()
