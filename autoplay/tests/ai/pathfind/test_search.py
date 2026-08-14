"""The search itself: step lengths, obstacles, goals and failure."""

from __future__ import annotations

import math

import pytest

from sor_autoplay.ai.pathfind import (
    Direction,
    Edge,
    Point,
    PointGoal,
    Rect,
    RectGoal,
    Segment,
    SegmentGoal,
    find_path,
)

WORLD = Rect(0, 0, 320, 112)
BODY = Rect(0, 0, 16, 16)


def plan(**kwargs):
    options = {"world": WORLD, "step": 8}
    options.update(kwargs)
    return find_path(**options)


def walked(path) -> tuple[float, float]:
    return (
        sum(step.dx for step in path.steps),
        sum(step.dy for step in path.steps),
    )


def test_a_goal_already_satisfied_needs_no_steps() -> None:
    path = plan(start=BODY, goal=PointGoal(Point(4, 4)))

    assert path.reached
    assert path.steps == ()
    assert path.final == BODY


def test_a_straight_run_is_one_merged_vector() -> None:
    path = plan(start=BODY, goal=PointGoal(Point(100, 8)))

    assert path.reached
    assert len(path.steps) == 1
    assert path.steps[0].direction is Direction.RIGHT
    assert path.steps[0].length == 88


def test_every_vector_is_a_multiple_of_the_step_and_never_shorter() -> None:
    path = plan(
        start=BODY,
        goal=PointGoal(Point(200, 100)),
        obstacles=[Rect(64, 0, 16, 80), Rect(140, 40, 16, 72)],
    )

    assert path.reached
    for step in path.steps:
        assert step.length >= 8
        assert step.length % 8 == 0


def test_the_first_half_of_an_open_diagonal_is_diagonal_then_it_straightens() -> None:
    # Both axes are 48px; X wins the tie. The first 24px may cut the
    # corner; after that every vector is a cardinal.
    path = plan(start=BODY, goal=PointGoal(Point(64, 64)))

    assert path.reached
    assert path.steps[0].direction is Direction.DOWN_RIGHT
    assert path.steps[0].length == 24
    assert all(not step.direction.is_diagonal for step in path.steps[1:])
    assert path.final == Rect(48, 48, 16, 16)


def test_a_small_off_axis_gap_is_picked_up_diagonally_then_the_long_axis_runs_straight() -> None:
    # 184px of X, 16px of Y: dominant is X, so the first 92px of X may
    # include the diagonal that soaks up Y, and everything after that is
    # a single RIGHT.
    path = plan(start=BODY, goal=PointGoal(Point(200, 32)))

    assert path.reached
    assert path.steps[0].direction is Direction.DOWN_RIGHT
    assert all(not step.direction.is_diagonal for step in path.steps[1:])
    assert path.steps[-1].direction is Direction.RIGHT


def test_a_taller_goal_straightens_on_y() -> None:
    # Y is the farther axis, so the split is a horizontal midline: X is
    # soaked up with a diagonal while more than half of Y remains, and
    # the last stretch is DOWN.
    path = plan(start=BODY, goal=PointGoal(Point(32, 96)))

    assert path.reached
    assert any(step.direction.is_diagonal for step in path.steps)
    assert path.steps[-1].direction is Direction.DOWN
    assert not path.steps[-1].direction.is_diagonal


def test_a_late_diagonal_is_used_when_cardinals_cannot_arrive() -> None:
    # Already touching the crate's corner, so both axis gaps are zero and
    # the whole search is the "second half" -- cardinals unless they
    # cannot arrive. Hanging out of the world on both axes, the first
    # cardinal step lands still outside and only DOWN_RIGHT walks back in.
    start = Rect(-8, -8, 16, 16)
    crate = Rect(8, 8, 16, 16)
    goal = RectGoal(crate, frozenset({(Edge.LEFT, Edge.RIGHT)}))
    path = plan(start=start, goal=goal)

    assert not goal.is_reached(start)
    assert start.gap_to(goal.bounding_box()) == (0.0, 0.0)
    assert path.reached
    assert path.steps[0].direction is Direction.DOWN_RIGHT


def test_diagonals_can_be_turned_off() -> None:
    path = plan(start=BODY, goal=PointGoal(Point(64, 64)), allow_diagonals=False)

    assert path.reached
    assert all(not step.direction.is_diagonal for step in path.steps)


def test_the_body_walks_around_an_obstacle_instead_of_through_it() -> None:
    wall = Rect(48, 0, 16, 64)
    path = plan(start=BODY, goal=PointGoal(Point(120, 8)), obstacles=[wall])

    assert path.reached
    for rect in path.positions():
        assert not rect.overlaps(wall)
        assert WORLD.contains(rect)


def test_a_step_cannot_tunnel_through_a_thin_obstacle() -> None:
    # Thinner than one step: only a swept test can see it.
    fence = Rect(40, 0, 2, 112)
    path = plan(start=BODY, goal=PointGoal(Point(120, 8)), obstacles=[fence], step=32)

    assert not path.reached


def test_a_diagonal_does_not_cut_a_corner() -> None:
    obstacles = [Rect(16, 0, 16, 16), Rect(32, 16, 16, 16)]
    path = plan(
        start=BODY,
        goal=PointGoal(Point(40, 40)),
        obstacles=obstacles,
        step=16,
    )

    for previous, current in zip(path.positions(), path.positions()[1:]):
        swept = previous.union(current)
        assert not any(swept.overlaps(obstacle) for obstacle in obstacles)


def test_the_body_fits_the_gap_it_is_routed_through() -> None:
    # A 16px corridor for a 16px body: passable, and the only way across.
    obstacles = [Rect(64, 0, 16, 48), Rect(64, 64, 16, 48)]
    path = plan(start=BODY.moved_to(0, 48), goal=PointGoal(Point(160, 56)), obstacles=obstacles)

    assert path.reached
    for rect in path.positions():
        assert not any(rect.overlaps(obstacle) for obstacle in obstacles)


def test_a_body_too_wide_for_the_gap_is_not_routed_through_it() -> None:
    obstacles = [Rect(64, 0, 16, 48), Rect(64, 60, 16, 52)]
    path = plan(
        start=Rect(0, 44, 16, 16),
        goal=PointGoal(Point(160, 56)),
        obstacles=obstacles,
    )

    assert not path.reached


def test_a_walled_off_goal_returns_the_closest_best_effort() -> None:
    wall = Rect(64, 0, 16, 112)
    path = plan(start=BODY, goal=PointGoal(Point(200, 56)), obstacles=[wall])

    assert not path.reached
    assert path.steps  # still worth walking up to the wall
    assert path.final.right <= wall.left
    assert path.final.right > BODY.right


def test_a_segment_goal_stops_on_the_named_edge() -> None:
    threshold = Segment(Point(160, 0), Point(160, 112))
    path = plan(start=BODY, goal=SegmentGoal.of(threshold, {Edge.RIGHT}))

    assert path.reached
    assert path.final.right == pytest.approx(160)


def test_the_opposite_edge_goal_walks_past_the_line() -> None:
    threshold = Segment(Point(160, 0), Point(160, 112))
    path = plan(start=BODY, goal=SegmentGoal.of(threshold, {Edge.LEFT}))

    assert path.reached
    assert path.final.left == pytest.approx(160)


def test_a_segment_goal_only_counts_where_the_segment_actually_is() -> None:
    # The line spans the bottom half of the world only; a body kept in the
    # top half by the wall must come down to meet it.
    threshold = Segment(Point(200, 80), Point(200, 112))
    path = plan(start=BODY, goal=SegmentGoal.of(threshold, {Edge.RIGHT}))

    assert path.reached
    assert path.final.right == pytest.approx(200)
    assert path.final.bottom >= 80


def test_a_diagonal_segment_goal_is_reachable() -> None:
    goal = SegmentGoal.of(Segment(Point(120, 0), Point(200, 112)), {Edge.RIGHT})
    path = plan(start=BODY, goal=goal)

    assert path.reached
    assert goal.is_reached(path.final)


def test_a_rect_goal_arrives_stacked_not_merely_near() -> None:
    # The crate is solid as well as the destination: the body must stop
    # flush above or below it, never beside it.
    crate = Rect(160, 48, 16, 16)
    goal = RectGoal.horizontal(crate)
    path = plan(start=BODY, goal=goal, obstacles=[crate])

    assert path.reached
    assert goal.is_reached(path.final)
    assert not path.final.overlaps(crate)
    assert path.final.bottom == pytest.approx(48) or path.final.top == pytest.approx(64)


def test_a_rect_goal_from_one_side_only_walks_around_the_target() -> None:
    crate = Rect(160, 48, 16, 16)
    # Only "my top edge on its bottom edge": the body must end up *below*
    # the crate even though above is much closer to where it starts.
    goal = RectGoal(crate, frozenset({(Edge.TOP, Edge.BOTTOM)}))
    path = plan(start=BODY, goal=goal, obstacles=[crate])

    assert path.reached
    assert path.final.top == pytest.approx(64)
    for rect in path.positions():
        assert not rect.overlaps(crate)


def test_a_vertical_rect_goal_arrives_side_by_side() -> None:
    crate = Rect(160, 48, 16, 16)
    goal = RectGoal.vertical(crate)
    path = plan(start=BODY, goal=goal, obstacles=[crate])

    assert path.reached
    assert path.final.right == pytest.approx(160) or path.final.left == pytest.approx(176)


def test_a_rect_goal_the_body_cannot_line_up_with_fails_cleanly() -> None:
    # The crate sits flush against the top of the world, so nothing can ever
    # place a body's bottom edge on the crate's top edge or its top edge on
    # the crate's bottom edge without leaving the world... except from below,
    # which this pairing forbids.
    crate = Rect(160, 0, 16, 8)
    goal = RectGoal(crate, frozenset({(Edge.BOTTOM, Edge.TOP)}))
    path = plan(start=BODY.moved_to(0, 40), goal=goal, obstacles=[crate])

    assert not path.reached
    assert WORLD.contains(path.final)


def test_by_default_a_corner_touch_is_a_good_enough_arrival() -> None:
    # The cheapest way to put a left edge on the crate's right edge is to
    # clip its corner, and that is what the search settles for unless it is
    # told otherwise.
    crate = Rect(160, 48, 16, 16)
    goal = RectGoal(crate, frozenset({(Edge.LEFT, Edge.RIGHT)}))
    path = plan(start=BODY, goal=goal, obstacles=[crate])

    assert path.reached
    assert path.final.left == pytest.approx(176)
    assert path.misalignment > 0
    assert path.contact < 16


def test_maximize_contact_walks_the_extra_bit_to_line_up() -> None:
    crate = Rect(160, 48, 16, 16)
    goal = RectGoal(crate, frozenset({(Edge.LEFT, Edge.RIGHT)}))
    loose = plan(start=BODY, goal=goal, obstacles=[crate])
    flush = plan(start=BODY, goal=goal, obstacles=[crate], maximize_contact=True)

    assert flush.reached
    assert flush.misalignment == 0
    assert flush.contact == pytest.approx(16)  # the whole shared edge
    assert flush.final.left == pytest.approx(176)
    assert flush.final.top == pytest.approx(crate.top)
    assert flush.length >= loose.length  # alignment is paid for in walking


def test_maximize_contact_costs_more_expansions() -> None:
    crate = Rect(160, 48, 16, 16)
    goal = RectGoal.horizontal(crate)
    loose = plan(start=BODY, goal=goal, obstacles=[crate])
    flush = plan(start=BODY, goal=goal, obstacles=[crate], maximize_contact=True)

    assert flush.nodes_expanded >= loose.nodes_expanded


def test_enough_contact_refuses_arrivals_below_the_bar() -> None:
    crate = Rect(160, 48, 16, 16)
    goal = RectGoal(crate, frozenset({(Edge.LEFT, Edge.RIGHT)}))
    path = plan(start=BODY, goal=goal, obstacles=[crate], enough_contact=16)

    assert path.reached
    assert path.contact >= 16
    assert path.final.top == pytest.approx(crate.top)


def test_enough_contact_that_cannot_be_met_fails_cleanly() -> None:
    # Side-by-side contact is measured along the *vertical* edges, so it is
    # the crate's 8px height that caps it: a 16px body can never share more
    # than 8px of edge with it, however it approaches.
    crate = Rect(160, 48, 16, 8)
    path = plan(
        start=BODY,
        goal=RectGoal.vertical(crate),
        obstacles=[crate],
        enough_contact=16,
    )

    assert not path.reached


def test_enough_contact_ignores_goals_with_nothing_to_measure() -> None:
    # A point has no edge to share, so a contact requirement cannot make it
    # unreachable.
    path = plan(start=BODY, goal=PointGoal(Point(120, 40)), enough_contact=999)

    assert path.reached
    assert path.contact == math.inf


def test_maximize_contact_applies_to_a_parallel_segment_goal() -> None:
    # A vertical line only half as tall as the world: arriving at its very
    # end touches it with 0px of the body's edge, arriving level with it
    # touches with all 16.
    threshold = Segment(Point(200, 60), Point(200, 112))
    goal = SegmentGoal.of(threshold, {Edge.RIGHT})
    loose = plan(start=BODY, goal=goal)
    flush = plan(start=BODY, goal=goal, maximize_contact=True)

    assert loose.reached and flush.reached
    assert flush.contact >= loose.contact
    assert flush.contact == pytest.approx(16)
    assert flush.misalignment == 0


def test_an_oblique_segment_expresses_no_alignment_preference() -> None:
    goal = SegmentGoal.of(Segment(Point(120, 0), Point(200, 112)), {Edge.RIGHT})
    path = plan(start=BODY, goal=goal, maximize_contact=True, enough_contact=8)

    assert path.reached
    assert path.misalignment == 0
    assert path.contact == math.inf


def test_a_start_that_already_arrived_still_lines_up_when_asked() -> None:
    crate = Rect(48, 48, 16, 16)
    body = Rect(32, 56, 16, 16)  # left edge already on the crate's left side
    goal = RectGoal(crate, frozenset({(Edge.RIGHT, Edge.LEFT)}))

    assert goal.is_reached(body)
    assert not plan(start=body, goal=goal, obstacles=[crate]).steps

    flush = plan(start=body, goal=goal, obstacles=[crate], maximize_contact=True)
    assert flush.steps
    assert flush.misalignment == 0
    assert flush.final.top == pytest.approx(crate.top)


def test_a_body_starting_inside_an_obstacle_can_still_escape() -> None:
    # It cannot get out in one step, so the crate it stands in is dropped
    # from the collision set -- but every *other* obstacle still applies.
    crate = Rect(0, 0, 32, 32)
    wall = Rect(48, 0, 16, 64)
    path = plan(
        start=Rect(8, 8, 16, 16),
        goal=PointGoal(Point(80, 8)),
        obstacles=[crate, wall],
    )

    assert path.reached
    assert not path.final.overlaps(crate)
    for rect in path.positions():
        assert not rect.overlaps(wall)


def test_a_start_hanging_out_of_the_world_can_walk_back_in() -> None:
    path = plan(start=Rect(-8, 0, 16, 16), goal=PointGoal(Point(40, 8)))

    assert path.reached
    for rect in path.positions()[1:]:
        assert WORLD.contains(rect)


def test_the_body_never_leaves_the_world() -> None:
    # The lattice is anchored at the start, so x stays 300 - 8k and never
    # hits 0 exactly; tolerance is how a caller asks for "near enough".
    path = plan(start=Rect(300, 90, 16, 16), goal=PointGoal(Point(0, 0), tolerance=8))

    assert path.reached
    for rect in path.positions():
        assert WORLD.contains(rect)


def test_a_goal_outside_the_world_fails_without_raising() -> None:
    path = plan(start=BODY, goal=PointGoal(Point(1000, 1000)))

    assert not path.reached
    assert WORLD.contains(path.final)


def test_the_node_budget_bounds_the_work() -> None:
    path = plan(start=BODY, goal=PointGoal(Point(300, 100)), max_nodes=5)

    assert not path.reached
    assert path.nodes_expanded <= 5


def test_the_same_world_always_plans_the_same_route() -> None:
    obstacles = [Rect(64, 0, 16, 80), Rect(140, 40, 16, 72)]
    first = plan(start=BODY, goal=PointGoal(Point(200, 100)), obstacles=obstacles)
    second = plan(start=BODY, goal=PointGoal(Point(200, 100)), obstacles=obstacles)

    assert first.steps == second.steps


def test_the_route_around_an_obstacle_is_not_much_longer_than_the_direct_one() -> None:
    obstacles = [Rect(64, 0, 16, 40)]
    path = plan(start=BODY.moved_to(0, 0), goal=PointGoal(Point(160, 8)), obstacles=obstacles)

    assert path.reached
    # A straight run would be ~144. Going around a 40px wall on cardinals
    # plus a first-half diagonal is a bit over 200; anything much larger
    # would be a wild detour, not a go-around.
    assert path.length < 220


def test_positions_and_walked_offsets_agree_with_the_final_rectangle() -> None:
    path = plan(
        start=BODY,
        goal=PointGoal(Point(150, 90)),
        obstacles=[Rect(64, 0, 16, 64)],
    )
    dx, dy = walked(path)

    assert path.positions()[-1] == path.final
    assert path.final == BODY.moved_by(dx, dy)


def test_a_zero_or_negative_step_is_rejected() -> None:
    with pytest.raises(ValueError):
        plan(start=BODY, goal=PointGoal(Point(10, 10)), step=0)
