"""Stage geometry and ROM-backed boss movement regressions."""

from __future__ import annotations

import unittest

from sor_autoplay.agent.bosses import tactical_move
from sor_autoplay.agent.stage import stage_advice, steer_away_from_holes
from sor_autoplay.hazards import FloorHole
from sor_autoplay.phases import CombatPhase, boss_phase
from sor_autoplay.world_map import MapEntity


def _entity(
    *,
    kind: str,
    type_id: int,
    world_x: int,
    world_y: int,
    slot: str,
    phase: CombatPhase = CombatPhase.NORMAL,
) -> MapEntity:
    return MapEntity(
        kind=kind,
        family="Player" if kind == "player" else "Boss",
        symbol="P" if kind == "player" else "B",
        color="#fff",
        label=slot,
        type_id=type_id,
        world_x=world_x,
        world_y=world_y,
        world_z=0,
        map_x=float(world_x),
        map_y=float(world_y),
        health=0x20,
        slot=slot,
        action_state=0x02,
        combat_phase=phase,
    )


class StageGeometryTests(unittest.TestCase):
    def test_stage4_progress_turns_into_vertical_detour_at_pit(self) -> None:
        hole = FloorHole(world_x=100, lane_y=40, width=32, height=24)
        dx, dy = steer_away_from_holes(
            90,
            50,
            1.0,
            0.0,
            (hole,),
            level_index=3,
        )
        self.assertEqual(dx, 0.0)
        self.assertLess(dy, 0.0)

    def test_stage4_resumes_horizontal_progress_from_safe_lane(self) -> None:
        hole = FloorHole(world_x=100, lane_y=40, width=32, height=24)
        dx, dy = steer_away_from_holes(
            90,
            24,
            1.0,
            0.0,
            (hole,),
            level_index=3,
        )
        self.assertGreater(dx, 0.0)
        self.assertEqual(dy, 0.0)

    def test_round7_elevator_has_no_horizontal_progress_or_static_holes(self) -> None:
        advice = stage_advice(6)
        self.assertTrue(advice.elevator)
        self.assertFalse(advice.horizontal_progress)
        self.assertFalse(advice.avoid_holes)


class BossPhaseTests(unittest.TestCase):
    def test_souther_primary_two_is_claw_attack_without_tactical_byte(self) -> None:
        self.assertEqual(
            boss_phase(type_id=0x55, primary_byte=0x02, tactical=0),
            CombatPhase.ATTACKING,
        )

    def test_twin_primary_two_is_jump_grab_without_tactical_byte(self) -> None:
        self.assertEqual(
            boss_phase(type_id=0x58, primary_byte=0x02, tactical=0),
            CombatPhase.ATTACKING,
        )


class BossTacticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.me = _entity(
            kind="player",
            type_id=1,
            world_x=120,
            world_y=64,
            slot="P1",
        )

    def test_souther_claw_commit_is_evaded_on_lane(self) -> None:
        souther = _entity(
            kind="boss",
            type_id=0x55,
            world_x=175,
            world_y=64,
            slot="B0",
            phase=CombatPhase.ATTACKING,
        )
        move = tactical_move(self.me, souther, (self.me, souther), level_index=1)
        self.assertIsNotNone(move)
        assert move is not None
        self.assertFalse(move.hold)
        self.assertEqual(move.goal_x, self.me.world_x)
        self.assertNotEqual(move.goal_y, self.me.world_y)

    def test_souther_attack_does_not_pull_player_back_into_lane(self) -> None:
        souther = _entity(
            kind="boss",
            type_id=0x55,
            world_x=175,
            world_y=92,
            slot="B0",
            phase=CombatPhase.ATTACKING,
        )
        move = tactical_move(self.me, souther, (self.me, souther), level_index=1)
        self.assertIsNotNone(move)
        assert move is not None
        self.assertTrue(move.hold)
        self.assertIn("safe lane", move.note)

    def test_stage5_twins_bracketing_player_force_lane_escape(self) -> None:
        left = _entity(
            kind="boss",
            type_id=0x58,
            world_x=80,
            world_y=64,
            slot="B0",
        )
        right = _entity(
            kind="boss",
            type_id=0x58,
            world_x=160,
            world_y=66,
            slot="B1",
        )
        move = tactical_move(
            self.me,
            right,
            (self.me, left, right),
            level_index=4,
        )
        self.assertIsNotNone(move)
        assert move is not None
        self.assertFalse(move.hold)
        self.assertIn("surround", move.note)
        self.assertNotEqual(move.goal_y, self.me.world_y)


if __name__ == "__main__":
    unittest.main()
