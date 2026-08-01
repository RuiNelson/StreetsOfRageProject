"""Tests for combat phase decoding and phase-aware agent behaviour."""

from __future__ import annotations

import unittest

from sor_autoplay.agent.combat import select_target
from sor_autoplay.agent.characters import PROFILES
from sor_autoplay.agent.enemies import attack_mix
from sor_autoplay.agent.policy import AgentConfig, decide_actions
from sor_autoplay.memory_map import (
    ENEMY_ST_BLOCKED,
    ENEMY_ST_DEATH,
    ENEMY_ST_GRABBED,
    ENEMY_ST_KNOCKDOWN,
    ENEMY_ST_NORMAL,
)
from sor_autoplay.phases import (
    CombatPhase,
    boss_phase,
    decode_target_seat,
    ordinary_enemy_phase,
    should_ignore_as_target,
)
from sor_autoplay.world_map import MapEntity, WorldMap


def _e(**kwargs) -> MapEntity:
    defaults = dict(
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
        primary_state=ENEMY_ST_NORMAL,
        combat_phase=CombatPhase.NORMAL,
    )
    defaults.update(kwargs)
    # Keep action_state low byte in sync with primary_state when set.
    if "primary_state" in kwargs and "action_state" not in kwargs:
        defaults["action_state"] = kwargs["primary_state"] & 0xFF
    if "combat_phase" not in kwargs and "primary_state" in kwargs:
        defaults["combat_phase"] = ordinary_enemy_phase(kwargs["primary_state"])
    return MapEntity(**defaults)  # type: ignore[arg-type]


class PhaseDecodeTests(unittest.TestCase):
    def test_ordinary_states(self) -> None:
        self.assertEqual(ordinary_enemy_phase(ENEMY_ST_NORMAL), CombatPhase.NORMAL)
        self.assertEqual(ordinary_enemy_phase(ENEMY_ST_KNOCKDOWN), CombatPhase.KNOCKDOWN)
        self.assertEqual(ordinary_enemy_phase(ENEMY_ST_GRABBED), CombatPhase.GRABBED)
        self.assertEqual(ordinary_enemy_phase(ENEMY_ST_DEATH), CombatPhase.DEATH)
        self.assertEqual(ordinary_enemy_phase(ENEMY_ST_BLOCKED), CombatPhase.BLOCKED)

    def test_abadede_police_recovery(self) -> None:
        self.assertEqual(
            boss_phase(type_id=0x30, primary_byte=0x06, tactical=0),
            CombatPhase.RECOVERY,
        )

    def test_later_boss_tactical_charge(self) -> None:
        self.assertEqual(
            boss_phase(type_id=0x56, primary_byte=0x02, tactical=0x08),
            CombatPhase.CHARGE,
        )

    def test_target_seat(self) -> None:
        self.assertEqual(decode_target_seat(0xB800), 1)
        self.assertEqual(decode_target_seat(0xB880), 2)
        self.assertIsNone(decode_target_seat(0xB900))

    def test_ignore_death(self) -> None:
        self.assertTrue(should_ignore_as_target(CombatPhase.DEATH))
        self.assertFalse(should_ignore_as_target(CombatPhase.KNOCKDOWN))


class PhaseAwareCombatTests(unittest.TestCase):
    def test_prefer_knockdown_over_normal(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, map_y=64, type_id=1)
        downed = _e(
            map_x=160,
            map_y=64,
            slot="E0",
            primary_state=ENEMY_ST_KNOCKDOWN,
            combat_phase=CombatPhase.KNOCKDOWN,
            label="Downed",
        )
        near = _e(
            map_x=120,
            map_y=64,
            slot="E1",
            primary_state=ENEMY_ST_NORMAL,
            combat_phase=CombatPhase.NORMAL,
            label="Near",
        )
        choice = select_target(me, (near, downed), PROFILES[0], my_seat=1)
        assert choice is not None
        self.assertEqual(choice.entity.label, "Downed")

    def test_prefer_hunter_targeting_me(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, map_y=64, type_id=1)
        hunter = _e(
            map_x=150,
            map_y=64,
            slot="E0",
            target_ptr=0xB800,
            label="Hunter",
        )
        other = _e(
            map_x=140,
            map_y=64,
            slot="E1",
            target_ptr=0xB880,
            label="Other",
        )
        choice = select_target(me, (other, hunter), PROFILES[0], my_seat=1)
        assert choice is not None
        self.assertEqual(choice.entity.label, "Hunter")

    def test_ignore_dead_targets(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, map_y=64, type_id=1)
        dead = _e(
            map_x=110,
            map_y=64,
            primary_state=ENEMY_ST_DEATH,
            combat_phase=CombatPhase.DEATH,
            health=0,
        )
        live = _e(map_x=180, map_y=64, slot="E1", label="Live")
        choice = select_target(me, (dead, live), PROFILES[0], my_seat=1)
        assert choice is not None
        self.assertEqual(choice.entity.label, "Live")

    def test_punish_mix_is_punch(self) -> None:
        from sor_autoplay.agent.enemies import plan_for

        plan = plan_for(_e())
        self.assertEqual(
            attack_mix(
                plan, PROFILES[0], tick=0, in_range=True, crowd=1, phase_name="knockdown"
            ),
            "punch",
        )
        # No jump on knockdown even for Adam.
        mixes = {
            attack_mix(
                plan, PROFILES[1], tick=t, in_range=True, crowd=1, phase_name="knockdown"
            )
            for t in range(30)
        }
        self.assertEqual(mixes, {"punch"})

    def test_policy_punishes_knockdown(self) -> None:
        from dataclasses import replace

        from sor_autoplay.memory_map import (
            MAX_HEALTH,
            OBJ_CHARACTER_ID,
            OBJ_HEALTH,
            OBJ_POS_X,
            OBJ_POS_Y,
            OBJ_TYPE,
        )
        from sor_autoplay.state import snapshot_from_memory_blocks

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
        p1 = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            map_y=64,
            type_id=1,
            label="P1",
        )
        foe = _e(
            map_x=118,
            map_y=64,
            primary_state=ENEMY_ST_KNOCKDOWN,
            combat_phase=CombatPhase.KNOCKDOWN,
            label="Garcia",
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
            entities=(p1, foe),
        )
        snap = replace(snap, world_map=world)
        decision = decide_actions(snap, AgentConfig(p1_enabled=True))
        self.assertIn("punish", decision.p1_note)


if __name__ == "__main__":
    unittest.main()
