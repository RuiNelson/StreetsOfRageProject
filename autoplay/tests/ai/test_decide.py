import unittest

from sor_autoplay.ai.tokens import (
    Attack,
    CounterGrab,
    FlipHold,
    GrabEnemy,
    JumpAttack,
    AttackHeldEnemy,
    HitAntonioBoomerang,
    OpenBreakable,
    Punch,
    RearAttack,
    SprayPepper,
    StabWithKnifeOrBottle,
    SwingBatOrPipe,
    TechRecover,
    ThrowKnife,
    ThrowPepper,
)
from sor_autoplay.ai.tokens import Myself, Partner
from sor_autoplay import prop_solids
from sor_autoplay.ai.decide import (
    BREAKABLE_PUNCH_X,
    breakable_smash_outer_x,
    in_smash_range,
    generate_verb_tokens,
    could_call_police,
    could_counter_grab,
    could_handle_continue_menu,
    could_handle_mr_x_dialog,
    could_dodge_antonio_kick,
    could_grab_enemy,
    could_hit_antonio_boomerang,
    could_hold_actions,
    could_jump_attack,
    could_projectile_sidestep,
    could_punch,
    could_rear_attack,
    could_retreat_from_danger,
    could_spray_pepper,
    could_stab_with_knife_or_bottle,
    could_swing_bat_or_pipe,
    could_tech_recover,
    could_throw_knife,
    could_throw_pepper,
    could_walk_to_advance_stage,
    could_open_breakable,
    could_walk_to_near_enemy,
    could_walk_to_pickup,
    could_walk_to_weapon,
)
from sor_autoplay.ai.tokens import (
    Antonio,
    AttackRange,
    ClosingEnemy,
    DodgeAntonioKick,
    Enemy,
    Garcia,
    HitAntonioBoomerang,
    Jack,
    Nora,
)
from sor_autoplay.ai.tokens import AnimationInProgress, CameraRange, Stage
from sor_autoplay.ai.tokens import Breakable, Pit, Projectile
from sor_autoplay.ai.tokens import HealthPickup, Weapon
from sor_autoplay.ai.tokens import CallPolice
from sor_autoplay.ai.tokens import (
    HandleContinueMenu,
    HandleMrXDialog,
    InContinueMenu,
    InMrXDialog,
)
from sor_autoplay.ai.tokens import Verb, Token
from sor_autoplay.ai.tokens import (
    ProjectileSidestep,
    RetreatFromDanger,
    Walk,
    WalkToAdvanceStage,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.phases import CombatPhase


def _with_inference(generator):
    """Run ``generate_inference_tokens`` before the generator under test.

    AI.md's loop always derives the ``Inferred`` half of the context before
    any ``could_*`` runs, and the generators read those tokens (``InPunchReach``,
    ``ActionableTarget``, ``IncomingMelee``, ``WeaponUpgrade``, ...) instead of
    recomputing the geometry themselves. These tests hand-build the *observed*
    half, so they have to derive the inferred half the same way the loop does
    -- otherwise they would be exercising half a pipeline.
    """

    def wrapped(context):
        return generator(generate_inference_tokens(set(context)))

    return wrapped


could_call_police = _with_inference(could_call_police)
could_counter_grab = _with_inference(could_counter_grab)
could_handle_continue_menu = _with_inference(could_handle_continue_menu)
could_handle_mr_x_dialog = _with_inference(could_handle_mr_x_dialog)
could_dodge_antonio_kick = _with_inference(could_dodge_antonio_kick)
could_grab_enemy = _with_inference(could_grab_enemy)
could_hit_antonio_boomerang = _with_inference(could_hit_antonio_boomerang)
could_hold_actions = _with_inference(could_hold_actions)
could_jump_attack = _with_inference(could_jump_attack)
could_projectile_sidestep = _with_inference(could_projectile_sidestep)
could_punch = _with_inference(could_punch)
could_rear_attack = _with_inference(could_rear_attack)
could_retreat_from_danger = _with_inference(could_retreat_from_danger)
could_spray_pepper = _with_inference(could_spray_pepper)
could_stab_with_knife_or_bottle = _with_inference(could_stab_with_knife_or_bottle)
could_swing_bat_or_pipe = _with_inference(could_swing_bat_or_pipe)
could_tech_recover = _with_inference(could_tech_recover)
could_throw_knife = _with_inference(could_throw_knife)
could_throw_pepper = _with_inference(could_throw_pepper)
could_walk_to_advance_stage = _with_inference(could_walk_to_advance_stage)
could_open_breakable = _with_inference(could_open_breakable)
could_walk_to_near_enemy = _with_inference(could_walk_to_near_enemy)
could_walk_to_pickup = _with_inference(could_walk_to_pickup)
could_walk_to_weapon = _with_inference(could_walk_to_weapon)
generate_verb_tokens = _with_inference(generate_verb_tokens)


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


class VerbDataclassContractTests(unittest.TestCase):
    def test_decision_class_hierarchy(self) -> None:
        self.assertTrue(issubclass(Walk, Verb))
        self.assertTrue(issubclass(Attack, Verb))
        self.assertTrue(issubclass(CallPolice, Verb))
        self.assertTrue(issubclass(WalkToNearEnemy, Walk))
        self.assertTrue(issubclass(Punch, Attack))
        self.assertTrue(issubclass(HandleContinueMenu, Verb))
        self.assertTrue(issubclass(HandleMrXDialog, Verb))

    def test_priority_defaults(self) -> None:
        self.assertEqual(Punch(actor_slot="P1", target_slot="obj01").priority, 10)
        self.assertEqual(WalkToNearEnemy(actor_slot="P1", target_slot="obj01").priority, 20)
        self.assertEqual(CallPolice(actor_slot="P1").priority, 0)
        self.assertEqual(WalkToAdvanceStage(actor_slot="P1", direction="right").priority, 5)


class CouldPunchTests(unittest.TestCase):
    def test_fires_within_range(self) -> None:
        # Axel punch band: inner 16 .. outer 50 (controls-and-input.md).
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy}

        result = could_punch(context)

        self.assertEqual(result, {Punch(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_inside_inner_dead_zone(self) -> None:
        # The dead zone is the *usable* inner edge (punch_usable_inner_x): a
        # body centred just inside the box's own 16px edge still overlaps it,
        # so only dx under 10 is genuinely unhittable for Axel.
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=106, world_y=100)  # dx=6
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_punch(context), set())

    def test_fires_at_a_body_overlapping_the_boxes_inner_edge(self) -> None:
        # dx=10 is inside Axel's measured 16px box edge but the enemy's own
        # ~13px-wide body still reaches into the box, so this connects. The
        # AI used to refuse it, walk away to "re-establish range", turn
        # around doing so, and then oscillate in punching range forever.
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=110, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(
            could_punch(context), {Punch(actor_slot="P1", target_slot="obj01")}
        )

    def test_does_not_fire_out_of_range(self) -> None:
        myself = make_myself()
        enemy = make_enemy(world_x=200, world_y=200)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_punch(context), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}

        self.assertEqual(could_punch(context), set())

    def test_ignores_enemies_that_should_be_ignored_as_target(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=130, world_y=105, combat_phase=CombatPhase.DEATH)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_punch(context), set())

    def test_ignores_an_enemy_outside_the_playable_lane(self) -> None:
        # Regression: stage 1's scripted "behind a door" enemy is a real,
        # tracked Enemy object (health, combat_phase) at an anomalously
        # high world_y the player can never physically reach -- attacking
        # it just wastes time on a target that can never connect. Y=115 is
        # otherwise well within punch band Y-slack (dy=10 <= PUNCH_RANGE_Y),
        # so only the lane-bounds filter (LANE_Y_MAX_DEFAULT=112) explains
        # this being excluded.
        myself = make_myself(world_x=100, world_y=105)
        beyond_lane = make_enemy(world_x=130, world_y=115, combat_phase=CombatPhase.NORMAL)
        context: set[Token] = {myself, beyond_lane}

        self.assertEqual(could_punch(context), set())

    def test_fires_for_an_enemy_right_at_the_playable_lane_edge(self) -> None:
        myself = make_myself(world_x=100, world_y=105)
        at_edge = make_enemy(world_x=130, world_y=112, combat_phase=CombatPhase.NORMAL)
        context: set[Token] = {myself, at_edge}

        result = could_punch(context)

        self.assertEqual(result, {Punch(actor_slot="P1", target_slot="obj01")})

    def test_never_fires_for_the_partner(self) -> None:
        # One AgentLoop runs per AI-controlled player and executes the
        # surviving verb on *that* player's own VirtualGamepad, so a
        # verb parametrized with the partner's slot, position and facing
        # would be carried out on the wrong pad -- Myself pressing B at empty
        # air because the partner happened to be next to an enemy, and
        # out-ranking Myself's own candidates while doing it. Partner stays
        # in the context as Information only.
        partner = Partner(
            slot="P2",
            player_index=2,
            character_id=1,  # Adam: inner 8, outer 48
            character_name="Adam",
            world_x=300,
            world_y=60,
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
        enemy = make_enemy(slot="obj02", world_x=320, world_y=62)
        context: set[Token] = {partner, enemy}

        self.assertEqual(could_punch(context), set())

    def test_still_fires_for_myself_while_a_partner_is_present(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        partner = Partner(
            slot="P2",
            player_index=2,
            character_id=1,
            character_name="Adam",
            world_x=300,
            world_y=60,
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
        enemy = make_enemy(world_x=130, world_y=100)
        context: set[Token] = {myself, partner, enemy}

        self.assertEqual(
            could_punch(context), {Punch(actor_slot="P1", target_slot="obj01")}
        )

    def test_does_not_fire_when_holding_an_enemy(self) -> None:
        myself = make_myself(held_weapon_type=0x01)  # not a weapon-type id -> holding an enemy
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_punch(context), set())

    def test_does_not_fire_while_holding_any_weapon(self) -> None:
        # Punch is unarmed-only now -- a held bat/pipe/knife/bottle/pepper
        # fires SwingBatOrPipe/StabWithKnifeOrBottle/SprayPepper instead
        # (same B-button input, but a genuinely different ROM move/reach).
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        enemy = make_enemy(world_x=130, world_y=100)  # well within any of the bands

        self.assertEqual(could_punch({myself, enemy}), set())


class CouldSwingBatOrPipeTests(unittest.TestCase):
    def test_fires_within_the_measured_36px_reach(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        enemy = make_enemy(world_x=130, world_y=100)  # dx=30, within bat's 36

        result = could_swing_bat_or_pipe({myself, enemy})

        self.assertEqual(result, {SwingBatOrPipe(actor_slot="P1", target_slot="obj01")})

    def test_pipe_also_fires(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0B)
        enemy = make_enemy(world_x=130, world_y=100)

        result = could_swing_bat_or_pipe({myself, enemy})

        self.assertEqual(result, {SwingBatOrPipe(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_beyond_the_36px_reach(self) -> None:
        # Axel's unarmed outer is 50, but a held bat's measured reach is 36
        # (weapons-range-and-damage.md) -- a target at dx=45 is unreachable.
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        enemy = make_enemy(world_x=145, world_y=100)

        self.assertEqual(could_swing_bat_or_pipe({myself, enemy}), set())

    def test_does_not_fire_when_unarmed(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        enemy = make_enemy(world_x=130, world_y=100)

        self.assertEqual(could_swing_bat_or_pipe({myself, enemy}), set())

    def test_does_not_fire_when_holding_a_different_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)  # knife
        enemy = make_enemy(world_x=130, world_y=100)

        self.assertEqual(could_swing_bat_or_pipe({myself, enemy}), set())


class CouldStabWithKnifeOrBottleTests(unittest.TestCase):
    def test_fires_within_the_unarmed_punch_band(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=130, world_y=105)

        result = could_stab_with_knife_or_bottle({myself, enemy})

        self.assertEqual(result, {StabWithKnifeOrBottle(actor_slot="P1", target_slot="obj01")})

    def test_bottle_also_fires(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x09)
        enemy = make_enemy(world_x=130, world_y=105)

        result = could_stab_with_knife_or_bottle({myself, enemy})

        self.assertEqual(result, {StabWithKnifeOrBottle(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_when_unarmed(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        enemy = make_enemy(world_x=130, world_y=105)

        self.assertEqual(could_stab_with_knife_or_bottle({myself, enemy}), set())

    def test_does_not_fire_when_holding_a_different_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)  # bat
        enemy = make_enemy(world_x=130, world_y=105)

        self.assertEqual(could_stab_with_knife_or_bottle({myself, enemy}), set())


class CouldSprayPepperTests(unittest.TestCase):
    def test_fires_within_the_unarmed_punch_band(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0C)
        enemy = make_enemy(world_x=130, world_y=105)

        result = could_spray_pepper({myself, enemy})

        self.assertEqual(result, {SprayPepper(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_when_unarmed(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        enemy = make_enemy(world_x=130, world_y=105)

        self.assertEqual(could_spray_pepper({myself, enemy}), set())

    def test_does_not_fire_when_holding_a_different_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)  # knife
        enemy = make_enemy(world_x=130, world_y=105)

        self.assertEqual(could_spray_pepper({myself, enemy}), set())


class CouldRearAttackTests(unittest.TestCase):
    def test_fires_when_enemy_is_behind(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=80, world_y=100)  # behind while facing right
        context: set[Token] = {myself, enemy}

        result = could_rear_attack(context)

        self.assertEqual(result, {RearAttack(actor_slot="P1", target_slot="obj01")})

    def test_axel_does_not_fire_for_an_enemy_in_front(self) -> None:
        # controls-and-input.md "Measured chord timing": Axel's $322A box is
        # X -40..-8 -- pure backfist, no forward reach at all.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=108, world_y=100)  # dx=8, in front
        context: set[Token] = {myself, enemy}

        result = could_rear_attack(context)

        self.assertEqual(result, set())

    def test_adams_hop_fires_for_an_enemy_closed_in_front(self) -> None:
        # Adam's chord ($22 -> $24) is a forward-reaching hop, X -42..+14.
        myself = make_myself(
            character_id=1, character_name="Adam", world_x=100, world_y=100, facing_left=False
        )
        enemy = make_enemy(world_x=108, world_y=100)  # dx=8, within Adam's +14 front reach
        context: set[Token] = {myself, enemy}

        result = could_rear_attack(context)

        self.assertEqual(result, {RearAttack(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_early_for_a_closing_enemy_still_outside_the_band(self) -> None:
        # Regression (live-diagnosed): an earlier version also fired here
        # purely on ClosingEnemy, before the enemy was actually within
        # _in_rear_band's real range. $322A only hits based on *current*
        # position, so that committed Axel to a guaranteed-whiff attack and
        # left him locked in its recovery frames exactly when the
        # still-closing enemy arrived and landed its own hit for free.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=160, world_y=100)  # dx=60, outside Axel's 40px band
        context: set[Token] = {myself, enemy, ClosingEnemy(slot="obj01")}

        result = could_rear_attack(context)

        self.assertEqual(result, set())

    def test_still_fires_by_the_real_band_regardless_of_a_closing_enemy_token(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=80, world_y=100)  # behind while facing right
        context: set[Token] = {myself, enemy, ClosingEnemy(slot="obj01")}

        result = could_rear_attack(context)

        self.assertEqual(result, {RearAttack(actor_slot="P1", target_slot="obj01")})


class CouldCounterGrabTests(unittest.TestCase):
    def test_fires_when_held_by_enemy(self) -> None:
        myself = make_myself(
            combat_phase=CombatPhase.HELD_BY_ENEMY,
            action_state=0x7A,
        )
        context: set[Token] = {myself}

        self.assertEqual(could_counter_grab(context), {CounterGrab(actor_slot="P1")})

    def test_does_not_fire_when_free(self) -> None:
        myself = make_myself(combat_phase=CombatPhase.NORMAL)
        self.assertEqual(could_counter_grab({myself}), set())


class CouldTechRecoverTests(unittest.TestCase):
    def test_fires_when_the_tech_window_is_armed(self) -> None:
        myself = make_myself(
            combat_phase=CombatPhase.HURT_PLAYER, action_state=0x72, tech_armed=1
        )
        context: set[Token] = {myself}

        self.assertEqual(could_tech_recover(context), {TechRecover(actor_slot="P1")})

    def test_does_not_fire_when_not_armed(self) -> None:
        myself = make_myself(
            combat_phase=CombatPhase.HURT_PLAYER, action_state=0x72, tech_armed=0
        )
        self.assertEqual(could_tech_recover({myself}), set())

    def test_does_not_fire_on_a_non_techable_action_even_if_armed(self) -> None:
        myself = make_myself(combat_phase=CombatPhase.NORMAL, action_state=0x02, tech_armed=1)
        self.assertEqual(could_tech_recover({myself}), set())

    def test_bypasses_the_animation_in_progress_gate(self) -> None:
        # Unlike could_punch etc., could_tech_recover must still fire while
        # the actor is "blocked" -- that's the whole HURT_PLAYER window it's
        # meant to interrupt (mirrors could_counter_grab's own exception).
        myself = make_myself(
            combat_phase=CombatPhase.HURT_PLAYER, action_state=0x72, tech_armed=1
        )
        context: set[Token] = {myself, AnimationInProgress(slot="P1")}

        self.assertEqual(could_tech_recover(context), {TechRecover(actor_slot="P1")})


class DefeatedEnemyTests(unittest.TestCase):
    """A body is not a target -- the other half of "attacking enemies that
    are not there". The ROM's lethal check is signed, so an enemy whose
    health word has crossed $8000 is already dead while its object sits in
    the slot with an action family that has not caught up."""

    def test_no_punch_at_a_corpse(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        corpse = make_enemy(world_x=130, world_y=100, health=0xFFFF)

        self.assertEqual(could_punch({myself, corpse}), set())

    def test_no_chase_of_a_corpse(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        corpse = make_enemy(world_x=200, world_y=100, health=0x8000)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)

        self.assertEqual(could_walk_to_near_enemy({myself, corpse, camera}), set())

    def test_a_dying_enemy_at_zero_health_is_still_fought(self) -> None:
        # Zero is not defeated: the ROM counts it alive and wants the
        # finishing hit.
        myself = make_myself(world_x=100, world_y=100)
        dying = make_enemy(world_x=130, world_y=100, health=0)

        self.assertEqual(
            could_punch({myself, dying}), {Punch(actor_slot="P1", target_slot="obj01")}
        )


class CouldWalkToNearEnemyTests(unittest.TestCase):
    def test_produces_one_candidate_per_reachable_enemy_not_just_the_nearest(self) -> None:
        # could_walk_to_near_enemy must not pre-select -- per AI.md, ranking
        # several same-kind candidates against each other is
        # determine_priority_verb's job (see test_priority.py's
        # test_walk_to_near_enemy_picks_the_closer_of_two_candidates).
        myself = make_myself(world_x=0, world_y=0)
        # Outside punch/rear connect bands so walk is the right candidate.
        near = make_enemy(slot="near", world_x=80, world_y=10)
        far = make_enemy(slot="far", world_x=500, world_y=10)
        context: set[Token] = {myself, near, far}

        result = could_walk_to_near_enemy(context)

        self.assertEqual(
            result,
            {
                WalkToNearEnemy(actor_slot="P1", target_slot="near"),
                WalkToNearEnemy(actor_slot="P1", target_slot="far"),
            },
        )

    def test_never_targets_an_enemy_standing_in_a_pit(self) -> None:
        # Live-diagnosed: walking toward a target that is itself sitting in
        # a pit's danger zone means standing there too, and once
        # execute._pit_escape_mask pushes the actor back out, the same
        # target immediately pulls it right back in -- read as the actor
        # turning left then right forever at the pit's own edge.
        myself = make_myself(world_x=0, world_y=0)
        pit = Pit(world_x=70, lane_y=0, width=20, height=20)
        stuck = make_enemy(slot="stuck", world_x=80, world_y=10)
        context: set[Token] = {myself, pit, stuck}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_no_enemies_no_decision(self) -> None:
        myself = make_myself()
        self.assertEqual(could_walk_to_near_enemy({myself}), set())

    def test_no_decision_when_animation_in_progress(self) -> None:
        myself = make_myself()
        enemy = make_enemy()
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}
        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_falls_back_to_an_off_screen_enemy_ahead_in_the_stage_direction(self) -> None:
        # Regression: with nothing on-screen, an off-screen enemy still
        # correctly holds back could_walk_to_advance_stage, but nothing
        # ever chased it, so the AI produced no verb at all and the
        # camera never moved to bring it into view.
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        ahead = make_enemy(world_x=500, world_y=100)  # off-screen, ahead
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, ahead, stage}

        result = could_walk_to_near_enemy(context)

        self.assertEqual(result, {WalkToNearEnemy(actor_slot="P1", target_slot="obj01")})

    def test_does_not_chase_an_off_screen_enemy_behind(self) -> None:
        # Must never walk backward for an abandoned off-screen leftover.
        myself = make_myself(world_x=500, world_y=100)
        camera = CameraRange(left=400, right=600, top=0, bottom=200)
        behind = make_enemy(world_x=50, world_y=100)  # off-screen, behind
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, behind, stage}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_off_screen_fallback_needs_a_stage_token(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        ahead = make_enemy(world_x=500, world_y=100)
        context: set[Token] = {myself, camera, ahead}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_off_screen_fallback_inert_when_stage_direction_is_none(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        ahead = make_enemy(world_x=500, world_y=100)
        stage = Stage(level_index=6, direction="none")
        context: set[Token] = {myself, camera, ahead, stage}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_on_screen_enemy_still_takes_priority_over_the_fallback(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        on_screen = make_enemy(slot="near", world_x=150, world_y=10, health=10)
        off_screen_ahead = make_enemy(slot="far", world_x=500, world_y=100)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, on_screen, off_screen_ahead, stage}

        result = could_walk_to_near_enemy(context)

        self.assertEqual(result, {WalkToNearEnemy(actor_slot="P1", target_slot="near")})

    def test_skips_an_enemy_already_actionable_in_front(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=130, world_y=100)  # in front, in punch band
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_does_not_skip_an_enemy_behind_beyond_both_real_bands(self) -> None:
        # Regression (live-diagnosed): dx=-46 sits inside _in_punch_band's raw
        # distance box (punch_inner=16..punch_outer=50 for Axel) but the
        # enemy is behind the actor's facing, beyond both RearAttack's real
        # band (40px) and could_punch's 4px behind tolerance -- nothing can
        # actually hit it. Skipping WalkToNearEnemy here left the actor
        # standing still, undefended, while the enemy closed in and hit.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=54, world_y=100)  # behind (facing right), dx=-46
        context: set[Token] = {myself, enemy}

        result = could_walk_to_near_enemy(context)

        self.assertEqual(result, {WalkToNearEnemy(actor_slot="P1", target_slot="obj01")})

    def test_turns_toward_an_enemy_behind_when_the_chord_is_not_warranted(self) -> None:
        # dx=-30 is inside Axel's 40px rear band, but turning around is
        # available (dx >= punch_inner 16, nothing flanking), so this walk --
        # the turn-around; holding the D-pad toward the enemy sets facing --
        # must be offered as the faster, more reliable alternative to the
        # $322A chord. Treating mere band membership as "already actionable"
        # is what made the AI reflexively reach for the chord instead.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=70, world_y=100)  # behind, dx=-30
        context: set[Token] = {myself, enemy}

        self.assertEqual(
            could_walk_to_near_enemy(context),
            {WalkToNearEnemy(actor_slot="P1", target_slot="obj01")},
        )

    def test_skips_an_enemy_behind_inside_the_punch_dead_zone(self) -> None:
        # dx=-6 is inside Axel's *usable* inner edge (punch_usable_inner_x,
        # 10): turning around still leaves it unhittable, so RearAttack
        # genuinely owns this one and walking is not an alternative.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=94, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_skips_an_enemy_behind_while_boxed_in(self) -> None:
        # A flanker in front means spending the turn hands it a free hit --
        # RearAttack owns this one too.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        behind = make_enemy(world_x=70, world_y=100)
        flanker = make_enemy(slot="obj02", world_x=140, world_y=100)
        context: set[Token] = {myself, behind, flanker}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_skips_a_dangerous_enemy_in_the_caution_zone_only_while_hurt(self) -> None:
        # Axel: punch_outer=50, RETREAT_CAUTION_MARGIN=24 -> zone is dx<=74.
        # Standing off is only right when could_retreat_from_danger will
        # actually claim the enemy (_retreat_is_worth_it) -- otherwise the two
        # verbs would leave it unowned and the actor would just stand there.
        myself = make_myself(
            world_x=100, world_y=100, facing_left=False, health_percent=20.0
        )
        enemy = make_enemy(
            world_x=170, world_y=100, combat_phase=CombatPhase.ATTACKING
        )  # dx=70, dangerous, in front (not actionable: outside punch_outer=50)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_walk_to_near_enemy(context), set())

    def test_closes_on_a_dangerous_enemy_in_the_caution_zone_while_healthy(self) -> None:
        # The design point behind _retreat_is_worth_it: an enemy cannot be
        # defeated without standing in its range, so a committed enemy nearby
        # is the normal state of a fight, not a reason to stop walking. At
        # full health this must approach, not stand off.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.ATTACKING)
        context: set[Token] = {myself, enemy}

        result = could_walk_to_near_enemy(context)

        self.assertEqual(result, {WalkToNearEnemy(actor_slot="P1", target_slot="obj01")})

    def test_still_approaches_a_dangerous_enemy_beyond_the_caution_zone(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(
            world_x=200, world_y=100, combat_phase=CombatPhase.ATTACKING
        )  # dx=100, beyond the 74px caution zone
        context: set[Token] = {myself, enemy}

        result = could_walk_to_near_enemy(context)

        self.assertEqual(result, {WalkToNearEnemy(actor_slot="P1", target_slot="obj01")})


class CouldRetreatFromDangerTests(unittest.TestCase):
    """Backing off is a concession, not a reflex: an enemy cannot be defeated
    without standing in its range, so danger alone is never the reason. Every
    firing case here therefore also carries a reason to concede -- hurt, or
    surrounded (``decide._retreat_is_worth_it``)."""

    def test_fires_for_a_dangerous_enemy_in_the_caution_zone_while_hurt(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False, health_percent=20.0)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.ATTACKING)  # dx=70
        context: set[Token] = {myself, enemy}

        result = could_retreat_from_danger(context)

        self.assertEqual(result, {RetreatFromDanger(actor_slot="P1", target_slot="obj01")})

    def test_fires_for_a_charging_enemy_too(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False, health_percent=20.0)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.CHARGE)
        context: set[Token] = {myself, enemy}

        result = could_retreat_from_danger(context)

        self.assertEqual(result, {RetreatFromDanger(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_while_healthy_and_one_on_one(self) -> None:
        # The design point: at full health the same committed enemy is
        # could_walk_to_near_enemy's to close on, not something to flee.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.ATTACKING)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_retreat_from_danger(context), set())

    def test_fires_while_healthy_when_surrounded(self) -> None:
        # The other reason to concede: no amount of facing answers being hit
        # from both sides at once, so space is worth more than damage even at
        # full health. Pincer -- one enemy each side of the actor, both inside
        # REAR_THREAT_X (56). dx=54 for the committed one is the window where
        # it is close enough to count toward Surrounded and to threaten, but
        # still outside punch_outer (50) and so not yet ActionableTarget --
        # a hittable enemy is attacked, never retreated from.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        front = make_enemy(
            slot="obj01", world_x=154, world_y=100, combat_phase=CombatPhase.ATTACKING
        )
        behind = make_enemy(slot="obj02", world_x=60, world_y=100)
        context: set[Token] = {myself, front, behind}
        context |= generate_inference_tokens(context)

        result = could_retreat_from_danger(context)

        self.assertIn(RetreatFromDanger(actor_slot="P1", target_slot="obj01"), result)

    def test_does_not_fire_for_a_non_dangerous_enemy(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False, health_percent=20.0)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.NORMAL)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_retreat_from_danger(context), set())

    def test_fires_for_a_dangerous_enemy_behind_the_actor(self) -> None:
        # Deliberately side-agnostic (see this generator's docstring). An
        # earlier version skipped behind enemies, which is what made the
        # verb that owns a committed enemy depend on which way the actor
        # happened to be facing -- and since retreating *sets* facing away,
        # that handed the same enemy back and forth between this verb and
        # could_walk_to_near_enemy's turn-around on every tick. Uncovered
        # before: the whole limit cycle lived in this gap.
        myself = make_myself(world_x=100, world_y=100, facing_left=True, health_percent=20.0)
        enemy = make_enemy(  # to the right of a left-facing actor -> behind
            world_x=170, world_y=100, combat_phase=CombatPhase.ATTACKING
        )
        context: set[Token] = {myself, enemy}

        result = could_retreat_from_danger(context)

        self.assertEqual(result, {RetreatFromDanger(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_when_already_actionable(self) -> None:
        # Already hittable -- attack instead of retreating.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=130, world_y=100, combat_phase=CombatPhase.ATTACKING)  # dx=30, in front, in punch band
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_retreat_from_danger(context), set())

    def test_does_not_fire_when_still_far_beyond_the_caution_zone(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=200, world_y=100, combat_phase=CombatPhase.ATTACKING)  # dx=100
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_retreat_from_danger(context), set())

    def test_no_decision_when_animation_in_progress(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.ATTACKING)
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}

        self.assertEqual(could_retreat_from_danger(context), set())

    def test_does_not_fire_for_a_dangerous_enemy_several_lanes_away(self) -> None:
        # The caution zone is a box, not an X-only band: an enemy committed
        # to an attack it cannot possibly connect with (dy well past
        # RETREAT_CAUTION_MARGIN_Y) is no reason to walk backwards.
        myself = make_myself(world_x=100, world_y=40, facing_left=False)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.ATTACKING)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_retreat_from_danger(context), set())

    def test_an_out_of_lane_dangerous_enemy_is_still_worth_approaching(self) -> None:
        # The other half of the same gate: could_walk_to_near_enemy skips the
        # enemy could_retreat_from_danger owns, so an X-only caution zone
        # left the actor neither approaching nor retreating -- it just
        # produced no verb at all for a threat it was never in line with.
        myself = make_myself(world_x=100, world_y=40, facing_left=False)
        enemy = make_enemy(world_x=170, world_y=100, combat_phase=CombatPhase.ATTACKING)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        self.assertEqual(
            could_walk_to_near_enemy(context),
            {WalkToNearEnemy(actor_slot="P1", target_slot="obj01")},
        )

    def test_no_enemies_no_decision(self) -> None:
        myself = make_myself()
        self.assertEqual(could_retreat_from_danger({myself}), set())


class CouldWalkToAdvanceStageTests(unittest.TestCase):
    def test_fires_when_no_enemies_present(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, stage}

        result = could_walk_to_advance_stage(context)

        self.assertEqual(result, {WalkToAdvanceStage(actor_slot="P1", direction="right")})

    def test_does_not_fire_when_an_enemy_is_present(self) -> None:
        myself = make_myself()
        enemy = make_enemy()
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, enemy, stage}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_does_not_fire_when_the_only_enemy_is_off_screen(self) -> None:
        """A spawned-but-not-yet-visible enemy must hold the stage just like
        an on-screen one -- it is a reason to hold position, not a "next
        wave cue" to push past (see could_walk_to_advance_stage's
        docstring)."""

        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        off_screen_enemy = make_enemy(world_x=500, world_y=100)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, off_screen_enemy, stage}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_fires_when_the_camera_is_clear_but_an_off_screen_enemy_remains_absent(
        self,
    ) -> None:
        """Sanity check for the fix above: with no enemy token at all (on or
        off screen), advance still fires."""

        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, stage}

        result = could_walk_to_advance_stage(context)

        self.assertEqual(result, {WalkToAdvanceStage(actor_slot="P1", direction="right")})

    def test_fires_when_the_only_remaining_enemy_is_off_screen_at_zero_health(self) -> None:
        # Regression: world_map.MapEntity.is_defeated's own note says zero
        # health is still "alive" (needs a finishing hit) -- but nothing
        # ever chases an off-screen target, so such a straggler must not
        # block stage advance forever.
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        stranded = make_enemy(world_x=500, world_y=100, health=0)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, stranded, stage}

        result = could_walk_to_advance_stage(context)

        self.assertEqual(result, {WalkToAdvanceStage(actor_slot="P1", direction="right")})

    def test_does_not_fire_when_the_off_screen_zero_health_enemy_could_still_be_hit(
        self,
    ) -> None:
        # An on-screen enemy at 0 health is still reachable/finishable, so
        # it must keep blocking advance just like any other live enemy.
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        on_screen_zero_hp = make_enemy(world_x=150, world_y=100, health=0)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, on_screen_zero_hp, stage}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_off_screen_enemy_with_nonzero_health_still_blocks(self) -> None:
        # Only exactly-zero health is exempted -- a still-damageable
        # off-screen enemy is a genuine "about to scroll into view" reason
        # to hold position, per the original docstring rationale.
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        off_screen_alive = make_enemy(world_x=500, world_y=100, health=1)
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, camera, off_screen_alive, stage}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_does_not_fire_when_direction_is_none(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=6, direction="none")
        context: set[Token] = {myself, stage}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=0, direction="right")
        context: set[Token] = {myself, stage, AnimationInProgress(slot="P1")}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_does_not_fire_without_a_stage_token(self) -> None:
        myself = make_myself()
        self.assertEqual(could_walk_to_advance_stage({myself}), set())

    def test_uses_left_direction_for_level_seven(self) -> None:
        myself = make_myself()
        stage = Stage(level_index=7, direction="left")
        context: set[Token] = {myself, stage}

        result = could_walk_to_advance_stage(context)

        self.assertEqual(result, {WalkToAdvanceStage(actor_slot="P1", direction="left")})

    def test_does_not_fire_when_a_breakable_sits_ahead_on_the_path(self) -> None:
        # A crate blocks lateral progress. Producing WalkToAdvanceStage next
        # to OpenBreakable is the limit cycle: the HUD flipped between them
        # for as long as a prop was on screen.
        myself = make_myself(world_x=100, world_y=100)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        stage = Stage(level_index=0, direction="right")
        prop = Breakable(slot="obj09", world_x=200, world_y=100, type_id=0x40)
        context: set[Token] = {myself, camera, stage, prop}

        self.assertEqual(could_walk_to_advance_stage(context), set())

    def test_fires_when_the_only_breakable_is_already_behind(self) -> None:
        # A crate the actor has already walked past must not hold back
        # advance -- otherwise every smashed-or-passed prop turns the
        # actor around.
        myself = make_myself(world_x=200, world_y=100)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        stage = Stage(level_index=0, direction="right")
        prop = Breakable(slot="obj09", world_x=100, world_y=100, type_id=0x40)
        context: set[Token] = {myself, camera, stage, prop}

        self.assertEqual(
            could_walk_to_advance_stage(context),
            {WalkToAdvanceStage(actor_slot="P1", direction="right")},
        )


class CouldCallPoliceTests(unittest.TestCase):
    def test_fires_when_health_is_critical(self) -> None:
        myself = make_myself(specials=1, health_percent=10.0)
        context: set[Token] = {myself, make_enemy()}

        self.assertEqual(could_call_police(context), {CallPolice(actor_slot="P1")})

    def test_does_not_fire_with_no_enemies_even_when_critical(self) -> None:
        myself = make_myself(specials=1, health_percent=10.0)
        context: set[Token] = {myself}

        self.assertEqual(could_call_police(context), set())

    def test_does_not_fire_at_the_critical_threshold(self) -> None:
        myself = make_myself(specials=1, health_percent=18.0)
        context: set[Token] = {myself, make_enemy()}

        self.assertEqual(could_call_police(context), set())

    def test_does_not_fire_when_health_is_not_critical(self) -> None:
        myself = make_myself(specials=1, health_percent=30.0)
        context: set[Token] = {myself, make_enemy()}

        self.assertEqual(could_call_police(context), set())

    def test_never_fires_with_zero_specials(self) -> None:
        myself = make_myself(specials=0, health_percent=1.0)
        context: set[Token] = {myself, make_enemy()}

        self.assertEqual(could_call_police(context), set())

    def test_never_fires_when_holding_an_enemy(self) -> None:
        myself = make_myself(specials=1, health_percent=10.0, held_weapon_type=0x10)
        context: set[Token] = {myself, make_enemy()}

        self.assertEqual(could_call_police(context), set())

    def test_fires_when_pincered_below_the_surrounded_threshold(self) -> None:
        # The other reason the special exists: it is the only move that
        # clears every side at once, so a crowd counts even above the
        # "about to die" thresholds -- just not while comfortably healthy.
        myself = make_myself(specials=1, health_percent=50.0, world_x=100, world_y=100)
        front = make_enemy(slot="obj01", world_x=130, world_y=100)
        back = make_enemy(slot="obj02", world_x=70, world_y=100)
        context: set[Token] = {myself, front, back}

        self.assertEqual(could_call_police(context), {CallPolice(actor_slot="P1")})

    def test_does_not_fire_when_pincered_while_healthy(self) -> None:
        myself = make_myself(specials=1, health_percent=90.0, world_x=100, world_y=100)
        front = make_enemy(slot="obj01", world_x=130, world_y=100)
        back = make_enemy(slot="obj02", world_x=70, world_y=100)
        context: set[Token] = {myself, front, back}

        self.assertEqual(could_call_police(context), set())

    def test_does_not_fire_for_a_queue_on_one_side(self) -> None:
        myself = make_myself(specials=1, health_percent=50.0, world_x=100, world_y=100)
        near = make_enemy(slot="obj01", world_x=130, world_y=100)
        far = make_enemy(slot="obj02", world_x=145, world_y=100)
        context: set[Token] = {myself, near, far}

        self.assertEqual(could_call_police(context), set())

    def test_last_life_fires_at_a_higher_health_threshold(self) -> None:
        # A KO on the last life risks a continue/game-over instead of a free
        # respawn (player-health-lives-and-combat.md) -- 30% is above the
        # ordinary 18% threshold but below the last-life 35% one.
        myself = make_myself(specials=1, health_percent=30.0, lives=1)
        context: set[Token] = {myself, make_enemy()}

        self.assertEqual(could_call_police(context), {CallPolice(actor_slot="P1")})

    def test_last_life_still_respects_its_own_higher_threshold(self) -> None:
        myself = make_myself(specials=1, health_percent=40.0, lives=1)
        context: set[Token] = {myself, make_enemy()}

        self.assertEqual(could_call_police(context), set())


class CouldHandleContinueMenuTests(unittest.TestCase):
    def test_fires_on_in_continue_menu(self) -> None:
        menu = InContinueMenu(slot="P1", name_entry=False, selects_no=False)
        self.assertEqual(
            could_handle_continue_menu({menu}),
            {HandleContinueMenu(actor_slot="P1")},
        )

    def test_does_not_fire_without_the_menu(self) -> None:
        self.assertEqual(could_handle_continue_menu({make_myself()}), set())


class CouldHandleMrXDialogTests(unittest.TestCase):
    def test_fires_on_in_mr_x_dialog(self) -> None:
        dialog = InMrXDialog(slot="P1", selects_no=False)
        self.assertEqual(
            could_handle_mr_x_dialog({dialog}),
            {HandleMrXDialog(actor_slot="P1")},
        )

    def test_does_not_fire_without_the_dialog(self) -> None:
        self.assertEqual(could_handle_mr_x_dialog({make_myself()}), set())


class CouldGrabEnemyTests(unittest.TestCase):
    """Axel (character_id 0): grab reach is his punch outer edge, 50px, with
    a 10px lane tolerance (reach.GRAB_RANGE_Y)."""

    def _pincer(self, **actor_overrides) -> tuple[Myself, Garcia, Garcia]:
        myself = make_myself(world_x=100, world_y=100, facing_left=False, **actor_overrides)
        front = make_garcia(slot="front", world_x=130, world_y=100)
        behind = make_garcia(slot="behind", world_x=60, world_y=100)
        return myself, front, behind

    def test_fires_on_the_front_enemy_of_a_pincer(self) -> None:
        myself, front, behind = self._pincer()

        result = could_grab_enemy({myself, front, behind})

        self.assertEqual(result, {GrabEnemy(actor_slot="P1", target_slot="front")})

    def test_fires_on_jack_when_already_on_his_back(self) -> None:
        myself = make_myself(world_x=150, world_y=100, facing_left=True)
        jack = make_jack(slot="jack", world_x=130, world_y=100, facing_left=True)

        result = could_grab_enemy({myself, jack})

        self.assertEqual(result, {GrabEnemy(actor_slot="P1", target_slot="jack")})

    def test_fires_on_nora_without_any_rear_threat(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        nora = make_nora(slot="nora", world_x=130, world_y=100)

        result = could_grab_enemy({myself, nora})

        self.assertEqual(result, {GrabEnemy(actor_slot="P1", target_slot="nora")})

    def test_does_not_fire_on_an_ordinary_lone_enemy(self) -> None:
        # No GrabOpportunity: nothing to gain over simply punching it.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        front = make_garcia(slot="front", world_x=130, world_y=100)

        self.assertEqual(could_grab_enemy({myself, front}), set())

    def test_does_not_fire_out_of_grab_reach(self) -> None:
        myself, _, behind = self._pincer()
        far = make_garcia(slot="front", world_x=160, world_y=100)

        self.assertEqual(could_grab_enemy({myself, far, behind}), set())

    def test_does_not_fire_while_armed(self) -> None:
        myself, front, behind = self._pincer(held_weapon_type=0x0A)

        self.assertEqual(could_grab_enemy({myself, front, behind}), set())

    def test_does_not_fire_while_already_holding_an_enemy(self) -> None:
        myself, front, behind = self._pincer(held_weapon_type=0x01, action_state=0x60)

        self.assertEqual(could_grab_enemy({myself, front, behind}), set())

    def test_does_not_fire_while_airborne(self) -> None:
        myself, front, behind = self._pincer(is_airborne=True)

        self.assertEqual(could_grab_enemy({myself, front, behind}), set())

    def test_does_not_walk_into_a_committed_attack(self) -> None:
        # The target is dangerous and inside the caution box, so inference
        # raises IncomingMelee for it: walking in now takes the hit, not the
        # hold. It is also no longer grabbable, so this is doubly gated.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        nora = make_nora(
            slot="nora", world_x=130, world_y=100, combat_phase=CombatPhase.ATTACKING
        )

        self.assertEqual(could_grab_enemy({myself, nora}), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself, front, behind = self._pincer()
        context: set[Token] = {myself, front, behind, AnimationInProgress(slot="P1")}

        self.assertEqual(could_grab_enemy(context), set())


class CouldHoldActionsTests(unittest.TestCase):
    def test_front_hold_offers_knee_and_flip(self) -> None:
        myself = make_myself(
            world_x=100, world_y=100, held_weapon_type=0x01, action_state=0x60
        )
        near = make_enemy(slot="near", world_x=110, world_y=100)
        context: set[Token] = {myself, near}

        result = could_hold_actions(context)

        self.assertIn(AttackHeldEnemy(actor_slot="P1", target_slot="near"), result)
        self.assertIn(FlipHold(actor_slot="P1", target_slot="near"), result)

    def test_does_not_fire_when_holding_a_weapon(self) -> None:
        myself = make_myself(held_weapon_type=0x08, action_state=0x60)
        enemy = make_enemy(world_x=110, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_hold_actions(context), set())

    def test_does_not_fire_when_not_holding_anything(self) -> None:
        myself = make_myself(held_weapon_type=0, action_state=0x60)
        enemy = make_enemy(world_x=110, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_hold_actions(context), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself = make_myself(held_weapon_type=0x01, action_state=0x60)
        enemy = make_enemy(world_x=110, world_y=100)
        context: set[Token] = {myself, enemy, AnimationInProgress(slot="P1")}

        self.assertEqual(could_hold_actions(context), set())

    def test_targets_the_grabbed_enemy_not_a_nearer_bystander(self) -> None:
        # Every hold move's emergency (priority._held_enemy_emergency) is
        # gated on its target being GRABBED, so naming a bystander that
        # happens to be a pixel closer collapsed the whole family to
        # emergency 0 and handed the knee/throw/suplex choice to the static
        # priority tie-break instead of the rear-threat reasoning.
        myself = make_myself(
            world_x=100, world_y=100, held_weapon_type=0x01, action_state=0x60
        )
        bystander = make_enemy(slot="bystander", world_x=102, world_y=100)
        grabbed = make_enemy(
            slot="grabbed", world_x=110, world_y=100, combat_phase=CombatPhase.GRABBED
        )
        context: set[Token] = {myself, bystander, grabbed}

        result = could_hold_actions(context)

        self.assertIn(AttackHeldEnemy(actor_slot="P1", target_slot="grabbed"), result)
        self.assertNotIn(AttackHeldEnemy(actor_slot="P1", target_slot="bystander"), result)

    def test_no_crash_with_no_enemies(self) -> None:
        myself = make_myself(held_weapon_type=0x01, action_state=0x60)
        result = could_hold_actions({myself})
        self.assertTrue(any(isinstance(t, AttackHeldEnemy) for t in result))


class CouldJumpAttackTests(unittest.TestCase):
    def test_stays_committed_once_airborne_even_out_of_band(self) -> None:
        # THE reported "jumps at an enemy it could kick and never presses B".
        # Mid-flight the target walks out of the kick band -- or the flight
        # carries the actor past it -- and the verb used to vanish with it.
        # A tick with no verb reaches press_no_button, which *releases the
        # directional hold*, so the jump both lands empty-handed and (if it
        # happens during the 5-frame crouch) goes straight up: $384E reads no
        # direction at launch. Measured on the flight harness: 66 of 556
        # launched jumps produced no kick at all before this.
        myself = make_myself(world_x=100, world_y=100, is_airborne=True, facing_left=False)
        gone = make_enemy(world_x=260, world_y=100)  # far outside every band
        camera = CameraRange(left=0, right=400, top=0, bottom=200)

        result = could_jump_attack({myself, gone, camera})

        self.assertEqual(result, {JumpAttack(actor_slot="P1", target_slot="obj01")})

    def test_stays_committed_to_an_enemy_just_off_camera(self) -> None:
        # An enemy a pixel outside the camera is still a better thing to aim
        # a committed flight at than releasing the controller.
        myself = make_myself(world_x=100, world_y=100, is_airborne=True, facing_left=False)
        offscreen = make_enemy(world_x=420, world_y=100)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)

        result = could_jump_attack({myself, offscreen, camera})

        self.assertEqual(result, {JumpAttack(actor_slot="P1", target_slot="obj01")})

    def test_never_jump_kicks_while_holding_a_weapon(self) -> None:
        # A held weapon puts the ROM in the parallel $3C-$43 jump family --
        # a different move whose reach and kick edge this pipeline models
        # nowhere. Live: 246 of 4859 ticks sat in $42 with a bat in hand
        # while the AI thought it was doing an ordinary jump kick.
        armed = make_myself(
            world_x=100, world_y=100, is_airborne=False, facing_left=False,
            held_weapon_type=0x0A,  # baseball bat
        )
        enemy = make_enemy(world_x=160, world_y=100)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)

        self.assertEqual(could_jump_attack({armed, enemy, camera}), set())

    def test_grounded_still_needs_the_band(self) -> None:
        # The commitment is only about being already airborne; from the
        # ground this must stay as selective as it ever was.
        myself = make_myself(world_x=100, world_y=100, is_airborne=False, facing_left=False)
        gone = make_enemy(world_x=260, world_y=100)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)

        self.assertEqual(could_jump_attack({myself, gone, camera}), set())

    def test_does_not_commit_to_a_corpse(self) -> None:
        myself = make_myself(world_x=100, world_y=100, is_airborne=True, facing_left=False)
        dead = make_enemy(world_x=260, world_y=100, health=0xFFFF)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)

        self.assertEqual(could_jump_attack({myself, dead, camera}), set())

    def test_fires_when_horizontal_jump_kick_is_useful(self) -> None:
        # Jump-kick only beyond punch outer (Axel 50) with real ΔX, in front.
        myself = make_myself(world_x=100, world_y=100, is_airborne=False, facing_left=False)
        enemy = make_enemy(world_x=160, world_y=105)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        result = could_jump_attack(context)

        self.assertEqual(result, {JumpAttack(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_in_place(self) -> None:
        myself = make_myself(world_x=100, world_y=100, is_airborne=False)
        enemy = make_enemy(world_x=110, world_y=100)  # too close / no air travel
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        self.assertEqual(could_jump_attack(context), set())

    def test_still_fires_while_airborne_so_the_kick_b_edge_gets_pressed(self) -> None:
        # Live-diagnosed regression: the AI used to launch (C) and then go
        # completely silent for the rest of the flight, because this used to
        # bail out on any airborne actor -- leaving
        # execute.state_machine_jump_attack's airborne branch (the B press
        # that actually lands the kick) unreachable. controls-and-input.md
        # "C only to leave the ground, then B later while airborne" requires
        # this generator to keep offering the verb every tick of the flight.
        myself = make_myself(world_x=100, world_y=100, is_airborne=True, facing_left=False)
        enemy = make_enemy(world_x=160, world_y=105)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        result = could_jump_attack(context)

        self.assertEqual(result, {JumpAttack(actor_slot="P1", target_slot="obj01")})

    def test_airborne_follow_through_ignores_the_ground_launch_min_dx(self) -> None:
        # Mid-flight the actor has already closed some of the gap under its
        # own committed trajectory (no mid-air lane control) -- dx=40 is
        # inside Axel's punch_outer (50) and would fail the *grounded* launch
        # gate, but the B edge still has to land during free flight.
        myself = make_myself(world_x=100, world_y=100, is_airborne=True, facing_left=False)
        enemy = make_enemy(world_x=140, world_y=100)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        result = could_jump_attack(context)

        self.assertEqual(result, {JumpAttack(actor_slot="P1", target_slot="obj01")})

    def test_airborne_follow_through_still_respects_max_dx(self) -> None:
        myself = make_myself(world_x=100, world_y=100, is_airborne=True, facing_left=False)
        enemy = make_enemy(world_x=500, world_y=500)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        self.assertEqual(could_jump_attack(context), set())

    def test_does_not_fire_out_of_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, is_airborne=False)
        enemy = make_enemy(world_x=500, world_y=500)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        self.assertEqual(could_jump_attack(context), set())

    def test_does_not_fire_when_holding_an_enemy(self) -> None:
        myself = make_myself(
            world_x=100, world_y=100, is_airborne=False, held_weapon_type=0x01, facing_left=False
        )
        enemy = make_enemy(world_x=160, world_y=105)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        self.assertEqual(could_jump_attack(context), set())

    def test_axel_does_not_fire_beyond_his_shorter_kick_range(self) -> None:
        # controls-and-input.md "Closed-form trajectory summary": Axel's
        # early-kick range is 60px, well short of the old flat 72px cap.
        myself = make_myself(world_x=100, world_y=100, is_airborne=False, facing_left=False)
        enemy = make_enemy(world_x=165, world_y=100)  # dx=65 > Axel's 60
        camera = CameraRange(left=0, right=400, top=0, bottom=200)
        context: set[Token] = {myself, enemy, camera}

        self.assertEqual(could_jump_attack(context), set())

    def test_blaze_fires_at_a_range_beyond_axels_reach(self) -> None:
        myself = make_myself(
            character_id=2, character_name="Blaze", world_x=100, world_y=100,
            is_airborne=False, facing_left=False,
        )
        enemy = make_enemy(world_x=165, world_y=100)  # dx=65, within Blaze's 75

        result = could_jump_attack({myself, enemy})

        self.assertEqual(result, {JumpAttack(actor_slot="P1", target_slot="obj01")})


class CouldThrowKnifeTests(unittest.TestCase):
    def test_fires_when_holding_knife_and_enemy_outside_melee_but_in_knife_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=160, world_y=100)  # outside KNIFE_MELEE_X=40
        context: set[Token] = {myself, enemy}

        result = could_throw_knife(context)

        self.assertEqual(result, {ThrowKnife(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_when_enemy_is_in_melee_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=110, world_y=105)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_knife(context), set())

    def test_does_not_fire_when_holding_a_different_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x09)
        enemy = make_enemy(world_x=160, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_knife(context), set())

    def test_does_not_fire_when_enemy_beyond_knife_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=500, world_y=500)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_knife(context), set())

    def test_fires_at_an_enemy_that_will_walk_into_range(self) -> None:
        # dx=32 is inside melee right now, so a throw would be the wrong
        # move -- but the knife flies at 16 px/frame and the enemy is walking
        # *away* at 2, so by the time it is released and lands the gap is a
        # throwing gap. Judged at the impact point, not at the current one.
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)
        enemy = make_enemy(world_x=132, world_y=100, grunt_vel_x=2.0)

        result = could_throw_knife({myself, enemy})

        self.assertEqual(result, {ThrowKnife(actor_slot="P1", target_slot="obj01")})


class CouldThrowPepperTests(unittest.TestCase):
    def test_fires_when_holding_pepper_and_enemy_outside_melee_but_in_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0C)
        enemy = make_enemy(world_x=160, world_y=100)  # outside KNIFE_MELEE_X=40
        context: set[Token] = {myself, enemy}

        result = could_throw_pepper(context)

        self.assertEqual(result, {ThrowPepper(actor_slot="P1", target_slot="obj01")})

    def test_does_not_fire_when_enemy_is_in_melee_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0C)
        enemy = make_enemy(world_x=110, world_y=105)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_pepper(context), set())

    def test_does_not_fire_when_holding_a_different_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x08)  # knife
        enemy = make_enemy(world_x=160, world_y=100)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_pepper(context), set())

    def test_does_not_fire_when_enemy_beyond_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0C)
        enemy = make_enemy(world_x=500, world_y=500)
        context: set[Token] = {myself, enemy}

        self.assertEqual(could_throw_pepper(context), set())

    def test_fires_at_a_target_still_walking_into_throw_range(self) -> None:
        # dx=100 is outside the 90px envelope right now. Pepper spray crawls
        # at 6 px/frame (weapons-range-and-damage.md) against a target closing
        # at 2, so the can and the target meet at 66px -- well inside it. The
        # throw is judged where they meet, not where the target stands.
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0C)
        closing = make_enemy(world_x=200, world_y=100, grunt_vel_x=-2.0)

        result = could_throw_pepper({myself, closing})

        self.assertEqual(result, {ThrowPepper(actor_slot="P1", target_slot="obj01")})

    def test_never_withdraws_a_throw_the_current_position_allows(self) -> None:
        # The additive rule, swept: a target inside the envelope now yields a
        # throw whatever it is doing, exactly as it did before any prediction
        # existed. A throw is cheap and the weapon is spent either way; losing
        # one to a mis-modelled flight is the expensive mistake.
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0C)
        for dx in range(42, 90, 4):
            for vel in (-3.0, -2.0, 0.0, 2.0, 3.0):
                enemy = make_enemy(world_x=100 + dx, world_y=100, grunt_vel_x=vel)
                with self.subTest(dx=dx, vel=vel):
                    self.assertEqual(
                        could_throw_pepper({myself, enemy}),
                        {ThrowPepper(actor_slot="P1", target_slot="obj01")},
                    )


class InSmashRangeTests(unittest.TestCase):
    """A punch box starts 16px in front of Axel, so "close enough to hit"
    has an inner edge as well as an outer one."""

    def _prop(self, dx: int, dy: int = 0):
        return Breakable(slot="prop", world_x=100 + dx, world_y=100 + dy, type_id=0x11)

    def test_a_prop_the_actor_stands_on_is_not_in_range(self) -> None:
        # Live: 94 seconds of a 7-minute run spent punching one prop from 1px
        # away -- ~430 presses that could not connect -- because this said
        # yes, so the executor pressed B instead of repositioning, and the
        # attack animation then blocked every verb on the following tick,
        # releasing the controller and resetting the steering axis so the
        # actor never walked away either.
        actor = make_myself(world_x=100, world_y=100)

        self.assertFalse(in_smash_range(actor, self._prop(dx=1)))
        self.assertFalse(in_smash_range(actor, self._prop(dx=-4, dy=-14)))

    def test_a_prop_inside_the_punch_band_is(self) -> None:
        actor = make_myself(world_x=100, world_y=100)

        self.assertTrue(in_smash_range(actor, self._prop(dx=24)))
        self.assertTrue(in_smash_range(actor, self._prop(dx=-24)))

    def test_a_prop_beyond_the_outer_edge_is_not(self) -> None:
        actor = make_myself(world_x=100, world_y=100)

        self.assertFalse(in_smash_range(actor, self._prop(dx=60)))

    def test_a_narrow_props_reach_is_the_plain_constant(self) -> None:
        # Every prop whose own wall is inside BREAKABLE_PUNCH_X keeps exactly
        # the reach it always had.
        for type_id in (0x11, 0x19, 0x18):
            with self.subTest(type_id=type_id):
                prop = Breakable(slot="prop", world_x=100, world_y=100, type_id=type_id)
                self.assertEqual(breakable_smash_outer_x(prop), BREAKABLE_PUNCH_X)

    def test_a_prop_wider_than_the_punch_can_still_be_reached(self) -> None:
        # A round-6 prop's push-back box already reaches 36px from its own
        # origin -- exactly BREAKABLE_PUNCH_X -- so an origin-distance reach
        # of 36 would call every position the ROM allows out of range, and
        # the verb would approach a prop it can never arrive at.
        prop = Breakable(slot="prop", world_x=100, world_y=100, type_id=0x41)
        wall = prop_solids.solid_half_width(prop.type_id)

        self.assertGreater(breakable_smash_outer_x(prop), wall)
        actor = make_myself(world_x=100 - (wall + 1), world_y=100)
        self.assertTrue(in_smash_range(actor, prop))


class CouldWalkToWeaponTests(unittest.TestCase):
    def test_fires_for_in_camera_upgrade_weapon(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        weapon = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x0A)
        context: set[Token] = {myself, camera, weapon}

        result = could_walk_to_weapon(context)

        self.assertEqual(result, {WalkToWeapon(actor_slot="P1", target_slot="wpn1")})

    def test_does_not_fire_for_same_or_worse_ranked_weapon(self) -> None:
        # Holding bat (rank 4); bottle is rank 3 — not an upgrade.
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        weapon = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x09)
        context: set[Token] = {myself, camera, weapon}

        self.assertEqual(could_walk_to_weapon(context), set())

    def test_does_not_fire_for_weapon_outside_camera_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        weapon = Weapon(slot="wpn1", world_x=999, world_y=999, weapon_type=0x0A)
        context: set[Token] = {myself, camera, weapon}

        self.assertEqual(could_walk_to_weapon(context), set())

    def test_produces_one_candidate_per_upgrade_not_just_the_best(self) -> None:
        # could_walk_to_weapon must not pre-select -- per AI.md, ranking
        # several same-kind candidates against each other is
        # determine_priority_verb's job (see test_priority.py's
        # test_walk_to_weapon_picks_the_higher_ranked_upgrade).
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        knife = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x08)
        pepper = Weapon(slot="wpn2", world_x=130, world_y=115, weapon_type=0x0C)
        context: set[Token] = {myself, camera, knife, pepper}

        result = could_walk_to_weapon(context)

        self.assertEqual(
            result,
            {
                WalkToWeapon(actor_slot="P1", target_slot="wpn1"),
                WalkToWeapon(actor_slot="P1", target_slot="wpn2"),
            },
        )

    def test_knife_is_upgrade_over_bat(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        knife = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x08)
        context: set[Token] = {myself, camera, knife}

        result = could_walk_to_weapon(context)

        self.assertEqual(result, {WalkToWeapon(actor_slot="P1", target_slot="wpn1")})

    def test_never_targets_a_weapon_sitting_in_a_pit(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        weapon = Weapon(slot="wpn1", world_x=120, world_y=110, weapon_type=0x0A)
        pit = Pit(world_x=110, lane_y=100, width=20, height=20)
        context: set[Token] = {myself, camera, weapon, pit}

        self.assertEqual(could_walk_to_weapon(context), set())


class CouldWalkToPickupTests(unittest.TestCase):
    def test_fires_for_health_when_missing_enough(self) -> None:
        myself = make_myself(world_x=100, world_y=100, health=40, health_percent=50.0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        food = HealthPickup(
            slot="food1", world_x=120, world_y=110, pickup_type=0x4B, health_delta=20
        )
        context: set[Token] = {myself, camera, food}

        result = could_walk_to_pickup(context)

        self.assertEqual(result, {WalkToPickup(actor_slot="P1", target_slot="food1")})

    def test_does_not_fire_for_health_when_full(self) -> None:
        myself = make_myself(world_x=100, world_y=100, health=80, health_percent=100.0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        food = HealthPickup(
            slot="food1", world_x=120, world_y=110, pickup_type=0x47, health_delta=80
        )
        context: set[Token] = {myself, camera, food}

        self.assertEqual(could_walk_to_pickup(context), set())

    def test_never_targets_a_pickup_sitting_in_a_pit(self) -> None:
        myself = make_myself(world_x=100, world_y=100, health=40, health_percent=50.0)
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        food = HealthPickup(
            slot="food1", world_x=120, world_y=110, pickup_type=0x4B, health_delta=20
        )
        pit = Pit(world_x=110, lane_y=100, width=20, height=20)
        context: set[Token] = {myself, camera, food, pit}

        self.assertEqual(could_walk_to_pickup(context), set())


class GenerateVerbTokensTests(unittest.TestCase):
    def test_unions_all_candidates_into_context(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        # Inside Axel punch band (inner 16..outer 50).
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy}

        result = generate_verb_tokens(context)

        self.assertIn(myself, result)
        self.assertIn(enemy, result)
        self.assertIn(Punch(actor_slot="P1", target_slot="obj01"), result)
        # Already in connectable band — walk is suppressed.
        self.assertNotIn(WalkToNearEnemy(actor_slot="P1", target_slot="obj01"), result)

    def test_does_not_mutate_input_context(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        enemy = make_enemy(world_x=130, world_y=105)
        context: set[Token] = {myself, enemy}
        original = set(context)

        generate_verb_tokens(context)

        self.assertEqual(context, original)


class CouldOpenBreakableTests(unittest.TestCase):
    def test_fires_for_an_in_camera_breakable_beyond_smash_range(self) -> None:
        myself = make_myself(world_x=0, world_y=0)
        camera = CameraRange(left=-50, right=200, top=-50, bottom=200)
        prop = Breakable(slot="obj09", world_x=60, world_y=0, type_id=0x40)
        context: set[Token] = {myself, camera, prop}

        result = could_open_breakable(context)

        self.assertEqual(result, {OpenBreakable(actor_slot="P1", target_slot="obj09")})

    def test_fires_when_already_in_smash_range(self) -> None:
        # The old split produced nothing here from could_walk_to_breakable
        # and relied on could_smash_breakable for the same prop; one verb
        # covers both, and priority scores this at the in-range tier.
        myself = make_myself(world_x=0, world_y=0)
        camera = CameraRange(left=-50, right=200, top=-50, bottom=200)
        prop = Breakable(slot="obj09", world_x=10, world_y=0, type_id=0x40)
        context: set[Token] = {myself, camera, prop}

        self.assertEqual(
            could_open_breakable(context), {OpenBreakable(actor_slot="P1", target_slot="obj09")}
        )

    def test_never_targets_a_breakable_sitting_in_a_pit(self) -> None:
        myself = make_myself(world_x=0, world_y=0)
        camera = CameraRange(left=-50, right=200, top=-50, bottom=200)
        prop = Breakable(slot="obj09", world_x=60, world_y=0, type_id=0x40)
        pit = Pit(world_x=50, lane_y=-10, width=20, height=20)
        context: set[Token] = {myself, camera, prop, pit}

        self.assertEqual(could_open_breakable(context), set())

    def test_fires_for_a_prop_in_range_behind_the_actor(self) -> None:
        # Behind the stage direction, so the "ahead" filter drops it -- but
        # it is already in reach, and opening it costs only the B press.
        myself = make_myself(world_x=200, world_y=0)
        camera = CameraRange(left=-50, right=400, top=-50, bottom=200)
        stage = Stage(level_index=0, direction="right")
        prop = Breakable(slot="obj09", world_x=180, world_y=0, type_id=0x40)
        context: set[Token] = {myself, camera, stage, prop}

        self.assertEqual(
            could_open_breakable(context), {OpenBreakable(actor_slot="P1", target_slot="obj09")}
        )

    def test_produces_one_candidate_per_reachable_breakable_not_just_the_nearest(self) -> None:
        # Must not pre-select -- per AI.md, ranking several same-kind
        # candidates against each other is determine_priority_verb's
        # job (see test_priority.py's
        # test_open_breakable_picks_the_closer_of_two_candidates).
        myself = make_myself(world_x=0, world_y=0)
        camera = CameraRange(left=-50, right=300, top=-50, bottom=200)
        near = Breakable(slot="near", world_x=60, world_y=0, type_id=0x40)
        far = Breakable(slot="far", world_x=250, world_y=0, type_id=0x40)
        context: set[Token] = {myself, camera, near, far}

        result = could_open_breakable(context)

        self.assertEqual(
            result,
            {
                OpenBreakable(actor_slot="P1", target_slot="near"),
                OpenBreakable(actor_slot="P1", target_slot="far"),
            },
        )

    def test_missing_camera_still_considers_off_screen_breakables(self) -> None:
        myself = make_myself(world_x=0, world_y=0)
        prop = Breakable(slot="obj09", world_x=60, world_y=0, type_id=0x40)
        context: set[Token] = {myself, prop}

        result = could_open_breakable(context)

        self.assertEqual(result, {OpenBreakable(actor_slot="P1", target_slot="obj09")})

    def test_does_not_walk_back_to_a_breakable_already_behind(self) -> None:
        # The old fallback (if nothing is ahead, consider every crate)
        # made the actor turn around after walking past one, then
        # WalkToAdvanceStage walked past it again.
        myself = make_myself(world_x=200, world_y=0)
        camera = CameraRange(left=-50, right=400, top=-50, bottom=200)
        stage = Stage(level_index=0, direction="right")
        prop = Breakable(slot="obj09", world_x=60, world_y=0, type_id=0x40)
        context: set[Token] = {myself, camera, stage, prop}

        self.assertEqual(could_open_breakable(context), set())


class JackJugglingMeleeTests(unittest.TestCase):
    """While Jack juggles his axe/torch (has_projectile), a punch or an
    armed melee swing is refused -- only the jump kick and the from-behind
    chord are safe finishers (decide._could_melee_strike)."""

    def test_could_punch_refuses_a_juggling_jack(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        jack = make_jack(world_x=130, world_y=105, has_projectile=True)
        context: set[Token] = {myself, jack}

        self.assertEqual(could_punch(context), set())

    def test_could_punch_fires_once_the_weapon_is_gone(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        jack = make_jack(world_x=130, world_y=105, has_projectile=False)
        context: set[Token] = {myself, jack}

        result = could_punch(context)

        self.assertEqual(result, {Punch(actor_slot="P1", target_slot="obj01")})

    def test_could_swing_bat_or_pipe_also_refuses_a_juggling_jack(self) -> None:
        myself = make_myself(world_x=100, world_y=100, held_weapon_type=0x0A)  # baseball bat
        jack = make_jack(world_x=130, world_y=105, has_projectile=True)
        context: set[Token] = {myself, jack}

        self.assertEqual(could_swing_bat_or_pipe(context), set())

    def test_a_non_juggling_jack_does_not_affect_a_different_juggling_jack(self) -> None:
        # The refusal is per-target, read from each Jack's own has_projectile
        # -- not a blanket "no melee on any Jack this tick".
        myself = make_myself(world_x=100, world_y=100)
        juggling = make_jack(slot="obj01", world_x=130, world_y=105, has_projectile=True)
        idle = make_jack(slot="obj02", world_x=135, world_y=100, has_projectile=False)
        context: set[Token] = {myself, juggling, idle}

        result = could_punch(context)

        self.assertEqual(result, {Punch(actor_slot="P1", target_slot="obj02")})

    def test_could_rear_attack_is_unaffected(self) -> None:
        # From behind, juggling or not, the chord still answers him -- the
        # exception only covers the four melee-strike siblings.
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        jack = make_jack(world_x=80, world_y=100, has_projectile=True)  # behind

        result = could_rear_attack({myself, jack})

        self.assertEqual(result, {RearAttack(actor_slot="P1", target_slot="obj01")})

    def test_could_jump_attack_is_unaffected(self) -> None:
        # The kick arrives from above, not through the juggling itself.
        myself = make_myself(world_x=100, world_y=100, is_airborne=False, facing_left=False)
        jack = make_jack(world_x=160, world_y=105, has_projectile=True)
        camera = CameraRange(left=0, right=400, top=0, bottom=200)

        result = could_jump_attack({myself, jack, camera})

        self.assertEqual(result, {JumpAttack(actor_slot="P1", target_slot="obj01")})


class CouldProjectileSidestepTests(unittest.TestCase):
    def test_fires_for_a_threatening_projectile(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        projectile = Projectile(slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x1E)
        context: set[Token] = {myself, projectile}

        result = could_projectile_sidestep(context)

        self.assertEqual(result, {ProjectileSidestep(actor_slot="P1", target_slot="obj10")})

    def test_does_not_fire_for_a_projectile_heading_away(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        projectile = Projectile(slot="obj10", world_x=150, world_y=100, vel_x=5.0, vel_z=0.0, type_id=0x1E)
        context: set[Token] = {myself, projectile}

        self.assertEqual(could_projectile_sidestep(context), set())

    def test_does_not_fire_when_animation_in_progress(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        projectile = Projectile(slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x1E)
        context: set[Token] = {myself, projectile, AnimationInProgress(slot="P1")}

        self.assertEqual(could_projectile_sidestep(context), set())

    def test_does_not_fire_while_held_by_enemy(self) -> None:
        myself = make_myself(
            world_x=100, world_y=100, combat_phase=CombatPhase.HELD_BY_ENEMY
        )
        projectile = Projectile(slot="obj10", world_x=150, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x1E)
        context: set[Token] = {myself, projectile}

        self.assertEqual(could_projectile_sidestep(context), set())

    def test_never_fires_for_the_partner(self) -> None:
        partner = Partner(
            slot="P2",
            player_index=2,
            character_id=1,
            character_name="Adam",
            world_x=150,
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
        projectile = Projectile(slot="obj10", world_x=200, world_y=100, vel_x=-5.0, vel_z=0.0, type_id=0x1E)
        context: set[Token] = {partner, projectile}

        self.assertEqual(could_projectile_sidestep(context), set())


def _antonio(**overrides) -> Antonio:
    fields = dict(
        slot="obj09",
        type_id=0x56,
        world_x=160,
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


class CouldDodgeAntonioKickTests(unittest.TestCase):
    def test_fires_when_the_kick_token_is_present(self) -> None:
        myself = make_myself(world_x=120, world_y=100)
        antonio = _antonio(world_x=160, combat_phase=CombatPhase.ATTACKING, primary_state=2)
        result = could_dodge_antonio_kick({myself, antonio})
        self.assertTrue(
            any(isinstance(v, DodgeAntonioKick) and v.target_slot == "obj09" for v in result)
        )

    def test_does_not_fire_while_airborne(self) -> None:
        myself = make_myself(world_x=120, world_y=100, is_airborne=True, action_state=0x12)
        antonio = _antonio(world_x=160, combat_phase=CombatPhase.ATTACKING, primary_state=2)
        self.assertFalse(
            any(isinstance(v, DodgeAntonioKick) for v in could_dodge_antonio_kick({myself, antonio}))
        )


class CouldHitAntonioBoomerangTests(unittest.TestCase):
    def test_fires_when_the_thrown_boomerang_is_in_punch_range(self) -> None:
        myself = make_myself(world_x=100, world_y=100, facing_left=False)
        antonio = _antonio(world_x=300, world_y=100, boss_dist_x=200, boss_dist_lane=0)
        boomerang = Projectile(
            slot="obj10", world_x=130, world_y=100, vel_x=-8.0, vel_z=0.0, type_id=0x96
        )
        result = could_hit_antonio_boomerang({myself, antonio, boomerang})
        self.assertTrue(
            any(
                isinstance(v, HitAntonioBoomerang) and v.target_slot == "obj10"
                for v in result
            )
        )

    def test_does_not_fire_at_an_attached_boomerang(self) -> None:
        myself = make_myself(world_x=100, world_y=100)
        antonio = _antonio(world_x=150, world_y=100, boss_dist_x=50, boss_dist_lane=0)
        boomerang = Projectile(
            slot="obj10", world_x=148, world_y=100, vel_x=-0.4, vel_z=0.0, type_id=0x96
        )
        self.assertFalse(
            any(
                isinstance(v, HitAntonioBoomerang)
                for v in could_hit_antonio_boomerang({myself, antonio, boomerang})
            )
        )


class PunchSkippedDuringAntonioKickTests(unittest.TestCase):
    def test_does_not_punch_antonio_while_he_is_about_to_kick(self) -> None:
        myself = make_myself(world_x=120, world_y=100, facing_left=False)
        antonio = _antonio(
            world_x=160,
            world_y=100,
            combat_phase=CombatPhase.ATTACKING,
            primary_state=2,
            boss_dist_x=40,
            boss_dist_lane=0,
        )
        punches = [
            v for v in could_punch({myself, antonio}) if isinstance(v, Punch)
        ]
        self.assertEqual(punches, [])


if __name__ == "__main__":
    unittest.main()
