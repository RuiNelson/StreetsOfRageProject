"""``navigation`` -- the adapter between the AI's tokens and ``pathfind``."""

from __future__ import annotations

import unittest
from dataclasses import replace

from sor_autoplay.ai import navigation as nav
from sor_autoplay.ai.pathfind import PointGoal, Rect, RegionGoal
from sor_autoplay.ai.tokens import (
    AttackRange,
    Breakable,
    CameraRange,
    Enemy,
    Myself,
    Pit,
    Stage,
)
from sor_autoplay.ai.reach import PIT_AVOID_MARGIN
from sor_autoplay.phases import CombatPhase
from sor_autoplay.hitboxes import Hitbox
from sor_autoplay.world_map import LANE_Y_MIN


def _myself(*, world_x=0, world_y=0, hitbox=None) -> Myself:
    return Myself(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=world_x,
        world_y=world_y,
        health=100,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        action_state=0,
        is_airborne=False,
        facing_left=False,
        combat_phase=CombatPhase.NORMAL,
        hitbox=hitbox,
    )


def _enemy(*, world_x=100, world_y=50, ranges=(), facing_left=True) -> Enemy:
    return Enemy(
        slot="obj01",
        type_id=0x20,
        world_x=world_x,
        world_y=world_y,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=facing_left,
        attack_ranges=tuple(ranges),
    )


class BodyRectTests(unittest.TestCase):
    def test_uses_the_real_cached_box_when_there_is_one(self) -> None:
        actor = _myself(hitbox=Hitbox(x0=10, x1=30, y0=40, y1=52, z0=0, z1=40))

        self.assertEqual(nav.body_rect(actor), Rect(10, 40, 20, 12))

    def test_falls_back_to_a_nominal_body_centred_on_the_actor(self) -> None:
        # "Unknown" is not "no body": routing a point through gaps a real
        # character cannot fit is worse than routing an approximate box.
        body = nav.body_rect(_myself(world_x=100, world_y=50))

        self.assertEqual(body.width, nav.NOMINAL_BODY_W)
        self.assertEqual(body.center.x, 100)
        self.assertEqual(body.center.y, 50)

    def test_a_degenerate_box_counts_as_no_box(self) -> None:
        actor = _myself(hitbox=Hitbox(x0=0, x1=0, y0=0, y1=0, z0=0, z1=0))

        self.assertEqual(nav.body_rect(actor).width, nav.NOMINAL_BODY_W)


class WorldRectTests(unittest.TestCase):
    def test_is_the_lane_band_and_the_camera(self) -> None:
        world = nav.world_rect(
            {Stage(level_index=0, direction="right"), CameraRange(left=100, right=420, top=0, bottom=112)}
        )

        self.assertEqual(world.top, LANE_Y_MIN)
        self.assertEqual(world.left, 100 - nav.WORLD_MARGIN_X)
        self.assertEqual(world.right, 420 + nav.WORLD_MARGIN_X)

    def test_without_a_camera_only_the_lane_band_is_bounded(self) -> None:
        world = nav.world_rect({Stage(level_index=0, direction="right")})

        self.assertEqual(world.top, LANE_Y_MIN)
        self.assertLess(world.width, 1e7)
        self.assertGreater(world.width, 1000)

    def test_the_margin_always_contains_advance_stages_own_lookahead(self) -> None:
        # Live-diagnosed: an actor standing at the camera's trailing edge got
        # a WalkToAdvanceStage lookahead point 40px ahead of its own position
        # -- which, with too small a margin, landed outside `world_rect`
        # entirely. No lattice position could then ever satisfy the goal,
        # `plan_route` reported `reached=False` forever, and the actor
        # stalled dead on the camera's own edge: not poorly routed, unable to
        # progress at all, since advancing is exactly what would have
        # scrolled the camera and made the goal reachable again.
        camera = CameraRange(left=3520, right=3808, top=0, bottom=112)
        context = {Stage(level_index=0, direction="right"), camera}
        world = nav.world_rect(context)

        actor_x = camera.right  # the exact live-reproduced stall position
        lookahead_x = actor_x + 40  # WalkToAdvanceStage's fixed lookahead

        self.assertLessEqual(lookahead_x, world.right)


class ObstacleTests(unittest.TestCase):
    def test_a_pit_keeps_a_hair_more_clearance_than_the_predicate(self) -> None:
        # `pit_endangers` is inclusive, collision here is not: without the
        # extra pixel the route is content to stop on the exact spot the pit
        # escape will shove it off, which is a one-pixel deadlock.
        pit = Pit(world_x=40, lane_y=60, width=20, height=10)

        (rect,) = nav.solid_obstacles({pit})

        self.assertEqual(rect.left, 40 - PIT_AVOID_MARGIN - 1)
        self.assertEqual(rect.width, 20 + 2 * (PIT_AVOID_MARGIN + 1))

    def test_a_pit_is_measured_against_the_actors_origin_not_its_body(self) -> None:
        # The ROM's floor rule is about the object's position, and so is
        # every other pit check in the AI. Growing the hole by the margin
        # *and* colliding a whole body against it counts the clearance twice
        # -- measured on the sweep as an actor fleeing a hole it stood safely
        # beside. Insetting by half the body makes "the body overlaps this"
        # mean "the origin is within the margin".
        pit = Pit(world_x=40, lane_y=60, width=20, height=10)
        body = Rect(0, 0, 16, 16)

        (loose,) = nav.solid_obstacles({pit})
        (inset,) = nav.solid_obstacles({pit}, body=body)

        self.assertEqual(inset.width, loose.width - body.width)
        self.assertEqual(inset.height, loose.height - body.height)

    def test_a_breakable_uses_the_roms_push_back_box_not_its_sprite(self) -> None:
        # The two are different rectangles, and it is the push-back one that
        # stops a walking actor: a round-5 prop's sprite sits in front of its
        # origin while its wall runs 20px behind it. Routing off the sprite
        # planned through solid ground -- the stage-5 stall.
        prop = Breakable(
            slot="obj09",
            world_x=100,
            world_y=50,
            type_id=0x1F,
            hitbox=Hitbox(x0=80, x1=120, y0=40, y1=60, z0=0, z1=40),
        )

        (rect,) = nav.solid_obstacles({prop})

        self.assertEqual(rect, Rect(70, 30, 60, 24))

    def test_a_breakable_is_measured_against_the_actors_origin(self) -> None:
        # sub_00003BAE tests the mover's own position against the box, never
        # its body, so the obstacle a body-collision search needs is the box
        # shrunk by the body -- the same restatement a pit already gets.
        prop = Breakable(slot="obj09", world_x=100, world_y=50, type_id=0x1F)
        body = Rect(0, 0, 16, 16)

        (loose,) = nav.solid_obstacles({prop})
        (inset,) = nav.solid_obstacles({prop}, body=body)

        self.assertEqual(inset.width, loose.width - body.width)
        self.assertEqual(inset.height, loose.height - body.height)

    def test_the_conversion_follows_an_off_centre_body(self) -> None:
        # A cached player box is not centred on the actor's own position --
        # Axel's spans -7..+3 of it facing left. Assuming it is centred left
        # a 2px sliver of wall the route was happy to step into, and the ROM
        # was not: recorded live, the actor held DOWN against a round-5 prop
        # for 42 seconds from 2px inside its box.
        prop = Breakable(slot="obj09", world_x=4512, world_y=72, type_id=0x1F)
        body = Rect(4477, 42, 10, 16)  # origin (4484, 50), facing left

        (rect,) = nav.solid_obstacles({prop}, body=body, origin=(4484.0, 50.0))

        # The wall is x 4482..4542; standing at 4484 is inside it, so the
        # body drawn around 4484 must overlap what the search collides with.
        self.assertTrue(rect.overlaps(Rect(4477, 62, 10, 16)))
        self.assertFalse(rect.overlaps(Rect(4475, 62, 10, 16)))

    def test_a_wall_shallower_than_the_body_still_blocks(self) -> None:
        # A phone booth's band is 14px against a 16px actor. Insetting it to
        # nothing would let the lattice drop it and treat the booth as air.
        prop = Breakable(slot="obj09", world_x=100, world_y=50, type_id=0x11)

        (inset,) = nav.solid_obstacles({prop}, body=Rect(0, 0, 16, 16))

        self.assertGreater(inset.width, 0)
        self.assertGreater(inset.height, 0)

    def test_an_ignored_breakable_is_not_an_obstacle(self) -> None:
        prop = Breakable(slot="obj09", world_x=100, world_y=50, type_id=0x40)

        self.assertEqual(
            nav.solid_obstacles({prop}, ignore_slots=frozenset({"obj09"})),
            [],
        )

    def test_an_idle_enemys_reach_is_not_a_wall(self) -> None:
        # Every enemy on screen *could* swing. Routing around that potential
        # is how an approach turns into a detour: measured on the sweep, one
        # idle enemy past a pit cost a whole run's attacks.
        swing = AttackRange(
            shape_id=0x22,
            animation=0,
            forward_min=8,
            forward_max=40,
            lane_min=-8,
            lane_max=8,
            height_min=0,
            height_max=32,
        )
        idle = _enemy(world_x=200, world_y=50, ranges=(swing,))

        self.assertEqual(len(nav.enemy_rects(idle)), 1)

    def test_a_committed_enemy_contributes_its_body_and_every_reach(self) -> None:
        swing = AttackRange(
            shape_id=0x22,
            animation=0,
            forward_min=8,
            forward_max=40,
            lane_min=-8,
            lane_max=8,
            height_min=0,
            height_max=32,
        )
        enemy = replace(
            _enemy(world_x=200, world_y=50, ranges=(swing,), facing_left=True),
            combat_phase=CombatPhase.ATTACKING,
        )

        rects = nav.enemy_rects(enemy)

        self.assertEqual(len(rects), 2)
        # Left-facing: the band is on its left, mirrored by `projected`.
        self.assertEqual(rects[1], Rect(160, 42, 32, 16))

    def test_dangers_skip_the_enemy_being_walked_to(self) -> None:
        context = {_enemy(world_x=200, world_y=50), Stage(level_index=0, direction="right")}

        self.assertTrue(nav.danger_obstacles(context))
        self.assertEqual(
            nav.danger_obstacles(context, ignore_slots=frozenset({"obj01"})), []
        )


class AdvanceGoalTests(unittest.TestCase):
    def test_a_pit_on_the_current_lane_is_walked_around_not_into(self) -> None:
        # WalkToAdvanceStage used to aim a PointGoal 40px ahead on the
        # actor's own Y. Once that point sat in the pit every covering
        # cell was inside the hole, the search reported best-effort, and
        # the first vector was RIGHT into the pit -- with room above it.
        pit = Pit(world_x=400, lane_y=40, width=96, height=40)
        actor = _myself(world_x=360, world_y=60)
        camera = CameraRange(left=232, right=488, top=0, bottom=112)
        context = {
            actor,
            pit,
            camera,
            Stage(level_index=3, direction="right"),
        }
        body, origin = nav.actor_footprint(actor)
        solids = nav.solid_obstacles(context, body=body, origin=origin)
        goal = nav.advance_goal(context, actor.world_x + 40)
        path = nav.plan_route(context, actor, goal, solids=solids)

        self.assertTrue(path.reached)
        self.assertTrue(path.steps)
        self.assertIsNot(path.steps[0].direction, nav.Direction.RIGHT)
        for rect in path.positions():
            self.assertFalse(any(rect.overlaps(solid) for solid in solids))


class StrikeGoalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.body = Rect(0, 0, 16, 16)

    def _at(self, cx: float, cy: float) -> Rect:
        return Rect(cx - 8, cy - 8, 16, 16)

    def test_arrival_means_the_reach_predicate_would_agree(self) -> None:
        goal = nav.strike_goal(self.body, 8, 8, 100, 50, stop_dx=40, lane_slack=12)

        self.assertTrue(goal.is_reached(self._at(64, 50)))  # dx=36
        self.assertTrue(goal.is_reached(self._at(60, 50)))  # dx=40, flush
        self.assertFalse(goal.is_reached(self._at(56, 50)))  # dx=44, short
        self.assertFalse(goal.is_reached(self._at(64, 66)))  # lane too far off

    def test_arrival_is_measured_from_the_origin_not_the_body_centre(self) -> None:
        # A real cached box is not centred on the actor's position: recorded
        # live, Axel's spans 2153..2163 with his origin at 2156, i.e. -3..+7.
        # Every reach predicate compares origins, so a region that quietly
        # measured the body's centre instead stopped the actor 2px outside
        # the range it then refused to punch from -- 1600 of 2500 ticks of a
        # live run spent standing against one crate, pressing nothing.
        body = Rect(2153, 28, 10, 16)
        origin_x, origin_y = 2156, 36
        goal = nav.strike_goal(
            body, origin_x, origin_y, 2192, 32, stop_dx=36, lane_slack=16, inner_dx=10
        )

        def at(origin_x: float) -> Rect:
            return Rect(origin_x - 3, 28, 10, 16)

        self.assertTrue(goal.is_reached(at(2192 - 36)))  # exactly in range
        self.assertTrue(goal.is_reached(at(2192 - 30)))
        self.assertFalse(goal.is_reached(at(2192 - 38)))  # the stall's spot

    def test_contact_is_the_lane_margin_left_over(self) -> None:
        goal = nav.strike_goal(self.body, 8, 8, 100, 50, stop_dx=40, lane_slack=12)

        square = goal.contact(self._at(70, 50))
        drifted = goal.contact(self._at(70, 56))

        self.assertGreater(square, drifted)
        self.assertEqual(goal.contact(self._at(70, 62)), 0)  # exactly lane_slack

    def test_a_dead_zone_makes_the_ground_two_bands_with_a_hole(self) -> None:
        goal = nav.strike_goal(
            self.body, 8, 8, 100, 50, stop_dx=40, lane_slack=12, inner_dx=10
        )

        self.assertIsInstance(goal, RegionGoal)
        self.assertEqual(len(goal.regions), 2)
        self.assertTrue(goal.is_reached(self._at(70, 50)))  # dx=30, in range
        self.assertFalse(goal.is_reached(self._at(100, 50)))  # standing on it
        self.assertTrue(goal.is_reached(self._at(130, 50)))  # the far band

    def test_a_side_restricts_it_to_one_band(self) -> None:
        goal = nav.strike_goal(
            self.body, 8, 8, 100, 50, stop_dx=40, lane_slack=12, inner_dx=10, side="left"
        )

        self.assertEqual(len(goal.regions), 1)
        self.assertTrue(goal.is_reached(self._at(70, 50)))
        self.assertFalse(goal.is_reached(self._at(130, 50)))

    def test_a_body_bigger_than_the_band_falls_back_to_a_point(self) -> None:
        goal = nav.strike_goal(Rect(0, 0, 64, 64), 32, 32, 100, 50, stop_dx=20, lane_slack=8)

        self.assertIsInstance(goal, PointGoal)


class PlanRouteTests(unittest.TestCase):
    def _context(self, *tokens):
        return {
            Stage(level_index=0, direction="right"),
            CameraRange(left=0, right=320, top=0, bottom=112),
            *tokens,
        }

    def test_prefers_the_route_that_keeps_clear_of_danger(self) -> None:
        # A wall of reach across the lane the straight line would use.
        swing = AttackRange(
            shape_id=0x22,
            animation=0,
            forward_min=0,
            forward_max=40,
            lane_min=-40,
            lane_max=8,
            height_min=0,
            height_max=32,
        )
        enemy = replace(
            _enemy(world_x=140, world_y=60, ranges=(swing,), facing_left=True),
            combat_phase=CombatPhase.ATTACKING,
        )
        context = self._context(enemy)
        actor = _myself(world_x=20, world_y=60)
        goal = PointGoal(nav.Point(240, 60))

        careful = nav.plan_route(
            context,
            actor,
            goal,
            solids=[],
            dangers=nav.danger_obstacles(context),
        )

        self.assertTrue(careful.reached)
        band = Rect(100, 20, 40, 48)
        for rect in careful.positions():
            self.assertFalse(rect.overlaps(band))

    def test_falls_back_to_the_solids_alone_when_danger_walls_it_in(self) -> None:
        # Reach spanning the whole lane band: no danger-free route exists,
        # and refusing to move is worse than an exposed one.
        wall = AttackRange(
            shape_id=0x22,
            animation=0,
            forward_min=0,
            forward_max=40,
            lane_min=-120,
            lane_max=120,
            height_min=0,
            height_max=32,
        )
        enemy = replace(
            _enemy(world_x=140, world_y=60, ranges=(wall,), facing_left=True),
            combat_phase=CombatPhase.ATTACKING,
        )
        context = self._context(enemy)

        route = nav.plan_route(
            context,
            _myself(world_x=20, world_y=60),
            PointGoal(nav.Point(240, 60)),
            solids=[],
            dangers=nav.danger_obstacles(context),
        )

        self.assertTrue(route.reached)

    def test_a_solid_is_never_dropped_by_the_fallback(self) -> None:
        prop = Breakable(slot="obj09", world_x=140, world_y=60, type_id=0x40)
        context = self._context(prop)
        solids = nav.solid_obstacles(context)

        route = nav.plan_route(
            context,
            _myself(world_x=20, world_y=60),
            PointGoal(nav.Point(240, 60)),
            solids=solids,
            dangers=[Rect(0, 0, 320, 112)],  # everything is dangerous
        )

        for rect in route.positions():
            for solid in solids:
                self.assertFalse(rect.overlaps(solid))


class FirstVectorTests(unittest.TestCase):
    def test_only_the_first_vector_becomes_a_mask(self) -> None:
        context = {
            Stage(level_index=0, direction="right"),
            CameraRange(left=0, right=320, top=0, bottom=112),
        }
        actor = _myself(world_x=20, world_y=60)

        mask = nav.route_mask(
            context, actor, PointGoal(nav.Point(240, 60)), solids=[], dangers=[]
        )

        self.assertEqual(mask, 0x0008)  # RIGHT, and nothing else

    def test_an_arrived_route_commands_nothing(self) -> None:
        context = {Stage(level_index=0, direction="right")}
        actor = _myself(world_x=20, world_y=60)

        mask = nav.route_mask(
            context, actor, PointGoal(nav.Point(20, 60)), solids=[], dangers=[]
        )

        self.assertEqual(mask, 0)


if __name__ == "__main__":
    unittest.main()
