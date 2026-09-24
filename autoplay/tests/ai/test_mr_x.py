"""Mr. X's ROM model (``mr_x.py``) and the plan on it (``mr_x_plan.py``).

The model was checked field by field against lockstep recordings
(``tools/mr_x_lab.py --check``: every one of his updates in two runs, every
bullet step, every grab and hit, no field off outside the states it does not
replay); these pin the facts the plan rests on, each as the ROM plays it.
"""

import unittest

from sor_autoplay.ai import mr_x as model
from sor_autoplay.ai import mr_x_plan
from sor_autoplay.ai.mr_x import BulletSim, MrXSim, Outcome
from sor_autoplay.ai.twins import BLAZE, ActorSim

CAM = 128
FLOOR = model.FLOOR_ROUND_8


def _mr_x(**overrides) -> MrXSim:
    fields = dict(
        slot=4, x=300.0, y=60.0, z=float(FLOOR), vx=0.0, vy=0.0, vz=0.0, acc=0.0, grav=0.0,
        shake=0, primary=model.PRIMARY_DECIDE, sub=1, t54=10, t56=0, anim=model.ANIM_WALK,
        frame=0, last_frame=0xFF, flags1=0, f37=0, hp=50, damage=34, screen_x=0, cam_x=CAM,
        floor=FLOOR, attack_id=0, body_id=0x38, latch=0, gone=False,
    )
    fields.update(overrides)
    m = MrXSim(**fields)
    model.emit(m)
    return m


def _actor(x: float, y: float, *, facing_left: bool = False, character: int = BLAZE) -> ActorSim:
    a = ActorSim.standing(x=x, y=y, z=FLOOR, facing_left=facing_left, character=character, cam_x=CAM)
    a.punch = None
    return a


def _run(m: MrXSim, a: ActorSim, updates: int, stick=(0, 0), bullets=None):
    """Player update, then the object pass, ``updates`` times."""

    bullets = [] if bullets is None else bullets
    events = []
    for k in range(updates):
        a.latch = 0
        model.actor_step(a, *stick)
        for outcome in model.object_pass(m, bullets, a):
            if outcome is not Outcome.NONE:
                events.append((k, outcome))
    return events, bullets


class LungeTests(unittest.TestCase):
    def test_inside_both_gates_the_walk_in_lunges(self) -> None:
        m = _mr_x(primary=model.PRIMARY_WALK_IN, sub=1, x=300.0, y=60.0)
        a = _actor(250.0, 55.0)  # 50 px, 5 lanes: inside $40 and $10
        _run(m, a, 1)
        self.assertEqual((m.primary, m.sub), (model.PRIMARY_LUNGE, 0))
        self.assertEqual(m.x, 300.0)  # no move and no contact test that update

    def test_the_dash_is_52_px_with_the_64_px_box_out(self) -> None:
        m = _mr_x(primary=model.PRIMARY_LUNGE, sub=0, x=300.0, y=60.0)
        a = _actor(180.0, 30.0)  # far off his lane: nothing lands
        _run(m, a, 1)
        self.assertEqual(model.SHAPES[m.attack_id], (-64, 8, -8, 8, -80, 0))  # facing left
        _run(m, a, 5)
        self.assertEqual(m.x, 300.0 - (16 + 14 + 12 + 10))
        self.assertEqual(m.sub, 2)

    def test_17_lanes_off_it_misses_and_16_it_lands(self) -> None:
        for lane_gap, hit in ((17, False), (16, True)):
            with self.subTest(lane_gap=lane_gap):
                m = _mr_x(primary=model.PRIMARY_LUNGE, sub=0, x=300.0, y=60.0)
                a = _actor(260.0, 60.0 + lane_gap)
                events, _ = _run(m, a, 12)
                self.assertEqual(any(o is Outcome.HIT for _, o in events), hit)


class GunTests(unittest.TestCase):
    def test_far_off_he_goes_to_the_gun_after_ten_updates(self) -> None:
        m = _mr_x(x=300.0, t54=10)
        a = _actor(160.0, 60.0)  # 140 px: $80 or more
        _run(m, a, 9)
        self.assertEqual(m.primary, model.PRIMARY_DECIDE)
        _run(m, a, 1)
        self.assertEqual(m.primary, model.PRIMARY_GUN)

    def test_inside_128_px_he_walks_in(self) -> None:
        m = _mr_x(x=300.0, t54=10)
        _run(m, _actor(180.0, 60.0), 1)
        self.assertEqual(m.primary, model.PRIMARY_WALK_IN)

    def test_the_gun_fans_eight_bullets_from_the_top_lane_and_has_no_box(self) -> None:
        m = _mr_x(primary=model.PRIMARY_GUN, sub=0, x=300.0, y=40.0)
        a = _actor(200.0, 110.0)  # out of the fan's way
        fired: list[BulletSim] = []
        for _ in range(90):
            a.latch = 0
            model.actor_step(a, 0, 0)
            before = len(fired)
            spawned: list[BulletSim] = []
            model.mr_x_update(m, a, spawned=spawned)
            model.emit(m)
            fired.extend(spawned)
            if m.primary == model.PRIMARY_GUN:
                self.assertEqual(m.attack_id, 0)
            if len(fired) > before:
                self.assertEqual(m.y, model.GUN_LANE)
        self.assertEqual(len(fired), 8)
        # Index 0 straight down the street, 10 px in front of him, 32 lanes
        # down and 48 up; index 7 level with his facing.
        first, last = fired[0], fired[-1]
        self.assertEqual((first.vx, first.vy), (0.0, 24.0))
        self.assertEqual((first.x, first.y, first.z), (290.0, model.GUN_LANE + 32, FLOOR - 48))
        self.assertEqual((last.vx, last.vy), (-24.0, 0.0))

    def test_walking_into_him_in_the_wait_is_the_hold(self) -> None:
        m = _mr_x(primary=model.PRIMARY_GUN, sub=2, t54=15, x=300.0, y=model.GUN_LANE, anim=model.ANIM_GUN_UP)
        a = _actor(270.0, 4.0)
        events, _ = _run(m, a, 10, stick=(1, 0))
        self.assertEqual(events[0][1], Outcome.GRAB)


class RegrabTests(unittest.TestCase):
    def test_the_retreats_first_update_tests_where_he_stands(self) -> None:
        # Released 24 px in front of the actor: the walk straight back in has
        # its box on his body before he moves (measured: 3 frames after).
        m = _mr_x(primary=model.PRIMARY_RETREAT, sub=0, x=324.0, y=60.0)
        a = _actor(300.0, 60.0)
        events, _ = _run(m, a, 1, stick=(1, 0))
        self.assertEqual(events, [(0, Outcome.GRAB)])

    def test_one_update_later_he_is_gone(self) -> None:
        m = _mr_x(primary=model.PRIMARY_RETREAT, sub=0, x=324.0, y=60.0)
        a = _actor(300.0, 60.0)
        _run(m, a, 1)  # standing: no box, no hold
        events, _ = _run(m, a, 1, stick=(1, 0))
        self.assertEqual(events, [])
        self.assertEqual(m.x, 324.0 + 16)


class ReleaseTests(unittest.TestCase):
    def test_a_release_he_has_not_read_yet_is_still_re_grabbed(self) -> None:
        # The tick after the back press can still see him held (he reads the
        # cleared +$7D on his next update): the plan walks straight in anyway,
        # and the retreat's first update takes the walking box.
        m = _mr_x(primary=model.PRIMARY_HELD, sub=1, x=324.0, y=60.0, t54=38)
        a = _actor(300.0, 60.0)
        a.holding = False
        memory = mr_x_plan.PlanMemory()
        for k in range(4):
            p = mr_x_plan.plan(a, m, [], memory=memory)
            a.latch = 0
            model.actor_step(a, p.dir_x, p.dir_y)
            if Outcome.GRAB in model.object_pass(m, [], a):
                self.assertLessEqual(k, 2)
                return
        self.fail("no re-grab")


class StepInTests(unittest.TestCase):
    def test_his_lane_step_into_the_walking_box_is_the_hold(self) -> None:
        # dx 14 facing him, 20 lanes off: $13B6C's range test sees 20 >= 16,
        # steps him 8 lanes and then tests -- onto the walking box.
        m = _mr_x(primary=model.PRIMARY_WALK_IN, sub=1, x=300.0, y=60.0, vx=-8.0, vy=-8.0)
        a = _actor(286.0, 40.0)
        events, _ = _run(m, a, 1, stick=(0, -1))
        self.assertEqual(events, [(0, Outcome.GRAB)])


class ClampAndBulletTests(unittest.TestCase):
    def test_the_lane_word_is_held_at_0_with_its_fraction(self) -> None:
        m = _mr_x(primary=model.PRIMARY_GUN, sub=1, y=7.5, vy=-8.0)
        model.mr_x_update(m, _actor(100.0, 60.0))
        model.emit(m)
        self.assertEqual(m.y, 0.5)

    def test_a_bullet_fired_below_his_slot_is_set_up_a_pass_late(self) -> None:
        raw = bytearray(128)
        raw[0] = model.BULLET_TYPE
        raw[0x10:0x14] = (300 << 16).to_bytes(4, "big")
        raw[0x14:0x18] = int(2.5 * 65536).to_bytes(4, "big")
        raw[0x18:0x1C] = (FLOOR << 16).to_bytes(4, "big")
        raw[0x58] = 0
        raw[0x59] = 0
        b = BulletSim.from_bytes(bytes(raw), slot=2, cam_x=CAM)
        self.assertEqual((b.x, b.y, b.delay), (310.0, 34.5, 1))
        a = _actor(310.0, 34.0)  # right where it will be
        self.assertIs(model.bullet_update(b, a), Outcome.NONE)  # the set-up pass
        self.assertIs(model.bullet_update(b, a), Outcome.HIT)


class PlanTests(unittest.TestCase):
    def test_the_gun_is_walked_into_without_a_hit(self) -> None:
        m = _mr_x(primary=model.PRIMARY_GUN, sub=2, t54=21, x=300.0, y=model.GUN_LANE, anim=model.ANIM_GUN_UP)
        a = _actor(240.0, 20.0)
        bullets: list[BulletSim] = []
        memory = mr_x_plan.PlanMemory()
        for _ in range(60):
            p = mr_x_plan.plan(a, m, bullets, memory=memory)
            a.latch = 0
            model.actor_step(a, p.dir_x, p.dir_y, punch=p.punch)
            outcomes = model.object_pass(m, bullets, a)
            self.assertNotIn(Outcome.HIT, outcomes)
            if Outcome.GRAB in outcomes:
                return
        self.fail("no hold in 60 updates")

    def test_deciding_close_he_is_kept_out_of_reach_of_his_walk_in(self) -> None:
        # Within $80 he walks in, and the lunge follows; the plan backs off so
        # his decision reads the gun.
        m = _mr_x(x=300.0, t54=10)
        a = _actor(230.0, 60.0)
        p = mr_x_plan.plan(a, m, [])
        self.assertEqual(p.mode, "keep_away")
        self.assertLessEqual(p.dir_x, 0)

    def test_no_punch_that_can_miss(self) -> None:
        # Wherever the walk-in finds the actor, a punch the plan presses lands
        # under every timing a tick can land on (the rule the user set for the
        # twins' rear attack: "não quero que dê ataques em falso").
        punched = 0
        for gap_x in range(40, 140, 12):
            for gap_lane in (0, 10, 20, 30, 40):
                m = _mr_x(primary=model.PRIMARY_WALK_IN, sub=1, x=300.0, y=60.0, vx=-8.0, vy=8.0)
                a = _actor(300.0 - gap_x, 60.0 + gap_lane)
                if not mr_x_plan.plan(a, m, []).punch:
                    continue
                punched += 1
                press = mr_x_plan._Program((0, 0), 0, "punch@0", punch_at=0)
                for player_first, lead, overrun in mr_x_plan.SCENARIOS:
                    with self.subTest(gap_x=gap_x, gap_lane=gap_lane, lead=lead, player_first=player_first):
                        result = mr_x_plan._rollout(
                            m, [], a, press, player_first=player_first, lead=lead,
                            committed=(0, 0), overrun=overrun, horizon=mr_x_plan.HORIZON,
                        )
                        self.assertIs(result.now_struck, True)
        self.assertGreater(punched, 0)

    def test_nothing_to_punch_far_off(self) -> None:
        m = _mr_x(primary=model.PRIMARY_WALK_IN, sub=1, x=300.0, y=60.0, vx=-8.0, vy=8.0)
        self.assertFalse(mr_x_plan.plan(_actor(150.0, 100.0), m, []).punch)

    def test_a_punch_into_his_walk_in_lands_before_his_lunge(self) -> None:
        # On his lane 90 px out: the walk-in closes 8 an update and Blaze's
        # punch (18-68 px ahead) meets him before his lunge's first test.
        m = _mr_x(primary=model.PRIMARY_WALK_IN, sub=1, x=300.0, y=60.0, vx=-8.0, vy=8.0)
        a = _actor(210.0, 60.0)
        p = mr_x_plan.plan(a, m, [])
        self.assertNotEqual(p.outcome, "hit")


class HoldStepTests(unittest.TestCase):
    def _step(self, **kw) -> str:
        fields = dict(action_base=0x60, knees_in_chain=0, primary=model.PRIMARY_HELD, substate=1, health=50)
        fields.update(kw)
        return mr_x_plan.hold_step(**fields)

    def test_knee_knee_release_each_on_his_read(self) -> None:
        self.assertEqual(self._step(), "knee")
        self.assertEqual(self._step(knees_in_chain=1), "knee")
        self.assertEqual(self._step(knees_in_chain=2), "release")
        self.assertEqual(self._step(substate=3), "wait")  # the shake a knee buys
        self.assertEqual(self._step(substate=0), "wait")  # stood back in front

    def test_the_last_knee_kills(self) -> None:
        self.assertEqual(self._step(knees_in_chain=2, health=2), "knee")

    def test_a_back_hold_is_released_unless_the_suplex_kills(self) -> None:
        self.assertEqual(self._step(action_base=0x66, primary=model.PRIMARY_HELD_BACK), "release")
        self.assertEqual(
            self._step(action_base=0x66, primary=model.PRIMARY_HELD_BACK, health=5), "suplex"
        )


if __name__ == "__main__":
    unittest.main()
