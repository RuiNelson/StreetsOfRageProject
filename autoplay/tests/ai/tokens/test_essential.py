import unittest

from sor_autoplay.ai.essential import AnimationInProgress, CameraRange, Stage
from sor_autoplay.ai.tokens import Information


class EssentialTokenTests(unittest.TestCase):
    def test_all_are_information(self) -> None:
        self.assertTrue(issubclass(Stage, Information))
        self.assertTrue(issubclass(CameraRange, Information))
        self.assertTrue(issubclass(AnimationInProgress, Information))

    def test_stage_fields(self) -> None:
        stage = Stage(level_index=0, direction="right")
        self.assertEqual(stage.level_index, 0)
        self.assertEqual(stage.direction, "right")

    def test_camera_range_fields(self) -> None:
        camera = CameraRange(left=32.0, right=288.0, top=0.0, bottom=112.0)
        self.assertEqual(camera.left, 32.0)
        self.assertEqual(camera.right, 288.0)
        self.assertEqual(camera.top, 0.0)
        self.assertEqual(camera.bottom, 112.0)

    def test_animation_in_progress_slot(self) -> None:
        anim = AnimationInProgress(slot="P1")
        self.assertEqual(anim.slot, "P1")

    def test_frozen_and_hashable(self) -> None:
        stage = Stage(level_index=0, direction="right")
        with self.assertRaises(Exception):
            stage.level_index = 1  # type: ignore[misc]
        self.assertIn(stage, {stage})


if __name__ == "__main__":
    unittest.main()
