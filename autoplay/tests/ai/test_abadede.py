"""The Abadede plan's ROM model and decisions (``ai/abadede.py``).

Every number here is the ROM's (``$143D0`` onwards): the approach at 6 px an
update that ends inside 16 lanes, the four-update pause and its three-way
decision, the retreat, the run at 12 px an update that keeps its lane and
ends inside 16 px, the brake and the punch that lands nowhere, the contact
order, and the band 17-18 lanes off his run where the walking box takes him
and his box misses. The verb wiring is ``test_abadede_wiring``'s.
"""

import unittest

from sor_autoplay.ai import abadede as plan
from sor_autoplay.ai import kinematics
from sor_autoplay.ai.antonio import ActorSim, actor_update
from sor_autoplay.ai.reach import PLAYER_BODY_REACH_X, walk_box_reach_x
from sor_autoplay.ai.tokens import Abadede, Myself
from sor_autoplay.memory_map import PLAYER_KNEE_CHAIN_BIT
from sor_autoplay.phases import CombatPhase

# Camera at world X 0: his screen X is his world X plus the $80 bias.
CAM_X = 0
AXEL, ADAM, BLAZE = 0, 1, 2
NONE, GRAB, STRUCK, HIT = plan.Outcome.NONE, plan.Outcome.GRAB, plan.Outcome.STRUCK, plan.Outcome.HIT


def _sim(
    x: float,
    y: float,
    *,
    primary: int = plan.PRIMARY_APPROACH,
    sub: int = plan.SUB_RUN,
    t54: int = 0,
    vx: float = 0.0,
    vy: float = 0.0,
    left: bool = True,
    variant: bool = False,
) -> plan.AbadedeSim:
    running = primary == plan.PRIMARY_CHARGE and sub in (plan.SUB_SETUP, plan.SUB_RUN)
    anim = (plan.ANIM_CHARGE if running else plan.ANIM_WALK) | (plan.ANIM_MIRROR_BIT if left else 0)
    return plan.AbadedeSim(
        x=float(x), y=float(y), primary=primary, sub=sub, t54=t54, vx=vx, vy=vy, anim=anim,
        jitter=1, screen_x=int(x) - CAM_X + plan.SCREEN_BIAS, cam_x=CAM_X, inert=0,
        variant=variant,
    )


def _run(x: float, y: float, *, left: bool = True) -> plan.AbadedeSim:
    """His run, already under way."""

    return _sim(
        x, y, primary=plan.PRIMARY_CHARGE, sub=plan.SUB_RUN,
        vx=-plan.CHARGE_SPEED if left else plan.CHARGE_SPEED, left=left,
    )


def _actor(x: float, y: float, *, char: int = BLAZE, left: bool = False) -> ActorSim:
    return ActorSim(
        x=float(x), y=float(y), facing_left=left, walking=False, vx=0.0, flags_31=0,
        speeds=kinematics.walk_speeds(char), walk_reach=walk_box_reach_x(char),
        body_reach=PLAYER_BODY_REACH_X[char], lane_lo=2.0, lane_hi=112.0,
        x_lo=-1e9, x_hi=1e9, holding=False, untouchable=False, unavailable=False,
        box_x=float(x), box_y=float(y),
    )


def _step(b: plan.AbadedeSim, a: ActorSim, move=(0, 0), *, punch=None) -> plan.Outcome:
    actor_update(a, *move)
    return plan.boss_update(b, a, punch=punch, margin=False)


def _until_contact(b, a, move=(0, 0), *, updates: int = 60, punch=None) -> tuple[plan.Outcome, int | None]:
    for n in range(updates):
        outcome = _step(b, a, move, punch=punch)
        if outcome is not NONE:
            return outcome, n
    return NONE, None


def _abadede(world_x: int = 200, world_y: int = 60, **overrides) -> Abadede:
    fields = dict(
        slot="obj00", type_id=0x30, world_x=world_x, world_y=world_y, health=32,
        combat_phase=CombatPhase.NORMAL, targets_player=1, facing_left=True,
        primary_state=plan.PRIMARY_HELD, substate=plan.HELD_READING, timer_54=30,
        screen_x=world_x + plan.SCREEN_BIAS, anim=plan.ANIM_WALK | plan.ANIM_MIRROR_BIT,
    )
    fields.update(overrides)
    return Abadede(**fields)


def _holder(action: int = 0x60, knees: int = 0, **overrides) -> Myself:
    last = {0: 0, 1: 0x6A, 2: 0x6C}[knees]
    fields = dict(
        slot="P1", player_index=1, character_id=BLAZE, character_name="Blaze",
        world_x=176, world_y=60, health=80, health_percent=100.0, lives=3,
        specials=1, held_weapon_type=0, facing_left=False,
        combat_phase=CombatPhase.HOLDING, action_state=action, is_airborne=False,
        held_enemy_slot="obj00", action_flags=PLAYER_KNEE_CHAIN_BIT if knees else 0,
        knee_chain_last=last,
    )
    fields.update(overrides)
    return Myself(**fields)


class ApproachTests(unittest.TestCase):
    """State 1 (``$145EC``) and the pause (``$14656``)."""

    def test_he_walks_six_a_side_until_the_lane_gap_is_under_sixteen(self) -> None:
        b = _sim(250, 20, sub=plan.SUB_SETUP)
        a = _actor(100, 60)
        _step(b, a)  # $145F8: aimed, no step
        self.assertEqual((b.vx, b.vy, b.facing_left), (-6.0, 6.0, True))
        lanes = []
        while b.primary == plan.PRIMARY_APPROACH:
            _step(b, a)
            lanes.append(b.y)
        self.assertEqual(lanes, [26.0, 32.0, 38.0, 44.0, 50.0, 50.0])
        self.assertEqual((b.primary, b.t54), (plan.PRIMARY_PAUSE, plan.PAUSE_UPDATES))
        self.assertEqual(b.x, 220.0)

    def test_x_only_moves_twenty_four_or_more_out(self) -> None:
        b = _sim(120, 20, vx=-6.0, vy=6.0)
        _step(b, _actor(100, 60))
        self.assertEqual((b.x, b.y), (120.0, 26.0))

    def test_the_pause_stands_four_updates_then_decides(self) -> None:
        b = _sim(170, 50, primary=plan.PRIMARY_PAUSE, t54=4, vx=-6.0)
        a = _actor(100, 60)
        for _ in range(3):
            _step(b, a)
            self.assertEqual((b.primary, b.x), (plan.PRIMARY_PAUSE, 170.0))
        _step(b, a)
        self.assertEqual(b.primary, plan.PRIMARY_CHARGE)

    def test_the_decision(self) -> None:
        cases = (
            ("far: charge", 113, 0, plan.PRIMARY_CHARGE),
            ("back off first", 112, 0, plan.PRIMARY_RETREAT),
            ("back off first", 81, 15, plan.PRIMARY_RETREAT),
            ("near: charge", 80, 0, plan.PRIMARY_CHARGE),
            ("lane: walk again", 40, 16, plan.PRIMARY_APPROACH),
        )
        for name, dx, dy, expected in cases:
            with self.subTest(name, dx=dx, dy=dy):
                b = _sim(100 + dx, 60, primary=plan.PRIMARY_PAUSE, t54=1)
                _step(b, _actor(100, 60 + dy))
                self.assertEqual((b.primary, b.sub), (expected, plan.SUB_SETUP))

    def test_round_eights_variant_decides_on_twenty_four_lanes_and_never_backs_off(self) -> None:
        for dx, dy, expected in (
            (100, 0, plan.PRIMARY_CHARGE),  # the middle band: no retreat
            (60, 20, plan.PRIMARY_CHARGE),  # 16-23 lanes: a run, not a walk
            (60, 24, plan.PRIMARY_APPROACH),
        ):
            with self.subTest(dx=dx, dy=dy):
                b = _sim(100 + dx, 60, primary=plan.PRIMARY_PAUSE, t54=1, variant=True)
                _step(b, _actor(100, 60 + dy))
                self.assertEqual(b.primary, expected)

    def test_the_variant_is_read_off_the_spawn_parameter(self) -> None:
        for param, variant in ((0x00, False), (0x10, False), (0x01, True)):
            with self.subTest(param=param):
                b = plan.AbadedeSim.from_token(_abadede(script_param=param), cam_x=CAM_X)
                self.assertIs(b.variant, variant)

    def test_off_screen_the_middle_band_charges_too(self) -> None:
        b = _sim(400, 60, primary=plan.PRIMARY_PAUSE, t54=1)  # screen X $210
        _step(b, _actor(300, 60))
        self.assertEqual(b.primary, plan.PRIMARY_CHARGE)


class RetreatTests(unittest.TestCase):
    """State 3 (``$146F0``)."""

    def test_he_backs_off_six_an_update_facing_the_target(self) -> None:
        b = _sim(150, 60, primary=plan.PRIMARY_RETREAT, sub=plan.SUB_SETUP, vx=-6.0)
        a = _actor(100, 60)
        _step(b, a)
        self.assertEqual((b.vx, b.vy, b.facing_left, b.t54), (6.0, 0.0, True, plan.RETREAT_UPDATES))
        xs = []
        while b.primary == plan.PRIMARY_RETREAT:
            _step(b, a)
            xs.append(b.x)
        self.assertEqual(xs[:3], [156.0, 162.0, 168.0])
        self.assertEqual(len(xs), plan.RETREAT_UPDATES)
        self.assertEqual((b.primary, b.t54), (plan.PRIMARY_PAUSE, plan.PAUSE_UPDATES))

    def test_leaving_the_screen_band_ends_it(self) -> None:
        b = _sim(310, 60, primary=plan.PRIMARY_RETREAT, sub=plan.SUB_RUN, t54=15, vx=6.0)
        a = _actor(200, 60)
        _step(b, a)  # screen $1B6: still inside, steps to 316 ($1BC)
        _step(b, a)  # $1BC: steps to 322 ($1C2)
        self.assertEqual(b.primary, plan.PRIMARY_RETREAT)
        _step(b, a)  # $1C2: out of [$80, $1C0)
        self.assertEqual(b.primary, plan.PRIMARY_PAUSE)


class ChargeTests(unittest.TestCase):
    """State 7 (``$14BDC``)."""

    def test_the_run_is_twelve_an_update_on_the_lane_it_started_on(self) -> None:
        b = _sim(220, 50, primary=plan.PRIMARY_CHARGE, sub=plan.SUB_SETUP, vx=-6.0, vy=6.0)
        a = _actor(100, 20)
        _step(b, a)
        self.assertEqual((b.vx, b.vy, b.sub), (-12.0, 0.0, plan.SUB_RUN))
        _step(b, a, (0, 1))
        _step(b, a, (0, 1))
        self.assertEqual((b.x, b.y), (196.0, 50.0))

    def test_inside_sixteen_he_brakes_two_updates_then_punches_fifteen(self) -> None:
        b = _run(150, 60)
        a = _actor(100, 20)  # far off his lane: nothing touches
        subs = []
        for _ in range(40):
            self.assertIs(_step(b, a), NONE)
            subs.append((b.primary, b.sub))
            if b.primary == plan.PRIMARY_RETREAT:
                break
        self.assertEqual(b.x, 114.0)  # 150 - 3 x 12: the last step lands inside 16
        brake = subs.count((plan.PRIMARY_CHARGE, plan.SUB_BRAKE))
        punch = subs.count((plan.PRIMARY_CHARGE, plan.SUB_PUNCH))
        self.assertEqual((brake, punch), (plan.BRAKE_UPDATES - 1 + 1, plan.PUNCH_UPDATES))

    def test_a_screen_edge_stops_the_run_on_the_next_update(self) -> None:
        b = _run(5, 60)  # screen $85, running left
        a = _actor(-300, 20)
        _step(b, a)  # the edge test reads $85: on
        self.assertEqual((b.primary, b.x), (plan.PRIMARY_CHARGE, -7.0))
        _step(b, a)  # now $79: stop, and decide on the next update
        self.assertEqual((b.primary, b.t54), (plan.PRIMARY_PAUSE, 1))


class ContactTests(unittest.TestCase):
    """``$AAA0``: the actor's box on his body first, then his on the actor."""

    def test_his_run_reaches_sixteen_lanes_and_no_further(self) -> None:
        for dy, expected in ((0, HIT), (16, HIT), (-16, HIT), (17, NONE), (-17, NONE)):
            with self.subTest(dy=dy):
                outcome, _ = _until_contact(_run(200, 60), _actor(100, 60 + dy))
                self.assertIs(outcome, expected)

    def test_on_his_lane_his_box_arrives_before_the_walking_box(self) -> None:
        outcome, _ = _until_contact(_run(220, 60), _actor(100, 60))
        self.assertIs(outcome, HIT)

    def test_seventeen_and_eighteen_lanes_off_the_walking_box_takes_him(self) -> None:
        for dy in (17, 18, -17, -18):
            with self.subTest(dy=dy):
                outcome, _ = _until_contact(_run(220, 60), _actor(100, 60 + dy), (1, 0))
                self.assertIs(outcome, GRAB)

    def test_nineteen_lanes_off_nothing_touches(self) -> None:
        outcome, _ = _until_contact(_run(220, 60), _actor(100, 79), (1, 0), updates=12)
        self.assertIs(outcome, NONE)

    def test_a_punch_meets_his_run_before_his_box_meets_the_actor(self) -> None:
        outcome, _ = _until_contact(_run(220, 60), _actor(100, 60), punch=(18, 68))
        self.assertIs(outcome, STRUCK)

    def test_a_strike_outside_his_screen_band_counts_for_nothing(self) -> None:
        b = _run(40, 60)
        b.screen_x = 0x70
        self.assertIs(plan.contact(b, _actor(0, 60), punch=(18, 68), margin=False), NONE)

    def test_the_punch_ending_his_run_lands_nowhere(self) -> None:
        b = _sim(110, 60, primary=plan.PRIMARY_CHARGE, sub=plan.SUB_PUNCH, t54=10, vx=-12.0)
        b.anim = plan.ANIM_PUNCH  # its box reaches 32 px behind him, onto the actor
        self.assertIs(_step(b, _actor(100, 60)), NONE)

    def test_backing_off_his_box_is_dropped(self) -> None:
        b = _sim(110, 60, primary=plan.PRIMARY_RETREAT, sub=plan.SUB_RUN, t54=10, vx=6.0, left=True)
        b.anim = plan.ANIM_WALK  # the box ahead of him, over the actor
        self.assertIs(_step(b, _actor(125, 60)), NONE)

    def test_in_the_pause_his_walk_box_takes_the_actor_ten_lanes_off_and_no_further(self) -> None:
        for dy, expected in ((10, HIT), (11, NONE)):
            with self.subTest(dy=dy):
                b = _sim(130, 60, primary=plan.PRIMARY_PAUSE, t54=4, vx=-6.0)
                self.assertIs(_step(b, _actor(100, 60 + dy)), expected)

    def test_from_behind_the_actor_facing_its_way_the_grab_is_refused(self) -> None:
        # $3266: same facing, and he is behind the actor -- the code lands on
        # him (state $B) and the actor takes nothing; he is then stood 24 px
        # in front of the actor and backs off.
        b = _sim(96, 60, primary=plan.PRIMARY_RETREAT, sub=plan.SUB_RUN, t54=10, vx=-6.0, left=False)
        a = _actor(100, 60, left=False)
        self.assertIs(_step(b, a, (0, 1)), NONE)
        self.assertEqual((b.primary, b.sub), (plan.PRIMARY_HELD, plan.HELD_STAND))
        _step(b, a)
        self.assertEqual((b.x, b.sub), (100.0 + plan.HOLD_STAND_DX, plan.HELD_READING))
        _step(b, a)
        self.assertEqual(b.primary, plan.PRIMARY_RETREAT)

    def test_facing_each_other_or_from_behind_him_the_grab_is_the_hold(self) -> None:
        front = _sim(110, 60, primary=plan.PRIMARY_PAUSE, t54=4, left=True)
        self.assertIs(_step(front, _actor(100, 71, left=False), (0, 1)), GRAB)
        back = _sim(110, 60, primary=plan.PRIMARY_PAUSE, t54=4, left=False)
        self.assertIs(_step(back, _actor(100, 71, left=False), (0, 1)), GRAB)

    def test_walking_into_the_pause_from_eleven_lanes_is_the_hold(self) -> None:
        b = _sim(140, 60, primary=plan.PRIMARY_PAUSE, t54=4, vx=-6.0)
        outcome, _ = _until_contact(b, _actor(100, 71), (1, 0), updates=4)
        self.assertIs(outcome, GRAB)


class ReleaseTests(unittest.TestCase):
    """A hold the actor let go of (``$148C8``)."""

    def test_a_released_hold_is_a_retreat_whose_first_test_is_the_regrab(self) -> None:
        b = _sim(124, 60, primary=plan.PRIMARY_HELD, sub=plan.HELD_READING, t54=30)
        a = _actor(100, 60)
        self.assertIs(_step(b, a, (1, 0)), NONE)
        self.assertEqual((b.primary, b.sub), (plan.PRIMARY_RETREAT, plan.SUB_SETUP))
        self.assertIs(_step(b, a, (1, 0)), NONE)
        self.assertIs(_step(b, a, (1, 0)), GRAB)

    def test_after_a_knees_shake_he_stands_in_front_of_the_actor(self) -> None:
        b = _sim(300, 60, primary=plan.PRIMARY_HELD, sub=plan.HELD_KNEE_SHAKING, t54=1)
        a = _actor(100, 64, left=True)
        _step(b, a)
        _step(b, a)
        self.assertEqual((b.x, b.y, b.sub), (100.0 - plan.HOLD_STAND_DX, 64.0, plan.HELD_READING))
        self.assertFalse(b.facing_left)


class PlanTests(unittest.TestCase):
    """``plan_from_sims``: the lookahead's choices."""

    def test_a_run_from_across_the_screen_is_met_from_the_sweet_band(self) -> None:
        p = plan.plan_from_sims(_run(290, 40), _actor(60, 40), punch=plan.punch_spec(BLAZE))
        self.assertEqual(p.outcome, "grab")
        self.assertFalse(p.punch)
        self.assertNotEqual(p.dir_y, 0)

    def test_a_run_already_close_on_the_lane_is_met_with_a_punch(self) -> None:
        p = plan.plan_from_sims(_run(200, 60), _actor(100, 60), punch=plan.punch_spec(BLAZE))
        self.assertEqual(p.outcome, "struck")

    def test_without_a_punch_it_never_presses_one(self) -> None:
        p = plan.plan_from_sims(_run(200, 60), _actor(100, 60), punch=None)
        self.assertFalse(p.punch)

    def test_the_pause_is_walked_into_from_his_side_band(self) -> None:
        b = _sim(150, 50, primary=plan.PRIMARY_PAUSE, t54=4, vx=-6.0)
        p = plan.plan_from_sims(b, _actor(110, 63), punch=plan.punch_spec(BLAZE))
        self.assertEqual(p.outcome, "grab")


def _fight(b: plan.AbadedeSim, a: ActorSim, *, char: int, updates: int = 120):
    """The planner playing the actor against his model, update by update, to
    the first contact."""

    spec = plan.punch_spec(char)
    punched_on = None
    for moves in range(updates):
        if punched_on is not None and moves - punched_on < spec.lock:
            a.walking = False
            a.box_x, a.box_y = a.x, a.y
        else:
            punched_on = None
            p = plan.plan_from_sims(b, a, punch=spec)
            if p.punch:
                punched_on = moves
                a.facing_left = b.x < a.x
                a.walking = False
                a.box_x, a.box_y = a.x, a.y
            else:
                actor_update(a, p.dir_x, p.dir_y)
        live = None
        if punched_on is not None and spec.live[0] <= moves - punched_on <= spec.live[1]:
            live = spec.box
        outcome = plan.boss_update(b, a, punch=live, margin=False)
        if outcome is not NONE:
            return outcome, moves
    return NONE, None


class ClosedLoopTests(unittest.TestCase):
    """The planner against his model, from the starts the fight offers."""

    STARTS = (
        ("entrance, walking in from above", lambda: _sim(260, 16, sub=plan.SUB_SETUP)),
        ("pausing on the actor's lane", lambda: _sim(170, 60, primary=plan.PRIMARY_PAUSE, t54=3, vx=-6.0)),
        ("backing off", lambda: _sim(160, 60, primary=plan.PRIMARY_RETREAT, sub=plan.SUB_SETUP, vx=-6.0)),
        ("running from far on the lane", lambda: _run(300, 60)),
        ("running from far, off the lane", lambda: _run(300, 48)),
        ("setting up a run", lambda: _sim(240, 66, primary=plan.PRIMARY_CHARGE, sub=plan.SUB_SETUP, vx=-6.0)),
    )

    def test_every_start_ends_in_his_hands_and_never_in_his_run(self) -> None:
        for char in (BLAZE, AXEL, ADAM):
            for name, make in self.STARTS:
                with self.subTest(name, char=char):
                    outcome, _ = _fight(make(), _actor(100, 60, char=char), char=char)
                    self.assertIn(outcome, (GRAB, STRUCK))


class HoldStepTests(unittest.TestCase):
    """``hold_step``: knee, knee, release -- each on an update he reads."""

    def test_a_knee_only_on_an_update_he_reads(self) -> None:
        self.assertIs(plan.hold_step(_holder(), _abadede()), plan.HoldStep.KNEE)
        for sub in (plan.HELD_STAND, plan.HELD_KNEE_SHAKE, plan.HELD_KNEE_SHAKING):
            with self.subTest(sub=sub):
                self.assertIs(plan.hold_step(_holder(knees=1), _abadede(substate=sub)), plan.HoldStep.WAIT)

    def test_after_two_knees_the_release(self) -> None:
        self.assertIs(plan.hold_step(_holder(knees=1), _abadede()), plan.HoldStep.KNEE)
        self.assertIs(plan.hold_step(_holder(knees=2), _abadede()), plan.HoldStep.RELEASE)

    def test_the_third_knee_only_when_it_kills(self) -> None:
        self.assertIs(plan.hold_step(_holder(knees=2), _abadede(health=3)), plan.HoldStep.KNEE)
        self.assertIs(plan.hold_step(_holder(knees=2), _abadede(health=4)), plan.HoldStep.RELEASE)

    def test_a_back_hold_crosses_over_suplexes_to_kill_or_lets_go(self) -> None:
        back = _holder(action=0x66)
        self.assertIs(plan.hold_step(back, _abadede()), plan.HoldStep.CROSS)
        self.assertIs(plan.hold_step(back, _abadede(health=5)), plan.HoldStep.SUPLEX)
        spent = _holder(action=0x66, crossover_spent=True)
        self.assertIs(plan.hold_step(spent, _abadede()), plan.HoldStep.RELEASE)
        # State $D (handed a back hold): a crossover would free him.
        self.assertIs(
            plan.hold_step(back, _abadede(primary_state=plan.PRIMARY_HELD_BACK)), plan.HoldStep.RELEASE
        )

    def test_his_run_presses_from_two_updates_before_it_is_decided(self) -> None:
        self.assertTrue(plan.charge_is_pressing(_abadede(primary_state=plan.PRIMARY_CHARGE, substate=1)))
        self.assertTrue(plan.charge_is_pressing(_abadede(primary_state=plan.PRIMARY_PAUSE, timer_54=2)))
        self.assertFalse(plan.charge_is_pressing(_abadede(primary_state=plan.PRIMARY_PAUSE, timer_54=3)))
        self.assertFalse(plan.charge_is_pressing(_abadede(primary_state=plan.PRIMARY_CHARGE, substate=3)))


if __name__ == "__main__":
    unittest.main()
