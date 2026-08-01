import unittest

from sor_autoplay.memory_map import (
    OBJ_CHARACTER_ID,
    OBJ_FLAGS,
    OBJ_HEALTH,
    OBJ_POS_X,
    OBJ_POS_Y,
    OBJ_POS_Z,
    OBJ_TYPE,
    OBJECT_SLOT_SIZE,
)
from sor_autoplay.object_catalog import player_style, style_for_type
from sor_autoplay.world_map import (
    ACTORS_BYTES,
    CAMERA_BYTES,
    LANE_Y_MAX_DEFAULT,
    LANE_Y_MAX_ROUND7,
    OBJECT_TABLE_BYTES,
    SCREEN_WIDTH,
    lane_y_max_for_level,
    parse_world_map,
    project_to_map,
)


def _put_u8(buf: bytearray, offset: int, value: int) -> None:
    buf[offset] = value & 0xFF


def _put_u16(buf: bytearray, offset: int, value: int) -> None:
    buf[offset : offset + 2] = int(value & 0xFFFF).to_bytes(2, "big")


def _put_fixed16(buf: bytearray, offset: int, integer: int) -> None:
    buf[offset : offset + 2] = int(integer & 0xFFFF).to_bytes(2, "big", signed=False)
    buf[offset + 2 : offset + 4] = b"\x00\x00"


class ObjectCatalogTests(unittest.TestCase):
    def test_player_colors(self) -> None:
        self.assertEqual(player_style(1, 0).color, "#4da3ff")
        self.assertEqual(player_style(2, 2).color, "#ff5c5c")

    def test_pickups(self) -> None:
        self.assertEqual(style_for_type(0x4B).symbol, "a")


class ProjectionTests(unittest.TestCase):
    def test_map_is_lane_depth(self) -> None:
        self.assertEqual(project_to_map(800, 2, camera_x=768), (32.0, 2.0))
        self.assertEqual(project_to_map(800, 112, camera_x=768), (32.0, 112.0))

    def test_lane_clamp_from_rom(self) -> None:
        self.assertEqual(LANE_Y_MAX_DEFAULT, 0x70)
        self.assertEqual(LANE_Y_MAX_ROUND7, 0xA0)
        self.assertEqual(lane_y_max_for_level(0), 0x70)
        self.assertEqual(lane_y_max_for_level(6), 0xA0)


class WorldMapParseTests(unittest.TestCase):
    def test_bottom_of_lane_is_bottom_of_camera(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        _put_u8(actors, OBJ_TYPE, 0x01)
        _put_u8(actors, OBJ_FLAGS, 0x08)
        _put_fixed16(actors, OBJ_POS_X, 800)
        _put_fixed16(actors, OBJ_POS_Y, 0x70)  # ROM max lane most rounds
        _put_fixed16(actors, OBJ_POS_Z, 160)
        _put_u16(actors, OBJ_HEALTH, 0x50)
        _put_u8(actors, OBJ_CHARACTER_ID, 0x02)

        world = parse_world_map(
            actors_block=bytes(actors),
            camera_block=bytes(camera),
            p1_character_id=2,
            level_index=0,
        )
        p1 = world.entities[0]
        self.assertEqual(world.camera_bottom, float(0x70))
        self.assertEqual(p1.map_y, 112.0)
        # At bottom of playable lane → bottom edge of camera box.
        frac = (p1.map_y - world.camera_top) / world.camera_height
        self.assertAlmostEqual(frac, 1.0)

    def test_top_of_lane_near_top(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)
        _put_u8(actors, OBJ_TYPE, 0x01)
        _put_u8(actors, OBJ_FLAGS, 0x08)
        _put_fixed16(actors, OBJ_POS_X, 800)
        _put_fixed16(actors, OBJ_POS_Y, 2)
        _put_fixed16(actors, OBJ_POS_Z, 160)
        _put_u16(actors, OBJ_HEALTH, 0x50)

        world = parse_world_map(
            actors_block=bytes(actors),
            camera_block=bytes(camera),
            p1_character_id=0,
            level_index=0,
        )
        p1 = world.entities[0]
        frac = (p1.map_y - world.camera_top) / world.camera_height
        self.assertLess(frac, 0.05)

    def test_round7_taller_lane(self) -> None:
        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        world = parse_world_map(
            actors_block=bytes(actors),
            camera_block=bytes(camera),
            level_index=6,
        )
        self.assertEqual(world.camera_bottom, float(0xA0))
        self.assertAlmostEqual(world.camera_width / world.camera_height, SCREEN_WIDTH / 0xA0)

    def test_hitstun_flash_does_not_drop_on_screen_enemy(self) -> None:
        """SAT blink toggles flags bit0; on-screen enemies must stay on the map."""

        actors = bytearray(ACTORS_BYTES)
        camera = bytearray(CAMERA_BYTES)
        _put_u16(camera, 0x02, 768)

        def put_enemy(*, flags: int) -> None:
            base = 0x100
            _put_u8(actors, base + OBJ_TYPE, 0x20)
            _put_u8(actors, base + OBJ_FLAGS, flags)
            _put_fixed16(actors, base + OBJ_POS_X, 800)  # map_x = 32
            _put_fixed16(actors, base + OBJ_POS_Y, 0x40)
            _put_fixed16(actors, base + OBJ_POS_Z, 160)
            _put_u16(actors, base + OBJ_HEALTH, 6)

        put_enemy(flags=0x0C)  # visible frame
        w1 = parse_world_map(actors_block=bytes(actors), camera_block=bytes(camera))
        self.assertTrue(any(e.type_id == 0x20 for e in w1.entities))

        put_enemy(flags=0x0D)  # same enemy, flash frame (bit0 set)
        w2 = parse_world_map(actors_block=bytes(actors), camera_block=bytes(camera))
        self.assertTrue(any(e.type_id == 0x20 for e in w2.entities))

        # Off-screen dormant spawn with hidden bit must still appear on the map.
        base = 0x100
        _put_u8(actors, base + OBJ_FLAGS, 0x01)
        _put_fixed16(actors, base + OBJ_POS_X, 768 + 400)  # map_x = 400
        w3 = parse_world_map(actors_block=bytes(actors), camera_block=bytes(camera))
        dormant = [e for e in w3.entities if e.type_id == 0x20]
        self.assertEqual(len(dormant), 1)
        self.assertGreater(dormant[0].map_x, SCREEN_WIDTH)
        # View expands so the dormant spawn is not clipped off the plot.
        self.assertGreaterEqual(w3.view_right, dormant[0].map_x)


if __name__ == "__main__":
    unittest.main()
