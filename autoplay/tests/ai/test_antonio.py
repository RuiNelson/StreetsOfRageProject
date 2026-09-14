"""The Antonio plan's ROM model and decisions (``ai/antonio.py``).

Every number here is the ROM's (``$16CE4`` onwards, and the shared later-boss
helpers ``$17924``-``$17D76``): the side-dependent kick gate, the dash window,
his lane keeping, the kick's frame-by-frame boxes, the contact order that makes
a grab beat his kick, and the lookahead built on all of it. The verb wiring is
``test_decide``/``test_priority``/``test_execute``'s.
"""

import unittest

from sor_autoplay.ai import antonio as plan
from sor_autoplay.ai.tokens import Antonio, CameraRange, Myself, Projectile
from sor_autoplay.memory_map import (
    PLAYER_CROSSOVER_SPENT_BIT,
    PLAYER_HIT_REACTION_BIT,
    PLAYER_KNEE_CHAIN_BIT,
)
from sor_autoplay.phases import CombatPhase

# Camera at world X 0: the walk clamp is 32..288 and his screen X is his
# world X plus the $80 bias.
CAMERA = CameraRange(left=32, right=288, top=0, bottom=112)
BLAZE = 2


def _actor(
    world_x: int,
    world_y: int,
    *,
    facing_left: bool = False,
    walking: bool = False,
    vel_x: float = 0.0,
    **overrides,
) -> Myself:
    action = (0x06 if walking else 0x02) | (1 if facing_left else 0)
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=BLAZE,
        character_name="Blaze",
        world_x=world_x,
        world_y=world_y,
        health=80,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=facing_left,
        combat_phase=CombatPhase.NORMAL,
        action_state=action,
        is_airborne=False,
        vel_x=vel_x,
    )
    fields.update(overrides)
    return Myself(**fields)


def _antonio(
    world_x: int = 200,
    world_y: int = 60,
    *,
    primary_state: int = 1,
    tactical: int = 0,
    facing_left: bool = True,
    **overrides,
) -> Antonio:
    mirror = 0x02 if facing_left else 0x00
    fields = dict(
        slot="obj09",
        type_id=0x56,
        world_x=world_x,
        world_y=world_y,
        health=24,
        combat_phase=CombatPhase.ATTACKING if primary_state == 2 else CombatPhase.NORMAL,
        targets_player=1,
        facing_left=facing_left,
        primary_state=primary_state,
        tactical=tactical,
        screen_x=world_x + 0x80,
        anim=mirror,
        anim_frame=0,
        anim_countdown=6,
        attack_box_id=0,
        body_box_id=0x77 if facing_left else 0x76,
    )
    fields.update(overrides)
    return Antonio(**fields)


def _kicking(world_x: int = 200, world_y: int = 60, *, frame: int = 3) -> Antonio:
    """On his kick, the frame ``frame`` latched (facing left, at the actor)."""

    attack, body = {1: (0x85, 0x7D), 2: (0x89, 0x7D), 3: (0x81, 0x7F)}[frame]
    return _antonio(
        world_x,
        world_y,
        primary_state=2,
        anim=plan.ANIM_KICK | plan.ANIM_MIRROR_BIT,
        anim_frame=frame,
        anim_countdown=plan.KICK_FRAME_UPDATES,
        attack_box_id=attack,
        body_box_id=body,
    )


def _sims(antonio: Antonio, actor: Myself) -> tuple[plan.BossSim, plan.ActorSim]:
    boss = plan.BossSim.from_token(antonio, cam_x=0)
    sim = plan.ActorSim.from_token(
        actor,
        lane_lo=float(plan.PLAYER_LANE_MIN),
        lane_hi=float(plan.PLAYER_LANE_MAX),
        x_lo=CAMERA.left,
        x_hi=CAMERA.right,
    )
    return boss, sim


class KickGateTests(unittest.TestCase):
    """``$16EAE``: the lane gate is 8 px above his lane and 16 level or below."""

    def test_above_his_lane_the_gate_is_eight_pixels(self) -> None:
        antonio = _antonio(200, 60)
        self.assertFalse(plan.kick_gate_open(antonio, _actor(160, 52)))
        self.assertTrue(plan.kick_gate_open(antonio, _actor(160, 53)))

    def test_level_or_below_the_gate_is_sixteen_pixels(self) -> None:
        antonio = _antonio(200, 60)
        self.assertTrue(plan.kick_gate_open(antonio, _actor(160, 60)))
        self.assertTrue(plan.kick_gate_open(antonio, _actor(160, 75)))
        self.assertFalse(plan.kick_gate_open(antonio, _actor(160, 76)))

    def test_the_x_window_follows_the_targets_own_velocity(self) -> None:
        antonio = _antonio(200, 60)
        # Walking into him (on his left, moving right): $78.
        self.assertTrue(plan.kick_gate_open(antonio, _actor(81, 60, vel_x=3.25)))
        self.assertFalse(plan.kick_gate_open(antonio, _actor(80, 60, vel_x=3.25)))
        # Walking away (on his left, moving left): $50.
        self.assertTrue(plan.kick_gate_open(antonio, _actor(121, 60, vel_x=-3.25)))
        self.assertFalse(plan.kick_gate_open(antonio, _actor(120, 60, vel_x=-3.25)))

    def test_standing_still_the_window_depends_on_the_side(self) -> None:
        antonio = _antonio(200, 60)
        # On his left, +$60 set and +$31 bit 1 clear: $50.
        self.assertTrue(plan.kick_gate_open(antonio, _actor(121, 60)))
        self.assertFalse(plan.kick_gate_open(antonio, _actor(120, 60)))
        # On his right: $68.
        self.assertTrue(plan.kick_gate_open(antonio, _actor(303, 60)))
        self.assertFalse(plan.kick_gate_open(antonio, _actor(304, 60)))

    def test_a_kick_on_its_frames_is_always_open(self) -> None:
        self.assertTrue(plan.kick_gate_open(_kicking(), _actor(10, 100)))

    def test_nothing_fires_while_he_is_held_or_the_target_unavailable(self) -> None:
        self.assertFalse(plan.kick_gate_open(_antonio(primary_state=4), _actor(170, 60)))
        self.assertFalse(plan.kick_gate_open(_antonio(target_unavailable=1), _actor(170, 60)))


class LaneKeepingTests(unittest.TestCase):
    """``$179AC`` (tactical 0) and ``$1797E`` (the dash)."""

    def test_he_keeps_a_target_below_him_eighteen_to_twenty_one_pixels_down(self) -> None:
        velocity = plan._backoff_lane_velocity
        self.assertEqual([velocity(d, False) for d in (40, 28, 24, 20, 12, 4)], [4, 2, 1, 0, -1, -4])

    def test_he_rushes_a_target_above_him(self) -> None:
        self.assertEqual(plan._backoff_lane_velocity(30, True), -4.0)

    def test_the_dash_homes_four_two_one_then_nothing(self) -> None:
        velocity = plan._dash_lane_velocity
        self.assertEqual([velocity(d, False) for d in (40, 20, 10, 6)], [4, 2, 1, 0])
        self.assertEqual(velocity(10, True), -1.0)

    def test_a_target_below_settles_just_outside_the_kick_gate(self) -> None:
        antonio = _antonio(200, 30, phase_timer=5)
        trace = plan.simulate(antonio, _actor(170, 60), [(0, 0)] * 12, camera=CAMERA)
        self.assertTrue(all(step[0] is plan.Outcome.NONE for step in trace))
        self.assertTrue(all(step[3] == plan.PRIMARY_ACTIVE for step in trace))
        self.assertTrue(18 <= 60 - trace[-1][2] <= 21)

    def test_a_target_above_him_inside_forty_pixels_is_rushed_and_kicked(self) -> None:
        antonio = _antonio(200, 60, phase_timer=5)
        trace = plan.simulate(antonio, _actor(170, 40), [(0, 0)] * 6, camera=CAMERA)
        self.assertEqual(trace[0][2], 56.0)
        self.assertIn(plan.PRIMARY_KICK, [step[3] for step in trace])


class DashAndScreenTests(unittest.TestCase):
    def test_the_dash_arms_inside_its_window_and_carries_him_four_pixels(self) -> None:
        boss, actor = _sims(_antonio(200, 60), _actor(120, 48))
        plan.boss_update(boss, actor)
        self.assertEqual(boss.tactical, 8)
        self.assertEqual(boss.x, 196.0)

    def test_off_screen_he_walks_back_in_and_skips_both_gates(self) -> None:
        antonio = _antonio(20, 60, screen_x=0x70)
        boss, actor = _sims(antonio, _actor(40, 60))
        plan.boss_update(boss, actor)
        self.assertEqual(boss.tactical, 9)
        self.assertEqual(boss.vx, plan.REENTRY_SPEED)
        self.assertEqual(boss.primary, plan.PRIMARY_ACTIVE)


class KickTimelineTests(unittest.TestCase):
    """``$171CC``: frame 1 on entry, three updates a frame, over as 8 comes up."""

    def test_the_boxes_the_kick_latches_update_by_update(self) -> None:
        boss, actor = _sims(_antonio(200, 60), _actor(170, 60))
        plan.boss_update(boss, actor)
        self.assertEqual(boss.primary, plan.PRIMARY_KICK)
        # Out of every box it throws, so the timeline runs through.
        actor.x = actor.box_x = 40.0
        shown = [boss.shown_attack]
        x_during = []
        for _ in range(20):
            plan.boss_update(boss, actor)
            shown.append(boss.shown_attack)
            x_during.append(boss.x)
        self.assertEqual(shown, [0x85] * 3 + [0x89] * 3 + [0x81] * 12 + [0] * 3)
        self.assertEqual(set(x_during), {200.0})  # he does not move while kicking
        plan.boss_update(boss, actor)
        self.assertEqual(boss.primary, plan.PRIMARY_ACTIVE)

    def test_a_walk_into_his_leaning_body_is_a_grab_and_not_a_hit(self) -> None:
        # Frames 3-6: body 14..40 px forward, kick 12..84. $AAA0 tests the
        # walking box against the body first.
        kicking = _kicking(200, 60, frame=3)
        boss, actor = _sims(kicking, _actor(150, 60, walking=True))
        self.assertIs(plan.contact(boss, actor, margin=False), plan.Outcome.GRAB)
        boss, actor = _sims(kicking, _actor(130, 60, walking=True))
        self.assertIs(plan.contact(boss, actor, margin=False), plan.Outcome.HIT)

    def test_a_still_actor_has_no_walking_box_to_grab_with(self) -> None:
        boss, actor = _sims(_kicking(200, 60, frame=3), _actor(150, 60))
        self.assertIs(plan.contact(boss, actor, margin=False), plan.Outcome.HIT)

    def test_an_actor_already_holding_collides_with_nothing(self) -> None:
        # The update after a re-grab: the actor is in its front hold while he
        # still shows kick frame 1 (measured in lockstep, tools/antonio_lab.py).
        holding = _actor(170, 60, action_state=0x61, held_enemy_slot="obj09")
        boss, actor = _sims(_kicking(200, 60, frame=1), holding)
        self.assertIs(plan.contact(boss, actor, margin=False), plan.Outcome.NONE)

    def test_lanes_sixteen_apart_still_touch(self) -> None:
        boss, actor = _sims(_kicking(200, 60, frame=3), _actor(150, 76, walking=True))
        self.assertIs(plan.contact(boss, actor, margin=False), plan.Outcome.GRAB)
        boss, actor = _sims(_kicking(200, 60, frame=3), _actor(150, 77, walking=True))
        self.assertIs(plan.contact(boss, actor, margin=False), plan.Outcome.NONE)


class TargetStateTests(unittest.TestCase):
    """``$179F8``, ``$AA34`` and ``$17CF2``: what the target's own bytes do.

    Each one was a mismatch the wander lab found (``tools/antonio_lab.py
    --actor wander``) before it was modelled.
    """

    def test_an_actor_in_a_hit_reaction_is_not_kicked_again(self) -> None:
        # Knocked down ($5C) inside the frame-3 box: +$59 bit 1, until the
        # floor landing, makes $AA34 skip the player.
        down = _actor(150, 60, action_state=0x5C, flags_59=PLAYER_HIT_REACTION_BIT)
        boss, actor = _sims(_kicking(200, 60, frame=3), down)
        self.assertIs(plan.contact(boss, actor, margin=False), plan.Outcome.NONE)

    def test_a_contact_code_not_yet_consumed_blocks_every_contact(self) -> None:
        boss, actor = _sims(_kicking(200, 60, frame=3), _actor(150, 60, contact_code=0x01))
        self.assertIs(plan.contact(boss, actor, margin=False), plan.Outcome.NONE)

    def test_his_gates_reread_the_target_rather_than_trust_plus_77(self) -> None:
        # +$77 left set by an earlier update: $179F8 clears it first.
        boss, actor = _sims(_antonio(200, 60, target_unavailable=1), _actor(120, 48))
        plan.boss_update(boss, actor)
        self.assertEqual(boss.tactical, 8)

    def test_a_target_in_actions_5a_to_5f_closes_both_gates(self) -> None:
        # The dash window of DashAndScreenTests, with the target getting up:
        # no dash, no back-off -- the lane approach, as the lab recorded.
        boss, actor = _sims(_antonio(200, 60), _actor(120, 48, action_state=0x5A))
        plan.boss_update(boss, actor)
        self.assertEqual(boss.tactical, 5)
        self.assertEqual(boss.primary, plan.PRIMARY_ACTIVE)

    def test_at_the_camera_clamp_the_boxes_stand_one_step_out(self) -> None:
        # $4140 caches the walking box before $43AA clamps the walk: pinned at
        # the left edge (32) and walking left, the box starts from 28.75.
        # His body (facing right, -14..15) ends at 11: the clamped box, from
        # 13, would miss it; the cached one, from 9, takes the hold.
        boss = _antonio(-4, 60, facing_left=False, body_box_id=0x76)
        pinned = _actor(32, 60, facing_left=True, walking=True, vel_x=-3.25)
        self.assertIs(plan.contact(*_sims(boss, pinned), margin=False), plan.Outcome.GRAB)
        free = _actor(33, 60, facing_left=True, walking=True, vel_x=-3.25)
        self.assertIs(plan.contact(*_sims(boss, free), margin=False), plan.Outcome.NONE)

    def test_at_the_top_of_the_street_the_boxes_stand_one_step_up(self) -> None:
        # The same for $43AA's lane clamp (measured in the lab): walking
        # up-left into lane 2, 16 lanes above him, the box was cached a step
        # higher -- 18 away, so no hold. Not walking into the clamp, 16
        # still touches.
        boss = _antonio(200, 18, body_box_id=0x77)
        pinned = _actor(190, 2, facing_left=True, walking=True, vel_x=-3.25, vel_lane=-1.625)
        self.assertIs(plan.contact(*_sims(boss, pinned), margin=False), plan.Outcome.NONE)
        free = _actor(190, 2, facing_left=True, walking=True, vel_x=-3.25)
        self.assertIs(plan.contact(*_sims(boss, free), margin=False), plan.Outcome.GRAB)

    def test_a_walk_into_the_clamp_moves_the_boxes_not_the_actor(self) -> None:
        _, actor = _sims(_antonio(), _actor(33, 60, facing_left=True, walking=True))
        plan.actor_update(actor, -1, 0)
        self.assertEqual(actor.x, float(CAMERA.left))
        self.assertEqual(actor.box_x, 33 - 3.25)

    def test_a_pending_grab_is_his_held_state_on_his_next_update(self) -> None:
        holding = _actor(170, 60, action_state=0x60, held_enemy_slot="obj09")
        boss, actor = _sims(_antonio(200, 60, hold_flags=0x01), holding)
        self.assertIs(plan.boss_update(boss, actor), plan.Outcome.NONE)
        self.assertEqual(boss.primary, plan.PRIMARY_HELD)


def _boomerang(x: float, y: float, **overrides) -> Projectile:
    fields = dict(
        slot="obj10",
        world_x=int(x),
        world_y=int(y),
        vel_x=0.0,
        vel_z=0.0,
        type_id=plan.BOOMERANG_TYPE,
        fine_x=float(x),
        fine_y=float(y),
        screen_x=int(x) + 0x80,
    )
    fields.update(overrides)
    return Projectile(**fields)


class BoomerangTests(unittest.TestCase):
    """``$17262``: launched from his wind-up, out, back, caught in tactical 7."""

    def _boss(self, antonio: Antonio, boomerang: Projectile | None = None) -> plan.BossSim:
        return plan.BossSim.from_token(antonio, cam_x=0, boomerang=boomerang, boomerang_known=True)

    def _far_actor(self) -> plan.ActorSim:
        return _sims(_antonio(), _actor(40, 100, facing_left=True))[1]

    def test_frame_two_of_the_wind_up_launches_it(self) -> None:
        # Facing the actor on his left: the mirrored wind-up ($32), whose
        # frame 2 names child animation $42 at 64 px ahead ($173A0 record 13).
        # It reads his +$0A before the renderer steps it: frame 1 about to
        # roll over does not launch it yet (the lockstep lab caught a model
        # that did, one update early) ...
        winding = _antonio(
            300, 40, tactical=6, phase_timer=20,
            anim=plan.ANIM_WINDUP | plan.ANIM_MIRROR_BIT, anim_frame=1, anim_countdown=1,
        )
        boss = self._boss(winding)
        plan.boss_update(boss, self._far_actor())
        self.assertIsNone(boss.boomerang)
        self.assertEqual(boss.frame, plan.BOOMERANG_LAUNCH_FRAME)
        # ... frame 2 about to be shown does.
        plan.boss_update(boss, self._far_actor())
        m = boss.boomerang
        self.assertEqual(m.state, plan.BOOMERANG_OUT)
        self.assertEqual((m.x, m.y, m.vx, m.vy), (236.0, 40.0, -14.0, 4.5))
        self.assertEqual(m.countdown, plan.BOOMERANG_OUT_UPDATES)

    def _thrown(self) -> plan.BossSim:
        boss = self._boss(_antonio(300, 40, tactical=7, anim=plan.ANIM_THROW | plan.ANIM_MIRROR_BIT))
        boss.boomerang = plan.BoomerangSim(
            state=plan.BOOMERANG_OUT, x=236.0, y=40.0, vx=-14.0, vy=4.5,
            anim=plan.ANIM_BOOMERANG_LEFT, frame=1, shown=0xA5, screen_x=236 + 0x80,
            countdown=plan.BOOMERANG_OUT_UPDATES, lane_target=0, above=False,
            turn_lane=0, knock_timer=0, slot="obj10",
        )
        return boss

    def test_out_it_slows_and_dives_for_32_updates_then_turns(self) -> None:
        boss = self._thrown()
        m = boss.boomerang
        for _ in range(plan.BOOMERANG_OUT_UPDATES):
            plan._boomerang_step(boss, None, margin=False)
        # 31 updates of travel (the 32nd stops it dead): 14*31 - 0.4375*496
        # on X, 4.5*31 - 0.1875*496 down the lane.
        self.assertEqual(m.state, plan.BOOMERANG_BACK)
        self.assertEqual((m.vx, m.vy), (0.0, 0.0))
        self.assertAlmostEqual(m.x, 236.0 - 217.0)
        self.assertAlmostEqual(m.y, 40.0 + 46.5)
        # $172F6's lea: it homes on its own +$78 (0), which lies above it.
        self.assertEqual((m.lane_target, m.above), (0, True))

    def test_back_it_climbs_to_its_lane_while_it_comes_back(self) -> None:
        boss = self._thrown()
        m = boss.boomerang
        for _ in range(plan.BOOMERANG_OUT_UPDATES + 31):
            plan._boomerang_step(boss, None, margin=False)
        self.assertEqual((m.y, m.vy), (0.0, 0.0))  # clamped at the top, then within 4
        self.assertAlmostEqual(m.vx, 31 * plan.BOOMERANG_DECEL_X)  # back toward him

    def test_tactical_7_walks_him_to_its_lane_and_catches_it(self) -> None:
        facing_left = _antonio(300, 40, tactical=7, anim=plan.ANIM_THROW | plan.ANIM_MIRROR_BIT)
        coming = _boomerang(100, 10, state=plan.BOOMERANG_BACK, anim=plan.ANIM_BOOMERANG_LEFT)
        boss = self._boss(facing_left, coming)
        plan.boss_update(boss, self._far_actor())
        self.assertEqual((boss.tactical, boss.vy), (7, -1.0))
        # His hand is 24 px in front of him (276); inside 8 px of it, caught.
        caught = _boomerang(281, 10, state=plan.BOOMERANG_BACK, anim=plan.ANIM_BOOMERANG_LEFT)
        boss = self._boss(facing_left, caught)
        plan.boss_update(boss, self._far_actor())
        self.assertEqual(boss.tactical, 0)
        self.assertIsNone(boss.boomerang)

    def test_with_no_boomerang_left_tactical_7_is_over(self) -> None:
        boss = self._boss(_antonio(300, 40, tactical=7, anim=plan.ANIM_THROW | plan.ANIM_MIRROR_BIT))
        plan.boss_update(boss, self._far_actor())
        self.assertEqual(boss.tactical, 0)

    def test_back_below_tactical_6_he_takes_a_fresh_one(self) -> None:
        # $17206: his linked one still out, and he is in tactical 0 -- a new
        # one on his hand, and the old one flies on unlinked.
        coming = _boomerang(100, 10, state=plan.BOOMERANG_BACK, anim=plan.ANIM_BOOMERANG_LEFT)
        boss = self._boss(_antonio(300, 40, phase_timer=5), coming)
        plan.boss_update(boss, self._far_actor())
        self.assertEqual(boss.boomerang.state, plan.BOOMERANG_ATTACHED)
        self.assertEqual([s.slot for s in boss.strays], ["obj10"])
        self.assertEqual(boss.strays[0].state, plan.BOOMERANG_BACK)

    def test_an_unlinked_one_still_hits(self) -> None:
        stray = _boomerang(100, 60, state=plan.BOOMERANG_BACK, attack_box_id=0xA5,
                           anim=plan.ANIM_BOOMERANG_LEFT, slot="obj11")
        boss = plan.BossSim.from_token(
            _antonio(300, 40, tactical=1, phase_timer=10), cam_x=0, strays=[stray], boomerang_known=True
        )
        on_path = _sims(_antonio(), _actor(95, 60))[1]
        self.assertIs(plan.boss_update(boss, on_path), plan.Outcome.HIT)

    def test_his_link_names_his_own(self) -> None:
        mine = _boomerang(0, 0, slot="obj10")
        old = _boomerang(100, 10, slot="obj11", state=plan.BOOMERANG_BACK)
        linked, strays = plan.split_boomerangs(_antonio(child_slot="obj10"), [old, mine])
        self.assertIs(linked, mine)
        self.assertEqual(strays, [old])
        # Linked to the old one (no fresh one yet): that is his, nothing stray.
        linked, strays = plan.split_boomerangs(_antonio(child_slot="obj11"), [old])
        self.assertIs(linked, old)
        self.assertEqual(strays, [])

    def test_its_box_on_the_actors_body_is_a_hit(self) -> None:
        m = plan.BoomerangSim.from_token(
            _boomerang(100, 60, state=plan.BOOMERANG_OUT, attack_box_id=0xA5)
        )
        on_path = _sims(_antonio(), _actor(95, 60))[1]
        self.assertTrue(plan.boomerang_contact(m, on_path, margin=False))
        off_lane = _sims(_antonio(), _actor(95, 77))[1]
        self.assertFalse(plan.boomerang_contact(m, off_lane, margin=False))

    def test_not_looked_for_it_is_not_modelled(self) -> None:
        winding = _antonio(
            300, 40, tactical=6, phase_timer=20,
            anim=plan.ANIM_WINDUP | plan.ANIM_MIRROR_BIT, anim_frame=2, anim_countdown=6,
        )
        boss = plan.BossSim.from_token(winding, cam_x=0)
        plan.boss_update(boss, self._far_actor())
        self.assertIsNone(boss.boomerang)

    def test_the_engage_steps_off_a_returning_boomerangs_path(self) -> None:
        # The measured hit: 130 px out, just below his lane, a boomerang from
        # an earlier throw coming back at the actor's lane from behind.
        antonio = _antonio(200, 15, tactical=7, anim=plan.ANIM_THROW, facing_left=False)
        coming = _boomerang(
            430, 24, state=plan.BOOMERANG_BACK, anim=plan.ANIM_BOOMERANG_RIGHT,
            vel_x=-8.0, attack_box_id=0xA4, lane_target=0, lane_target_above=True,
        )
        actor = _actor(330, 20, facing_left=True)
        standing = plan.simulate(
            antonio, actor, [(0, 0)] * plan.HORIZON_UPDATES, camera=None,
            boomerang=coming, boomerang_known=True,
        )
        self.assertIs(standing[-1][0], plan.Outcome.HIT)  # it would land
        result = plan.plan_engage(actor, antonio, projectiles=[coming])
        self.assertNotEqual(result.outcome, "hit")
        self.assertNotEqual((result.dir_x, result.dir_y), (0, 0))


class EngageAimTests(unittest.TestCase):
    def _mode(self, actor: Myself, antonio: Antonio) -> plan.EngageMode:
        boss, sim = _sims(antonio, actor)
        return plan.engage_aim(sim, boss)[0]

    def test_above_him_by_nine_or_more_is_the_pocket(self) -> None:
        self.assertIs(self._mode(_actor(120, 50), _antonio(200, 60)), plan.EngageMode.POCKET)

    def test_just_above_him_inside_his_kick_lane_climbs(self) -> None:
        self.assertIs(self._mode(_actor(120, 55), _antonio(200, 60)), plan.EngageMode.RISE)

    def test_level_or_below_inside_his_window_gets_out_first(self) -> None:
        self.assertIs(self._mode(_actor(120, 70), _antonio(200, 60)), plan.EngageMode.RETREAT)

    def test_level_or_below_out_of_his_window_climbs_there(self) -> None:
        self.assertIs(self._mode(_actor(60, 70), _antonio(200, 60)), plan.EngageMode.CLIMB)

    def test_with_no_room_above_him_it_lures_him_down(self) -> None:
        self.assertIs(self._mode(_actor(120, 40), _antonio(200, 6)), plan.EngageMode.LURE)


class PlanEngageTests(unittest.TestCase):
    def _plan(self, actor: Myself, antonio: Antonio) -> plan.EngagePlan:
        return plan.plan_engage(actor, antonio, camera=CAMERA)

    def test_the_regrab_after_a_release_walks_straight_back_in(self) -> None:
        # Released: he is back in primary 1, 40 px in front on the actor's
        # lane ($17D76), and the release left the actor facing away.
        result = self._plan(_actor(160, 60, facing_left=True), _antonio(200, 60))
        self.assertEqual(result.dir_x, 1)
        self.assertEqual(result.outcome, "grab")

    def test_from_the_pocket_the_walk_in_meets_his_dash(self) -> None:
        result = self._plan(_actor(110, 48), _antonio(200, 60))
        self.assertEqual(result.dir_x, 1)
        self.assertEqual(result.outcome, "grab")

    def test_keeps_walking_into_a_kick_it_can_grab_through(self) -> None:
        # Already walking in, 48 px out on frame 3: the walking box meets his
        # leaning body. Letting go now would drop the box and take the kick,
        # which is exactly what scoring both update orders rules out.
        actor = _actor(152, 60, walking=True, vel_x=3.25)
        result = self._plan(actor, _kicking(200, 60, frame=3))
        self.assertEqual(result.dir_x, 1)
        self.assertEqual(result.outcome, "grab")

    def test_a_still_actor_inside_a_live_kick_box_has_no_good_answer(self) -> None:
        # Standing 48 px out on frame 3 is inside the 12..84 px box with no
        # walking box yet: the next update of his can land before any stick
        # does. Not a case the plan can fix -- only one it must never create.
        result = self._plan(_actor(152, 60), _kicking(200, 60, frame=3))
        self.assertEqual(result.outcome, "hit")

    def test_never_walks_into_a_kick_it_cannot_grab_through(self) -> None:
        result = self._plan(_actor(100, 60), _kicking(200, 60, frame=3))
        self.assertNotEqual(result.dir_x, 1)
        self.assertNotEqual(result.outcome, "hit")

    def test_below_him_inside_his_window_it_is_never_hit(self) -> None:
        result = self._plan(_actor(150, 60), _antonio(200, 40, phase_timer=5))
        self.assertNotEqual(result.outcome, "hit")

    def test_at_the_camera_edge_it_walks_into_him_as_he_walks_back_on(self) -> None:
        # He is past the right edge (+$28 >= $1C0), so tactical 9 walks him in
        # at 4 px an update with both gates skipped; the actor, clamped at
        # the edge, keeps its walking box pointed at him and he walks into it.
        antonio = _antonio(328, 60, screen_x=328 + 0x80)
        result = self._plan(_actor(288, 60, facing_left=True), antonio)
        self.assertEqual(result.dir_x, 1)
        self.assertEqual(result.outcome, "grab")

    def test_his_walk_back_on_screen_is_not_walked_into(self) -> None:
        antonio = _antonio(10, 60, screen_x=0x70, tactical=9, timer_5c=20, boss_vel_x=4.0)
        result = self._plan(_actor(60, 60), antonio)
        self.assertNotEqual(result.outcome, "hit")

    def test_a_hit_reactions_immunity_is_not_counted_on(self) -> None:
        # Still flagged (+$59 bit 1) in front of a live kick: the plan cannot
        # see when the immunity ends, so it plans exactly as if it had.
        flagged = _actor(100, 60, flags_59=PLAYER_HIT_REACTION_BIT)
        self.assertEqual(
            self._plan(flagged, _kicking(200, 60, frame=3)),
            self._plan(_actor(100, 60), _kicking(200, 60, frame=3)),
        )


class HoldStepTests(unittest.TestCase):
    """Knee, knee, release -- the holding player's own bytes, as for Souther."""

    def _front(self, knees: int, **overrides) -> Myself:
        last = {0: 0, 1: 0x6A, 2: 0x6C}[knees]
        flags = PLAYER_KNEE_CHAIN_BIT if knees else 0
        return _actor(160, 60, action_state=0x60, action_flags=flags, knee_chain_last=last, **overrides)

    def test_two_knees_then_the_release(self) -> None:
        antonio = _antonio(200, 60, primary_state=4)
        self.assertIs(plan.hold_step(self._front(0), antonio), plan.HoldStep.KNEE)
        self.assertIs(plan.hold_step(self._front(1), antonio), plan.HoldStep.KNEE)
        self.assertIs(plan.hold_step(self._front(2), antonio), plan.HoldStep.RELEASE)

    def test_the_third_knee_only_when_it_kills(self) -> None:
        antonio = _antonio(200, 60, primary_state=4, health=3)
        self.assertIs(plan.hold_step(self._front(2), antonio), plan.HoldStep.KNEE)

    def test_a_back_hold_crosses_once_and_suplexes_only_to_kill(self) -> None:
        back = _actor(160, 60, action_state=0x66)
        spent = _actor(160, 60, action_state=0x66, crossover_spent=True)
        self.assertIs(plan.hold_step(back, _antonio(primary_state=4)), plan.HoldStep.CROSS)
        self.assertIs(plan.hold_step(spent, _antonio(primary_state=4)), plan.HoldStep.RELEASE)
        self.assertIs(plan.hold_step(back, _antonio(primary_state=4, health=5)), plan.HoldStep.SUPLEX)

    def test_the_crossover_bit_is_the_players(self) -> None:
        self.assertEqual(PLAYER_CROSSOVER_SPENT_BIT, 0x80)


if __name__ == "__main__":
    unittest.main()
