"""On-screen targeting, jump-in, and rear-reaction behaviour."""

from __future__ import annotations

import unittest

from sor_autoplay.agent.characters import PROFILES
from sor_autoplay.agent.combat import (
    JUMP_KICK_MAX,
    closest_behind,
    engagement_band,
    is_on_screen,
    select_target,
)
from sor_autoplay.agent.enemies import attack_mix, plan_for
from sor_autoplay.agent.policy import AgentConfig, AgentState, decide_actions
from sor_autoplay.memory_map import MAX_HEALTH, OBJ_CHARACTER_ID, OBJ_HEALTH, OBJ_POS_X, OBJ_POS_Y, OBJ_TYPE
from sor_autoplay.phases import CombatPhase
from sor_autoplay.state import snapshot_from_memory_blocks
from sor_autoplay.world_map import MapEntity, WorldMap


def _e(**kwargs) -> MapEntity:
    d = dict(
        kind="enemy",
        family="Garcia",
        symbol="G",
        color="#fff",
        label="Garcia",
        type_id=0x20,
        world_x=100,
        world_y=64,
        world_z=0,
        map_x=100.0,
        map_y=64.0,
        health=10,
        slot="E0",
        combat_phase=CombatPhase.NORMAL,
    )
    d.update(kwargs)
    if "map_x" in kwargs and "world_x" not in kwargs:
        d["world_x"] = int(kwargs["map_x"])
    return MapEntity(**d)  # type: ignore[arg-type]


class ScreenAndBandTests(unittest.TestCase):
    def test_off_screen_not_selected(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, type_id=1)
        far = _e(map_x=500, label="Off", slot="E0")  # two screens ahead
        near = _e(map_x=140, label="On", slot="E1")
        choice = select_target(me, (far, near), PROFILES[0], my_seat=1)
        assert choice is not None
        self.assertEqual(choice.entity.label, "On")
        self.assertFalse(is_on_screen(far, soft=True))

    def test_jump_band(self) -> None:
        self.assertEqual(engagement_band(50, 4, PROFILES[0]), "jump")
        self.assertEqual(engagement_band(20, 4, PROFILES[0]), "close")
        self.assertEqual(engagement_band(120, 4, PROFILES[0]), "far")

    def test_attack_mix_jump_at_mid(self) -> None:
        plan = plan_for(_e())
        self.assertEqual(
            attack_mix(
                plan, PROFILES[0], tick=0, in_range=False, crowd=1, band="jump"
            ),
            "jump",
        )

    def test_attack_mix_rear_when_behind(self) -> None:
        plan = plan_for(_e())
        self.assertEqual(
            attack_mix(
                plan,
                PROFILES[0],
                tick=0,
                in_range=True,
                crowd=1,
                band="close",
                behind=True,
            ),
            "rear",
        )

    def test_closest_behind(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, type_id=1)
        back = _e(map_x=70, label="Back", slot="E0")
        front = _e(map_x=130, label="Front", slot="E1")
        # Facing right → behind is left.
        hit = closest_behind(me, (back, front), face_right=True)
        assert hit is not None
        self.assertEqual(hit.label, "Back")


class PolicyAggressionTests(unittest.TestCase):
    def _snap(self, entities: tuple[MapEntity, ...]):
        from dataclasses import replace

        def put_u8(b: bytearray, o: int, v: int) -> None:
            b[o] = v & 0xFF

        def put_u16(b: bytearray, o: int, v: int) -> None:
            b[o : o + 2] = (v & 0xFFFF).to_bytes(2, "big")

        g, t, o = bytearray(0x40), bytearray(4), bytearray(0x100)
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

    def test_jump_in_at_mid_range(self) -> None:
        p1 = _e(kind="player", family="Player", slot="P1", map_x=100, world_x=100, type_id=1, label="P1")
        foe = _e(map_x=100 + 50, world_x=150, label="Garcia")  # jump band
        snap = self._snap((p1, foe))
        d = decide_actions(snap, AgentConfig(p1_enabled=True), AgentState())
        # Jump+attack chord = B|C
        self.assertTrue(d.p1_mask & 0x20, msg=f"jump bit missing {d.p1_mask:#x} {d.p1_note}")
        self.assertTrue(d.p1_mask & 0x40 or d.p1_mask & 0x20)  # C jump
        self.assertIn("jump", d.p1_note)

    def test_rear_when_enemy_behind(self) -> None:
        p1 = _e(kind="player", family="Player", slot="P1", map_x=100, world_x=100, type_id=1, label="P1")
        # Progress is right by default; foe behind on the left.
        foe = _e(map_x=70, world_x=70, label="Backstab")
        snap = self._snap((p1, foe))
        mem = AgentState()
        # Pretend we were walking right.
        mem.p1_walk.active = True
        mem.p1_walk.dir_x = 1
        d = decide_actions(snap, AgentConfig(p1_enabled=True), mem)
        self.assertTrue(
            "rear" in d.p1_note or "back atk" in d.p1_note,
            d.p1_note,
        )
        # Rear = B|C
        self.assertEqual(d.p1_mask & 0x60, 0x60, msg=hex(d.p1_mask))


if __name__ == "__main__":
    unittest.main()
