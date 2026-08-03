"""Stage geometry and ROM-backed boss movement regressions."""

from __future__ import annotations

import unittest

from sor_autoplay.agent.bosses import tactical_move
from sor_autoplay.agent.stage import (
    is_stage_press,
    press_blocks_goal,
    press_bypass_goal,
    press_same_lane_threat,
    press_solid_holes,
    safer_lane_from_press,
    select_blocking_press,
    stage_advice,
    steer_away_from_holes,
    under_stage_press,
)
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


class StagePressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.me = _entity(
            kind="player",
            type_id=1,
            world_x=100,
            world_y=64,
            slot="P1",
        )
        self.press = MapEntity(
            kind="projectile",
            family="Stage hazard",
            symbol="!",
            color="#ef4444",
            label="Press",
            type_id=0x42,
            world_x=130,
            world_y=64,
            world_z=0x40,
            map_x=130.0,
            map_y=64.0,
            health=None,
            slot="H0",
            outgoing_damage=0x14,
            combat_phase=CombatPhase.ATTACKING,
        )

    def test_type_42_is_stage_press(self) -> None:
        self.assertTrue(is_stage_press(self.press))
        self.assertFalse(is_stage_press(self.me))

    def test_solid_body_aabb_blocks_press_lane(self) -> None:
        solids = press_solid_holes((self.press,))
        self.assertEqual(len(solids), 1)
        solid = solids[0]
        # Press centre sits inside the solid AABB.
        self.assertLessEqual(solid.world_x, self.press.world_x)
        self.assertGreaterEqual(solid.world_x_end, self.press.world_x)
        self.assertLessEqual(solid.lane_y, self.press.world_y)
        self.assertGreaterEqual(solid.lane_y_end, self.press.world_y)

    def test_under_and_approach_bands(self) -> None:
        # me at 100, press at 130: |dx|=30 is inside the crush half-X (48).
        self.assertTrue(press_same_lane_threat(self.me, self.press))
        self.assertTrue(under_stage_press(self.me, self.press))
        # Approach-only: inside react X (100) but outside crush half-X (48).
        approach = _entity(
            kind="player",
            type_id=1,
            world_x=70,
            world_y=64,
            slot="P1",
        )
        self.assertTrue(press_same_lane_threat(approach, self.press))
        self.assertFalse(under_stage_press(approach, self.press))
        under = _entity(
            kind="player",
            type_id=1,
            world_x=130,
            world_y=64,
            slot="P1",
        )
        self.assertTrue(under_stage_press(under, self.press))

    def test_safer_lane_leaves_press_lane(self) -> None:
        goal_y = safer_lane_from_press(
            self.me, self.press, level_index=5, camera_bottom=112.0
        )
        self.assertNotAlmostEqual(goal_y, float(self.press.world_y))
        self.assertGreater(abs(goal_y - float(self.press.world_y)), 20.0)
        # Round 6 free path is the lower class-1 floor, not the upper rim
        # (upper holds class-2 machine walls that block RIGHT).
        self.assertGreater(goal_y, float(self.press.world_y))

    def test_solid_housing_blocks_progress_goal(self) -> None:
        """Progress straight through a press X on its lane must be blocked."""

        self.assertTrue(
            press_blocks_goal(self.me, self.press, goal_x=260.0, goal_y=64.0)
        )
        # Free lower lane past the crusher body is not a block for progress.
        past = _entity(
            kind="player",
            type_id=1,
            world_x=220,
            world_y=96,
            slot="P1",
        )
        self.assertFalse(
            press_blocks_goal(past, self.press, goal_x=300.0, goal_y=96.0)
        )

    def test_bypass_detours_then_advances_past_housing(self) -> None:
        gx, gy, reason = press_bypass_goal(
            self.me,
            self.press,
            progress_right=True,
            level_index=5,
            camera_bottom=112.0,
        )
        # First phase: leave the solid lane at current X toward lower free path.
        self.assertIn("press", reason)
        self.assertEqual(gx, float(self.me.world_x))
        self.assertGreater(gy, float(self.press.world_y))

        # Second phase: once on the safe lane, advance past the solid far edge.
        on_safe = _entity(
            kind="player",
            type_id=1,
            world_x=100,
            world_y=int(gy),
            slot="P1",
        )
        gx2, gy2, reason2 = press_bypass_goal(
            on_safe,
            self.press,
            progress_right=True,
            level_index=5,
            camera_bottom=112.0,
        )
        self.assertIn("advance past press", reason2)
        self.assertGreater(gx2, float(self.press.world_x))
        self.assertAlmostEqual(gy2, gy, delta=1.0)

    def test_free_lower_lane_does_not_detour_to_upper_rim(self) -> None:
        """Regression: oversized solid + upper-only free edge caused stage-6 shake."""

        free_lower = _entity(
            kind="player",
            type_id=1,
            world_x=100,
            world_y=96,
            slot="P1",
        )
        # Free of the crusher body on Y — not a corridor block.
        self.assertIsNone(
            select_blocking_press(
                free_lower,
                (self.press,),
                goal_x=260.0,
                goal_y=96.0,
                progress_right=True,
            )
        )
        # If bypass is asked anyway, advance on the free lower lane (not UP).
        gx, gy, reason = press_bypass_goal(
            free_lower,
            self.press,
            progress_right=True,
            level_index=5,
            camera_bottom=112.0,
        )
        self.assertIn("advance past press", reason)
        self.assertGreater(gx, float(self.press.world_x))
        self.assertGreater(gy, float(self.press.world_y))
        self.assertGreaterEqual(gy, 90.0)

    def test_select_blocking_press_on_corridor(self) -> None:
        chosen = select_blocking_press(
            self.me,
            (self.press,),
            goal_x=260.0,
            goal_y=64.0,
            progress_right=True,
        )
        self.assertIs(chosen, self.press)

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
