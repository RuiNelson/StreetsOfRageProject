"""Tests for the reach predicates that read a real ``AttackRange``.

The rest of ``reach.py`` is exercised through ``test_inference.py`` (which
turns those bands into ``TargetInReach`` tokens); this file covers the
predicates that answer questions about the *enemy's* reach rather than the
actor's, since those are the ones that changed from an assumed margin to the
ROM's own geometry.
"""

import unittest

from sor_autoplay.ai import reach
from sor_autoplay.ai.tokens import AttackRange, Enemy, Garcia, Jack, Myself, Nora, Signal
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
    def test_jack_in_the_rear_band_is_always_warranted(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
