"""Jack's ROM model and the plan built on it (``ai/jack.py``).

The trajectories pinned here are the ones ``tools/jack_fight.py`` traced live
in round 2 (Blaze, floor at z 160), not re-derived from the code under test:
the juggle arc's heights 120, 113, 107, 103, 99, 97, 96, 96, 97 ... 128, the
axe riding 8 lanes below him at 24 - k px from his X, the thrown axe waiting
16 px behind his hand 64 px up, then flying from 32 px in front of him at 10
px an update, 48 px above his feet.
"""

import unittest

from sor_autoplay.ai import jack as J
from sor_autoplay.ai import kinematics
from sor_autoplay.ai.antonio import ActorSim
from sor_autoplay.ai.souther import HoldStep
from sor_autoplay.ai.tokens import CameraRange, Jack, Myself, Projectile
from sor_autoplay.memory_map import PLAYER_KNEE_CHAIN_BIT
from sor_autoplay.phases import CombatPhase

FLOOR = 160.0
BLAZE_BODY = (2, 12, -8, 8, -48, 0)
AXEL_BODY = (0, 13, -8, 8, -51, 0)
CAM_X = 2700
CAMERA = CameraRange(left=CAM_X + 0x20, right=CAM_X + 0x120, top=0, bottom=112)


def _jack_sim(x: float = 2744.0, y: float = 49.0, *, left: bool = False, **overrides) -> J.JackSim:
    fields = dict(
        slot="obj00", x=x, y=y, z=FLOOR, floor=FLOOR, state=J.ST_APPROACH, flags=0x01,
        facing_left=left, vx=0.0, vy=0.0, vz=0.0, aim_x=int(x), aim_y=int(y), speed=0x200,
        t50=100, t51=0, t54=0, anim=J.ANIM_MIRROR_BIT if left else J.ANIM_IDLE, frame=0,
        countdown=5, reload=5, animating=True, personality=0, juggle=True, torch=False,
        alive=True, hold_dx=0, hp=9,
    )
    fields.update(overrides)
    return J.JackSim(**fields)


def _actor(x: float, y: float, *, left: bool = False, walking: bool = False) -> ActorSim:
    return ActorSim(
        x=float(x), y=float(y), facing_left=left, walking=walking, vx=0.0, flags_31=0,
        speeds=kinematics.walk_speeds(2), walk_reach=19, body_reach=12, lane_lo=2.0,
        lane_hi=112.0, x_lo=-1e9, x_hi=1e9, holding=False, untouchable=False,
        unavailable=False, box_x=float(x), box_y=float(y),
    )


def _world(jack: J.JackSim, axes=(), body=BLAZE_BODY) -> J.World:
    return J.World([jack], list(axes), CAM_X, FLOOR, body)


def _step(axe: J.AxeSim, world: J.World, actor: ActorSim, updates: int) -> list[J.Outcome]:
    return [J.axe_update(axe, actor, world, margin=False) for _ in range(updates)]


def _juggling_world(*, left: bool, x: float = 2800.0, y: float = 60.0) -> J.World:
    """Him with both juggled axes up, 8 updates apart, as $FC1C spawns them."""

    world = _world(_jack_sim(x, y, left=left))
    far = _actor(x - 400, y)
    first = J.AxeSim.spawned(0, J.AXE_JUGGLED, 0x2B)
    world.axes.append(first)
    _step(first, world, far, J.SPAWN_GAP)
    second = J.AxeSim.spawned(0, J.AXE_JUGGLED, 0x2B)
    world.axes.append(second)
    for _ in range(3):
        J.axe_update(first, far, world)
        J.axe_update(second, far, world)
    return world


class VectorVelocityTests(unittest.TestCase):
    def test_a_straight_walk_is_the_speed_itself(self) -> None:
        # $F55E's walk to 108 px, traced at vx -2.0 with his aim straight left.
        self.assertEqual(J._vector_velocity(-108, 0, 0x200), (-2.0, 0.0))

    def test_a_diagonal_keeps_the_speed(self) -> None:
        vx, vy = J._vector_velocity(-40, 40, 0x200)
        self.assertLess(vx, 0)
        self.assertGreater(vy, 0)
        self.assertAlmostEqual((vx * vx + vy * vy) ** 0.5, 2.0, delta=0.05)


class JuggleTests(unittest.TestCase):
    def test_the_arc_is_the_traced_one(self) -> None:
        jack = _jack_sim(2744, 49)
        axe = J.AxeSim.spawned(0, J.AXE_JUGGLED, 0x2B)
        world = _world(jack, [axe])
        far = _actor(2400, 49)
        heights, xs = [], []
        for _ in range(15):
            J.axe_update(axe, far, world, margin=False)
            heights.append(J._hi(axe.z))
            xs.append(J._hi(axe.x))
        self.assertEqual(
            heights, [120, 113, 107, 103, 99, 97, 96, 96, 97, 99, 103, 107, 113, 120, 128]
        )
        self.assertEqual(xs[0], 2744 + 24)  # 24 px in front of him ...
        self.assertEqual(xs[1] - xs[0], -1)  # ... drifting back 1 px an update
        self.assertEqual(J._hi(axe.y), 49 + 8)  # 8 lanes below him
        self.assertTrue(axe.returning)
        self.assertEqual(axe.vx, J.RETURN_VX)

    def test_facing_left_it_rides_8_px_in_front_and_drifts_further(self) -> None:
        jack = _jack_sim(2744, 49, left=True)
        axe = J.AxeSim.spawned(0, J.AXE_JUGGLED, 0x2B)
        world = _world(jack, [axe])
        _step(axe, world, _actor(2400, 49), 2)
        self.assertEqual(J._hi(axe.x), 2744 - 8 - 1)

    def test_it_walks_back_to_his_hand_and_starts_again(self) -> None:
        jack = _jack_sim(2744, 49)
        axe = J.AxeSim.spawned(0, J.AXE_JUGGLED, 0x2B)
        world = _world(jack, [axe])
        far = _actor(2400, 49)
        _step(axe, world, far, 15)
        back = 0
        while not axe.entry:
            J.axe_update(axe, far, world)
            back += 1
            self.assertLess(back, 10)
        self.assertEqual(back, 5)  # 9 -> 13 -> 17 -> 21 -> 25 >= his hand's 24
        self.assertEqual(J._hi(axe.z), 128)

    def test_an_arc_ending_off_his_juggle_stance_drops_it(self) -> None:
        jack = _jack_sim(2744, 49, anim=0x10)  # held, hit, throwing: not 0/2
        axe = J.AxeSim.spawned(0, J.AXE_JUGGLED, 0x2B)
        world = _world(jack, [axe])
        _step(axe, world, _actor(2400, 49), 15)
        self.assertEqual(axe.state, J.AXE_DROPPED)

    def test_the_spawner_puts_up_two_axes_eight_updates_apart(self) -> None:
        jack = _jack_sim(2744, 49, juggle=False)
        world = _world(jack)
        J._spawn_juggle(jack, 0, world)
        world.axes.extend(world.spawned)
        world.spawned = []
        far = _actor(2400, 49)
        juggled_at = []
        for update in range(12):
            J.world_update(world, far)
            juggled = sum(1 for x in world.axes if x.state == J.AXE_JUGGLED)
            juggled_at.append(juggled)
        self.assertEqual(juggled_at[0], 1)
        self.assertEqual(juggled_at[J.SPAWN_GAP - 1], 1)
        self.assertEqual(juggled_at[J.SPAWN_GAP], 2)


class ThrowTests(unittest.TestCase):
    def test_a_throw_waits_over_his_head_then_flies_from_32_px_in_front(self) -> None:
        jack = _jack_sim(2825, 30, state=J.ST_ALIGNED_THROW, anim=J.ANIM_THROW, frame=0)
        axe = J.AxeSim.spawned(0, J.AXE_THROWN, 0x2B)
        world = _world(jack, [axe])
        far = _actor(3200, 100)
        J.axe_update(axe, far, world)
        self.assertEqual((J._hi(axe.x), J._hi(axe.y), J._hi(axe.z)), (2809, 29, 96))
        self.assertTrue(jack.flags & 0x10)  # tells his $F728 to animate
        J.axe_update(axe, far, world)
        self.assertFalse(axe.released)  # his frame 0: it waits
        jack.frame = J.THROW_RELEASE_FRAME
        xs = []
        for _ in range(3):
            J.axe_update(axe, far, world)
            xs.append(J._hi(axe.x))
        self.assertTrue(axe.released)
        self.assertEqual(J._hi(axe.z), 112)  # his feet - 48
        self.assertEqual(xs, [2867, 2877, 2887])  # traced: 2809 + 48, then 10 an update

    def test_his_ranged_throw_spawns_one_every_twelve_updates(self) -> None:
        # $F410: frames of 3 updates ($0303), four to the loop, a spawn on each
        # loop's frame 0 -- three of them, and the fourth loop ends the state.
        jack = _jack_sim(2825, 30, state=J.ST_THROW, flags=0, left=False)
        world = _world(jack)
        far = _actor(3100, 30)  # beyond the 64 px abort
        spawns, left_at, seen = [], None, 0
        for update in range(40):
            J.jack_update(0, far, world)
            thrown = sum(1 for x in world.spawned if x.state == J.AXE_INIT)
            if thrown > seen:
                spawns.append(update)
                seen = thrown
            if left_at is None and jack.state != J.ST_THROW:
                left_at = update
        self.assertEqual(spawns, [0, 12, 24])
        self.assertEqual(left_at, 36)
        # ... and the reset lands in his personality's $0C, whose entry puts a
        # fresh juggle up: $0E had cleared the latch.
        self.assertTrue(any(x.state == J.AXE_SPAWNER for x in world.spawned))

    def test_in_his_dodge_he_keeps_turning_to_the_actor(self) -> None:
        # $DBCC calls $9E4C every update: walked past, he turns -- traced live,
        # two hits of the second round-2 run came from grabs aimed at a back
        # that turned into his front.
        jack = _jack_sim(2800, 60, left=False, state=J.ST_EVADE, flags=0x03, vx=4.0)
        world = _world(jack)
        J.jack_update(0, _actor(2790, 40), world)
        self.assertTrue(jack.facing_left)
        self.assertEqual(jack.anim & J.ANIM_MIRROR_BIT, J.ANIM_MIRROR_BIT)
        J.jack_update(0, _actor(2830, 40), world)
        self.assertFalse(jack.facing_left)

    def test_closing_inside_64_px_turns_his_throw_into_the_dodge(self) -> None:
        jack = _jack_sim(2825, 30, state=J.ST_THROW, flags=0x01, anim=J.ANIM_THROW, frame=1)
        world = _world(jack)
        J.jack_update(0, _actor(2870, 30), world)
        self.assertEqual(jack.state, J.ST_EVADE)


class ContactTests(unittest.TestCase):
    def _released(self, x: float, y: float, z: float) -> J.AxeSim:
        axe = J.AxeSim.spawned(0, J.AXE_THROWN, 0x2B)
        axe.entry = False
        axe.released = True
        axe.x, axe.y, axe.z, axe.vx = x, y, z, -J.THROW_SPEED
        return axe

    def test_a_thrown_axe_meets_a_standing_blaze_at_head_height(self) -> None:
        world = _world(_jack_sim(2900, 60))
        axe = self._released(2800, 59, 112.0)  # box z 102..114 over her 112..160
        self.assertTrue(J.axe_hits(axe, _actor(2800, 60), world, margin=False))

    def test_seventeen_lanes_off_it_passes(self) -> None:
        world = _world(_jack_sim(2900, 60))
        axe = self._released(2800, 59, 112.0)
        self.assertFalse(J.axe_hits(axe, _actor(2800, 59 - 17), world, margin=False))
        self.assertFalse(J.axe_hits(axe, _actor(2800, 59 + 17), world, margin=False))

    def test_a_juggled_axe_at_its_apex_passes_over_a_standing_body(self) -> None:
        world = _world(_jack_sim(2800, 60))
        axe = J.AxeSim.spawned(0, J.AXE_JUGGLED, 0x2B)
        axe.entry = False
        axe.x, axe.y = 2790.0, 68.0
        axe.z = 96.0  # box 86..98: over a body at 112..160
        self.assertFalse(J.axe_hits(axe, _actor(2790, 60), world, margin=False))
        axe.z = 120.0  # box 110..122
        self.assertTrue(J.axe_hits(axe, _actor(2790, 60), world, margin=False))

    def test_axel_is_taller_than_blaze(self) -> None:
        axe = J.AxeSim.spawned(0, J.AXE_JUGGLED, 0x2B)
        axe.entry = False
        axe.x, axe.y, axe.z = 2790.0, 68.0, 107.0  # box 97..109
        self.assertFalse(J.axe_hits(axe, _actor(2790, 60), _world(_jack_sim()), margin=False))
        self.assertTrue(
            J.axe_hits(axe, _actor(2790, 60), _world(_jack_sim(), body=AXEL_BODY), margin=False)
        )

    def test_the_grab_is_his_body_behind_his_origin(self) -> None:
        jack = _jack_sim(2800, 60, left=True)  # body 2800..2812
        world = _world(jack)
        self.assertTrue(J.grab_contact(jack, _actor(2825, 60, left=True, walking=True), world))
        self.assertFalse(J.grab_contact(jack, _actor(2835, 60, left=True, walking=True), world))
        self.assertFalse(J.grab_contact(jack, _actor(2825, 60, left=True), world))  # standing
        self.assertTrue(J.grab_contact(jack, _actor(2825, 60 - 16, left=True, walking=True), world))
        self.assertFalse(J.grab_contact(jack, _actor(2825, 60 - 17, left=True, walking=True), world))

    def test_looking_about_he_cannot_be_grabbed(self) -> None:
        jack = _jack_sim(2800, 60, left=True, state=J.ST_LOOK)
        self.assertFalse(
            J.grab_contact(jack, _actor(2825, 60, left=True, walking=True), _world(jack))
        )


class HoldIsBurntTests(unittest.TestCase):
    def test_a_back_hold_keeps_his_flying_axes_away(self) -> None:
        # He faces left; the actor is behind him, to his right, facing left too.
        world = _juggling_world(left=True)
        self.assertFalse(J.hold_is_burnt(world, _actor(2822, 60, left=True), 0))

    def test_a_front_hold_is_burnt_while_they_fly(self) -> None:
        world = _juggling_world(left=True)
        self.assertTrue(J.hold_is_burnt(world, _actor(2770, 60, left=False), 0))

    def test_an_arc_ending_on_the_grab_walks_back_through_the_holder(self) -> None:
        # Traced live: the grab's own pass still saw his juggle stance, the
        # axe whose arc ended then walked back to his hand -- that leg never
        # looks at him again -- and hit the front holder six updates later.
        jack = _jack_sim(2800, 60, left=False)
        axe = J.AxeSim.spawned(0, J.AXE_JUGGLED, 0x2B)
        world = _world(jack, [axe])
        _step(axe, world, _actor(2400, 60), 14)  # one update from 128
        holder = _actor(2830, 60, left=True)  # in front of him, facing him
        self.assertTrue(J.hold_is_burnt(world, holder, 0))

    def test_a_grab_only_sets_his_state(self) -> None:
        # $A9D4 writes $0500; $A04A places and poses him on his next update.
        jack = _jack_sim(2800, 60, left=True)
        world = _world(jack)
        J.jack_update(0, _actor(2825, 60, left=True, walking=True), world)
        self.assertEqual(jack.state, J.ST_HELD)
        self.assertEqual(jack.anim, J.ANIM_MIRROR_BIT)
        self.assertEqual(jack.x, 2800.0)

    def test_with_nothing_up_a_front_hold_is_clean(self) -> None:
        world = _world(_jack_sim(2800, 60, left=True, juggle=False))
        self.assertFalse(J.hold_is_burnt(world, _actor(2770, 60, left=False), 0))


def _token_axes(world: J.World) -> list[Projectile]:
    return [
        Projectile(
            slot=f"obj0{i + 3}", world_x=J._hi(x.x), world_y=J._hi(x.y), vel_x=x.vx,
            vel_z=x.vz, type_id=J.AXE_TYPE, state=x.state, world_z=J._hi(x.z), fine_z=x.z,
            owner_slot="obj00", flags_31=0x01 | (0x02 if x.returning or x.released else 0),
            offset=x.off, attack_box_id=x.box,
        )
        for i, x in enumerate(world.axes)
    ]


def _myself(x: int, y: int, *, left: bool, **overrides) -> Myself:
    fields = dict(
        slot="P1", player_index=1, character_id=2, character_name="Blaze", world_x=x,
        world_y=y, health=80, health_percent=100.0, lives=3, specials=1, held_weapon_type=0,
        facing_left=left, combat_phase=CombatPhase.NORMAL,
        action_state=0x02 | (1 if left else 0), is_airborne=False, world_z=int(FLOOR),
    )
    fields.update(overrides)
    return Myself(**fields)


def _jack(x: int, y: int, *, left: bool, **overrides) -> Jack:
    fields = dict(
        slot="obj00", type_id=0x27, world_x=x, world_y=y, health=9,
        combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=left,
        has_projectile=True, state=J.ST_APPROACH, flags_31=0x01, stun_timer=100,
        world_z=int(FLOOR), animating=True, anim=J.ANIM_MIRROR_BIT if left else 0,
        approach_x=x, approach_y=y, approach_speed=0x200, screen_x=x - CAM_X + 0x80,
    )
    fields.update(overrides)
    return Jack(**fields)


class EvadeTests(unittest.TestCase):
    """``$DBCC``, his ``$07``: the lane dodge, then the walk past the target."""

    def _walking(self, x: float, *, left: bool, vx: float) -> J.JackSim:
        return _jack_sim(
            x, 23, left=left, state=J.ST_EVADE, flags=0x03 | (0x04 if left else 0), vx=vx, juggle=False,
        )

    def test_the_level_bound_stops_his_walk_and_nothing_else(self) -> None:
        # Traced live (round 5): walking right into $1510 he stood at X 5390
        # while the actor, held at the camera's 5344, stayed within 80 px.
        jack = self._walking(5390.0, left=False, vx=3.0)
        world = _world(jack)
        for _ in range(30):
            J.jack_update(0, _actor(5344, 41), world)
        self.assertEqual((jack.x, jack.state), (5390.0, J.ST_EVADE))

    def test_80_px_behind_his_walk_he_reselects(self) -> None:
        jack = self._walking(5390.0, left=False, vx=3.0)
        J.jack_update(0, _actor(5302, 41), _world(jack))
        self.assertEqual(jack.state, J.ST_RESELECT)

    def test_round_4_dodges_up_and_round_6_down_whatever_the_target(self) -> None:
        for level, down in ((1, True), (J.LEVEL_ROUND_4, False), (J.LEVEL_ROUND_6, True)):
            jack = _jack_sim(2800, 60, state=J.ST_EVADE, flags=0x00)
            world = _world(jack)
            world.level = level
            J.jack_update(0, _actor(2700, 20), world)  # the target in the top half
            self.assertEqual(jack.vy > 0, down, level)


class AimTests(unittest.TestCase):
    def _aim(self, actor: ActorSim, jack: J.JackSim) -> tuple[J.EngageMode, float, float]:
        world = _juggling_world(left=jack.facing_left, x=jack.x, y=jack.y)
        world.jacks[0] = jack
        return J.engage_aim(actor, world, 0)

    def test_below_his_lane_it_leaves_the_band_downward(self) -> None:
        # Traced live: 17 lanes below him the old aim went up to the pocket
        # above -- through the juggle -- while 8 lanes down cleared it.
        mode, _, aim_y = self._aim(_actor(2850, 77), _jack_sim(2800, 60, left=False))
        self.assertIs(mode, J.EngageMode.AROUND)
        self.assertGreaterEqual(aim_y, 60 + J.ZONE_LANE[1] + 1)

    def test_above_his_lane_it_leaves_the_band_upward(self) -> None:
        mode, _, aim_y = self._aim(_actor(2850, 56), _jack_sim(2800, 60, left=False))
        self.assertLessEqual(aim_y, 60 + J.ZONE_LANE[0] - 1)

    def test_in_his_dodge_there_is_no_back_to_go_for(self) -> None:
        jack = _jack_sim(2800, 60, left=True, state=J.ST_EVADE)
        mode, aim_x, _ = self._aim(_actor(2830, 60, left=True), jack)
        self.assertIs(mode, J.EngageMode.AROUND)
        self.assertEqual(aim_x, 2830)

    def test_behind_him_past_the_bands_back_edge_it_walks_in(self) -> None:
        mode, aim_x, aim_y = self._aim(_actor(2830, 60, left=True), _jack_sim(2800, 60, left=True))
        self.assertIs(mode, J.EngageMode.BEHIND)
        self.assertEqual((aim_x, aim_y), (2800 + J.BACK_DX, 60))

    def test_in_his_dodge_it_waits_in_the_pocket_above_him(self) -> None:
        jack = _jack_sim(2800, 91, left=True, state=J.ST_EVADE, flags=0x07, vx=-3.0)
        mode, aim_x, aim_y = self._aim(_actor(2850, 30), jack)
        self.assertIs(mode, J.EngageMode.AROUND)
        self.assertEqual((aim_x, aim_y), (2850, 91 - J.POCKET_DY))

    def test_below_him_in_his_dodge_it_does_not_cross_his_band(self) -> None:
        jack = _jack_sim(2800, 21, left=True, state=J.ST_EVADE, flags=0x07, vx=-3.0)
        _, _, aim_y = self._aim(_actor(2850, 60), jack)
        self.assertEqual(aim_y, 60)

    def test_pinned_out_of_reach_in_his_dodge_it_steps_80_px_behind_his_walk(self) -> None:
        jack = _jack_sim(5390, 23, left=True, state=J.ST_EVADE, flags=0x03, vx=3.0, juggle=False)
        actor = _actor(5344, 41)
        actor.x_hi = 5344.0
        _, aim_x, _ = J.engage_aim(actor, _world(jack), 0)
        self.assertLessEqual(aim_x + J.EVADE_PAST_DX, 5390)

    def test_walking_away_out_of_reach_in_his_dodge_it_stands(self) -> None:
        # Traced live: going after the exit point kept the actor ~70 px behind
        # him, inside the 80 his reset needs.
        jack = _jack_sim(2690, 22, left=False, state=J.ST_EVADE, flags=0x07, vx=-4.0, juggle=False)
        actor = _actor(2760, 46)
        actor.x_lo = 2732.0
        _, aim_x, _ = J.engage_aim(actor, _world(jack), 0)
        self.assertEqual(aim_x, 2760)

    def test_walking_back_into_reach_in_his_dodge_it_waits(self) -> None:
        jack = _jack_sim(2690, 91, left=False, state=J.ST_EVADE, flags=0x03, vx=3.0, juggle=False)
        actor = _actor(2740, 60)
        actor.x_lo = 2732.0
        mode, _, _ = J.engage_aim(actor, _world(jack), 0)
        self.assertIsNot(mode, J.EngageMode.AROUND)


class PlanTests(unittest.TestCase):
    def test_it_never_walks_into_a_live_juggle(self) -> None:
        axes = _token_axes(_juggling_world(left=True))
        plan = J.plan_engage(
            _myself(2760, 60, left=True), _jack(2800, 60, left=True),
            projectiles=axes, camera=CAMERA,
        )
        self.assertNotEqual(plan.outcome, "hit")
        self.assertIs(plan.mode, J.EngageMode.AROUND)

    def test_from_his_back_it_walks_in_and_takes_the_hold(self) -> None:
        axes = _token_axes(_juggling_world(left=True))
        plan = J.plan_engage(
            _myself(2826, 60, left=True), _jack(2800, 60, left=True),
            projectiles=axes, camera=CAMERA,
        )
        self.assertEqual(plan.outcome, "grab")
        self.assertEqual(plan.dir_x, -1)

    def test_with_no_axe_out_it_walks_straight_in(self) -> None:
        stunned = _jack(
            2800, 60, left=True, state=J.ST_HITSTUN, has_projectile=False, stun_timer=20,
            combat_phase=CombatPhase.STUNNED,
        )
        plan = J.plan_engage(_myself(2770, 60, left=False), stunned, camera=CAMERA)
        self.assertEqual(plan.outcome, "grab")
        self.assertEqual(plan.dir_x, 1)

    def test_a_throw_about_to_fly_along_its_lane_is_left(self) -> None:
        thrower = _jack(
            2900, 60, left=True, state=J.ST_THROW, has_projectile=False,
            anim=J.ANIM_THROW | J.ANIM_MIRROR_BIT, anim_frame=0, anim_countdown=3,
            anim_reload=3, flags_31=0x03, stun_timer=3,
        )
        waiting = Projectile(
            slot="obj05", world_x=2916, world_y=59, vel_x=0.0, vel_z=0.0, type_id=J.AXE_TYPE,
            state=J.AXE_THROWN, world_z=96, fine_z=96.0, owner_slot="obj00", flags_31=0x01,
            attack_box_id=0x2B,
        )
        plan = J.plan_engage(
            _myself(2750, 60, left=False), thrower, projectiles=[waiting], camera=CAMERA
        )
        self.assertNotEqual(plan.outcome, "hit")
        self.assertIs(plan.mode, J.EngageMode.CLEAR)
        self.assertNotEqual(plan.dir_y, 0)


class PunchTests(unittest.TestCase):
    BOX = (18, 68)  # Blaze's punch box ahead of her

    def test_a_punch_from_the_pocket_stuns_him_and_his_axes_come_down(self) -> None:
        world = _juggling_world(left=True)
        jack = world.jacks[0]
        actor = _actor(2760, 60 - 12, left=False)  # 12 lanes over his, in front
        world.punch = self.BOX
        self.assertIs(J.jack_update(0, actor, world), J.Outcome.STRUCK)
        self.assertEqual((jack.state, jack.t50, jack.hp), (J.ST_HITSTUN, J.HITSTUN_UPDATES, 8))
        self.assertFalse(jack.juggle)  # he re-spawns the juggle when he resets
        world.punch = None
        far = _actor(2400, 60)
        for _ in range(22):
            for axe in world.axes:
                J.axe_update(axe, far, world)
            world.axes = [x for x in world.axes if not x.gone and x.state != J.AXE_DROPPED]
        self.assertEqual(world.axes, [])

    def test_the_pocket_is_out_of_the_juggle(self) -> None:
        # 9 lanes is the ROM's edge; the plan keeps its 1-lane margin, so 10.
        world = _juggling_world(left=True)
        pocket = _actor(2785, 60 - 10, left=False)
        for _ in range(24):
            for axe in world.axes:
                self.assertIs(J.axe_update(axe, pocket, world), J.Outcome.NONE)

    def test_a_punch_at_zero_health_kills(self) -> None:
        jack = _jack_sim(2800, 60, left=True, hp=0)
        world = _world(jack)
        world.punch = self.BOX
        J.jack_update(0, _actor(2760, 60, left=False), world)
        self.assertFalse(jack.alive)

    def test_a_live_punch_knocks_a_released_throw_away(self) -> None:
        world = _world(_jack_sim(2900, 60, left=True))
        axe = J.AxeSim.spawned(0, J.AXE_THROWN, 0x2B)
        axe.entry, axe.released = False, True
        axe.x, axe.y, axe.z, axe.vx = 2830.0, 59.0, 112.0, -J.THROW_SPEED
        world.axes.append(axe)
        world.punch = self.BOX
        self.assertIs(J.axe_update(axe, _actor(2790, 60, left=False), world), J.Outcome.NONE)
        self.assertEqual(axe.state, J.AXE_DROPPED)
        self.assertTrue(axe.harmless)

    def test_an_arc_cut_short_falls_on_a_body_in_its_lane(self) -> None:
        # Traced live (round 2): the hold cut his arc short at z 128; the axe
        # fell 128, 137, 147, 158 at -1 px an update, hit the front holder 22
        # px away, and was gone at the floor.
        world = _world(_jack_sim(2827, 68, left=False, state=J.ST_HELD))
        axe = J.AxeSim.spawned(0, J.AXE_DROPPED, 0x2B)
        axe.entry = False
        axe.x, axe.y, axe.z, axe.vx, axe.vz = 2837.0, 76.0, 128.0, -1.0, 7.875
        world.axes.append(axe)
        holder = _actor(2859, 68, left=True)
        heights, outcomes = [], []
        while not axe.gone:
            heights.append(int(axe.z))
            outcomes.append(J.axe_update(axe, holder, world, margin=False))
        self.assertEqual(heights, [128, 137, 147, 158])
        self.assertIn(J.Outcome.HIT, outcomes)

    def test_a_dead_jacks_axes_still_fly(self) -> None:
        axe = Projectile(
            slot="obj03", world_x=2790, world_y=68, vel_x=4.0, vel_z=0.0, type_id=J.AXE_TYPE,
            state=J.AXE_JUGGLED, world_z=128, fine_z=128.0, owner_slot="obj09", flags_31=0x03,
            offset=-10.0, attack_box_id=0x2B,
        )
        world = J.build_world(_myself(2700, 60, left=False), [], [axe], camera=CAMERA)
        self.assertEqual(len(world.axes), 1)
        self.assertFalse(world.jacks[0].alive)

    def test_in_his_dodge_the_plan_punches_from_the_pocket(self) -> None:
        # Traced live (round 2): in $07 he walks past the actor along lane 91
        # with his juggle up; POCKET_DY lanes above him the punch reaches his
        # body and the juggle cannot reach the actor.
        axes = _token_axes(_juggling_world(left=True, x=2860, y=91))
        dodging = _jack(
            2860, 91, left=True, state=J.ST_EVADE, flags_31=0x07, grunt_vel_x=-3.0, stun_timer=10,
        )
        plan = J.plan_engage(
            _myself(2800, 91 - J.POCKET_DY, left=False), dodging,
            projectiles=axes, camera=CAMERA, can_punch=True,
        )
        self.assertIn(plan.outcome, ("struck", "grab"))

    def test_on_his_walk_to_the_lane_the_pocket_is_no_pocket(self) -> None:
        # $08 walks his lane toward the target, the juggle with it: the pocket
        # 12 lanes over is crossed within 3 updates, so the plan does not stand
        # there to punch.
        axes = _token_axes(_juggling_world(left=True))
        plan = J.plan_engage(
            _myself(2755, 60 - 12, left=False), _jack(2800, 60, left=True),
            projectiles=axes, camera=CAMERA, can_punch=True,
        )
        self.assertNotEqual(plan.outcome, "hit")
        self.assertFalse(plan.punch)

    def test_armed_the_swing_lands_through_his_juggle(self) -> None:
        # User: with a weapon the AI can strike Jack even while he juggles --
        # the live weapon box meets an axe before the axe meets the actor
        # (``_punch_meets_axe``). A pipe in Blaze's hand, 50 px in front of
        # him on his lane, both axes up.
        axes = _token_axes(_juggling_world(left=True))
        plan = J.plan_engage(
            _myself(2750, 60, left=False, held_weapon_type=0x0B), _jack(2800, 60, left=True),
            projectiles=axes, camera=CAMERA, strikes=J.strike_specs(2, 0x0B),
        )
        self.assertEqual(plan.outcome, "struck")
        self.assertTrue(plan.punch)

    def test_armed_nothing_is_swung_from_where_an_axe_lands_first(self) -> None:
        axes = _token_axes(_juggling_world(left=True))
        plan = J.plan_engage(
            _myself(2770, 60, left=False, held_weapon_type=0x0B), _jack(2800, 60, left=True),
            projectiles=axes, camera=CAMERA, strikes=J.strike_specs(2, 0x0B),
        )
        self.assertFalse(plan.punch)

    def test_a_weapon_strike_takes_its_own_damage(self) -> None:
        jack = _jack_sim(2800, 60, left=True, hp=9)
        world = _world(jack)
        world.punch = (35, 53)
        world.damage = 4
        self.assertIs(J.jack_update(0, _actor(2750, 60, left=False), world), J.Outcome.STRUCK)
        self.assertEqual(jack.hp, 5)

    def test_strike_timings_per_hand(self) -> None:
        self.assertEqual(len(J.strike_specs(2, 0)), 1)
        self.assertEqual(J.strike_specs(2, 0x0C), ())  # pepper: B throws the can
        swings = J.strike_specs(2, 0x0A)
        self.assertEqual({s.box for s in swings}, {(35, 53)})
        self.assertEqual({s.damage for s in swings}, {4})
        self.assertGreater(len(swings), 1)  # the live window is unmeasured
        self.assertEqual({s.damage for s in J.strike_specs(0, 0x08)}, {5})

    def test_no_second_punch_while_his_stun_runs(self) -> None:
        world = _world(_jack_sim(2800, 60, left=True, state=J.ST_HITSTUN, t50=20))
        self.assertFalse(J._punch_worth_trying(world, 0, _actor(2760, 48)))
        world.jacks[0].t50 = J.REPUNCH_T50
        self.assertTrue(J._punch_worth_trying(world, 0, _actor(2760, 48)))


class HoldStepTests(unittest.TestCase):
    def _holder(self, base: int, *, knees: int = 0, crossed: bool = False, x: int = 2800) -> Myself:
        return _myself(
            x, 60, left=False, action_state=base, held_enemy_slot="obj00",
            action_flags=PLAYER_KNEE_CHAIN_BIT if knees else 0,
            knee_chain_last={0: 0, 1: 0x6A, 2: 0x6C}[knees], crossover_spent=crossed,
        )

    def _held(self, hp: int = 9, x: int = 2832) -> Jack:
        return _jack(x, 60, left=True, health=hp, state=J.ST_HELD, combat_phase=CombatPhase.GRABBED)

    def _flying(self, *, x: int, z: float = 120.0) -> Projectile:
        return Projectile(
            slot="obj03", world_x=x, world_y=68, vel_x=-1.0, vel_z=-7.875, type_id=J.AXE_TYPE,
            state=J.AXE_JUGGLED, world_z=int(z), fine_z=z, owner_slot="obj00",
            flags_31=0x01, offset=float(x - 2832), attack_box_id=0x2B,
        )

    def test_a_back_hold_waits_for_his_axes_to_come_down(self) -> None:
        holder = self._holder(0x66)
        self.assertIs(J.hold_step(holder, self._held(), [self._flying(x=2870)]), HoldStep.WAIT)

    def test_a_clean_back_hold_crosses_over_for_the_knees(self) -> None:
        self.assertIs(J.hold_step(self._holder(0x66), self._held(9)), HoldStep.CROSS)

    def test_a_back_hold_suplexes_when_it_kills(self) -> None:
        # Strictly: 5 from a Jack at 5 leaves him alive at 0.
        self.assertIs(J.hold_step(self._holder(0x66), self._held(4)), HoldStep.SUPLEX)
        self.assertIs(J.hold_step(self._holder(0x66), self._held(5)), HoldStep.CROSS)

    def test_a_front_hold_knees_twice_then_crosses_for_the_suplex(self) -> None:
        self.assertIs(J.hold_step(self._holder(0x60, knees=0), self._held()), HoldStep.KNEE)
        self.assertIs(J.hold_step(self._holder(0x60, knees=1), self._held()), HoldStep.KNEE)
        self.assertIs(J.hold_step(self._holder(0x60, knees=2), self._held()), HoldStep.CROSS)

    def test_the_third_knee_when_it_kills_or_nothing_else_is_left(self) -> None:
        self.assertIs(J.hold_step(self._holder(0x60, knees=2), self._held(2)), HoldStep.KNEE)
        self.assertIs(
            J.hold_step(self._holder(0x60, knees=2, crossed=True), self._held(9)), HoldStep.KNEE
        )

    def test_facing_a_camera_bound_it_throws_him_back_toward_the_middle(self) -> None:
        # Traced live (round 5): at the camera's right bound, knee, knee, cross
        # over, suplex threw a Jack 58 px past it, his slide took him to 136,
        # and his jumps kept him out of reach for 30 s.
        at_edge = self._holder(0x60, knees=2, x=2980)
        self.assertIs(J.hold_step(at_edge, self._held(9, x=3012), camera=CAMERA), HoldStep.THROW)
        self.assertIs(J.hold_step(at_edge, self._held(2, x=3012), camera=CAMERA), HoldStep.KNEE)
        mid = self._holder(0x60, knees=2)
        self.assertIs(J.hold_step(mid, self._held(9), camera=CAMERA), HoldStep.CROSS)

    def test_a_front_hold_crosses_out_of_an_axe_coming_down_on_it(self) -> None:
        axe = self._flying(x=2824)
        self.assertIs(J.hold_step(self._holder(0x60), self._held(), [axe]), HoldStep.CROSS)
        self.assertIs(
            J.hold_step(self._holder(0x60, crossed=True), self._held(), [axe]), HoldStep.RELEASE
        )


if __name__ == "__main__":
    unittest.main()
