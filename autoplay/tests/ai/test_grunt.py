"""The street enemies' ROM model (``grunt.py``) and the plan on it
(``grunt_plan.py``).

The models were checked field by field against lockstep recordings
(``tools/grunt_lab.py --check``: Garcia ``$21``/``$22`` 21,258 updates, Signal
5,164, HakuRo 4,727, Nora 3,790, every contact outcome but the terrain's);
these pin the facts the plan rests on.
"""

import unittest

from sor_autoplay.ai import grunt as model
from sor_autoplay.ai import grunt_plan
from sor_autoplay.ai.grunt import GruntSim, Outcome
from sor_autoplay.ai.twins import BLAZE, ActorSim

CAM = 128
FLOOR = 160


def _grunt(type_id: int, state: int, **overrides) -> GruntSim:
    fields = dict(
        slot=0, type=type_id, x=400.0, y=60.0, z=float(FLOOR), vx=0.0, vy=0.0, vz=0.0,
        state=state, flags=0, t50=0, t51=0, t52=0, f48=0, aim_x=0, aim_y=0, speed=0x480,
        off_x=0x20, off_y=0, anim=0, frame=0, countdown=1, reload=5, animating=True,
        attack_id=0, body_id=0x01, hp=9, param=0, screen_x=0, cam_x=CAM, alive=True,
        repeats=0, damage=8, w54=0, armed=False, level=0, floor=float(FLOOR),
        last_frame_tick=0, rng=5,
    )
    fields.update(overrides)
    g = GruntSim(**fields)
    g.screen_x = int(g.x) - CAM + model.SCREEN_BIAS
    return g


def _actor(x: float, y: float, *, facing_left: bool = False, weapon: int = 0) -> ActorSim:
    a = ActorSim.standing(x=x, y=y, z=FLOOR, facing_left=facing_left, character=BLAZE, cam_x=CAM)
    a.punch = None
    a.action = 0x02
    a.weapon = weapon
    return a


def _run(g: GruntSim, a: ActorSim, updates: int, stick=(0, 0), punch_at=None):
    events = []
    for k in range(updates):
        a.latch = 0
        grunt_plan.actor_step(a, *stick, punch=(k == punch_at))
        out = model.grunt_update(g, a)
        if out is not Outcome.NONE:
            events.append((k, out))
    return events


class GarciaJabTests(unittest.TestCase):
    def test_walking_in_along_his_lane_is_his_jab_first(self) -> None:
        # $E102: box $12 (0-40 ahead) meets the actor's body before the
        # walking box (0-19 ahead) meets his -- the punch's first frame is
        # already the jab.
        g = _grunt(model.GARCIA, 0x09, x=320.0, y=60.0)
        a = _actor(250.0, 60.0)
        events = _run(g, a, 20, stick=(1, 0))
        self.assertEqual(events[0][1], Outcome.HIT)

    def test_his_band_is_16_lanes_either_way(self) -> None:
        g = _grunt(model.GARCIA, 0x09, x=300.0, y=60.0)
        near = _actor(270.0, 76.0)
        self.assertTrue(model._trigger(g, near, 0x13))
        far = _actor(270.0, 77.0)
        self.assertFalse(model._trigger(g, far, 0x13))

    def test_a_walking_box_on_his_body_in_hitstun_is_the_hold(self) -> None:
        g = _grunt(model.GARCIA, model.ST_HITSTUN, flags=0x03, t50=20, x=270.0, y=60.0, anim=0x08)
        a = _actor(250.0, 60.0)
        events = _run(g, a, 4, stick=(1, 0))
        self.assertEqual(events[0][1], Outcome.GRAB)
        self.assertEqual(g.state, model.ST_HELD)


class RefusedHoldTests(unittest.TestCase):
    def test_a_body_behind_the_actors_origin_facing_its_way_is_no_hold(self) -> None:
        # $3266: the round-1 loop of 60 s -- a Nora 3 px behind the actor's
        # origin, both facing right, "grabbed" every other update and let go.
        a = _actor(300.0, 60.0)
        behind = _grunt(model.NORA, 0x09, x=297.0, y=60.0, anim=0x00)
        self.assertFalse(model.takes_hold(a, behind))
        facing = _grunt(model.NORA, 0x09, x=297.0, y=60.0, anim=0x02)
        self.assertTrue(model.takes_hold(a, facing))
        ahead = _grunt(model.NORA, 0x09, x=305.0, y=60.0, anim=0x00)
        self.assertTrue(model.takes_hold(a, ahead))

    def test_refused_he_resets_the_next_update(self) -> None:
        g = _grunt(model.GARCIA, model.ST_HITSTUN, flags=0x03, t50=20, x=297.0, y=60.0, anim=0x08)
        a = _actor(300.0, 60.0)
        a.walking = True
        grunt_plan.refresh_boxes(a, a.x, a.y)
        out = model.grunt_update(g, a)
        self.assertIs(out, Outcome.GRAB)
        self.assertEqual(g.state, model.ST_HELD)
        model.grunt_update(g, _actor(300.0, 60.0))
        self.assertEqual(g.state, model.ST_RESELECT)


class KnifeTests(unittest.TestCase):
    """The user's report: an armed Garcia hurts by touching."""

    def test_the_entry_run_carries_his_whole_body_as_a_box(self) -> None:
        g = _grunt(model.GARCIA_KNIFE, 0x0C, x=330.0, y=60.0)
        a = _actor(250.0, 60.0)
        events = _run(g, a, 20)
        self.assertEqual(g.anim & ~model.ANIM_MIRROR, 0x38)
        self.assertEqual(events[0][1], Outcome.HIT)
        self.assertEqual(model.GARCIA_ANIMS[0x38][1][0][0], 0x01)

    def test_walking_into_him_facing_him_takes_the_hold_first(self) -> None:
        # $AAA0 tests the actor's walking box on his body before his box on
        # the actor's: the one input that beats the run standing on its line.
        g = _grunt(model.GARCIA_KNIFE, 0x0C, x=330.0, y=60.0)
        a = _actor(250.0, 60.0)
        events = _run(g, a, 20, stick=(1, 0))
        self.assertEqual(events[0][1], Outcome.GRAB)

    def test_off_his_line_the_run_goes_by(self) -> None:
        g = _grunt(model.GARCIA_KNIFE, 0x0C, x=330.0, y=60.0)
        a = _actor(250.0, 80.0)
        g.flags |= 0x01
        g.vx, g.vy = -5.0, 0.0  # set on entry toward the actor's old spot
        events = _run(g, a, 30)
        self.assertFalse(any(out is Outcome.HIT for _, out in events))


class ThrownKnifeTests(unittest.TestCase):
    def test_beyond_96_px_on_his_lane_he_throws_it(self) -> None:
        # $D7BE: after 24 updates, within 16 lanes and 96 px or more away, the
        # throw ($D8EC); frame 1 lets the knife go.
        g = _grunt(model.GARCIA_KNIFE, 0x08, x=400.0, y=60.0, anim=0x1E, armed=True)
        a = _actor(280.0, 60.0)
        seen = []
        for _ in range(60):
            a.latch = 0
            model.grunt_update(g, a)
            if g.thrown is not None:
                seen.append(g.thrown)
                g.thrown = None
        self.assertEqual(len(seen), 1)
        self.assertLess(seen[0].vx, 0)

    def test_the_flying_knife_reaches_20_lanes_off_its_own(self) -> None:
        a = _actor(250.0, 60.0)
        k = model.KnifeSim(x=300.0, y=84.0, z=FLOOR - 38.0, vx=-16.0)
        hits = [model.knife_update(k, a, CAM) for _ in range(6)]
        self.assertIn(Outcome.HIT, hits)
        far = model.KnifeSim(x=300.0, y=90.0, z=FLOOR - 38.0, vx=-16.0)
        self.assertNotIn(Outcome.HIT, [model.knife_update(far, _actor(250.0, 60.0), CAM) for _ in range(6)])

    def test_an_enemy_knife_in_flight_is_told_from_the_actors(self) -> None:
        data = bytearray(0x80)
        data[0x00] = model.KNIFE_TYPE
        data[0x30] = model.KNIFE_FLYING
        data[0x1C:0x20] = (-16 * 65536).to_bytes(4, "big", signed=True)
        data[0x52:0x54] = (0xB900).to_bytes(2, "big")
        self.assertTrue(model.is_enemy_knife_in_flight(bytes(data)))
        data[0x52:0x54] = (0xB800).to_bytes(2, "big")  # P1 threw it
        self.assertFalse(model.is_enemy_knife_in_flight(bytes(data)))


class SignalTests(unittest.TestCase):
    def test_his_touch_is_his_hold_on_the_actor(self) -> None:
        g = _grunt(model.SIGNAL, 0x09, x=290.0, y=60.0, anim=0x02, speed=0x380, attack_id=0x3D)
        a = _actor(284.0, 60.0, facing_left=True)
        out = model.grunt_update(g, a)
        self.assertIs(out, Outcome.SEIZED)
        self.assertEqual(g.state, 0x0C)


class NoraTests(unittest.TestCase):
    def test_inside_32_px_the_whip_cannot_land(self) -> None:
        g = _grunt(model.NORA, 0x08, x=280.0, y=60.0, anim=0x02)
        a = _actor(260.0, 60.0)
        self.assertFalse(model._trigger(g, a, 0x23))

    def test_the_lash_is_frame_2_of_its_animation(self) -> None:
        g = _grunt(model.NORA, 0x08, x=320.0, y=60.0, anim=0x02, flags=0x01, t51=0x50, speed=0x180)
        a = _actor(260.0, 60.0)
        events = _run(g, a, 20)
        self.assertEqual(events[0][1], Outcome.HIT)
        self.assertGreaterEqual(events[0][0], 10)


class HakuRoTests(unittest.TestCase):
    def test_the_dash_turns_into_the_strike_at_44_px(self) -> None:
        # Level with him within 72 px it is the jump kick ($0D), and the
        # strike's box $06 on the actor's body the strike ($0A).
        g = _grunt(model.HAKURO, 0x0E, x=380.0, y=60.0, anim=0x02, param=0)
        a = _actor(250.0, 60.0)
        seen = set()
        for _ in range(40):
            a.latch = 0
            model.grunt_update(g, a)
            seen.add(g.state)
        self.assertTrue(seen & {0x0A, 0x0D})


class WeaponTests(unittest.TestCase):
    def test_the_pipe_knocks_him_down_before_his_jab(self) -> None:
        # The swung weapon is a registered attacker: $AA34 tests it first.
        g = _grunt(model.GARCIA, 0x07, flags=0x03, t50=5, x=320.0, y=60.0)
        a = _actor(250.0, 60.0, weapon=grunt_plan.PIPE)
        events = _run(g, a, 8, punch_at=0)
        self.assertEqual(events[0], (4, Outcome.KNOCKED))
        self.assertIn(g.state, (model.ST_KNOCKDOWN, model.ST_DYING))


class ObservationTests(unittest.TestCase):
    def test_every_modelled_type_keeps_its_raw_slot(self) -> None:
        # Without it the plan never saw a Signal, a HakuRo or a Nora live: the
        # map kept raw bytes for Mr. X and the Garcias alone.
        from sor_autoplay.world_map import RAW_SLOT_TYPES

        self.assertLessEqual(model.MODELLED_TYPES, RAW_SLOT_TYPES)
        self.assertIn(model.KNIFE_TYPE, RAW_SLOT_TYPES)


class EntryTests(unittest.TestCase):
    def test_a_ride_in_is_no_fight_to_wait_on(self) -> None:
        a = _actor(250.0, 60.0)
        g = _grunt(model.GARCIA, 0x13, x=300.0, y=60.0)
        self.assertEqual(grunt_plan.relevant(a, [g]), [])
        self.assertIsNone(grunt_plan.plan(a, [g]))

    def test_lying_in_wait_is_part_of_the_fight(self) -> None:
        a = _actor(250.0, 60.0)
        g = _grunt(model.GARCIA, model.LYING_IN_WAIT, x=300.0, y=60.0, anim=0x04, frame=3, body_id=0)
        self.assertEqual(grunt_plan.relevant(a, [g]), [g])
        self.assertIs(grunt_plan.pick_target(a, [g]), g)

    def test_he_gets_up_within_80_px(self) -> None:
        g = _grunt(model.GARCIA, model.LYING_IN_WAIT, x=300.0, y=60.0, flags=0x01, t50=0x60)
        model.grunt_update(g, _actor(200.0, 60.0))
        self.assertEqual(g.state, model.LYING_IN_WAIT)
        model.grunt_update(g, _actor(230.0, 60.0))
        self.assertEqual(g.state, model.ST_RESELECT)


class PlanTests(unittest.TestCase):
    def test_no_walk_into_an_approaching_garcias_jab(self) -> None:
        # The user: "a IA desloca-se para o alcance de um inimigo sem pensar
        # que o inimigo vai lhe dar um murro logo que estiver ao alcance".
        g = _grunt(model.GARCIA, 0x09, flags=0x01, t50=40, x=340.0, y=60.0, anim=0x02, speed=0x480)
        a = _actor(250.0, 60.0)
        trace: list = []
        plan = grunt_plan.plan(a, [g], budget_ms=None, trace=trace)
        self.assertIsNotNone(plan)
        self.assertNotEqual(plan.outcome, "hit")
        # Walking straight in along his lane is his jab under every timing.
        straight = [row for row in trace if row[0] == "(1, 0)x12"]
        self.assertTrue(straight and all(row[5] is not None for row in straight))

    def test_a_stunned_garcia_in_reach_is_taken(self) -> None:
        g = _grunt(model.GARCIA, model.ST_HITSTUN, flags=0x03, t50=20, x=275.0, y=60.0, anim=0x08)
        a = _actor(250.0, 60.0)
        plan = grunt_plan.plan(a, [g], budget_ms=None)
        self.assertIn(plan.outcome, ("grab", "struck"))

    def test_no_punch_through_the_partner(self) -> None:
        # Never hurt the partner (user): a Garcia in hitstun in the punch's
        # reach, the partner standing in it too.
        g = _grunt(model.GARCIA, model.ST_HITSTUN, flags=0x03, t50=20, x=300.0, y=60.0, anim=0x08)
        a = _actor(250.0, 60.0)
        a.partner_body = (270, 290, 52, 68, 100, 160)
        plan = grunt_plan.plan(a, [g], budget_ms=None)
        self.assertFalse(plan.punch or plan.chord)

    def test_the_partners_fight_is_not_a_target(self) -> None:
        g = _grunt(model.GARCIA, 0x07, x=300.0, y=60.0)
        a = _actor(250.0, 60.0)
        a.spared = frozenset({g.slot})
        self.assertIsNone(grunt_plan.pick_target(a, [g]))

    def test_the_rear_attack_is_offered_turned_onto_a_near_enemy(self) -> None:
        # The user: "usar um back-attack, que é rápido e tem mais range".
        g = _grunt(model.GARCIA, 0x09, flags=0x01, t50=40, x=330.0, y=60.0, anim=0x02)
        a = _actor(250.0, 60.0)
        labels = [p.label for p in grunt_plan._programs(a, [g], True, True)]
        self.assertIn("turn-1x1+chord", labels)
        # ...and the strikes come before the sticks, so a budget cut drops sticks.
        self.assertLess(labels.index("punch@0"), labels.index("(0, 0)x2"))

    def test_a_hit_only_when_the_tick_is_two_updates_late_is_no_veto(self) -> None:
        self.assertIn((False, 2, False), grunt_plan.SOFT_SCENARIOS)
        self.assertGreater(grunt_plan.SOFT_FLOOR, grunt_plan.HIT_SCORE / 2)
        self.assertLess(grunt_plan.SOFT_FLOOR, grunt_plan.BURNT_HOLD_SCORE)

    def test_with_nobody_on_screen_the_tail_heads_for_its_middle(self) -> None:
        # A Garcia off screen pinned below the lift's X bound, out of every
        # strike's reach: standing at the clamp waiting for him was a deadlock.
        a = _actor(CAM + 0x20, 60.0)
        g = _grunt(model.GARCIA_KNIFE, 0x0D, x=CAM - 16.0, y=60.0, anim=0x1E)
        self.assertEqual(grunt_plan.tail_action(a, [g], None)[0], 1)

    def test_a_punch_stands_blazes_body_forward(self) -> None:
        a = _actor(250.0, 60.0)
        grunt_plan.actor_step(a, 0, 0, punch=True)
        grunt_plan.actor_step(a, 0, 0)
        grunt_plan.actor_step(a, 0, 0)
        grunt_plan.actor_step(a, 0, 0)  # the live frame
        self.assertEqual((a.body[0], a.body[1]), (250 + 19, 250 + 29))

    def test_a_kept_walk_into_the_camera_clamp_ends(self) -> None:
        # `$43AA` clamps the whole pixel and keeps the fraction: a kept walk
        # at a point computed at the clamp never arrived, and STICKY held it
        # 50 s in round 2's bottom-left corner.
        memory = grunt_plan.PlanMemory()
        a = _actor(CAM + 0x20 + 0.5, 60.0)
        memory.program = grunt_plan._Program((-1, 0), 12, "(-1, 0)x12", target=(float(CAM + 0x20), 60.0))
        self.assertIsNone(grunt_plan._kept(memory, a))
        # Away from the clamp it is kept.
        a = _actor(300.0, 60.0)
        memory.program = grunt_plan._Program((-1, 0), 12, "(-1, 0)x12", target=(260.0, 60.0))
        memory.pos = None
        self.assertIsNotNone(grunt_plan._kept(memory, a))

    def test_a_kept_walk_that_does_not_move_ends(self) -> None:
        memory = grunt_plan.PlanMemory()
        a = _actor(300.0, 60.0)
        memory.program = grunt_plan._Program((1, 0), 12, "(1, 0)x12", target=(340.0, 60.0))
        memory.pos = (300.0, 60.0)
        self.assertIsNotNone(grunt_plan._kept(memory, a))  # one tick can land inside an update
        self.assertIsNone(grunt_plan._kept(memory, a))  # a prop's wall undoing every step

    def test_solids_undo_the_step(self) -> None:
        a = _actor(250.0, 60.0)
        a.solids = ((240.0, 260.0, 50.0, 59.0),)
        grunt_plan.actor_step(a, 0, -1)
        self.assertEqual(a.y, 60.0)


if __name__ == "__main__":
    unittest.main()
