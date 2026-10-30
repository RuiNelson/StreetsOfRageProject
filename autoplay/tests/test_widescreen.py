"""``--widescreen`` (Mode 48): the walk clamp, and so the HUD's camera box and
the AI's ``CameraRange``, are $20 wider on each side.

The game's own routines (``SoRWidescreenArena.cpp``) move the player clamp
``$43AA`` from ``[cam+$20, cam+$120]`` to ``[cam, cam+$140]``.
"""

import dataclasses
import unittest
from types import SimpleNamespace

from sor_ai.ai import abadede, arena, grunt, jack, mr_x

from sor_ai.ai.mr_x import actor_from_bytes as mr_x_actor
from sor_ai.ai.observe import generate_direct_observation_tokens
from sor_ai.ai.tokens import CameraRange, find
from sor_ai.ai.twins import player_x_clamp
from sor_ai.world_map import (
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


def _bytes(**offsets: int) -> bytes:
    data = bytearray(0x80)
    for key, value in offsets.items():
        offset = int(key[1:], 16)
        width = 2 if offset == 0x28 else 1
        data[offset : offset + width] = value.to_bytes(width, "big")
    return bytes(data)


class ModelEdgeTests(unittest.TestCase):
    """Each ROM test the widescreen ports widen, in the model that replays it."""

    def test_arena_helpers(self):
        self.assertTrue(arena.inside(0x80, (0x80, 0x1C0), False))
        self.assertFalse(arena.inside(0x7F, (0x80, 0x1C0), False))
        self.assertTrue(arena.inside(0x60, (0x80, 0x1C0), True))
        self.assertFalse(arena.inside(0x1E0, (0x80, 0x1C0), True))
        self.assertEqual((arena.lo(0x80, True), arena.hi(0x1C0, True)), (0x60, 0x1E0))

    def test_grunt_windows_widen_but_92ac_stays(self):
        # screen X $68: outside every plain window, inside every widened one
        # except $97E6's own ($70 -> $50 still holds it).
        plain = grunt.GruntSim.from_bytes(_bytes(x28=0x68), slot=0, cam_x=0)
        wide = grunt.GruntSim.from_bytes(_bytes(x28=0x68), slot=0, cam_x=0, widescreen=True)
        self.assertFalse(grunt._on_screen_97ce(plain))
        self.assertTrue(grunt._on_screen_97ce(wide))
        self.assertFalse(grunt._on_screen_wide(plain))
        self.assertTrue(grunt._on_screen_wide(wide))
        self.assertFalse(grunt._struck_window(plain))
        self.assertTrue(grunt._struck_window(wide))
        # $92AC is an inline compare the ports did not touch.
        self.assertFalse(grunt._on_screen(wide))

    def test_the_far_right_edge_widens_too(self):
        plain = grunt.GruntSim.from_bytes(_bytes(x28=0x1D0), slot=0, cam_x=0)
        wide = grunt.GruntSim.from_bytes(_bytes(x28=0x1D0), slot=0, cam_x=0, widescreen=True)
        self.assertFalse(grunt._on_screen_97ce(plain))
        self.assertTrue(grunt._on_screen_97ce(wide))

    def test_mr_x_on_screen_and_bullets(self):
        plain = mr_x._on_screen(mr_x.MrXSim.from_bytes(_bytes(x28=0x1D0), slot=0, cam_x=0))
        wide = mr_x._on_screen(
            mr_x.MrXSim.from_bytes(_bytes(x28=0x1D0), slot=0, cam_x=0, widescreen=True)
        )
        self.assertFalse(plain)
        self.assertTrue(wide)
        # His own band ($13188...) is inline: not widened.
        sim = mr_x.MrXSim.from_bytes(_bytes(x28=0xB0), slot=0, cam_x=0, widescreen=True)
        self.assertFalse(mr_x._in_band(sim))

    def test_a_bullet_inherits_the_flag_from_mr_x(self):
        sim = mr_x.MrXSim.from_bytes(_bytes(), slot=0, cam_x=0, widescreen=True)
        self.assertTrue(mr_x.spawn_bullet(sim, 0).widescreen)

    def test_abadede_on_screen_and_charge_edges(self):
        def sim(screen_x, widescreen):
            return abadede.AbadedeSim(
                x=0.0, y=0.0, primary=1, sub=0, t54=0, vx=0.0, vy=0.0, anim=0, jitter=1,
                screen_x=screen_x, cam_x=0, inert=0, variant=False, widescreen=widescreen,
            )

        self.assertFalse(abadede._on_screen(sim(0x1D0, False)))
        self.assertTrue(abadede._on_screen(sim(0x1D0, True)))
        self.assertEqual(
            (arena.lo(abadede.CHARGE_EDGE_LEFT, True), arena.hi(abadede.CHARGE_EDGE_RIGHT, True)),
            (0x60, 0x1E0),
        )

    def test_jack_on_screen_and_retreat_edge(self):
        jack_at = SimpleNamespace(x=-0x18 + 0.0)  # screen X $68 with cam_x 0
        plain = jack.World([], [], 0, 0.0, (0,) * 6)
        wide = jack.World([], [], 0, 0.0, (0,) * 6, widescreen=True)
        self.assertFalse(jack._on_screen(jack_at, plain))
        self.assertTrue(jack._on_screen(jack_at, wide))
        self.assertTrue(wide.copy().widescreen)


if __name__ == "__main__":
    unittest.main()
