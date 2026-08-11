import unittest

from sor_autoplay.ai.tokens import (
    Attack,
    CounterGrab,
    FlipHold,
    JumpAttack,
    AttackHeldEnemy,
    Punch,
    RearAttack,
    SprayPepper,
    StabWithKnifeOrBottle,
    SwingBatOrPipe,
    TechRecover,
    ThrowKnife,
    ThrowPepper,
)
from sor_autoplay.ai.tokens import Myself, Partner
from sor_autoplay.ai.decide import (
    generate_decision_tokens,
    could_call_police,
    could_counter_grab,
    could_hold_actions,
    could_jump_attack,
    could_punch,
    could_rear_attack,
    could_retreat_from_danger,
    could_spray_pepper,
    could_stab_with_knife_or_bottle,
    could_swing_bat_or_pipe,
    could_tech_recover,
    could_throw_knife,
    could_throw_pepper,
    could_walk_to_advance_stage,
    could_walk_to_breakable,
    could_walk_to_near_enemy,
    could_walk_to_pickup,
    could_walk_to_weapon,
)
from sor_autoplay.ai.tokens import ClosingEnemy, Enemy
from sor_autoplay.ai.tokens import AnimationInProgress, CameraRange, Stage
from sor_autoplay.ai.tokens import Breakable
from sor_autoplay.ai.tokens import HealthPickup, Weapon
from sor_autoplay.ai.tokens import CallPolice
from sor_autoplay.ai.tokens import Decision, Token
from sor_autoplay.ai.tokens import (
    RetreatFromDanger,
    Walk,
    WalkToAdvanceStage,
    WalkToBreakable,
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
        self.assertTrue(issubclass(Punch, Attack))

    def test_priority_defaults(self) -> None:
        self.assertEqual(Punch(actor_slot="P1", target_slot="obj01").priority, 10)
        self.assertEqual(WalkToNearEnemy(actor_slot="P1", target_slot="obj01").priority, 20)
        self.assertEqual(CallPolice(actor_slot="P1").priority, 0)
        self.assertEqual(WalkToAdvanceStage(actor_slot="P1", direction="right").priority, 5)


class CouldPunchTests(unittest.TestCase):
    def test_fires_within_range(self) -> None:
        # Axel punch band: inner 16 .. outer 50 (controls-and-input.md).
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy}

        result = could_punch(context)

        self.assertEqual(result, {Punch(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_inside_inner_dead_zone(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=110, world_y=100)  # dx=10 < Axel inner 16
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_punch(context), set())

    def test_does_not_fire_out_of_range(self) -> None:
        myself = make_myself()
        enemy = make_enemy(world_x=200, world_y=200)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_punch(context), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}

        self.assertEqual(could_punch(context), set())

    def test_ignores_enemies_that_should_be_ignored_as_target(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=130, world_y=105, combat_phase=CombatPhase.DEATH)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_punch(context), set())

    def test_ignores_an_enemy_outside_the_playable_lane(self) -> None:
        # Regression: stage 1's scripted "behind a door" enemy is a real,
        # tracked Enemy object (health, combat_phase) at an anomalously
        # high world_y the player can never physically reach -- attacking
        # it just wastes time on a target that can never connect. Y=115 is
        # otherwise well within punch band Y-slack (dy=10 <= PUNCH_RANGE_Y),
        # so only the lane-bounds filter (LANE_Y_MAX_DEFAULT=112) explains
        # this being excluded.
        myself = make_myself(world_x=100, world_y=105)
        beyond_lane = make_enemy(world_x=130, world_y=115, combat_phase=CombatPhase.NORMAL)
        context: set[Token] = {myself, beyond_lane}

        self.assertEqual(could_punch(context), set())

    def test_fires_for_an_enemy_right_at_the_playable_lane_edge(self) -> None:
        myself = make_myself(world_x=100, world_y=105)
        at_edge = make_enemy(world_x=130, world_y=112, combat_phase=CombatPhase.NORMAL)
        context: set[Token] = {myself, at_edge}

        result = could_punch(context)

        self.assertEqual(result, {Punch(actor_slot="P1", target_slot="obj01")})

    def test_fires_for_partner_too(self) -> None:
        partner = Partner(
            slot="P2",
            player_index=2,
            character_id=1,  # Adam: inner 8, outer 48
            character_name="Adam",
            world_x=300,
            world_y=60,
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
        enemy = make_enemy(slot="obj02", world_x=320, world_y=62)
        context: set[Token] = {partner, enemy}

        result = could_punch(context)

        self.assertEqual(result, {Punch(actor_slot="P2", target_slot="obj02")})

    def test_does_not_fire_when_holding_an_enemy(self) -> None:
        myself = make_myself(held_weapon_type=0x01)  # not a weapon-type id -> holding an enemy
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_punch(context), set())

    def test_does_not_fire_while_holding_any_weapon(self) -> None:
        # Punch is unarmed-only now -- a held bat/pipe/knife/bottle/pepper
        # fires SwingBatOrPipe/StabWithKnifeOrBottle/SprayPepper instead
        # (same B-button input, but a genuinely different ROM move/reach).
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        enemy = make_enemy(world_x=130, world_y=100)  # well within any of the bands

        self.assertEqual(could_punch({myself, enemy}), set())


class CouldSwingBatOrPipeTests(unittest.TestCase):
    def test_fires_within_the_measured_36px_reach(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        enemy = make_enemy(world_x=130, world_y=100)  # dx=30, within bat's 36

        result = could_swing_bat_or_pipe({myself, enemy})

        self.assertEqual(result, {SwingBatOrPipe(actor_slot="P1", target_slot="obj01")})

    def test_pipe_also_fires(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0B)
        enemy = make_enemy(world_x=130, world_y=100)

        result = could_swing_bat_or_pipe({myself, enemy})

        self.assertEqual(result, {SwingBatOrPipe(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_beyond_the_36px_reach(self) -> None:
        # Axel's unarmed outer is 50, but a held bat's measured reach is 36
        # (weapons-range-and-damage.md) -- a target at dx=45 is unreachable.
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        enemy = make_enemy(world_x=145, world_y=100)

        self.assertEqual(could_swing_bat_or_pipe({myself, enemy}), set())

    def test_does_not_fire_when_unarmed(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        enemy = make_enemy(world_x=130, world_y=100)

        self.assertEqual(could_swing_bat_or_pipe({myself, enemy}), set())

    def test_does_not_fire_when_holding_a_different_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)  # knife
        enemy = make_enemy(world_x=130, world_y=100)

        self.assertEqual(could_swing_bat_or_pipe({myself, enemy}), set())


class CouldStabWithKnifeOrBottleTests(unittest.TestCase):
    def test_fires_within_the_unarmed_punch_band(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=130, world_y=105)

        result = could_stab_with_knife_or_bottle({myself, enemy})

        self.assertEqual(result, {StabWithKnifeOrBottle(actor_slot="P1", target_slot="obj01")})

    def test_bottle_also_fires(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x09)
        enemy = make_enemy(world_x=130, world_y=105)

        result = could_stab_with_knife_or_bottle({myself, enemy})

        self.assertEqual(result, {StabWithKnifeOrBottle(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_when_unarmed(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        enemy = make_enemy(world_x=130, world_y=105)

        self.assertEqual(could_stab_with_knife_or_bottle({myself, enemy}), set())

    def test_does_not_fire_when_holding_a_different_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)  # bat
        enemy = make_enemy(world_x=130, world_y=105)

        self.assertEqual(could_stab_with_knife_or_bottle({myself, enemy}), set())


class CouldSprayPepperTests(unittest.TestCase):
    def test_fires_within_the_unarmed_punch_band(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0C)
        enemy = make_enemy(world_x=130, world_y=105)

        result = could_spray_pepper({myself, enemy})

        self.assertEqual(result, {SprayPepper(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_when_unarmed(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        enemy = make_enemy(world_x=130, world_y=105)

        self.assertEqual(could_spray_pepper({myself, enemy}), set())

    def test_does_not_fire_when_holding_a_different_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)  # knife
        enemy = make_enemy(world_x=130, world_y=105)

        self.assertEqual(could_spray_pepper({myself, enemy}), set())


class CouldRearAttackTests(unittest.TestCase):
    def test_fires_when_enemy_is_behind(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=80, world_y=100)  # behind while facing right
        context: set[Token] = {myself, enemy}

        result = could_rear_attack(context)

        self.assertEqual(result, {RearAttack(actor_slot="P1", target_slot="obj01")})

    def test_axel_does_not_fire_for_an_enemy_in_front(self) -> None:
        # controls-and-input.md "Measured chord timing": Axel's $322A box is
        # X -40..-8 -- pure backfist, no forward reach at all.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=108, world_y=100)  # dx=8, in front
        context: set[Token] = {myself, enemy}

        result = could_rear_attack(context)

        self.assertEqual(result, set())

    def test_adams_hop_fires_for_an_enemy_closed_in_front(self) -> None:
        # Adam's chord ($22 -> $24) is a forward-reaching hop, X -42..+14.
        myself = make_myself(
            character_id=1, character_name="Adam", world_x=100, world_y=100, facing_left=False
        )
        enemy = make_enemy(world_x=108, world_y=100)  # dx=8, within Adam's +14 front reach
        context: set[Token] = {myself, enemy}

        result = could_rear_attack(context)

        self.assertEqual(result, {RearAttack(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_early_for_a_closing_enemy_still_outside_the_band(self) -> None:
        # Regression (live-diagnosed): an earlier version also fired here
        # purely on ClosingEnemy, before the enemy was actually within
        # _in_rear_band's real range. $322A only hits based on *current*
        # position, so that committed Axel to a guaranteed-whiff attack and
        # left him locked in its recovery frames exactly when the
        # still-closing enemy arrived and landed its own hit for free.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=160, world_y=100)  # dx=60, outside Axel's 40px band
        context: set[Token] = {myself, enemy, ClosingEnemy(slot="obj01")}

        result = could_rear_attack(context)

        self.assertEqual(result, set())

    def test_still_fires_by_the_real_band_regardless_of_a_closing_enemy_token(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=80, world_y=100)  # behind while facing right
        context: set[Token] = {myself, enemy, ClosingEnemy(slot="obj01")}

        result = could_rear_attack(context)

        self.assertEqual(result, {RearAttack(actor_slot="P1", target_slot="obj01")})


class CouldCounterGrabTests(unittest.TestCase):
    def test_fires_when_held_by_enemy(self) -> None:
        myself = make_myself(
            combat_phase=CombatPhase.HELD_BY_ENEMY,
            action_state=0x7A,
        )
        context: set[Token] = {myself}

        self.assertEqual(could_counter_grab(context), {CounterGrab(actor_slot="P1")})

    def test_does_not_fire_when_free(self) -> None:
        myself = make_myself(combat_phase=CombatPhase.NORMAL)
        self.assertEqual(could_counter_grab({myself}), set())


class CouldTechRecoverTests(unittest.TestCase):
    def test_fires_when_the_tech_window_is_armed(self) -> None:
        myself = make_myself(
            combat_phase=CombatPhase.HURT_PLAYER, action_state=0x72, tech_armed=1
        )
        context: set[Token] = {myself}

        self.assertEqual(could_tech_recover(context), {TechRecover(actor_slot="P1")})

    def test_does_not_fire_when_not_armed(self) -> None:
        myself = make_myself(
            combat_phase=CombatPhase.HURT_PLAYER, action_state=0x72, tech_armed=0
        )
        self.assertEqual(could_tech_recover({myself}), set())

    def test_does_not_fire_on_a_non_techable_action_even_if_armed(self) -> None:
        myself = make_myself(combat_phase=CombatPhase.NORMAL, action_state=0x02, tech_armed=1)
        self.assertEqual(could_tech_recover({myself}), set())

    def test_bypasses_the_animation_in_progress_gate(self) -> None:
        # Unlike could_punch etc., could_tech_recover must still fire while
        # the actor is "blocked" -- that's the whole HURT_PLAYER window it's
        # meant to interrupt (mirrors could_counter_grab's own exception).
        myself = make_myself(
            combat_phase=CombatPhase.HURT_PLAYER, action_state=0x72, tech_armed=1
        )
        context: set[Token] = {myself, AnimationInProgress(slot="P1")}

        self.assertEqual(could_tech_recover(context), {TechRecover(actor_slot="P1")})


class CouldWalkToNearEnemyTests(unittest.TestCase):
    def test_produces_one_candidate_per_reachable_enemy_not_just_the_nearest(self) -> None:
        # could_walk_to_near_enemy must not pre-select -- per AI.md, ranking
        # several same-kind candidates against each other is
        # determine_priority_decision's job (see test_priority.py's
        # test_walk_to_near_enemy_picks_the_closer_of_two_candidates).
        myself = make_myself(world_x=0, world_y=0)
        # Outside punch/rear connect bands so walk is the right candidate.
        near = make_enemy(slot="near", world_x=80, world_y=10)
        far = make_enemy(slot="far", world_x=500, world_y=10)
        context: set[Token] = {myself, near, far}

        result = could_walk_to_near_enemy(context)

        self.assertEqual(
            result,
            {
                WalkToNearEnemy(actor_slot="P1", target_slot="near"),
                WalkToNearEnemy(actor_slot="P1", target_slot="far"),
            },
        )

    def test_no_enemies_no_decision(self) -> None:
        myself = make_myself()
        self.assertEqual(could_walk_to_near_enemy({myself}), set())

    def test_no_decision_when_animation_in_progress(self) -> None:
        myself = make_myself()
        enemy = make_enemy()
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}
        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_falls_back_to_an_off_screen_enemy_ahead_in_the_stage_direction(self) -> None:
        # Regression: with nothing on-screen, an off-screen enemy still
        # correctly holds back could_walk_to_advance_stage, but nothing
        # ever chased it, so the AI produced no decision at all and the
        # camera never moved to bring it into view.
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        ahead = make_enemy(world_x=500, world_y=100)  # off-screen, ahead
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, ahead, stage}

        result = could_walk_to_near_enemy(context)

        self.assertEqual(result, {WalkToNearEnemy(actor_slot="P1", target_slot="obj01")})

    def test_does_not_chase_an_off_screen_enemy_behind(self) -> None:
        # Must never walk backward for an abandoned off-screen leftover.
        myself = make_myself(world_x=500, world_y=100)
        camera = CameraRange(left=400, right=600, top=0, bottom=200)
        behind = make_enemy(world_x=50, world_y=100)  # off-screen, behind
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, behind, stage}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_off_screen_fallback_needs_a_stage_token(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        ahead = make_enemy(world_x=500, world_y=100)
        context: set[Token] = {myself, camera, ahead}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_off_screen_fallback_inert_when_stage_direction_is_none(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        ahead = make_enemy(world_x=500, world_y=100)
        stage = Stage(level_index=6, direction="none")
        context: set[Token] = {myself, camera, ahead, stage}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_on_screen_enemy_still_takes_priority_over_the_fallback(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        on_screen = make_enemy(slot="near", world_x=150, world_y=10, health=10)
        off_screen_ahead = make_enemy(slot="far", world_x=500, world_y=100)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, on_screen, off_screen_ahead, stage}

        result = could_walk_to_near_enemy(context)

        self.assertEqual(result, {WalkToNearEnemy(actor_slot="P1", target_slot="near")})

    def test_skips_an_enemy_already_actionable_in_front(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=130, world_y=100)  # in front, in punch band
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_does_not_skip_an_enemy_behind_beyond_both_real_bands(self) -> None:
        # Regression (live-diagnosed): dx=-46 sits inside _in_punch_band's raw
        # distance box (punch_inner=16..punch_outer=50 for Axel) but the
        # enemy is behind the actor's facing, beyond both RearAttack's real
        # band (40px) and could_punch's 4px behind tolerance -- nothing can
        # actually hit it. Skipping WalkToNearEnemy here left the actor
        # standing still, undefended, while the enemy closed in and hit.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=54, world_y=100)  # behind (facing right), dx=-46
        context: set[Token] = {myself, enemy}

        result = could_walk_to_near_enemy(context)

        self.assertEqual(result, {WalkToNearEnemy(actor_slot="P1", target_slot="obj01")})

    def test_skips_an_enemy_behind_within_the_real_rear_band(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=70, world_y=100)  # behind, dx=-30, within Axel's 40px band
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_skips_a_dangerous_enemy_in_the_retreat_caution_zone(self) -> None:
        # Axel: punch_outer=50, RETREAT_CAUTION_MARGIN=24 -> zone is dx<=74.
        # could_retreat_from_danger covers this enemy instead.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(
            world_x=170, world_y=100, combat_phase=CombatPhase.ATTACKING
        )  # dx=70, dangerous, in front (not actionable: outside punch_outer=50)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_still_approaches_a_dangerous_enemy_beyond_the_caution_zone(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(
            world_x=200, world_y=100, combat_phase=CombatPhase.ATTACKING
        )  # dx=100, beyond the 74px caution zone
        context: set[Token] = {myself, enemy}

        result = could_walk_to_near_enemy(context)

        self.assertEqual(result, {WalkToNearEnemy(actor_slot="P1", target_slot="obj01")})


class CouldRetreatFromDangerTests(unittest.TestCase):
    def test_fires_for_a_dangerous_enemy_in_the_caution_zone(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.ATTACKING)  # dx=70
        context: set[Token] = {myself, enemy}

        result = could_retreat_from_danger(context)

        self.assertEqual(result, {RetreatFromDanger(actor_slot="P1", target_slot="obj01")})

    def test_fires_for_a_charging_enemy_too(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.CHARGE)
        context: set[Token] = {myself, enemy}

        result = could_retreat_from_danger(context)

        self.assertEqual(result, {RetreatFromDanger(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_for_a_non_dangerous_enemy(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.NORMAL)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_retreat_from_danger(context), set())

    def test_does_not_fire_when_already_actionable(self) -> None:
        # Already hittable -- attack instead of retreating.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=130, world_y=100, combat_phase=CombatPhase.ATTACKING)  # dx=30, in front, in punch band
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_retreat_from_danger(context), set())

    def test_does_not_fire_when_still_far_beyond_the_caution_zone(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=200, world_y=100, combat_phase=CombatPhase.ATTACKING)  # dx=100
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_retreat_from_danger(context), set())

    def test_no_decision_when_animation_in_progress(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.ATTACKING)
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}

        self.assertEqual(could_retreat_from_danger(context), set())

    def test_no_enemies_no_decision(self) -> None:
        myself = make_myself()
        self.assertEqual(could_retreat_from_danger({myself}), set())


class CouldWalkToAdvanceStageTests(unittest.TestCase):
    def test_fires_when_no_enemies_present(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, stage}

        result = could_walk_to_advance_stage(context)

        self.assertEqual(result, {WalkToAdvanceStage(actor_slot="P1", direction="right")})

    def test_does_not_fire_when_an_enemy_is_present(self) -> None:
        myself = make_myself()
        enemy = make_enemy()
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, enemy, stage}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_does_not_fire_when_the_only_enemy_is_off_screen(self) -> None:
        """A spawned-but-not-yet-visible enemy must hold the stage just like
        an on-screen one -- it is a reason to hold position, not a "next
        wave cue" to push past (see could_walk_to_advance_stage's
        docstring)."""

        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        off_screen_enemy = make_enemy(world_x=500, world_y=100)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, off_screen_enemy, stage}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_fires_when_the_camera_is_clear_but_an_off_screen_enemy_remains_absent(
        self,
    ) -> None:
        """Sanity check for the fix above: with no enemy token at all (on or
        off screen), advance still fires."""

        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, stage}

        result = could_walk_to_advance_stage(context)

        self.assertEqual(result, {WalkToAdvanceStage(actor_slot="P1", direction="right")})

    def test_fires_when_the_only_remaining_enemy_is_off_screen_at_zero_health(self) -> None:
        # Regression: world_map.MapEntity.is_defeated's own note says zero
        # health is still "alive" (needs a finishing hit) -- but nothing
        # ever chases an off-screen target, so such a straggler must not
        # block stage advance forever.
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        stranded = make_enemy(world_x=500, world_y=100, health=0)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, stranded, stage}

        result = could_walk_to_advance_stage(context)

        self.assertEqual(result, {WalkToAdvanceStage(actor_slot="P1", direction="right")})

    def test_does_not_fire_when_the_off_screen_zero_health_enemy_could_still_be_hit(
        self,
    ) -> None:
        # An on-screen enemy at 0 health is still reachable/finishable, so
        # it must keep blocking advance just like any other live enemy.
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        on_screen_zero_hp = make_enemy(world_x=150, world_y=100, health=0)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, on_screen_zero_hp, stage}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_off_screen_enemy_with_nonzero_health_still_blocks(self) -> None:
        # Only exactly-zero health is exempted -- a still-damageable
        # off-screen enemy is a genuine "about to scroll into view" reason
        # to hold position, per the original docstring rationale.
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        off_screen_alive = make_enemy(world_x=500, world_y=100, health=1)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, off_screen_alive, stage}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_does_not_fire_when_direction_is_none(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=6, direction="none")
        context: set[Token] = {myself, stage}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, stage, AnimationInProgress(slot="P1")}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_does_not_fire_without_a_stage_token(self) -> None:
        myself = make_myself()
        self.assertEqual(could_walk_to_advance_stage({myself}), set())

    def test_uses_left_direction_for_level_seven(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=7, direction="left")
        context: set[Token] = {myself, stage}

        result = could_walk_to_advance_stage(context)

        self.assertEqual(result, {WalkToAdvanceStage(actor_slot="P1", direction="left")})


class CouldCallPoliceTests(unittest.TestCase):
    def test_fires_when_health_is_critical(self) -> None:
        myself = make_myself(specials=1, health_percent=10.0)
        context: set[Token] = {myself}

        self.assertEqual(could_call_police(context), {CallPolice(actor_slot="P1")})

    def test_does_not_fire_at_the_critical_threshold(self) -> None:
        myself = make_myself(specials=1, health_percent=18.0)
        context: set[Token] = {myself}

        self.assertEqual(could_call_police(context), set())

    def test_does_not_fire_when_health_is_not_critical(self) -> None:
        myself = make_myself(specials=1, health_percent=30.0)
        context: set[Token] = {myself}

        self.assertEqual(could_call_police(context), set())

    def test_never_fires_with_zero_specials(self) -> None:
        myself = make_myself(specials=0, health_percent=1.0)
        context: set[Token] = {myself}

        self.assertEqual(could_call_police(context), set())

    def test_never_fires_when_holding_an_enemy(self) -> None:
        myself = make_myself(specials=1, health_percent=10.0, held_weapon_type=0x10)
        context: set[Token] = {myself}

        self.assertEqual(could_call_police(context), set())

    def test_last_life_fires_at_a_higher_health_threshold(self) -> None:
        # A KO on the last life risks a continue/game-over instead of a free
        # respawn (player-health-lives-and-combat.md) -- 30% is above the
        # ordinary 18% threshold but below the last-life 35% one.
        myself = make_myself(specials=1, health_percent=30.0, lives=1)
        context: set[Token] = {myself}

        self.assertEqual(could_call_police(context), {CallPolice(actor_slot="P1")})

    def test_last_life_still_respects_its_own_higher_threshold(self) -> None:
        myself = make_myself(specials=1, health_percent=40.0, lives=1)
        context: set[Token] = {myself}

        self.assertEqual(could_call_police(context), set())


class CouldHoldActionsTests(unittest.TestCase):
    def test_front_hold_offers_knee_and_flip(self) -> None:
        myself = make_myself(
            world_x=100, world_y=100, held_weapon_type=0x01, action_state=0x60
        )
        near = make_enemy(slot="near", world_x=110, world_y=100)
        context: set[Token] = {myself, near}

        result = could_hold_actions(context)

        self.assertIn(AttackHeldEnemy(actor_slot="P1", target_slot="near"), result)
        self.assertIn(FlipHold(actor_slot="P1", target_slot="near"), result)

    def test_does_not_fire_when_holding_a_weapon(self) -> None:
        myself = make_myself(held_weapon_type=0x08, action_state=0x60)
        enemy = make_enemy(world_x=110, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_hold_actions(context), set())

    def test_does_not_fire_when_not_holding_anything(self) -> None:
        myself = make_myself(held_weapon_type=0, action_state=0x60)
        enemy = make_enemy(world_x=110, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_hold_actions(context), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself = make_myself(held_weapon_type=0x01, action_state=0x60)
        enemy = make_enemy(world_x=110, world_y=100)
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}

        self.assertEqual(could_hold_actions(context), set())

    def test_no_crash_with_no_enemies(self) -> None:
        myself = make_myself(held_weapon_type=0x01, action_state=0x60)
        result = could_hold_actions({myself})
        self.assertTrue(any(isinstance(t, AttackHeldEnemy) for t in result))


class CouldJumpAttackTests(unittest.TestCase):
    def test_fires_when_horizontal_jump_kick_is_useful(self) -> None:
        # Jump-kick only beyond punch outer (Axel 50) with real ΔX, in front.
        myself = make_myself(world_x=100, world_y=100, is_airborne=False, facing_left=False)
        enemy = make_enemy(world_x=160, world_y=105)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        result = could_jump_attack(context)

        self.assertEqual(result, {JumpAttack(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_in_place(self) -> None:
        myself = make_myself(world_x=100, world_y=100, is_airborne=False)
        enemy = make_enemy(world_x=110, world_y=100)  # too close / no air travel
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        self.assertEqual(could_jump_attack(context), set())

    def test_does_not_fire_when_airborne(self) -> None:
        myself = make_myself(world_x=100, world_y=100, is_airborne=True, facing_left=False)
        enemy = make_enemy(world_x=160, world_y=105)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        self.assertEqual(could_jump_attack(context), set())

    def test_does_not_fire_out_of_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, is_airborne=False)
        enemy = make_enemy(world_x=500, world_y=500)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        self.assertEqual(could_jump_attack(context), set())

    def test_does_not_fire_when_holding_an_enemy(self) -> None:
        myself = make_myself(
            world_x=100, world_y=100, is_airborne=False, held_weapon_type=0x01, facing_left=False
        )
        enemy = make_enemy(world_x=160, world_y=105)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        self.assertEqual(could_jump_attack(context), set())

    def test_axel_does_not_fire_beyond_his_shorter_kick_range(self) -> None:
        # controls-and-input.md "Closed-form trajectory summary": Axel's
        # early-kick range is 60px, well short of the old flat 72px cap.
        myself = make_myself(world_x=100, world_y=100, is_airborne=False, facing_left=False)
        enemy = make_enemy(world_x=165, world_y=100)  # dx=65 > Axel's 60
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        self.assertEqual(could_jump_attack(context), set())

    def test_blaze_fires_at_a_range_beyond_axels_reach(self) -> None:
        myself = make_myself(
            character_id=2, character_name="Blaze", world_x=100, world_y=100,
            is_airborne=False, facing_left=False,
        )
        enemy = make_enemy(world_x=165, world_y=100)  # dx=65, within Blaze's 75

        result = could_jump_attack({myself, enemy})

        self.assertEqual(result, {JumpAttack(actor_slot="P1", target_slot="obj01")})


class CouldThrowKnifeTests(unittest.TestCase):
    def test_fires_when_holding_knife_and_enemy_outside_melee_but_in_knife_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=160, world_y=100)  # outside KNIFE_MELEE_X=40
        context: set[Token] = {myself, enemy}

        result = could_throw_knife(context)

        self.assertEqual(result, {ThrowKnife(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_when_enemy_is_in_melee_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=110, world_y=105)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_knife(context), set())

    def test_does_not_fire_when_holding_a_different_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x09)
        enemy = make_enemy(world_x=160, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_knife(context), set())

    def test_does_not_fire_when_enemy_beyond_knife_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=500, world_y=500)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_knife(context), set())


class CouldThrowPepperTests(unittest.TestCase):
    def test_fires_when_holding_pepper_and_enemy_outside_melee_but_in_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0C)
        enemy = make_enemy(world_x=160, world_y=100)  # outside KNIFE_MELEE_X=40
        context: set[Token] = {myself, enemy}

        result = could_throw_pepper(context)

        self.assertEqual(result, {ThrowPepper(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_when_enemy_is_in_melee_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0C)
        enemy = make_enemy(world_x=110, world_y=105)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_pepper(context), set())

    def test_does_not_fire_when_holding_a_different_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)  # knife
        enemy = make_enemy(world_x=160, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_pepper(context), set())

    def test_does_not_fire_when_enemy_beyond_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0C)
        enemy = make_enemy(world_x=500, world_y=500)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_pepper(context), set())


class CouldWalkToWeaponTests(unittest.TestCase):
    def test_fires_for_in_camera_upgrade_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        weapon = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x0A)
        context: set[Token] = {myself, camera, weapon}

        result = could_walk_to_weapon(context)

        self.assertEqual(result, {WalkToWeapon(actor_slot="P1", target_slot="wpn1")})

    def test_does_not_fire_for_same_or_worse_ranked_weapon(self) -> None:
        # Holding bat (rank 4); bottle is rank 3 — not an upgrade.
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        weapon = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x09)
        context: set[Token] = {myself, camera, weapon}

        self.assertEqual(could_walk_to_weapon(context), set())

    def test_does_not_fire_for_weapon_outside_camera_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        weapon = Weapon(slot="wpn1", world_x=999, world_y=999, weapon_type=0x0A)
        context: set[Token] = {myself, camera, weapon}

        self.assertEqual(could_walk_to_weapon(context), set())

    def test_produces_one_candidate_per_upgrade_not_just_the_best(self) -> None:
        # could_walk_to_weapon must not pre-select -- per AI.md, ranking
        # several same-kind candidates against each other is
        # determine_priority_decision's job (see test_priority.py's
        # test_walk_to_weapon_picks_the_higher_ranked_upgrade).
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        knife = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x08)
        pepper = Weapon(slot="wpn2", world_x=130, world_y=115, weapon_type=0x0C)
        context: set[Token] = {myself, camera, knife, pepper}

        result = could_walk_to_weapon(context)

        self.assertEqual(
            result,
            {
                WalkToWeapon(actor_slot="P1", target_slot="wpn1"),
                WalkToWeapon(actor_slot="P1", target_slot="wpn2"),
            },
        )

    def test_knife_is_upgrade_over_bat(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        knife = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x08)
        context: set[Token] = {myself, camera, knife}

        result = could_walk_to_weapon(context)

        self.assertEqual(result, {WalkToWeapon(actor_slot="P1", target_slot="wpn1")})


class CouldWalkToPickupTests(unittest.TestCase):
    def test_fires_for_health_when_missing_enough(self) -> None:
        myself = make_myself(world_x=100, world_y=100, health=40, health_percent=50.0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        food = HealthPickup(
            slot="food1", world_x=120, world_y=110, pickup_type=0x4B, health_delta=20
        )
        context: set[Token] = {myself, camera, food}

        result = could_walk_to_pickup(context)

        self.assertEqual(result, {WalkToPickup(actor_slot="P1", target_slot="food1")})

    def test_does_not_fire_for_health_when_full(self) -> None:
        myself = make_myself(world_x=100, world_y=100, health=80, health_percent=100.0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        food = HealthPickup(
            slot="food1", world_x=120, world_y=110, pickup_type=0x47, health_delta=80
        )
        context: set[Token] = {myself, camera, food}

        self.assertEqual(could_walk_to_pickup(context), set())


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


class CouldWalkToBreakableTests(unittest.TestCase):
    def test_fires_for_an_in_camera_breakable_beyond_smash_range(self) -> None:
        myself = make_myself(world_x=0, world_y=0)
        camera = CameraRange(left=-50, right=200, top=-50, bottom=200)
        prop = Breakable(slot="obj09", world_x=60, world_y=0, type_id=0x40)
        context: set[Token] = {myself, camera, prop}

        result = could_walk_to_breakable(context)

        self.assertEqual(result, {WalkToBreakable(actor_slot="P1", target_slot="obj09")})

    def test_does_not_fire_when_already_in_smash_range(self) -> None:
        myself = make_myself(world_x=0, world_y=0)
        camera = CameraRange(left=-50, right=200, top=-50, bottom=200)
        prop = Breakable(slot="obj09", world_x=10, world_y=0, type_id=0x40)
        context: set[Token] = {myself, camera, prop}

        self.assertEqual(could_walk_to_breakable(context), set())

    def test_produces_one_candidate_per_reachable_breakable_not_just_the_nearest(self) -> None:
        # Must not pre-select -- per AI.md, ranking several same-kind
        # candidates against each other is determine_priority_decision's
        # job (see test_priority.py's
        # test_walk_to_breakable_picks_the_closer_of_two_candidates).
        myself = make_myself(world_x=0, world_y=0)
        camera = CameraRange(left=-50, right=300, top=-50, bottom=200)
        near = Breakable(slot="near", world_x=60, world_y=0, type_id=0x40)
        far = Breakable(slot="far", world_x=250, world_y=0, type_id=0x40)
        context: set[Token] = {myself, camera, near, far}

        result = could_walk_to_breakable(context)

        self.assertEqual(
            result,
            {
                WalkToBreakable(actor_slot="P1", target_slot="near"),
                WalkToBreakable(actor_slot="P1", target_slot="far"),
            },
        )

    def test_missing_camera_still_considers_off_screen_breakables(self) -> None:
        myself = make_myself(world_x=0, world_y=0)
        prop = Breakable(slot="obj09", world_x=60, world_y=0, type_id=0x40)
        context: set[Token] = {myself, prop}

        result = could_walk_to_breakable(context)

        self.assertEqual(result, {WalkToBreakable(actor_slot="P1", target_slot="obj09")})


if __name__ == "__main__":
    unittest.main()
