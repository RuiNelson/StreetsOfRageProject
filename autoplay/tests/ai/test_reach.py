"""Tests for the reach predicates that read a real ``AttackRange``.

The rest of ``reach.py`` is exercised through ``test_inference.py`` (which
turns those bands into ``TargetInReach`` tokens); this file covers the
predicates that answer questions about the *enemy's* reach rather than the
actor's, since those are the ones that changed from an assumed margin to the
ROM's own geometry.
"""

import unittest

from sor_autoplay.ai import reach
from sor_autoplay.ai.tokens import AttackRange, Enemy, Garcia, Myself, Nora
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


class EnemyForwardDxTests(unittest.TestCase):
    def test_a_left_facing_enemy_measures_forward_to_its_left(self) -> None:
        enemy = _garcia(world_x=200, facing_left=True)
        self.assertEqual(reach.enemy_forward_dx(enemy, _myself(world_x=160)), 40)
        self.assertEqual(reach.enemy_forward_dx(enemy, _myself(world_x=240)), -40)

    def test_a_right_facing_enemy_measures_forward_to_its_right(self) -> None:
        enemy = _garcia(world_x=200, facing_left=False)
        self.assertEqual(reach.enemy_forward_dx(enemy, _myself(world_x=240)), 40)
        self.assertEqual(reach.enemy_forward_dx(enemy, _myself(world_x=160)), -40)


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


if __name__ == "__main__":
    unittest.main()
