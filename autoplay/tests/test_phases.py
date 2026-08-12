"""Tests for combat phase decoding used by the observer HUD and map."""

from __future__ import annotations

import unittest

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
from sor_autoplay.world_map import MapEntity


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

    def test_nora_whip_engage_and_special_are_attacking(self) -> None:
        # $08 (whip engage/swing, $F1B0) and $0A (shared "damaging special"
        # entry $DDE6, the same address already ATTACKING for Garcia $22's
        # own state $13) and $15 (the scripted lunge $F6BC).
        self.assertEqual(ordinary_enemy_phase(0x0801, type_id=0x26), CombatPhase.ATTACKING)
        self.assertEqual(ordinary_enemy_phase(0x0A01, type_id=0x26), CombatPhase.ATTACKING)
        self.assertEqual(ordinary_enemy_phase(0x1501, type_id=0x26), CombatPhase.ATTACKING)

    def test_nora_lunge_windup_is_charge(self) -> None:
        self.assertEqual(ordinary_enemy_phase(0x1301, type_id=0x26), CombatPhase.CHARGE)
        self.assertEqual(ordinary_enemy_phase(0x1401, type_id=0x26), CombatPhase.CHARGE)

    def test_nora_post_hit_recovery_is_stunned(self) -> None:
        # $0B/$0C/$0F all route through her own +$50 countdown ($9B36/$F078),
        # distinct from the generic $0200 hitstun state, which every ordinary
        # type (Nora included) already reads STUNNED via the hi-byte check.
        self.assertEqual(ordinary_enemy_phase(0x0B01, type_id=0x26), CombatPhase.STUNNED)
        self.assertEqual(ordinary_enemy_phase(0x0C01, type_id=0x26), CombatPhase.STUNNED)
        self.assertEqual(ordinary_enemy_phase(0x0F01, type_id=0x26), CombatPhase.STUNNED)

    def test_nora_state_ten_knockdown_and_twelve_blocked(self) -> None:
        # $10 ($F2AC) jumps straight into ordinary_enemy_begin_knockdown;
        # $12 ($F2BC) delegates every tick to the same $DBCC handler state
        # $07 (BLOCKED) already shares across every type.
        self.assertEqual(ordinary_enemy_phase(0x1001, type_id=0x26), CombatPhase.KNOCKDOWN)
        self.assertEqual(ordinary_enemy_phase(0x1201, type_id=0x26), CombatPhase.BLOCKED)

    def test_nora_normal_states_still_default_normal(self) -> None:
        # $09 (chase/approach, $F0FC) has no Nora-specific override and must
        # keep falling back to NORMAL rather than picking up a stray mapping.
        self.assertEqual(ordinary_enemy_phase(0x0901, type_id=0x26), CombatPhase.NORMAL)

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

    def test_common_state_two_is_hitstun(self) -> None:
        # $0200's own handler is $9B88, which does nothing but count the
        # stun timer +$50 down and write $0100 back at zero.
        self.assertEqual(ordinary_enemy_phase(0x0203), CombatPhase.STUNNED)

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

    def test_signed_negative_health_marks_defeated_entity(self) -> None:
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
        self.assertTrue(corpse.is_defeated)
        self.assertEqual(corpse.phase_tag, "die")


if __name__ == "__main__":
    unittest.main()
