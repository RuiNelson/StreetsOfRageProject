"""The type-``$22`` Garcia's ROM model (``garcia.py``) -- Mr. X's helpers.

Checked field by field against the Garcias of two lockstep recordings
(``garcia.check_recording``: 3,488 of their updates, three off -- two when
the target died); these pin the facts ``mr_x_plan`` rests on.
"""

import unittest

from sor_autoplay.ai import garcia as model
from sor_autoplay.ai import mr_x
from sor_autoplay.ai import mr_x_plan
from sor_autoplay.ai.garcia import GarciaSim, Outcome
from sor_autoplay.ai.twins import BLAZE, ActorSim

CAM = 128
FLOOR = mr_x.FLOOR_ROUND_8


def _garcia(**overrides) -> GarciaSim:
    fields = dict(
        slot=0, x=400.0, y=60.0, z=float(FLOOR), vx=0.0, vy=0.0, state=model.ST_APPROACH,
        flags=0, t50=0, aim_x=0, aim_y=0, speed=model.APPROACH_SPEED, anim=model.ANIM_WALK,
        frame=0, countdown=1, reload=3, animating=True, attack_id=0, body_id=0x01, hp=9,
        param=0, screen_x=0, cam_x=CAM, alive=True, repeats=0,
    )
    fields.update(overrides)
    g = GarciaSim(**fields)
    g.screen_x = int(g.x) - CAM + model.SCREEN_BIAS
    return g


def _actor(x: float, y: float, *, facing_left: bool = False) -> ActorSim:
    a = ActorSim.standing(x=x, y=y, z=FLOOR, facing_left=facing_left, character=BLAZE, cam_x=CAM)
    a.punch = None
    return a


def _run(g: GarciaSim, a: ActorSim, updates: int, stick=(0, 0), punch_at=None):
    events = []
    for k in range(updates):
        a.latch = 0
        mr_x.actor_step(a, *stick, punch=(k == punch_at))
        out = model.garcia_update(g, a)
        if out is not Outcome.NONE:
            events.append((k, out))
    return events


class ApproachTests(unittest.TestCase):
    def test_he_walks_at_the_point_32_px_short_at_4_5(self) -> None:
        g = _garcia(x=400.0, y=60.0)
        a = _actor(250.0, 60.0)
        _run(g, a, 2)
        self.assertEqual(g.aim_x, 250 + model.APPROACH_OFFSET)
        self.assertAlmostEqual(g.vx, -4.5)

    def test_the_jab_lands_the_update_after_its_trigger(self) -> None:
        # Walking in, box $12 (0-40 ahead) on the actor's body turns him to
        # the punch; the punch's entry latches the jab and it lands at once.
        g = _garcia(x=320.0, y=60.0)
        a = _actor(250.0, 60.0)
        events = _run(g, a, 12)
        self.assertEqual(g.state, model.ST_PUNCH)
        first_hit = events[0]
        self.assertIs(first_hit[1], Outcome.HIT)
        trigger_gap = abs(g.x - a.x)
        self.assertLessEqual(trigger_gap, 40 + 12)


class PunchTests(unittest.TestCase):
    def test_out_of_the_second_stage_it_ends_on_frame_6(self) -> None:
        g = _garcia(state=model.ST_PUNCH, flags=0, x=300.0, y=60.0)
        a = _actor(200.0, 60.0)  # 100 px: nothing reaches
        states = []
        for _ in range(30):
            model.garcia_update(g, a)
            states.append((g.state, g.frame))
        ended = next(i for i, (st, _) in enumerate(states) if st == model.ST_RESELECT)
        self.assertEqual(states[ended - 1], (model.ST_PUNCH, 6))


class EvadeTests(unittest.TestCase):
    def test_away_from_the_targets_half_of_the_street(self) -> None:
        g = _garcia(state=model.ST_EVADE, x=300.0, y=60.0)
        _run(g, _actor(250.0, 20.0), 1)
        self.assertGreater(g.vy, 0)  # target in the top half: he goes down
        g = _garcia(state=model.ST_EVADE, x=300.0, y=60.0)
        _run(g, _actor(250.0, 90.0), 1)
        self.assertLess(g.vy, 0)


class StrikeFirstTests(unittest.TestCase):
    def test_blazes_punch_out_reaches_his_jab(self) -> None:
        # He walks in at 4.5 px an update; Blaze's punch (18-68 px, live 3-7
        # updates after the press) meets him before his box $12 meets her.
        g = _garcia(x=330.0, y=60.0)
        a = _actor(250.0, 60.0)
        events = _run(g, a, 12, punch_at=0)
        self.assertIs(events[0][1], Outcome.STRUCK)


class ThreatTests(unittest.TestCase):
    def test_from_behind_his_jab_still_reaches_her(self) -> None:
        # He stops 32 px short of her origin and the jab reaches 40 past his:
        # her body (2-12 ahead of hers) is in it from behind as well -- 68 px
        # at 4.5 an update, then the trigger and the jab.
        a = _actor(300.0, 60.0, facing_left=False)
        threat = mr_x_plan.garcia_threat(a, [_garcia(x=200.0, y=60.0)])
        self.assertIsNotNone(threat)
        eta, behind = threat
        self.assertTrue(behind)
        self.assertEqual(eta, 14)

    def test_a_garcia_walking_up_behind_a_holder_is_flagged(self) -> None:
        a = _actor(300.0, 60.0, facing_left=True)  # facing left, back to the right
        g = _garcia(x=400.0, y=60.0)
        threat = mr_x_plan.garcia_threat(a, [g], updates=20)
        self.assertIsNotNone(threat)
        eta, behind = threat
        self.assertTrue(behind)
        self.assertGreater(eta, 5)


class BurntGrabTests(unittest.TestCase):
    def _walk_into_his_gun(self, garcias) -> mr_x_plan._Result:
        m = mr_x.MrXSim(
            slot=4, x=300.0, y=mr_x.GUN_LANE, z=float(FLOOR), vx=0.0, vy=0.0, vz=0.0, acc=0.0, grav=0.0,
            shake=0, primary=mr_x.PRIMARY_GUN, sub=2, t54=21, t56=0, anim=mr_x.ANIM_GUN_UP, frame=0,
            last_frame=0xFF, flags1=0, f37=0, hp=50, damage=34, screen_x=0, cam_x=CAM, floor=FLOOR,
            attack_id=0, body_id=0x38, latch=0, gone=False,
        )
        mr_x.emit(m)
        a = _actor(284.0, mr_x.GUN_LANE)
        walk = mr_x_plan._Program((1, 0), 8, "walk in")
        return mr_x_plan._rollout(
            m, [], a, walk, player_first=True, lead=0, committed=(0, 0), overrun=False,
            horizon=mr_x_plan.HORIZON, garcias0=garcias,
        )

    def test_alone_the_walk_into_his_gun_is_the_hold(self) -> None:
        self.assertIsNotNone(self._walk_into_his_gun([]).grab_at)

    def test_with_a_garcia_walking_up_behind_it_is_burnt(self) -> None:
        # His walk from 90 px behind reaches the holder ~13 updates after the
        # grab: time to let go, none to spend a knee (HOLD_KNEE_SAFE_UPDATES).
        result = self._walk_into_his_gun([_garcia(x=195.0, y=mr_x.GUN_LANE + 2)])
        self.assertIsNone(result.grab_at)
        self.assertIsNone(result.hit_at)
        self.assertIsNotNone(result.burnt_at)
        self.assertLess(mr_x_plan._score(result), 0)


if __name__ == "__main__":
    unittest.main()
