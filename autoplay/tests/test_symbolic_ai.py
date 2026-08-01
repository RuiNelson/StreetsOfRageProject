"""Fuzzy inference, knowledge graph, and tactical solver regressions."""

from __future__ import annotations

import unittest
from dataclasses import replace

from sor_autoplay.agent.arbiter import GoalKind, GoalMemory, solve_goal
from sor_autoplay.agent.autoplanner import AutoPlanner
from sor_autoplay.agent.characters import PROFILES
from sor_autoplay.agent.combat import select_target
from sor_autoplay.agent.expert import DEFAULT_COMBAT_EXPERT
from sor_autoplay.agent.fuzzy import FuzzyInference, FuzzyRule, falling, rising
from sor_autoplay.agent.grabs import GrabMemory, context_from_player, decide_held
from sor_autoplay.agent.knowledge import (
    Relation,
    build_tactical_graph,
)
from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
from sor_autoplay.phases import CombatPhase

from tests.test_expert_planner import _entity, _grab_scene, _snapshot


def _player(*, x: int = 100, y: int = 64, action: int = 0x02):
    return _entity(
        kind="player",
        family="Player",
        symbol="1",
        label="P1",
        slot="P1",
        type_id=1,
        map_x=x,
        world_x=x,
        map_y=y,
        world_y=y,
        action_state=action,
        combat_phase=CombatPhase.NORMAL,
    )


class FuzzyInferenceTests(unittest.TestCase):
    def test_memberships_and_explanation_trace(self) -> None:
        self.assertEqual(rising(5, 0, 10), 0.5)
        self.assertEqual(falling(5, 0, 10), 0.5)
        engine = FuzzyInference(
            (
                FuzzyRule("calm", (), 0.0, weight=0.25),
                FuzzyRule("hurt-pack", ("hurt", "pack"), 1.0),
            )
        )
        result = engine.infer({"hurt": 0.8, "pack": 0.6})
        self.assertGreater(result.value, 0.6)
        self.assertIn("hurt-pack", tuple(name for name, _ in result.activations))


class KnowledgeGraphTests(unittest.TestCase):
    def test_round1_lane_zero_actor_is_not_reachable(self) -> None:
        me = _player()
        staged = _entity(
            slot="E0",
            map_x=240,
            world_x=240,
            map_y=0,
            world_y=0,
            primary_state=0x1301,
            combat_phase=CombatPhase.ATTACKING,
        )
        live = _entity(slot="E1", map_x=180, world_x=180, map_y=64, world_y=64)
        graph = build_tactical_graph(
            me, (me, staged, live), level_index=0, player_index=1
        )
        self.assertFalse(graph.entity_has(staged, Relation.REACHABLE))
        self.assertFalse(graph.entity_has(staged, Relation.BLOCKS_PROGRESS))
        self.assertTrue(graph.entity_has(live, Relation.REACHABLE))

    def test_boss_just_beyond_viewport_still_blocks_progress(self) -> None:
        me = _player(x=288, y=37)
        antonio = _entity(
            kind="boss",
            family="Antonio",
            type_id=0x56,
            slot="B0",
            label="Antonio",
            map_x=328,
            world_x=3848,
            map_y=37,
            world_y=37,
        )
        graph = build_tactical_graph(
            me, (me, antonio), level_index=0, player_index=1
        )
        self.assertTrue(graph.entity_has(antonio, Relation.REACHABLE))
        self.assertTrue(graph.entity_has(antonio, Relation.BLOCKS_PROGRESS))


class FuzzyTargetTests(unittest.TestCase):
    def test_closest_wins_when_peril_is_equal(self) -> None:
        me = _player()
        near = _entity(slot="E0", map_x=135, world_x=135, label="Near")
        far = _entity(slot="E1", map_x=190, world_x=190, label="Far")
        choice = select_target(me, (near, far), PROFILES[0])
        assert choice is not None
        self.assertEqual(choice.entity.label, "Near")

    def test_committed_ranged_threat_beats_closer_idle_enemy(self) -> None:
        me = _player()
        near = _entity(slot="E0", map_x=130, world_x=130, label="Near")
        ranged = _entity(
            slot="E1",
            family="Jack",
            type_id=0x27,
            map_x=205,
            world_x=205,
            label="Ranged",
            target_ptr=0xB800,
            combat_phase=CombatPhase.ATTACKING,
        )
        choice = select_target(me, (near, ranged), PROFILES[0], my_seat=1)
        assert choice is not None
        self.assertEqual(choice.entity.label, "Ranged")
        self.assertIn("attacking", choice.explanation)

    def test_focus_hysteresis_rejects_small_target_oscillation(self) -> None:
        me = _player()
        current = _entity(slot="E0", map_x=140, world_x=140, label="Current")
        challenger = _entity(slot="E1", map_x=137, world_x=137, label="Challenger")
        choice = select_target(
            me,
            (current, challenger),
            PROFILES[0],
            preferred_slot="E0",
        )
        assert choice is not None
        self.assertEqual(choice.entity.label, "Current")

    def test_visible_round1_boss_has_no_generic_distance_cutoff(self) -> None:
        me = _player(x=0)
        antonio = _entity(
            kind="boss",
            family="Antonio",
            type_id=0x56,
            slot="B0",
            label="Antonio",
            map_x=310,
            world_x=310,
        )
        choice = select_target(me, (antonio,), PROFILES[0])
        assert choice is not None
        self.assertEqual(choice.entity.label, "Antonio")


class TacticalSolverTests(unittest.TestCase):
    def test_safe_valuable_nearby_loot_beats_distant_idle_enemy(self) -> None:
        me = _player()
        foe = _entity(slot="E0", map_x=295, world_x=295, label="Far Garcia")
        life = _entity(
            kind="pickup",
            family="Life",
            type_id=0x4C,
            slot="I0",
            label="Extra life",
            map_x=112,
            world_x=112,
            health=None,
            combat_phase=CombatPhase.UNKNOWN,
        )
        graph = build_tactical_graph(
            me, (me, foe, life), level_index=0, player_index=1
        )
        target = select_target(me, (foe,), PROFILES[0], graph=graph)
        result = solve_goal(
            graph,
            me,
            target=None if target is None else target.entity,
            target_utility=0.0 if target is None else target.utility,
            item=life,
            pressure_urgency=0.0,
            health_percent=100.0,
            memory=GoalMemory(),
        )
        self.assertEqual(result.winner.kind, GoalKind.LOOT)

    def test_dangerous_enemy_makes_loot_infeasible(self) -> None:
        me = _player()
        foe = _entity(
            slot="E0",
            map_x=165,
            world_x=165,
            target_ptr=0xB800,
            combat_phase=CombatPhase.ATTACKING,
        )
        weapon = _entity(
            kind="weapon",
            family="Weapon",
            type_id=0x0B,
            slot="W0",
            label="Pipe",
            map_x=112,
            world_x=112,
            health=None,
            combat_phase=CombatPhase.UNKNOWN,
        )
        graph = build_tactical_graph(
            me, (me, foe, weapon), level_index=0, player_index=1
        )
        target = select_target(me, (foe,), PROFILES[0], graph=graph)
        assert target is not None
        result = solve_goal(
            graph,
            me,
            target=target.entity,
            target_utility=target.utility,
            item=weapon,
            pressure_urgency=0.7,
            health_percent=100.0,
            memory=GoalMemory(),
        )
        self.assertEqual(result.winner.kind, GoalKind.FIGHT)
        self.assertFalse(any(c.kind == GoalKind.LOOT for c in result.candidates))


class PolicyRegressionTests(unittest.TestCase):
    def test_staged_lane_zero_enemy_allows_progress(self) -> None:
        me = _player()
        staged = _entity(
            slot="E0",
            map_x=240,
            world_x=240,
            map_y=0,
            world_y=0,
            primary_state=0x1301,
            combat_phase=CombatPhase.ATTACKING,
        )
        decision = decide_actions(
            _snapshot((me, staged)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertTrue(decision.p1_mask & 0x08, decision.p1_note)
        self.assertIn("progress", decision.p1_note)

    def test_boss_forces_fight_before_nearby_weapon(self) -> None:
        me = _player(x=10)
        antonio = _entity(
            kind="boss",
            family="Antonio",
            type_id=0x56,
            slot="B0",
            label="Antonio",
            map_x=310,
            world_x=310,
        )
        weapon = _entity(
            kind="weapon",
            family="Weapon",
            type_id=0x0B,
            slot="W0",
            label="Pipe",
            map_x=20,
            world_x=20,
            health=None,
            combat_phase=CombatPhase.UNKNOWN,
        )
        decision = decide_actions(
            _snapshot((me, antonio, weapon)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertIn("Antonio", decision.p1_note)
        self.assertNotIn("loot", decision.p1_note)
        self.assertNotIn("progress", decision.p1_note)

    def test_antonio_at_scroll_boundary_is_targeted_not_progressed_past(self) -> None:
        me = _player(x=288, y=37)
        antonio = _entity(
            kind="boss",
            family="Antonio",
            type_id=0x56,
            slot="B0",
            label="Antonio",
            map_x=328,
            world_x=3848,
            map_y=37,
            world_y=37,
        )
        decision = decide_actions(
            _snapshot((me, antonio)),
            AgentConfig(p1_enabled=True, police_threshold=99.0),
            AgentState(),
        )
        self.assertIn("Antonio", decision.p1_note)
        self.assertNotIn("progress", decision.p1_note)

    def test_distant_antonio_charge_is_approached_not_fled_right(self) -> None:
        me = _player(x=300)
        antonio = _entity(
            kind="boss",
            family="Antonio",
            type_id=0x56,
            slot="B0",
            label="Antonio",
            map_x=100,
            world_x=100,
            combat_phase=CombatPhase.CHARGE,
        )
        decision = decide_actions(
            _snapshot((me, antonio)),
            AgentConfig(p1_enabled=True, police_threshold=99.0),
            AgentState(),
        )
        self.assertTrue(decision.p1_mask & 0x04, decision.p1_note)
        self.assertFalse(decision.p1_mask & 0x08, decision.p1_note)
        self.assertIn("Antonio", decision.p1_note)

    def test_off_lane_antonio_charge_is_reengaged_not_guarded_forever(self) -> None:
        me = _player(x=150, y=92)
        antonio = _entity(
            kind="boss",
            family="Antonio",
            type_id=0x56,
            slot="B0",
            label="Antonio",
            map_x=83,
            world_x=83,
            map_y=19,
            world_y=19,
            combat_phase=CombatPhase.CHARGE,
        )
        decision = decide_actions(
            _snapshot((me, antonio)),
            AgentConfig(p1_enabled=True, police_threshold=99.0),
            AgentState(),
        )
        self.assertTrue(decision.p1_mask & 0x01, decision.p1_note)
        self.assertNotEqual(decision.p1_mask, 0, decision.p1_note)
        self.assertIn("reengage boss Antonio", decision.p1_note)

    def test_active_enemy_forbids_weapon_detour(self) -> None:
        me = _player()
        enemy = _entity(
            slot="E0",
            map_x=165,
            world_x=165,
            target_ptr=0xB800,
            combat_phase=CombatPhase.ATTACKING,
        )
        weapon = _entity(
            kind="weapon",
            family="Weapon",
            type_id=0x0B,
            slot="W0",
            label="Pipe",
            map_x=110,
            world_x=110,
            health=None,
            combat_phase=CombatPhase.UNKNOWN,
        )
        decision = decide_actions(
            _snapshot((me, enemy, weapon)),
            AgentConfig(p1_enabled=True, police_threshold=99.0),
            AgentState(),
        )
        self.assertNotIn("loot", decision.p1_note)


class GrabExecutionTests(unittest.TestCase):
    def test_reciprocal_enemy_link_overrides_stale_weapon_type(self) -> None:
        me, held, _rear = _grab_scene()
        me = replace(me, held_type=0x09, held_ptr=0xCD00)
        context = context_from_player(me, (me, held))
        self.assertTrue(context.enemy_grab)
        self.assertFalse(context.weapon)
        intent = decide_held(
            me,
            context,
            GrabMemory(),
            tick=0,
            foe=held,
            profile=PROFILES[0],
        )
        assert intent is not None
        self.assertTrue(intent.attack)
        self.assertNotIn("weapon anim", intent.note)

    def test_animation_state_suppresses_repeated_attack_edges(self) -> None:
        me = replace(_player(action=0x6A), held_type=0x20)
        intent = decide_held(
            me,
            context_from_player(me),
            GrabMemory(),
            tick=0,
            profile=PROFILES[0],
        )
        assert intent is not None
        self.assertFalse(intent.attack)
        self.assertIn("grab anim", intent.note)

    def test_animation_lock_survives_cleared_hold_evidence(self) -> None:
        me = _player(action=0x6C)
        intent = decide_actions(
            _snapshot((me,)),
            AgentConfig(p1_enabled=True, police_threshold=99.0),
            AgentState(),
        )
        self.assertFalse(intent.p1_mask & 0x20)
        self.assertIn("grab anim", intent.p1_note)

    def test_animation_lock_beats_stale_weapon_and_dangerous_target(self) -> None:
        me = replace(_player(action=0x6A), held_type=0x08)
        dangerous = _entity(
            slot="E0",
            map_x=130,
            world_x=130,
            combat_phase=CombatPhase.ATTACKING,
        )
        intent = decide_held(
            me,
            context_from_player(me, (me, dangerous)),
            GrabMemory(),
            tick=0,
            foe=dangerous,
            profile=PROFILES[0],
        )
        assert intent is not None
        self.assertFalse(intent.attack)
        self.assertIn("anim", intent.note)

    def test_orphan_front_hold_is_resolved_without_contact_pointer(self) -> None:
        me = _player(action=0x60)
        intent = decide_held(
            me,
            context_from_player(me),
            GrabMemory(),
            tick=0,
            profile=PROFILES[0],
        )
        assert intent is not None
        self.assertTrue(intent.attack)
        self.assertIn("resolve orphan", intent.note)

    def test_rejected_crossover_retries_then_falls_back_to_strike(self) -> None:
        me, held, rear = _grab_scene()
        entities = (me, held, rear)
        assessment = DEFAULT_COMBAT_EXPERT.assess(me, entities, held_enemy=held)
        planner = AutoPlanner()
        ctx = context_from_player(me, entities)
        intents = [planner.decide(assessment, me, ctx, held) for _ in range(5)]
        assert all(intent is not None for intent in intents)
        self.assertTrue(intents[0].jump)
        self.assertTrue(intents[2].jump)
        self.assertTrue(intents[4].attack)
        self.assertIn("fallback strike", intents[4].note)


if __name__ == "__main__":
    unittest.main()
