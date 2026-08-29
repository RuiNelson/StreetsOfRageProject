"""Rectangles, segments and the touching-is-not-overlapping rule."""

from __future__ import annotations

import math
import unittest

from sor_autoplay.ai.pathfind import Direction, Edge, Point, Rect, Segment
from sor_autoplay.ai.pathfind.geometry import direction_from_offset, octile_distance


class RectTests(unittest.TestCase):
    def test_rectangle_rejects_negative_extent(self) -> None:
        with self.assertRaises(ValueError):
            Rect(0, 0, -1, 4)

    def test_flush_rectangles_touch_without_overlapping(self) -> None:
        left = Rect(0, 0, 10, 10)
        right = Rect(10, 0, 10, 10)

        self.assertFalse(left.overlaps(right))
        self.assertTrue(left.overlaps(right.moved_by(-0.5, 0)))

    def test_containment_allows_flush_borders(self) -> None:
        world = Rect(0, 0, 100, 50)

        self.assertTrue(world.contains(Rect(90, 40, 10, 10)))
        self.assertFalse(world.contains(Rect(90, 40, 10, 11)))

    def test_edges_are_the_sides_of_the_rectangle(self) -> None:
        rect = Rect(10, 20, 30, 40)

        self.assertEqual(rect.edge(Edge.LEFT), Segment(Point(10, 20), Point(10, 60)))
        self.assertEqual(rect.edge(Edge.RIGHT), Segment(Point(40, 20), Point(40, 60)))
        self.assertEqual(rect.edge(Edge.TOP), Segment(Point(10, 20), Point(40, 20)))
        self.assertEqual(rect.edge(Edge.BOTTOM), Segment(Point(10, 60), Point(40, 60)))

    def test_union_is_the_swept_box_of_an_axis_move(self) -> None:
        rect = Rect(0, 0, 8, 8)

        self.assertEqual(rect.union(rect.moved_by(16, 0)), Rect(0, 0, 24, 8))

    def test_gap_is_zero_on_an_overlapping_axis(self) -> None:
        rect = Rect(0, 0, 10, 10)
        other = Rect(30, 5, 10, 10)

        self.assertEqual(rect.gap_to(other), (20, 0))
        self.assertEqual(rect.gap_to(rect), (0, 0))


class SegmentTests(unittest.TestCase):
    def test_segments_crossing_and_touching_both_intersect(self) -> None:
        horizontal = Segment(Point(0, 0), Point(10, 0))

        self.assertTrue(horizontal.intersects(Segment(Point(5, -5), Point(5, 5))))
        self.assertTrue(horizontal.intersects(Segment(Point(10, 0), Point(20, 10))))
        # collinear
        self.assertTrue(horizontal.intersects(Segment(Point(5, 0), Point(8, 0))))
        self.assertFalse(horizontal.intersects(Segment(Point(5, 1), Point(8, 1))))

    def test_diagonal_segment_is_handled_like_any_other(self) -> None:
        diagonal = Segment(Point(0, 0), Point(10, 10))

        self.assertTrue(diagonal.intersects(Segment(Point(0, 10), Point(10, 0))))
        self.assertFalse(diagonal.intersects(Segment(Point(0, 5), Point(4, 9))))


class DirectionTests(unittest.TestCase):
    def test_direction_offsets_round_trip(self) -> None:
        self.assertIs(direction_from_offset(3, -3), Direction.UP_RIGHT)
        self.assertIs(direction_from_offset(0, 7), Direction.DOWN)
        with self.assertRaises(ValueError):
            direction_from_offset(0, 0)

    def test_octile_distance_matches_eight_direction_travel(self) -> None:
        self.assertAlmostEqual(octile_distance(5, 0), 5)
        self.assertAlmostEqual(octile_distance(4, 4), 4 * math.sqrt(2))
        self.assertAlmostEqual(octile_distance(10, 4), 4 * math.sqrt(2) + 6)
