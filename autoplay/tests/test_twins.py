"""Onihime/Yasha ROM-backed counter AI and focus-fire."""

from __future__ import annotations

import unittest

from sor_autoplay.agent.combat import select_target
from sor_autoplay.agent.characters import PROFILES
from sor_autoplay.agent.enemies import plan_for
from sor_autoplay.agent.twins import (
    TwinComposition,
    TwinFocusMemory,
    TwinRoutine,
    decode_routine,
    in_jump_arm_range,
    plan_for_twin,
    tactical_move,
    twin_composition,
    twin_focus_bonus,
    update_focus,
)
from sor_autoplay.phases import CombatPhase
from sor_autoplay.world_map import MapEntity


def _twin(
    *,
    slot: str,
    world_x: int,
    world_y: int = 64,
    pair_role: int = 1,
    action_state: int = 0x01,
    tactical: int = 0,
    health: int = 0x20,
    phase: CombatPhase = CombatPhase.NORMAL,
    boss_dist_x: int = 0,
    boss_dist_lane: int = 0,
) -> MapEntity:
    return MapEntity(
        kind="boss",
        family="Onihime/Yasha",
        symbol="B",
        color="#ff375f",
        label=slot,
        type_id=0x58,
        world_x=world_x,
        world_y=world_y,
        world_z=0,
        map_x=float(world_x),
        map_y=float(world_y),
        health=health,
        slot=slot,
        action_state=action_state,
        tactical=tactical,
        pair_role=pair_role,
        combat_phase=phase,
        boss_dist_x=boss_dist_x,
        boss_dist_lane=boss_dist_lane,
    )


def _player(world_x: int = 120, world_y: int = 64) -> MapEntity:
    return MapEntity(
        kind="player",
        family="Player",
        symbol="P",
        color="#fff",
        label="P1",
        type_id=1,
        world_x=world_x,
        world_y=world_y,
        world_z=0,
        map_x=float(world_x),
        map_y=float(world_y),
        health=0x60,
        slot="P1",
        action_state=0x02,
    )


class TwinRoutineTests(unittest.TestCase):
    def test_primary_two_is_commit(self) -> None:
        t = _twin(slot="B0", world_x=160, action_state=0x02)
        self.assertEqual(decode_routine(t), TwinRoutine.COMMIT)

    def test_approach_jump_substate(self) -> None:
        t = _twin(
            slot="B0",
            world_x=160,
            pair_role=1,
            action_state=0x01,
            tactical=0x02,
        )
        self.assertEqual(decode_routine(t), TwinRoutine.APPROACH_JUMP)

    def test_grab_role_is_hunt(self) -> None:
        t = _twin(
            slot="B1",
            world_x=160,
            pair_role=2,
            action_state=0x01,
            tactical=0x00,
        )
        self.assertEqual(decode_routine(t), TwinRoutine.GRAB_HUNT)

    def test_grab_leap_substate(self) -> None:
        t = _twin(
            slot="B1",
            world_x=160,
            pair_role=2,
            action_state=0x01,
            tactical=0x03,
        )
        self.assertEqual(decode_routine(t), TwinRoutine.GRAB_LEAP)

    def test_recovery_primary(self) -> None:
        t = _twin(slot="B0", world_x=160, action_state=0x03)
        self.assertEqual(decode_routine(t), TwinRoutine.RECOVERY)

    def test_jump_arm_window_uses_boss_dist(self) -> None:
        me = _player(120)
        close = _twin(slot="B0", world_x=200, boss_dist_x=0x50)  # 80 < 96
        far = _twin(slot="B1", world_x=200, boss_dist_x=0x70)  # 112
        self.assertTrue(in_jump_arm_range(me, close))
        self.assertFalse(in_jump_arm_range(me, far))


class TwinFocusTests(unittest.TestCase):
    def test_focus_latches_and_stays(self) -> None:
        me = _player(120)
        weak = _twin(slot="B0", world_x=150, health=0x08, pair_role=1)
        strong = _twin(slot="B1", world_x=180, health=0x20, pair_role=2)
        mem = TwinFocusMemory()
        slot = update_focus(me, (weak, strong), mem)
        self.assertEqual(slot, "B0")
        self.assertEqual(mem.focus_slot, "B0")
        # Stronger twin closer later — still stick to B0.
        strong2 = _twin(slot="B1", world_x=125, health=0x20, pair_role=2)
        self.assertEqual(update_focus(me, (weak, strong2), mem), "B0")

    def test_focus_moves_to_survivor_after_kill(self) -> None:
        me = _player(120)
        a = _twin(slot="B0", world_x=150, health=0x08)
        b = _twin(slot="B1", world_x=180, health=0x20)
        mem = TwinFocusMemory()
        update_focus(me, (a, b), mem)
        self.assertEqual(mem.focus_slot, "B0")
        dead = _twin(
            slot="B0",
            world_x=150,
            health=0x8000,
            phase=CombatPhase.DEATH,
        )
        self.assertEqual(update_focus(me, (dead, b), mem), "B1")
        self.assertEqual(twin_composition((dead, b)), TwinComposition.SURVIVOR)

    def test_focus_utility_dominates_other_twin(self) -> None:
        a = _twin(slot="B0", world_x=150)
        b = _twin(slot="B1", world_x=155)
        self.assertGreater(
            twin_focus_bonus(a, (a, b), focus_slot="B0"),
            twin_focus_bonus(b, (a, b), focus_slot="B0") + 0.5,
        )

    def test_select_target_hard_locks_focus(self) -> None:
        me = _player(120)
        focus = _twin(slot="B0", world_x=200, world_y=64, health=0x20)
        other = _twin(
            slot="B1",
            world_x=140,
            world_y=64,
            health=0x04,
            pair_role=2,
            phase=CombatPhase.ATTACKING,
            action_state=0x02,
        )
        # Closer + attacking other would normally win; focus lock forces B0.
        chosen = select_target(
            me,
            (focus, other),
            PROFILES[0],
            twin_focus_slot="B0",
        )
        self.assertIsNotNone(chosen)
        assert chosen is not None
        self.assertEqual(chosen.entity.slot, "B0")


class TwinPlanAndTacticTests(unittest.TestCase):
    def test_pair_focus_plan_no_jump(self) -> None:
        a = _twin(slot="B0", world_x=160)
        b = _twin(slot="B1", world_x=180, pair_role=2)
        plan = plan_for(a, (a, b), focus_slot="B0")
        self.assertTrue(plan.no_jump)
        self.assertIn("focus", plan.note)
        self.assertEqual(plan.grab_bias, 0.0)

    def test_survivor_plan_allows_grab(self) -> None:
        a = _twin(slot="B0", world_x=160)
        plan = plan_for_twin(a, (a,), focus_slot="B0")
        assert plan is not None
        self.assertGreaterEqual(plan.grab_bias, 0.5)
        self.assertIn("survivor", plan.note)
        self.assertFalse(plan.no_jump)

    def test_commit_overlay_on_focus_plan(self) -> None:
        a = _twin(slot="B0", world_x=160, action_state=0x02)
        b = _twin(slot="B1", world_x=180, pair_role=2)
        plan = plan_for(a, (a, b), focus_slot="B0")
        self.assertIn("commit", plan.note)
        self.assertGreaterEqual(plan.range_scale, 1.5)

    def test_pair_surround_still_works(self) -> None:
        me = _player(120, 64)
        left = _twin(slot="B0", world_x=80, world_y=64)
        right = _twin(slot="B1", world_x=160, world_y=66, pair_role=2)
        move = tactical_move(
            me,
            right,
            (me, left, right),
            level_index=4,
            focus_slot="B0",
        )
        self.assertIsNotNone(move)
        assert move is not None
        self.assertIn("surround", move.note)

    def test_partner_commit_evades_while_focusing_other(self) -> None:
        me = _player(120, 64)
        focus = _twin(slot="B0", world_x=200, world_y=64, pair_role=1)
        partner = _twin(
            slot="B1",
            world_x=130,
            world_y=64,
            pair_role=2,
            action_state=0x02,
            phase=CombatPhase.ATTACKING,
        )
        move = tactical_move(
            me,
            focus,
            (me, focus, partner),
            level_index=4,
            focus_slot="B0",
        )
        self.assertIsNotNone(move)
        assert move is not None
        self.assertIn("partner-evade", move.note)

    def test_survivor_idle_no_forced_move(self) -> None:
        me = _player(120, 64)
        # Far enough that jump-arm window is false (ΔX=80 >= 96? 200-120=80 < 96)
        # Park survivor at ΔX=120 so no deny window.
        survivor = _twin(slot="B0", world_x=240, world_y=64, action_state=0x01)
        move = tactical_move(
            me,
            survivor,
            (me, survivor),
            level_index=4,
            focus_slot="B0",
        )
        self.assertIsNone(move)


if __name__ == "__main__":
    unittest.main()
