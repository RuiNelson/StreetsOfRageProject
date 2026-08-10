import unittest

from sor_autoplay.ai.tokens import Character, Myself, Partner, PlayableCharacter
from sor_autoplay.ai.tokens import Information, Token
from sor_autoplay.ai.tokens import (
    punch_outer_x,
    rear_attack_behind_max_x,
    rear_attack_front_max_x,
)
from sor_autoplay.phases import CombatPhase


def _myself(**overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=800,
        world_y=64,
        health=50,
        health_percent=100.0,
        lives=3,
        specials=2,
        held_weapon_type=0,
        facing_left=False,
        combat_phase=CombatPhase.NORMAL,
        action_state=0,
        is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


class CharacterHierarchyTests(unittest.TestCase):
    def test_class_hierarchy(self) -> None:
        self.assertTrue(issubclass(Character, Information))
        self.assertTrue(issubclass(Character, Token))
        self.assertTrue(issubclass(PlayableCharacter, Character))
        self.assertTrue(issubclass(Myself, PlayableCharacter))
        self.assertTrue(issubclass(Partner, PlayableCharacter))

    def test_myself_and_partner_are_distinct_types(self) -> None:
        self.assertFalse(issubclass(Myself, Partner))
        self.assertFalse(issubclass(Partner, Myself))

    def test_myself_fields_round_trip(self) -> None:
        me = _myself()
        self.assertEqual(me.slot, "P1")
        self.assertEqual(me.player_index, 1)
        self.assertEqual(me.character_id, 0)
        self.assertEqual(me.character_name, "Axel")
        self.assertEqual(me.world_x, 800)
        self.assertEqual(me.world_y, 64)
        self.assertEqual(me.health, 50)
        self.assertEqual(me.health_percent, 100.0)
        self.assertEqual(me.lives, 3)
        self.assertEqual(me.specials, 2)
        self.assertEqual(me.held_weapon_type, 0)
        self.assertFalse(me.facing_left)
        self.assertEqual(me.combat_phase, CombatPhase.NORMAL)
        self.assertEqual(me.action_state, 0)
        self.assertFalse(me.is_airborne)

    def test_partner_accepts_same_shape(self) -> None:
        partner = Partner(
            slot="P2",
            player_index=2,
            character_id=2,
            character_name="Blaze",
            world_x=820,
            world_y=64,
            health=40,
            health_percent=80.0,
            lives=2,
            specials=1,
            held_weapon_type=0x0A,
            facing_left=True,
            combat_phase=CombatPhase.HOLDING,
            action_state=0x66,
            is_airborne=True,
        )
        self.assertEqual(partner.character_name, "Blaze")
        self.assertEqual(partner.held_weapon_type, 0x0A)
        self.assertTrue(partner.facing_left)
        self.assertEqual(partner.action_state, 0x66)
        self.assertTrue(partner.is_airborne)

    def test_frozen_and_hashable(self) -> None:
        me = _myself()
        with self.assertRaises(Exception):
            me.health = 1  # type: ignore[misc]
        context = {me}
        self.assertIn(me, context)

    def test_priority_defaults_to_zero(self) -> None:
        self.assertEqual(_myself().priority, 0)


class PunchOuterXWeaponAwareTests(unittest.TestCase):
    def test_unarmed_uses_per_character_table(self) -> None:
        self.assertEqual(punch_outer_x(0), 50)  # Axel
        self.assertEqual(punch_outer_x(1), 48)  # Adam
        self.assertEqual(punch_outer_x(2), 60)  # Blaze

    def test_bat_or_pipe_shrinks_reach_to_measured_36px_for_every_character(self) -> None:
        for character_id in (0, 1, 2):
            self.assertEqual(punch_outer_x(character_id, held_weapon_type=0x0A), 36)
            self.assertEqual(punch_outer_x(character_id, held_weapon_type=0x0B), 36)

    def test_other_held_types_do_not_shrink_reach(self) -> None:
        # Knife (0x08) and unarmed grab-slot values are unaffected.
        self.assertEqual(punch_outer_x(0, held_weapon_type=0x08), 50)


class RearAttackBoxTests(unittest.TestCase):
    def test_behind_max_matches_measured_per_character_box(self) -> None:
        self.assertEqual(rear_attack_behind_max_x(0), 40)  # Axel
        self.assertEqual(rear_attack_behind_max_x(1), 42)  # Adam
        self.assertEqual(rear_attack_behind_max_x(2), 53)  # Blaze

    def test_only_adam_reaches_forward(self) -> None:
        self.assertEqual(rear_attack_front_max_x(0), 0)  # Axel: pure backfist
        self.assertEqual(rear_attack_front_max_x(1), 14)  # Adam: forward hop
        self.assertEqual(rear_attack_front_max_x(2), 0)  # Blaze: pure backfist


class ThrowTechReadyTests(unittest.TestCase):
    def test_true_when_armed_on_a_techable_action(self) -> None:
        # $5C, $72, $88 are the techable free-flight families; facing bit
        # (bit 0) must not matter.
        for action_state in (0x5C, 0x5D, 0x72, 0x73, 0x88, 0x89):
            me = _myself(action_state=action_state, tech_armed=1)
            self.assertTrue(me.throw_tech_ready, msg=hex(action_state))

    def test_false_when_not_armed(self) -> None:
        me = _myself(action_state=0x72, tech_armed=0)
        self.assertFalse(me.throw_tech_ready)

    def test_false_on_an_ordinary_street_throw_even_if_armed_field_nonzero(self) -> None:
        # $72 IS techable, but per controls-and-input.md the ordinary street
        # throw path never actually sets +$45 -- this only checks that the
        # property still correctly gates on the field regardless, since a
        # non-techable action must never read as ready even if tech_armed
        # were somehow nonzero (defensive: e.g. $02 idle).
        me = _myself(action_state=0x02, tech_armed=1)
        self.assertFalse(me.throw_tech_ready)

    def test_defaults_to_not_armed(self) -> None:
        me = _myself(action_state=0x72)
        self.assertFalse(me.throw_tech_ready)


if __name__ == "__main__":
    unittest.main()
