"""Fuzzy inference, knowledge graph, and tactical solver regressions."""

from __future__ import annotations

import unittest
from dataclasses import replace

from sor_autoplay.agent.arbiter import GoalKind, GoalMemory, solve_goal
from sor_autoplay.agent.autoplanner import AutoPlanner
from sor_autoplay.agent.characters import PROFILES
from sor_autoplay.agent.combat import select_pickup, select_target
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
    def test_held_weapons_are_not_collectible(self) -> None:
        me = _player()
        free = _entity(
            kind="weapon",
            family="Weapon",
            label="bat",
            slot="W0",
            type_id=0x0A,
            map_x=120,
            world_x=120,
            map_y=64,
            world_y=64,
            interaction=0,
            item_param=0,
        )
        held = replace(free, slot="W1", interaction=1)
        worn = replace(free, slot="W2", item_param=3)
        graph = build_tactical_graph(
            me, (me, free, held, worn), level_index=0, player_index=1
        )
        self.assertTrue(graph.entity_has(free, Relation.COLLECTIBLE))
        self.assertFalse(graph.entity_has(held, Relation.COLLECTIBLE))
        self.assertFalse(graph.entity_has(worn, Relation.COLLECTIBLE))

    def test_off_camera_pickups_are_not_collectible(self) -> None:
        """Loot only inside walk-band camera ± pickup reach (not CRT / view ring)."""

        me = _player(x=160)
        on_camera = _entity(
            kind="pickup",
            family="Score",
            type_id=0x3F,
            slot="I0",
            label="On",
            map_x=200,
            world_x=200,
            map_y=64,
            world_y=64,
            health=None,
            combat_phase=CombatPhase.UNKNOWN,
            interaction=0,
        )
        # CRT letterbox left of the walk clamp: player min map_x=32, pickup ±16
        # cannot reach map_x=5 without scrolling the camera left.
        stranded_left = replace(on_camera, slot="I1", label="Left", map_x=5, world_x=5)
        # Past walk+pickup on the right (and often still dimmed on the HUD).
        stranded_right = replace(
            on_camera, slot="I2", label="Right", map_x=320, world_x=320
        )
        # Diagnostic view ring — well outside the CRT.
        off_view = replace(on_camera, slot="I3", label="Far", map_x=400, world_x=400)
        # Just inside walk edge + pickup reach: still legal from map_x=288.
        edge_ok = replace(on_camera, slot="I4", label="Edge", map_x=300, world_x=300)
        graph = build_tactical_graph(
            me,
            (me, on_camera, stranded_left, stranded_right, off_view, edge_ok),
            level_index=0,
            player_index=1,
        )
        self.assertTrue(graph.entity_has(on_camera, Relation.COLLECTIBLE))
        self.assertTrue(graph.entity_has(edge_ok, Relation.COLLECTIBLE))
        self.assertFalse(graph.entity_has(stranded_left, Relation.COLLECTIBLE))
        self.assertFalse(graph.entity_has(stranded_right, Relation.COLLECTIBLE))
        self.assertFalse(graph.entity_has(off_view, Relation.COLLECTIBLE))
        self.assertIs(
            select_pickup(
                me,
                (on_camera, stranded_left, stranded_right, off_view, edge_ok),
                allow_health=True,
                allow_special_life=True,
                graph=graph,
            ),
            on_camera,
        )

    def test_jack_affordances_follow_weapon_latch_and_throw_state(self) -> None:
        me = _player()
        armed = _entity(
            slot="E0",
            family="Jack",
            type_id=0x27,
            primary_state=0x0C00,
            family_state=0x01,
        )
        throwing = _entity(
            slot="E1",
            family="Jack",
            type_id=0x27,
            primary_state=0x0E00,
            family_state=0x01,
        )
        graph = build_tactical_graph(
            me, (me, armed, throwing), level_index=0, player_index=1
        )
        self.assertTrue(graph.entity_has(armed, Relation.ARMED))
        # Armed Jack keeps weapons attached: punches still land, grabs do not.
        self.assertFalse(graph.entity_has(armed, Relation.GRABBABLE))
        self.assertTrue(graph.entity_has(throwing, Relation.THROWING))
        self.assertTrue(graph.entity_has(throwing, Relation.GRABBABLE))
        unarmed = _entity(
            slot="E2",
            family="Jack",
            type_id=0x27,
            primary_state=0x0100,
            family_state=0,
        )
        graph2 = build_tactical_graph(
            me, (me, unarmed), level_index=0, player_index=1
        )
        self.assertTrue(graph2.entity_has(unarmed, Relation.GRABBABLE))

    def test_jack_attached_helpers_are_not_dangerous_until_launched(self) -> None:
        me = _player()
        attached = _entity(
            kind="projectile",
            family="Jack",
            label="attached axe",
            slot="H0",
            type_id=0x28,
            health=None,
            primary_state=0x0101,
        )
        launched = replace(attached, slot="H1", primary_state=0x0300)
        graph = build_tactical_graph(
            me, (me, attached, launched), level_index=0, player_index=1
        )
        self.assertTrue(graph.entity_has(attached, Relation.ATTACHED))
        self.assertFalse(graph.entity_has(attached, Relation.DANGEROUS))
        self.assertFalse(graph.entity_has(attached, Relation.LAUNCHED))
        self.assertTrue(graph.entity_has(launched, Relation.LAUNCHED))
        self.assertTrue(graph.entity_has(launched, Relation.DANGEROUS))

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

    def test_signed_negative_corpse_is_a_hard_defeated_graph_node(self) -> None:
        me = _player()
        corpse = _entity(
            slot="E0",
            map_x=130,
            world_x=130,
            health=0xFFFF,
            primary_state=0x0B00,
            combat_phase=CombatPhase.ATTACKING,
        )
        graph = build_tactical_graph(
            me, (me, corpse), level_index=0, player_index=1
        )
        self.assertTrue(graph.entity_has(corpse, Relation.DEFEATED))
        self.assertFalse(graph.entity_has(corpse, Relation.REACHABLE))
        self.assertFalse(graph.entity_has(corpse, Relation.DANGEROUS))
        self.assertFalse(graph.entity_has(corpse, Relation.PUNISHABLE))
        self.assertFalse(graph.entity_has(corpse, Relation.BLOCKS_PROGRESS))

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

    def test_family_priority_order_at_equal_geometry(self) -> None:
        me = _player()
        ordered = (
            _entity(
                kind="boss",
                family="Antonio",
                type_id=0x56,
                slot="B0",
                label="Boss",
                map_x=150,
            ),
            _entity(family="Jack", type_id=0x27, slot="E1", label="Jack", map_x=150),
            _entity(family="Nora", type_id=0x26, slot="E2", label="Nora", map_x=150),
            _entity(family="Signal", type_id=0x24, slot="E3", label="Signal", map_x=150),
            _entity(family="Haku-Ro", type_id=0x25, slot="E4", label="Ninja", map_x=150),
            _entity(family="Garcia", type_id=0x22, slot="E5", label="Garcia", map_x=150),
        )
        for higher, lower in zip(ordered, ordered[1:]):
            with self.subTest(higher=higher.label, lower=lower.label):
                choice = select_target(me, (lower, higher), PROFILES[0])
                assert choice is not None
                self.assertEqual(choice.entity.slot, higher.slot)

    def test_position_can_outweigh_ordinary_family_priority(self) -> None:
        me = _player()
        distant_jack = _entity(
            family="Jack",
            type_id=0x27,
            slot="E0",
            label="Distant Jack",
            map_x=290,
            map_y=108,
        )
        immediate_garcia = _entity(
            family="Garcia",
            type_id=0x22,
            slot="E1",
            label="Immediate Garcia",
            map_x=125,
            map_y=64,
        )
        choice = select_target(me, (distant_jack, immediate_garcia), PROFILES[0])
        assert choice is not None
        self.assertEqual(choice.entity.label, "Immediate Garcia")


class WeaponUpgradeTests(unittest.TestCase):
    def test_held_bottle_can_be_replaced_by_pipe(self) -> None:
        me = replace(_player(action=0x32), held_type=0x09, held_ptr=0xBA00)
        pipe = _entity(
            kind="weapon",
            family="Weapon",
            type_id=0x0B,
            slot="W0",
            label="Steel pipe",
            map_x=112,
            health=None,
            combat_phase=CombatPhase.UNKNOWN,
        )
        graph = build_tactical_graph(
            me, (me, pipe), level_index=0, player_index=1
        )
        choice = select_pickup(
            me,
            (pipe,),
            allow_health=True,
            allow_special_life=True,
            already_holding_weapon=True,
            held_weapon_type=me.held_type,
            profile=PROFILES[0],
            graph=graph,
        )
        self.assertEqual(choice, pipe)

    def test_held_pipe_is_not_replaced_by_weaker_bottle(self) -> None:
        me = replace(_player(action=0x32), held_type=0x0B, held_ptr=0xBA00)
        bottle = _entity(
            kind="weapon",
            family="Weapon",
            type_id=0x09,
            slot="W0",
            label="Bottle",
            map_x=112,
            health=None,
            combat_phase=CombatPhase.UNKNOWN,
        )
        graph = build_tactical_graph(
            me, (me, bottle), level_index=0, player_index=1
        )
        self.assertIsNone(
            select_pickup(
                me,
                (bottle,),
                allow_health=True,
                allow_special_life=True,
                already_holding_weapon=True,
                held_weapon_type=me.held_type,
                profile=PROFILES[0],
                graph=graph,
            )
        )


class EnemyGrabEscapeTests(unittest.TestCase):
    def test_policy_executes_rom_guarded_c_then_b_counter(self) -> None:
        memory = AgentState()
        config = AgentConfig(p1_enabled=True)
        held = replace(
            _player(action=0x7A),
            combat_phase=CombatPhase.HELD_BY_ENEMY,
        )

        acquiring = replace(held, action_state=0x78)
        acquire_wait = decide_actions(_snapshot((acquiring,)), config, memory)
        self.assertEqual(acquire_wait.p1_mask, 0)
        self.assertIn("enemy grab acquire", acquire_wait.p1_note)

        jump = decide_actions(_snapshot((held,)), config, memory)
        self.assertEqual(jump.p1_mask & 0x60, 0x40)
        self.assertIn("escape enemy grab crossover", jump.p1_note)

        retry_guard = decide_actions(_snapshot((held,)), config, memory)
        self.assertEqual(retry_guard.p1_mask, 0)
        self.assertIn("await enemy grab jump", retry_guard.p1_note)

        crossover = replace(held, action_state=0x7C)
        crossing = decide_actions(_snapshot((crossover,)), config, memory)
        self.assertEqual(crossing.p1_mask, 0)
        self.assertIn("enemy grab crossover", crossing.p1_note)

        counter_window = replace(held, action_flags=0x80)
        throw = decide_actions(_snapshot((counter_window,)), config, memory)
        self.assertEqual(throw.p1_mask & 0x60, 0x20)
        self.assertIn("escape enemy grab counter throw", throw.p1_note)

        throwing = replace(held, action_state=0x7E, action_flags=0)
        wait = decide_actions(_snapshot((throwing,)), config, memory)
        self.assertEqual(wait.p1_mask, 0)
        self.assertIn("enemy grab counter throw", wait.p1_note)

    def test_policy_progresses_past_signed_negative_floor_corpse(self) -> None:
        me = _player()
        corpse = _entity(
            slot="E0",
            map_x=130,
            world_x=130,
            health=0xFFFF,
            primary_state=0x0300,
            combat_phase=CombatPhase.KNOCKDOWN,
        )
        decision = decide_actions(
            _snapshot((me, corpse)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertEqual(decision.p1_mask & 0x60, 0)
        self.assertTrue(decision.p1_mask & 0x08, decision.p1_note)
        self.assertIn("progress", decision.p1_note)


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
    def test_does_not_loot_off_camera_collectable(self) -> None:
        me = _player(x=200)
        # Dim / off-camera on the HUD map ring and outside loot camera.
        off = _entity(
            kind="pickup",
            family="Score",
            type_id=0x3F,
            slot="I0",
            label="Score",
            map_x=360,
            world_x=360,
            map_y=64,
            world_y=64,
            world_z=160,
            health=None,
            combat_phase=CombatPhase.UNKNOWN,
            interaction=0,
        )
        decision = decide_actions(
            _snapshot((me, off)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertNotIn("loot", decision.p1_note)
        self.assertNotIn("Score", decision.p1_note)

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
            AgentConfig(p1_enabled=True, police_threshold=99.0),
            AgentState(),
        )
        self.assertIn("Antonio", decision.p1_note)
        self.assertNotIn("loot", decision.p1_note)
        self.assertNotIn("progress", decision.p1_note)

    def test_reachable_boss_triggers_special_before_approach(self) -> None:
        me = _player(x=288, y=37)
        antonio = _entity(
            kind="boss",
            family="Antonio",
            type_id=0x56,
            slot="B0",
            label="Antonio",
            map_x=328,
            world_x=3848,
            map_y=100,
            world_y=100,
        )
        decision = decide_actions(
            _snapshot((me, antonio)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertTrue(decision.p1_mask & 0x10, decision.p1_note)
        self.assertIn("boss-immediate", decision.p1_note)

    def test_policy_walks_to_a_better_weapon_while_already_armed(self) -> None:
        me = replace(_player(action=0x32), held_type=0x09, held_ptr=0xBA00)
        pipe = _entity(
            kind="weapon",
            family="Weapon",
            type_id=0x0B,
            slot="W0",
            label="Steel pipe",
            map_x=140,
            health=None,
            combat_phase=CombatPhase.UNKNOWN,
        )
        decision = decide_actions(
            _snapshot((me, pipe)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertIn("upgrade weapon Steel pipe", decision.p1_note)

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

    def test_nearby_antonio_charge_retreats_instead_of_closing_in(self) -> None:
        """Live measurement (round1-start, axel, rng 711800410): Antonio dashes
        in on both axes (dx=36, dy=30) and connects, locking the player into
        the $50-$5F/$70-$74 hurt/throw-recovery chain for ~15 decisions. The
        off-lane "reengage boss" fixed-point fix (dy=73, far off-lane) must
        not also march the player into a boss that is already closing in."""

        me = _player(x=150, y=54)
        antonio = _entity(
            kind="boss",
            family="Antonio",
            type_id=0x56,
            slot="B0",
            label="Antonio",
            map_x=186,
            world_x=186,
            map_y=24,
            world_y=24,
            combat_phase=CombatPhase.CHARGE,
        )
        decision = decide_actions(
            _snapshot((me, antonio)),
            AgentConfig(p1_enabled=True, police_threshold=99.0),
            AgentState(),
        )
        self.assertNotIn("reengage boss Antonio", decision.p1_note)

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
