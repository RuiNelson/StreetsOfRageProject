import unittest

from sor_autoplay.ai.character import Character, Myself, Partner, PlayableCharacter
from sor_autoplay.ai.tokens import Information, Token
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


if __name__ == "__main__":
    unittest.main()
