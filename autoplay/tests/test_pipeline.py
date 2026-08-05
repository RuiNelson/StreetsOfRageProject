"""Mode classifier, DecisionContext, and commitment skill pipeline."""

from __future__ import annotations

import unittest
from dataclasses import replace

from sor_autoplay.agent.context import (
    PlayerMode,
    SeatMemory,
    build_decision_context,
    classify_mode,
)
from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
from sor_autoplay.phases import CombatPhase

from tests.test_expert_planner import _entity, _grab_scene, _snapshot


class ModeClassifierTests(unittest.TestCase):
    def test_exclusive_modes_from_rom_state(self) -> None:
        me = _entity(kind="player", slot="P1", symbol="1", action_state=0x02)
        # Minimal stand-in: only fields classify_mode reads from player_snap.
        class _Snap:
            is_playable = True
            is_continue_ui = False

        snap = _Snap()
        self.assertEqual(
            classify_mode(me=me, player_snap=snap, is_mr_x=True),  # type: ignore[arg-type]
            PlayerMode.DIALOG,
        )

        class _ContinueSnap:
            is_playable = False
            is_continue_ui = True

        self.assertEqual(
            classify_mode(me=None, player_snap=_ContinueSnap(), is_mr_x=False),  # type: ignore[arg-type]
            PlayerMode.CONTINUE_UI,
        )
        self.assertEqual(
            classify_mode(me=None, player_snap=snap, is_mr_x=False),  # type: ignore[arg-type]
            PlayerMode.NOT_PLAYABLE,
        )
        held = replace(me, action_state=0x7A)
        self.assertEqual(
            classify_mode(me=held, player_snap=snap, is_mr_x=False),  # type: ignore[arg-type]
            PlayerMode.ENEMY_HELD,
        )
        hurt = replace(me, action_state=0x50)
        self.assertEqual(
            classify_mode(me=hurt, player_snap=snap, is_mr_x=False),  # type: ignore[arg-type]
            PlayerMode.HURT,
        )
        # Ordinary enemy throw air $72 is locked (not FREE combat).
        thrown = replace(me, action_state=0x72)
        self.assertEqual(
            classify_mode(me=thrown, player_snap=snap, is_mr_x=False),  # type: ignore[arg-type]
            PlayerMode.HURT,
        )
        # Special-throw choreography $84 likewise.
        choreo = replace(me, action_state=0x84)
        self.assertEqual(
            classify_mode(me=choreo, player_snap=snap, is_mr_x=False),  # type: ignore[arg-type]
            PlayerMode.HURT,
        )
        anim = replace(me, action_state=0x68)
        self.assertEqual(
            classify_mode(me=anim, player_snap=snap, is_mr_x=False),  # type: ignore[arg-type]
            PlayerMode.GRAB_ANIM,
        )
        air = replace(me, action_state=0x12)
        self.assertEqual(
            classify_mode(me=air, player_snap=snap, is_mr_x=False),  # type: ignore[arg-type]
            PlayerMode.AIRBORNE,
        )
        free = replace(me, action_state=0x02)
        self.assertEqual(
            classify_mode(me=free, player_snap=snap, is_mr_x=False),  # type: ignore[arg-type]
            PlayerMode.FREE,
        )


class ThrowLandTechTests(unittest.TestCase):
    def test_c_up_when_tech_armed_in_throw_air(self) -> None:
        """Special throw +$45: emit logical C+Up (mask UP|C) during $5C/$72/$88."""

        p1 = _entity(
            kind="player",
            family="Player",
            symbol="1",
            label="P1",
            slot="P1",
            type_id=1,
            action_state=0x5C,
            combat_phase=CombatPhase.HURT_PLAYER,
            tech_armed=1,
        )
        memory = AgentState()
        config = AgentConfig(p1_enabled=True)
        decision = decide_actions(_snapshot((p1,)), config, memory)
        # Buttons: UP=1, C=JUMP=0x40 in megadrive_remote IntFlag layout used by mask.
        self.assertTrue(decision.p1_mask & 0x01, decision.p1_note)  # Up
        self.assertTrue(decision.p1_mask & 0x40, decision.p1_note)  # C
        self.assertIn("throw land tech", decision.p1_note)

    def test_no_tech_on_ordinary_throw_without_arm(self) -> None:
        p1 = _entity(
            kind="player",
            family="Player",
            symbol="1",
            label="P1",
            slot="P1",
            type_id=1,
            action_state=0x72,
            combat_phase=CombatPhase.HURT_PLAYER,
            tech_armed=0,
        )
        decision = decide_actions(
            _snapshot((p1,)),
            AgentConfig(p1_enabled=True),
            AgentState(),
        )
        self.assertEqual(decision.p1_mask, 0, decision.p1_note)
        self.assertIn("hurt", decision.p1_note)

    def test_tech_retry_holds_up_without_repeating_c_edge(self) -> None:
        p1 = _entity(
            kind="player",
            family="Player",
            symbol="1",
            label="P1",
            slot="P1",
            type_id=1,
            action_state=0x5C,
            combat_phase=CombatPhase.HURT_PLAYER,
            tech_armed=1,
        )
        memory = AgentState()
        config = AgentConfig(p1_enabled=True)
        first = decide_actions(_snapshot((p1,)), config, memory)
        self.assertTrue(first.p1_mask & 0x40)
        second = decide_actions(_snapshot((p1,)), config, memory)
        self.assertTrue(second.p1_mask & 0x01, second.p1_note)
        self.assertEqual(second.p1_mask & 0x40, 0, second.p1_note)
        self.assertIn("await", second.p1_note)


class CommitmentTests(unittest.TestCase):
    def test_continue_does_not_reset_escape_latch(self) -> None:
        """Restarting the skill every tick used to clear the retry window."""

        p1 = _entity(
            kind="player",
            family="Player",
            symbol="1",
            label="P1",
            slot="P1",
            type_id=1,
            action_state=0x7A,
            combat_phase=CombatPhase.NORMAL,
        )
        memory = AgentState()
        config = AgentConfig(p1_enabled=True)
        jump = decide_actions(_snapshot((p1,)), config, memory)
        self.assertEqual(jump.p1_mask & 0x60, 0x40)
        self.assertEqual(memory.seat(1).commitment.name, "enemy_grab_escape")
        retry = decide_actions(_snapshot((p1,)), config, memory)
        self.assertEqual(retry.p1_mask, 0)
        self.assertIn("await", retry.p1_note)

    def test_crossover_skill_owns_exposed_back_hold(self) -> None:
        me, held, rear = _grab_scene()
        memory = AgentState()
        decision = decide_actions(
            _snapshot((me, held, rear)),
            AgentConfig(p1_enabled=True),
            memory,
        )
        self.assertTrue(decision.p1_mask & 0x40, decision.p1_note)
        self.assertIn("crossover", decision.p1_note)
        self.assertEqual(memory.seat(1).commitment.name, "crossover_suplex")

    def test_seat_memory_aliases(self) -> None:
        memory = AgentState()
        me = _entity(
            kind="player",
            slot="P1",
            symbol="1",
            world_x=10,
            world_y=10,
            map_x=10,
            map_y=10,
        )
        memory.p1_walk.set_goal(me, 100.0, 64.0, reason="test")
        self.assertTrue(memory.p1_walk.active)
        self.assertIs(memory.walk(1), memory.p1.walk)
        memory.clear_tactical()
        self.assertFalse(memory.p1_walk.active)
        self.assertFalse(memory.seat(1).commitment.active)


class DecisionContextTests(unittest.TestCase):
    def test_build_context_classifies_and_perceives(self) -> None:
        me = _entity(
            kind="player",
            family="Player",
            symbol="1",
            label="P1",
            slot="P1",
            type_id=1,
            action_state=0x02,
            combat_phase=CombatPhase.NORMAL,
        )
        foe = _entity(slot="E0", map_x=140, world_x=140, map_y=64, world_y=64)
        snap = _snapshot((me, foe))
        seat = SeatMemory()
        ctx = build_decision_context(
            snap,
            player_index=1,
            player_snap=snap.p1,
            both_agents=False,
            police_threshold=4.5,
            tick=1,
            seat=seat,
            me=me,
            partner=None,
            partner_snap=None,
            is_mr_x=False,
        )
        self.assertEqual(ctx.mode, PlayerMode.FREE)
        ctx.ensure_perception()
        self.assertIsNotNone(ctx.graph)
        self.assertIsNotNone(ctx.press)


if __name__ == "__main__":
    unittest.main()
