"""Onihime and Yasha's ROM model (``twins.py``) and the plan on it
(``twins_plan.py``).

The model was checked field by field against lockstep recordings
(``tools/twins_lab.py --check``: every twin update of four runs, no field off
bar the held throw and the respawn knock-back it does not replay); these pin
the facts the plan rests on, each as the ROM plays it.
"""

import unittest

from sor_autoplay.ai import twins as model
from sor_autoplay.ai import twins_plan
from sor_autoplay.ai.twins import ActorSim, Outcome, TwinSim

CAM = 5056
EDGE = CAM + model.PLAYER_X_MAX_OFFSET  # the right edge: 5344
GROUND = 160.0


def _twin(**overrides) -> TwinSim:
    fields = dict(
        slot=0, x=5200.0, y=60.0, z=GROUND, vx=0.0, vy=0.0, vz=0.0, ground=GROUND,
        primary=model.PRIMARY_ACTIVE, tac=0, t78=0, anim=0, frame=0, countdown=0, reload=0,
        shown_attack=0x8F, shown_body=0x4F, screen_x=0, cam_x=CAM, mode=0, toggle=0, role=1,
        unavailable=0, f4b=0, pending=0, f37=0, r62=0, r63=0, f66=0, f6d=0, hp=32,
        left=False, above=False, d50=0, d52=0, partner=None, gone=False,
    )
    fields.update(overrides)
    t = TwinSim(**fields)
    model.emit(t)  # latch the boxes and +$28 as the renderer would have
    return t


def _grabber(x: float, y: float = 60.0, **overrides) -> TwinSim:
    fields = dict(
        slot=1, x=x, y=y, role=2, mode=model.MODE_GRAB_BIT, tac=1,
        anim=model.ANIM_WALK, reload=5, countdown=5, shown_attack=0x8F, shown_body=0x51,
    )
    fields.update(overrides)
    return _twin(**fields)


def _actor(x: float = EDGE, y: float = 60.0, *, facing_left: bool = False, character: int = model.BLAZE) -> ActorSim:
    return ActorSim.standing(x=x, y=y, z=int(GROUND), facing_left=facing_left, character=character, cam_x=CAM)


def _play(twins, a, updates: int, stick=(0, 0), chord_at=None):
    """Player update, then the object pass, ``updates`` times."""

    events = []
    model.link_pair(twins)
    for k in range(updates):
        model.actor_update(a, *stick, chord=(chord_at == k))
        for t, outcome in zip(twins, model.object_pass(twins, a)):
            if outcome is not Outcome.NONE:
                events.append((k, t.slot, outcome))
    return events


class ApproachTwinTests(unittest.TestCase):
    """Role 1 never walks into anyone: a backflip inside 96 px, a flying kick
    from 16-31 lanes off inside 112."""

    def test_inside_96_px_it_backflips_away(self) -> None:
        a = _actor(EDGE, 60.0)
        t = _twin(x=EDGE - 80.0, y=60.0)
        _play([t], a, 1)
        self.assertEqual((t.tac, t.anim & ~model.ANIM_MIRROR), (2, model.ANIM_FLIP))
        _play([t], a, 26)
        self.assertEqual(t.primary, model.PRIMARY_ACTIVE)
        self.assertAlmostEqual(t.x, EDGE - 80.0 - 84.0)  # 21 updates at 4 px, away

    def test_the_flying_kick_commits_from_the_walk_and_flies_28_updates(self) -> None:
        a = _actor(EDGE, 60.0)
        t = _twin(x=EDGE - 110.0, y=40.0, tac=1, anim=model.ANIM_WALK, reload=5, countdown=5)
        _play([t], a, 1)
        self.assertEqual((t.primary, t.t78), (model.PRIMARY_COMMIT, 9))
        _play([t], a, 1)  # the launch: +$78 reaches $0A
        self.assertAlmostEqual(t.vx, model.KICK_SPEED)
        self.assertAlmostEqual(t.vy, 20 / 16)
        start = t.x - t.vx
        flight = 1
        while t.z < GROUND:
            _play([t], a, 1)
            flight += 1
        self.assertEqual(flight, 28)
        self.assertAlmostEqual(t.x - start, 28 * model.KICK_SPEED, places=3)

    def test_on_its_lane_it_never_commits(self) -> None:
        a = _actor(EDGE, 60.0)
        t = _twin(x=EDGE - 104.0, y=52.0, tac=1, anim=model.ANIM_WALK, reload=5, countdown=5)
        _play([t], a, 1)
        self.assertEqual(t.primary, model.PRIMARY_ACTIVE)

    def test_its_box_in_state_1_is_no_hit(self) -> None:
        # $159F8 clears the target's +$7C: the idle's $8F box on the actor.
        a = _actor(EDGE, 60.0, facing_left=True)
        t = _twin(x=EDGE - 10.0, y=60.0, tac=0, t78=0)
        self.assertEqual(model.twin_update(t, a), Outcome.NONE)


class GrabTwinTests(unittest.TestCase):
    """Role 2 walks in at 2 px an update, and jumps only at a target that
    faces it."""

    def test_it_walks_into_a_turned_back(self) -> None:
        a = _actor(EDGE, 60.0, facing_left=False)
        t = _grabber(EDGE - 100.0, 60.0)
        _play([t], a, 10)
        self.assertEqual(t.tac, 1)
        self.assertAlmostEqual(t.x, EDGE - 80.0)

    def test_facing_it_inside_64_px_is_its_jump_in(self) -> None:
        a = _actor(EDGE, 60.0, facing_left=True)
        t = _grabber(EDGE - 60.0, 60.0)
        _play([t], a, 1)
        self.assertEqual((t.tac, t.anim & ~model.ANIM_MIRROR), (2, model.ANIM_JUMP_IN))

    def test_its_walking_box_on_the_body_is_the_grab(self) -> None:
        a = _actor(EDGE, 60.0, facing_left=False)
        t = _grabber(EDGE - 40.0, 60.0)
        events = _play([t], a, 20)
        self.assertEqual(events[0][2], Outcome.GRABBED)
        # Blaze's idle body faces away (+2..+12): the box ($8F, 0..19) reaches
        # it from 17 px; walking in 2 px at a time it is there at 16.
        self.assertAlmostEqual(a.x - t.x, 16.0)


class RearAttackTests(unittest.TestCase):
    def test_schedules(self) -> None:
        self.assertEqual(model.chord_live_steps(model.BLAZE), (3, 10))
        self.assertEqual(model.chord_live_steps(model.AXEL), (1, 5))
        self.assertEqual(model.chord_live_steps(model.ADAM), (10, 18))
        self.assertEqual([len(model.chord_schedule(c)) for c in (model.AXEL, model.ADAM, model.BLAZE)], [8, 24, 14])

    def test_adams_hop_is_the_measured_one(self) -> None:
        heights = [round(GROUND + h) for h in model._ADAM_HOP]
        self.assertEqual(heights[:6], [154, 148, 144, 140, 138, 136])

    def test_the_strike_beats_the_grab_and_knocks_it_down_90_px(self) -> None:
        a = _actor(EDGE, 60.0, facing_left=False)
        t = _grabber(EDGE - 70.0, 60.0)
        struck_at = None
        model.link_pair([t])
        for k in range(12):
            model.actor_update(a, 0, 0, chord=(k == 0))
            if model.object_pass([t], a) == [Outcome.STRUCK]:
                struck_at = t.x
                break
        self.assertIsNotNone(struck_at)
        # Damage lands on its next update, then 18 updates at 5 px away from
        # the actor ($17C36, $163D0): 90 px, 30 updates down and 8 getting up.
        _play([t], a, 1)
        updates = 1
        self.assertEqual(t.primary, model.PRIMARY_REACTION)
        while t.primary != model.PRIMARY_ACTIVE:
            _play([t], a, 1)
            updates += 1
        self.assertEqual(t.hp, 30)
        self.assertAlmostEqual(struck_at - t.x, 90.0)
        self.assertEqual(updates, 1 + 30 + 8)

    def test_a_chord_pressed_too_late_is_the_grab(self) -> None:
        a = _actor(EDGE, 60.0, facing_left=False)
        t = _grabber(EDGE - 26.0, 60.0)
        events = _play([t], a, 6, chord_at=0)
        # Blaze's body box moves behind her during the startup ($75/$76).
        self.assertEqual(events[0][2], Outcome.GRABBED)

    def test_the_clamp_keeps_the_fraction(self) -> None:
        a = _actor(EDGE - 1.0, 60.0)
        a.x += 0.75
        model.actor_update(a, 1, 0)
        self.assertEqual(model._hi(a.x), EDGE)
        self.assertAlmostEqual(a.x - EDGE, 0.0 + ((EDGE - 1.0 + 0.75 + 3.25) - (EDGE + 3)))


class PlanTests(unittest.TestCase):
    def test_the_grab_twin_is_put_behind(self) -> None:
        a = _actor(5200.0, 60.0)
        g = _grabber(5100.0)
        approach = _twin(x=5400.0)
        self.assertEqual(twins_plan.choose_wall(a, [approach, g]), 1)
        self.assertEqual(twins_plan.choose_wall(a, [approach, _grabber(5300.0)]), -1)

    def test_it_chords_the_grab_twin_as_it_walks_into_the_box(self) -> None:
        a = _actor(EDGE, 60.0)
        pressed = None
        g = _grabber(EDGE - 120.0, 60.0)
        twins = [g]
        model.link_pair(twins)
        for k in range(60):
            p = twins_plan.plan(a, twins, committed=(0, 0))
            model.actor_update(a, p.dir_x, p.dir_y, p.chord and a.chord is None)
            if p.chord and pressed is None:
                pressed = (k, a.x - g.x)
            outcomes = model.object_pass(twins, a)
            self.assertNotIn(Outcome.GRABBED, outcomes)
            if Outcome.STRUCK in outcomes:
                break
        self.assertIsNotNone(pressed)
        self.assertEqual(outcomes, [Outcome.STRUCK])
        # Blaze's box reaches 58 px behind her: pressed with the twin a few
        # updates out of it, so it walks into the box early in its life.
        self.assertGreater(pressed[1], 58)

    def test_no_chord_at_nothing(self) -> None:
        a = _actor(EDGE, 60.0)
        p = twins_plan.plan(a, [_grabber(EDGE - 200.0, 60.0)])
        self.assertFalse(p.chord)

    def test_a_chord_that_can_miss_is_never_pressed(self) -> None:
        # User: "não quero que dê ataques em falso". Found offline
        # (tools/twins_sim.py with the rule off: 9 whiffs in 38 chords): the
        # grab twin walking in 92 px behind a walking Blaze, the approach twin
        # getting up. A chord now lands on nothing under every timing -- her
        # box ends 53 px out -- and only the next one strikes; the plan
        # scored the pair above waiting. It is dropped, not scored down.
        a = _actor(EDGE, 96.5)
        a.walking = True
        model.refresh_boxes(a, a.x, a.y)
        base = dict(
            z=GROUND, vz=0.0, ground=GROUND, frame=0, cam_x=CAM, unavailable=0, pending=0, f37=0,
            r63=0, f66=0, f6d=0, hp=26, left=False, above=False, partner=None, gone=False,
        )
        getting_up = TwinSim(
            slot=0, x=5190.0, y=60.975, vx=0.0, vy=0.0, primary=5, tac=0, t78=34, anim=28,
            countdown=3, reload=10, shown_attack=0, shown_body=0, screen_x=262, mode=0,
            toggle=0, role=1, f4b=1, r62=2, d50=154, d52=13, **base,
        )
        walking_in = TwinSim(
            slot=1, x=5252.0, y=83.0, vx=2.0, vy=1.0, primary=model.PRIMARY_ACTIVE, tac=1,
            t78=0, anim=model.ANIM_WALK, countdown=2, reload=5, shown_attack=0x8F,
            shown_body=0x51, screen_x=324, mode=model.MODE_GRAB_BIT, toggle=0, role=2, f4b=0,
            r62=0, d50=94, d52=12, **base,
        )
        twins = [getting_up, walking_in]
        model.link_pair(twins)
        press_now = twins_plan._Program((0, 0), 0, 0, "chord")
        for player_first, lead, overrun in twins_plan.SCENARIOS:
            result = twins_plan._rollout(
                twins, a, press_now, 1, player_first=player_first, lead=lead,
                committed=(0, 1), overrun=overrun,
            )
            self.assertIs(result.now_struck, False)
            self.assertTrue(result.strikes)  # the next chord lands
        p = twins_plan.plan(a, twins, committed=(0, 1))
        self.assertFalse(p.chord)
        self.assertEqual(p.outcome, "strike")

    def test_a_flying_kick_is_never_taken(self) -> None:
        a = _actor(EDGE, 60.0)
        t = _twin(x=EDGE - 108.0, y=40.0, tac=1, anim=model.ANIM_WALK, reload=5, countdown=5)
        twins = [t]
        for _ in range(60):
            p = twins_plan.plan(a, twins, committed=(0, 0))
            model.actor_update(a, p.dir_x, p.dir_y, p.chord and a.chord is None)
            outcomes = model.object_pass(twins, a)
            self.assertNotIn(Outcome.HIT, outcomes)


if __name__ == "__main__":
    unittest.main()
