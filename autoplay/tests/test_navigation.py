"""Symbolic navigation: hole detours, breakable sides, jump landing safety."""

from __future__ import annotations

import unittest

from sor_autoplay.agent.characters import profile_for
from sor_autoplay.agent.controls import JUMP
from sor_autoplay.agent.navigation import (
    NavMemory,
    NavPhase,
    breakable_side_approach,
    breakable_side_ready,
    jump_landing_safe,
    observe_motion,
    path_blocked_ahead,
    recover_when_stuck,
    route_to_goal,
)
from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
from sor_autoplay.hazards import FloorHole
from sor_autoplay.memory_map import MAX_HEALTH, OBJ_CHARACTER_ID, OBJ_HEALTH, OBJ_POS_X, OBJ_POS_Y, OBJ_TYPE
from sor_autoplay.state import snapshot_from_memory_blocks
from sor_autoplay.world_map import MapEntity, WorldMap


def _entity(
    *,
    kind: str,
    map_x: float,
    map_y: float,
    world_x: int | None = None,
    world_y: int | None = None,
    slot: str = "E0",
    label: str = "X",
    family: str = "X",
    type_id: int = 0x20,
    action_state: int = 0x02,
) -> MapEntity:
    wx = int(world_x if world_x is not None else map_x)
    wy = int(world_y if world_y is not None else map_y)
    return MapEntity(
        kind=kind,
        family=family,
        symbol="x",
        color="#fff",
        label=label,
        type_id=type_id,
        world_x=wx,
        world_y=wy,
        world_z=0,
        map_x=map_x,
        map_y=map_y,
        health=10 if kind == "enemy" else None,
        slot=slot,
        action_state=action_state,
    )


def _put_u8(buf: bytearray, offset: int, value: int) -> None:
    buf[offset] = value & 0xFF


def _put_u16(buf: bytearray, offset: int, value: int) -> None:
    buf[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def _snapshot(entities: tuple[MapEntity, ...], *, level_index: int = 3, holes=()) -> object:
    from dataclasses import replace

    globals_block = bytearray(0x40)
    timer_block = bytearray(4)
    objects = bytearray(0x100)
    _put_u16(globals_block, 0x00, 0x0016)
    _put_u16(globals_block, 0x02, level_index)
    _put_u16(globals_block, 0x04, 0x0001)
    _put_u8(globals_block, 0x18, 0x01)
    _put_u8(globals_block, 0x1E, 0x00)
    _put_u8(globals_block, 0x20, 0x03)
    _put_u8(globals_block, 0x21, 0x02)
    _put_u16(timer_block, 0, 0x0040)
    _put_u8(objects, OBJ_TYPE, 0x01)
    _put_u16(objects, OBJ_HEALTH, MAX_HEALTH)
    _put_u8(objects, OBJ_CHARACTER_ID, 0x00)
    _put_u16(objects, OBJ_POS_X, 100)
    _put_u16(objects, OBJ_POS_Y, 0x40)
    snap = snapshot_from_memory_blocks(
        globals_block=bytes(globals_block),
        timer_block=bytes(timer_block),
        objects_block=bytes(objects),
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
    return replace(snap, world_map=world, floor_holes=holes)


class HoleRoutingTests(unittest.TestCase):
    def test_detour_latches_one_lane_without_flip(self) -> None:
        hole = FloorHole(world_x=100, lane_y=40, width=32, height=24)
        me = _entity(
            kind="player",
            map_x=90,
            map_y=50,
            world_x=90,
            world_y=50,
            slot="P1",
            label="P1",
            family="Player",
        )
        memory = NavMemory()
        first = route_to_goal(
            me,
            250.0,
            50.0,
            (hole,),
            memory,
            level_index=3,
            progress_right=True,
            reason="progress",
        )
        self.assertEqual(memory.phase, NavPhase.DETOUR)
        self.assertIsNotNone(memory.detour_lane)
        latched = memory.detour_lane
        self.assertEqual(first.goal_x, 90.0)
        self.assertEqual(first.goal_y, latched)

        # Same geometry next tick — must keep the same detour side.
        second = route_to_goal(
            me,
            250.0,
            50.0,
            (hole,),
            memory,
            level_index=3,
            progress_right=True,
            reason="progress",
        )
        self.assertEqual(memory.detour_lane, latched)
        self.assertEqual(second.goal_y, latched)
        self.assertTrue(second.committed)

    def test_path_blocked_ahead_detects_pit(self) -> None:
        hole = FloorHole(world_x=100, lane_y=40, width=32, height=24)
        hit = path_blocked_ahead(90.0, 50.0, progress_right=True, holes=(hole,))
        self.assertIs(hit, hole)

    def test_stage4_policy_does_not_oscillate_vertical(self) -> None:
        hole = FloorHole(world_x=100, lane_y=40, width=32, height=24)
        memory = AgentState()
        vertical_signs: list[int] = []
        x, y = 90, 50
        for _ in range(6):
            p1 = _entity(
                kind="player",
                map_x=x,
                map_y=y,
                world_x=x,
                world_y=y,
                slot="P1",
                label="P1 Axel",
                family="Player",
            )
            snap = _snapshot((p1,), level_index=3, holes=(hole,))
            decision = decide_actions(
                snap, AgentConfig(p1_enabled=True), memory
            )
            up = bool(decision.p1_mask & 0x01)
            down = bool(decision.p1_mask & 0x02)
            if up:
                vertical_signs.append(-1)
                y -= 8
            elif down:
                vertical_signs.append(1)
                y += 8
            else:
                vertical_signs.append(0)
                if decision.p1_mask & 0x08:
                    x += 8
                if decision.p1_mask & 0x04:
                    x -= 8
        # While detouring, vertical sign must not flip-flop every tick.
        nonzero = [s for s in vertical_signs if s != 0]
        if len(nonzero) >= 2:
            self.assertTrue(
                all(s == nonzero[0] for s in nonzero),
                f"vertical oscillation: {vertical_signs}",
            )


class BreakableSideTests(unittest.TestCase):
    def test_top_bottom_stack_moves_to_side_first(self) -> None:
        me = _entity(
            kind="player",
            map_x=100,
            map_y=40,
            world_x=100,
            world_y=40,
            slot="P1",
            family="Player",
        )
        prop = _entity(
            kind="breakable",
            map_x=100,
            map_y=64,
            world_x=100,
            world_y=64,
            slot="B0",
            label="Crate",
            family="Crate",
            type_id=0x11,
        )
        profile = profile_for(0)
        wp = breakable_side_approach(me, prop, profile, progress_right=True)
        self.assertNotEqual(wp.goal_x, float(prop.world_x))
        self.assertEqual(wp.goal_y, float(me.world_y))
        self.assertIn("side-align", wp.reason)
        self.assertFalse(breakable_side_ready(me, prop, profile))

    def test_side_stand_is_ready_to_smash(self) -> None:
        me = _entity(
            kind="player",
            map_x=70,
            map_y=64,
            world_x=70,
            world_y=64,
            slot="P1",
            family="Player",
        )
        prop = _entity(
            kind="breakable",
            map_x=100,
            map_y=64,
            world_x=100,
            world_y=64,
            slot="B0",
            label="Crate",
            family="Crate",
            type_id=0x11,
        )
        profile = profile_for(0)
        self.assertTrue(breakable_side_ready(me, prop, profile))
        wp = breakable_side_approach(me, prop, profile, progress_right=True)
        self.assertLess(wp.goal_x, float(prop.world_x))

    def test_hole_left_of_crate_forces_right_approach(self) -> None:
        """Stage-4 style: pit abuts crate from the left → stand on the right."""
        from sor_autoplay.agent.navigation import choose_breakable_side

        # Hole: x=60..100, crate at x=110, left stand (~78) is in the pit.
        hole = FloorHole(world_x=60, lane_y=48, width=44, height=40)
        prop = _entity(
            kind="breakable",
            map_x=110,
            map_y=64,
            world_x=110,
            world_y=64,
            slot="crate",
            label="Crate",
            family="Crate",
            type_id=0x11,
        )
        # Player is left of the hole — old code stayed on the left side forever.
        me = _entity(
            kind="player",
            map_x=40,
            map_y=64,
            world_x=40,
            world_y=64,
            slot="P1",
            family="Player",
        )
        profile = profile_for(0)
        memory = NavMemory()
        side = choose_breakable_side(
            me, prop, profile, (hole,), memory, progress_right=True
        )
        self.assertEqual(side, 1, "must approach from the solid right side")
        wp = breakable_side_approach(
            me,
            prop,
            profile,
            progress_right=True,
            holes=(hole,),
            memory=memory,
        )
        self.assertGreater(wp.goal_x, float(prop.world_x))
        self.assertEqual(memory.break_side, 1)
        # Hysteresis: even from the left, keep the right commitment.
        side2 = choose_breakable_side(
            me, prop, profile, (hole,), memory, progress_right=True
        )
        self.assertEqual(side2, 1)
        self.assertIn("R", wp.reason)

    def test_hole_crate_policy_does_not_flip_side(self) -> None:
        hole = FloorHole(world_x=60, lane_y=48, width=44, height=40)
        p1 = _entity(
            kind="player",
            map_x=40,
            map_y=64,
            world_x=40,
            world_y=64,
            slot="P1",
            label="P1 Axel",
            family="Player",
        )
        crate = _entity(
            kind="breakable",
            map_x=110,
            map_y=64,
            world_x=110,
            world_y=64,
            slot="obj01",
            label="Crate",
            family="Crate",
            type_id=0x11,
        )
        memory = AgentState()
        sides: list[str] = []
        x, y = 40.0, 64.0
        for _ in range(8):
            p1 = _entity(
                kind="player",
                map_x=x,
                map_y=y,
                world_x=int(x),
                world_y=int(y),
                slot="P1",
                label="P1 Axel",
                family="Player",
            )
            snap = _snapshot((p1, crate), level_index=3, holes=(hole,))
            decision = decide_actions(
                snap, AgentConfig(p1_enabled=True), memory
            )
            sides.append(decision.p1_note)
            if decision.p1_mask & 0x08:
                x += 10
            if decision.p1_mask & 0x04:
                x -= 10
            if decision.p1_mask & 0x02:
                y += 10
            if decision.p1_mask & 0x01:
                y -= 10
        self.assertEqual(memory.p1_nav.break_side, 1, sides)
        # Notes must not alternate L/R break sides.
        break_notes = [n for n in sides if "break" in n]
        if break_notes:
            has_l = any(" L " in n or "side-align L" in n or "close L" in n for n in break_notes)
            has_r = any(" R " in n or "side-align R" in n or "close R" in n or "safe R" in n or "lane R" in n for n in break_notes)
            self.assertFalse(has_l and has_r, break_notes)

    def test_policy_does_not_walk_vertically_onto_crate_x(self) -> None:
        p1 = _entity(
            kind="player",
            map_x=100,
            map_y=30,
            world_x=100,
            world_y=30,
            slot="P1",
            label="P1 Axel",
            family="Player",
        )
        crate = _entity(
            kind="breakable",
            map_x=100,
            map_y=64,
            world_x=100,
            world_y=64,
            slot="obj01",
            label="Crate",
            family="Crate",
            type_id=0x11,
        )
        snap = _snapshot((p1, crate), level_index=0, holes=())
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        # Must hold LEFT or RIGHT to leave the prop X, not only UP/DOWN.
        self.assertTrue(
            decision.p1_mask & 0x0C,
            decision.p1_note,
        )
        self.assertIn("side", decision.p1_note)


class StuckRecoveryTests(unittest.TestCase):
    def test_stuck_picks_alternate_safe_direction(self) -> None:
        """After no motion, abandon the blocked forward goal for a side step."""
        # Wide pit immediately to the right; forward goal is into the void.
        hole = FloorHole(world_x=100, lane_y=40, width=80, height=50)
        me = _entity(
            kind="player",
            map_x=90,
            map_y=64,
            world_x=90,
            world_y=64,
            slot="P1",
            family="Player",
        )
        memory = NavMemory()
        # Simulate being stuck while aiming right into the hole.
        for _ in range(20):
            observe_motion(memory, me)
        self.assertGreaterEqual(memory.stuck_ticks, 14)
        wp = recover_when_stuck(
            me,
            goal_x=200.0,
            goal_y=64.0,
            holes=(hole,),
            memory=memory,
            level_index=3,
            progress_right=True,
        )
        self.assertIsNotNone(wp)
        assert wp is not None
        self.assertIn("unstuck", wp.reason)
        # Must not aim into the pit.
        from sor_autoplay.agent.navigation import point_in_hole

        self.assertIsNone(
            point_in_hole(wp.goal_x, wp.goal_y, (hole,), margin=12.0),
            wp,
        )
        # Prefer a lane change rather than walking deeper into the hole.
        self.assertTrue(
            abs(wp.goal_y - 64.0) >= 10.0 or wp.goal_x <= 90.0,
            wp,
        )

    def test_route_to_goal_overrides_when_stuck(self) -> None:
        hole = FloorHole(world_x=100, lane_y=40, width=80, height=50)
        me = _entity(
            kind="player",
            map_x=90,
            map_y=64,
            world_x=90,
            world_y=64,
            slot="P1",
            family="Player",
        )
        memory = NavMemory()
        for _ in range(16):
            wp = route_to_goal(
                me,
                220.0,
                64.0,
                (hole,),
                memory,
                level_index=3,
                progress_right=True,
                reason="progress",
            )
        self.assertIn("unstuck", wp.reason)
        self.assertTrue(wp.committed)

    def test_force_goal_refresh_preserves_walk_stuck(self) -> None:
        from sor_autoplay.agent.walk import WalkState

        walk = WalkState()
        me = _entity(
            kind="player",
            map_x=100,
            map_y=64,
            world_x=100,
            world_y=64,
            slot="P1",
            family="Player",
        )
        walk.set_goal(me, 200, 64, reason="a")
        # Simulate stuck polls with forced same-neighbourhood refresh.
        for _ in range(25):
            walk.set_goal(me, 202, 64, reason="a", force=True, eps_x=6, eps_y=5)
            walk.step(me)
        # Stuck path should have tried a perpendicular re-aim (dir_y != 0)
        # at some point, or still be counting stuck.
        self.assertTrue(
            walk.stuck_ticks > 0 or walk.dir_y != 0 or walk.dir_x != 0,
            f"stuck={walk.stuck_ticks} dir=({walk.dir_x},{walk.dir_y})",
        )


class JumpLandingTests(unittest.TestCase):
    def test_jump_across_hole_is_unsafe(self) -> None:
        hole = FloorHole(world_x=110, lane_y=50, width=40, height=30)
        me = _entity(
            kind="player",
            map_x=90,
            map_y=64,
            world_x=90,
            world_y=64,
            slot="P1",
            family="Player",
        )
        foe = _entity(
            kind="enemy",
            map_x=160,
            map_y=64,
            world_x=160,
            world_y=64,
            slot="E0",
            label="Garcia",
            family="Garcia",
        )
        self.assertFalse(jump_landing_safe(me, foe, (hole,)))

    def test_jump_on_solid_ground_is_safe(self) -> None:
        hole = FloorHole(world_x=200, lane_y=50, width=40, height=30)
        me = _entity(
            kind="player",
            map_x=90,
            map_y=64,
            world_x=90,
            world_y=64,
            slot="P1",
            family="Player",
        )
        foe = _entity(
            kind="enemy",
            map_x=130,
            map_y=64,
            world_x=130,
            world_y=64,
            slot="E0",
            label="Garcia",
            family="Garcia",
        )
        self.assertTrue(jump_landing_safe(me, foe, (hole,)))

    def test_policy_refuses_jump_kick_into_hole(self) -> None:
        hole = FloorHole(world_x=110, lane_y=50, width=50, height=40)
        p1 = _entity(
            kind="player",
            map_x=90,
            map_y=64,
            world_x=90,
            world_y=64,
            slot="P1",
            label="P1 Axel",
            family="Player",
        )
        # Mid jump-kick window for Axel (~28-50).
        foe = _entity(
            kind="enemy",
            map_x=130,
            map_y=64,
            world_x=130,
            world_y=64,
            slot="E0",
            label="Garcia",
            family="Garcia",
            type_id=0x25,  # Haku-Ro has jump bias
        )
        snap = _snapshot((p1, foe), level_index=3, holes=(hole,))
        memory = AgentState()
        saw_jump = False
        for _ in range(12):
            decision = decide_actions(
                snap, AgentConfig(p1_enabled=True), memory
            )
            if decision.p1_mask & int(JUMP) and not (
                decision.p1_mask & 0x20
            ):
                # Pure C without B (not rear chord) would be jump start.
                if "jump" in decision.p1_note and "Signal" not in decision.p1_note:
                    saw_jump = True
                    break
        self.assertFalse(saw_jump, "must not jump-kick into a floor hole")


if __name__ == "__main__":
    unittest.main()
