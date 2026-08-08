import unittest

from sor_autoplay.ai.attack_decisions import CounterGrab, JumpAttack, Punch, Supplex
from sor_autoplay.ai.character import Myself
from sor_autoplay.ai.enemy import Enemy, Jack, Signal
from sor_autoplay.ai.hazard_tokens import IncomingProjectile
from sor_autoplay.ai.police_decision import CallPolice
from sor_autoplay.ai.priority import determine_priority_decision, _sidestep_emergency
from sor_autoplay.ai.tokens import Decision, find_all
from sor_autoplay.ai.walk_decisions import Sidestep, WalkToAdvanceStage, WalkToNearEnemy
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
    def test_sidestep_no_longer_beats_walk_to_near_enemy(self) -> None:
        """Sidestep is deliberately downgraded to the emergency floor (see
        the TODO on _EMERGENCY_SIDESTEP_FLOOR in priority.py) until its
        target-selection heuristics are reworked, so it must not outrank a
        real action just because a dangerous enemy is present."""

        dangerous = _enemy("obj01", CombatPhase.ATTACKING)
        context = {
            dangerous,
            Sidestep(actor_slot="P1", threat_slot="obj01", direction="up"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)
        # Information tokens (the Enemy) must survive untouched.
        self.assertIn(dangerous, result)

    def test_sidestep_still_wins_when_it_is_the_only_decision(self) -> None:
        """The floor keeps Sidestep a functional last resort -- it just no
        longer competes with real actions."""

        dangerous = _enemy("obj01", CombatPhase.ATTACKING)
        context = {dangerous, Sidestep(actor_slot="P1", threat_slot="obj01", direction="up")}

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], Sidestep)

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

    def test_sidestep_with_unresolvable_threat_no_longer_ranks_above_walk(self) -> None:
        # The referenced Enemy is absent from context entirely.
        context = {
            Sidestep(actor_slot="P1", threat_slot="missing", direction="down"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)

    def test_sidestep_on_incoming_projectile_no_longer_beats_walk_to_near_enemy(self) -> None:
        # No Enemy at all with this slot -- only an IncomingProjectile.
        context = {
            IncomingProjectile(slot="proj01", world_x=0, world_y=0, vel_x=-1.0, vel_z=0.0),
            Sidestep(actor_slot="P1", threat_slot="proj01", direction="up"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], WalkToNearEnemy)

    def test_supplex_always_outranks_punch_tier(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        context = {
            punishable,
            Supplex(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], Supplex)

    def test_counter_grab_beats_sidestep_and_call_police(self) -> None:
        context = {
            CounterGrab(actor_slot="P1"),
            CallPolice(actor_slot="P1"),
            Sidestep(actor_slot="P1", threat_slot="obj01", direction="up"),
            _enemy("obj01", CombatPhase.ATTACKING),
        }

        result = determine_priority_decision(context)

        decisions = find_all(result, Decision)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], CounterGrab)

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


class SidestepUrgencyTests(unittest.TestCase):
    def test_two_dangerous_sidesteps_prefer_rear_threat(self) -> None:
        # Facing right: front is +X, rear is −X. Both ATTACKING.
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        front = _enemy(
            "front",
            CombatPhase.ATTACKING,
            world_x=130,
            world_y=100,
            facing_left=True,
        )
        rear = _enemy(
            "rear",
            CombatPhase.ATTACKING,
            world_x=70,
            world_y=100,
            facing_left=False,
        )
        step_front = Sidestep(actor_slot="P1", threat_slot="front", direction="up")
        step_rear = Sidestep(actor_slot="P1", threat_slot="rear", direction="down")
        context = {myself, front, rear, step_front, step_rear}

        self.assertGreater(
            _sidestep_emergency(step_rear, context),
            _sidestep_emergency(step_front, context),
        )
        result = determine_priority_decision(context)
        winner = find_all(result, Decision)[0]
        self.assertEqual(winner.threat_slot, "rear")

    def test_two_dangerous_sidesteps_prefer_closer_threat(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        near = _enemy("near", CombatPhase.ATTACKING, world_x=120, world_y=100, facing_left=True)
        far = _enemy("far", CombatPhase.ATTACKING, world_x=180, world_y=100, facing_left=True)
        step_near = Sidestep(actor_slot="P1", threat_slot="near", direction="up")
        step_far = Sidestep(actor_slot="P1", threat_slot="far", direction="up")
        context = {myself, near, far, step_near, step_far}

        self.assertGreater(
            _sidestep_emergency(step_near, context),
            _sidestep_emergency(step_far, context),
        )
        result = determine_priority_decision(context)
        self.assertEqual(find_all(result, Decision)[0].threat_slot, "near")

    def test_signal_outranks_garcia_at_same_range(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        garcia = _enemy("g", CombatPhase.ATTACKING, type_id=0x20, world_x=130, world_y=100)
        signal = Signal(
            slot="s",
            type_id=0x24,
            world_x=130,
            world_y=100,
            health=10,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
            facing_left=True,
        )
        step_g = Sidestep(actor_slot="P1", threat_slot="g", direction="up")
        step_s = Sidestep(actor_slot="P1", threat_slot="s", direction="up")
        context = {myself, garcia, signal, step_g, step_s}

        self.assertGreater(
            _sidestep_emergency(step_s, context),
            _sidestep_emergency(step_g, context),
        )

    def test_unarmed_outranks_armed_player_same_threat(self) -> None:
        threat = _enemy("t", CombatPhase.ATTACKING, world_x=130, world_y=100, facing_left=True)
        unarmed = _myself(held_weapon_type=0)
        armed = _myself(held_weapon_type=0x08)  # knife
        step = Sidestep(actor_slot="P1", threat_slot="t", direction="up")

        self.assertGreater(
            _sidestep_emergency(step, {unarmed, threat, step}),
            _sidestep_emergency(step, {armed, threat, step}),
        )

    def test_jack_with_weapon_boosts_urgency(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        bare = Jack(
            slot="j0",
            type_id=0x27,
            world_x=130,
            world_y=100,
            health=10,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
            facing_left=True,
            has_projectile=False,
        )
        armed = Jack(
            slot="j1",
            type_id=0x27,
            world_x=130,
            world_y=100,
            health=10,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
            facing_left=True,
            has_projectile=True,
        )
        step0 = Sidestep(actor_slot="P1", threat_slot="j0", direction="up")
        step1 = Sidestep(actor_slot="P1", threat_slot="j1", direction="up")

        self.assertGreater(
            _sidestep_emergency(step1, {myself, armed, step1}),
            _sidestep_emergency(step0, {myself, bare, step0}),
        )

    def test_two_sidesteps_never_log_random_tie(self) -> None:
        myself = _myself(world_x=100, world_y=100, facing_left=False)
        a = _enemy("a", CombatPhase.ATTACKING, world_x=125, world_y=100, facing_left=True)
        b = _enemy("b", CombatPhase.ATTACKING, world_x=140, world_y=105, facing_left=True)
        context = {
            myself,
            a,
            b,
            Sidestep(actor_slot="P1", threat_slot="a", direction="up"),
            Sidestep(actor_slot="P1", threat_slot="b", direction="down"),
        }
        # Should pick deterministically with no WARNING about random ties.
        with self.assertNoLogs("sor_autoplay.ai.priority", level="WARNING"):
            result = determine_priority_decision(context)
        self.assertEqual(len(find_all(result, Decision)), 1)


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
