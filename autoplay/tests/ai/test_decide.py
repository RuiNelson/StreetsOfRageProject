import unittest

from sor_autoplay.ai.attack_decisions import Attack, Punch
from sor_autoplay.ai.character import Myself, Partner
from sor_autoplay.ai.decide import (
    generate_decision_tokens,
    should_call_police,
    should_punch,
    should_sidestep,
    should_walk_to_near_enemy,
)
from sor_autoplay.ai.enemy import Enemy
from sor_autoplay.ai.essential import AnimationInProgress
from sor_autoplay.ai.hazard_tokens import DangerZone
from sor_autoplay.ai.police_decision import CallPolice
from sor_autoplay.ai.tokens import Decision, Token
from sor_autoplay.ai.walk_decisions import Sidestep, Walk, WalkToNearEnemy
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


class DecisionDataclassContractTests(unittest.TestCase):
    def test_decision_class_hierarchy(self) -> None:
        self.assertTrue(issubclass(Walk, Decision))
        self.assertTrue(issubclass(Attack, Decision))
        self.assertTrue(issubclass(CallPolice, Decision))
        self.assertTrue(issubclass(WalkToNearEnemy, Walk))
        self.assertTrue(issubclass(Sidestep, Walk))
        self.assertTrue(issubclass(Punch, Attack))

    def test_priority_defaults(self) -> None:
        self.assertEqual(Punch(actor_slot="P1", target_slot="obj01").priority, 10)
        self.assertEqual(WalkToNearEnemy(actor_slot="P1", target_slot="obj01").priority, 20)
        self.assertEqual(Sidestep(actor_slot="P1", threat_slot="obj01", direction="up").priority, 30)
        self.assertEqual(CallPolice(actor_slot="P1").priority, 0)


class ShouldPunchTests(unittest.TestCase):
    def test_fires_within_range(self) -> None:
        myself = make_myself()
        enemy = make_enemy(world_x=110, world_y=105)
        context: set[Token] = {myself, enemy}

        result = should_punch(context)

        self.assertEqual(result, {Punch(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_out_of_range(self) -> None:
        myself = make_myself()
        enemy = make_enemy(world_x=200, world_y=200)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_punch(context), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself = make_myself()
        enemy = make_enemy(world_x=110, world_y=105)
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}

        self.assertEqual(should_punch(context), set())

    def test_ignores_enemies_that_should_be_ignored_as_target(self) -> None:
        myself = make_myself()
        enemy = make_enemy(world_x=110, world_y=105, combat_phase=CombatPhase.DEATH)
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_punch(context), set())

    def test_fires_for_partner_too(self) -> None:
        partner = Partner(
            slot="P2",
            player_index=2,
            character_id=1,
            character_name="Blaze",
            world_x=300,
            world_y=300,
            health=100,
            health_percent=100.0,
            lives=3,
            specials=1,
            held_weapon_type=0,
            facing_left=False,
            combat_phase=CombatPhase.NORMAL,
        )
        enemy = make_enemy(slot="obj02", world_x=305, world_y=302)
        context: set[Token] = {partner, enemy}

        result = should_punch(context)

        self.assertEqual(result, {Punch(actor_slot="P2", target_slot="obj02")})


class ShouldWalkToNearEnemyTests(unittest.TestCase):
    def test_picks_the_nearest_enemy(self) -> None:
        myself = make_myself(world_x=0, world_y=0)
        near = make_enemy(slot="near", world_x=10, world_y=10)
        far = make_enemy(slot="far", world_x=500, world_y=500)
        context: set[Token] = {myself, near, far}

        result = should_walk_to_near_enemy(context)

        self.assertEqual(result, {WalkToNearEnemy(actor_slot="P1", target_slot="near")})

    def test_no_enemies_no_decision(self) -> None:
        myself = make_myself()
        self.assertEqual(should_walk_to_near_enemy({myself}), set())

    def test_no_decision_when_animation_in_progress(self) -> None:
        myself = make_myself()
        enemy = make_enemy()
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}
        self.assertEqual(should_walk_to_near_enemy(context), set())


class ShouldSidestepTests(unittest.TestCase):
    def test_fires_for_confirmed_dangerous_enemy(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(
            world_x=110,
            world_y=120,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
        )
        context: set[Token] = {myself, enemy}

        result = should_sidestep(context)

        self.assertEqual(
            result,
            {Sidestep(actor_slot="P1", threat_slot="obj01", direction="up")},
        )

    def test_fires_for_close_facing_unknown_phase_enemy(self) -> None:
        # The caution rule: CombatPhase.UNKNOWN on a nearby, player-facing
        # enemy must be treated as "insufficient information," not "safe."
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(
            world_x=130,
            world_y=90,
            combat_phase=CombatPhase.UNKNOWN,
            targets_player=1,
            facing_left=True,  # facing left, myself is to its left -> facing myself
        )
        context: set[Token] = {myself, enemy}

        result = should_sidestep(context)

        self.assertEqual(
            result,
            {Sidestep(actor_slot="P1", threat_slot="obj01", direction="down")},
        )

    def test_does_not_fire_for_far_away_enemy(self) -> None:
        # Not is_dangerous and too far away for the UNKNOWN-caution rule to
        # apply either.
        myself = make_myself(world_x=0, world_y=0)
        enemy = make_enemy(
            world_x=500,
            world_y=500,
            combat_phase=CombatPhase.UNKNOWN,
            targets_player=1,
            facing_left=True,
        )
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_sidestep(context), set())

    def test_does_not_fire_for_non_targeting_enemy(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(
            world_x=105,
            world_y=105,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=2,
        )
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_sidestep(context), set())

    def test_does_not_fire_for_unknown_phase_when_not_facing(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(
            world_x=130,
            world_y=90,
            combat_phase=CombatPhase.UNKNOWN,
            targets_player=1,
            facing_left=False,  # facing away from myself
        )
        context: set[Token] = {myself, enemy}

        self.assertEqual(should_sidestep(context), set())


class ShouldCallPoliceTests(unittest.TestCase):
    def test_fires_when_danger_zone_threat_at_least_three(self) -> None:
        myself = make_myself(specials=1, health_percent=100.0)
        danger = DangerZone(slot="P1", left=0, right=1, top=0, bottom=1, threat_level=3)
        context: set[Token] = {myself, danger}

        self.assertEqual(should_call_police(context), {CallPolice(actor_slot="P1")})

    def test_fires_when_low_health_and_any_threat(self) -> None:
        myself = make_myself(specials=1, health_percent=10.0)
        danger = DangerZone(slot="P1", left=0, right=1, top=0, bottom=1, threat_level=1)
        context: set[Token] = {myself, danger}

        self.assertEqual(should_call_police(context), {CallPolice(actor_slot="P1")})

    def test_does_not_fire_below_thresholds(self) -> None:
        myself = make_myself(specials=1, health_percent=100.0)
        danger = DangerZone(slot="P1", left=0, right=1, top=0, bottom=1, threat_level=1)
        context: set[Token] = {myself, danger}

        self.assertEqual(should_call_police(context), set())

    def test_never_fires_with_zero_specials(self) -> None:
        myself = make_myself(specials=0, health_percent=1.0)
        danger = DangerZone(slot="P1", left=0, right=1, top=0, bottom=1, threat_level=10)
        context: set[Token] = {myself, danger}

        self.assertEqual(should_call_police(context), set())

    def test_no_danger_zone_means_no_signal(self) -> None:
        myself = make_myself(specials=1, health_percent=1.0)
        context: set[Token] = {myself}

        self.assertEqual(should_call_police(context), set())


class GenerateDecisionTokensTests(unittest.TestCase):
    def test_unions_all_candidates_into_context(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=110, world_y=105)
        context: set[Token] = {myself, enemy}

        result = generate_decision_tokens(context)

        self.assertIn(myself, result)
        self.assertIn(enemy, result)
        self.assertIn(Punch(actor_slot="P1", target_slot="obj01"), result)
        self.assertIn(WalkToNearEnemy(actor_slot="P1", target_slot="obj01"), result)

    def test_does_not_mutate_input_context(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=110, world_y=105)
        context: set[Token] = {myself, enemy}
        original = set(context)

        generate_decision_tokens(context)

        self.assertEqual(context, original)


if __name__ == "__main__":
    unittest.main()
