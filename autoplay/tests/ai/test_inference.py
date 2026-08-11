import unittest

from sor_autoplay.ai.tokens import Myself
from sor_autoplay.ai.tokens import Abadede, ClosingEnemy, Enemy, Garcia, Nora
from sor_autoplay.ai.tokens import (
    ActionableTarget,
    GrabToClearRear,
    GrabToNeutralizeWhip,
    InGrabReach,
    InJumpAttackReach,
    InPunchReach,
    InRearReach,
    IncomingMelee,
    PunishWindow,
    Surrounded,
)
from sor_autoplay.ai.tokens import CameraRange, Pit, SafeSpot
from sor_autoplay.ai.tokens import IncomingProjectile, Projectile
from sor_autoplay.ai.tokens import Weapon, WeaponUpgrade
from sor_autoplay.ai.inference import (
    check_for_closing_enemies,
    check_for_grab_opportunities,
    check_for_incoming_melee,
    check_for_incoming_projectiles,
    check_for_punish_windows,
    check_for_safe_spots,
    check_for_surrounded,
    check_for_targets_in_reach,
    check_for_weapon_upgrades,
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


def make_garcia(**overrides) -> Garcia:
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
    return Garcia(**fields)


def make_nora(**overrides) -> Nora:
    fields = dict(
        slot="obj02",
        type_id=0x26,
        world_x=100,
        world_y=100,
        health=11,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
    )
    fields.update(overrides)
    return Nora(**fields)


class CheckForIncomingProjectilesTests(unittest.TestCase):
    def test_promotes_only_projectiles_heading_toward_a_player(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        # Closing from the right.
        threat = Projectile(slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0)
        # Flying away / irrelevant lane.
        benign = Projectile(slot="obj11", world_x=30, world_y=200, vel_x=-1.5, vel_z=0.5)
        context: set[Token] = {myself, threat, benign}

        result = check_for_incoming_projectiles(context)

        self.assertEqual(
            result,
            {
                IncomingProjectile(
                    slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0
                ),
            },
        )

    def test_no_projectiles_no_output(self) -> None:
        self.assertEqual(check_for_incoming_projectiles(set()), set())

    def test_no_actors_no_output(self) -> None:
        p = Projectile(slot="obj10", world_x=10, world_y=20, vel_x=1.0, vel_z=0.0)
        self.assertEqual(check_for_incoming_projectiles({p}), set())


class CheckForClosingEnemiesTests(unittest.TestCase):
    def test_promotes_a_grunt_closing_diagonally_beyond_the_rear_band(self) -> None:
        # Axel (character_id=0), facing right: rear-attack *behind* band is
        # 40px, so the closing enemy must be behind (world_x < actor's).
        myself = make_myself(character_id=0, world_x=100, world_y=100, facing_left=False)
        garcia = make_garcia(
            slot="obj20", world_x=40, world_y=110, grunt_vel_x=10.0, grunt_vel_y=-2.0
        )
        context: set[Token] = {myself, garcia}

        result = check_for_closing_enemies(context)

        self.assertEqual(result, {ClosingEnemy(slot="obj20")})

    def test_no_promotion_when_closing_from_the_front(self) -> None:
        # Regression: Axel/Blaze have zero forward RearAttack reach, so an
        # enemy closing in from the front must never be promoted for them,
        # even though the same distance/speed would qualify from behind.
        myself = make_myself(character_id=0, world_x=100, world_y=100, facing_left=False)
        garcia = make_garcia(
            slot="obj20", world_x=160, world_y=100, grunt_vel_x=-10.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), set())

    def test_promotes_from_the_front_for_adams_forward_reaching_hop(self) -> None:
        # Adam (character_id=1) is the one character whose RearAttack chord
        # also reaches forward (14px) -- the front case must still work for him.
        myself = make_myself(character_id=1, world_x=100, world_y=100, facing_left=False)
        garcia = make_garcia(
            slot="obj20", world_x=160, world_y=100, grunt_vel_x=-10.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), {ClosingEnemy(slot="obj20")})

    def test_no_promotion_when_heading_away(self) -> None:
        myself = make_myself(character_id=0, world_x=100, world_y=100, facing_left=False)
        garcia = make_garcia(
            slot="obj20", world_x=40, world_y=110, grunt_vel_x=-10.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), set())

    def test_no_promotion_for_a_stationary_grunt(self) -> None:
        myself = make_myself(character_id=0, world_x=100, world_y=100, facing_left=False)
        garcia = make_garcia(slot="obj20", world_x=40, world_y=110)
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), set())

    def test_no_promotion_when_already_inside_the_rear_band(self) -> None:
        # decide._in_rear_band already covers this tick without early warning.
        myself = make_myself(character_id=0, world_x=100, world_y=100, facing_left=False)
        garcia = make_garcia(
            slot="obj20", world_x=70, world_y=100, grunt_vel_x=10.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), set())

    def test_no_promotion_when_too_far_off_lane(self) -> None:
        myself = make_myself(character_id=0, world_x=100, world_y=100, facing_left=False)
        garcia = make_garcia(
            slot="obj20", world_x=40, world_y=300, grunt_vel_x=10.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), set())

    def test_no_promotion_when_too_many_ticks_away(self) -> None:
        myself = make_myself(character_id=0, world_x=100, world_y=100, facing_left=False)
        garcia = make_garcia(
            slot="obj20", world_x=-100, world_y=110, grunt_vel_x=1.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        self.assertEqual(check_for_closing_enemies(context), set())

    def test_no_actors_no_output(self) -> None:
        garcia = make_garcia(slot="obj20", world_x=40, world_y=110, grunt_vel_x=10.0)
        self.assertEqual(check_for_closing_enemies({garcia}), set())


class CheckForTargetsInReachTests(unittest.TestCase):
    """Axel (character_id 0): punch band 16..50, rear-behind band 40, jump
    kick 50..60 (controls-and-input.md)."""

    def test_enemy_in_front_inside_the_punch_band(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(slot="obj01", world_x=130, world_y=100)

        result = check_for_targets_in_reach({myself, enemy})

        self.assertIn(InPunchReach(actor_slot="P1", target_slot="obj01"), result)
        self.assertIn(ActionableTarget(actor_slot="P1", target_slot="obj01"), result)
        self.assertNotIn(InJumpAttackReach(actor_slot="P1", target_slot="obj01"), result)

    def test_enemy_behind_beyond_the_tolerance_is_not_punch_reach(self) -> None:
        # The raw band ignores facing; a forward strike cannot hit backwards.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(slot="obj01", world_x=70, world_y=100)

        result = check_for_targets_in_reach({myself, enemy})

        self.assertNotIn(InPunchReach(actor_slot="P1", target_slot="obj01"), result)
        self.assertIn(InRearReach(actor_slot="P1", target_slot="obj01"), result)

    def test_rear_band_alone_is_not_actionable(self) -> None:
        # A behind enemy the actor could simply turn toward: the chord is not
        # warranted (not boxed in, not inside the punch dead zone), so
        # could_walk_to_near_enemy must still be free to turn around.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(slot="obj01", world_x=70, world_y=100)

        result = check_for_targets_in_reach({myself, enemy})

        self.assertNotIn(ActionableTarget(actor_slot="P1", target_slot="obj01"), result)

    def test_jump_kick_gap(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(slot="obj01", world_x=155, world_y=100)

        result = check_for_targets_in_reach({myself, enemy})

        self.assertIn(InJumpAttackReach(actor_slot="P1", target_slot="obj01"), result)
        self.assertNotIn(InPunchReach(actor_slot="P1", target_slot="obj01"), result)

    def test_ignores_enemies_outside_the_playable_lane(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        unreachable = make_enemy(slot="obj01", world_x=130, world_y=400)

        self.assertEqual(check_for_targets_in_reach({myself, unreachable}), set())

    def test_enemy_in_front_within_close_combat_range_is_grab_reach(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(slot="obj01", world_x=130, world_y=100)

        result = check_for_targets_in_reach({myself, enemy})

        self.assertIn(InGrabReach(actor_slot="P1", target_slot="obj01"), result)

    def test_enemy_beyond_the_punch_outer_edge_is_not_grab_reach(self) -> None:
        # Axel's outer edge is 50px; the walk-in is only worth committing to
        # from inside close-combat range.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(slot="obj01", world_x=155, world_y=100)

        result = check_for_targets_in_reach({myself, enemy})

        self.assertNotIn(InGrabReach(actor_slot="P1", target_slot="obj01"), result)

    def test_enemy_off_lane_is_not_grab_reach_even_inside_punch_reach(self) -> None:
        # dy=11 still clears PUNCH_RANGE_Y (12) but not GRAB_RANGE_Y (10):
        # two bodies have to actually overlap for the contact test to fire.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(slot="obj01", world_x=130, world_y=111)

        result = check_for_targets_in_reach({myself, enemy})

        self.assertIn(InPunchReach(actor_slot="P1", target_slot="obj01"), result)
        self.assertNotIn(InGrabReach(actor_slot="P1", target_slot="obj01"), result)

    def test_enemy_behind_beyond_the_tolerance_is_not_grab_reach(self) -> None:
        # The ROM's contact test reads the actor's *attack* box, which points
        # forward -- a behind enemy is turned toward first, not walked into.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(slot="obj01", world_x=70, world_y=100)

        result = check_for_targets_in_reach({myself, enemy})

        self.assertNotIn(InGrabReach(actor_slot="P1", target_slot="obj01"), result)


class CheckForGrabOpportunitiesTests(unittest.TestCase):
    def test_promotes_the_front_enemy_when_another_is_at_the_actors_back(self) -> None:
        # Axel facing right: the enemy at x=60 is behind, inside
        # reach.rear_threats' box (56 x 24), so holding the one in front is
        # what turns the pincer into a backwards throw.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        front = make_garcia(slot="obj01", world_x=130, world_y=100)
        behind = make_garcia(slot="obj02", world_x=60, world_y=100)

        result = check_for_grab_opportunities({myself, front, behind})

        self.assertIn(GrabToClearRear(actor_slot="P1", target_slot="obj01"), result)

    def test_the_rear_enemy_alone_is_not_its_own_reason_to_be_grabbed(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        behind = make_garcia(slot="obj02", world_x=60, world_y=100)

        result = check_for_grab_opportunities({myself, behind})

        self.assertEqual(result, set())

    def test_no_opportunity_from_a_lone_enemy_in_front(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        front = make_garcia(slot="obj01", world_x=130, world_y=100)

        self.assertEqual(check_for_grab_opportunities({myself, front}), set())

    def test_promotes_nora_on_her_own(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        nora = make_nora(slot="obj02", world_x=130, world_y=100)

        result = check_for_grab_opportunities({myself, nora})

        self.assertEqual(result, {GrabToNeutralizeWhip(actor_slot="P1", target_slot="obj02")})

    def test_a_committed_enemy_is_not_grabbable(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        nora = make_nora(slot="obj02", world_x=130, world_y=100, combat_phase=CombatPhase.ATTACKING)

        self.assertEqual(check_for_grab_opportunities({myself, nora}), set())

    def test_a_knocked_down_enemy_is_not_grabbable(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        nora = make_nora(slot="obj02", world_x=130, world_y=100, combat_phase=CombatPhase.KNOCKDOWN)

        self.assertEqual(check_for_grab_opportunities({myself, nora}), set())

    def test_a_stunned_enemy_is_still_grabbable(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        nora = make_nora(slot="obj02", world_x=130, world_y=100, combat_phase=CombatPhase.STUNNED)

        result = check_for_grab_opportunities({myself, nora})

        self.assertEqual(result, {GrabToNeutralizeWhip(actor_slot="P1", target_slot="obj02")})

    def test_bosses_are_out_of_scope(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        boss = Abadede(
            slot="obj01",
            type_id=0x30,
            world_x=130,
            world_y=100,
            health=40,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
        )
        behind = make_garcia(slot="obj02", world_x=60, world_y=100)

        # The boss would otherwise qualify (grabbable phase, an enemy at the
        # actor's back); the Grunt behind is only its own rear threat, which
        # is not a reason to grab it.
        self.assertEqual(check_for_grab_opportunities({myself, boss, behind}), set())


class CheckForIncomingMeleeTests(unittest.TestCase):
    def test_promotes_a_committed_enemy_inside_the_caution_box(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(
            slot="obj01", world_x=160, world_y=100, combat_phase=CombatPhase.ATTACKING
        )

        result = check_for_incoming_melee({myself, enemy})

        self.assertEqual(result, {IncomingMelee(actor_slot="P1", target_slot="obj01")})

    def test_a_committed_enemy_out_of_lane_is_not_a_threat(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(
            slot="obj01", world_x=110, world_y=60, combat_phase=CombatPhase.ATTACKING
        )

        self.assertEqual(check_for_incoming_melee({myself, enemy}), set())

    def test_a_calm_enemy_at_the_same_distance_is_not_a_threat(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(slot="obj01", world_x=160, world_y=100)

        self.assertEqual(check_for_incoming_melee({myself, enemy}), set())


class CheckForPunishWindowsTests(unittest.TestCase):
    def test_knockdown_has_no_readable_timer(self) -> None:
        myself = make_myself()
        enemy = make_enemy(slot="obj01", combat_phase=CombatPhase.KNOCKDOWN)

        result = check_for_punish_windows({myself, enemy})

        self.assertEqual(result, {PunishWindow(target_slot="obj01", frames_left=0)})

    def test_a_stunned_grunt_carries_its_remaining_frames(self) -> None:
        myself = make_myself()
        garcia = make_garcia(
            slot="obj01", combat_phase=CombatPhase.STUNNED, stun_timer=0x18
        )

        result = check_for_punish_windows({myself, garcia})

        self.assertEqual(result, {PunishWindow(target_slot="obj01", frames_left=0x18)})

    def test_a_healthy_enemy_is_not_a_punish_window(self) -> None:
        myself = make_myself()
        enemy = make_enemy(slot="obj01", combat_phase=CombatPhase.NORMAL)

        self.assertEqual(check_for_punish_windows({myself, enemy}), set())


class CheckForSurroundedTests(unittest.TestCase):
    def test_a_pincer_counts_even_with_only_two_enemies(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        front = make_enemy(slot="obj01", world_x=130, world_y=100)
        back = make_enemy(slot="obj02", world_x=70, world_y=100)

        result = check_for_surrounded({myself, front, back})

        self.assertEqual(
            result, {Surrounded(actor_slot="P1", in_front=1, behind=1)}
        )

    def test_two_enemies_on_the_same_side_are_a_queue_not_a_crowd(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        near = make_enemy(slot="obj01", world_x=130, world_y=100)
        far = make_enemy(slot="obj02", world_x=150, world_y=100)

        self.assertEqual(check_for_surrounded({myself, near, far}), set())

    def test_three_on_the_same_side_is_a_crowd(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        crowd = [
            make_enemy(slot=f"obj0{i}", world_x=120 + 5 * i, world_y=100)
            for i in range(3)
        ]

        result = check_for_surrounded({myself, *crowd})

        self.assertEqual(result, {Surrounded(actor_slot="P1", in_front=3, behind=0)})


class CheckForSafeSpotsTests(unittest.TestCase):
    def _threatened(self):
        myself = make_myself(world_x=100, world_y=60, facing_left=False)
        enemy = make_enemy(
            slot="obj01", world_x=160, world_y=60, combat_phase=CombatPhase.ATTACKING
        )
        camera = CameraRange(left=0, right=400, top=0, bottom=112)
        context = {myself, enemy, camera}
        return context | check_for_incoming_melee(context)

    def test_no_threat_no_safe_spot(self) -> None:
        myself = make_myself()
        enemy = make_enemy(slot="obj01")

        self.assertEqual(check_for_safe_spots({myself, enemy}), set())

    def test_backs_away_from_the_threat(self) -> None:
        result = check_for_safe_spots(self._threatened())

        spot = next(iter(result))
        self.assertIsInstance(spot, SafeSpot)
        self.assertEqual(spot.actor_slot, "P1")
        self.assertLess(spot.world_x, 100)

    def test_sidesteps_instead_of_backing_into_a_pit(self) -> None:
        # The straight retreat lands at x=68 (SAFE_SPOT_STEP_X back from
        # 100); a pit spanning that column, at every lane, must rule out all
        # three of its candidates and leave only the two pure sidesteps.
        context = self._threatened() | {
            Pit(world_x=40, lane_y=0, width=40, height=112)
        }

        result = check_for_safe_spots(context)

        self.assertEqual(len(result), 1)
        spot = next(iter(result))
        self.assertEqual(spot.world_x, 100)
        self.assertNotEqual(spot.world_y, 60)


class CheckForWeaponUpgradesTests(unittest.TestCase):
    def test_promotes_only_a_better_weapon_on_screen(self) -> None:
        myself = make_myself(held_weapon_type=0x0A)  # bat, rank 4
        knife = Weapon(slot="w1", world_x=120, world_y=100, weapon_type=0x08)
        pepper = Weapon(slot="w2", world_x=130, world_y=100, weapon_type=0x0C)
        camera = CameraRange(left=0, right=400, top=0, bottom=112)

        result = check_for_weapon_upgrades({myself, knife, pepper, camera})

        self.assertEqual(
            result,
            {WeaponUpgrade(actor_slot="P1", target_slot="w1", rank=5, rank_gain=1)},
        )

    def test_off_camera_weapons_are_ignored(self) -> None:
        myself = make_myself(held_weapon_type=0)
        knife = Weapon(slot="w1", world_x=900, world_y=100, weapon_type=0x08)
        camera = CameraRange(left=0, right=400, top=0, bottom=112)

        self.assertEqual(check_for_weapon_upgrades({myself, knife, camera}), set())

    def test_worn_out_weapons_are_ignored(self) -> None:
        myself = make_myself(held_weapon_type=0)
        spent = Weapon(slot="w1", world_x=120, world_y=100, weapon_type=0x08, wear=3)
        camera = CameraRange(left=0, right=400, top=0, bottom=112)

        self.assertEqual(check_for_weapon_upgrades({myself, spent, camera}), set())


class GenerateInferenceTokensTests(unittest.TestCase):
    def test_unions_context_with_incoming_projectile_check(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=105, world_y=100, targets_player=1)
        # Closing projectile so IncomingProjectile is emitted.
        projectile = Projectile(slot="obj10", world_x=150, world_y=100, vel_x=-4.0, vel_z=0.0)
        context: set[Token] = {myself, enemy, projectile}

        result = generate_inference_tokens(context)

        self.assertIn(myself, result)
        self.assertIn(enemy, result)
        self.assertIn(projectile, result)
        self.assertTrue(any(isinstance(t, IncomingProjectile) for t in result))

    def test_unions_context_with_closing_enemy_check(self) -> None:
        myself = make_myself(character_id=0, world_x=100, world_y=100, facing_left=False)
        garcia = make_garcia(
            slot="obj20", world_x=40, world_y=110, grunt_vel_x=10.0, grunt_vel_y=0.0
        )
        context: set[Token] = {myself, garcia}

        result = generate_inference_tokens(context)

        self.assertIn(garcia, result)
        self.assertIn(ClosingEnemy(slot="obj20"), result)

    def test_does_not_mutate_input_context(self) -> None:
        myself = make_myself()
        context: set[Token] = {myself}
        original = set(context)

        generate_inference_tokens(context)

        self.assertEqual(context, original)


if __name__ == "__main__":
    unittest.main()
