import unittest

from sor_autoplay.hazards import (
    FLOOR_CONVEYOR_LEFT,
    FLOOR_CONVEYOR_RIGHT,
    FLOOR_NONE,
    FLOOR_SOLID,
    FloorHole,
    collision_class_at,
    find_collision_barriers,
    find_floor_holes,
    floor_kind,
    is_hole_class,
    is_paused,
    is_police_special_active,
    is_wall_class,
)

ROUND_4 = 3
ROUND_6 = 5
ROUND_7 = 6


def _set_class(cmap: bytearray, stride: int, x: int, lane: int, klass: int) -> None:
    """Write one 8x8 cell's nibble the way ``collision_class_at`` reads it."""

    index = (lane >> 3) * stride + (x >> 4)
    if (x & 0x0F) < 8:
        cmap[index] = (cmap[index] & 0x0F) | (klass << 4)
    else:
        cmap[index] = (cmap[index] & 0xF0) | klass


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


class FloorTableTests(unittest.TestCase):
    """``$19C04``'s per-round class tables, read the way ``sub_0000AD30`` does."""

    def test_round_6_has_a_wall_two_belts_and_no_floor_class_that_drops(self) -> None:
        self.assertTrue(is_hole_class(ROUND_6, 0))
        self.assertEqual(floor_kind(ROUND_6, 1), FLOOR_SOLID)
        # Floor at z 0: 160 px of machine housing over a street at z 160.
        self.assertTrue(is_wall_class(ROUND_6, 2))
        self.assertEqual(floor_kind(ROUND_6, 3), FLOOR_CONVEYOR_RIGHT)
        self.assertEqual(floor_kind(ROUND_6, 4), FLOOR_CONVEYOR_LEFT)
        for belt in (3, 4):
            self.assertFalse(is_hole_class(ROUND_6, belt))
            self.assertFalse(is_wall_class(ROUND_6, belt))

    def test_rounds_1_to_5_drop_through_classes_0_3_and_4(self) -> None:
        for level_index in range(5):
            for klass in (0, 3, 4):
                self.assertEqual(floor_kind(level_index, klass), FLOOR_NONE)
                self.assertTrue(is_hole_class(level_index, klass))
            self.assertEqual(floor_kind(level_index, 1), FLOOR_SOLID)
            # Kind 16: past the four-entry jump table, a class no map uses.
            self.assertIsNone(floor_kind(level_index, 2))
            self.assertFalse(is_wall_class(level_index, 2))

    def test_round_7_raised_floor_is_a_wall_to_the_street(self) -> None:
        # Class 3 is floor at z 96 over a street at 136: 40 px up.
        self.assertTrue(is_wall_class(ROUND_7, 2))
        self.assertTrue(is_wall_class(ROUND_7, 3))

    def test_a_class_past_the_table_is_nothing(self) -> None:
        self.assertIsNone(floor_kind(ROUND_6, 9))
        self.assertFalse(is_hole_class(ROUND_6, 9))
        self.assertFalse(is_wall_class(ROUND_6, 9))


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

    def test_the_round_decides_what_a_hole_is(self) -> None:
        # A 16x16 block of class 3: a hole in round 4, a belt in round 6.
        stride = 4
        cmap = bytearray([0x11] * (stride * 3))
        cmap[1] = 0x33
        cmap[stride + 1] = 0x33

        round_4 = find_floor_holes(
            bytes(cmap), stride=stride, lane_max=16, world_x_max=64, level_index=ROUND_4
        )
        round_6 = find_floor_holes(
            bytes(cmap), stride=stride, lane_max=16, world_x_max=64, level_index=ROUND_6
        )

        self.assertEqual(round_4, (FloorHole(world_x=16, lane_y=0, width=16, height=16),))
        self.assertEqual(round_6, ())

    def test_a_scan_starting_mid_cell_reports_the_cell_edges(self) -> None:
        # holes_for_level starts at camera_x - 512, any X at all: the hole is
        # still where its cells are, not up to 7 px off.
        stride = 8
        cmap = bytearray([0x11] * (stride * 3))
        cmap[stride + 3] = 0x00  # x 48..64, lane 8
        cmap[2 * stride + 3] = 0x00

        holes = find_floor_holes(
            bytes(cmap), stride=stride, lane_max=16, world_x_min=5, world_x_max=128
        )

        self.assertEqual(holes, (FloorHole(world_x=48, lane_y=8, width=16, height=16),))


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
            level_index=ROUND_6,
        )
        barriers = find_collision_barriers(
            bytes(cmap),
            stride=stride,
            level_index=ROUND_6,
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

    def _round_6_street(self) -> tuple[bytes, int]:
        """Round 6 around the first housing past Bongo, as the live dump has it.

        The housing's left edge steps 8 px right per 8-lane row, x 2512..2680
        on lanes 0-7 to 2568..2680 on lanes 56-63; a right belt runs below it
        and a left belt further on.
        """

        stride = 180  # 2880 px
        cmap = bytearray([0x11] * (stride * 15))
        for row in range(8):
            for x in range(2512 + 8 * row, 2680, 8):
                _set_class(cmap, stride, x, 8 * row, 2)
        for lane in range(64, 120, 8):
            for x in range(2424 + lane - 64, 2560 + lane - 64, 8):
                _set_class(cmap, stride, x, lane, 3)
            for x in range(2848 - 64 + lane, 2880, 8):
                _set_class(cmap, stride, x, lane, 4)
        return bytes(cmap), stride

    def test_the_round_6_housing_is_one_rectangle_per_row(self) -> None:
        cmap, stride = self._round_6_street()

        walls = find_collision_barriers(
            cmap, stride=stride, level_index=ROUND_6, lane_max=112, world_x_min=2000
        )

        self.assertEqual(
            walls,
            tuple(
                FloorHole(world_x=2512 + 8 * row, lane_y=8 * row, width=168 - 8 * row, height=8)
                for row in range(8)
            ),
        )

    def test_the_floor_the_housing_steps_leave_is_outside_every_wall(self) -> None:
        # The bounding box would put this in the wall -- and an actor standing
        # there, centre inside it, would have the obstacle dropped whole.
        cmap, stride = self._round_6_street()

        walls = find_collision_barriers(
            cmap, stride=stride, level_index=ROUND_6, lane_max=112, world_x_min=2000
        )

        inside = [
            w
            for w in walls
            if w.world_x <= 2530 < w.world_x_end and w.lane_y <= 60 < w.lane_y_end
        ]
        self.assertEqual(inside, [])

    def test_belts_are_neither_walls_nor_holes(self) -> None:
        cmap, stride = self._round_6_street()

        walls = find_collision_barriers(
            cmap, stride=stride, level_index=ROUND_6, lane_max=112, world_x_min=2000
        )
        holes = find_floor_holes(
            cmap, stride=stride, lane_max=112, world_x_min=2000, level_index=ROUND_6
        )

        self.assertTrue(all(w.lane_y_end <= 64 for w in walls), walls)
        self.assertEqual(holes, ())

    def test_a_window_starting_mid_cell_reports_the_cell_edges(self) -> None:
        cmap, stride = self._round_6_street()

        walls = find_collision_barriers(
            cmap, stride=stride, level_index=ROUND_6, lane_max=112, world_x_min=2505
        )

        self.assertEqual(walls[0].world_x, 2512)


if __name__ == "__main__":
    unittest.main()
