"""``--widescreen`` (Mode 48): the walk clamp, and so the HUD's camera box and
the AI's ``CameraRange``, are $20 wider on each side.

The game's own routines (``SoRWidescreenArena.cpp``) move the player clamp
``$43AA`` from ``[cam+$20, cam+$120]`` to ``[cam, cam+$140]``.
"""

import dataclasses
import unittest

from sor_autoplay.ai.mr_x import actor_from_bytes as mr_x_actor
from sor_autoplay.ai.observe import generate_direct_observation_tokens
from sor_autoplay.ai.tokens import CameraRange, find
from sor_autoplay.ai.twins import player_x_clamp
from sor_autoplay.world_map import (
    ACTORS_BYTES,
    CAMERA_BYTES,
    WIDESCREEN_EXTRA_X,
    empty_world_map,
    is_in_loot_camera,
    parse_world_map,
)
from tests.ai.test_observe import _player_snapshot, _snapshot


def _world(widescreen: bool):
    camera = bytearray(CAMERA_BYTES)
    camera[0x02:0x04] = (768).to_bytes(2, "big")
    return parse_world_map(
        actors_block=bytes(ACTORS_BYTES), camera_block=bytes(camera), widescreen=widescreen
    )


class WorldMapTests(unittest.TestCase):
    def test_the_plain_walk_band_is_32_to_288(self):
        world = _world(False)
        self.assertEqual((world.camera_left, world.camera_right), (32.0, 288.0))
        self.assertFalse(world.widescreen)

    def test_widescreen_walks_the_whole_320(self):
        world = _world(True)
        self.assertEqual((world.camera_left, world.camera_right), (0.0, 320.0))
        self.assertTrue(world.widescreen)
        self.assertEqual(world.camera_width - _world(False).camera_width, 2 * WIDESCREEN_EXTRA_X)

    def test_the_view_still_contains_the_camera(self):
        world = _world(True)
        self.assertLessEqual(world.view_left, world.camera_left)
        self.assertGreaterEqual(world.view_right, world.camera_right)

    def test_the_empty_map_is_plain(self):
        self.assertFalse(empty_world_map().widescreen)

    def test_loot_reach_widens_with_the_band(self):
        self.assertFalse(is_in_loot_camera(-4.0))
        self.assertTrue(is_in_loot_camera(-4.0, widescreen=True))


class CameraRangeTests(unittest.TestCase):
    def _camera(self, widescreen: bool) -> CameraRange:
        snapshot = _snapshot(players=(_player_snapshot(index=1), _player_snapshot(index=2)))
        snapshot = dataclasses.replace(snapshot, world_map=_world(widescreen))
        return find(generate_direct_observation_tokens(snapshot, player_index=1), CameraRange)

    def test_left_and_right_follow_the_clamp(self):
        plain, wide = self._camera(False), self._camera(True)
        self.assertEqual((plain.left, plain.right), (800.0, 1056.0))
        self.assertEqual((wide.left, wide.right), (768.0, 1088.0))
        self.assertTrue(wide.widescreen and not plain.widescreen)

    def test_the_camera_x_is_the_same_either_way(self):
        self.assertEqual(self._camera(False).origin_x, 768)
        self.assertEqual(self._camera(True).origin_x, 768)

    def test_a_hand_built_range_assumes_the_plain_clamp(self):
        self.assertEqual(CameraRange(left=32.0, right=288.0, top=0.0, bottom=112.0).origin_x, 0.0)


class ActorClampTests(unittest.TestCase):
    def test_twins_and_mr_x_actors_clamp_to_the_wider_band(self):
        self.assertEqual(player_x_clamp(1000), (1032.0, 1288.0))
        self.assertEqual(player_x_clamp(1000, widescreen=True), (1000.0, 1320.0))
        data = bytes(0x80)
        plain = mr_x_actor(data, cam_x=1000)
        wide = mr_x_actor(data, cam_x=1000, widescreen=True)
        self.assertEqual((plain.x_lo, plain.x_hi), (1032.0, 1288.0))
        self.assertEqual((wide.x_lo, wide.x_hi), (1000.0, 1320.0))


if __name__ == "__main__":
    unittest.main()
