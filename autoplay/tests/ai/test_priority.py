import unittest

from sor_autoplay.ai.tokens import (
    AttackHeldEnemy,
    Breakable,
    CounterGrab,
    HealthPickup,
    JumpAttack,
    LifePickup,
    Punch,
    RearAttack,
    ScorePickup,
    SmashBreakable,
    SprayPepper,
    StabWithKnifeOrBottle,
    Supplex,
    SwingBatOrPipe,
    TechRecover,
    ThrowKnife,
    ThrowPepper,
    Weapon,
)
from sor_autoplay.ai.tokens import Myself
from sor_autoplay.ai.tokens import ClosingEnemy, Enemy
from sor_autoplay.ai.tokens import CallPolice
from sor_autoplay.ai.tokens import CameraRange
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.priority import determine_priority_decision as _rank_decisions
from sor_autoplay.ai.tokens import Decision, find_all
from sor_autoplay.ai.tokens import (
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToBreakable,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from sor_autoplay.phases import CombatPhase


def determine_priority_decision(context):
    """Rank a context built the way AI.md's loop builds it.

    Several ``_emergency_*`` functions read ``Inferred`` tokens
    (``PunishWindow``, ``IncomingMelee``, ``WeaponUpgrade``, ``Surrounded``)
    rather than re-deriving the same judgment from raw coordinates, and the
    loop always produces those before ranking. These tests hand-build the
    observed half of the context, so they derive the inferred half here.
    """

    return _rank_decisions(generate_inference_tokens(set(context)))


def _enemy(slot: str, combat_phase: CombatPhase, **overrides) -> Enemy:
    fields = dict(
        slot=slot,
        type_id=0x20,
        world_x=0,
        world_y=64,
        health=10,
        combat_phase=combat_phase,
        targets_player=1,
        facing_left=False,
    )
    fields.update(overrides)
    return Enemy(**fields)


def _camera() -> CameraRange:
    """A camera wide enough to contain every fixture position here."""

    return CameraRange(left=-200, right=600, top=0, bottom=112)


def _myself(**overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=100,
        world_y=64,
        health=80,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=False,
        combat_phase=CombatPhase.NORMAL,
        action_state=0x02,
        is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


class DetermineEmergencyWinnerTests(unittest.TestCase):
    def test_call_police_beats_punch_on_punishable_enemy(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        myself = _myself(health_percent=10.0)
        context = {
            punishable,
            myself,
            CallPolice(actor_slot="P1"),
            Punch(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], CallPolice)

    def test_call_police_on_last_life_beats_punch_above_ordinary_threshold(self) -> None:
        # 30% health is above the ordinary 18% threshold but below the
        # last-life 35% one, so emergency should still be raised.
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        myself = _myself(health_percent=30.0, lives=1)
        context = {
            punishable,
            myself,
            CallPolice(actor_slot="P1"),
            Punch(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], CallPolice)

    def test_call_police_below_full_health_loses_to_punishable_punch(self) -> None:
        # Above the health threshold, CallPolice's condition is false (0),
        # so a punishable Punch (60) wins instead.
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        myself = _myself(health_percent=100.0)
        context = {
            punishable,
            myself,
            CallPolice(actor_slot="P1"),
            Punch(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], Punch)

    def test_no_decisions_returns_context_unchanged(self) -> None:
        enemy = _enemy("obj01", CombatPhase.NORMAL)
        context = {enemy}

        result = determine_priority_decision(context)

        self.assertEqual(result, context)

    def test_walk_to_near_enemy_beats_walk_to_advance_stage(self) -> None:
        # AI.md: advancing the stage is the lowest-priority fallback.
        myself = _myself(world_x=0, world_y=50)
        enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=10, world_y=50)
        context = {
            myself,
            enemy,
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
            WalkToAdvanceStage(actor_slot="P1", direction="right"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)

    def test_walk_to_near_enemy_picks_the_closer_of_two_candidates(self) -> None:
        # could_walk_to_near_enemy (decide.py) no longer pre-selects the
        # nearest enemy -- this is now determine_priority_decision's job,
        # via _emergency_walk_to_near_enemy's distance-bucketed score.
        myself = _myself(world_x=0, world_y=64)
        near = _enemy("obj01", CombatPhase.NORMAL, world_x=10, world_y=64)
        far = _enemy("obj02", CombatPhase.NORMAL, world_x=150, world_y=64)
        context = {
            myself,
            near,
            far,
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].target_slot, "obj01")

    def test_advance_stage_fires_when_only_remaining_enemy_is_off_screen_at_zero_health(
        self,
    ) -> None:
        # Same regression as test_decide.py's could_walk_to_advance_stage
        # coverage, exercised through the emergency function this time:
        # priority.py must reach the same "not blocking" conclusion as
        # decide.py's own gate, via the shared _advance_blocking_enemies.
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        stranded = _enemy("obj01", CombatPhase.NORMAL, world_x=500, world_y=64, health=0)
        context = {
            camera,
            stranded,
            WalkToAdvanceStage(actor_slot="P1", direction="right"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToAdvanceStage)

    def test_supplex_always_outranks_punch_tier(self) -> None:
        held = _enemy("obj01", CombatPhase.GRABBED)
        punishable = _enemy("obj02", CombatPhase.KNOCKDOWN)
        context = {
            held,
            punishable,
            Supplex(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], Supplex)

    def test_hold_move_scores_zero_when_target_not_grabbed(self) -> None:
        # The "Enemy when held" condition is CombatPhase.GRABBED; a target in
        # any other phase (context desync, e.g. it just broke free) scores 0.
        not_held = _enemy("obj01", CombatPhase.NORMAL)
        punishable = _enemy("obj02", CombatPhase.KNOCKDOWN)
        context = {
            not_held,
            punishable,
            AttackHeldEnemy(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], Punch)

    def test_counter_grab_beats_call_police(self) -> None:
        myself = _myself(combat_phase=CombatPhase.HELD_BY_ENEMY, health_percent=10.0)
        context = {
            myself,
            CounterGrab(actor_slot="P1"),
            CallPolice(actor_slot="P1"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], CounterGrab)

    def test_tech_recover_beats_call_police(self) -> None:
        myself = _myself(
            combat_phase=CombatPhase.HURT_PLAYER,
            action_state=0x72,
            tech_armed=1,
            health_percent=10.0,
        )
        context = {
            myself,
            TechRecover(actor_slot="P1"),
            CallPolice(actor_slot="P1"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], TechRecover)

    def test_tech_recover_scores_zero_when_not_armed(self) -> None:
        myself = _myself(
            combat_phase=CombatPhase.HURT_PLAYER,
            action_state=0x72,
            tech_armed=0,
            health_percent=10.0,
        )
        context = {
            myself,
            TechRecover(actor_slot="P1"),
            CallPolice(actor_slot="P1"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], CallPolice)

    def test_counter_grab_beats_tech_recover(self) -> None:
        # Being held by an enemy right now outranks a still-open landing
        # tech window from an earlier throw.
        myself = _myself(
            combat_phase=CombatPhase.HELD_BY_ENEMY,
            action_state=0x72,
            tech_armed=1,
        )
        context = {
            myself,
            CounterGrab(actor_slot="P1"),
            TechRecover(actor_slot="P1"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], CounterGrab)

    def test_counter_grab_scores_zero_when_not_held(self) -> None:
        myself = _myself(combat_phase=CombatPhase.NORMAL, health_percent=10.0)
        context = {
            myself,
            CounterGrab(actor_slot="P1"),
            CallPolice(actor_slot="P1"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], CallPolice)

    def test_jump_attack_emergency_splits_punishable_vs_default(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        normal = _enemy("obj02", CombatPhase.NORMAL)

        punishable_context = {
            punishable,
            JumpAttack(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }
        result = determine_priority_decision(punishable_context)
        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], JumpAttack)

        default_context = {
            normal,
            JumpAttack(actor_slot="P1", target_slot="obj02"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }
        result = determine_priority_decision(default_context)
        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], JumpAttack)


class DetermineEmergencyMeleeWeaponSiblingsTests(unittest.TestCase):
    """SwingBatOrPipe/StabWithKnifeOrBottle/SprayPepper share Punch's exact
    emergency formula (_emergency_melee_strike) -- one representative check
    per sibling that the shared wiring wins over a punishable-but-farther
    WalkToNearEnemy exactly like Punch does."""

    def test_swing_bat_or_pipe_beats_walk_to_near_enemy_on_punishable_target(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        context = {
            punishable,
            SwingBatOrPipe(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], SwingBatOrPipe)

    def test_stab_with_knife_or_bottle_beats_walk_to_near_enemy_on_punishable_target(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        context = {
            punishable,
            StabWithKnifeOrBottle(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], StabWithKnifeOrBottle)

    def test_spray_pepper_beats_walk_to_near_enemy_on_punishable_target(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        context = {
            punishable,
            SprayPepper(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], SprayPepper)


class DetermineEmergencyTokenConditionTests(unittest.TestCase):
    """Branches that were reachable in the old constant chain but had no
    dedicated coverage: WalkToPickup tiers, WalkToWeapon rank, ThrowKnife
    range, and the two Breakable decisions' target-presence check."""

    def test_walk_to_pickup_critical_health_beats_life_pickup(self) -> None:
        critical = _myself(health_percent=30.0)
        pickup = HealthPickup(slot="obj01", world_x=0, world_y=64, pickup_type=0x4B, health_delta=20)
        life_pickup = LifePickup(slot="obj02", world_x=0, world_y=64, pickup_type=0x4C)
        context = {
            critical,
            pickup,
            life_pickup,
            WalkToPickup(actor_slot="P1", target_slot="obj01"),
            WalkToPickup(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].target_slot, "obj01")

    def test_walk_to_pickup_full_health_pickup_beats_score_pickup(self) -> None:
        # At full health the HealthPickup formula drops from critical (50)
        # to its non-critical tier (15), which still beats a ScorePickup (3).
        healthy = _myself(health_percent=100.0)
        pickup = HealthPickup(slot="obj01", world_x=0, world_y=64, pickup_type=0x4B, health_delta=20)
        score_pickup = ScorePickup(slot="obj02", world_x=0, world_y=64, pickup_type=0x3F, points=3000)
        context = {
            healthy,
            pickup,
            score_pickup,
            WalkToPickup(actor_slot="P1", target_slot="obj01"),
            WalkToPickup(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].target_slot, "obj01")

    def test_walk_to_pickup_life_beats_score(self) -> None:
        actor = _myself()
        life_pickup = LifePickup(slot="obj01", world_x=0, world_y=64, pickup_type=0x4C)
        score_pickup = ScorePickup(slot="obj02", world_x=0, world_y=64, pickup_type=0x3F, points=3000)
        context = {
            actor,
            life_pickup,
            score_pickup,
            WalkToPickup(actor_slot="P1", target_slot="obj01"),
            WalkToPickup(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].target_slot, "obj01")

    def test_walk_to_weapon_scores_when_rank_beats_held(self) -> None:
        # The camera matters: WeaponUpgrade is only inferred for a weapon
        # actually on screen, and _emergency_walk_to_weapon reads that token
        # rather than re-ranking the raw Weapon.
        unarmed = _myself(held_weapon_type=0)
        knife = Weapon(slot="obj01", world_x=0, world_y=64, weapon_type=0x08)
        context = {unarmed, knife, _camera(), WalkToWeapon(actor_slot="P1", target_slot="obj01")}

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToWeapon)

    def test_walk_to_weapon_picks_the_higher_ranked_upgrade(self) -> None:
        # could_walk_to_weapon (decide.py) no longer pre-selects the best
        # upgrade -- this is now determine_priority_decision's job, via
        # _emergency_walk_to_weapon's rank-scaled score.
        unarmed = _myself(held_weapon_type=0)
        knife = Weapon(slot="obj01", world_x=0, world_y=64, weapon_type=0x08)  # rank 5
        pepper = Weapon(slot="obj02", world_x=0, world_y=64, weapon_type=0x0C)  # rank 2
        context = {
            unarmed,
            knife,
            pepper,
            _camera(),
            WalkToWeapon(actor_slot="P1", target_slot="obj01"),
            WalkToWeapon(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].target_slot, "obj01")

    def test_walk_to_weapon_scores_zero_when_not_an_upgrade(self) -> None:
        # Already holding the best weapon: the floor pepper spray isn't an
        # upgrade, so WalkToWeapon's condition is false and it loses to a
        # WalkToNearEnemy (14) that would otherwise be a weaker decision.
        armed_with_knife = _myself(held_weapon_type=0x08)
        pepper = Weapon(slot="obj01", world_x=0, world_y=64, weapon_type=0x0C)
        enemy = _enemy("obj02", CombatPhase.NORMAL)
        context = {
            armed_with_knife,
            pepper,
            enemy,
            _camera(),
            WalkToWeapon(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)

    def test_throw_knife_scores_within_range_beyond_melee(self) -> None:
        actor = _myself(world_x=0, world_y=64)
        far_enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=60, world_y=64)
        context = {
            actor,
            far_enemy,
            ThrowKnife(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], ThrowKnife)

    def test_throw_knife_scores_zero_when_still_in_melee(self) -> None:
        actor = _myself(world_x=0, world_y=64)
        near_enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=10, world_y=64)
        context = {
            actor,
            near_enemy,
            ThrowKnife(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)

    def test_throw_knife_picks_the_closer_of_two_qualifying_enemies(self) -> None:
        # could_throw_knife (decide.py) no longer pre-selects the nearest
        # enemy -- this is now determine_priority_decision's job, via the
        # shared _emergency_thrown_weapon's distance-bucketed score.
        actor = _myself(world_x=0, world_y=64)
        near = _enemy("obj01", CombatPhase.NORMAL, world_x=50, world_y=64)
        far = _enemy("obj02", CombatPhase.NORMAL, world_x=85, world_y=64)
        context = {
            actor,
            near,
            far,
            ThrowKnife(actor_slot="P1", target_slot="obj01"),
            ThrowKnife(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].target_slot, "obj01")

    def test_throw_pepper_scores_within_range_beyond_melee(self) -> None:
        actor = _myself(world_x=0, world_y=64)
        far_enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=60, world_y=64)
        context = {
            actor,
            far_enemy,
            ThrowPepper(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], ThrowPepper)

    def test_throw_pepper_scores_zero_when_still_in_melee(self) -> None:
        actor = _myself(world_x=0, world_y=64)
        near_enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=10, world_y=64)
        context = {
            actor,
            near_enemy,
            ThrowPepper(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)

    def test_smash_breakable_scores_when_target_present(self) -> None:
        prop = Breakable(slot="obj01", world_x=0, world_y=64, type_id=0x70)
        enemy = _enemy("obj02", CombatPhase.NORMAL)
        context = {
            prop,
            enemy,
            SmashBreakable(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], SmashBreakable)

    def test_walk_to_breakable_picks_the_closer_of_two_candidates(self) -> None:
        # could_walk_to_breakable (decide.py) no longer pre-selects the
        # nearest breakable -- this is now determine_priority_decision's
        # job, via _emergency_walk_to_breakable's distance-bucketed score.
        myself = _myself(world_x=0, world_y=64)
        near = Breakable(slot="near", world_x=10, world_y=64, type_id=0x40)
        far = Breakable(slot="far", world_x=150, world_y=64, type_id=0x40)
        context = {
            myself,
            near,
            far,
            WalkToBreakable(actor_slot="P1", target_slot="near"),
            WalkToBreakable(actor_slot="P1", target_slot="far"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].target_slot, "near")

    def test_walk_to_breakable_scores_zero_when_target_missing(self) -> None:
        enemy = _enemy("obj02", CombatPhase.NORMAL)
        context = {
            enemy,
            WalkToBreakable(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)


class DetermineEmergencyRearAttackTests(unittest.TestCase):
    """RearAttack's emergency only depends on the target's combat_phase, not
    on whether the candidate was triggered by the real band check or by a
    ClosingEnemy early-warning token -- confirms priority.py needed no
    change when could_rear_attack learned to react to ClosingEnemy."""

    def test_dangerous_target_wins_regardless_of_a_closing_enemy_token(self) -> None:
        dangerous = _enemy("objA", CombatPhase.ATTACKING)
        calm = _enemy("objB", CombatPhase.NORMAL)
        rear_dangerous = RearAttack(actor_slot="P1", target_slot="objA")
        rear_calm = RearAttack(actor_slot="P1", target_slot="objB")
        # objB's decision exists only because of the early-warning token, not
        # because it is in the real band -- must not out-rank a genuine
        # dangerous-phase target sitting in range.
        context = {
            dangerous,
            calm,
            rear_dangerous,
            rear_calm,
            ClosingEnemy(slot="objB"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIs(decisions[0], rear_dangerous)

    def test_loses_to_turning_around_when_the_chord_is_not_warranted(self) -> None:
        # The abuse case: a lone enemy at the actor's back, far enough out of
        # the punch dead zone that turning around and punching works. $322A
        # costs up to 21 frames of startup and hits only by current position,
        # so it must not be the reflex answer -- the turn-around
        # (WalkToNearEnemy, which decide.py now offers for this same enemy)
        # has to win.
        myself = _myself(world_x=100, world_y=100)  # Axel, facing right
        behind = _enemy("obj01", CombatPhase.NORMAL, world_x=70, world_y=100)
        context = {
            myself,
            behind,
            RearAttack(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)

    def test_still_fires_when_it_is_the_only_option(self) -> None:
        # "Se poder usar, usar": nothing else reaches this enemy, so the
        # chord is still the decision -- de-preferring it must not mean
        # standing there doing nothing.
        myself = _myself(world_x=100, world_y=100)
        behind = _enemy("obj01", CombatPhase.NORMAL, world_x=70, world_y=100)
        context = {myself, behind, RearAttack(actor_slot="P1", target_slot="obj01")}

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], RearAttack)

    def test_outranks_turning_around_inside_the_punch_dead_zone(self) -> None:
        # dx=-10 is closer than Axel's punch_inner (16): turning around
        # leaves the enemy unhittable, so the chord is the right tool and
        # keeps its top-tier score.
        myself = _myself(world_x=100, world_y=100)
        behind = _enemy("obj01", CombatPhase.NORMAL, world_x=90, world_y=100)
        context = {
            myself,
            behind,
            RearAttack(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], RearAttack)

    def test_outranks_a_punch_while_boxed_in(self) -> None:
        # Flanked front and back: spending the turn hands the front enemy a
        # free hit, which is exactly what the chord exists for -- it must
        # beat punching either one.
        myself = _myself(world_x=100, world_y=100)
        behind = _enemy("obj01", CombatPhase.NORMAL, world_x=70, world_y=100)
        flanker = _enemy("obj02", CombatPhase.NORMAL, world_x=140, world_y=100)
        context = {
            myself,
            behind,
            flanker,
            RearAttack(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], RearAttack)

    def test_loses_to_a_punch_on_a_front_enemy_when_not_warranted(self) -> None:
        # Not boxed in (the punchable enemy is on the same side as nothing
        # else) and out of the dead zone: a fast, reliable strike wins.
        myself = _myself(world_x=100, world_y=100)
        behind = _enemy("obj01", CombatPhase.NORMAL, world_x=70, world_y=100)
        context = {
            myself,
            behind,
            RearAttack(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], Punch)


class DetermineEmergencyRetreatFromDangerTests(unittest.TestCase):
    def test_picks_the_closer_of_two_retreat_candidates(self) -> None:
        # Both distances stay inside reach.too_close_to_keep_approaching's
        # caution zone (Axel: punch_outer 50 + RETREAT_CAUTION_MARGIN 24), the
        # only range could_retreat_from_danger ever produces a candidate at.
        # An out-of-zone distance here would sit on the band's floor together
        # with everything else and make this pass or fail on the random
        # tie-break rather than on the ranking under test.
        # world_y sits inside the playable lane (LANE_Y_MIN..lane max): an
        # enemy outside it is not a live target at all, so no IncomingMelee
        # would be inferred and neither candidate would rank as a retreat.
        myself = _myself(world_x=0, world_y=64)
        near = _enemy("obj01", CombatPhase.ATTACKING, world_x=20, world_y=64)
        far = _enemy("obj02", CombatPhase.ATTACKING, world_x=70, world_y=64)
        context = {
            myself,
            near,
            far,
            RetreatFromDanger(actor_slot="P1", target_slot="obj01"),
            RetreatFromDanger(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].target_slot, "obj01")

    def test_outranks_walking_toward_a_different_far_enemy(self) -> None:
        # The actor can only do one thing -- backing away from an imminent,
        # not-yet-hittable threat must win over still approaching a
        # completely different, farther-off target.
        myself = _myself(world_x=0, world_y=64)
        dangerous_close = _enemy("obj01", CombatPhase.ATTACKING, world_x=60, world_y=64)
        calm_far = _enemy("obj02", CombatPhase.NORMAL, world_x=300, world_y=64)
        context = {
            myself,
            dangerous_close,
            calm_far,
            RetreatFromDanger(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], RetreatFromDanger)

    def test_loses_to_a_punch_on_a_different_enemy(self) -> None:
        # RetreatFromDanger's own docstring: "lower than any real attack so
        # attacking always wins once actually possible". Its band used to be
        # 30..20, which beat a plain Punch (20), a JumpAttack (18/28) and a
        # knife throw (21..25) -- so a dangerous enemy closing in made the
        # actor back away from a *different* enemy it could already hit.
        myself = _myself(world_x=0, world_y=64)
        dangerous_close = _enemy("obj01", CombatPhase.ATTACKING, world_x=20, world_y=64)
        punchable = _enemy("obj02", CombatPhase.NORMAL, world_x=40, world_y=64)
        context = {
            myself,
            dangerous_close,
            punchable,
            RetreatFromDanger(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], Punch)

    def test_loses_to_the_weakest_real_attack(self) -> None:
        # JumpAttack against a non-punishable target (18) is the lowest real
        # attack tier there is -- retreat must sit under even that.
        myself = _myself(world_x=0, world_y=64)
        dangerous_close = _enemy("obj01", CombatPhase.ATTACKING, world_x=20, world_y=64)
        kickable = _enemy("obj02", CombatPhase.NORMAL, world_x=60, world_y=64)
        context = {
            myself,
            dangerous_close,
            kickable,
            RetreatFromDanger(actor_slot="P1", target_slot="obj01"),
            JumpAttack(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], JumpAttack)

    def test_scores_zero_when_target_missing(self) -> None:
        # RetreatFromDanger for a target that has since vanished from the
        # context must not out-rank a real candidate for a present enemy.
        myself = _myself(world_x=0, world_y=64)
        present = _enemy("obj02", CombatPhase.NORMAL, world_x=10, world_y=64)
        context = {
            myself,
            present,
            RetreatFromDanger(actor_slot="P1", target_slot="obj01"),  # obj01 missing
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)


class DeterminePriorityTieBreakTests(unittest.TestCase):
    def test_priority_field_breaks_an_emergency_tie(self) -> None:
        enemy_a = _enemy("objA", CombatPhase.NORMAL)  # non-punishable -> emergency 20
        enemy_b = _enemy("objB", CombatPhase.NORMAL)  # non-punishable -> emergency 20
        low = Punch(actor_slot="P1", target_slot="objA", priority=5)
        high = Punch(actor_slot="P1", target_slot="objB", priority=50)
        context = {enemy_a, enemy_b, low, high}

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIs(decisions[0], high)


class DeterminePriorityRandomTieTests(unittest.TestCase):
    def test_exact_tie_logs_warning_and_still_picks_exactly_one(self) -> None:
        enemy_a = _enemy("objA", CombatPhase.NORMAL)
        enemy_b = _enemy("objB", CombatPhase.NORMAL)
        punch_a = Punch(actor_slot="P1", target_slot="objA")
        punch_b = Punch(actor_slot="P1", target_slot="objB")
        context = {enemy_a, enemy_b, punch_a, punch_b}

        with self.assertLogs("sor_autoplay.ai.priority", level="WARNING") as logs:
            result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIn(decisions[0], (punch_a, punch_b))
        # The two tied Punch candidates target different enemies -- the log
        # must show that (full repr), not just the shared class name, or it
        # misleadingly reads as the exact same decision logged twice.
        message = logs.output[0]
        self.assertIn("target_slot='objA'", message)
        self.assertIn("target_slot='objB'", message)


if __name__ == "__main__":
    unittest.main()
