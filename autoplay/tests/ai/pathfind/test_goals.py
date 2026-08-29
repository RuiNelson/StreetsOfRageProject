"""Point and segment destinations, and the edge rule that separates them."""

from __future__ import annotations

import unittest

from sor_autoplay.ai.pathfind import (
    HORIZONTAL_EDGES,
    Edge,
    Point,
    PointGoal,
    Rect,
    RectGoal,
    RegionGoal,
    Segment,
    SegmentGoal,
)


class PointGoalTests(unittest.TestCase):
    def test_point_goal_is_reached_by_covering_the_point(self) -> None:
        goal = PointGoal(Point(20, 20))

        self.assertTrue(goal.is_reached(Rect(16, 16, 8, 8)))
        # exactly on a corner
        self.assertTrue(goal.is_reached(Rect(20, 20, 8, 8)))
        self.assertFalse(goal.is_reached(Rect(0, 0, 8, 8)))

    def test_point_goal_tolerance_widens_the_body_for_the_test(self) -> None:
        goal = PointGoal(Point(20, 0), tolerance=4)

        self.assertTrue(goal.is_reached(Rect(8, 0, 8, 8)))
        self.assertFalse(goal.is_reached(Rect(4, 0, 8, 8)))


class SegmentGoalTests(unittest.TestCase):
    def test_segment_goal_only_counts_the_named_edges(self) -> None:
        line = Segment(Point(50, 0), Point(50, 100))
        right_edge_only = SegmentGoal.of(line, {Edge.RIGHT})

        touching_with_right = Rect(42, 40, 8, 8)
        touching_with_left = Rect(50, 40, 8, 8)

        self.assertTrue(right_edge_only.is_reached(touching_with_right))
        self.assertFalse(right_edge_only.is_reached(touching_with_left))
        self.assertTrue(SegmentGoal.of(line, {Edge.LEFT}).is_reached(touching_with_left))

    def test_segment_goal_accepts_several_edges(self) -> None:
        line = Segment(Point(50, 0), Point(50, 100))
        goal = SegmentGoal.of(line, {Edge.LEFT, Edge.RIGHT})

        self.assertTrue(goal.is_reached(Rect(42, 40, 8, 8)))
        self.assertTrue(goal.is_reached(Rect(50, 40, 8, 8)))

    def test_segment_goal_ignores_a_segment_swallowed_by_the_body(self) -> None:
        goal = SegmentGoal.of(Segment(Point(20, 20), Point(22, 22)), {Edge.RIGHT})

        self.assertFalse(goal.is_reached(Rect(10, 10, 30, 30)))

    def test_segment_goal_needs_at_least_one_edge(self) -> None:
        with self.assertRaises(ValueError):
            SegmentGoal(Segment(Point(0, 0), Point(1, 1)), frozenset())


class RectGoalTests(unittest.TestCase):
    def test_horizontal_rect_goal_needs_the_boxes_stacked(self) -> None:
        crate = Rect(100, 40, 16, 16)
        goal = RectGoal.horizontal(crate)

        above = Rect(100, 24, 16, 16)  # bottom edge on the crate's top edge
        below = Rect(100, 56, 16, 16)  # top edge on the crate's bottom edge
        beside = Rect(84, 40, 16, 16)  # touching, but vertical edges meeting
        apart = Rect(100, 20, 16, 16)  # stacked but 4px short

        self.assertTrue(goal.is_reached(above))
        self.assertTrue(goal.is_reached(below))
        self.assertFalse(goal.is_reached(beside))
        self.assertFalse(goal.is_reached(apart))

    def test_horizontal_rect_goal_needs_the_spans_to_overlap(self) -> None:
        goal = RectGoal.horizontal(Rect(100, 40, 16, 16))

        # partly above: still meets
        self.assertTrue(goal.is_reached(Rect(108, 24, 16, 16)))
        # corner to corner
        self.assertTrue(goal.is_reached(Rect(116, 24, 16, 16)))
        # right of it entirely
        self.assertFalse(goal.is_reached(Rect(124, 24, 16, 16)))

    def test_vertical_rect_goal_is_the_other_orientation(self) -> None:
        crate = Rect(100, 40, 16, 16)
        goal = RectGoal.vertical(crate)

        self.assertTrue(goal.is_reached(Rect(84, 40, 16, 16)))
        self.assertTrue(goal.is_reached(Rect(116, 40, 16, 16)))
        self.assertFalse(goal.is_reached(Rect(100, 24, 16, 16)))

    def test_a_rect_goal_can_name_one_pairing_only(self) -> None:
        crate = Rect(100, 40, 16, 16)
        from_above_only = RectGoal(crate, frozenset({(Edge.BOTTOM, Edge.TOP)}))

        self.assertTrue(from_above_only.is_reached(Rect(100, 24, 16, 16)))
        self.assertFalse(from_above_only.is_reached(Rect(100, 56, 16, 16)))

    def test_of_builds_the_cross_product_including_aligned_pairs(self) -> None:
        crate = Rect(100, 40, 16, 16)
        goal = RectGoal.of(crate, HORIZONTAL_EDGES, HORIZONTAL_EDGES)

        self.assertEqual(len(goal.contacts), 4)
        # Side by side: the tops are collinear and overlap, so a cross product
        # reports arrival where `horizontal()` correctly does not.
        self.assertTrue(goal.is_reached(Rect(116, 40, 16, 16)))
        self.assertFalse(RectGoal.horizontal(crate).is_reached(Rect(116, 40, 16, 16)))

    def test_a_rect_goal_needs_at_least_one_pairing(self) -> None:
        with self.assertRaises(ValueError):
            RectGoal(Rect(0, 0, 8, 8), frozenset())


class RegionGoalTests(unittest.TestCase):
    def test_region_goal_is_reached_by_overlapping_it(self) -> None:
        goal = RegionGoal.of(Rect(100, 40, 40, 20))

        self.assertTrue(goal.is_reached(Rect(96, 36, 16, 16)))
        self.assertFalse(goal.is_reached(Rect(60, 40, 16, 16)))
        # Arriving is inclusive: flush against the region's edge has arrived,
        # and `contact` is what tells that apart from a real overlap.
        self.assertTrue(goal.is_reached(Rect(84, 40, 16, 16)))
        self.assertEqual(goal.contact(Rect(84, 40, 16, 16)), 0)
        self.assertFalse(goal.is_reached(Rect(83, 40, 16, 16)))

    def test_region_contact_measures_the_named_axis(self) -> None:
        goal = RegionGoal.of(Rect(100, 40, 40, 20), axis="y")
        body = Rect(96, 42, 16, 16)

        # whole body height inside the region
        self.assertEqual(goal.contact(body), 16)
        self.assertEqual(goal.contact(Rect(96, 50, 16, 16)), 10)
        self.assertEqual(RegionGoal.of(Rect(100, 40, 40, 20), axis="x").contact(body), 12)

    def test_region_contact_plateaus_then_falls_off_to_the_edge(self) -> None:
        # Body 16 tall, region 24 tall: full contact while it is inside, then a
        # px lost per px of drift, reaching 0 exactly at the region's edge.
        goal = RegionGoal.of(Rect(0, 0, 40, 24), axis="y")
        measured = [goal.contact(Rect(0, offset, 16, 16)) for offset in range(0, 26, 4)]

        self.assertEqual(measured, [16, 16, 16, 12, 8, 4, 0])
        # Flush at the edge is still an arrival, with nothing to show for it.
        self.assertTrue(goal.is_reached(Rect(0, 24, 16, 16)))
        self.assertEqual(goal.contact(Rect(0, 24, 16, 16)), 0)
        self.assertFalse(goal.is_reached(Rect(0, 25, 16, 16)))

    def test_region_misalignment_is_the_contact_still_missing(self) -> None:
        goal = RegionGoal.of(Rect(0, 0, 40, 24), axis="y")

        self.assertEqual(goal.misalignment(Rect(0, 4, 16, 16)), 0)
        self.assertEqual(goal.misalignment(Rect(0, 16, 16, 16)), 8)

    def test_a_region_goal_rejects_an_unknown_axis(self) -> None:
        with self.assertRaises(ValueError):
            RegionGoal.of(Rect(0, 0, 8, 8), axis="z")

    def test_a_region_goal_needs_a_region(self) -> None:
        with self.assertRaises(ValueError):
            RegionGoal.of()

    def test_several_regions_are_alternatives_and_the_body_may_be_in_either(self) -> None:
        # The annulus case: two bands with a hole between them, which is what a
        # strike's ground looks like -- close enough to reach, far enough not to
        # be standing on the target.
        left_band = Rect(0, 0, 20, 24)
        right_band = Rect(60, 0, 20, 24)
        goal = RegionGoal.of(left_band, right_band, axis="y")

        self.assertTrue(goal.is_reached(Rect(8, 4, 16, 16)))
        self.assertTrue(goal.is_reached(Rect(56, 4, 16, 16)))
        # in the hole
        self.assertFalse(goal.is_reached(Rect(32, 4, 16, 16)))
        self.assertEqual(goal.bounding_box(), Rect(0, 0, 80, 24))

    def test_contact_is_measured_against_the_region_the_body_is_in(self) -> None:
        goal = RegionGoal.of(Rect(0, 0, 20, 24), Rect(60, 0, 20, 24), axis="y")

        self.assertEqual(goal.contact(Rect(8, 16, 16, 16)), 8)
        self.assertEqual(goal.misalignment(Rect(8, 16, 16, 16)), 8)
        # not in any region
        self.assertEqual(goal.contact(Rect(32, 4, 16, 16)), 0)


class BoundingBoxTests(unittest.TestCase):
    def test_bounding_boxes_cover_the_goal(self) -> None:
        self.assertEqual(
            RectGoal.horizontal(Rect(5, 7, 9, 9)).bounding_box(), Rect(5, 7, 9, 9)
        )
        self.assertEqual(PointGoal(Point(5, 7)).bounding_box(), Rect(5, 7, 0, 0))
        self.assertEqual(
            SegmentGoal.of(
                Segment(Point(10, 40), Point(4, 0)), {Edge.TOP}
            ).bounding_box(),
            Rect(4, 0, 6, 40),
        )
