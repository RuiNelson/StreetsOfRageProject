"""Rectangles, segments and the touching-is-not-overlapping rule."""

from __future__ import annotations

import math

import pytest

from sor_autoplay.ai.pathfind import Direction, Edge, Point, Rect, Segment
from sor_autoplay.ai.pathfind.geometry import (
    direction_from_offset,
    manhattan_distance,
    octile_distance,
)


def test_rectangle_rejects_negative_extent() -> None:
    with pytest.raises(ValueError):
        Rect(0, 0, -1, 4)


def test_flush_rectangles_touch_without_overlapping() -> None:
    left = Rect(0, 0, 10, 10)
    right = Rect(10, 0, 10, 10)

    assert not left.overlaps(right)
    assert left.overlaps(right.moved_by(-0.5, 0))


def test_containment_allows_flush_borders() -> None:
    world = Rect(0, 0, 100, 50)

    assert world.contains(Rect(90, 40, 10, 10))
    assert not world.contains(Rect(90, 40, 10, 11))


def test_edges_are_the_sides_of_the_rectangle() -> None:
    rect = Rect(10, 20, 30, 40)

    assert rect.edge(Edge.LEFT) == Segment(Point(10, 20), Point(10, 60))
    assert rect.edge(Edge.RIGHT) == Segment(Point(40, 20), Point(40, 60))
    assert rect.edge(Edge.TOP) == Segment(Point(10, 20), Point(40, 20))
    assert rect.edge(Edge.BOTTOM) == Segment(Point(10, 60), Point(40, 60))


def test_union_is_the_swept_box_of_an_axis_move() -> None:
    rect = Rect(0, 0, 8, 8)

    assert rect.union(rect.moved_by(16, 0)) == Rect(0, 0, 24, 8)


def test_gap_is_zero_on_an_overlapping_axis() -> None:
    rect = Rect(0, 0, 10, 10)
    other = Rect(30, 5, 10, 10)

    assert rect.gap_to(other) == (20, 0)
    assert rect.gap_to(rect) == (0, 0)


def test_segments_crossing_and_touching_both_intersect() -> None:
    horizontal = Segment(Point(0, 0), Point(10, 0))

    assert horizontal.intersects(Segment(Point(5, -5), Point(5, 5)))
    assert horizontal.intersects(Segment(Point(10, 0), Point(20, 10)))
    assert horizontal.intersects(Segment(Point(5, 0), Point(8, 0)))  # collinear
    assert not horizontal.intersects(Segment(Point(5, 1), Point(8, 1)))


def test_diagonal_segment_is_handled_like_any_other() -> None:
    diagonal = Segment(Point(0, 0), Point(10, 10))

    assert diagonal.intersects(Segment(Point(0, 10), Point(10, 0)))
    assert not diagonal.intersects(Segment(Point(0, 5), Point(4, 9)))


def test_direction_offsets_round_trip() -> None:
    assert direction_from_offset(3, -3) is Direction.UP_RIGHT
    assert direction_from_offset(0, 7) is Direction.DOWN
    with pytest.raises(ValueError):
        direction_from_offset(0, 0)


def test_octile_distance_matches_eight_direction_travel() -> None:
    assert octile_distance(5, 0) == pytest.approx(5)
    assert octile_distance(4, 4) == pytest.approx(4 * math.sqrt(2))
    assert octile_distance(10, 4) == pytest.approx(4 * math.sqrt(2) + 6)


def test_manhattan_distance_is_the_cardinal_walk() -> None:
    assert manhattan_distance(5, 0) == pytest.approx(5)
    assert manhattan_distance(-4, 4) == pytest.approx(8)
    assert manhattan_distance(10, 4) == pytest.approx(14)
