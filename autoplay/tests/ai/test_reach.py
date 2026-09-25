"""Tests for the reach predicates that read a real ``AttackRange``.

The rest of ``reach.py`` is exercised through ``test_decide.py``/
``test_priority.py`` (which call these bands directly, once per tick); this
file covers the predicates that answer questions about the *enemy's* reach
rather than the actor's, since those are the ones that changed from an
assumed margin to the ROM's own geometry.
"""

import unittest
from dataclasses import replace

from sor_autoplay.ai import kinematics, reach
from sor_autoplay.ai.tokens import (
    Abadede,
    Antonio,
    AttackRange,
    CameraRange,
    Enemy,
    Garcia,
    GrabEnemy,
    GrabReason,
    Jack,
    JumpAttack,
    Myself,
    Nora,
    Partner,
    Projectile,
    Punch,
    RearAttack,
    Signal,
    Souther,
    Stage,
    Surrounded,
    Weapon,
)
from sor_autoplay.hitboxes import Hitbox
from sor_autoplay.phases import CombatPhase

# Nora's whip and Garcia's straight punch, exactly as attack_ranges.py pulls
# them out of $242F8 and $1FC70 (shapes $22 and $12).
NORA_WHIP = AttackRange(
    shape_id=0x22,
    animation=10,
    forward_min=32,
    forward_max=80,
    lane_min=-12,
    lane_max=10,
    height_min=-44,
    height_max=-20,
)
GARCIA_PUNCH = AttackRange(
    shape_id=0x12,
    animation=10,
    forward_min=0,
    forward_max=40,
    lane_min=-8,
    lane_max=8,
    height_min=-50,
    height_max=-44,
)


def _myself(**overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=100,
        world_y=100,
        health=100,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=False,
        combat_phase=CombatPhase.NORMAL,
        action_state=0,
        is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


def _nora(**overrides) -> Nora:
    fields = dict(
        slot="obj02",
        type_id=0x26,
        world_x=200,
        world_y=100,
        health=11,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,  # facing the actor, who stands to its left
        attack_ranges=(NORA_WHIP,),
    )
    fields.update(overrides)
    return Nora(**fields)


def _garcia(**overrides) -> Garcia:
    fields = dict(
        slot="obj01",
        type_id=0x20,
        world_x=200,
        world_y=100,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
        attack_ranges=(GARCIA_PUNCH,),
    )
    fields.update(overrides)
    return Garcia(**fields)


def _signal(**overrides) -> Signal:
    # Signal's own animation set carries no shape with meaningful reach
    # anywhere in it (enemy-ai.md "Signal's slide is velocity, not a
    # hitbox") -- attack_ranges stays empty even mid-slide, unlike Garcia
    # or Nora above.
    fields = dict(
        slot="obj03",
        type_id=0x24,
        world_x=300,
        world_y=100,
        health=8,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
        attack_ranges=(),
    )
    fields.update(overrides)
    return Signal(**fields)


class EnemyForwardDxTests(unittest.TestCase):
    def test_a_left_facing_enemy_measures_forward_to_its_left(self) -> None:
        enemy = _garcia(world_x=200, facing_left=True)
        self.assertEqual(reach.enemy_forward_dx(enemy, _myself(world_x=160)), 40)
        self.assertEqual(reach.enemy_forward_dx(enemy, _myself(world_x=240)), -40)

    def test_a_right_facing_enemy_measures_forward_to_its_right(self) -> None:
        enemy = _garcia(world_x=200, facing_left=False)
        self.assertEqual(reach.enemy_forward_dx(enemy, _myself(world_x=240)), 40)
        self.assertEqual(reach.enemy_forward_dx(enemy, _myself(world_x=160)), -40)


class RearAttackWarrantedTests(unittest.TestCase):
    def test_jack_is_judged_like_any_lone_grunt(self) -> None:
        # No chord is ever produced at Jack (EngageJack owns him), and the
        # predicate keeps no special case for him either.
        actor = _myself(world_x=100, world_y=100)
        jack = Jack(
            slot="obj01",
            type_id=0x27,
            world_x=70,
            world_y=100,
            health=10,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=False,
            has_projectile=False,
        )
        self.assertFalse(reach.rear_attack_is_warranted(actor, jack, [jack]))

    def test_a_lone_garcia_behind_is_not_warranted(self) -> None:
        actor = _myself(world_x=100, world_y=100)
        garcia = _garcia(world_x=70, world_y=100)
        self.assertFalse(reach.rear_attack_is_warranted(actor, garcia, [garcia]))


class EnemyCanReachTests(unittest.TestCase):
    def test_inside_a_real_range(self) -> None:
        # 40px ahead of Garcia, whose punch covers 0..40.
        self.assertTrue(reach.enemy_can_reach(_garcia(), _myself(world_x=160)))

    def test_beyond_every_range_even_with_the_margin(self) -> None:
        # 60px ahead: past 40 + REACH_SAFETY_MARGIN.
        self.assertFalse(reach.enemy_can_reach(_garcia(), _myself(world_x=140)))

    def test_behind_the_enemy_is_not_reachable(self) -> None:
        self.assertFalse(reach.enemy_can_reach(_garcia(), _myself(world_x=240)))

    def test_off_lane_is_not_reachable(self) -> None:
        self.assertFalse(reach.enemy_can_reach(_garcia(), _myself(world_x=160, world_y=160)))

    def test_unknown_when_no_ranges_were_extracted(self) -> None:
        # A boss, or a session with no ROM tables: "unknown", never "no".
        bare = _garcia(attack_ranges=())
        self.assertIsNone(reach.enemy_can_reach(bare, _myself(world_x=160)))

    def test_inside_noras_dead_zone_she_cannot_reach(self) -> None:
        # 16px ahead is well under the whip's 32px minimum.
        self.assertFalse(reach.enemy_can_reach(_nora(), _myself(world_x=184)))

    def test_at_whip_distance_she_can(self) -> None:
        self.assertTrue(reach.enemy_can_reach(_nora(), _myself(world_x=140)))


class InEnemyDeadZoneTests(unittest.TestCase):
    def test_pressed_against_nora(self) -> None:
        self.assertTrue(reach.in_enemy_dead_zone(_nora(), _myself(world_x=190)))

    def test_not_inside_once_the_whip_can_start(self) -> None:
        # 32px out is the whip's own edge, so this is not a dead zone.
        self.assertFalse(reach.in_enemy_dead_zone(_nora(), _myself(world_x=168)))

    def test_an_enemy_whose_attack_reaches_its_own_feet_has_no_dead_zone(self) -> None:
        self.assertFalse(reach.in_enemy_dead_zone(_garcia(), _myself(world_x=196)))

    def test_behind_the_enemy_is_not_a_dead_zone(self) -> None:
        # It only has to turn around, which is free.
        self.assertFalse(reach.in_enemy_dead_zone(_nora(), _myself(world_x=210)))

    def test_no_ranges_means_no_claim_of_safety(self) -> None:
        self.assertFalse(reach.in_enemy_dead_zone(_nora(attack_ranges=()), _myself(world_x=190)))

    def test_every_range_must_agree(self) -> None:
        # Armed with a pipe, Nora gains a 0..36 range that covers her own
        # feet, so the whip's dead zone stops being one.
        pipe = AttackRange(
            shape_id=0,
            animation=-1,
            forward_min=0,
            forward_max=36,
            lane_min=-8,
            lane_max=8,
            height_min=-60,
            height_max=0,
        )
        armed = _nora(attack_ranges=(NORA_WHIP, pipe))

        self.assertFalse(reach.in_enemy_dead_zone(armed, _myself(world_x=190)))


class TooCloseToKeepApproachingTests(unittest.TestCase):
    def test_prefers_the_enemys_own_reach_over_the_actors_punch_box(self) -> None:
        # 60px from Garcia: outside his real 40px punch, but *inside* the old
        # caution box (Axel's punch_outer 50 + RETREAT_CAUTION_MARGIN 24 = 74).
        # The extracted reach is what should decide.
        actor = _myself(world_x=140)
        self.assertFalse(reach.too_close_to_keep_approaching(actor, _garcia()))

    def test_falls_back_to_the_caution_box_without_ranges(self) -> None:
        actor = _myself(world_x=140)
        self.assertTrue(reach.too_close_to_keep_approaching(actor, _garcia(attack_ranges=())))

    def test_noras_dead_zone_is_not_too_close(self) -> None:
        # Pressed against her: the old box called this the most dangerous
        # place on the screen; her only attack cannot touch the actor here.
        self.assertFalse(reach.too_close_to_keep_approaching(_myself(world_x=190), _nora()))

    def test_whip_distance_is_too_close(self) -> None:
        self.assertTrue(reach.too_close_to_keep_approaching(_myself(world_x=140), _nora()))


class EnemyMaxAndMinReachTests(unittest.TestCase):
    def test_max_reach_is_the_longest_range(self) -> None:
        enemy = _garcia(attack_ranges=(GARCIA_PUNCH, NORA_WHIP))
        self.assertEqual(enemy.max_reach, 80)

    def test_min_reach_is_the_nearest_edge_of_any_range(self) -> None:
        enemy = _garcia(attack_ranges=(GARCIA_PUNCH, NORA_WHIP))
        self.assertEqual(enemy.min_reach, 0)

    def test_a_lone_dead_zone_range_reports_its_own_minimum(self) -> None:
        self.assertEqual(_nora().min_reach, 32)

    def test_unknown_reach_reads_as_zero(self) -> None:
        bare: Enemy = _garcia(attack_ranges=())
        self.assertEqual(bare.max_reach, 0)
        self.assertEqual(bare.min_reach, 0)


class EnemyProjectedTests(unittest.TestCase):
    def test_moves_by_velocity_times_frames(self) -> None:
        signal = _signal(world_x=300, world_y=100, grunt_vel_x=-2.5, grunt_vel_y=2.0)

        projected = reach.enemy_projected(signal, 6)

        self.assertEqual(projected.world_x, 300 - round(2.5 * 6))
        self.assertEqual(projected.world_y, 100 + round(2.0 * 6))

    def test_a_stationary_enemy_projects_to_itself(self) -> None:
        signal = _signal(world_x=300, world_y=100)

        projected = reach.enemy_projected(signal, 6)

        self.assertEqual((projected.world_x, projected.world_y), (300, 100))

    def test_leaves_every_other_field_untouched(self) -> None:
        signal = _signal(grunt_vel_x=-2.5)

        projected = reach.enemy_projected(signal, 6)

        self.assertEqual(projected.slot, signal.slot)
        self.assertEqual(projected.combat_phase, signal.combat_phase)
        self.assertEqual(projected.attack_ranges, signal.attack_ranges)


class EnemyWillCloseSoonTests(unittest.TestCase):
    """Signal's slide (enemy-ai.md "Signal's slide is velocity, not a
    hitbox") is the ROM-confirmed case this exists for: no attack shape
    anywhere in its animation set, so attack_ranges is empty and
    too_close_to_keep_approaching only ever sees the caution-box fallback,
    which is reactive -- it does not fire until the slide has already
    arrived."""

    def test_a_fast_committed_signal_still_far_away_closes_soon(self) -> None:
        # 99px out (well outside Axel's 74px caution box) but sliding in at
        # the slide's own ROM speed, ~2.5 px per 60 Hz frame: over
        # CLOSING_ENEMY_THREAT_FRAMES that is 30px, landing at dx=69, inside
        # the box -- deliberately about the *projection*, not current
        # distance.
        actor = _myself(world_x=100, world_y=100)
        signal = _signal(world_x=199, world_y=100, grunt_vel_x=-2.5, grunt_vel_y=0.0)

        self.assertFalse(reach.too_close_to_keep_approaching(actor, signal))
        self.assertTrue(reach.enemy_will_close_soon(actor, signal))

    def test_a_stationary_signal_never_closes_soon_on_its_own(self) -> None:
        # Far away and not moving: the *current*-position test already
        # answers this; projecting a stationary enemy must not add a second,
        # different answer.
        actor = _myself(world_x=100, world_y=100)
        far = _signal(world_x=400, world_y=100)

        self.assertFalse(reach.too_close_to_keep_approaching(actor, far))
        self.assertFalse(reach.enemy_will_close_soon(actor, far))

    def test_moving_away_does_not_close_soon(self) -> None:
        # Same distance and speed as the closing case above, opposite sign.
        actor = _myself(world_x=100, world_y=100)
        signal = _signal(world_x=199, world_y=100, grunt_vel_x=2.5, grunt_vel_y=0.0)

        self.assertFalse(reach.enemy_will_close_soon(actor, signal))

    def test_off_lane_closing_does_not_count(self) -> None:
        # Heading straight at the actor's X but on a lane the caution box's
        # own Y margin excludes -- the projection must still respect that,
        # not just the X approach.
        actor = _myself(world_x=100, world_y=100)
        signal = _signal(world_x=199, world_y=300, grunt_vel_x=-2.5, grunt_vel_y=0.0)

        self.assertFalse(reach.enemy_will_close_soon(actor, signal))

    def test_a_grunt_with_a_real_reach_still_prefers_it_once_projected(self) -> None:
        # Garcia (confirmed punch: forward 0..40, lane -8..8) 60px ahead of
        # his own reach, closing at the ROM lunge speed of ~2.75 px per 60 Hz
        # frame -- over CLOSING_ENEMY_THREAT_FRAMES that projects him to
        # forward_dx=27, inside his real band, well before the caution box's
        # coarser fallback would have said anything. facing_left=True
        # (default) means the actor, to Garcia's left, is what "forward"
        # means for him, so his own world_x must fall to close the gap.
        actor = _myself(world_x=100, world_y=100)
        garcia = _garcia(world_x=160, world_y=100, grunt_vel_x=-2.75, grunt_vel_y=0.0)

        self.assertFalse(reach.too_close_to_keep_approaching(actor, garcia))
        self.assertTrue(reach.enemy_will_close_soon(actor, garcia))


class BodyWidthGeometryTests(unittest.TestCase):
    """A hit is box-against-body, not box-against-point ($450C)."""

    def test_a_body_overlapping_the_inner_edge_is_in_the_punch_band(self) -> None:
        # dx=10 is inside Axel's measured 16px box edge, but the enemy's own
        # ~13px body still reaches into the box. Treating this as a dead zone
        # made the AI refuse to punch, walk away to re-establish range, turn
        # around doing so, and then shuffle in punching range forever.
        actor = _myself(world_x=100, character_id=0)
        enemy = _garcia(world_x=110, world_y=100)

        self.assertTrue(reach.punch_would_connect(actor, enemy))

    def test_a_body_fully_inside_the_dead_zone_is_not(self) -> None:
        actor = _myself(world_x=100, character_id=0)
        enemy = _garcia(world_x=106, world_y=100)

        self.assertFalse(reach.punch_would_connect(actor, enemy))

    def test_a_forward_strike_never_reaches_behind(self) -> None:
        # The punch box starts 8-18px *in front* depending on character, so
        # no body centred behind the actor can overlap it. A flat 4px of
        # "behind tolerance" said otherwise, and Adam -- who lands 4px past
        # an enemy after a jump kick -- then stood there punching forward
        # into empty air for as long as the enemy stayed put.
        for character_id in (0, 1, 2):
            with self.subTest(character_id=character_id):
                self.assertEqual(reach.punch_behind_tolerance_x(character_id), 0)
                actor = _myself(world_x=100, character_id=character_id, facing_left=False)
                behind = _garcia(world_x=96, world_y=100)
                self.assertFalse(reach.punch_would_connect(actor, behind))

    def test_a_zero_width_front_chord_band_never_matches(self) -> None:
        # Axel and Blaze have no forward reach with $322A at all, and `<=`
        # against a zero-width band still matched dx == 0 -- which is exactly
        # where a jump kick landing on its target leaves the actor, so the
        # AI answered "nothing can hit this" with a backfist aimed the other
        # way.
        for character_id in (0, 2):
            with self.subTest(character_id=character_id):
                actor = _myself(world_x=100, character_id=character_id, facing_left=False)
                on_top = _garcia(world_x=100, world_y=100)
                self.assertFalse(reach.in_rear_band(actor, on_top))

    def test_adams_forward_chord_still_reaches(self) -> None:
        actor = _myself(world_x=100, character_id=1, facing_left=False)
        self.assertTrue(reach.in_rear_band(actor, _garcia(world_x=110, world_y=100)))


class LiveEnemyTests(unittest.TestCase):
    def test_an_enemy_past_the_lethal_boundary_is_not_a_target(self) -> None:
        # The ROM's lethal check is signed: $8000-$FFFF is already dead while
        # the object still sits in its slot with a stale action family. The
        # AI used to chase, rank and punch those corpses.
        dead = _garcia(world_x=130, world_y=100, health=0xFFFF)

        self.assertTrue(dead.is_defeated)
        self.assertEqual(reach.live_enemies({dead}), [])

    def test_zero_health_is_still_a_target(self) -> None:
        # Not yet defeated -- the ROM counts it alive and wants one more hit.
        dying = _garcia(world_x=130, world_y=100, health=0)

        self.assertFalse(dying.is_defeated)
        self.assertEqual(reach.live_enemies({dying}), [dying])

    def test_an_enemy_below_the_players_own_lane_floor_is_still_a_target(self) -> None:
        # The two clamps differ by two pixels: players are held to $02..$70
        # ($44 0A) and enemies to $00..$70 ($17AB8). Judging an enemy by the
        # player's floor dropped Souther -- who fights from the top of the
        # band -- out of the target list for a quarter of a round-2 fight,
        # and with no target the AI walked away from a live boss.
        high = _garcia(world_x=130, world_y=0)

        self.assertTrue(reach.in_targetable_lane(high.world_y, {high}))
        self.assertFalse(reach.in_playable_lane(high.world_y, {high}))
        self.assertEqual(reach.live_enemies({high}), [high])

    def test_an_enemy_past_the_lane_ceiling_is_not_a_target(self) -> None:
        # The placeholder this filter exists for -- stage 1's scripted
        # "behind a door" enemy -- is past the *ceiling*, which the enemy
        # band rejects exactly as the player band did.
        offstage = _garcia(world_x=130, world_y=400)

        self.assertFalse(reach.in_targetable_lane(offstage.world_y, {offstage}))
        self.assertEqual(reach.live_enemies({offstage}), [])

    def test_an_enemy_in_the_screen_strip_outside_the_walk_clamp_is_on_screen(self) -> None:
        # CameraRange is the player's walk clamp, 256px wide; the CRT is 320.
        # An enemy in the 32px strip down either side is plainly visible and
        # fighting, and used to vanish from every verb that asks
        # on_screen_enemies -- Souther backs into the left strip constantly.
        camera = CameraRange(left=3552, right=3808, top=0, bottom=112)
        in_strip = _garcia(world_x=3536, world_y=40)
        off_screen = _garcia(slot="obj02", world_x=3400, world_y=40)

        self.assertFalse(reach.in_camera(camera, in_strip.world_x, in_strip.world_y))
        self.assertEqual(
            reach.on_screen_enemies({camera, in_strip, off_screen}), [in_strip]
        )


class EnemyStillEmergingTests(unittest.TestCase):
    """Round 5's HakuRo, still below the boat's deck (``enemy.world_z``).

    ai-analysis/enemy-ai.md, "HakuRo: rising from below deck": a live capture
    of round 5, wave 3 measured the ROM parking a fully visible, otherwise
    ordinary HakuRo at ``world_z=212`` -- 52px ($34) below the round's own
    floor (``hazards.base_floor_z(4) == 160``) -- for over thirty seconds
    with no progress at all, because ``haku_ro_type25_dispatcher``'s state
    ``$13`` handler ($0000E952) does not touch +$18/+$24 again until the
    camera scrolls close enough. ``phases.py`` has no per-type table entry
    for HakuRo at all, so that state decodes as ``CombatPhase.UNKNOWN`` --
    not one of ``should_ignore_as_target``'s phases -- which is why the
    geometry check in ``reach.enemy_still_emerging`` is the fix rather than a
    phase-table entry.
    """

    def test_an_enemy_below_the_rounds_floor_is_not_yet_a_target(self) -> None:
        stage = Stage(level_index=4, direction="right")  # round 5
        rising = _enemy(world_x=130, world_y=0, world_z=212)

        self.assertTrue(reach.enemy_still_emerging(rising, {stage, rising}))
        self.assertEqual(reach.live_enemies({stage, rising}), [])

    def test_an_enemy_on_the_floor_is_a_target(self) -> None:
        stage = Stage(level_index=4, direction="right")
        landed = _enemy(world_x=130, world_y=0, world_z=160)

        self.assertFalse(reach.enemy_still_emerging(landed, {stage, landed}))
        self.assertEqual(reach.live_enemies({stage, landed}), [landed])

    def test_small_jitter_above_the_floor_does_not_suppress_a_target(self) -> None:
        # Right at the margin's own edge -- still not suppressed. The margin
        # exists so a body genuinely on the floor is never dropped by noise;
        # 52px of real emergence is nowhere near it.
        stage = Stage(level_index=4, direction="right")
        jittered = _enemy(
            world_x=130, world_y=0, world_z=160 + reach.EMERGING_FLOOR_MARGIN_Z
        )

        self.assertFalse(reach.enemy_still_emerging(jittered, {stage, jittered}))

    def test_becomes_a_target_again_the_moment_it_lands(self) -> None:
        # Must not over-suppress: once the ROM's own landing snap runs
        # (state $13 -> $0E, world_z back to the floor), the same enemy is
        # targetable again with no extra machinery.
        stage = Stage(level_index=4, direction="right")
        still_rising = _enemy(slot="obj02", world_x=130, world_y=0, world_z=212)
        landed = replace(still_rising, world_z=160)

        self.assertEqual(reach.live_enemies({stage, still_rising}), [])
        self.assertEqual(reach.live_enemies({stage, landed}), [landed])

    def test_with_no_stage_token_nothing_is_suppressed(self) -> None:
        # Conservative default: a missing token must never be read as a
        # reason to drop a target -- only a real measurement is.
        rising = _enemy(world_x=130, world_y=0, world_z=212)

        self.assertFalse(reach.enemy_still_emerging(rising, {rising}))
        self.assertEqual(reach.live_enemies({rising}), [rising])

    def test_a_boss_never_populates_world_z_so_it_is_never_suppressed(self) -> None:
        # Boss tracks its own elevation as ground_z/vel_z; world_z stays at
        # its default 0, always well above any round's floor.
        stage = Stage(level_index=4, direction="right")
        boss = _souther(world_x=130, world_y=0, primary_state=1)

        self.assertFalse(reach.enemy_still_emerging(boss, {stage, boss}))


def _antonio(**overrides) -> Antonio:
    fields = dict(
        slot="obj09",
        type_id=0x56,
        world_x=200,
        world_y=100,
        health=40,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
        primary_state=1,
        boss_dist_x=40,
        boss_dist_lane=4,
    )
    fields.update(overrides)
    return Antonio(**fields)


def _souther(**overrides) -> Souther:
    fields = dict(
        slot="obj11",
        type_id=0x55,
        world_x=200,
        world_y=100,
        health=32,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
        primary_state=1,
        tactical=0,
        boss_dist_x=40,
        boss_dist_lane=4,
    )
    fields.update(overrides)
    return Souther(**fields)


class SoutherWouldPunishJumpTests(unittest.TestCase):
    def test_armed_in_state_1(self) -> None:
        myself = _myself(world_x=160, world_y=100)
        souther = _souther(world_x=200, world_y=100, primary_state=1, tactical=2)
        self.assertTrue(reach.souther_would_punish_jump(myself, {myself, souther}))

    def test_armed_during_the_claw_windup(self) -> None:
        myself = _myself(world_x=160, world_y=100)
        souther = _souther(
            world_x=200,
            world_y=100,
            combat_phase=CombatPhase.ATTACKING,
            primary_state=2,
            tactical=0,
        )
        self.assertTrue(reach.souther_would_punish_jump(myself, {myself, souther}))

    def test_still_refused_once_the_dash_is_launched(self) -> None:
        # $1619E / $161C6 never call $16234 -- but they skip it because he is
        # *already attacking*, with the type-$98 claw live. This was the
        # live-reported bug: treating "not counter-armed" as "safe to jump"
        # flew the AI straight into the claws.
        myself = _myself(world_x=160, world_y=100)
        for tactical in (1, 2):
            souther = _souther(
                world_x=200,
                world_y=100,
                combat_phase=CombatPhase.ATTACKING,
                primary_state=2,
                tactical=tactical,
            )
            self.assertTrue(
                reach.souther_would_punish_jump(myself, {myself, souther}),
                f"tactical {tactical:#04x}",
            )

    def test_even_a_punishable_souther_refuses_the_hop(self) -> None:
        # There is no safe window, and this used to be treated as one. $16234
        # is off the call path of the shared $03/$04 hit reaction, so the hop
        # cannot be countered on the tick it launches -- but the flight is ~45
        # frames against a recovery of a handful, and $16294
        # (souther_select_target) re-runs $162A4 against the player's live
        # action state every state-1 tick, which stays $16/$17 for the whole
        # flight. The counter arms itself the moment he stands up, with the
        # actor still airborne. A punishable Souther is a walk-in and a grab.
        myself = _myself(world_x=160, world_y=100)
        souther = _souther(
            world_x=200, world_y=100, combat_phase=CombatPhase.RECOVERY
        )
        self.assertTrue(reach.souther_would_punish_jump(myself, {myself, souther}))

    def test_a_dead_souther_stops_refusing_it(self) -> None:
        # The refusal is about a boss who can still stand up, and nothing else
        # on the screen should inherit it.
        myself = _myself(world_x=160, world_y=100)
        souther = _souther(world_x=200, world_y=100, health=0xFFFF)

        self.assertTrue(souther.is_defeated)
        self.assertFalse(reach.souther_would_punish_jump(myself, {myself, souther}))

    def test_off_lane_is_still_refused(self) -> None:
        # The ROM's own $12 lane window is deliberately not reproduced: the
        # flight cannot leave its lane, but Souther closes lane at 4px/frame
        # ($15F98/$160D0), which erases 18px in about five of the flight's ~25
        # frames. Gating on lane is what let the AI launch from just off-lane
        # and get hit anyway.
        myself = _myself(world_x=160, world_y=100)
        souther = _souther(world_x=200, world_y=140, primary_state=1)
        self.assertTrue(reach.souther_would_punish_jump(myself, {myself, souther}))

    def test_launch_from_just_outside_the_box_still_flies_into_it(self) -> None:
        # +$79 stays set for the whole kick action, so Souther re-tests the
        # box on every frame of the flight: the X half-width has to include
        # the character's own free-flight reach.
        myself = _myself(world_x=0, world_y=100)
        flight = reach.jump_attack_max_dx(myself.character_id)
        self.assertGreater(flight, 0)
        inside = _souther(
            world_x=reach.SOUTHER_JUMP_COUNTER_DIST_X + flight - 1,
            world_y=100,
            primary_state=1,
        )
        self.assertTrue(reach.souther_would_punish_jump(myself, {myself, inside}))
        beyond = _souther(
            world_x=reach.SOUTHER_JUMP_COUNTER_DIST_X + flight,
            world_y=100,
            primary_state=1,
        )
        self.assertFalse(reach.souther_would_punish_jump(myself, {myself, beyond}))

    def test_defeated_souther_never_counters(self) -> None:
        myself = _myself(world_x=160, world_y=100)
        souther = _souther(
            world_x=200, world_y=100, primary_state=1, health=0xFFFF
        )
        self.assertFalse(reach.souther_would_punish_jump(myself, {myself, souther}))

    def test_true_with_two_southers_in_the_box(self) -> None:
        # Round 6's pair: the predicate is a plain bool, so this is just
        # confirming a second Souther in range doesn't break anything.
        myself = _myself(world_x=160, world_y=100)
        first = _souther(slot="obj11", world_x=200, world_y=100, primary_state=1)
        second = _souther(slot="obj12", world_x=120, world_y=100, primary_state=1)
        self.assertTrue(
            reach.souther_would_punish_jump(myself, {myself, first, second})
        )


def _enemy(**overrides) -> Enemy:
    fields = dict(
        slot="obj01",
        type_id=0x20,
        world_x=100,
        world_y=100,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
    )
    fields.update(overrides)
    return Enemy(**fields)


class IsIncomingMeleeTests(unittest.TestCase):
    def test_promotes_a_committed_enemy_inside_the_caution_box(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        enemy = _enemy(
            slot="obj01", world_x=160, world_y=100, combat_phase=CombatPhase.ATTACKING
        )

        self.assertTrue(reach.is_incoming_melee(myself, enemy))

    def test_a_committed_enemy_out_of_lane_is_not_a_threat(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        enemy = _enemy(
            slot="obj01", world_x=110, world_y=60, combat_phase=CombatPhase.ATTACKING
        )

        self.assertFalse(reach.is_incoming_melee(myself, enemy))

    def test_a_calm_enemy_at_the_same_distance_is_not_a_threat(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        enemy = _enemy(slot="obj01", world_x=160, world_y=100)

        self.assertFalse(reach.is_incoming_melee(myself, enemy))

    def test_a_fast_committed_enemy_still_far_away_promotes_predictively(self) -> None:
        # Signal's slide (enemy-ai.md "Signal's slide is velocity, not a
        # hitbox"): no attack shape anywhere in its own animation set, so
        # attack_ranges stays empty and the only way to see this coming is
        # the velocity projection. 99px out (past Axel's 74px caution box)
        # but closing at the slide's own ~2.5 px per 60 Hz frame facing left,
        # which is 30px over reach.CLOSING_ENEMY_THREAT_FRAMES.
        myself = _myself(world_x=100, world_y=100)
        signal = _enemy(
            slot="obj01",
            type_id=0x24,
            world_x=199,
            world_y=100,
            combat_phase=CombatPhase.ATTACKING,
            facing_left=True,
            grunt_vel_x=-2.5,
            grunt_vel_y=0.0,
        )

        self.assertTrue(reach.is_incoming_melee(myself, signal))

    def test_a_committed_enemy_moving_away_is_not_promoted(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        signal = _enemy(
            slot="obj01",
            type_id=0x24,
            world_x=250,
            world_y=100,
            combat_phase=CombatPhase.ATTACKING,
            grunt_vel_x=25.0,
            grunt_vel_y=0.0,
        )

        self.assertFalse(reach.is_incoming_melee(myself, signal))

    def test_a_calm_enemy_closing_fast_is_still_not_a_threat(self) -> None:
        # Velocity alone never substitutes for the dangerous-phase gate --
        # an ordinary approaching Grunt (CombatPhase.NORMAL) always has
        # nonzero velocity and must not be promoted just for walking toward
        # the actor.
        myself = _myself(world_x=100, world_y=100)
        enemy = _enemy(
            slot="obj01",
            world_x=250,
            world_y=100,
            combat_phase=CombatPhase.NORMAL,
            grunt_vel_x=-25.0,
            grunt_vel_y=0.0,
        )

        self.assertFalse(reach.is_incoming_melee(myself, enemy))


class SoutherDashArrivesSoonTests(unittest.TestCase):
    """A committed Souther closes faster than any grunt and was invisible to
    ``too_close_to_keep_approaching``/``enemy_will_close_soon``: a ``Boss``
    populates no ``attack_ranges`` (so the caution box falls back to the
    actor's own punch reach) and no ``grunt_vel_*`` (so the predictive half
    projects him standing still). ``$161C6`` closes at 8px/frame.
    """

    def test_the_committed_dash_promotes_from_beyond_the_caution_box(self) -> None:
        myself = _myself(world_x=100, world_y=60)
        souther = _souther(
            world_x=190,
            world_y=60,
            combat_phase=CombatPhase.ATTACKING,
            primary_state=2,
            tactical=2,
            boss_dist_x=90,
        )
        self.assertTrue(reach.souther_dash_arrives_soon(myself, souther))
        self.assertTrue(reach.is_incoming_melee(myself, souther))

    def test_an_uncommitted_souther_at_the_same_range_does_not(self) -> None:
        myself = _myself(world_x=100, world_y=60)
        souther = _souther(world_x=190, world_y=60, primary_state=1, boss_dist_x=90)
        self.assertFalse(reach.souther_dash_arrives_soon(myself, souther))

    def test_off_lane_is_not_incoming_because_the_dash_cannot_steer(self) -> None:
        # $161C6 writes only +$1C and resolves within $18 of its lane, so an
        # actor already off that lane is genuinely not about to be hit --
        # which is exactly what DodgeSoutherSlash spent the tick achieving.
        myself = _myself(world_x=100, world_y=60)
        souther = _souther(
            world_x=190,
            world_y=110,
            combat_phase=CombatPhase.ATTACKING,
            primary_state=2,
            tactical=2,
            boss_dist_x=90,
            boss_dist_lane=50,
        )
        self.assertFalse(reach.souther_dash_arrives_soon(myself, souther))

    def test_beyond_the_dash_reach_is_not_incoming(self) -> None:
        myself = _myself(world_x=100, world_y=60)
        souther = _souther(
            world_x=400,
            world_y=60,
            combat_phase=CombatPhase.ATTACKING,
            primary_state=2,
            tactical=2,
            boss_dist_x=300,
        )
        self.assertFalse(reach.souther_dash_arrives_soon(myself, souther))


class HeldEnemyTests(unittest.TestCase):
    """``reach.held_enemy`` -- which body is actually in the actor's hands."""

    def test_the_rom_hold_link_wins_over_a_nearer_bystander(self) -> None:
        myself = _myself(
            world_x=100, world_y=100, action_state=0x60, held_enemy_slot="obj02"
        )
        near = _garcia(slot="obj01", world_x=112, world_y=100, attack_ranges=())
        held = _garcia(slot="obj02", world_x=140, world_y=100, attack_ranges=())

        self.assertIs(reach.held_enemy(myself, [near, held]), held)

    def test_falls_back_to_the_grabbed_phase(self) -> None:
        myself = _myself(world_x=100, world_y=100, action_state=0x60)
        near = _garcia(slot="obj01", world_x=112, world_y=100, attack_ranges=())
        held = _garcia(
            slot="obj02",
            world_x=140,
            world_y=100,
            attack_ranges=(),
            combat_phase=CombatPhase.GRABBED,
        )

        self.assertIs(reach.held_enemy(myself, [near, held]), held)

    def test_falls_back_to_contact_for_a_boss_that_announces_nothing(self) -> None:
        # A held Antonio reads primary $04 -- RECOVERY, the same byte as his
        # ordinary hit reaction -- and the player's +$60 keeps the weapon it
        # was already carrying. Contact is all that is left.
        myself = _myself(
            world_x=100, world_y=100, action_state=0x60, held_weapon_type=0x0B
        )
        antonio = _antonio(
            slot="obj00",
            world_x=140,
            world_y=100,
            combat_phase=CombatPhase.RECOVERY,
            primary_state=0x04,
        )
        far = _garcia(slot="obj01", world_x=400, world_y=100, attack_ranges=())

        self.assertIs(reach.held_enemy(myself, [antonio, far]), antonio)

    def test_nothing_while_not_holding(self) -> None:
        myself = _myself(world_x=100, world_y=100, action_state=0x02)
        near = _garcia(slot="obj01", world_x=112, world_y=100, attack_ranges=())

        self.assertIsNone(reach.held_enemy(myself, [near]))

    def test_no_enemy_is_in_hand_while_the_link_names_the_partner(self) -> None:
        # $3266 wrote the other player's object into +$4C. The fallbacks
        # would otherwise name these bystanders -- one GRABBED, one in
        # contact -- for the hold family to knee and suplex through the
        # partner.
        myself = _myself(
            world_x=100, world_y=100, action_state=0x66, held_enemy_slot="P2"
        )
        grabbed = _garcia(
            slot="obj01",
            world_x=90,
            world_y=100,
            attack_ranges=(),
            combat_phase=CombatPhase.GRABBED,
        )
        contact = _garcia(slot="obj02", world_x=120, world_y=100, attack_ranges=())

        self.assertIsNone(reach.held_enemy(myself, [grabbed, contact]))

    def test_no_grab_reason_survives_while_already_holding(self) -> None:
        # $AAA0 refuses a fresh grab while the actor's own +$4C is set.
        myself = _myself(
            world_x=100, world_y=100, action_state=0x60, held_enemy_slot="obj00"
        )
        antonio = _antonio(
            slot="obj00",
            world_x=140,
            world_y=100,
            combat_phase=CombatPhase.RECOVERY,
            primary_state=0x04,
        )

        self.assertEqual(reach.grab_reasons(set(), myself, antonio, [antonio]), frozenset())


class GrabReasonsTests(unittest.TestCase):
    """``reach.grab_reasons`` -- why a hold beats a strike, right now.

    Not "every enemy that could be grabbed": a grab costs the actor its
    attack for the walk-in and locks both bodies together, so this only
    reports the situations where that trade pays off -- see ``GrabReason``.
    """

    def test_promotes_the_front_enemy_when_another_is_at_the_actors_back(self) -> None:
        # Axel facing right: the enemy at x=60 is behind, inside
        # reach.rear_threats' box (56 x 24), so holding the one in front is
        # what turns the pincer into a backwards throw.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        front = _garcia(slot="obj01", world_x=130, world_y=100, attack_ranges=())
        behind = _garcia(slot="obj02", world_x=60, world_y=100, attack_ranges=())
        enemies = [front, behind]

        self.assertIn(
            GrabReason.CLEAR_REAR, reach.grab_reasons(set(), myself, front, enemies)
        )

    def test_promotes_a_body_with_a_charge_coming_in_behind_it(self) -> None:
        # The user's geometry: an enemy in front, and behind it a Signal
        # sliding in. His slide is velocity with no attack shape at all
        # (enemy-ai.md), so there is nothing to sidestep -- take the hold.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        front = _garcia(slot="obj01", world_x=136, world_y=100, attack_ranges=())
        signal = _signal(
            slot="obj02",
            world_x=190,
            world_y=100,
            combat_phase=CombatPhase.ATTACKING,
            facing_left=True,
            grunt_vel_x=-2.5,
        )
        enemies = [front, signal]

        self.assertIn(
            GrabReason.DODGE_CHARGE, reach.grab_reasons(set(), myself, front, enemies)
        )

    def test_a_charge_on_the_far_side_is_not_coming_through_the_body(self) -> None:
        # Same two enemies, but the Signal is on the *other* side of the
        # actor, so holding the front body puts nothing between them. The
        # same-side/further-away test is what keeps this from becoming
        # "grab whenever anybody swings".
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        front = _garcia(slot="obj01", world_x=136, world_y=100, attack_ranges=())
        signal = _signal(
            slot="obj02",
            world_x=40,
            world_y=100,
            combat_phase=CombatPhase.ATTACKING,
            facing_left=False,
            grunt_vel_x=2.5,
        )
        enemies = [front, signal]

        self.assertNotIn(
            GrabReason.DODGE_CHARGE, reach.grab_reasons(set(), myself, front, enemies)
        )

    def test_a_frontal_crowd_promotes_the_grabbable_body(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        front = _garcia(slot="obj01", world_x=130, world_y=100, attack_ranges=())
        side_a = _garcia(slot="obj02", world_x=145, world_y=110, attack_ranges=())
        side_b = _garcia(slot="obj03", world_x=120, world_y=85, attack_ranges=())
        enemies = [front, side_a, side_b]
        context = {Surrounded(actor_slot="P1", in_front=3, behind=0)}

        self.assertIn(
            GrabReason.WHILE_SURROUNDED, reach.grab_reasons(context, myself, front, enemies)
        )

    def test_no_crowd_opportunity_without_the_surrounded_judgment(self) -> None:
        # The gate is the Surrounded token itself, not proximity: two enemies
        # on the same side are an ordinary fight, not an encirclement.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        front = _garcia(slot="obj01", world_x=130, world_y=100, attack_ranges=())
        second = _garcia(slot="obj02", world_x=145, world_y=110, attack_ranges=())
        enemies = [front, second]

        self.assertNotIn(
            GrabReason.WHILE_SURROUNDED, reach.grab_reasons(set(), myself, front, enemies)
        )

    def test_the_rear_enemy_alone_is_not_its_own_reason_to_be_grabbed(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        behind = _garcia(slot="obj02", world_x=60, world_y=100, attack_ranges=())

        self.assertEqual(reach.grab_reasons(set(), myself, behind, [behind]), frozenset())

    def test_no_opportunity_from_a_lone_enemy_in_front(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        front = _garcia(slot="obj01", world_x=130, world_y=100, attack_ranges=())

        self.assertEqual(reach.grab_reasons(set(), myself, front, [front]), frozenset())

    def test_jack_earns_no_reason_of_his_own(self) -> None:
        # On his back, facing him: EngageJack takes that hold (jack.py), so
        # GrabEnemy needs no reason for it.
        myself = _myself(world_x=150, world_y=100, facing_left=True)
        jack = _jack(slot="obj01", world_x=130, world_y=100, facing_left=True)

        self.assertEqual(reach.grab_reasons(set(), myself, jack, [jack]), frozenset())

    def test_does_not_promote_jack_when_he_is_facing_the_actor(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        jack = _jack(slot="obj01", world_x=130, world_y=100, facing_left=True)

        self.assertEqual(reach.grab_reasons(set(), myself, jack, [jack]), frozenset())

    def test_promotes_nora_on_her_own(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        nora = _nora(slot="obj02", world_x=130, world_y=100)

        self.assertEqual(
            reach.grab_reasons(set(), myself, nora, [nora]),
            frozenset({GrabReason.DEAD_ZONE}),
        )

    def test_a_committed_enemy_is_not_grabbable(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        nora = _nora(slot="obj02", world_x=130, world_y=100, combat_phase=CombatPhase.ATTACKING)

        self.assertEqual(reach.grab_reasons(set(), myself, nora, [nora]), frozenset())

    def test_a_knocked_down_enemy_is_not_grabbable(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        nora = _nora(slot="obj02", world_x=130, world_y=100, combat_phase=CombatPhase.KNOCKDOWN)

        self.assertEqual(reach.grab_reasons(set(), myself, nora, [nora]), frozenset())

    def test_a_stunned_enemy_is_still_grabbable(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        nora = _nora(slot="obj02", world_x=130, world_y=100, combat_phase=CombatPhase.STUNNED)

        self.assertEqual(
            reach.grab_reasons(set(), myself, nora, [nora]),
            frozenset({GrabReason.DEAD_ZONE}),
        )

    def test_bosses_are_out_of_scope(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        boss = Abadede(
            slot="obj01",
            type_id=0x30,
            world_x=130,
            world_y=100,
            health=40,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
        )
        behind = _garcia(slot="obj02", world_x=60, world_y=100, attack_ranges=())

        # The boss would otherwise qualify (grabbable phase, an enemy at the
        # actor's back); the Grunt behind is only its own rear threat, which
        # is not a reason to grab it.
        self.assertEqual(reach.grab_reasons(set(), myself, boss, [boss, behind]), frozenset())

    def test_souther_is_never_a_grab_reason_case(self) -> None:
        # His hold is the engage's own walk-in (EngageSouther), from the lane
        # and at the moment souther.plan_engage picks -- not a reason
        # could_grab_enemy weighs against a strike.
        myself = _myself(world_x=160, world_y=100)
        for primary, phase in (
            (1, CombatPhase.NORMAL),
            (3, CombatPhase.RECOVERY),
            (4, CombatPhase.RECOVERY),
        ):
            with self.subTest(primary=primary):
                souther = _souther(
                    world_x=180, world_y=100, combat_phase=phase, primary_state=primary
                )
                self.assertEqual(
                    reach.grab_reasons(set(), myself, souther, [souther]), frozenset()
                )


def _connects(band, actor, enemy, verb_cls) -> bool:
    return reach.connects(band, actor, enemy, kinematics.connect_frames(verb_cls, actor, enemy))


class FramesUntilMeleeLandsTests(unittest.TestCase):
    """The clock the hold decision runs on -- see reach.frames_until_melee_lands.

    "Is it incoming" and "when does it land" have to agree, so this is built
    out of the same predicates rather than out of new arithmetic.
    """

    def test_a_calm_enemy_is_never_landing(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        enemy = _enemy(world_x=110, world_y=100)

        self.assertIsNone(reach.frames_until_melee_lands(myself, enemy))

    def test_an_attacker_already_in_range_lands_now(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        enemy = _enemy(world_x=110, world_y=100, combat_phase=CombatPhase.ATTACKING)

        self.assertEqual(reach.frames_until_melee_lands(myself, enemy), 0)

    def test_a_distant_attacker_is_not_coming_at_all(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        enemy = _enemy(world_x=400, world_y=100, combat_phase=CombatPhase.ATTACKING)

        self.assertIsNone(reach.frames_until_melee_lands(myself, enemy))

    def test_the_soonest_of_several_is_what_is_left(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        near = _enemy(
            slot="obj01", world_x=110, world_y=100, combat_phase=CombatPhase.ATTACKING
        )
        far = _enemy(slot="obj02", world_x=400, world_y=100)

        self.assertEqual(
            reach.frames_until_any_melee_lands(myself, [near, far]), 0
        )

    def test_an_ignored_slot_does_not_shorten_the_clock(self) -> None:
        # The body in the actor's hands: attacking or not, it cannot hit
        # anyone while held.
        myself = _myself(world_x=100, world_y=100)
        held = _enemy(
            slot="held", world_x=110, world_y=100, combat_phase=CombatPhase.ATTACKING
        )

        self.assertIsNone(
            reach.frames_until_any_melee_lands(
                myself, [held], ignore_slots=frozenset({"held"})
            )
        )


class ConnectsBandTimelineTests(unittest.TestCase):
    """Axel (character_id 0): punch band 16..50, rear-behind band 40, jump
    kick 50..60 (controls-and-input.md).

    Covers ``reach.connects`` (the per-move timeline union) together with
    each band predicate it wraps -- what used to be ``inference.check_for_
    targets_in_reach``'s own per-tick token production, now called directly
    by ``decide.py``'s ``_targets_in_reach``/``_actionable_targets``.
    """

    def test_enemy_in_front_inside_the_punch_band(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        enemy = _enemy(world_x=130, world_y=100)

        self.assertTrue(_connects(reach.punch_would_connect, myself, enemy, Punch))
        self.assertTrue(reach.enemy_actionable(myself, enemy, [enemy]))
        self.assertFalse(_connects(reach.in_jump_attack_band, myself, enemy, JumpAttack))

    def test_enemy_behind_beyond_the_tolerance_is_not_punch_reach(self) -> None:
        # The raw band ignores facing; a forward strike cannot hit backwards.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        enemy = _enemy(world_x=70, world_y=100)

        self.assertFalse(_connects(reach.punch_would_connect, myself, enemy, Punch))
        self.assertTrue(_connects(reach.in_rear_band, myself, enemy, RearAttack))

    def test_rear_band_alone_is_not_actionable(self) -> None:
        # A behind enemy the actor could simply turn toward: the chord is not
        # warranted (not boxed in, not inside the punch dead zone), so
        # could_walk_to_near_enemy must still be free to turn around.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        enemy = _enemy(world_x=70, world_y=100)

        self.assertFalse(reach.enemy_actionable(myself, enemy, [enemy]))

    def test_jump_kick_gap(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        enemy = _enemy(world_x=155, world_y=100)

        self.assertTrue(_connects(reach.in_jump_attack_band, myself, enemy, JumpAttack))
        self.assertFalse(_connects(reach.punch_would_connect, myself, enemy, Punch))

    def test_ignores_enemies_outside_the_playable_lane(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        unreachable = _enemy(world_x=130, world_y=400)

        self.assertEqual(reach.live_enemies({myself, unreachable}), [])

    def test_enemy_in_front_within_close_combat_range_is_grab_reach(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        enemy = _enemy(world_x=130, world_y=100)

        self.assertTrue(_connects(reach.grab_would_connect, myself, enemy, GrabEnemy))

    def test_enemy_beyond_the_punch_outer_edge_is_not_grab_reach(self) -> None:
        # Axel's outer edge is 50px; the walk-in is only worth committing to
        # from inside close-combat range.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        enemy = _enemy(world_x=155, world_y=100)

        self.assertFalse(_connects(reach.grab_would_connect, myself, enemy, GrabEnemy))

    def test_an_enemy_walking_into_the_punch_band_is_already_in_punch_reach(self) -> None:
        # dx=58 is outside Axel's 16..50 band right now, but the strike
        # damages from frame 3 to frame 12, and the enemy is inside the box
        # for most of that span: the punch arms as it arrives rather than
        # starting from scratch once it has.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        arriving = _enemy(world_x=158, world_y=100, grunt_vel_x=-2.0)

        self.assertTrue(_connects(reach.punch_would_connect, myself, arriving, Punch))

    def test_an_enemy_walking_in_close_is_still_punchable(self) -> None:
        # THE regression this whole family has to guard. Judging the punch at
        # a single future instant projected this enemy into the punch's own
        # *inner* dead zone (below Axel's 16px edge), which deleted the
        # punch reach, handed the tick to could_walk_to_near_enemy and had
        # the actor walk into an enemy it should have been hitting -- while
        # promoting the slow RearAttack chord at point-blank range, since a
        # target inside the dead zone is what makes that chord "warranted".
        # Measured over a swept pipeline against the previous commit.
        #
        # The move's damaging span is what covers the target's movement, and
        # frame 0 is always part of it, so a prediction can only ever add an
        # attack -- never remove the one the observed position already gives.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        closing = _enemy(world_x=120, world_y=100, grunt_vel_x=-2.0)

        self.assertTrue(_connects(reach.punch_would_connect, myself, closing, Punch))
        self.assertTrue(reach.enemy_actionable(myself, closing, [closing]))

    def test_a_walking_enemy_never_loses_a_band_it_currently_occupies(self) -> None:
        # The additive guarantee, swept: whatever the observed position
        # offers, every velocity must still offer.
        def _bands(actor, enemy) -> set:
            found = set()
            if _connects(reach.punch_would_connect, actor, enemy, Punch):
                found.add("PUNCH")
            if _connects(reach.in_rear_band, actor, enemy, RearAttack):
                found.add("REAR")
            if _connects(reach.in_jump_attack_band, actor, enemy, JumpAttack):
                found.add("JUMP_ATTACK")
            if _connects(reach.grab_would_connect, actor, enemy, GrabEnemy):
                found.add("GRAB")
            if reach.enemy_actionable(actor, enemy, [enemy]):
                found.add("ACTIONABLE")
            return found

        myself = _myself(world_x=100, world_y=100, facing_left=False)
        for dx in range(8, 130, 2):
            still = _enemy(world_x=100 + dx, world_y=100)
            baseline = _bands(myself, still)
            for vel in (-3.0, -2.0, -1.0, 1.0, 2.0, 3.0):
                moving = _enemy(world_x=100 + dx, world_y=100, grunt_vel_x=vel)
                with self.subTest(dx=dx, vel=vel):
                    self.assertTrue(baseline <= _bands(myself, moving))

    def test_adams_slow_chord_reaches_a_target_walking_into_it(self) -> None:
        # Adam's chord damages from frame 21 to frame 38 -- more than half a
        # second -- so a target 90px behind him and walking in is inside his
        # 42px box while it is still swinging. Axel's, damaging at frames
        # 3..12, is long over before that same target arrives, and his box is
        # 40px: the two characters genuinely disagree about this target, and
        # only a per-character timeline can say so.
        axel = _myself(world_x=100, world_y=100, facing_left=False)
        adam = _myself(
            world_x=100, world_y=100, facing_left=False, character_id=1, character_name="Adam"
        )
        arriving = _enemy(world_x=30, world_y=100, grunt_vel_x=2.0)

        self.assertTrue(_connects(reach.in_rear_band, adam, arriving, RearAttack))
        self.assertFalse(_connects(reach.in_rear_band, axel, arriving, RearAttack))

    def test_a_jump_kick_arms_for_an_enemy_walking_into_its_range(self) -> None:
        # dx=70 is past Axel's 50..60 kick band, but the launch is 5 crouch
        # frames away ($1FC0) and the enemy covers 14px of that on its own.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        arriving = _enemy(world_x=170, world_y=100, grunt_vel_x=-2.0)

        self.assertTrue(_connects(reach.in_jump_attack_band, myself, arriving, JumpAttack))

    def test_a_jump_kick_is_never_armed_from_beyond_its_own_flight(self) -> None:
        # The kick's lead is its crouch, never its whole flight: solving the
        # full interception instead launched kicks from 100+px on the
        # assumption the target kept closing for all 25 frames.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        far = _enemy(world_x=204, world_y=100, grunt_vel_x=-2.0)

        self.assertFalse(_connects(reach.in_jump_attack_band, myself, far, JumpAttack))

    def test_a_grab_walk_in_still_offers_a_target_it_would_reach(self) -> None:
        # Already inside the walk-in range (dx=40) and retreating slowly:
        # the walk-in arrives essentially at once, so the hold is still on
        # offer -- a lead must not make the AI refuse grabs it can take.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        retreating = _enemy(world_x=140, world_y=100, grunt_vel_x=2.0)

        self.assertTrue(_connects(reach.grab_would_connect, myself, retreating, GrabEnemy))

    def test_a_walk_in_that_would_never_catch_up_is_not_grab_reach(self) -> None:
        # 25px beyond Axel's own close-combat edge and retreating at 2 px per
        # frame against his ROM walk speed of 3 ($3670): the gap closes at
        # 1 px/frame, so the walk-in arrives far too late to be worth
        # committing to -- and the prediction lands well outside the range.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        retreating = _enemy(world_x=175, world_y=100, grunt_vel_x=2.0)

        self.assertFalse(_connects(reach.grab_would_connect, myself, retreating, GrabEnemy))

    def test_a_stationary_enemy_is_judged_exactly_where_it_stands(self) -> None:
        # The no-velocity case must be untouched by any of the above: every
        # projection is the identity, so the bands answer as they always did.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        still = _enemy(world_x=130, world_y=100)

        self.assertTrue(_connects(reach.punch_would_connect, myself, still, Punch))
        self.assertTrue(_connects(reach.grab_would_connect, myself, still, GrabEnemy))
        self.assertTrue(reach.enemy_actionable(myself, still, [still]))

    def test_grab_reach_shares_the_punch_band_lane(self) -> None:
        # `$AAA0` reads the actor's own forward attack box -- the punch's box
        # -- so the two bands share a lane tolerance. They used to differ by
        # two pixels (10 against 12), and those two pixels sat exactly where
        # `decide._actionable_targets` stops the approach: the AI settled at
        # 12px of lane, called the punch in range, and could never reach the
        # hold from the position it had chosen to stop at. The bodies are
        # 16px tall, so 12px of lane is still an overlap.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        enemy = _enemy(world_x=130, world_y=111)

        self.assertTrue(_connects(reach.punch_would_connect, myself, enemy, Punch))
        self.assertTrue(_connects(reach.grab_would_connect, myself, enemy, GrabEnemy))

    def test_enemy_further_off_lane_than_the_band_is_not_grab_reach(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        enemy = _enemy(world_x=130, world_y=100 + reach.GRAB_RANGE_Y + 8)

        self.assertFalse(_connects(reach.grab_would_connect, myself, enemy, GrabEnemy))

    def test_enemy_behind_beyond_the_tolerance_is_not_grab_reach(self) -> None:
        # The ROM's contact test reads the actor's *attack* box, which points
        # forward -- a behind enemy is turned toward first, not walked into.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        enemy = _enemy(world_x=70, world_y=100)

        self.assertFalse(_connects(reach.grab_would_connect, myself, enemy, GrabEnemy))


class WeaponUpgradeRankTests(unittest.TestCase):
    def test_higher_rank_than_held_is_an_upgrade(self) -> None:
        myself = _myself(held_weapon_type=0x0A)  # bat, rank 4
        knife = Weapon(slot="w1", world_x=120, world_y=100, weapon_type=0x08)
        camera = CameraRange(left=0, right=400, top=0, bottom=112)

        self.assertEqual(reach.weapon_upgrade_rank(myself, knife, camera), 5)

    def test_lower_rank_than_held_is_not_an_upgrade(self) -> None:
        myself = _myself(held_weapon_type=0x0A)  # bat, rank 4
        pepper = Weapon(slot="w2", world_x=130, world_y=100, weapon_type=0x0C)
        camera = CameraRange(left=0, right=400, top=0, bottom=112)

        self.assertIsNone(reach.weapon_upgrade_rank(myself, pepper, camera))

    def test_off_camera_weapons_are_ignored(self) -> None:
        myself = _myself(held_weapon_type=0)
        knife = Weapon(slot="w1", world_x=900, world_y=100, weapon_type=0x08)
        camera = CameraRange(left=0, right=400, top=0, bottom=112)

        self.assertIsNone(reach.weapon_upgrade_rank(myself, knife, camera))

    def test_worn_out_weapons_are_ignored(self) -> None:
        myself = _myself(held_weapon_type=0)
        spent = Weapon(slot="w1", world_x=120, world_y=100, weapon_type=0x08, wear=3)
        camera = CameraRange(left=0, right=400, top=0, bottom=112)

        self.assertIsNone(reach.weapon_upgrade_rank(myself, spent, camera))

    def test_no_camera_means_no_upgrade(self) -> None:
        myself = _myself(held_weapon_type=0)
        knife = Weapon(slot="w1", world_x=120, world_y=100, weapon_type=0x08)

        self.assertIsNone(reach.weapon_upgrade_rank(myself, knife, None))


def _jack(**overrides) -> Jack:
    fields = dict(
        slot="obj01",
        type_id=0x27,
        world_x=100,
        world_y=100,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
        has_projectile=False,
    )
    fields.update(overrides)
    return Jack(**fields)


class ProjectileThreatensTests(unittest.TestCase):
    def test_heading_toward_the_actor_in_lane_threatens(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        threat = Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x1E
        )

        self.assertTrue(reach.projectile_threatens(threat, myself))

    def test_flying_away_does_not_threaten(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        benign = Projectile(
            slot="obj11", world_x=30, world_y=100, vel_x=-1.5, vel_z=0.0, type_id=0x1E
        )

        self.assertFalse(reach.projectile_threatens(benign, myself))

    def test_out_of_lane_does_not_threaten(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        off_lane = Projectile(
            slot="obj11", world_x=150, world_y=200, vel_x=-5.0, vel_z=0.0, type_id=0x1E
        )

        self.assertFalse(reach.projectile_threatens(off_lane, myself))

    def test_stationary_hazard_threatens_only_when_overlapping(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        overlapping = Projectile(
            slot="obj12", world_x=110, world_y=100, vel_x=0.0, vel_z=0.5, type_id=0x1E
        )
        far = Projectile(
            slot="obj13", world_x=300, world_y=100, vel_x=0.0, vel_z=0.5, type_id=0x1E
        )

        self.assertTrue(reach.projectile_threatens(overlapping, myself))
        self.assertFalse(reach.projectile_threatens(far, myself))


class ProjectileTicksToImpactTests(unittest.TestCase):
    def test_scales_with_distance_over_speed(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        projectile = Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x1E
        )

        self.assertEqual(reach.projectile_ticks_to_impact(projectile, myself), 10.0)

    def test_stationary_projectile_is_already_arrived(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        projectile = Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=0.0, vel_z=0.0, type_id=0x1E
        )

        self.assertEqual(reach.projectile_ticks_to_impact(projectile, myself), 0.0)


class AntonioStillHoldingBoomerangTests(unittest.TestCase):
    def test_attached_boomerang_is_still_held(self) -> None:
        antonio = _antonio(world_x=150, world_y=100)
        boomerang = Projectile(
            slot="obj10",
            world_x=148,
            world_y=100,
            vel_x=-0.5,
            vel_z=0.0,
            type_id=reach.ANTONIO_BOOMERANG_TYPE_ID,
        )

        self.assertTrue(reach.antonio_still_holding_boomerang(boomerang, {antonio}))

    def test_thrown_boomerang_is_no_longer_held(self) -> None:
        antonio = _antonio(world_x=300, world_y=100)
        boomerang = Projectile(
            slot="obj10",
            world_x=150,
            world_y=100,
            vel_x=-8.0,
            vel_z=0.0,
            type_id=reach.ANTONIO_BOOMERANG_TYPE_ID,
        )

        self.assertFalse(reach.antonio_still_holding_boomerang(boomerang, {antonio}))

    def test_other_projectile_types_are_never_his_boomerang(self) -> None:
        antonio = _antonio(world_x=150, world_y=100)
        knife = Projectile(
            slot="obj10", world_x=148, world_y=100, vel_x=-0.5, vel_z=0.0, type_id=0x1E
        )

        self.assertFalse(reach.antonio_still_holding_boomerang(knife, {antonio}))


class IsSoutherClawTests(unittest.TestCase):
    def test_claw_and_afterimage_types_are_unthrowable(self) -> None:
        for type_id in (0x98, 0x99):
            claw = Projectile(
                slot="obj20",
                type_id=type_id,
                world_x=180,
                world_y=100,
                vel_x=-8.0,
                vel_z=0.0,
            )
            self.assertTrue(reach.is_souther_claw(claw), f"type {type_id:#04x}")

    def test_other_types_are_not_the_claw(self) -> None:
        other = Projectile(
            slot="obj20", type_id=0x1E, world_x=180, world_y=100, vel_x=-8.0, vel_z=0.0
        )
        self.assertFalse(reach.is_souther_claw(other))


class JackStillJugglingTests(unittest.TestCase):
    """The axe's own +$30/+$31 say whether it has a flight (ai/jack.py)."""

    def _axe(self, state: int, flags: int) -> Projectile:
        return Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=-10.0, vel_z=0.0, type_id=0x28,
            state=state, flags_31=flags,
        )

    def test_ignored_while_juggled_tossed_or_dropped(self) -> None:
        jack = _jack(slot="obj20", world_x=140, world_y=100, has_projectile=True)
        for state in (1, 2, 3):
            self.assertTrue(reach.jack_still_juggling(self._axe(state, 0x01), {jack}))

    def test_a_throw_waiting_for_his_release_frame_is_not_out_yet(self) -> None:
        # 64 px over his head until his frame 1: nothing to step off.
        self.assertTrue(reach.jack_still_juggling(self._axe(4, 0x01), set()))

    def test_a_released_throw_is_out_even_point_blank(self) -> None:
        # The old distance guess called this one "still juggling" within 40 px
        # of him -- exactly where his aligned throw is released.
        jack = _jack(slot="obj20", world_x=140, world_y=100, has_projectile=True)
        self.assertFalse(reach.jack_still_juggling(self._axe(4, 0x03), {jack}))

    def test_other_projectile_types_are_never_his_axe(self) -> None:
        jack = _jack(slot="obj20", world_x=140, world_y=100, has_projectile=True)
        knife = Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x1E
        )

        self.assertFalse(reach.jack_still_juggling(knife, {jack}))


class TableInPunchBandTests(unittest.TestCase):
    """Round 8's thrown table (``reach.TABLE_TYPE_ID``) -- same shape as
    ``decide._boomerang_in_punch_band``, mirrored here for ``could_hit_table``."""

    def test_in_lane_and_in_range_connects(self) -> None:
        myself = _myself(world_x=100, world_y=100)

        self.assertTrue(reach.table_in_punch_band(myself, 112, 100))

    def test_out_of_lane_does_not_connect(self) -> None:
        myself = _myself(world_x=100, world_y=100)

        self.assertFalse(reach.table_in_punch_band(myself, 112, 130))

    def test_too_far_on_x_does_not_connect(self) -> None:
        myself = _myself(world_x=100, world_y=100)

        self.assertFalse(reach.table_in_punch_band(myself, 300, 100))


def _partner(**overrides) -> Partner:
    fields = dict(
        slot="P2",
        player_index=2,
        character_id=2,
        character_name="Blaze",
        world_x=130,
        world_y=100,
        health=80,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=True,
        combat_phase=CombatPhase.NORMAL,
        action_state=0x02,
        is_airborne=False,
    )
    fields.update(overrides)
    return Partner(**fields)


class WalkingBoxGrabTests(unittest.TestCase):
    """A walk into the other player is a hold on them -- ``$4478``.

    The actor is Axel (walking box 0..16, 3.0 px/frame on X and 2.375 on the
    lane), the partner Blaze (body within 12 of her origin). One tick sweeps
    ``reach.WALK_SWEEP_FRAMES`` (4) frames of walk: 12 px on X, 9.5 on the lane.
    """

    def _grabs(self, actor, partner, *, step_x=0, step_y=0) -> bool:
        return reach.walking_box_would_grab(actor, partner, step_x=step_x, step_y=step_y)

    def test_the_walk_boxes_are_the_roms_own(self) -> None:
        # Shapes $4D / $CF / $8F, the walk animation's box in each set.
        self.assertEqual([reach.walk_box_reach_x(c) for c in (0, 1, 2)], [16, 20, 19])
        # Unknown: the longest, since this reach keeps the actor out.
        self.assertEqual(reach.walk_box_reach_x(None), 20)

    def test_walking_toward_the_partner_takes_the_hold(self) -> None:
        actor = _myself(world_x=100)
        # Her body 128..152; the box 100..116, swept 12 px on, just touches.
        self.assertTrue(self._grabs(actor, _partner(world_x=140), step_x=1))
        self.assertFalse(self._grabs(actor, _partner(world_x=141), step_x=1))

    def test_walking_away_takes_no_hold(self) -> None:
        actor = _myself(world_x=100)
        self.assertFalse(self._grabs(actor, _partner(world_x=120), step_x=-1))

    def test_turning_toward_a_partner_behind_takes_the_hold(self) -> None:
        # ReleasePartner's aftermath: the ROM leaves the actor facing away,
        # and the X press toward her is what turns the box onto her.
        actor = _myself(world_x=100, facing_left=True)
        partner = _partner(world_x=125)
        self.assertTrue(self._grabs(actor, partner, step_x=1))
        self.assertFalse(self._grabs(actor, partner, step_y=-1))
        self.assertFalse(self._grabs(actor, partner, step_x=-1))

    def test_a_lane_walk_keeps_the_box_facing_the_way_it_faces(self) -> None:
        # $2D00: Up alone is $0A, Down alone $0E, both through $2EE8, which
        # keeps the facing bit -- the same walk animation, the same box.
        actor = _myself(world_x=100, world_y=100)
        partner = _partner(world_x=120, world_y=120)
        self.assertTrue(self._grabs(actor, partner, step_y=1))  # into her lane
        self.assertFalse(self._grabs(actor, partner, step_y=-1))  # out of it
        facing_away = replace(actor, facing_left=True)
        self.assertFalse(self._grabs(facing_away, partner, step_y=1))

    def test_lanes_sixteen_apart_still_touch(self) -> None:
        # $450C compares with bgt/blt/bge: touching boxes are contact.
        actor = _myself(world_x=100, world_y=100)
        self.assertTrue(self._grabs(actor, _partner(world_x=120, world_y=116), step_x=1))
        self.assertFalse(self._grabs(actor, _partner(world_x=120, world_y=117), step_x=1))

    def test_standing_still_puts_out_no_box(self) -> None:
        # Idle $02 plays animation 0, which names no attack box.
        self.assertFalse(self._grabs(_myself(world_x=100), _partner(world_x=110)))

    def test_a_partner_walking_in_closes_the_gap_too(self) -> None:
        # +$1C: her own walk is swept over the same frames.
        actor = _myself(world_x=100)
        standing = _partner(world_x=150)
        self.assertFalse(self._grabs(actor, standing, step_x=1))
        self.assertTrue(self._grabs(actor, replace(standing, vel_x=-3.25), step_x=1))

    def test_the_live_body_box_widens_the_span(self) -> None:
        box = Hitbox(x0=120, x1=160, y0=92, y1=108, z0=-50, z1=0)
        self.assertEqual(
            reach.player_body_span_x(_partner(world_x=150, hitbox=box)), (120, 162)
        )


class NearbyEnemiesTests(unittest.TestCase):
    """``reach.nearby_enemies`` -- the cluster estimate ``Supplex``/
    ``ThrowHeldEnemy`` score a bonus with (priority._hold_cluster_bonus),
    same box as ``Surrounded``'s (SURROUNDED_NEAR_X/_Y), centred on a body
    instead of the actor."""

    def test_finds_bodies_inside_the_box_and_excludes_the_anchor(self) -> None:
        anchor = _garcia(slot="held", world_x=200, world_y=100)
        close = _garcia(slot="obj02", world_x=200 + reach.SURROUNDED_NEAR_X, world_y=100)
        self.assertEqual(reach.nearby_enemies(anchor, [anchor, close]), [close])

    def test_excludes_bodies_outside_the_box_on_either_axis(self) -> None:
        anchor = _garcia(slot="held", world_x=200, world_y=100)
        too_far_x = _garcia(
            slot="obj02", world_x=200 + reach.SURROUNDED_NEAR_X + 1, world_y=100
        )
        too_far_y = _garcia(
            slot="obj03", world_x=200, world_y=100 + reach.SURROUNDED_NEAR_Y + 1
        )
        self.assertEqual(reach.nearby_enemies(anchor, [anchor, too_far_x, too_far_y]), [])

    def test_counts_more_than_one_clustered_body(self) -> None:
        anchor = _garcia(slot="held", world_x=200, world_y=100)
        near_1 = _garcia(slot="obj02", world_x=220, world_y=100)
        near_2 = _garcia(slot="obj03", world_x=180, world_y=108)
        self.assertCountEqual(
            reach.nearby_enemies(anchor, [anchor, near_1, near_2]), [near_1, near_2]
        )


if __name__ == "__main__":
    unittest.main()
