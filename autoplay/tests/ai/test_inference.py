import unittest

from sor_autoplay.ai.character import Myself
from sor_autoplay.ai.enemy import Enemy
from sor_autoplay.ai.hazard_tokens import DangerZone, IncomingProjectile, Projectile
from sor_autoplay.ai.inference import (
    check_for_danger_zone,
    check_for_incoming_projectiles,
    generate_inference_tokens,
)
from sor_autoplay.ai.tokens import Token
from sor_autoplay.phases import CombatPhase


def make_myself(**overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=100,
        world_y=100,
        health=100,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=False,
        combat_phase=CombatPhase.NORMAL,
        action_state=0,
        is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


def make_enemy(**overrides) -> Enemy:
    fields = dict(
        slot="obj01",
        type_id=0x20,
        world_x=100,
        world_y=100,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
    )
    fields.update(overrides)
    return Enemy(**fields)


class CheckForIncomingProjectilesTests(unittest.TestCase):
    def test_promotes_every_projectile_one_to_one(self) -> None:
        p1 = Projectile(slot="obj10", world_x=10, world_y=20, vel_x=1.0, vel_z=-2.0)
        p2 = Projectile(slot="obj11", world_x=30, world_y=40, vel_x=-1.5, vel_z=0.5)
        context: set[Token] = {p1, p2}

        result = check_for_incoming_projectiles(context)

        self.assertEqual(
            result,
            {
                IncomingProjectile(slot="obj10", world_x=10, world_y=20, vel_x=1.0, vel_z=-2.0),
                IncomingProjectile(slot="obj11", world_x=30, world_y=40, vel_x=-1.5, vel_z=0.5),
            },
        )

    def test_no_projectiles_no_output(self) -> None:
        self.assertEqual(check_for_incoming_projectiles(set()), set())


class CheckForDangerZoneTests(unittest.TestCase):
    def test_threat_level_counts_targeting_enemies(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        e1 = make_enemy(slot="e1", world_x=90, world_y=100, targets_player=1, combat_phase=CombatPhase.NORMAL)
        e2 = make_enemy(slot="e2", world_x=120, world_y=100, targets_player=1, combat_phase=CombatPhase.ATTACKING)
        context: set[Token] = {myself, e1, e2}

        result = check_for_danger_zone(context)

        self.assertEqual(len(result), 1)
        zone = next(iter(result))
        self.assertIsInstance(zone, DangerZone)
        self.assertEqual(zone.slot, "P1")
        self.assertEqual(zone.threat_level, 2)

    def test_unknown_caution_bonus_adds_extra_threat(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        # Close, facing, UNKNOWN phase -> +1 bonus on top of the base count.
        e1 = make_enemy(
            slot="e1",
            world_x=110,
            world_y=100,
            targets_player=1,
            combat_phase=CombatPhase.UNKNOWN,
            facing_left=True,
        )
        context: set[Token] = {myself, e1}

        result = check_for_danger_zone(context)

        self.assertEqual(len(result), 1)
        zone = next(iter(result))
        self.assertEqual(zone.threat_level, 2)  # 1 base + 1 caution bonus

    def test_unknown_far_away_does_not_get_bonus(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        e1 = make_enemy(
            slot="e1",
            world_x=500,
            world_y=500,
            targets_player=1,
            combat_phase=CombatPhase.UNKNOWN,
            facing_left=True,
        )
        context: set[Token] = {myself, e1}

        result = check_for_danger_zone(context)

        zone = next(iter(result))
        self.assertEqual(zone.threat_level, 1)

    def test_no_targeting_enemies_emits_nothing(self) -> None:
        myself = make_myself()
        e1 = make_enemy(targets_player=2)
        context: set[Token] = {myself, e1}

        self.assertEqual(check_for_danger_zone(context), set())

    def test_no_myself_or_partner_emits_nothing(self) -> None:
        e1 = make_enemy(targets_player=1)
        self.assertEqual(check_for_danger_zone({e1}), set())

    def test_nearby_non_targeting_enemies_raise_threat_above_zero(self) -> None:
        # No enemy targets the player at all, but two are clustered nearby --
        # per AI.md, clustering alone (even before any attack) should still
        # be able to produce threat_level > 0.
        myself = make_myself(world_x=100, world_y=100)
        e1 = make_enemy(slot="e1", world_x=120, world_y=100, targets_player=None)
        e2 = make_enemy(slot="e2", world_x=140, world_y=100, targets_player=None)
        context: set[Token] = {myself, e1, e2}

        result = check_for_danger_zone(context)

        self.assertEqual(len(result), 1)
        zone = next(iter(result))
        self.assertEqual(zone.threat_level, 1)  # 2 nearby // 2 == 1

    def test_targeting_plus_nearby_beats_targeting_alone(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        e1 = make_enemy(slot="e1", world_x=105, world_y=100, targets_player=1, combat_phase=CombatPhase.NORMAL)
        context_targeting_only: set[Token] = {myself, e1}
        targeting_only_zone = next(iter(check_for_danger_zone(context_targeting_only)))

        e2 = make_enemy(slot="e2", world_x=150, world_y=100, targets_player=None, combat_phase=CombatPhase.NORMAL)
        e3 = make_enemy(slot="e3", world_x=160, world_y=100, targets_player=None, combat_phase=CombatPhase.NORMAL)
        context_with_cluster: set[Token] = {myself, e1, e2, e3}
        clustered_zone = next(iter(check_for_danger_zone(context_with_cluster)))

        self.assertGreater(clustered_zone.threat_level, targeting_only_zone.threat_level)

    def test_nearby_enemy_already_counted_as_targeting_is_not_double_counted(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        e1 = make_enemy(slot="e1", world_x=105, world_y=100, targets_player=1, combat_phase=CombatPhase.NORMAL)
        context: set[Token] = {myself, e1}

        zone = next(iter(check_for_danger_zone(context)))

        self.assertEqual(zone.threat_level, 1)


class GenerateInferenceTokensTests(unittest.TestCase):
    def test_unions_context_with_both_checks(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=105, world_y=100, targets_player=1)
        projectile = Projectile(slot="obj10", world_x=1, world_y=2, vel_x=0.0, vel_z=0.0)
        context: set[Token] = {myself, enemy, projectile}

        result = generate_inference_tokens(context)

        self.assertIn(myself, result)
        self.assertIn(enemy, result)
        self.assertIn(projectile, result)
        self.assertTrue(any(isinstance(t, IncomingProjectile) for t in result))
        self.assertTrue(any(isinstance(t, DangerZone) for t in result))

    def test_does_not_mutate_input_context(self) -> None:
        myself = make_myself()
        context: set[Token] = {myself}
        original = set(context)

        generate_inference_tokens(context)

        self.assertEqual(context, original)


if __name__ == "__main__":
    unittest.main()
