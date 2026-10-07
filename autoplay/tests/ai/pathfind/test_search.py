"""The search itself: step lengths, obstacles, goals and failure."""

from __future__ import annotations

import math
import random
import time
import unittest
from unittest import mock

from sor_autoplay.ai.pathfind import (
    Direction,
    Edge,
    Lattice,
    Point,
    PointGoal,
    Rect,
    RectGoal,
    RegionGoal,
    Segment,
    SegmentGoal,
    find_path,
)
from sor_autoplay.ai.pathfind import search as search_module

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


def close(a: float, b: float) -> bool:
    """``pytest.approx``'s default tolerance, for the ``or`` comparisons."""

    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)


class StepShapeTests(unittest.TestCase):
    def test_a_goal_already_satisfied_needs_no_steps(self) -> None:
        path = plan(start=BODY, goal=PointGoal(Point(4, 4)))

        self.assertTrue(path.reached)
        self.assertEqual(path.steps, ())
        self.assertEqual(path.final, BODY)

    def test_a_straight_run_is_one_merged_vector(self) -> None:
        path = plan(start=BODY, goal=PointGoal(Point(100, 8)))

        self.assertTrue(path.reached)
        self.assertEqual(len(path.steps), 1)
        self.assertIs(path.steps[0].direction, Direction.RIGHT)
        self.assertEqual(path.steps[0].length, 88)

    def test_every_vector_is_a_multiple_of_the_step_and_never_shorter(self) -> None:
        path = plan(
            start=BODY,
            goal=PointGoal(Point(200, 100)),
            obstacles=[Rect(64, 0, 16, 80), Rect(140, 40, 16, 72)],
        )

        self.assertTrue(path.reached)
        for step in path.steps:
            self.assertGreaterEqual(step.length, 8)
            self.assertEqual(step.length % 8, 0)

    def test_a_clear_offset_is_two_axis_aligned_vectors_y_then_x(self) -> None:
        path = plan(start=BODY, goal=PointGoal(Point(64, 64)))

        self.assertTrue(path.reached)
        self.assertEqual(
            [step.direction for step in path.steps],
            [Direction.DOWN, Direction.RIGHT],
        )
        self.assertEqual(path.steps[0].length, 48)
        self.assertEqual(path.steps[1].length, 48)
        self.assertAlmostEqual(path.length, 96)

    def test_a_straight_vertical_run_is_one_merged_vector(self) -> None:
        path = plan(start=BODY, goal=PointGoal(Point(8, 80)))

        self.assertTrue(path.reached)
        self.assertEqual(len(path.steps), 1)
        self.assertIs(path.steps[0].direction, Direction.DOWN)
        self.assertEqual(path.steps[0].length, 64)

    def test_y_then_x_walks_up_then_left_when_that_is_the_offset(self) -> None:
        path = plan(start=BODY.moved_to(200, 80), goal=PointGoal(Point(40, 8)))

        self.assertTrue(path.reached)
        self.assertEqual(
            [step.direction for step in path.steps],
            [Direction.UP, Direction.LEFT],
        )

    def test_y_then_x_is_used_when_it_clears_a_wall_the_direct_x_run_hits(self) -> None:
        # Wall sits in the starting row, so walking right first is impossible,
        # but dropping to the goal's row first walks under it.
        wall = Rect(48, 0, 16, 32)
        path = plan(start=BODY, goal=PointGoal(Point(120, 64)), obstacles=[wall])

        self.assertTrue(path.reached)
        self.assertEqual(
            [step.direction for step in path.steps],
            [Direction.DOWN, Direction.RIGHT],
        )
        for rect in path.positions():
            self.assertFalse(rect.overlaps(wall))

    def test_diagonals_can_be_turned_off(self) -> None:
        wall = Rect(0, 16, 16, 16)
        path = plan(
            start=BODY,
            goal=PointGoal(Point(64, 64)),
            obstacles=[wall],
            allow_diagonals=False,
        )

        self.assertTrue(path.reached)
        for step in path.steps:
            self.assertFalse(step.direction.is_diagonal)

    def test_a_star_finishes_with_y_then_x_once_the_corridor_opens(self) -> None:
        # Wall blocks the starting column, so A* has to step aside first.
        # The first expanded node that can see the goal by Y then X finishes
        # that way -- no diagonal dash for the remainder.
        wall = Rect(0, 16, 16, 16)
        path = plan(start=BODY, goal=PointGoal(Point(64, 64)), obstacles=[wall])

        self.assertTrue(path.reached)
        self.assertIs(path.steps[0].direction, Direction.RIGHT)
        self.assertFalse(any(step.direction.is_diagonal for step in path.steps))
        self.assertEqual(
            [step.direction for step in path.steps[-2:]],
            [Direction.DOWN, Direction.RIGHT],
        )
        self.assertTrue(PointGoal(Point(64, 64)).is_reached(path.final))


class FinishAimTests(unittest.TestCase):
    """The Y-then-X finish aims at every free arrival.

    It used to aim at two cells of a goal window too big to try in full (over
    64 cells): the one nearest the node and the middle. Both are often
    exactly the cells that are out, and with a node budget as small as the
    AI's (10) the search then never arrived at all. Each scene below has a
    window over 64 cells where both of those cells are out, and is reached
    from the first node.
    """

    def test_a_strip_whose_nearest_rows_sit_in_a_hole_goes_round_it(self) -> None:
        # WalkToAdvanceStage's goal: a strip across the band, here inside the
        # hole's X. The start's own rows and the middle ones are in the hole.
        hole = Rect(80, 32, 64, 48)
        path = plan(
            start=Rect(40, 48, 16, 16),
            goal=RegionGoal.of(Rect(100, 0, 1, 112), axis="x"),
            obstacles=[hole],
            step=4,
            max_nodes=1,
        )

        self.assertTrue(path.reached)
        self.assertEqual(path.nodes_expanded, 1)
        self.assertEqual(
            [step.direction for step in path.steps], [Direction.UP, Direction.RIGHT]
        )
        for rect in path.positions():
            self.assertFalse(rect.overlaps(hole))

    def test_a_band_only_further_rows_cover_is_closed_lane_first(self) -> None:
        # A strike goal: two bands with a gap between them, and a lane margin
        # (enough_contact) only a body covering the whole band meets. Open
        # space, yet the nearest window cell is short of the band and the
        # middle one sits in the gap.
        path = plan(
            start=Rect(0, 60, 16, 16),
            goal=RegionGoal(
                (Rect(200, 20, 20, 8), Rect(256, 20, 20, 8)), axis="y"
            ),
            enough_contact=8,
            step=4,
            max_nodes=1,
        )

        self.assertTrue(path.reached)
        self.assertEqual(path.nodes_expanded, 1)
        self.assertEqual(
            [step.direction for step in path.steps], [Direction.UP, Direction.RIGHT]
        )

    def test_the_finish_is_the_cheapest_over_every_free_arrival(self) -> None:
        # Checked against the brute force it replaces: every free arrival
        # tried from the node, ranked by the finish's own key.
        real = search_module._best_yx_from
        checked = 0

        def compare(lattice, origin, arrival_at, window, **kwargs):
            nonlocal checked
            got = real(lattice, origin, arrival_at, window, **kwargs)
            arrivals = kwargs.get("arrivals")
            if window is None or not arrivals:
                return got
            flush = kwargs["require_flush"]
            best = None
            for node, misalignment in arrivals.items():
                if node == origin or (flush and misalignment > 0):
                    continue
                if not search_module._yx_clear(lattice, origin, node):
                    continue
                di, dj = abs(node[0] - origin[0]), abs(node[1] - origin[1])
                key = (di + dj, misalignment, dj, di, node[1], node[0])
                if best is None or key < best[0]:
                    best = (key, node, misalignment)
            self.assertEqual(got, None if best is None else best[1:], (origin, window))
            checked += 1
            return got

        rng = random.Random(0xF1415)
        with mock.patch.object(search_module, "_best_yx_from", compare):
            for _ in range(300):
                start, goal, obstacles, world, step = _random_scene(rng)
                for options in ({}, {"enough_contact": 4}, {"maximize_contact": True}):
                    find_path(
                        start=start,
                        goal=goal,
                        world=world,
                        obstacles=obstacles,
                        step=step,
                        max_nodes=100,
                        **options,
                    )

        self.assertGreater(checked, 1000)


class AroundFinishTests(unittest.TestCase):
    """The X-then-Y finish, asked only once a search has ended without
    arriving: walk along the own lane past a wall, then step onto the goal.

    Round 4's bridge (both Blaze and Axel, live): a prop beside the first
    hole, its near pocket in the hole and its wall over the lanes between,
    so every Y-then-X finish a 10-node budget reaches walks into the wall or
    the hole. The actor rocked in front of it until the round clock took a
    life.
    """

    def scene(self, **kwargs):
        hole = Rect(60, 64, 64, 48)
        wall = Rect(124, 60, 48, 40)
        goal = RegionGoal((Rect(100, 72, 16, 16), Rect(176, 72, 16, 16)), axis="y")
        path = plan(
            start=Rect(40, 36, 16, 16),
            goal=goal,
            obstacles=[hole, wall],
            step=4,
            max_nodes=10,
            **kwargs,
        )
        return path, (hole, wall)

    def test_a_far_pocket_past_a_wall_is_walked_round_to(self) -> None:
        path, obstacles = self.scene()

        self.assertTrue(path.reached)
        self.assertEqual(path.steps[-1].direction, Direction.DOWN)
        self.assertIn(Direction.RIGHT, [step.direction for step in path.steps])
        for rect in path.positions():
            for obstacle in obstacles:
                self.assertFalse(rect.overlaps(obstacle))

    def test_also_under_maximize_contact(self) -> None:
        path, _ = self.scene(maximize_contact=True)

        self.assertTrue(path.reached)

    def test_a_route_y_then_x_already_finds_is_left_as_it_was(self) -> None:
        # Open floor: the lane first, then the walk in, as before.
        path = plan(
            start=Rect(40, 36, 16, 16),
            goal=RegionGoal.of(Rect(200, 72, 16, 16), axis="y"),
            step=4,
            max_nodes=10,
        )

        self.assertTrue(path.reached)
        self.assertEqual(
            [step.direction for step in path.steps], [Direction.DOWN, Direction.RIGHT]
        )


class ObstacleTests(unittest.TestCase):
    def test_the_body_walks_around_an_obstacle_instead_of_through_it(self) -> None:
        wall = Rect(48, 0, 16, 64)
        path = plan(start=BODY, goal=PointGoal(Point(120, 8)), obstacles=[wall])

        self.assertTrue(path.reached)
        for rect in path.positions():
            self.assertFalse(rect.overlaps(wall))
            self.assertTrue(WORLD.contains(rect))

    def test_a_step_cannot_tunnel_through_a_thin_obstacle(self) -> None:
        # Thinner than one step: only a swept test can see it.
        fence = Rect(40, 0, 2, 112)
        path = plan(
            start=BODY, goal=PointGoal(Point(120, 8)), obstacles=[fence], step=32
        )

        self.assertFalse(path.reached)

    def test_a_diagonal_does_not_cut_a_corner(self) -> None:
        obstacles = [Rect(16, 0, 16, 16), Rect(32, 16, 16, 16)]
        path = plan(
            start=BODY,
            goal=PointGoal(Point(40, 40)),
            obstacles=obstacles,
            step=16,
        )

        for previous, current in zip(path.positions(), path.positions()[1:]):
            swept = previous.union(current)
            self.assertFalse(any(swept.overlaps(obstacle) for obstacle in obstacles))

    def test_the_body_fits_the_gap_it_is_routed_through(self) -> None:
        # A 16px corridor for a 16px body: passable, and the only way across.
        obstacles = [Rect(64, 0, 16, 48), Rect(64, 64, 16, 48)]
        path = plan(
            start=BODY.moved_to(0, 48),
            goal=PointGoal(Point(160, 56)),
            obstacles=obstacles,
        )

        self.assertTrue(path.reached)
        for rect in path.positions():
            self.assertFalse(any(rect.overlaps(obstacle) for obstacle in obstacles))

    def test_a_body_too_wide_for_the_gap_is_not_routed_through_it(self) -> None:
        obstacles = [Rect(64, 0, 16, 48), Rect(64, 60, 16, 52)]
        path = plan(
            start=Rect(0, 44, 16, 16),
            goal=PointGoal(Point(160, 56)),
            obstacles=obstacles,
        )

        self.assertFalse(path.reached)

    def test_a_walled_off_goal_returns_the_closest_best_effort(self) -> None:
        wall = Rect(64, 0, 16, 112)
        path = plan(start=BODY, goal=PointGoal(Point(200, 56)), obstacles=[wall])

        self.assertFalse(path.reached)
        self.assertTrue(path.steps)  # still worth walking up to the wall
        self.assertLessEqual(path.final.right, wall.left)
        self.assertGreater(path.final.right, BODY.right)

    def test_a_body_starting_inside_an_obstacle_can_still_escape(self) -> None:
        # It cannot get out in one step, so the crate it stands in is dropped
        # from the collision set -- but every *other* obstacle still applies.
        crate = Rect(0, 0, 32, 32)
        wall = Rect(48, 0, 16, 64)
        path = plan(
            start=Rect(8, 8, 16, 16),
            goal=PointGoal(Point(80, 8)),
            obstacles=[crate, wall],
        )

        self.assertTrue(path.reached)
        self.assertFalse(path.final.overlaps(crate))
        for rect in path.positions():
            self.assertFalse(rect.overlaps(wall))

    def test_a_one_pixel_graze_does_not_drop_the_wall(self) -> None:
        # A body whose edge merely clips a 1px-tall floor is not "already
        # inside" it. Dropping that wall is how a first-level phone booth
        # vanished from the search while the actor stood legally in front.
        from sor_autoplay.ai.pathfind.grid import Lattice

        wall = Rect(80, 36.5, 40, 1.0)
        start = Rect(92, 36, 16, 16)  # overlaps the 1px, centre at y=44
        lattice = Lattice(start=start, world=WORLD, obstacles=[wall], step=4)

        self.assertTrue(wall.overlaps(start))
        self.assertEqual(lattice.ignored, ())
        self.assertIn(wall, lattice.obstacles)


class WorldBoundsTests(unittest.TestCase):
    def test_a_start_hanging_out_of_the_world_can_walk_back_in(self) -> None:
        path = plan(start=Rect(-8, 0, 16, 16), goal=PointGoal(Point(40, 8)))

        self.assertTrue(path.reached)
        for rect in path.positions()[1:]:
            self.assertTrue(WORLD.contains(rect))

    def test_the_body_never_leaves_the_world(self) -> None:
        # The lattice is anchored at the start, so x stays 300 - 8k and never
        # hits 0 exactly; tolerance is how a caller asks for "near enough".
        path = plan(
            start=Rect(300, 90, 16, 16), goal=PointGoal(Point(0, 0), tolerance=8)
        )

        self.assertTrue(path.reached)
        for rect in path.positions():
            self.assertTrue(WORLD.contains(rect))

    def test_a_goal_outside_the_world_fails_without_raising(self) -> None:
        path = plan(start=BODY, goal=PointGoal(Point(1000, 1000)))

        self.assertFalse(path.reached)
        self.assertTrue(WORLD.contains(path.final))


class SegmentGoalSearchTests(unittest.TestCase):
    def test_a_segment_goal_stops_on_the_named_edge(self) -> None:
        threshold = Segment(Point(160, 0), Point(160, 112))
        path = plan(start=BODY, goal=SegmentGoal.of(threshold, {Edge.RIGHT}))

        self.assertTrue(path.reached)
        self.assertAlmostEqual(path.final.right, 160)

    def test_the_opposite_edge_goal_walks_past_the_line(self) -> None:
        threshold = Segment(Point(160, 0), Point(160, 112))
        path = plan(start=BODY, goal=SegmentGoal.of(threshold, {Edge.LEFT}))

        self.assertTrue(path.reached)
        self.assertAlmostEqual(path.final.left, 160)

    def test_a_segment_goal_only_counts_where_the_segment_actually_is(self) -> None:
        # The line spans the bottom half of the world only; a body kept in the
        # top half by the wall must come down to meet it.
        threshold = Segment(Point(200, 80), Point(200, 112))
        path = plan(start=BODY, goal=SegmentGoal.of(threshold, {Edge.RIGHT}))

        self.assertTrue(path.reached)
        self.assertAlmostEqual(path.final.right, 200)
        self.assertGreaterEqual(path.final.bottom, 80)

    def test_a_diagonal_segment_goal_is_reachable(self) -> None:
        goal = SegmentGoal.of(Segment(Point(120, 0), Point(200, 112)), {Edge.RIGHT})
        path = plan(start=BODY, goal=goal)

        self.assertTrue(path.reached)
        self.assertTrue(goal.is_reached(path.final))


class RectGoalSearchTests(unittest.TestCase):
    def test_a_rect_goal_arrives_stacked_not_merely_near(self) -> None:
        # The crate is solid as well as the destination: the body must stop
        # flush above or below it, never beside it.
        crate = Rect(160, 48, 16, 16)
        goal = RectGoal.horizontal(crate)
        path = plan(start=BODY, goal=goal, obstacles=[crate])

        self.assertTrue(path.reached)
        self.assertTrue(goal.is_reached(path.final))
        self.assertFalse(path.final.overlaps(crate))
        self.assertTrue(close(path.final.bottom, 48) or close(path.final.top, 64))

    def test_a_rect_goal_from_one_side_only_walks_around_the_target(self) -> None:
        crate = Rect(160, 48, 16, 16)
        # Only "my top edge on its bottom edge": the body must end up *below*
        # the crate even though above is much closer to where it starts.
        goal = RectGoal(crate, frozenset({(Edge.TOP, Edge.BOTTOM)}))
        path = plan(start=BODY, goal=goal, obstacles=[crate])

        self.assertTrue(path.reached)
        self.assertAlmostEqual(path.final.top, 64)
        for rect in path.positions():
            self.assertFalse(rect.overlaps(crate))

    def test_a_vertical_rect_goal_arrives_side_by_side(self) -> None:
        crate = Rect(160, 48, 16, 16)
        goal = RectGoal.vertical(crate)
        path = plan(start=BODY, goal=goal, obstacles=[crate])

        self.assertTrue(path.reached)
        self.assertTrue(close(path.final.right, 160) or close(path.final.left, 176))

    def test_a_rect_goal_the_body_cannot_line_up_with_fails_cleanly(self) -> None:
        # The crate sits flush against the top of the world, so nothing can ever
        # place a body's bottom edge on the crate's top edge or its top edge on
        # the crate's bottom edge without leaving the world... except from below,
        # which this pairing forbids.
        crate = Rect(160, 0, 16, 8)
        goal = RectGoal(crate, frozenset({(Edge.BOTTOM, Edge.TOP)}))
        path = plan(start=BODY.moved_to(0, 40), goal=goal, obstacles=[crate])

        self.assertFalse(path.reached)
        self.assertTrue(WORLD.contains(path.final))


class ContactTests(unittest.TestCase):
    def test_by_default_a_corner_touch_is_a_good_enough_arrival(self) -> None:
        # The cheapest way to put a left edge on the crate's right edge is to
        # clip its corner, and that is what the search settles for unless it is
        # told otherwise.
        crate = Rect(160, 48, 16, 16)
        goal = RectGoal(crate, frozenset({(Edge.LEFT, Edge.RIGHT)}))
        path = plan(start=BODY, goal=goal, obstacles=[crate])

        self.assertTrue(path.reached)
        self.assertAlmostEqual(path.final.left, 176)
        self.assertGreater(path.misalignment, 0)
        self.assertLess(path.contact, 16)

    def test_maximize_contact_walks_the_extra_bit_to_line_up(self) -> None:
        crate = Rect(160, 48, 16, 16)
        goal = RectGoal(crate, frozenset({(Edge.LEFT, Edge.RIGHT)}))
        loose = plan(start=BODY, goal=goal, obstacles=[crate])
        flush = plan(start=BODY, goal=goal, obstacles=[crate], maximize_contact=True)

        self.assertTrue(flush.reached)
        self.assertEqual(flush.misalignment, 0)
        self.assertAlmostEqual(flush.contact, 16)  # the whole shared edge
        self.assertAlmostEqual(flush.final.left, 176)
        self.assertAlmostEqual(flush.final.top, crate.top)
        # The bare arrival is the Y-then-X corner clip -- lining up square
        # means walking around the crate, which those two legs cannot do.
        self.assertTrue(loose.reached)
        self.assertGreater(loose.misalignment, 0)
        self.assertEqual(
            [step.direction for step in loose.steps],
            [Direction.DOWN, Direction.RIGHT],
        )

    def test_maximize_contact_still_uses_y_then_x_when_that_corridor_is_flush(
        self,
    ) -> None:
        # Stacked on the crate is a Y-then-X arrival and a flush one, so
        # maximize_contact must not fall through to a diagonal A* route.
        crate = Rect(160, 48, 16, 16)
        path = plan(
            start=BODY,
            goal=RectGoal.horizontal(crate),
            obstacles=[crate],
            maximize_contact=True,
        )

        self.assertTrue(path.reached)
        self.assertEqual(path.misalignment, 0)
        self.assertIs(path.steps[0].direction, Direction.DOWN)
        for step in path.steps:
            self.assertFalse(step.direction.is_diagonal)

    def test_maximize_contact_costs_more_expansions(self) -> None:
        crate = Rect(160, 48, 16, 16)
        goal = RectGoal.horizontal(crate)
        loose = plan(start=BODY, goal=goal, obstacles=[crate])
        flush = plan(start=BODY, goal=goal, obstacles=[crate], maximize_contact=True)

        self.assertGreaterEqual(flush.nodes_expanded, loose.nodes_expanded)

    def test_enough_contact_refuses_arrivals_below_the_bar(self) -> None:
        crate = Rect(160, 48, 16, 16)
        goal = RectGoal(crate, frozenset({(Edge.LEFT, Edge.RIGHT)}))
        path = plan(start=BODY, goal=goal, obstacles=[crate], enough_contact=16)

        self.assertTrue(path.reached)
        self.assertGreaterEqual(path.contact, 16)
        self.assertAlmostEqual(path.final.top, crate.top)

    def test_enough_contact_that_cannot_be_met_fails_cleanly(self) -> None:
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

        self.assertFalse(path.reached)

    def test_enough_contact_ignores_goals_with_nothing_to_measure(self) -> None:
        # A point has no edge to share, so a contact requirement cannot make it
        # unreachable.
        path = plan(start=BODY, goal=PointGoal(Point(120, 40)), enough_contact=999)

        self.assertTrue(path.reached)
        self.assertEqual(path.contact, math.inf)

    def test_maximize_contact_applies_to_a_parallel_segment_goal(self) -> None:
        # A vertical line only half as tall as the world: arriving at its very
        # end touches it with 0px of the body's edge, arriving level with it
        # touches with all 16.
        threshold = Segment(Point(200, 60), Point(200, 112))
        goal = SegmentGoal.of(threshold, {Edge.RIGHT})
        loose = plan(start=BODY, goal=goal)
        flush = plan(start=BODY, goal=goal, maximize_contact=True)

        self.assertTrue(loose.reached)
        self.assertTrue(flush.reached)
        self.assertGreaterEqual(flush.contact, loose.contact)
        self.assertAlmostEqual(flush.contact, 16)
        self.assertEqual(flush.misalignment, 0)

    def test_an_oblique_segment_expresses_no_alignment_preference(self) -> None:
        goal = SegmentGoal.of(Segment(Point(120, 0), Point(200, 112)), {Edge.RIGHT})
        path = plan(start=BODY, goal=goal, maximize_contact=True, enough_contact=8)

        self.assertTrue(path.reached)
        self.assertEqual(path.misalignment, 0)
        self.assertEqual(path.contact, math.inf)

    def test_a_start_that_already_arrived_still_lines_up_when_asked(self) -> None:
        crate = Rect(48, 48, 16, 16)
        body = Rect(32, 56, 16, 16)  # left edge already on the crate's left side
        goal = RectGoal(crate, frozenset({(Edge.RIGHT, Edge.LEFT)}))

        self.assertTrue(goal.is_reached(body))
        self.assertFalse(plan(start=body, goal=goal, obstacles=[crate]).steps)

        flush = plan(start=body, goal=goal, obstacles=[crate], maximize_contact=True)
        self.assertTrue(flush.steps)
        self.assertEqual(flush.misalignment, 0)
        self.assertAlmostEqual(flush.final.top, crate.top)


class BudgetAndDeterminismTests(unittest.TestCase):
    def test_the_node_budget_bounds_the_work(self) -> None:
        # A full-height wall so no node can finish by Y-then-X, and A* is the
        # one that has to stop at the budget.
        wall = Rect(64, 0, 16, 112)
        path = plan(
            start=BODY,
            goal=PointGoal(Point(300, 100)),
            obstacles=[wall],
            max_nodes=5,
        )

        self.assertFalse(path.reached)
        self.assertLessEqual(path.nodes_expanded, 5)

    def test_the_same_world_always_plans_the_same_route(self) -> None:
        obstacles = [Rect(64, 0, 16, 80), Rect(140, 40, 16, 72)]
        first = plan(start=BODY, goal=PointGoal(Point(200, 100)), obstacles=obstacles)
        second = plan(start=BODY, goal=PointGoal(Point(200, 100)), obstacles=obstacles)

        self.assertEqual(first.steps, second.steps)

    def test_the_route_around_an_obstacle_is_not_much_longer_than_the_direct_one(
        self,
    ) -> None:
        obstacles = [Rect(64, 0, 16, 40)]
        path = plan(
            start=BODY.moved_to(0, 0),
            goal=PointGoal(Point(160, 8)),
            obstacles=obstacles,
        )

        self.assertTrue(path.reached)
        self.assertLess(path.length, 200)  # a straight run would be ~144

    def test_positions_and_walked_offsets_agree_with_the_final_rectangle(self) -> None:
        path = plan(
            start=BODY,
            goal=PointGoal(Point(150, 90)),
            obstacles=[Rect(64, 0, 16, 64)],
        )
        dx, dy = walked(path)

        self.assertEqual(path.positions()[-1], path.final)
        self.assertEqual(path.final, BODY.moved_by(dx, dy))

    def test_a_walled_off_search_stays_cheap_at_a_fine_step(self) -> None:
        # Scanning every Y-then-X cell from every expanded node froze the
        # viewer at step=1 behind a full-height wall (~60s for a segment).
        started = time.perf_counter()
        path = plan(
            start=BODY,
            goal=PointGoal(Point(280, 56)),
            obstacles=[Rect(64, 0, 16, 112)],
            step=1,
        )

        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertFalse(path.reached)

    def test_a_zero_or_negative_step_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            plan(start=BODY, goal=PointGoal(Point(10, 10)), step=0)


def _random_goal(rng: random.Random, world: Rect):
    gx = rng.randrange(0, int(world.width))
    gy = rng.randrange(0, int(world.height))
    kind = rng.randrange(6)
    if kind == 0:
        return PointGoal(Point(gx, gy))
    if kind == 1:
        return PointGoal(Point(gx, gy), tolerance=rng.choice((4, 8)))
    if kind == 2:
        return RegionGoal.of(
            Rect(gx, gy, rng.randrange(4, 24), rng.randrange(4, 24)),
            axis=rng.choice(("both", "x", "y")),
        )
    if kind == 3:
        w, h = rng.randrange(6, 16), rng.randrange(8, 24)
        gap = rng.randrange(8, 32)
        return RegionGoal.of(
            Rect(gx, gy, w, h),
            Rect(gx + w + gap, gy, w, h),
            axis=rng.choice(("both", "y")),
        )
    if kind == 4:
        length = rng.randrange(8, 48)
        end = Point(gx, gy + length) if rng.random() < 0.5 else Point(gx + length, gy)
        edges = rng.choice(
            ([Edge.LEFT], [Edge.RIGHT], [Edge.TOP], [Edge.BOTTOM], list(Edge))
        )
        return SegmentGoal.of(Segment(Point(gx, gy), end), edges)
    target = Rect(gx, gy, rng.randrange(4, 24), rng.randrange(4, 24))
    return RectGoal.horizontal(target) if rng.random() < 0.5 else RectGoal.vertical(target)


def _random_scene(rng: random.Random):
    step = rng.choice((4, 8))
    world = Rect(0, 0, rng.randrange(8, 20) * 8, rng.randrange(6, 12) * 8)
    bw, bh = rng.choice((8, 12, 16)), rng.choice((8, 12, 16))
    obstacles = []
    if rng.random() < 0.5:
        # A wall across the lane band, half the time with a hole in it.
        x = rng.randrange(8, max(9, int(world.width) - 24))
        w = rng.randrange(2, 12)
        gap = rng.choice((0, bh - 1, bh, bh + 4, rng.randrange(1, 24)))
        if gap == 0:
            obstacles.append(Rect(x, -4, w, world.height + 8))
        else:
            top = rng.randrange(0, max(1, int(world.height) - gap))
            obstacles.append(Rect(x, -4, w, top + 4))
            obstacles.append(
                Rect(
                    x + rng.randrange(-4, 5),
                    top + gap,
                    w,
                    world.height - top - gap + 4,
                )
            )
    edge_row = None
    if rng.random() < 0.3:
        # A shelf that leaves a corridor exactly one body tall along the top
        # or the bottom of the world: passable, since touching is not
        # overlapping, and the case a sliver-tolerant cover test gets wrong.
        x = rng.randrange(8, max(9, int(world.width) - 24))
        w = rng.randrange(2, 24)
        if rng.random() < 0.5:
            obstacles.append(Rect(x, bh, w, world.height - bh))
            edge_row = 0
        else:
            obstacles.append(Rect(x, 0, w, world.height - bh))
            edge_row = int(world.height) - bh
    for _ in range(rng.randrange(0, 5)):
        obstacles.append(
            Rect(
                rng.randrange(0, int(world.width)),
                rng.randrange(0, int(world.height)),
                rng.randrange(2, 30),
                rng.randrange(2, 40),
            )
        )
    sx = rng.randrange(0, int(world.width) - bw + 1)
    sy = rng.randrange(0, int(world.height) - bh + 1)
    if edge_row is not None and rng.random() < 0.7:
        sy = edge_row
    if obstacles and rng.random() < 0.25:
        # A start clipping an obstacle without being buried in it.
        grazed = rng.choice(obstacles)
        clipped = int(grazed.right) - rng.randrange(1, 3)
        if 0 <= clipped <= world.width - bw:
            sx = clipped
    return Rect(sx, sy, bw, bh), _random_goal(rng, world), obstacles, world, step


class SealedRouteTests(unittest.TestCase):
    """A vertical line with no y left for the body proves a goal unreachable.

    The check is a proof or nothing: it may miss a walled-off goal (A* still
    answers) but must never call a reachable one sealed.
    """

    def _sealed(self, start, goal, obstacles, *, world=WORLD, step=8) -> bool:
        lattice = Lattice(start=start, world=world, obstacles=obstacles, step=step)
        box = goal.bounding_box()
        return search_module._route_is_sealed(
            lattice, start, box.x, box.x + box.width, step
        )

    def test_a_sealed_verdict_is_never_a_reachable_scene(self) -> None:
        rng = random.Random(0x5EA1ED)
        sealed_scenes = []
        for _ in range(1500):
            scene = _random_scene(rng)
            start, goal, obstacles, world, step = scene
            if self._sealed(start, goal, obstacles, world=world, step=step):
                sealed_scenes.append(scene)

        # Not vacuous: plenty of the random walls really do seal the goal.
        self.assertGreater(len(sealed_scenes), 100)
        with mock.patch.object(search_module, "SEALED_MAX_NODES", 10**9):
            for start, goal, obstacles, world, step in sealed_scenes:
                path = find_path(
                    start=start,
                    goal=goal,
                    world=world,
                    obstacles=obstacles,
                    step=step,
                    max_nodes=10**6,
                )
                self.assertFalse(path.reached, (start, goal, world, obstacles, step))

    def test_a_wall_far_from_the_start_is_not_searched_at_length(self) -> None:
        wall = Rect(300, 0, 16, 112)
        path = plan(
            start=BODY,
            goal=PointGoal(Point(600, 56)),
            world=Rect(0, 0, 640, 112),
            obstacles=[wall],
            step=4,
        )

        self.assertFalse(path.reached)
        self.assertLessEqual(path.nodes_expanded, search_module.SEALED_MAX_NODES)
        self.assertTrue(path.steps)  # still walks towards the wall
        self.assertLessEqual(path.final.right, wall.left)

    def test_a_budget_within_the_sealed_cap_is_never_checked(self) -> None:
        with mock.patch.object(
            search_module, "_route_is_sealed", side_effect=AssertionError("checked")
        ):
            path = plan(
                start=BODY,
                goal=PointGoal(Point(200, 56)),
                obstacles=[Rect(64, 0, 16, 112)],
                max_nodes=search_module.SEALED_MAX_NODES,
            )

        self.assertFalse(path.reached)

    def test_a_gap_exactly_one_body_tall_passes(self) -> None:
        start = Rect(0, 48, 16, 16)
        goal = PointGoal(Point(160, 56))
        obstacles = [Rect(64, 0, 16, 48), Rect(64, 64, 16, 48)]

        self.assertFalse(self._sealed(start, goal, obstacles))
        self.assertTrue(plan(start=start, goal=goal, obstacles=obstacles).reached)

    def test_a_gap_a_pixel_short_of_the_body_is_sealed(self) -> None:
        start = Rect(0, 48, 16, 16)
        goal = PointGoal(Point(160, 56))
        obstacles = [Rect(64, 0, 16, 48), Rect(64, 63, 16, 49)]

        self.assertTrue(self._sealed(start, goal, obstacles))
        self.assertFalse(plan(start=start, goal=goal, obstacles=obstacles).reached)

    def test_a_corridor_one_body_tall_along_the_world_edge_is_not_sealed(self) -> None:
        # Touching is not overlapping: the body runs flush between the top of
        # the world and the top of the obstacles. A sliver-tolerant cover test
        # called this sealed.
        top = [Rect(64, 16, 16, 40), Rect(64, 56, 16, 56)]
        goal = PointGoal(Point(200, 8))
        self.assertFalse(self._sealed(BODY, goal, top))
        self.assertTrue(plan(start=BODY, goal=goal, obstacles=top).reached)

        bottom = [Rect(64, 0, 16, 96)]
        start = Rect(0, 96, 16, 16)
        goal = PointGoal(Point(200, 104))
        self.assertFalse(self._sealed(start, goal, bottom))
        self.assertTrue(plan(start=start, goal=goal, obstacles=bottom).reached)

    def test_a_start_clipping_a_wall_may_step_out_through_it(self) -> None:
        # Not buried (its centre is clear of the wall) but not free either:
        # the first move is judged by where it lands alone, so it steps over
        # the wall's last 2 px and the goal is reachable.
        wall = Rect(20, -10, 4, 132)
        start = Rect(22, 40, 16, 16)
        goal = PointGoal(Point(200, 48))

        self.assertFalse(self._sealed(start, goal, [wall], step=4))
        self.assertTrue(plan(start=start, goal=goal, obstacles=[wall], step=4).reached)

    def test_a_one_row_corridor_is_sealed_only_by_what_stands_in_it(self) -> None:
        lane = Rect(0, 40, 320, 16)  # a world exactly one body tall
        start = Rect(0, 40, 16, 16)
        goal = PointGoal(Point(200, 48))
        pit = Rect(100, 30, 40, 40)

        self.assertFalse(self._sealed(start, goal, [], world=lane))
        self.assertTrue(plan(start=start, goal=goal, world=lane).reached)
        self.assertTrue(self._sealed(start, goal, [pit], world=lane))
        self.assertFalse(
            plan(start=start, goal=goal, world=lane, obstacles=[pit]).reached
        )

    def test_a_goal_to_the_left_is_sealed_by_a_wall_between(self) -> None:
        start = Rect(200, 40, 16, 16)
        goal = PointGoal(Point(20, 48))
        with_hole = [Rect(100, 0, 16, 40), Rect(100, 64, 16, 48)]

        self.assertTrue(self._sealed(start, goal, [Rect(100, 0, 16, 112)]))
        self.assertFalse(self._sealed(start, goal, with_hole))
        self.assertTrue(plan(start=start, goal=goal, obstacles=with_hole).reached)

    def test_a_start_inside_the_goals_hull_has_nothing_to_cross(self) -> None:
        # The start sits in the hole of an annulus whose left band is behind
        # a wall; the right band is open, so the goal is reachable.
        goal = RegionGoal.of(Rect(0, 40, 20, 24), Rect(100, 40, 20, 24), axis="y")
        start = Rect(50, 40, 16, 16)
        wall = Rect(30, 0, 8, 112)

        self.assertFalse(self._sealed(start, goal, [wall]))
        self.assertTrue(plan(start=start, goal=goal, obstacles=[wall]).reached)

    def test_two_obstacles_can_seal_a_line_neither_seals_alone(self) -> None:
        upper = Rect(64, 0, 16, 60)
        lower = Rect(72, 50, 16, 62)
        goal = PointGoal(Point(200, 56))

        self.assertFalse(self._sealed(BODY, goal, [upper]))
        self.assertFalse(self._sealed(BODY, goal, [lower]))
        self.assertTrue(self._sealed(BODY, goal, [upper, lower]))
        self.assertFalse(plan(start=BODY, goal=goal, obstacles=[upper, lower]).reached)

    def test_a_staircase_wall_is_a_known_miss(self) -> None:
        # Each piece leaves a hole at every x it covers, yet the holes step
        # from the bottom of the street to the top, so nothing gets through.
        # No single vertical line is sealed, so the check cannot see it and
        # A* has to prove it, as it always did.
        world = Rect(0, 0, 240, 126)
        pieces = [Rect(16, 0, 44, 50), Rect(56, 46, 44, 34), Rect(96, 76, 44, 50)]
        start = Rect(0, 90, 16, 16)
        goal = PointGoal(Point(200, 20))

        self.assertFalse(self._sealed(start, goal, pieces, world=world))
        self.assertFalse(
            plan(start=start, goal=goal, world=world, obstacles=pieces).reached
        )
