import unittest

from sor_autoplay.ai.attack_decisions import Punch
from sor_autoplay.ai.enemy import Enemy
from sor_autoplay.ai.police_decision import CallPolice
from sor_autoplay.ai.priority import determine_priority_decision
from sor_autoplay.ai.tokens import Decision, find_all
from sor_autoplay.ai.walk_decisions import Sidestep, WalkToNearEnemy
from sor_autoplay.phases import CombatPhase


def _enemy(slot: str, combat_phase: CombatPhase) -> Enemy:
    return Enemy(
        slot=slot,
        type_id=0x20,
        world_x=0,
        world_y=0,
        health=10,
        combat_phase=combat_phase,
        targets_player=1,
        facing_left=False,
    )


class DetermineEmergencyWinnerTests(unittest.TestCase):
    def test_sidestep_on_dangerous_enemy_beats_walk_to_near_enemy(self) -> None:
        dangerous = _enemy("obj01", CombatPhase.ATTACKING)
        context = {
            dangerous,
            Sidestep(actor_slot="P1", threat_slot="obj01", direction="up"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], Sidestep)
        # Information tokens (the Enemy) must survive untouched.
        self.assertIn(dangerous, result)

    def test_call_police_beats_punch_on_punishable_enemy(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        context = {
            punishable,
            CallPolice(actor_slot="P1"),
            Punch(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], CallPolice)

    def test_no_decisions_returns_context_unchanged(self) -> None:
        enemy = _enemy("obj01", CombatPhase.NORMAL)
        context = {enemy}

        result = determine_priority_decision(context)

        self.assertEqual(result, context)

    def test_sidestep_with_unresolvable_threat_still_ranks_above_walk(self) -> None:
        # The referenced Enemy is absent from context entirely.
        context = {
            Sidestep(actor_slot="P1", threat_slot="missing", direction="down"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], Sidestep)


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
