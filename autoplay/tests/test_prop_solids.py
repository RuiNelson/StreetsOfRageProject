import unittest

from sor_autoplay import prop_solids


class RecordSelectionTests(unittest.TestCase):
    def test_named_types_get_their_own_record(self) -> None:
        # The compare chain at $3BC4..$3C00, type by type.
        self.assertEqual(prop_solids.record_for_type(0x11), (-28, 56, -10, 14))
        self.assertEqual(prop_solids.record_for_type(0x19), (-28, 56, -10, 14))
        self.assertEqual(prop_solids.record_for_type(0x18), (-28, 56, -16, 20))
        self.assertEqual(prop_solids.record_for_type(0x1D), (-30, 60, -28, 32))
        self.assertEqual(prop_solids.record_for_type(0x1F), (-30, 60, -20, 24))
        self.assertEqual(prop_solids.record_for_type(0x41), (-36, 72, -20, 24))

    def test_an_unnamed_type_falls_through_to_the_last_record(self) -> None:
        # The chain ends in `nop`, not a branch: d4 still holds the last
        # record's offset, so every unnamed solid type uses it.
        self.assertEqual(
            prop_solids.record_for_type(0x1B), prop_solids.record_for_type(0x41)
        )

    def test_every_record_ends_four_px_in_front_of_the_origin(self) -> None:
        # A prop is solid behind its feet and walkable in front of them.
        for type_id in (0x11, 0x19, 0x18, 0x1D, 0x1F, 0x41, 0x1B):
            with self.subTest(type_id=type_id):
                _, _, dy0, height = prop_solids.record_for_type(type_id)
                self.assertEqual(dy0 + height, 4)


class SolidBoxTests(unittest.TestCase):
    def test_the_box_is_not_the_sprite(self) -> None:
        # The stage-5 prop, live: sprite body box lane 86..106, wall 76..100.
        box = prop_solids.solid_box(0x1F, 1648, 96)

        self.assertEqual((box.x0, box.x1), (1618, 1678))
        self.assertEqual((box.y0, box.y1), (76, 100))

    def test_blocking_is_strict_on_every_edge(self) -> None:
        # Two `bcc` exits per axis: a position exactly on an edge is clear.
        # Measured live on stage 5 -- holding UP into a prop standing at lane
        # 56 comes to rest at lane 60, its box's own lower edge.
        box = prop_solids.solid_box(0x1F, 1584, 56)

        self.assertEqual(box.y1, 60)
        self.assertFalse(box.blocks(1584, 60))
        self.assertTrue(box.blocks(1584, 59))
        self.assertFalse(box.blocks(box.x0, 50))
        self.assertTrue(box.blocks(box.x0 + 1, 50))

    def test_the_stage_5_fence_leaves_a_16px_lane_corridor(self) -> None:
        # Rows at lane 56 and 96: the corridor between them is 60..76, which
        # is what the live probe walked (UP stopped at 60, DOWN at 75).
        upper = prop_solids.solid_box(0x1F, 1584, 56)
        lower = prop_solids.solid_box(0x1F, 1584, 96)

        self.assertEqual(upper.y1, 60)
        self.assertEqual(lower.y0, 76)

    def test_half_width_is_the_wall_reach(self) -> None:
        self.assertEqual(prop_solids.solid_half_width(0x1F), 30)
        self.assertEqual(prop_solids.solid_half_width(0x11), 28)
        self.assertEqual(prop_solids.solid_half_width(0x41), 36)


if __name__ == "__main__":
    unittest.main()
