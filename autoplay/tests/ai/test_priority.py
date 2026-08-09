import unittest

from sor_autoplay.ai.tokens import (
    AttackHeldEnemy,
    Breakable,
    CounterGrab,
    HealthPickup,
    JumpAttack,
    LifePickup,
    Punch,
    ScorePickup,
    SmashBreakable,
    Supplex,
    ThrowKnife,
    Weapon,
)
from sor_autoplay.ai.tokens import Myself
from sor_autoplay.ai.tokens import Enemy
from sor_autoplay.ai.tokens import CallPolice
from sor_autoplay.ai.priority import determine_priority_decision
from sor_autoplay.ai.tokens import Decision, find_all
from sor_autoplay.ai.tokens import (
    WalkToAdvanceStage,
    WalkToBreakable,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from sor_autoplay.phases import CombatPhase


def _enemy(slot: str, combat_phase: CombatPhase, **overrides) -> Enemy:
    fields = dict(
        slot=slot,
        type_id=0x20,
        world_x=0,
        world_y=0,
        health=10,
        combat_phase=combat_phase,
        targets_player=1,
        facing_left=False,
    )
    fields.update(overrides)
    return Enemy(**fields)


def _myself(**overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=100,
        world_y=100,
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
        enemy = _enemy("obj01", CombatPhase.NORMAL)
        context = {
            enemy,
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
            WalkToAdvanceStage(actor_slot="P1", direction="right"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)

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


class DetermineEmergencyTokenConditionTests(unittest.TestCase):
    """Branches that were reachable in the old constant chain but had no
    dedicated coverage: WalkToPickup tiers, WalkToWeapon rank, ThrowKnife
    range, and the two Breakable decisions' target-presence check."""

    def test_walk_to_pickup_critical_health_beats_life_pickup(self) -> None:
        critical = _myself(health_percent=30.0)
        pickup = HealthPickup(slot="obj01", world_x=0, world_y=0, pickup_type=0x4B, health_delta=20)
        life_pickup = LifePickup(slot="obj02", world_x=0, world_y=0, pickup_type=0x4C)
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
        pickup = HealthPickup(slot="obj01", world_x=0, world_y=0, pickup_type=0x4B, health_delta=20)
        score_pickup = ScorePickup(slot="obj02", world_x=0, world_y=0, pickup_type=0x3F, points=3000)
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
        life_pickup = LifePickup(slot="obj01", world_x=0, world_y=0, pickup_type=0x4C)
        score_pickup = ScorePickup(slot="obj02", world_x=0, world_y=0, pickup_type=0x3F, points=3000)
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
        unarmed = _myself(held_weapon_type=0)
        knife = Weapon(slot="obj01", world_x=0, world_y=0, weapon_type=0x08)
        context = {unarmed, knife, WalkToWeapon(actor_slot="P1", target_slot="obj01")}

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToWeapon)

    def test_walk_to_weapon_scores_zero_when_not_an_upgrade(self) -> None:
        # Already holding the best weapon: the floor pepper spray isn't an
        # upgrade, so WalkToWeapon's condition is false and it loses to a
        # WalkToNearEnemy (14) that would otherwise be a weaker decision.
        armed_with_knife = _myself(held_weapon_type=0x08)
        pepper = Weapon(slot="obj01", world_x=0, world_y=0, weapon_type=0x0C)
        enemy = _enemy("obj02", CombatPhase.NORMAL)
        context = {
            armed_with_knife,
            pepper,
            enemy,
            WalkToWeapon(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)

    def test_throw_knife_scores_within_range_beyond_melee(self) -> None:
        actor = _myself(world_x=0, world_y=0)
        far_enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=60, world_y=0)
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
        actor = _myself(world_x=0, world_y=0)
        near_enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=10, world_y=0)
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

    def test_smash_breakable_scores_when_target_present(self) -> None:
        prop = Breakable(slot="obj01", world_x=0, world_y=0, type_id=0x70)
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

        with self.assertLogs("sor_autoplay.ai.priority", level="WARNING"):
            result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIn(decisions[0], (punch_a, punch_b))


if __name__ == "__main__":
    unittest.main()
