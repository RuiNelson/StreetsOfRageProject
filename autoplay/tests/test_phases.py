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
    player_phase,
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
    # +$30 is the high byte of the combined state/flags word.
    if "primary_state" in kwargs and "action_state" not in kwargs:
        defaults["action_state"] = (kwargs["primary_state"] >> 8) & 0xFF
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

    def test_round1_garcia_attack_states(self) -> None:
        self.assertEqual(
            ordinary_enemy_phase(0x0901, type_id=0x22), CombatPhase.CHARGE
        )
        self.assertEqual(
            ordinary_enemy_phase(0x0A01, type_id=0x22), CombatPhase.ATTACKING
        )
        self.assertEqual(
            ordinary_enemy_phase(0x0B09, type_id=0x22), CombatPhase.ATTACKING
        )
        self.assertEqual(
            ordinary_enemy_phase(0x1101, type_id=0x22), CombatPhase.ATTACKING
        )
        self.assertEqual(
            ordinary_enemy_phase(0x1301, type_id=0x22), CombatPhase.ATTACKING
        )

    def test_signal_attack_family_states(self) -> None:
        self.assertEqual(
            ordinary_enemy_phase(0x0801, type_id=0x24), CombatPhase.CHARGE
        )
        self.assertEqual(
            ordinary_enemy_phase(0x0A01, type_id=0x24), CombatPhase.ATTACKING
        )
        self.assertEqual(
            ordinary_enemy_phase(0x0D01, type_id=0x24), CombatPhase.RECOVERY
        )

    def test_common_state_two_is_contact_recovery(self) -> None:
        self.assertEqual(ordinary_enemy_phase(0x0203), CombatPhase.RECOVERY)

    def test_abadede_police_recovery(self) -> None:
        self.assertEqual(
            boss_phase(type_id=0x30, primary_byte=0x06, tactical=0),
            CombatPhase.RECOVERY,
        )

    def test_later_boss_tactical_charge(self) -> None:
        # Primary $01 (state 1, active combat) is where tactical $08 (the
        # boomerang wind-up/throw commit, asm $16E88) actually coexists with
        # a live boss in the ROM; state 2 clears tactical to 0 before it is
        # ever entered, so primary $02 is covered by its own dedicated rule
        # below instead (test_antonio_state2_is_always_attacking).
        self.assertEqual(
            boss_phase(type_id=0x56, primary_byte=0x01, tactical=0x08),
            CombatPhase.CHARGE,
        )

    def test_antonio_state2_is_always_attacking(self) -> None:
        """$171CC (antonio_state2_close_strike, asm $16F0E): a short committed
        action entered from state 1 on a target proximity/velocity/facing
        gate, not a pure distance check. Tactical is cleared to 0 on entry,
        so without a type-specific rule this decodes as NORMAL — a real blind
        spot, since a zero target X-velocity is one of the entry paths and
        matches the player's own signature while throwing a ground combo."""

        self.assertEqual(
            boss_phase(type_id=0x56, primary_byte=0x02, tactical=0x00),
            CombatPhase.ATTACKING,
        )
        # Souther's own primary $02 special case must stay unaffected.
        self.assertEqual(
            boss_phase(type_id=0x55, primary_byte=0x02, tactical=0x00),
            CombatPhase.ATTACKING,
        )

    def test_target_seat(self) -> None:
        self.assertEqual(decode_target_seat(0xB800), 1)
        self.assertEqual(decode_target_seat(0xB880), 2)
        self.assertIsNone(decode_target_seat(0xB900))

    def test_enemy_held_player_actions_have_a_distinct_phase(self) -> None:
        for action in range(0x78, 0x80):
            with self.subTest(action=action):
                self.assertEqual(
                    player_phase(action_byte=action, held_type=0),
                    CombatPhase.HELD_BY_ENEMY,
                )

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

    def test_active_attacker_beats_blocked_target_in_another_lane(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            map_y=64,
            type_id=1,
        )
        blocked = _e(
            map_x=54,
            map_y=94,
            slot="E0",
            combat_phase=CombatPhase.BLOCKED,
            label="Blocked",
        )
        attacker = _e(
            map_x=141,
            map_y=89,
            slot="E1",
            type_id=0x22,
            combat_phase=CombatPhase.CHARGE,
            target_ptr=0xB800,
            label="Attacker",
        )
        choice = select_target(me, (blocked, attacker), PROFILES[0], my_seat=1)
        assert choice is not None
        self.assertEqual(choice.entity.label, "Attacker")

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

    def test_zero_health_attacker_remains_a_target_until_attack_ends(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, map_y=64, type_id=1)
        active = _e(
            map_x=135,
            map_y=64,
            primary_state=0x0B00,
            combat_phase=CombatPhase.ATTACKING,
            health=0,
            type_id=0x22,
            label="Active at zero HP",
        )
        choice = select_target(me, (active,), PROFILES[0], my_seat=1)
        assert choice is not None
        self.assertEqual(choice.entity.label, "Active at zero HP")

    def test_zero_health_normal_enemy_remains_a_target_for_finishing_hit(self) -> None:
        me = _e(kind="player", family="Player", slot="P1", map_x=100, map_y=64, type_id=1)
        zero = _e(
            map_x=135,
            map_y=64,
            primary_state=0x0100,
            combat_phase=CombatPhase.NORMAL,
            health=0,
            type_id=0x22,
            label="Needs lethal underflow",
        )
        choice = select_target(me, (zero,), PROFILES[0], my_seat=1)
        assert choice is not None
        self.assertEqual(choice.entity.label, "Needs lethal underflow")

    def test_signed_negative_health_is_never_revived_by_stale_attack_state(self) -> None:
        me = _e(
            kind="player",
            family="Player",
            slot="P1",
            map_x=100,
            map_y=64,
            type_id=1,
        )
        corpse = _e(
            map_x=120,
            map_y=64,
            slot="E0",
            primary_state=0x0B00,
            combat_phase=CombatPhase.ATTACKING,
            health=0xFFFF,
            type_id=0x22,
            label="Stale attacking corpse",
        )
        live = _e(map_x=180, map_y=64, slot="E1", label="Live")
        choice = select_target(me, (corpse, live), PROFILES[0], my_seat=1)
        assert choice is not None
        self.assertEqual(choice.entity.label, "Live")
        self.assertTrue(corpse.is_defeated)
        self.assertEqual(corpse.phase_tag, "die")

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
