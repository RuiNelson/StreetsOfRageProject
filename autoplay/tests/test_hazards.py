import unittest

from sor_autoplay.hazards import (
    collision_class_at,
    find_collision_barriers,
    find_floor_holes,
    is_paused,
    is_police_special_active,
)


class PauseSpecialTests(unittest.TestCase):
    def test_pause_flag(self) -> None:
        self.assertFalse(is_paused(0))
        # Fresh pause write is 3; after first paused frame bit1 is cleared → 1.
        self.assertTrue(is_paused(3))
        self.assertTrue(is_paused(1))
        self.assertTrue(is_paused(2))

    def test_police_special(self) -> None:
        self.assertFalse(is_police_special_active(0))
        self.assertTrue(is_police_special_active(1))
        self.assertTrue(is_police_special_active(0x01))


class CollisionHoleTests(unittest.TestCase):
    def test_nibble_select(self) -> None:
        # One row, stride 2: bytes [0x10, 0x01] → classes high/low 1,0 then 0,1
        cmap = bytes([0x10, 0x01])
        stride = 2
        self.assertEqual(collision_class_at(cmap, stride=stride, world_x=0, lane_y=0), 1)
        self.assertEqual(collision_class_at(cmap, stride=stride, world_x=8, lane_y=0), 0)
        self.assertEqual(collision_class_at(cmap, stride=stride, world_x=16, lane_y=0), 0)
        self.assertEqual(collision_class_at(cmap, stride=stride, world_x=24, lane_y=0), 1)

    def test_a_column_past_the_map_width_is_not_the_next_lane_row(self) -> None:
        # Regression: `row * stride + col` with col >= stride lands in the
        # NEXT lane row's bytes. Row 0 here is solid floor and row 1 is all
        # pit, so reading row 0 past the map's own width (stride * 16 = 64px)
        # used to report class 0 -- an invented pit from row 1's data.
        stride = 4
        cmap = bytes([0x11] * stride + [0x00] * stride)

        self.assertEqual(collision_class_at(cmap, stride=stride, world_x=56, lane_y=0), 1)
        self.assertEqual(collision_class_at(cmap, stride=stride, world_x=64, lane_y=0), 0)
        # ...and the class-0 read above must be "off the map", not "a pit":
        # nothing may be reported as a hole beyond the blockmap's own width.
        holes = find_floor_holes(
            cmap, stride=stride, lane_max=8, world_x_min=0, world_x_max=160
        )
        self.assertTrue(
            all(h.world_x_end <= stride * 16 for h in holes),
            f"hole reported past the map width: {holes}",
        )

    def test_scanning_past_the_map_width_invents_no_hole_on_solid_ground(self) -> None:
        # holes_for_level sweeps camera_x-512 .. camera_x+832, which runs off
        # the end of the blockmap near every stage's end. A single all-solid
        # row must stay hole-free however far past its width the scan reaches.
        stride = 4
        cmap = bytes([0x11] * stride)

        holes = find_floor_holes(
            cmap, stride=stride, lane_max=8, world_x_min=0, world_x_max=1024
        )

        self.assertEqual(holes, ())

    def test_find_and_merge_holes(self) -> None:
        # One connected L-shaped hole must become a single bounding box.
        # stride=4 bytes (64px wide), a few rows.
        stride = 4
        rows = 4
        cmap = bytearray([0x11] * (stride * rows))  # solid (class 1 both nibbles)
        # 16px-wide column cells: byte index = world_x>>4
        # Hole: wide bar on row0 cols 2-3, plus stem on row1 col2
        cmap[2] = 0x00
        cmap[3] = 0x00
        cmap[stride + 2] = 0x00
        holes = find_floor_holes(
            bytes(cmap),
            stride=stride,
            lane_max=24,
            world_x_min=0,
            world_x_max=64,
        )
        self.assertEqual(len(holes), 1, holes)
        hole = holes[0]
        self.assertEqual(hole.world_x, 32)
        self.assertEqual(hole.width, 32)
        self.assertEqual(hole.lane_y, 0)
        self.assertEqual(hole.height, 16)

    def test_two_separate_holes(self) -> None:
        stride = 8
        rows = 3
        cmap = bytearray([0x11] * (stride * rows))
        # Two separate 16px pits on row 1 (lane 8), far apart so they stay separate.
        cmap[stride + 1] = 0x00  # x=16..32
        cmap[stride + 6] = 0x00  # x=96..112
        holes = find_floor_holes(
            bytes(cmap),
            stride=stride,
            lane_max=24,
            world_x_min=0,
            world_x_max=128,
        )
        xs = sorted(h.world_x for h in holes)
        self.assertIn(16, xs)
        self.assertIn(96, xs)
        # Must not explode into a tile staircase.
        self.assertLessEqual(len(holes), 3)


class CollisionBarrierTests(unittest.TestCase):
    def test_class_two_wall_is_a_barrier_not_a_hole(self) -> None:
        """Round-6 factory housing is class 2; class 0 remains the pit class."""

        stride = 4
        rows = 4
        # Class 1 floor everywhere.
        cmap = bytearray([0x11] * (stride * rows))
        # Class 2 wall block on row0-1, cols 2-3 (x=32..64, y=0..16).
        cmap[2] = 0x22
        cmap[3] = 0x22
        cmap[stride + 2] = 0x22
        cmap[stride + 3] = 0x22

        holes = find_floor_holes(
            bytes(cmap),
            stride=stride,
            lane_max=24,
            world_x_min=0,
            world_x_max=64,
        )
        barriers = find_collision_barriers(
            bytes(cmap),
            stride=stride,
            lane_max=24,
            world_x_min=0,
            world_x_max=64,
        )
        self.assertEqual(holes, ())
        self.assertEqual(len(barriers), 1, barriers)
        wall = barriers[0]
        self.assertEqual(wall.world_x, 32)
        self.assertEqual(wall.width, 32)
        self.assertEqual(wall.lane_y, 0)
        self.assertEqual(wall.height, 16)


if __name__ == "__main__":
    unittest.main()
