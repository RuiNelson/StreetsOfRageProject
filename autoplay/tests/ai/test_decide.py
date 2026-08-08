import unittest

from sor_autoplay.ai.attack_decisions import (
    Attack,
    CounterGrab,
    JumpAttack,
    Punch,
    RearAttack,
    Supplex,
    ThrowKnife,
)
from sor_autoplay.ai.character import Myself, Partner
from sor_autoplay.ai.decide import (
    generate_decision_tokens,
    should_call_police,
    should_counter_grab,
    should_dodge_projectile,
    should_jump_attack,
    should_punch,
    should_rear_attack,
    should_retreat_from_danger_zone,
    should_sidestep,
    should_supplex,
    should_throw_knife,
    should_walk_to_advance_stage,
    should_walk_to_near_enemy,
    should_walk_to_pickup,
    should_walk_to_weapon,
)
from sor_autoplay.ai.enemy import Enemy
from sor_autoplay.ai.essential import AnimationInProgress, CameraRange, Stage
from sor_autoplay.ai.hazard_tokens import DangerZone, IncomingProjectile
from sor_autoplay.ai.pickup_tokens import HealthPickup, Weapon
from sor_autoplay.ai.police_decision import CallPolice
from sor_autoplay.ai.tokens import Decision, Token
from sor_autoplay.ai.walk_decisions import (
    Sidestep,
    Walk,
    WalkToAdvanceStage,
    WalkToCoordinate,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from sor_autoplay.phases import CombatPhase


def make_myself(**overrides) -> Myself:
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


def make_enemy(**overrides) -> Enemy:
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


class DecisionDataclassContractTests(unittest.TestCase):
    def test_decision_class_hierarchy(self) -> None:
        self.assertTrue(issubclass(Walk, Decision))
        self.assertTrue(issubclass(Attack, Decision))
        self.assertTrue(issubclass(CallPolice, Decision))
        self.assertTrue(issubclass(WalkToNearEnemy, Walk))
        self.assertTrue(issubclass(Sidestep, Walk))
        self.assertTrue(issubclass(Punch, Attack))

    def test_priority_defaults(self) -> None:
        self.assertEqual(Punch(actor_slot="P1", target_slot="obj01").priority, 10)
        self.assertEqual(WalkToNearEnemy(actor_slot="P1", target_slot="obj01").priority, 20)
        self.assertEqual(Sidestep(actor_slot="P1", threat_slot="obj01", direction="up").priority, 30)
        self.assertEqual(CallPolice(actor_slot="P1").priority, 0)
        self.assertEqual(WalkToAdvanceStage(actor_slot="P1", direction="right").priority, 5)


class ShouldPunchTests(unittest.TestCase):
    def test_fires_within_range(self) -> None:
        # Axel punch band: inner 16 .. outer 50 (controls-and-input.md).
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy}

        result = should_punch(context)

        self.assertEqual(result, {Punch(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_inside_inner_dead_zone(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=110, world_y=100)  # dx=10 < Axel inner 16
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_punch(context), set())

    def test_does_not_fire_out_of_range(self) -> None:
        myself = make_myself()
        enemy = make_enemy(world_x=200, world_y=200)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_punch(context), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}

        self.assertEqual(should_punch(context), set())

    def test_ignores_enemies_that_should_be_ignored_as_target(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=130, world_y=105, combat_phase=CombatPhase.DEATH)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_punch(context), set())

    def test_fires_for_partner_too(self) -> None:
        partner = Partner(
            slot="P2",
            player_index=2,
            character_id=1,  # Adam: inner 8, outer 48
            character_name="Adam",
            world_x=300,
            world_y=300,
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
        enemy = make_enemy(slot="obj02", world_x=320, world_y=302)
        context: set[Token] = {partner, enemy}

        result = should_punch(context)

        self.assertEqual(result, {Punch(actor_slot="P2", target_slot="obj02")})

    def test_does_not_fire_when_holding_an_enemy(self) -> None:
        myself = make_myself(held_weapon_type=0x01)  # not a weapon-type id -> holding an enemy
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_punch(context), set())


class ShouldRearAttackTests(unittest.TestCase):
    def test_fires_when_enemy_is_behind(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=80, world_y=100)  # behind while facing right
        context: set[Token] = {myself, enemy}

        result = should_rear_attack(context)

        self.assertEqual(result, {RearAttack(actor_slot="P1", target_slot="obj01")})

    def test_fires_when_enemy_inside_punch_dead_zone(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=108, world_y=100)  # dx=8 < Axel inner 16
        context: set[Token] = {myself, enemy}

        result = should_rear_attack(context)

        self.assertEqual(result, {RearAttack(actor_slot="P1", target_slot="obj01")})


class ShouldCounterGrabTests(unittest.TestCase):
    def test_fires_when_held_by_enemy(self) -> None:
        myself = make_myself(
            combat_phase=CombatPhase.HELD_BY_ENEMY,
            action_state=0x7A,
        )
        context: set[Token] = {myself}

        self.assertEqual(should_counter_grab(context), {CounterGrab(actor_slot="P1")})

    def test_does_not_fire_when_free(self) -> None:
        myself = make_myself(combat_phase=CombatPhase.NORMAL)
        self.assertEqual(should_counter_grab({myself}), set())


class ShouldWalkToNearEnemyTests(unittest.TestCase):
    def test_picks_the_nearest_enemy(self) -> None:
        myself = make_myself(world_x=0, world_y=0)
        # Outside punch/rear connect bands so walk is the right candidate.
        near = make_enemy(slot="near", world_x=80, world_y=10)
        far = make_enemy(slot="far", world_x=500, world_y=500)
        context: set[Token] = {myself, near, far}

        result = should_walk_to_near_enemy(context)

        self.assertEqual(result, {WalkToNearEnemy(actor_slot="P1", target_slot="near")})

    def test_no_enemies_no_decision(self) -> None:
        myself = make_myself()
        self.assertEqual(should_walk_to_near_enemy({myself}), set())

    def test_no_decision_when_animation_in_progress(self) -> None:
        myself = make_myself()
        enemy = make_enemy()
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}
        self.assertEqual(should_walk_to_near_enemy(context), set())


class ShouldWalkToAdvanceStageTests(unittest.TestCase):
    def test_fires_when_no_enemies_present(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, stage}

        result = should_walk_to_advance_stage(context)

        self.assertEqual(result, {WalkToAdvanceStage(actor_slot="P1", direction="right")})

    def test_does_not_fire_when_an_enemy_is_present(self) -> None:
        myself = make_myself()
        enemy = make_enemy()
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, enemy, stage}

        self.assertEqual(should_walk_to_advance_stage(context), set())

    def test_does_not_fire_when_direction_is_none(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=6, direction="none")
        context: set[Token] = {myself, stage}

        self.assertEqual(should_walk_to_advance_stage(context), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, stage, AnimationInProgress(slot="P1")}

        self.assertEqual(should_walk_to_advance_stage(context), set())

    def test_does_not_fire_without_a_stage_token(self) -> None:
        myself = make_myself()
        self.assertEqual(should_walk_to_advance_stage({myself}), set())

    def test_uses_left_direction_for_level_seven(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=7, direction="left")
        context: set[Token] = {myself, stage}

        result = should_walk_to_advance_stage(context)

        self.assertEqual(result, {WalkToAdvanceStage(actor_slot="P1", direction="left")})


class ShouldSidestepTests(unittest.TestCase):
    def test_fires_for_confirmed_dangerous_enemy(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(
            world_x=110,
            world_y=120,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
        )
        context: set[Token] = {myself, enemy}

        result = should_sidestep(context)

        self.assertEqual(
            result,
            {Sidestep(actor_slot="P1", threat_slot="obj01", direction="up")},
        )

    def test_fires_for_close_facing_unknown_phase_enemy(self) -> None:
        # The caution rule: CombatPhase.UNKNOWN on a nearby, player-facing
        # enemy must be treated as "insufficient information," not "safe."
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(
            world_x=130,
            world_y=90,
            combat_phase=CombatPhase.UNKNOWN,
            targets_player=1,
            facing_left=True,  # facing left, myself is to its left -> facing myself
        )
        context: set[Token] = {myself, enemy}

        result = should_sidestep(context)

        self.assertEqual(
            result,
            {Sidestep(actor_slot="P1", threat_slot="obj01", direction="down")},
        )

    def test_does_not_fire_for_far_away_enemy(self) -> None:
        # Not is_dangerous and too far away for the UNKNOWN-caution rule to
        # apply either.
        myself = make_myself(world_x=0, world_y=0)
        enemy = make_enemy(
            world_x=500,
            world_y=500,
            combat_phase=CombatPhase.UNKNOWN,
            targets_player=1,
            facing_left=True,
        )
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_sidestep(context), set())

    def test_does_not_fire_for_non_targeting_enemy(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(
            world_x=105,
            world_y=105,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=2,
        )
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_sidestep(context), set())

    def test_does_not_fire_for_unknown_phase_when_not_facing(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(
            world_x=130,
            world_y=90,
            combat_phase=CombatPhase.UNKNOWN,
            targets_player=1,
            facing_left=False,  # facing away from myself
        )
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_sidestep(context), set())


class ShouldCallPoliceTests(unittest.TestCase):
    def test_fires_when_danger_zone_threat_at_least_three(self) -> None:
        myself = make_myself(specials=1, health_percent=100.0)
        danger = DangerZone(slot="P1", left=0, right=1, top=0, bottom=1, threat_level=3)
        context: set[Token] = {myself, danger}

        self.assertEqual(should_call_police(context), {CallPolice(actor_slot="P1")})

    def test_fires_when_low_health_and_any_threat(self) -> None:
        myself = make_myself(specials=1, health_percent=10.0)
        danger = DangerZone(slot="P1", left=0, right=1, top=0, bottom=1, threat_level=1)
        context: set[Token] = {myself, danger}

        self.assertEqual(should_call_police(context), {CallPolice(actor_slot="P1")})

    def test_does_not_fire_below_thresholds(self) -> None:
        myself = make_myself(specials=1, health_percent=100.0)
        danger = DangerZone(slot="P1", left=0, right=1, top=0, bottom=1, threat_level=1)
        context: set[Token] = {myself, danger}

        self.assertEqual(should_call_police(context), set())

    def test_never_fires_with_zero_specials(self) -> None:
        myself = make_myself(specials=0, health_percent=1.0)
        danger = DangerZone(slot="P1", left=0, right=1, top=0, bottom=1, threat_level=10)
        context: set[Token] = {myself, danger}

        self.assertEqual(should_call_police(context), set())

    def test_no_danger_zone_means_no_signal(self) -> None:
        myself = make_myself(specials=1, health_percent=1.0)
        context: set[Token] = {myself}

        self.assertEqual(should_call_police(context), set())


class ShouldSupplexTests(unittest.TestCase):
    def test_fires_when_holding_a_non_weapon_target(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x01)
        near = make_enemy(slot="near", world_x=110, world_y=100)
        far = make_enemy(slot="far", world_x=500, world_y=500)
        context: set[Token] = {myself, near, far}

        result = should_supplex(context)

        self.assertEqual(result, {Supplex(actor_slot="P1", target_slot="near")})

    def test_does_not_fire_when_holding_a_weapon(self) -> None:
        myself = make_myself(held_weapon_type=0x08)
        enemy = make_enemy(world_x=110, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_supplex(context), set())

    def test_does_not_fire_when_not_holding_anything(self) -> None:
        myself = make_myself(held_weapon_type=0)
        enemy = make_enemy(world_x=110, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_supplex(context), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself = make_myself(held_weapon_type=0x01)
        enemy = make_enemy(world_x=110, world_y=100)
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}

        self.assertEqual(should_supplex(context), set())

    def test_no_crash_with_no_enemies(self) -> None:
        myself = make_myself(held_weapon_type=0x01)
        self.assertEqual(should_supplex({myself}), set())


class ShouldJumpAttackTests(unittest.TestCase):
    def test_fires_when_not_airborne_and_enemy_in_range(self) -> None:
        # Jump-kick only beyond punch outer (Axel 50); mid-range band.
        myself = make_myself(world_x=100, world_y=100, is_airborne=False)
        enemy = make_enemy(world_x=155, world_y=110)
        context: set[Token] = {myself, enemy}

        result = should_jump_attack(context)

        self.assertEqual(result, {JumpAttack(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_when_airborne(self) -> None:
        myself = make_myself(world_x=100, world_y=100, is_airborne=True)
        enemy = make_enemy(world_x=155, world_y=110)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_jump_attack(context), set())

    def test_does_not_fire_out_of_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, is_airborne=False)
        enemy = make_enemy(world_x=500, world_y=500)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_jump_attack(context), set())

    def test_does_not_fire_when_holding_an_enemy(self) -> None:
        myself = make_myself(world_x=100, world_y=100, is_airborne=False, held_weapon_type=0x01)
        enemy = make_enemy(world_x=155, world_y=110)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_jump_attack(context), set())


class ShouldThrowKnifeTests(unittest.TestCase):
    def test_fires_when_holding_knife_and_enemy_outside_melee_but_in_knife_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=160, world_y=100)  # outside KNIFE_MELEE_X=40
        context: set[Token] = {myself, enemy}

        result = should_throw_knife(context)

        self.assertEqual(result, {ThrowKnife(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_when_enemy_is_in_melee_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=110, world_y=105)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_throw_knife(context), set())

    def test_does_not_fire_when_holding_a_different_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x09)
        enemy = make_enemy(world_x=160, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_throw_knife(context), set())

    def test_does_not_fire_when_enemy_beyond_knife_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=500, world_y=500)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_throw_knife(context), set())


class ShouldWalkToWeaponTests(unittest.TestCase):
    def test_fires_for_in_camera_upgrade_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        weapon = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x0A)
        context: set[Token] = {myself, camera, weapon}

        result = should_walk_to_weapon(context)

        self.assertEqual(result, {WalkToWeapon(actor_slot="P1", target_slot="wpn1")})

    def test_does_not_fire_for_same_or_worse_ranked_weapon(self) -> None:
        # Holding bat (rank 4); bottle is rank 3 — not an upgrade.
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        weapon = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x09)
        context: set[Token] = {myself, camera, weapon}

        self.assertEqual(should_walk_to_weapon(context), set())

    def test_does_not_fire_for_weapon_outside_camera_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        weapon = Weapon(slot="wpn1", world_x=999, world_y=999, weapon_type=0x0A)
        context: set[Token] = {myself, camera, weapon}

        self.assertEqual(should_walk_to_weapon(context), set())

    def test_picks_highest_ranked_of_several_upgrades(self) -> None:
        # Damage rank: knife 5 > bat 4 > bottle 3 > pepper 2.
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        knife = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x08)
        pepper = Weapon(slot="wpn2", world_x=130, world_y=115, weapon_type=0x0C)
        context: set[Token] = {myself, camera, knife, pepper}

        result = should_walk_to_weapon(context)

        self.assertEqual(result, {WalkToWeapon(actor_slot="P1", target_slot="wpn1")})

    def test_knife_is_upgrade_over_bat(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        knife = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x08)
        context: set[Token] = {myself, camera, knife}

        result = should_walk_to_weapon(context)

        self.assertEqual(result, {WalkToWeapon(actor_slot="P1", target_slot="wpn1")})


class ShouldWalkToPickupTests(unittest.TestCase):
    def test_fires_for_health_when_missing_enough(self) -> None:
        myself = make_myself(world_x=100, world_y=100, health=40, health_percent=50.0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        food = HealthPickup(
            slot="food1", world_x=120, world_y=110, pickup_type=0x4B, health_delta=20
        )
        context: set[Token] = {myself, camera, food}

        result = should_walk_to_pickup(context)

        self.assertEqual(result, {WalkToPickup(actor_slot="P1", target_slot="food1")})

    def test_does_not_fire_for_health_when_full(self) -> None:
        myself = make_myself(world_x=100, world_y=100, health=80, health_percent=100.0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        food = HealthPickup(
            slot="food1", world_x=120, world_y=110, pickup_type=0x47, health_delta=80
        )
        context: set[Token] = {myself, camera, food}

        self.assertEqual(should_walk_to_pickup(context), set())


class ShouldRetreatFromDangerZoneTests(unittest.TestCase):
    def test_fires_at_or_above_threshold_and_moves_away_from_centroid(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        danger = DangerZone(slot="P1", left=100, right=140, top=100, bottom=100, threat_level=4)
        context: set[Token] = {myself, danger}

        result = should_retreat_from_danger_zone(context)

        self.assertEqual(len(result), 1)
        decision = next(iter(result))
        self.assertIsInstance(decision, WalkToCoordinate)
        self.assertEqual(decision.actor_slot, "P1")
        # centroid_x = 120; actor is left of it, so retreat should move further left.
        self.assertLess(decision.target_x, myself.world_x)

    def test_does_not_fire_below_threshold(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        danger = DangerZone(slot="P1", left=100, right=140, top=100, bottom=100, threat_level=3)
        context: set[Token] = {myself, danger}

        self.assertEqual(should_retreat_from_danger_zone(context), set())

    def test_no_danger_zone_no_decision(self) -> None:
        myself = make_myself()
        self.assertEqual(should_retreat_from_danger_zone({myself}), set())


class ShouldDodgeProjectileTests(unittest.TestCase):
    def test_fires_for_closing_in_lane_projectile_within_window(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        projectile = IncomingProjectile(slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0)
        context: set[Token] = {myself, projectile}

        result = should_dodge_projectile(context)

        self.assertEqual(result, {Sidestep(actor_slot="P1", threat_slot="obj10", direction="down")})

    def test_does_not_fire_for_moving_away_projectile(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        projectile = IncomingProjectile(slot="obj10", world_x=150, world_y=100, vel_x=5.0, vel_z=0.0)
        context: set[Token] = {myself, projectile}

        self.assertEqual(should_dodge_projectile(context), set())

    def test_does_not_fire_when_out_of_lane(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        projectile = IncomingProjectile(slot="obj10", world_x=150, world_y=500, vel_x=-5.0, vel_z=0.0)
        context: set[Token] = {myself, projectile}

        self.assertEqual(should_dodge_projectile(context), set())

    def test_does_not_fire_when_too_far_to_impact_in_time(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        projectile = IncomingProjectile(slot="obj10", world_x=10000, world_y=100, vel_x=-1.0, vel_z=0.0)
        context: set[Token] = {myself, projectile}

        self.assertEqual(should_dodge_projectile(context), set())

    def test_does_not_fire_for_zero_velocity(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        projectile = IncomingProjectile(slot="obj10", world_x=150, world_y=100, vel_x=0.0, vel_z=0.0)
        context: set[Token] = {myself, projectile}

        self.assertEqual(should_dodge_projectile(context), set())


class GenerateDecisionTokensTests(unittest.TestCase):
    def test_unions_all_candidates_into_context(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        # Inside Axel punch band (inner 16..outer 50).
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy}

        result = generate_decision_tokens(context)

        self.assertIn(myself, result)
        self.assertIn(enemy, result)
        self.assertIn(Punch(actor_slot="P1", target_slot="obj01"), result)
        # Already in connectable band — walk is suppressed.
        self.assertNotIn(WalkToNearEnemy(actor_slot="P1", target_slot="obj01"), result)

    def test_does_not_mutate_input_context(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy}
        original = set(context)

        generate_decision_tokens(context)

        self.assertEqual(context, original)


if __name__ == "__main__":
    unittest.main()
