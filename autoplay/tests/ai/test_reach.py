"""Tests for the reach predicates that read a real ``AttackRange``.

The rest of ``reach.py`` is exercised through ``test_decide.py``/
``test_priority.py`` (which call these bands directly, once per tick); this
file covers the predicates that answer questions about the *enemy's* reach
rather than the actor's, since those are the ones that changed from an
assumed margin to the ROM's own geometry.
"""

import unittest

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
    Projectile,
    Punch,
    RearAttack,
    Signal,
    Souther,
    Surrounded,
    Weapon,
)
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
    def test_jack_facing_the_actor_from_behind_is_warranted(self) -> None:
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
        self.assertTrue(reach.rear_attack_is_warranted(actor, jack, [jack]))

    def test_on_jacks_back_the_chord_is_not_warranted(self) -> None:
        # Actor overshot to x=150 facing right; Jack at 130 facing left.
        actor = _myself(world_x=150, world_y=100, facing_left=False)
        jack = Jack(
            slot="obj01",
            type_id=0x27,
            world_x=130,
            world_y=100,
            health=10,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
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


class AntonioWillKickTests(unittest.TestCase):
    def test_fires_when_already_in_state_2(self) -> None:
        myself = _myself(world_x=160, world_y=100)
        antonio = _antonio(
            combat_phase=CombatPhase.ATTACKING,
            primary_state=2,
            boss_dist_x=40,
            boss_dist_lane=4,
        )
        self.assertTrue(reach.antonio_will_kick(antonio, myself))

    def test_committed_kick_off_lane_is_not_a_threat(self) -> None:
        myself = _myself(world_x=160, world_y=100)
        antonio = _antonio(
            combat_phase=CombatPhase.ATTACKING,
            primary_state=2,
            boss_dist_x=40,
            boss_dist_lane=24,
        )
        self.assertFalse(reach.antonio_will_kick(antonio, myself))

    def test_fires_when_standing_still_inside_the_stationary_window(self) -> None:
        myself = _myself(world_x=160, world_y=100, vel_x=0.0)
        antonio = _antonio(
            world_x=200,
            facing_left=True,
            boss_dist_x=40,
            boss_dist_lane=4,
            primary_state=1,
        )
        self.assertTrue(reach.antonio_will_kick(antonio, myself))

    def test_fires_once_the_dash_is_committed(self) -> None:
        myself = _myself(world_x=3808, world_y=33)
        antonio = _antonio(
            world_x=3848,
            world_y=16,
            boss_dist_x=40,
            boss_dist_lane=17,
            primary_state=1,
            tactical=0x08,
        )
        self.assertTrue(reach.antonio_will_kick(antonio, myself))

    def test_uncommitted_dash_window_is_not_enough(self) -> None:
        # The dash *window* is the whole fight range; firing here made
        # DodgeAntonioKick win every tick and never attack.
        myself = _myself(world_x=3808, world_y=33, vel_x=3.0)
        antonio = _antonio(
            world_x=3848,
            world_y=16,
            boss_dist_x=40,
            boss_dist_lane=17,
            primary_state=1,
            tactical=0,
        )
        self.assertFalse(reach.antonio_will_kick(antonio, myself))

    def test_does_not_fire_when_off_lane(self) -> None:
        myself = _myself(world_x=160, world_y=100, vel_x=0.0)
        antonio = _antonio(
            world_x=200,
            boss_dist_x=40,
            boss_dist_lane=24,
            primary_state=1,
        )
        self.assertFalse(reach.antonio_will_kick(antonio, myself))

    def test_does_not_fire_when_far_on_x(self) -> None:
        myself = _myself(world_x=40, world_y=100, vel_x=0.0)
        antonio = _antonio(
            world_x=200,
            boss_dist_x=0x80,  # 128, outside the dash window too
            boss_dist_lane=4,
            primary_state=1,
        )
        self.assertFalse(reach.antonio_will_kick(antonio, myself))

    def test_does_not_fire_when_target_unavailable(self) -> None:
        myself = _myself(world_x=160, world_y=100)
        antonio = _antonio(target_unavailable=1, combat_phase=CombatPhase.ATTACKING)
        self.assertFalse(reach.antonio_will_kick(antonio, myself))

    def test_closing_uses_the_wider_window(self) -> None:
        # Antonio faces left (looking at a player on his left). Player
        # walking right (vel > 0) is walking toward him -> $78 window.
        myself = _myself(world_x=100, world_y=100, vel_x=3.0)
        antonio = _antonio(
            world_x=200,
            facing_left=True,
            boss_dist_x=0x70,  # 112, inside $78, outside $50/$68
            boss_dist_lane=4,
            primary_state=1,
        )
        self.assertTrue(reach.antonio_will_kick(antonio, myself))


class SoutherWillSlashTests(unittest.TestCase):
    def test_fires_when_already_committed(self) -> None:
        myself = _myself(world_x=160, world_y=100)
        souther = _souther(
            combat_phase=CombatPhase.ATTACKING, primary_state=2, boss_dist_lane=60
        )
        # Primary $02 is the whole committed claw; unlike Antonio's kick there
        # is no lane gate left to satisfy -- $161C6 closes the lane itself.
        self.assertTrue(reach.souther_will_slash(souther, myself))

    def test_stationary_actor_uses_the_middle_window(self) -> None:
        myself = _myself(world_x=160, world_y=100, vel_x=0.0)
        inside = _souther(boss_dist_x=reach.SOUTHER_SLASH_DIST_STATIONARY - 1)
        self.assertTrue(reach.souther_will_slash(inside, myself))
        outside = _souther(boss_dist_x=reach.SOUTHER_SLASH_DIST_STATIONARY)
        self.assertFalse(reach.souther_will_slash(outside, myself))

    def test_closing_actor_gets_the_widest_window(self) -> None:
        # Souther faces left, so a positive vel_x is the actor walking into
        # him: the ROM's `neg`-then-`bmi` path, threshold $68.
        myself = _myself(world_x=160, world_y=100, vel_x=3.0)
        souther = _souther(
            facing_left=True, boss_dist_x=reach.SOUTHER_SLASH_DIST_CLOSING - 1
        )
        self.assertTrue(reach.souther_will_slash(souther, myself))
        # The same distance while backing away is outside the tighter window.
        fleeing = _myself(world_x=160, world_y=100, vel_x=-3.0)
        self.assertGreater(
            reach.SOUTHER_SLASH_DIST_CLOSING - 1, reach.SOUTHER_SLASH_DIST_AWAY
        )
        self.assertFalse(reach.souther_will_slash(souther, fleeing))

    def test_retreating_actor_uses_the_tightest_window(self) -> None:
        myself = _myself(world_x=160, world_y=100, vel_x=-3.0)
        inside = _souther(
            facing_left=True, boss_dist_x=reach.SOUTHER_SLASH_DIST_AWAY - 1
        )
        self.assertTrue(reach.souther_will_slash(inside, myself))

    def test_inner_abort_denies_the_start(self) -> None:
        # `cmpi.w #$0018,d2 / bcs` -- he cannot begin the slash from inside
        # 24px, so this is not a threat even though every other gate holds.
        myself = _myself(world_x=160, world_y=100, vel_x=0.0)
        souther = _souther(boss_dist_x=reach.SOUTHER_SLASH_DIST_MIN - 1)
        self.assertFalse(reach.souther_will_slash(souther, myself))
        at_edge = _souther(boss_dist_x=reach.SOUTHER_SLASH_DIST_MIN)
        self.assertTrue(reach.souther_will_slash(at_edge, myself))

    def test_off_lane_denies_the_start(self) -> None:
        myself = _myself(world_x=160, world_y=100, vel_x=0.0)
        souther = _souther(boss_dist_lane=reach.SOUTHER_SLASH_LANE)
        self.assertFalse(reach.souther_will_slash(souther, myself))

    def test_unavailable_target_never_fires(self) -> None:
        myself = _myself(world_x=160, world_y=100, vel_x=0.0)
        souther = _souther(target_unavailable=1)
        self.assertFalse(reach.souther_will_slash(souther, myself))

    def test_recovering_souther_is_not_a_threat(self) -> None:
        myself = _myself(world_x=160, world_y=100, vel_x=0.0)
        souther = _souther(combat_phase=CombatPhase.RECOVERY)
        self.assertFalse(reach.souther_will_slash(souther, myself))


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

    def test_a_punishable_souther_is_the_one_safe_case(self) -> None:
        # He cannot act and no claw is out; the grab outranks the hop anyway.
        myself = _myself(world_x=160, world_y=100)
        souther = _souther(
            world_x=200, world_y=100, combat_phase=CombatPhase.RECOVERY
        )
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

    def test_promotes_jack_when_the_actor_is_on_his_back(self) -> None:
        # Jack faces left at x=130; the actor at x=150 is behind him and
        # facing him -- the hold that lands before the axe turns around.
        myself = _myself(world_x=150, world_y=100, facing_left=True)
        jack = _jack(slot="obj01", world_x=130, world_y=100, facing_left=True)

        self.assertEqual(
            reach.grab_reasons(set(), myself, jack, [jack]),
            frozenset({GrabReason.JACK_FROM_BEHIND}),
        )

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

    def test_promotes_antonio_once_he_is_in_hitstun(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        antonio = _antonio(
            slot="obj09", world_x=130, world_y=100, combat_phase=CombatPhase.RECOVERY,
            primary_state=3,
        )

        self.assertEqual(
            reach.grab_reasons(set(), myself, antonio, [antonio]),
            frozenset({GrabReason.ANTONIO_ON_PUNISH}),
        )

    def test_a_ready_antonio_is_not_a_grab_opportunity(self) -> None:
        # Walking into him before the punch lands is how the kick hits first.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        antonio = _antonio(
            slot="obj09", world_x=130, world_y=100, combat_phase=CombatPhase.NORMAL,
            primary_state=1,
        )

        self.assertEqual(reach.grab_reasons(set(), myself, antonio, [antonio]), frozenset())

    def test_the_brief_souther_hit_reaction_offers_the_hold(self) -> None:
        myself = _myself(world_x=160, world_y=100)
        souther = _souther(
            world_x=180, world_y=100, combat_phase=CombatPhase.RECOVERY, primary_state=3
        )

        self.assertEqual(
            reach.grab_reasons(set(), myself, souther, [souther]),
            frozenset({GrabReason.SOUTHER_ON_PUNISH}),
        )

    def test_the_long_souther_recovery_state_does_not(self) -> None:
        # Measured live: primary $04 held 70% of a 120s fight against $03's
        # 4%, and both decode as RECOVERY. Keyed on the phase alone, the
        # grab scored 75 -- top of the table -- for most of the fight and
        # never converted: 2318 ticks of GrabEnemy while Souther lost 11
        # health and the actor lost a life. $04 is where he sits, not a
        # window.
        myself = _myself(world_x=160, world_y=100)
        souther = _souther(
            world_x=180, world_y=100, combat_phase=CombatPhase.RECOVERY, primary_state=4
        )

        self.assertEqual(reach.grab_reasons(set(), myself, souther, [souther]), frozenset())

    def test_a_souther_that_can_still_act_offers_nothing(self) -> None:
        myself = _myself(world_x=160, world_y=100)
        souther = _souther(world_x=180, world_y=100)

        self.assertEqual(reach.grab_reasons(set(), myself, souther, [souther]), frozenset())


def _connects(band, actor, enemy, verb_cls) -> bool:
    return reach.connects(band, actor, enemy, kinematics.connect_frames(verb_cls, actor, enemy))


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

    def test_antonio_opener_includes_punch_range_on_his_lane(self) -> None:
        myself = _myself(world_x=120, world_y=100, facing_left=False)
        antonio = _antonio(world_x=160, world_y=100, boss_dist_x=40, boss_dist_lane=0)

        self.assertTrue(_connects(reach.in_jump_attack_band, myself, antonio, JumpAttack))

    def test_antonio_opener_does_not_cover_another_lane(self) -> None:
        myself = _myself(world_x=120, world_y=80, facing_left=False)
        antonio = _antonio(world_x=160, world_y=100, boss_dist_x=40, boss_dist_lane=20)

        self.assertFalse(_connects(reach.in_jump_attack_band, myself, antonio, JumpAttack))

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

    def test_enemy_off_lane_is_not_grab_reach_even_inside_punch_reach(self) -> None:
        # dy=11 still clears PUNCH_RANGE_Y (12) but not GRAB_RANGE_Y (10):
        # two bodies have to actually overlap for the contact test to fire.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        enemy = _enemy(world_x=130, world_y=111)

        self.assertTrue(_connects(reach.punch_would_connect, myself, enemy, Punch))
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
    def test_ignored_while_still_juggling(self) -> None:
        jack = _jack(slot="obj20", world_x=140, world_y=100, has_projectile=True)
        axe = Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x28
        )

        self.assertTrue(reach.jack_still_juggling(axe, {jack}))

    def test_no_longer_juggling_once_thrown(self) -> None:
        jack = _jack(slot="obj20", world_x=300, world_y=100, has_projectile=False)
        axe = Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x28
        )

        self.assertFalse(reach.jack_still_juggling(axe, {jack}))

    def test_other_projectile_types_are_never_his_axe(self) -> None:
        jack = _jack(slot="obj20", world_x=140, world_y=100, has_projectile=True)
        knife = Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x1E
        )

        self.assertFalse(reach.jack_still_juggling(knife, {jack}))


if __name__ == "__main__":
    unittest.main()
