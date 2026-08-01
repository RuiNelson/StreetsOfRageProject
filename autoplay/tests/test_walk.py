"""Walk-to-(x,y) latch tests."""

from __future__ import annotations

import unittest

from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
from sor_autoplay.agent.walk import WalkState
from sor_autoplay.memory_map import MAX_HEALTH, OBJ_CHARACTER_ID, OBJ_HEALTH, OBJ_POS_X, OBJ_POS_Y, OBJ_TYPE
from sor_autoplay.state import snapshot_from_memory_blocks
from sor_autoplay.world_map import MapEntity, WorldMap


def _player(world_x: int = 100, world_y: int = 64) -> MapEntity:
    return MapEntity(
        kind="player",
        family="Player",
        symbol="1",
        color="#fff",
        label="P1",
        type_id=1,
        world_x=world_x,
        world_y=world_y,
        world_z=0,
        map_x=float(world_x),
        map_y=float(world_y),
        health=MAX_HEALTH,
        slot="P1",
    )


class WalkStateTests(unittest.TestCase):
    def test_holds_direction_until_past(self) -> None:
        walk = WalkState()
        me = _player(100, 64)
        walk.set_goal(me, goal_x=200, goal_y=64, reason="test")
        # Many steps while still left of goal: always RIGHT held.
        for x in range(100, 190, 5):
            me = _player(x, 64)
            intent = walk.step(me)
            assert intent is not None
            self.assertTrue(intent.right, msg=f"x={x} note={intent.note}")
            self.assertFalse(intent.left)
            self.assertTrue(walk.active)

        # Past goal: walk completes.
        me = _player(205, 64)
        intent = walk.step(me)
        assert intent is not None
        self.assertIn("done", intent.note)
        self.assertFalse(walk.active)

    def test_same_goal_keeps_latch(self) -> None:
        walk = WalkState()
        me = _player(100, 64)
        walk.set_goal(me, 200, 64, reason="a")
        d0 = walk.dir_x
        walk.set_goal(me, 205, 64, reason="b")  # within slack
        self.assertEqual(walk.dir_x, d0)
        self.assertEqual(walk.reason, "b")

    def test_already_on_goal_is_not_active(self) -> None:
        walk = WalkState()
        me = _player(100, 64)
        walk.set_goal(me, 105, 64, reason="near", eps_x=10)
        # |105-100| <= 10 → already on band, no walk armed.
        self.assertFalse(walk.active)
        self.assertIsNone(walk.step(me))

    def test_arrive_after_travel(self) -> None:
        walk = WalkState()
        me = _player(100, 64)
        walk.set_goal(me, 150, 64, reason="far", eps_x=10)
        self.assertTrue(walk.active)
        me = _player(148, 64)
        intent = walk.step(me)
        assert intent is not None
        self.assertIn("done", intent.note)
        self.assertFalse(walk.active)


class PolicyWalkIntegrationTests(unittest.TestCase):
    def _snap(self, entities: tuple[MapEntity, ...]):
        from dataclasses import replace

        def put_u8(buf: bytearray, off: int, v: int) -> None:
            buf[off] = v & 0xFF

        def put_u16(buf: bytearray, off: int, v: int) -> None:
            buf[off : off + 2] = (v & 0xFFFF).to_bytes(2, "big")

        g = bytearray(0x40)
        t = bytearray(4)
        o = bytearray(0x100)
        put_u16(g, 0x00, 0x0016)
        put_u8(g, 0x18, 0x01)
        put_u8(g, 0x1E, 0x00)
        put_u8(g, 0x20, 0x03)
        put_u8(g, 0x21, 0x02)
        put_u16(t, 0, 0x0040)
        put_u8(o, OBJ_TYPE, 0x01)
        put_u16(o, OBJ_HEALTH, MAX_HEALTH)
        put_u8(o, OBJ_CHARACTER_ID, 0x00)
        put_u16(o, OBJ_POS_X, 100)
        put_u16(o, OBJ_POS_Y, 0x40)
        snap = snapshot_from_memory_blocks(
            globals_block=bytes(g), timer_block=bytes(t), objects_block=bytes(o)
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
        return replace(snap, world_map=world)

    def test_progress_uses_walk_note(self) -> None:
        p1 = _player(100, 64)
        snap = self._snap((p1,))
        mem = AgentState()
        d = decide_actions(snap, AgentConfig(p1_enabled=True), mem)
        self.assertTrue(d.p1_mask & 0x08, msg=hex(d.p1_mask))  # RIGHT
        self.assertIn("walk", d.p1_note)
        self.assertTrue(mem.p1_walk.active)

        # Same goal neighbourhood while player barely moves: still RIGHT.
        d2 = decide_actions(snap, AgentConfig(p1_enabled=True), mem)
        self.assertTrue(d2.p1_mask & 0x08)
        self.assertTrue(mem.p1_walk.active)


if __name__ == "__main__":
    unittest.main()
