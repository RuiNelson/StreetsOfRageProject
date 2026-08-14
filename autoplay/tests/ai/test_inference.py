import unittest

from sor_autoplay.ai.tokens import Myself
from sor_autoplay.ai.tokens import Abadede, Antonio, ClosingEnemy, Enemy, Garcia, Jack, Nora
from sor_autoplay.ai.tokens import (
    ActionableTarget,
    AntonioIsGoingToKick,
    GrabToClearRear,
    GrabIntoDeadZone,
    InGrabReach,
    InJumpAttackReach,
    InPunchReach,
    InRearReach,
    IncomingMelee,
    PunishWindow,
    Surrounded,
)
from sor_autoplay.ai.tokens import Breakable, CameraRange, Pit, SafeSpot
from sor_autoplay.hitboxes import Hitbox
from sor_autoplay.ai.tokens import IncomingProjectile, Projectile
from sor_autoplay.ai.tokens import Weapon, WeaponUpgrade
from sor_autoplay.ai.inference import (
    ANTONIO_BOOMERANG_TYPE_ID,
    ANTONIO_KICK_DIST_STATIONARY,
    check_for_antonio_kick,
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
    _safe_spot_candidates,
)
from sor_autoplay.ai.tokens import AttackRange, Token
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


def make_jack(**overrides) -> Jack:
    fields = dict(
        slot="obj01",
        type_id=0x27,
        world_x=100,
        world_y=100,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
        has_projectile=False,
    )
    fields.update(overrides)
    return Jack(**fields)


# Nora's real whip reach, exactly as attack_ranges.py extracts it from
# $242F8's animation 10 (shape $22). The dead-zone judgment is driven by this
# data, not by the enemy's class, so the fixture has to carry it.
NORA_WHIP = AttackRange(
    shape_id=0x22,
    animation=10,
    forward_min=32,
    forward_max=80,
    lane_min=-12,
    lane_max=10,
    height_min=-44,
    height_max=-20,
)


def make_nora(**overrides) -> Nora:
    fields = dict(
        slot="obj02",
        attack_ranges=(NORA_WHIP,),
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
        threat = Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x1E
        )
        # Flying away / irrelevant lane.
        benign = Projectile(
            slot="obj11", world_x=30, world_y=200, vel_x=-1.5, vel_z=0.5, type_id=0x1E
        )
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
        p = Projectile(slot="obj10", world_x=10, world_y=20, vel_x=1.0, vel_z=0.0, type_id=0x1E)
        self.assertEqual(check_for_incoming_projectiles({p}), set())

    def test_jack_axe_ignored_while_still_juggling(self) -> None:
        # Same geometry as the promoted threat above, but this is Jack's own
        # axe/torch (type $28) still spinning through his juggle -- the
        # instantaneous velocity happens to point at the actor, but nothing
        # has actually been thrown yet.
        myself = make_myself(world_x=100, world_y=100)
        jack = make_jack(slot="obj20", world_x=140, world_y=100, has_projectile=True)
        axe = Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x28
        )
        context: set[Token] = {myself, jack, axe}

        self.assertEqual(check_for_incoming_projectiles(context), set())

    def test_jack_axe_promoted_once_thrown(self) -> None:
        # has_projectile false: Jack has let go, so this is a real thrown
        # axe/torch and should be sidestepped like any other projectile.
        myself = make_myself(world_x=100, world_y=100)
        jack = make_jack(slot="obj20", world_x=300, world_y=100, has_projectile=False)
        axe = Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x28
        )
        context: set[Token] = {myself, jack, axe}

        result = check_for_incoming_projectiles(context)

        self.assertEqual(
            result,
            {
                IncomingProjectile(
                    slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0
                ),
            },
        )


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

    def test_an_enemy_walking_into_the_punch_band_is_already_in_punch_reach(self) -> None:
        # dx=58 is outside Axel's 16..50 band right now, but the strike
        # damages from frame 3 to frame 12, and the enemy is inside the box
        # for most of that span: the punch arms as it arrives rather than
        # starting from scratch once it has.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        arriving = make_enemy(slot="obj01", world_x=158, world_y=100, grunt_vel_x=-2.0)

        result = check_for_targets_in_reach({myself, arriving})

        self.assertIn(InPunchReach(actor_slot="P1", target_slot="obj01"), result)

    def test_an_enemy_walking_in_close_is_still_punchable(self) -> None:
        # THE regression this whole family has to guard. Judging the punch at
        # a single future instant projected this enemy into the punch's own
        # *inner* dead zone (below Axel's 16px edge), which deleted the
        # InPunchReach, handed the tick to could_walk_to_near_enemy and had
        # the actor walk into an enemy it should have been hitting -- while
        # promoting the slow RearAttack chord at point-blank range, since a
        # target inside the dead zone is what makes that chord "warranted".
        # Measured over a swept pipeline against the previous commit.
        #
        # The move's damaging span is what covers the target's movement, and
        # frame 0 is always part of it, so a prediction can only ever add an
        # attack -- never remove the one the observed position already gives.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        closing = make_enemy(slot="obj01", world_x=120, world_y=100, grunt_vel_x=-2.0)

        result = check_for_targets_in_reach({myself, closing})

        self.assertIn(InPunchReach(actor_slot="P1", target_slot="obj01"), result)
        self.assertIn(ActionableTarget(actor_slot="P1", target_slot="obj01"), result)

    def test_a_walking_enemy_never_loses_a_band_it_currently_occupies(self) -> None:
        # The additive guarantee, swept: whatever the observed position
        # offers, every velocity must still offer.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        for dx in range(8, 130, 2):
            still = make_enemy(slot="obj01", world_x=100 + dx, world_y=100)
            baseline = check_for_targets_in_reach({myself, still})
            for vel in (-3.0, -2.0, -1.0, 1.0, 2.0, 3.0):
                moving = make_enemy(
                    slot="obj01", world_x=100 + dx, world_y=100, grunt_vel_x=vel
                )
                with self.subTest(dx=dx, vel=vel):
                    self.assertTrue(
                        baseline <= check_for_targets_in_reach({myself, moving})
                    )

    def test_adams_slow_chord_reaches_a_target_walking_into_it(self) -> None:
        # Adam's chord damages from frame 21 to frame 38 -- more than half a
        # second -- so a target 90px behind him and walking in is inside his
        # 42px box while it is still swinging. Axel's, damaging at frames
        # 3..12, is long over before that same target arrives, and his box is
        # 40px: the two characters genuinely disagree about this target, and
        # only a per-character timeline can say so.
        axel = make_myself(world_x=100, world_y=100, facing_left=False)
        adam = make_myself(
            world_x=100, world_y=100, facing_left=False, character_id=1, character_name="Adam"
        )
        arriving = make_enemy(slot="obj01", world_x=30, world_y=100, grunt_vel_x=2.0)

        self.assertIn(
            InRearReach(actor_slot="P1", target_slot="obj01"),
            check_for_targets_in_reach({adam, arriving}),
        )
        self.assertNotIn(
            InRearReach(actor_slot="P1", target_slot="obj01"),
            check_for_targets_in_reach({axel, arriving}),
        )

    def test_a_jump_kick_arms_for_an_enemy_walking_into_its_range(self) -> None:
        # dx=70 is past Axel's 50..60 kick band, but the launch is 5 crouch
        # frames away ($1FC0) and the enemy covers 14px of that on its own.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        arriving = make_enemy(slot="obj01", world_x=170, world_y=100, grunt_vel_x=-2.0)

        result = check_for_targets_in_reach({myself, arriving})

        self.assertIn(InJumpAttackReach(actor_slot="P1", target_slot="obj01"), result)

    def test_a_jump_kick_is_never_armed_from_beyond_its_own_flight(self) -> None:
        # The kick's lead is its crouch, never its whole flight: solving the
        # full interception instead launched kicks from 100+px on the
        # assumption the target kept closing for all 25 frames.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        far = make_enemy(slot="obj01", world_x=204, world_y=100, grunt_vel_x=-2.0)

        result = check_for_targets_in_reach({myself, far})

        self.assertNotIn(InJumpAttackReach(actor_slot="P1", target_slot="obj01"), result)

    def test_a_grab_walk_in_still_offers_a_target_it_would_reach(self) -> None:
        # Already inside the walk-in range (dx=40) and retreating slowly:
        # the walk-in arrives essentially at once, so the hold is still on
        # offer -- a lead must not make the AI refuse grabs it can take.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        retreating = make_enemy(slot="obj01", world_x=140, world_y=100, grunt_vel_x=2.0)

        result = check_for_targets_in_reach({myself, retreating})

        self.assertIn(InGrabReach(actor_slot="P1", target_slot="obj01"), result)

    def test_a_walk_in_that_would_never_catch_up_is_not_grab_reach(self) -> None:
        # 25px beyond Axel's own close-combat edge and retreating at 2 px per
        # frame against his ROM walk speed of 3 ($3670): the gap closes at
        # 1 px/frame, so the walk-in arrives far too late to be worth
        # committing to -- and the prediction lands well outside the range.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        retreating = make_enemy(slot="obj01", world_x=175, world_y=100, grunt_vel_x=2.0)

        result = check_for_targets_in_reach({myself, retreating})

        self.assertNotIn(InGrabReach(actor_slot="P1", target_slot="obj01"), result)

    def test_a_stationary_enemy_is_judged_exactly_where_it_stands(self) -> None:
        # The no-velocity case must be untouched by any of the above: every
        # projection is the identity, so the bands answer as they always did.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        still = make_enemy(slot="obj01", world_x=130, world_y=100)

        result = check_for_targets_in_reach({myself, still})

        self.assertIn(InPunchReach(actor_slot="P1", target_slot="obj01"), result)
        self.assertIn(InGrabReach(actor_slot="P1", target_slot="obj01"), result)
        self.assertIn(ActionableTarget(actor_slot="P1", target_slot="obj01"), result)

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

        self.assertEqual(result, {GrabIntoDeadZone(actor_slot="P1", target_slot="obj02")})

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

        self.assertEqual(result, {GrabIntoDeadZone(actor_slot="P1", target_slot="obj02")})

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

    def test_a_fast_committed_enemy_still_far_away_promotes_predictively(self) -> None:
        # Signal's slide (enemy-ai.md "Signal's slide is velocity, not a
        # hitbox"): no attack shape anywhere in its own animation set, so
        # attack_ranges stays empty and the only way to see this coming is
        # the velocity projection. 99px out (past Axel's 74px caution box)
        # but closing at the slide's own ~2.5 px per 60 Hz frame facing left,
        # which is 30px over reach.CLOSING_ENEMY_THREAT_FRAMES.
        myself = make_myself(world_x=100, world_y=100)
        signal = make_enemy(
            slot="obj01",
            type_id=0x24,
            world_x=199,
            world_y=100,
            combat_phase=CombatPhase.ATTACKING,
            facing_left=True,
            grunt_vel_x=-2.5,
            grunt_vel_y=0.0,
        )

        result = check_for_incoming_melee({myself, signal})

        self.assertEqual(result, {IncomingMelee(actor_slot="P1", target_slot="obj01")})

    def test_a_committed_enemy_moving_away_is_not_promoted(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        signal = make_enemy(
            slot="obj01",
            type_id=0x24,
            world_x=250,
            world_y=100,
            combat_phase=CombatPhase.ATTACKING,
            grunt_vel_x=25.0,
            grunt_vel_y=0.0,
        )

        self.assertEqual(check_for_incoming_melee({myself, signal}), set())

    def test_a_calm_enemy_closing_fast_is_still_not_a_threat(self) -> None:
        # Velocity alone never substitutes for the dangerous-phase gate --
        # an ordinary approaching Grunt (CombatPhase.NORMAL) always has
        # nonzero velocity and must not be promoted just for walking toward
        # the actor.
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(
            slot="obj01",
            world_x=250,
            world_y=100,
            combat_phase=CombatPhase.NORMAL,
            grunt_vel_x=-25.0,
            grunt_vel_y=0.0,
        )

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

    def test_side_pick_does_not_glitch_exactly_on_alignment(self) -> None:
        # Regression (live-diagnosed, same shape as execute.py's X pick):
        # the old "away" sign was a raw compare between actor and threat X,
        # so a couple of px of jitter right around alignment flipped every
        # candidate here -- including the sidesteps -- to the opposite side.
        actor = make_myself(world_x=100, world_y=60, facing_left=True)
        xs = []
        for threat_x in (99, 100, 101):
            threat = make_enemy(world_x=threat_x, world_y=60)
            xs.append(_safe_spot_candidates(actor, threat)[0][0])

        self.assertEqual(len(set(xs)), 1, f"away side flipped across alignment: {xs}")

    def test_prefers_the_plain_retreat_over_a_near_tied_sidestep(self) -> None:
        # Regression: candidates used to be picked by raw max clearance, so
        # two candidates within a couple of px of each other on ordinary
        # jitter flipped which one won -- and since the candidates differ in
        # whether they add a Y step, that flip read live as the actor
        # darting into a vertical dash instead of holding a steady retreat
        # line. Pits carve away every candidate except the plain retreat
        # (index 0, x=68,y=60) and the X-away-plus-Y-up sidestep (x=68,
        # y=36), and a bystander enemy at (68, 51) is placed so the
        # sidestep's *raw* clearance (15px) edges out the plain retreat's
        # (9px) by less than SAFE_SPOT_PREFERENCE_MARGIN -- old code picked
        # the sidestep; the anchor bias must keep picking the plain retreat.
        myself = make_myself(world_x=100, world_y=60, facing_left=False)
        threat = make_enemy(
            slot="obj01", world_x=160, world_y=60, combat_phase=CombatPhase.ATTACKING
        )
        bystander = make_enemy(
            slot="obj02", world_x=68, world_y=51, combat_phase=CombatPhase.NORMAL
        )
        camera = CameraRange(left=0, right=400, top=0, bottom=112)
        context = {myself, threat, bystander, camera}
        context = context | check_for_incoming_melee(context)
        context = context | {
            Pit(world_x=0, lane_y=76, width=400, height=8),
            Pit(world_x=90, lane_y=28, width=20, height=8),
        }

        result = check_for_safe_spots(context)

        spot = next(iter(result))
        self.assertEqual((spot.world_x, spot.world_y), (68, 60))

    def test_rejects_a_candidate_whose_route_is_blocked_by_a_breakable(self) -> None:
        # The plain retreat (index 0) lands at (68, 60) -- straight line from
        # the actor's (100, 60). A prop whose push-back box (x 38..98, lane
        # 48..80 for one standing at (68, 76)) covers exactly that spot makes
        # the candidate unreachable, even though it survives every
        # pre-existing filter (in lane, in camera, not a pit). The two
        # sidesteps that also step to x=68 clear the box's lane range and
        # must win instead.
        context = self._threatened() | {
            Breakable(slot="crate1", world_x=68, world_y=76, type_id=0x1D)
        }

        result = check_for_safe_spots(context)

        spot = next(iter(result))
        self.assertNotEqual((spot.world_x, spot.world_y), (68, 60))
        self.assertEqual(spot.world_x, 68)
        self.assertIn(spot.world_y, (84, 36))

    def test_threats_own_presence_does_not_reject_every_candidate(self) -> None:
        # The threat being fled sits close enough (12px) that, if its own
        # body/reach were counted as danger for this reachability gate, it
        # would sit on or near several candidates by construction -- exactly
        # the failure mode point 2 of the task warns about. With no other
        # obstacles at all, a plausible candidate (the plain retreat) is
        # still produced.
        myself = make_myself(world_x=100, world_y=60, facing_left=False)
        threat = make_enemy(
            slot="obj01", world_x=112, world_y=60, combat_phase=CombatPhase.ATTACKING
        )
        camera = CameraRange(left=0, right=400, top=0, bottom=112)
        context = {myself, threat, camera}
        context = context | check_for_incoming_melee(context)

        result = check_for_safe_spots(context)

        self.assertEqual(len(result), 1)
        spot = next(iter(result))
        self.assertEqual((spot.world_x, spot.world_y), (68, 60))

    def test_no_safe_spot_when_every_candidate_is_boxed_in(self) -> None:
        # Every candidate step _safe_spot_candidates offers is walled off by
        # crates on all four sides, tight enough that the actor's own 16x16
        # body has no room to move at all -- not even the plain retreat can
        # find a route. check_for_safe_spots must fall back to producing no
        # SafeSpot at all (today's existing "no candidate survives" outcome,
        # `best is None: continue`), rather than handing execute.py a
        # destination that cannot actually be walked to.
        # Rows of wide round-6 props (push-back box x +/-36, lane -20..+4)
        # tile the lanes above and below, overlapping so no one-pixel line
        # between two boxes is left standable, and a deep prop (lane -28..+4)
        # seals the actor's own lane on the side it would retreat toward.
        # The actor's lane is the one gap none of them reach into.
        context = self._threatened() | {
            Breakable(slot=f"wall{x}_{y}", world_x=x, world_y=y, type_id=0x41)
            for x in (40, 76, 112)
            for y in (40, 52, 88, 104)
        } | {Breakable(slot="wall_w", world_x=68, world_y=76, type_id=0x1D)}

        result = check_for_safe_spots(context)

        self.assertEqual(result, set())


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
        projectile = Projectile(
            slot="obj10", world_x=150, world_y=100, vel_x=-4.0, vel_z=0.0, type_id=0x1E
        )
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


def make_antonio(**overrides) -> Antonio:
    fields = dict(
        slot="obj09",
        type_id=0x56,
        world_x=200,
        world_y=100,
        health=40,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
        primary_state=1,
        boss_dist_x=40,
        boss_dist_lane=4,
    )
    fields.update(overrides)
    return Antonio(**fields)


class CheckForAntonioKickTests(unittest.TestCase):
    def test_fires_when_already_in_state_2(self) -> None:
        myself = make_myself(world_x=160, world_y=100)
        antonio = make_antonio(
            combat_phase=CombatPhase.ATTACKING,
            primary_state=2,
            boss_dist_x=40,
            boss_dist_lane=4,
        )
        result = check_for_antonio_kick({myself, antonio})
        self.assertEqual(
            result, {AntonioIsGoingToKick(actor_slot="P1", target_slot="obj09")}
        )

    def test_committed_kick_off_lane_is_not_a_threat(self) -> None:
        myself = make_myself(world_x=160, world_y=100)
        antonio = make_antonio(
            combat_phase=CombatPhase.ATTACKING,
            primary_state=2,
            boss_dist_x=40,
            boss_dist_lane=24,
        )
        self.assertEqual(check_for_antonio_kick({myself, antonio}), set())

    def test_fires_when_standing_still_inside_the_stationary_window(self) -> None:
        myself = make_myself(world_x=160, world_y=100, vel_x=0.0)
        antonio = make_antonio(
            world_x=200,
            facing_left=True,
            boss_dist_x=40,
            boss_dist_lane=4,
            primary_state=1,
        )
        result = check_for_antonio_kick({myself, antonio})
        self.assertEqual(
            result, {AntonioIsGoingToKick(actor_slot="P1", target_slot="obj09")}
        )

    def test_fires_once_the_dash_is_committed(self) -> None:
        myself = make_myself(world_x=3808, world_y=33)
        antonio = make_antonio(
            world_x=3848,
            world_y=16,
            boss_dist_x=40,
            boss_dist_lane=17,
            primary_state=1,
            tactical=0x08,
        )
        result = check_for_antonio_kick({myself, antonio})
        self.assertEqual(
            result, {AntonioIsGoingToKick(actor_slot="P1", target_slot="obj09")}
        )

    def test_uncommitted_dash_window_is_not_enough(self) -> None:
        # The dash *window* is the whole fight range; firing here made
        # DodgeAntonioKick win every tick and never attack.
        myself = make_myself(world_x=3808, world_y=33, vel_x=3.0)
        antonio = make_antonio(
            world_x=3848,
            world_y=16,
            boss_dist_x=40,
            boss_dist_lane=17,
            primary_state=1,
            tactical=0,
        )
        self.assertEqual(check_for_antonio_kick({myself, antonio}), set())

    def test_does_not_fire_when_off_lane(self) -> None:
        myself = make_myself(world_x=160, world_y=100, vel_x=0.0)
        antonio = make_antonio(
            world_x=200,
            boss_dist_x=40,
            boss_dist_lane=24,
            primary_state=1,
        )
        self.assertEqual(check_for_antonio_kick({myself, antonio}), set())

    def test_does_not_fire_when_far_on_x(self) -> None:
        myself = make_myself(world_x=40, world_y=100, vel_x=0.0)
        antonio = make_antonio(
            world_x=200,
            boss_dist_x=0x80,  # 128, outside the dash window too
            boss_dist_lane=4,
            primary_state=1,
        )
        self.assertEqual(check_for_antonio_kick({myself, antonio}), set())

    def test_does_not_fire_when_target_unavailable(self) -> None:
        myself = make_myself(world_x=160, world_y=100)
        antonio = make_antonio(target_unavailable=1, combat_phase=CombatPhase.ATTACKING)
        self.assertEqual(check_for_antonio_kick({myself, antonio}), set())

    def test_closing_uses_the_wider_window(self) -> None:
        # Antonio faces left (looking at a player on his left). Player
        # walking right (vel > 0) is walking toward him → $78 window.
        myself = make_myself(world_x=100, world_y=100, vel_x=3.0)
        antonio = make_antonio(
            world_x=200,
            facing_left=True,
            boss_dist_x=0x70,  # 112, inside $78, outside $50/$68
            boss_dist_lane=4,
            primary_state=1,
        )
        result = check_for_antonio_kick({myself, antonio})
        self.assertEqual(
            result, {AntonioIsGoingToKick(actor_slot="P1", target_slot="obj09")}
        )


class AntonioBoomerangIncomingTests(unittest.TestCase):
    def test_attached_boomerang_is_not_incoming(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        antonio = make_antonio(world_x=150, world_y=100)
        boomerang = Projectile(
            slot="obj10",
            world_x=148,
            world_y=100,
            vel_x=-0.5,
            vel_z=0.0,
            type_id=ANTONIO_BOOMERANG_TYPE_ID,
        )
        self.assertEqual(
            check_for_incoming_projectiles({myself, antonio, boomerang}), set()
        )

    def test_thrown_boomerang_is_incoming(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        antonio = make_antonio(world_x=300, world_y=100)
        boomerang = Projectile(
            slot="obj10",
            world_x=150,
            world_y=100,
            vel_x=-8.0,
            vel_z=0.0,
            type_id=ANTONIO_BOOMERANG_TYPE_ID,
        )
        result = check_for_incoming_projectiles({myself, antonio, boomerang})
        self.assertEqual(
            result,
            {
                IncomingProjectile(
                    slot="obj10", world_x=150, world_y=100, vel_x=-8.0, vel_z=0.0
                )
            },
        )


if __name__ == "__main__":
    unittest.main()
