"""The Bongo plan's ROM model and decisions (``ai/bongo.py``).

Every number here is the ROM's (``$174E0`` onwards, and the shared later-boss
helpers ``$17924``-``$17F9C``): the approach and its lane keeping, the turn,
the wind-up's three tacticals, the launch's lane velocity, the charge that
speeds up and never re-aims, the flame (type ``$97``) and its growing box,
the contact order that makes a grab beat the flame, the flame landing on a
holder, and the lookahead built on all of it. The verb wiring is
``test_bongo_wiring``'s.
"""

import unittest

from sor_autoplay.ai import bongo as plan
from sor_autoplay.ai import kinematics
from sor_autoplay.ai.antonio import ActorSim, actor_update
from sor_autoplay.ai.reach import PLAYER_BODY_REACH_X, walk_box_reach_x
from sor_autoplay.ai.tokens import Bongo, CameraRange, Myself, Projectile
from sor_autoplay.phases import CombatPhase

# Camera at world X 0: the walk clamp is 32..288 and his screen X is his
# world X plus the $80 bias.
CAM_X = 0
AXEL, ADAM, BLAZE = 0, 1, 2


def _bongo_sim(
    x: float,
    y: float,
    *,
    primary: int = plan.PRIMARY_ACTIVE,
    tactical: int = 0,
    t68: int = 0,
    left: bool = True,
    vx: float = 0.0,
    vy: float = 0.0,
) -> plan.BongoSim:
    anim = plan.ANIM_IDLE | (plan.ANIM_MIRROR_BIT if left else 0)
    return plan.BongoSim(
        x=float(x), y=float(y), z=0, primary=primary, tactical=tactical, t68=t68, t79=0,
        vx=vx, vy=vy, anim=anim, frame=0, countdown=10, reload=10, shown_attack=0,
        shown_body=0x94 if left else 0x95, screen_x=int(x) - CAM_X + plan.SCREEN_BIAS,
        cam_x=CAM_X, pair_role=0, inert=0, pending_hold=False, flame=None, flame_known=True,
    )


def _actor_sim(x: float, y: float, *, char: int = BLAZE, left: bool = False) -> ActorSim:
    return ActorSim(
        x=float(x), y=float(y), facing_left=left, walking=False, vx=0.0, flags_31=0,
        speeds=kinematics.walk_speeds(char), walk_reach=walk_box_reach_x(char),
        body_reach=PLAYER_BODY_REACH_X[char], lane_lo=2.0, lane_hi=112.0,
        x_lo=32.0, x_hi=288.0, holding=False, untouchable=False, unavailable=False,
        box_x=float(x), box_y=float(y),
    )


def _step(b: plan.BongoSim, a: ActorSim, move=(0, 0), *, char: int = BLAZE) -> plan.Outcome:
    actor_update(a, *move)
    return plan.boss_update(b, a, margin=False, body_top=plan.BODY_TOP_Z[char])


def _launch(b: plan.BongoSim, a: ActorSim) -> int:
    """Update him (the actor standing) until the charge launches; how many."""

    for n in range(1, 60):
        assert _step(b, a) is plan.Outcome.NONE
        if b.tactical == plan.TAC_CHARGE:
            return n
    raise AssertionError("never launched")


def _bongo_token(world_x: int = 200, world_y: int = 60, **overrides) -> Bongo:
    fields = dict(
        slot="obj00", type_id=0x57, world_x=world_x, world_y=world_y, health=30,
        combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=True,
        primary_state=plan.PRIMARY_ACTIVE, tactical=0, screen_x=world_x + plan.SCREEN_BIAS,
        anim=plan.ANIM_MIRROR_BIT, anim_frame=0, anim_countdown=10, body_box_id=0x94,
    )
    fields.update(overrides)
    return Bongo(**fields)


def _myself(world_x: int, world_y: int, **overrides) -> Myself:
    fields = dict(
        slot="P1", player_index=1, character_id=BLAZE, character_name="Blaze",
        world_x=world_x, world_y=world_y, health=80, health_percent=100.0, lives=3,
        specials=1, held_weapon_type=0, facing_left=False,
        combat_phase=CombatPhase.NORMAL, action_state=0x02, is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


class ApproachTests(unittest.TestCase):
    """State 1 (``$175BA``)."""

    def test_a_target_behind_him_costs_a_ten_update_turn_standing_still(self) -> None:
        b = _bongo_sim(200, 60, left=True)
        a = _actor_sim(260, 60)
        _step(b, a)
        self.assertEqual((b.primary, b.tactical, b.t68), (plan.PRIMARY_ACTIVE, 1, plan.TURN_UPDATES))
        x = b.x
        for _ in range(plan.TURN_UPDATES - 1):
            _step(b, a)
            self.assertEqual(b.x, x)
        _step(b, a)
        self.assertEqual(b.tactical, 0)
        self.assertFalse(b.facing_left)

    def test_far_he_walks_in_half_a_pixel_and_steps_away_on_the_lane(self) -> None:
        b = _bongo_sim(250, 60, left=True)
        a = _actor_sim(60, 70)  # 190 px off: outside his $B0 gate, 10 lanes below
        _step(b, a)
        self.assertEqual((b.vx, b.vy), (-0.5, -0.5))
        self.assertEqual(b.primary, plan.PRIMARY_ACTIVE)

    def test_a_level_target_counts_as_below_him(self) -> None:
        b = _bongo_sim(200, 60, left=True)
        _step(b, _actor_sim(10, 60))
        self.assertEqual(b.vy, -0.5)

    def test_the_lane_gap_he_keeps_is_eighty_to_ninety_six(self) -> None:
        for gap, expected in ((79, -0.5), (80, 0.0), (95, 0.0), (96, 0.5)):
            with self.subTest(gap=gap):
                b = _bongo_sim(200, 0, left=True)
                _step(b, _actor_sim(10, gap))
                self.assertEqual(b.vy, expected)

    def test_inside_his_gate_the_wind_up_starts(self) -> None:
        b = _bongo_sim(200, 60, left=True)
        _step(b, _actor_sim(200 - plan.WINDUP_DX + 1, 60))
        self.assertEqual((b.primary, b.tactical, b.t68), (plan.PRIMARY_CHARGE, 0, 5))
        self.assertEqual(b.anim & ~plan.ANIM_MIRROR_BIT, plan.ANIM_WINDUP[0])

    def test_the_edge_nudge_keeps_him_inside_the_screen_band(self) -> None:
        # Past $1F0 of the screen he is pulled back to it before walking.
        b = _bongo_sim(600, 60, left=True)
        b.screen_x = 600 + plan.SCREEN_BIAS
        _step(b, _actor_sim(40, 60))
        self.assertLess(b.x, plan.SCREEN_MAX - plan.SCREEN_BIAS)


class WindupAndLaunchTests(unittest.TestCase):
    """State 2 (``$17682``), tacticals 0-2 and the launch (``$176E6``)."""

    def test_the_launch_comes_twenty_one_updates_after_the_gate(self) -> None:
        b = _bongo_sim(200, 60, left=True)
        a = _actor_sim(60, 60)
        self.assertEqual(_launch(b, a), sum(plan.WINDUP_UPDATES) + 1)

    def test_the_launch_aims_his_lane_at_the_target_as_he_reaches_it(self) -> None:
        b = _bongo_sim(200, 60, left=True)
        a = _actor_sim(100, 100)
        _launch(b, a)
        d50 = abs(round(a.x) - int(b.x))
        self.assertEqual(b.vx, -plan.CHARGE_SPEED)
        self.assertAlmostEqual(b.vy, plan._launch_lane_speed(d50, 100 - int(b.y)))
        self.assertGreater(b.vy, 0)

    def test_a_level_target_gets_no_lane_velocity(self) -> None:
        b = _bongo_sim(200, 60, left=True, primary=plan.PRIMARY_CHARGE, tactical=2, t68=1)
        a = _actor_sim(100, 60)
        _step(b, a)
        self.assertEqual(b.vy, 0.0)

    def test_the_lane_speed_is_capped_at_six(self) -> None:
        self.assertEqual(plan._launch_lane_speed(4, 100), plan.CHARGE_MAX_SPEED)

    def test_the_flame_is_born_twenty_pixels_ahead_on_his_lane_plus_four(self) -> None:
        b = _bongo_sim(200, 60, left=True, primary=plan.PRIMARY_CHARGE, tactical=2, t68=1)
        _step(b, _actor_sim(40, 60))
        self.assertIsNotNone(b.flame)
        self.assertEqual((b.flame.x, b.flame.y), (180.0, 64.0))
        self.assertEqual(b.flame.state, plan.FLAME_IGNITING)


class ChargeTests(unittest.TestCase):
    """Tacticals 3-4 (``$17762``, ``$177E2``)."""

    def test_both_speeds_grow_an_eighth_an_update_to_six(self) -> None:
        b = _bongo_sim(250, 60, left=True, primary=plan.PRIMARY_CHARGE, tactical=3, vx=-2.0, vy=0.5)
        a = _actor_sim(40, 90)
        _step(b, a)
        self.assertEqual((b.vx, b.vy), (-2.125, 0.625))
        for _ in range(60):
            _step(b, a)
        self.assertEqual(b.vx, -plan.CHARGE_MAX_SPEED)

    def test_the_lane_never_re_aims(self) -> None:
        # Launched downward, it keeps going down with the target far above.
        b = _bongo_sim(250, 60, left=True, primary=plan.PRIMARY_CHARGE, tactical=3, vx=-2.0, vy=0.5)
        a = _actor_sim(40, 10)
        _step(b, a)
        self.assertEqual(b.vy, 0.625)

    def test_inside_eight_lanes_the_lane_speed_holds(self) -> None:
        b = _bongo_sim(250, 60, left=True, primary=plan.PRIMARY_CHARGE, tactical=3, vx=-2.0, vy=0.5)
        _step(b, _actor_sim(40, 64))
        self.assertEqual(b.vy, 0.5)

    def test_eighty_past_the_target_he_runs_out_then_turns(self) -> None:
        b = _bongo_sim(100, 60, left=True, primary=plan.PRIMARY_CHARGE, tactical=3, vx=-6.0)
        a = _actor_sim(200, 20)  # behind him, and 100 px off
        _step(b, a)
        self.assertEqual((b.tactical, b.t79), (plan.TAC_RUNOUT, plan.RUNOUT_UPDATES))
        for _ in range(plan.RUNOUT_UPDATES):
            _step(b, a)
            if b.primary == plan.PRIMARY_ACTIVE:
                break
        self.assertEqual(b.primary, plan.PRIMARY_ACTIVE)
        _step(b, a)
        self.assertEqual(b.tactical, 1)  # the turn: the target is behind him


class FlameTests(unittest.TestCase):
    def test_its_box_grows_through_the_ignition_then_burns(self) -> None:
        b = _bongo_sim(250, 60, left=True, primary=plan.PRIMARY_CHARGE, tactical=2, t68=1)
        a = _actor_sim(40, 20)
        _step(b, a)
        shown = []
        for _ in range(14):
            _step(b, a)
            shown.append((b.flame.state, b.flame.shown))
        # Four updates a frame, the first one being its birth; the hand-over
        # to anim $3C/$3E comes on the last update of frame 2 ($17858 reads
        # its own +$0D == 1 there), so $A0 shows three times after it.
        self.assertEqual([s for _, s in shown[:11]], [0x9C] * 3 + [0x9E] * 4 + [0xA0] * 3 + [0xA2])
        self.assertEqual(shown[12], (plan.FLAME_BURNING, 0xA2))

    def test_burning_it_is_gone_the_update_he_leaves_the_charge(self) -> None:
        b = _bongo_sim(250, 60, left=True, primary=plan.PRIMARY_CHARGE, tactical=2, t68=1)
        a = _actor_sim(40, 20)
        for _ in range(15):
            _step(b, a)
        b.primary = plan.PRIMARY_HIT
        b.inert = 30
        _step(b, a)
        self.assertIsNone(b.flame)

    def test_igniting_it_stays_on_him_whatever_he_does(self) -> None:
        b = _bongo_sim(250, 60, left=True, primary=plan.PRIMARY_CHARGE, tactical=2, t68=1)
        a = _actor_sim(40, 20)
        _step(b, a)
        b.primary = plan.PRIMARY_HIT
        b.inert = 30
        _step(b, a)
        self.assertIsNotNone(b.flame)
        self.assertEqual(b.flame.x, float(int(b.x) - plan.FLAME_DX))

    def test_its_lane_reach_is_fourteen_above_him_and_thirty_six_below(self) -> None:
        f = plan.FlameSim(
            state=plan.FLAME_BURNING, x=180.0, y=64.0, z=-plan.FLAME_DZ, anim=0x3E, frame=0,
            countdown=1, reload=1, shown=0xA2, screen_x=0, slot=None,
        )
        for lane, hit in ((45, False), (46, True), (96, True), (97, False)):
            with self.subTest(lane=lane):
                a = _actor_sim(170, lane)
                self.assertEqual(
                    plan.flame_contact(f, a, body_top=-48, actor_z=0, margin=False), hit
                )

    def test_a_holder_is_not_spared(self) -> None:
        f = plan.FlameSim(
            state=plan.FLAME_BURNING, x=180.0, y=64.0, z=-plan.FLAME_DZ, anim=0x3E, frame=0,
            countdown=1, reload=1, shown=0xA2, screen_x=0, slot=None,
        )
        a = _actor_sim(170, 60)
        a.holding = True
        self.assertTrue(plan.flame_contact(f, a, body_top=-48, actor_z=0, margin=False))


class ContactTests(unittest.TestCase):
    def test_a_walk_into_his_body_is_a_grab(self) -> None:
        b = _bongo_sim(200, 60, left=True)
        a = _actor_sim(170, 60)
        self.assertIs(_step(b, a, (1, 0)), plan.Outcome.GRAB)

    def test_a_still_actor_has_no_walking_box_to_grab_with(self) -> None:
        b = _bongo_sim(200, 60, left=True)
        a = _actor_sim(170, 60)
        self.assertIs(_step(b, a, (0, 0)), plan.Outcome.NONE)

    def test_sixteen_above_his_charge_the_flame_misses_and_the_grab_takes(self) -> None:
        # The pocket: his lane less the actor's is 16 -- outside the flame's
        # 14, inside the grab's 16. On the bottom clamp, where his lane
        # cannot run away from it (it speeds up downward at 16 lanes off).
        b = _bongo_sim(260, 112, left=True, primary=plan.PRIMARY_CHARGE, tactical=3, vx=-3.0)
        plan._spawn_flame(b)
        b.flame.state = plan.FLAME_BURNING
        b.flame.anim, b.flame.shown = 0x3E, 0xA2
        a = _actor_sim(170, 96, left=False)
        outcomes = []
        for _ in range(30):
            out = _step(b, a, (1, 0))
            outcomes.append(out)
            if out is not plan.Outcome.NONE:
                break
        self.assertIs(outcomes[-1], plan.Outcome.GRAB)

    def test_a_front_grab_in_the_ignition_is_the_flames_hit(self) -> None:
        # Just launched, facing the actor: the hold puts him 32 px out,
        # facing it, and the igniting flame sits on the holder.
        b = _bongo_sim(200, 60, left=True, primary=plan.PRIMARY_CHARGE, tactical=3, vx=-2.0)
        plan._spawn_flame(b)
        a = _actor_sim(100, 44, char=AXEL)  # 16 above: the flame misses the walk-in
        a.facing_left = False
        for _ in range(3):
            actor_update(a, 0, 0)
        b.x = a.x + 30
        self.assertTrue(plan._grab_is_burnt(b, _walking(a, left=False), body_top=-51, actor_z=0))

    def test_a_back_grab_in_the_ignition_is_not(self) -> None:
        # From behind he is held facing away, and the flame points away too.
        b = _bongo_sim(200, 60, left=True, primary=plan.PRIMARY_CHARGE, tactical=3, vx=-2.0)
        plan._spawn_flame(b)
        a = _actor_sim(230, 60, char=AXEL, left=True)
        self.assertFalse(plan._grab_is_burnt(b, _walking(a, left=True), body_top=-51, actor_z=0))


def _walking(a: ActorSim, *, left: bool) -> ActorSim:
    a.walking = True
    a.facing_left = left
    return a


class PlanTests(unittest.TestCase):
    """The lookahead, played against the model it stands on."""

    def _fight(self, b, a, *, char=BLAZE, updates=400):
        top = plan.BODY_TOP_Z[char]
        for n in range(updates):
            p = plan.plan_from_sims(b, a, body_top=top)
            actor_update(a, p.dir_x, p.dir_y)
            out = plan.boss_update(b, a, margin=False, body_top=top)
            if out is not plan.Outcome.NONE:
                return out, n
        return plan.Outcome.NONE, updates

    def test_the_entrance_is_a_hold_before_his_first_launch(self) -> None:
        # He spawns facing away 40 px off: turn and wind-up are 31 updates.
        for char in (AXEL, BLAZE):
            with self.subTest(char=char):
                b = _bongo_sim(248, 16, left=False)
                a = _actor_sim(208, 50, char=char)
                out, n = self._fight(b, a, char=char)
                self.assertIs(out, plan.Outcome.GRAB)
                self.assertLess(n, 31)

    def test_on_the_bottom_rail_the_charge_ends_in_a_hold(self) -> None:
        b = _bongo_sim(280, 112, left=True)
        a = _actor_sim(60, 104)
        out, _ = self._fight(b, a)
        self.assertIs(out, plan.Outcome.GRAB)

    def test_a_charge_off_the_top_clamp_is_not_a_hit(self) -> None:
        b = _bongo_sim(280, 0, left=True)
        a = _actor_sim(100, 40, char=AXEL)
        out, _ = self._fight(b, a, char=AXEL)
        self.assertIsNot(out, plan.Outcome.HIT)

    def test_plan_engage_reads_the_tokens(self) -> None:
        bongo = _bongo_token(200, 60)
        me = _myself(100, 60)
        p = plan.plan_engage(me, bongo, camera=CameraRange(left=32, right=288, top=0, bottom=112), projectiles=[])
        self.assertIn(p.dir_x, (-1, 0, 1))
        self.assertIn(p.dir_y, (-1, 0, 1))

    def test_his_flame_is_carried_from_the_tokens(self) -> None:
        bongo = _bongo_token(200, 60, primary_state=plan.PRIMARY_CHARGE, tactical=3, child_slot="obj01")
        flame = Projectile(
            slot="obj01", world_x=180, world_y=64, vel_x=0.0, vel_z=0.0, type_id=plan.FLAME_TYPE,
            state=plan.FLAME_BURNING, anim=0x3E, attack_box_id=0xA2, anim_countdown=1,
        )
        self.assertIs(plan.linked_flame(bongo, [flame]), flame)
        b, _ = plan.build_sims(_myself(100, 60), bongo, projectiles=[flame])
        self.assertIsNotNone(b.flame)
        self.assertEqual(b.flame.shown, 0xA2)


class HoldStepTests(unittest.TestCase):
    def test_knee_knee_release(self) -> None:
        bongo = _bongo_token(132, 64, primary_state=plan.PRIMARY_HELD, health=30)
        fresh = _myself(100, 64, action_state=0x60)
        self.assertIs(plan.hold_step(fresh, bongo), plan.HoldStep.KNEE)

    def test_charge_is_pressing_near_the_launch(self) -> None:
        self.assertTrue(plan.charge_is_pressing(_bongo_token(primary_state=2, tactical=3)))
        self.assertTrue(plan.charge_is_pressing(_bongo_token(primary_state=2, tactical=2, timer_68=4)))
        self.assertFalse(plan.charge_is_pressing(_bongo_token(primary_state=2, tactical=0, timer_68=5)))
        self.assertFalse(plan.charge_is_pressing(_bongo_token(primary_state=1)))


if __name__ == "__main__":
    unittest.main()
