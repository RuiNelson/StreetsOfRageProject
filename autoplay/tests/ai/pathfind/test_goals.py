"""Point and segment destinations, and the edge rule that separates them."""

from __future__ import annotations

import pytest

from sor_autoplay.ai.pathfind import Edge, Point, PointGoal, Rect, Segment, SegmentGoal


def test_point_goal_is_reached_by_covering_the_point() -> None:
    goal = PointGoal(Point(20, 20))

    assert goal.is_reached(Rect(16, 16, 8, 8))
    assert goal.is_reached(Rect(20, 20, 8, 8))  # exactly on a corner
    assert not goal.is_reached(Rect(0, 0, 8, 8))


def test_point_goal_tolerance_widens_the_body_for_the_test() -> None:
    goal = PointGoal(Point(20, 0), tolerance=4)

    assert goal.is_reached(Rect(8, 0, 8, 8))
    assert not goal.is_reached(Rect(4, 0, 8, 8))


def test_segment_goal_only_counts_the_named_edges() -> None:
    line = Segment(Point(50, 0), Point(50, 100))
    right_edge_only = SegmentGoal.of(line, {Edge.RIGHT})

    touching_with_right = Rect(42, 40, 8, 8)
    touching_with_left = Rect(50, 40, 8, 8)

    assert right_edge_only.is_reached(touching_with_right)
    assert not right_edge_only.is_reached(touching_with_left)
    assert SegmentGoal.of(line, {Edge.LEFT}).is_reached(touching_with_left)


def test_segment_goal_accepts_several_edges() -> None:
    line = Segment(Point(50, 0), Point(50, 100))
    goal = SegmentGoal.of(line, {Edge.LEFT, Edge.RIGHT})

    assert goal.is_reached(Rect(42, 40, 8, 8))
    assert goal.is_reached(Rect(50, 40, 8, 8))


def test_segment_goal_ignores_a_segment_swallowed_by_the_body() -> None:
    goal = SegmentGoal.of(Segment(Point(20, 20), Point(22, 22)), {Edge.RIGHT})

    assert not goal.is_reached(Rect(10, 10, 30, 30))


def test_segment_goal_needs_at_least_one_edge() -> None:
    with pytest.raises(ValueError):
        SegmentGoal(Segment(Point(0, 0), Point(1, 1)), frozenset())


def test_bounding_boxes_cover_the_goal() -> None:
    assert PointGoal(Point(5, 7)).bounding_box() == Rect(5, 7, 0, 0)
    assert SegmentGoal.of(
        Segment(Point(10, 40), Point(4, 0)), {Edge.TOP}
    ).bounding_box() == Rect(4, 0, 6, 40)
