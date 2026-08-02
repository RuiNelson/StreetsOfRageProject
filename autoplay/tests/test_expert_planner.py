"""Expert inference and persistent multi-step combat plan tests."""

from __future__ import annotations

import unittest
from dataclasses import replace
from enum import Enum, auto

from sor_autoplay.agent.autoplanner import AutoPlanner, PlanPhase
from sor_autoplay.agent.expert import (
    DEFAULT_COMBAT_EXPERT,
    TacticalFact,
    TacticalGoal,
)
from sor_autoplay.agent.grabs import context_from_player
from sor_autoplay.agent.inference import InferenceEngine, Rule
from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
from sor_autoplay.memory_map import (
    MAX_HEALTH,
    OBJ_CHARACTER_ID,
    OBJ_HEALTH,
    OBJ_POS_X,
    OBJ_POS_Y,
    OBJ_TYPE,
)
from sor_autoplay.phases import CombatPhase
from sor_autoplay.state import snapshot_from_memory_blocks
from sor_autoplay.world_map import MapEntity, WorldMap


def _entity(**kwargs: object) -> MapEntity:
    values: dict[str, object] = {
        "kind": "enemy",
        "family": "Garcia",
        "symbol": "G",
        "color": "#fff",
        "label": "Garcia",
        "type_id": 0x22,
        "world_x": 100,
        "world_y": 64,
        "world_z": 160,
        "map_x": 100.0,
        "map_y": 64.0,
        "health": 4,
        "slot": "E0",
        "action_state": 0x01,
        "primary_state": 0x0100,
        "combat_phase": CombatPhase.NORMAL,
    }
    values.update(kwargs)
    if "map_x" in kwargs and "world_x" not in kwargs:
        values["world_x"] = int(kwargs["map_x"])  # type: ignore[arg-type]
    if "map_y" in kwargs and "world_y" not in kwargs:
        values["world_y"] = int(kwargs["map_y"])  # type: ignore[arg-type]
    return MapEntity(**values)  # type: ignore[arg-type]


def _grab_scene(action: int = 0x60) -> tuple[MapEntity, MapEntity, MapEntity]:
    me = _entity(
        kind="player",
        family="Player",
        symbol="1",
        label="P1",
        type_id=1,
        slot="P1",
        action_state=action,
        primary_state=action << 8,
        map_x=100,
        world_x=100,
        contact_ptr=0xB900,
        combat_phase=CombatPhase.HOLDING,
    )
    held = _entity(
        label="Held Garcia",
        slot="E0",
        map_x=132,
        world_x=132,
        primary_state=0x0500,
        combat_phase=CombatPhase.GRABBED,
        attacker_ptr=0xB800,
        target_ptr=0xB800,
    )
    rear = _entity(label="Backstab", slot="E1", map_x=70, world_x=70)
    return me, held, rear


def _snapshot(entities: tuple[MapEntity, ...]):
    def put_u8(blob: bytearray, offset: int, value: int) -> None:
        blob[offset] = value & 0xFF

    def put_u16(blob: bytearray, offset: int, value: int) -> None:
        blob[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")

    globals_block = bytearray(0x40)
    timer_block = bytearray(4)
    player_block = bytearray(0x100)
    put_u16(globals_block, 0x00, 0x0016)
    put_u8(globals_block, 0x18, 0x01)
    put_u8(globals_block, 0x1E, 0x00)
    put_u8(globals_block, 0x20, 0x03)
    put_u8(globals_block, 0x21, 0x01)
    put_u16(timer_block, 0, 0x0040)
    put_u8(player_block, OBJ_TYPE, 0x01)
    put_u16(player_block, OBJ_HEALTH, MAX_HEALTH)
    put_u8(player_block, OBJ_CHARACTER_ID, 0x00)
    put_u16(player_block, OBJ_POS_X, 100)
    put_u16(player_block, OBJ_POS_Y, 64)
    snapshot = snapshot_from_memory_blocks(
        globals_block=bytes(globals_block),
        timer_block=bytes(timer_block),
        objects_block=bytes(player_block),
    )
    world = WorldMap(
        camera_x=0,
        camera_y=0,
        camera_left=0.0,
        camera_right=320.0,
        camera_top=0.0,
        camera_bottom=112.0,
        view_left=-40.0,
        view_right=360.0,
        view_top=-16.0,
        view_bottom=128.0,
        entities=entities,
    )
    return replace(snapshot, world_map=world)


class InferenceEngineTests(unittest.TestCase):
    def test_forward_chains_to_fixed_point_with_trace(self) -> None:
        class Fact(Enum):
            A = auto()
            B = auto()
            C = auto()

        engine = InferenceEngine(
            (
                Rule("a-to-b", frozenset({Fact.B}), frozenset({Fact.A})),
                Rule("b-to-c", frozenset({Fact.C}), frozenset({Fact.B})),
            )
        )
        result = engine.infer({Fact.A})
        self.assertEqual(result.facts, frozenset({Fact.A, Fact.B, Fact.C}))
        self.assertEqual(result.fired_rules, ("a-to-b", "b-to-c"))


class CombatExpertTests(unittest.TestCase):
    def test_infers_crossover_when_front_hold_exposes_back(self) -> None:
        me, held, rear = _grab_scene()
        assessment = DEFAULT_COMBAT_EXPERT.assess(
            me, (me, held, rear), held_enemy=held
        )
        self.assertEqual(assessment.goal, TacticalGoal.CROSSOVER_SUPLEX)
        self.assertIn(TacticalFact.BACK_EXPOSED, assessment.facts)
        self.assertIn("protect-back-with-crossover", assessment.fired_rules)
        self.assertEqual(assessment.rear_threat_slot, "E1")

    def test_front_threat_does_not_falsely_expose_back(self) -> None:
        me, held, _ = _grab_scene()
        front = _entity(label="Front", slot="E1", map_x=170, world_x=170)
        assessment = DEFAULT_COMBAT_EXPERT.assess(
            me, (me, held, front), held_enemy=held
        )
        self.assertEqual(assessment.goal, TacticalGoal.NONE)
        self.assertNotIn(TacticalFact.BACK_EXPOSED, assessment.facts)

    def test_existing_back_hold_is_a_direct_suplex_goal(self) -> None:
        me, held, rear = _grab_scene(action=0x67)
        assessment = DEFAULT_COMBAT_EXPERT.assess(
            me, (me, held, rear), held_enemy=held
        )
        self.assertEqual(assessment.goal, TacticalGoal.SUPLEX)

    def test_crowd_pressure_triggers_crossover_suplex(self) -> None:
        """AISpec §1.4.2 / §4.2: multi-enemy holds vault for a throw launch."""

        me, held, _ = _grab_scene()
        front = _entity(label="Front", slot="E1", map_x=170, world_x=170)
        alone = DEFAULT_COMBAT_EXPERT.assess(
            me, (me, held, front), held_enemy=held, crowd=1
        )
        self.assertEqual(alone.goal, TacticalGoal.NONE)
        crowded = DEFAULT_COMBAT_EXPERT.assess(
            me, (me, held, front), held_enemy=held, crowd=2
        )
        self.assertEqual(crowded.goal, TacticalGoal.CROSSOVER_SUPLEX)
        self.assertIn(TacticalFact.CROWD_PRESSURE, crowded.facts)
        self.assertIn("crowd-suplex-setup", crowded.fired_rules)


class AutoPlannerTests(unittest.TestCase):
    def test_rom_guarded_crossover_then_one_suplex_edge(self) -> None:
        me, held, rear = _grab_scene()
        entities = (me, held, rear)
        assessment = DEFAULT_COMBAT_EXPERT.assess(me, entities, held_enemy=held)
        planner = AutoPlanner()

        start = planner.decide(
            assessment, me, context_from_player(me, entities), held
        )
        assert start is not None
        self.assertTrue(start.jump)
        self.assertFalse(start.attack)
        self.assertEqual(planner.phase, PlanPhase.WAIT_CROSSOVER)

        vault_me = replace(me, action_state=0x76)
        vault_entities = (vault_me, held, rear)
        vault = planner.decide(
            DEFAULT_COMBAT_EXPERT.assess(
                vault_me, vault_entities, held_enemy=held
            ),
            vault_me,
            context_from_player(vault_me, vault_entities),
            held,
        )
        assert vault is not None
        self.assertFalse(vault.jump or vault.attack)

        back_me = replace(me, action_state=0x67)
        back_entities = (back_me, held, rear)
        suplex = planner.decide(
            DEFAULT_COMBAT_EXPERT.assess(
                back_me, back_entities, held_enemy=held
            ),
            back_me,
            context_from_player(back_me, back_entities),
            held,
        )
        assert suplex is not None
        self.assertTrue(suplex.attack)
        self.assertFalse(suplex.jump)

        # The enemy links can clear as soon as the ROM accepts B; the plan must
        # still own the active throw animation and suppress extra input.
        active_me = replace(me, action_state=0x69, contact_ptr=0)
        active_entities = (active_me, rear)
        finish = planner.decide(
            DEFAULT_COMBAT_EXPERT.assess(
                active_me, active_entities, held_enemy=None
            ),
            active_me,
            context_from_player(active_me, active_entities),
            None,
        )
        assert finish is not None
        self.assertFalse(finish.attack or finish.jump)
        self.assertIn("suplex active", finish.note)

        grounded_me = replace(active_me, action_state=0x02)
        grounded_entities = (grounded_me, rear)
        completed = planner.decide(
            DEFAULT_COMBAT_EXPERT.assess(
                grounded_me, grounded_entities, held_enemy=None
            ),
            grounded_me,
            context_from_player(grounded_me, grounded_entities),
            None,
        )
        self.assertIsNone(completed)
        self.assertFalse(planner.active)

    def test_policy_keeps_plan_across_rom_action_states(self) -> None:
        me, held, rear = _grab_scene()
        memory = AgentState()
        config = AgentConfig(p1_enabled=True, police_threshold=99.0)

        start = decide_actions(_snapshot((me, held, rear)), config, memory)
        self.assertEqual(start.p1_mask & 0x60, 0x40, start.p1_note)
        self.assertIn("plan crossover", start.p1_note)

        vault_me = replace(me, action_state=0x76)
        vault = decide_actions(
            _snapshot((vault_me, held, rear)), config, memory
        )
        self.assertEqual(vault.p1_mask & 0x60, 0, vault.p1_note)
        self.assertIn("plan vault", vault.p1_note)

        back_me = replace(me, action_state=0x67)
        suplex = decide_actions(
            _snapshot((back_me, held, rear)), config, memory
        )
        self.assertEqual(suplex.p1_mask & 0x60, 0x20, suplex.p1_note)
        self.assertIn("plan suplex", suplex.p1_note)

        active_me = replace(me, action_state=0x69, contact_ptr=0)
        finish = decide_actions(
            _snapshot((active_me, rear)), config, memory
        )
        self.assertEqual(finish.p1_mask & 0x60, 0, finish.p1_note)
        self.assertIn("suplex active", finish.p1_note)


if __name__ == "__main__":
    unittest.main()
