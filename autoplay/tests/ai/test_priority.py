import unittest

from sor_autoplay.ai.tokens import (
    Antonio,
    AttackHeldEnemy,
    Breakable,
    CounterGrab,
    DodgeAntonioKick,
    GrabEnemy,
    HealthPickup,
    HitAntonioBoomerang,
    JumpAttack,
    LifePickup,
    Punch,
    RearAttack,
    ScorePickup,
    OpenBreakable,
    SprayPepper,
    StabWithKnifeOrBottle,
    Supplex,
    SwingBatOrPipe,
    TechRecover,
    ThrowKnife,
    ThrowPepper,
    Weapon,
)
from sor_autoplay.ai.tokens import Myself
from sor_autoplay.ai.tokens import AttackRange, ClosingEnemy, Enemy, Garcia, Nora
from sor_autoplay.ai.tokens import CallPolice
from sor_autoplay.ai.tokens import (
    HandleContinueMenu,
    HandleMrXDialog,
    InContinueMenu,
    InMrXDialog,
)
from sor_autoplay.ai.tokens import CameraRange, Stage
from sor_autoplay.ai.tokens import Projectile
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.priority import determine_priority_verb as _rank_verbs
from sor_autoplay.ai.tokens import Verb, find_all
from sor_autoplay.ai.tokens import (
    DodgeAntonioKick,
    ProjectileSidestep,
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from sor_autoplay.phases import HITSTUN_FRAMES, PEPPER_STUN_FRAMES, CombatPhase


def determine_priority_verb(context):
    """Rank a context built the way AI.md's loop builds it.

    Several ``_emergency_*`` functions read ``Inferred`` tokens
    (``PunishWindow``, ``IncomingMelee``, ``WeaponUpgrade``, ``Surrounded``)
    rather than re-deriving the same judgment from raw coordinates, and the
    loop always produces those before ranking. These tests hand-build the
    observed half of the context, so they derive the inferred half here.
    """

    return _rank_verbs(generate_inference_tokens(set(context)))


def _enemy(slot: str, combat_phase: CombatPhase, **overrides) -> Enemy:
    fields = dict(
        slot=slot,
        type_id=0x20,
        world_x=0,
        world_y=64,
        health=10,
        combat_phase=combat_phase,
        targets_player=1,
        facing_left=False,
    )
    fields.update(overrides)
    return Enemy(**fields)


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


def _camera() -> CameraRange:
    """A camera wide enough to contain every fixture position here."""

    return CameraRange(left=-200, right=600, top=0, bottom=112)


def _myself(**overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=100,
        world_y=64,
        health=80,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=False,
        combat_phase=CombatPhase.NORMAL,
        action_state=0x02,
        is_airborne=False,
    )
    fields.update(overrides)
    return Myself(**fields)


class DetermineEmergencyWinnerTests(unittest.TestCase):
    def test_handle_continue_menu_beats_everything_else(self) -> None:
        context = {
            InContinueMenu(slot="P1", name_entry=False, selects_no=False),
            HandleContinueMenu(actor_slot="P1"),
            Punch(actor_slot="P1", target_slot="obj01"),
            _enemy("obj01", CombatPhase.KNOCKDOWN),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], HandleContinueMenu)

    def test_handle_mr_x_dialog_beats_a_punishable_punch(self) -> None:
        context = {
            InMrXDialog(slot="P1", selects_no=False),
            HandleMrXDialog(actor_slot="P1"),
            Punch(actor_slot="P1", target_slot="obj01"),
            _enemy("obj01", CombatPhase.KNOCKDOWN),
            _myself(),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], HandleMrXDialog)

    def test_call_police_beats_punch_on_punishable_enemy(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        myself = _myself(health_percent=10.0)
        context = {
            punishable,
            myself,
            CallPolice(actor_slot="P1"),
            Punch(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], CallPolice)

    def test_call_police_on_last_life_beats_punch_above_ordinary_threshold(self) -> None:
        # 30% health is above the ordinary 18% threshold but below the
        # last-life 35% one, so emergency should still be raised.
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        myself = _myself(health_percent=30.0, lives=1)
        context = {
            punishable,
            myself,
            CallPolice(actor_slot="P1"),
            Punch(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], CallPolice)

    def test_call_police_below_full_health_loses_to_punishable_punch(self) -> None:
        # Above the health threshold, CallPolice's condition is false (0),
        # so a punishable Punch (60) wins instead.
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        myself = _myself(health_percent=100.0)
        context = {
            punishable,
            myself,
            CallPolice(actor_slot="P1"),
            Punch(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], Punch)

    def test_no_verbs_returns_context_unchanged(self) -> None:
        enemy = _enemy("obj01", CombatPhase.NORMAL)
        context = {enemy}

        result = determine_priority_verb(context)

        self.assertEqual(result, context)

    def test_walk_to_near_enemy_beats_walk_to_advance_stage(self) -> None:
        # AI.md: advancing the stage is the lowest-priority fallback.
        myself = _myself(world_x=0, world_y=50)
        enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=10, world_y=50)
        context = {
            myself,
            enemy,
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
            WalkToAdvanceStage(actor_slot="P1", direction="right"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToNearEnemy)

    def test_walk_to_near_enemy_picks_the_closer_of_two_candidates(self) -> None:
        # could_walk_to_near_enemy (decide.py) no longer pre-selects the
        # nearest enemy -- this is now determine_priority_verb's job,
        # via _emergency_walk_to_near_enemy's distance-bucketed score.
        myself = _myself(world_x=0, world_y=64)
        near = _enemy("obj01", CombatPhase.NORMAL, world_x=10, world_y=64)
        far = _enemy("obj02", CombatPhase.NORMAL, world_x=150, world_y=64)
        context = {
            myself,
            near,
            far,
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")

    def test_advance_stage_fires_when_only_remaining_enemy_is_off_screen_at_zero_health(
        self,
    ) -> None:
        # Same regression as test_decide.py's could_walk_to_advance_stage
        # coverage, exercised through the emergency function this time:
        # priority.py must reach the same "not blocking" conclusion as
        # decide.py's own gate, via the shared _advance_blocking_enemies.
        camera = CameraRange(left=0, right=200, top=0, bottom=200)
        stranded = _enemy("obj01", CombatPhase.NORMAL, world_x=500, world_y=64, health=0)
        context = {
            camera,
            stranded,
            WalkToAdvanceStage(actor_slot="P1", direction="right"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToAdvanceStage)

    def test_supplex_always_outranks_punch_tier(self) -> None:
        held = _enemy("obj01", CombatPhase.GRABBED)
        punishable = _enemy("obj02", CombatPhase.KNOCKDOWN)
        context = {
            held,
            punishable,
            Supplex(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], Supplex)

    def test_hold_move_scores_zero_when_target_not_grabbed(self) -> None:
        # The "Enemy when held" condition is CombatPhase.GRABBED; a target in
        # any other phase (context desync, e.g. it just broke free) scores 0.
        not_held = _enemy("obj01", CombatPhase.NORMAL)
        punishable = _enemy("obj02", CombatPhase.KNOCKDOWN)
        context = {
            not_held,
            punishable,
            AttackHeldEnemy(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], Punch)

    def test_counter_grab_beats_call_police(self) -> None:
        myself = _myself(combat_phase=CombatPhase.HELD_BY_ENEMY, health_percent=10.0)
        context = {
            myself,
            CounterGrab(actor_slot="P1"),
            CallPolice(actor_slot="P1"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], CounterGrab)

    def test_tech_recover_beats_call_police(self) -> None:
        myself = _myself(
            combat_phase=CombatPhase.HURT_PLAYER,
            action_state=0x72,
            tech_armed=1,
            health_percent=10.0,
        )
        context = {
            myself,
            TechRecover(actor_slot="P1"),
            CallPolice(actor_slot="P1"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], TechRecover)

    def test_tech_recover_scores_zero_when_not_armed(self) -> None:
        myself = _myself(
            combat_phase=CombatPhase.HURT_PLAYER,
            action_state=0x72,
            tech_armed=0,
            health_percent=10.0,
        )
        context = {
            myself,
            TechRecover(actor_slot="P1"),
            CallPolice(actor_slot="P1"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], CallPolice)

    def test_counter_grab_beats_tech_recover(self) -> None:
        # Being held by an enemy right now outranks a still-open landing
        # tech window from an earlier throw.
        myself = _myself(
            combat_phase=CombatPhase.HELD_BY_ENEMY,
            action_state=0x72,
            tech_armed=1,
        )
        context = {
            myself,
            CounterGrab(actor_slot="P1"),
            TechRecover(actor_slot="P1"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], CounterGrab)

    def test_counter_grab_scores_zero_when_not_held(self) -> None:
        myself = _myself(combat_phase=CombatPhase.NORMAL, health_percent=10.0)
        context = {
            myself,
            CounterGrab(actor_slot="P1"),
            CallPolice(actor_slot="P1"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], CallPolice)

    def test_jump_attack_emergency_splits_punishable_vs_default(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        normal = _enemy("obj02", CombatPhase.NORMAL)

        punishable_context = {
            punishable,
            JumpAttack(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }
        result = determine_priority_verb(punishable_context)
        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], JumpAttack)

        default_context = {
            normal,
            JumpAttack(actor_slot="P1", target_slot="obj02"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }
        result = determine_priority_verb(default_context)
        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], JumpAttack)

    def test_jump_attack_prefers_a_nora_freshly_out_of_her_own_attack(self) -> None:
        # Just stopped attacking (ticks_since_last_attack small, not
        # dangerous, not in any ROM-confirmed PunishWindow phase either) --
        # the probabilistic recovery tier (24) must still beat a routine
        # WalkToNearEnemy toward a *different*, farther enemy competing for
        # the same tick.
        fresh_nora = Nora(
            slot="obj01",
            type_id=0x26,
            world_x=0,
            world_y=64,
            health=10,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=False,
            ticks_since_last_attack=2,
        )
        farther_enemy = _enemy("obj02", CombatPhase.NORMAL, world_x=200)
        context = {
            fresh_nora,
            farther_enemy,
            JumpAttack(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")
        self.assertIsInstance(verbs[0], JumpAttack)

    def test_jump_attack_recovery_tier_expires_after_the_window(self) -> None:
        fresh_nora = Nora(
            slot="obj01",
            type_id=0x26,
            world_x=0,
            world_y=64,
            health=10,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=False,
            ticks_since_last_attack=2,
        )
        stale_nora = Nora(
            slot="obj02",
            type_id=0x26,
            world_x=0,
            world_y=64,
            health=10,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=False,
            ticks_since_last_attack=999,
        )
        context = {
            fresh_nora,
            stale_nora,
            JumpAttack(actor_slot="P1", target_slot="obj01"),
            JumpAttack(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")

    def test_jump_attack_recovery_tier_does_not_apply_while_still_dangerous(self) -> None:
        # ticks_since_last_attack resets to 0 while she is dangerous
        # (observe.NoraAttackTracker), which must not be read as "freshly
        # recovered" -- that would encourage jumping into her active attack.
        still_dangerous = Nora(
            slot="obj01",
            type_id=0x26,
            world_x=0,
            world_y=64,
            health=10,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
            facing_left=False,
            ticks_since_last_attack=0,
        )
        freshly_recovered = Nora(
            slot="obj02",
            type_id=0x26,
            world_x=0,
            world_y=64,
            health=10,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=False,
            ticks_since_last_attack=2,
        )
        context = {
            still_dangerous,
            freshly_recovered,
            JumpAttack(actor_slot="P1", target_slot="obj01"),
            JumpAttack(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj02")


class DetermineEmergencyMeleeWeaponSiblingsTests(unittest.TestCase):
    """SwingBatOrPipe/StabWithKnifeOrBottle/SprayPepper share Punch's exact
    emergency formula (_emergency_melee_strike) -- one representative check
    per sibling that the shared wiring wins over a punishable-but-farther
    WalkToNearEnemy exactly like Punch does."""

    def test_swing_bat_or_pipe_beats_walk_to_near_enemy_on_punishable_target(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        context = {
            punishable,
            SwingBatOrPipe(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], SwingBatOrPipe)

    def test_stab_with_knife_or_bottle_beats_walk_to_near_enemy_on_punishable_target(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        context = {
            punishable,
            StabWithKnifeOrBottle(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], StabWithKnifeOrBottle)

    def test_spray_pepper_beats_walk_to_near_enemy_on_punishable_target(self) -> None:
        punishable = _enemy("obj01", CombatPhase.KNOCKDOWN)
        context = {
            punishable,
            SprayPepper(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], SprayPepper)


class DetermineEmergencyTokenConditionTests(unittest.TestCase):
    """Branches that were reachable in the old constant chain but had no
    dedicated coverage: WalkToPickup tiers, WalkToWeapon rank, ThrowKnife
    range, and the two Breakable verbs' target-presence check."""

    def test_walk_to_pickup_critical_health_beats_life_pickup(self) -> None:
        critical = _myself(health_percent=30.0)
        pickup = HealthPickup(slot="obj01", world_x=0, world_y=64, pickup_type=0x4B, health_delta=20)
        life_pickup = LifePickup(slot="obj02", world_x=0, world_y=64, pickup_type=0x4C)
        context = {
            critical,
            pickup,
            life_pickup,
            WalkToPickup(actor_slot="P1", target_slot="obj01"),
            WalkToPickup(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")

    def test_walk_to_pickup_full_health_pickup_beats_score_pickup(self) -> None:
        # At full health the HealthPickup formula drops from critical (50)
        # to its non-critical tier (15), which still beats a ScorePickup (3).
        healthy = _myself(health_percent=100.0)
        pickup = HealthPickup(slot="obj01", world_x=0, world_y=64, pickup_type=0x4B, health_delta=20)
        score_pickup = ScorePickup(slot="obj02", world_x=0, world_y=64, pickup_type=0x3F, points=3000)
        context = {
            healthy,
            pickup,
            score_pickup,
            WalkToPickup(actor_slot="P1", target_slot="obj01"),
            WalkToPickup(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")

    def test_walk_to_pickup_life_beats_score(self) -> None:
        actor = _myself()
        life_pickup = LifePickup(slot="obj01", world_x=0, world_y=64, pickup_type=0x4C)
        score_pickup = ScorePickup(slot="obj02", world_x=0, world_y=64, pickup_type=0x3F, points=3000)
        context = {
            actor,
            life_pickup,
            score_pickup,
            WalkToPickup(actor_slot="P1", target_slot="obj01"),
            WalkToPickup(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")

    def test_walk_to_weapon_scores_when_rank_beats_held(self) -> None:
        # The camera matters: WeaponUpgrade is only inferred for a weapon
        # actually on screen, and _emergency_walk_to_weapon reads that token
        # rather than re-ranking the raw Weapon.
        unarmed = _myself(held_weapon_type=0)
        knife = Weapon(slot="obj01", world_x=0, world_y=64, weapon_type=0x08)
        context = {unarmed, knife, _camera(), WalkToWeapon(actor_slot="P1", target_slot="obj01")}

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToWeapon)

    def test_walk_to_weapon_picks_the_higher_ranked_upgrade(self) -> None:
        # could_walk_to_weapon (decide.py) no longer pre-selects the best
        # upgrade -- this is now determine_priority_verb's job, via
        # _emergency_walk_to_weapon's rank-scaled score.
        unarmed = _myself(held_weapon_type=0)
        knife = Weapon(slot="obj01", world_x=0, world_y=64, weapon_type=0x08)  # rank 5
        pepper = Weapon(slot="obj02", world_x=0, world_y=64, weapon_type=0x0C)  # rank 2
        context = {
            unarmed,
            knife,
            pepper,
            _camera(),
            WalkToWeapon(actor_slot="P1", target_slot="obj01"),
            WalkToWeapon(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")

    def test_walk_to_weapon_scores_zero_when_not_an_upgrade(self) -> None:
        # Already holding the best weapon: the floor pepper spray isn't an
        # upgrade, so WalkToWeapon's condition is false and it loses to a
        # WalkToNearEnemy (14) that would otherwise be a weaker verb.
        armed_with_knife = _myself(held_weapon_type=0x08)
        pepper = Weapon(slot="obj01", world_x=0, world_y=64, weapon_type=0x0C)
        enemy = _enemy("obj02", CombatPhase.NORMAL)
        context = {
            armed_with_knife,
            pepper,
            enemy,
            _camera(),
            WalkToWeapon(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToNearEnemy)

    def test_throw_knife_scores_within_range_beyond_melee(self) -> None:
        actor = _myself(world_x=0, world_y=64)
        far_enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=60, world_y=64)
        context = {
            actor,
            far_enemy,
            ThrowKnife(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], ThrowKnife)

    def test_throw_knife_scores_zero_when_still_in_melee(self) -> None:
        actor = _myself(world_x=0, world_y=64)
        near_enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=10, world_y=64)
        context = {
            actor,
            near_enemy,
            ThrowKnife(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToNearEnemy)

    def test_throw_knife_picks_the_closer_of_two_qualifying_enemies(self) -> None:
        # could_throw_knife (decide.py) no longer pre-selects the nearest
        # enemy -- this is now determine_priority_verb's job, via the
        # shared _emergency_thrown_weapon's distance-bucketed score.
        actor = _myself(world_x=0, world_y=64)
        near = _enemy("obj01", CombatPhase.NORMAL, world_x=50, world_y=64)
        far = _enemy("obj02", CombatPhase.NORMAL, world_x=85, world_y=64)
        context = {
            actor,
            near,
            far,
            ThrowKnife(actor_slot="P1", target_slot="obj01"),
            ThrowKnife(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")

    def test_throw_pepper_scores_within_range_beyond_melee(self) -> None:
        actor = _myself(world_x=0, world_y=64)
        far_enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=60, world_y=64)
        context = {
            actor,
            far_enemy,
            ThrowPepper(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], ThrowPepper)

    def test_throw_pepper_scores_zero_when_still_in_melee(self) -> None:
        actor = _myself(world_x=0, world_y=64)
        near_enemy = _enemy("obj01", CombatPhase.NORMAL, world_x=10, world_y=64)
        context = {
            actor,
            near_enemy,
            ThrowPepper(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToNearEnemy)

    def test_open_breakable_in_range_scores_above_walking_to_an_enemy(self) -> None:
        # The in-range tier (16) is the former SmashBreakable's flat score.
        # 24px is inside the punch band proper -- past its 16px inner edge
        # and well within BREAKABLE_PUNCH_X. Standing on the prop's own
        # position, as this used to, is *not* in range: the box starts in
        # front of the actor, which is how the AI got stuck punching a prop
        # from 1px away for 94 seconds.
        myself = _myself(world_x=0, world_y=64)
        prop = Breakable(slot="obj01", world_x=24, world_y=64, type_id=0x70)
        enemy = _enemy("obj02", CombatPhase.NORMAL)
        context = {
            myself,
            prop,
            enemy,
            OpenBreakable(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], OpenBreakable)

    def test_open_breakable_picks_the_closer_of_two_candidates(self) -> None:
        # could_open_breakable (decide.py) does not pre-select the nearest
        # breakable -- this is determine_priority_verb's job, via
        # _emergency_open_breakable's distance score.
        myself = _myself(world_x=0, world_y=64)
        near = Breakable(slot="near", world_x=60, world_y=64, type_id=0x40)
        far = Breakable(slot="far", world_x=150, world_y=64, type_id=0x40)
        context = {
            myself,
            near,
            far,
            OpenBreakable(actor_slot="P1", target_slot="near"),
            OpenBreakable(actor_slot="P1", target_slot="far"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "near")

    def test_advance_stage_scores_zero_when_a_breakable_sits_ahead(self) -> None:
        # Same gate as decide.could_walk_to_advance_stage, so an injected
        # WalkToAdvanceStage cannot outrank OpenBreakable just because the
        # crate is far enough for the approach score to drop below 12.
        myself = _myself(world_x=0, world_y=64)
        prop = Breakable(slot="obj01", world_x=200, world_y=64, type_id=0x40)
        context = {
            myself,
            prop,
            CameraRange(left=0, right=400, top=0, bottom=200),
            Stage(level_index=0, direction="right"),
            OpenBreakable(actor_slot="P1", target_slot="obj01"),
            WalkToAdvanceStage(actor_slot="P1", direction="right"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], OpenBreakable)

    def test_open_breakable_scores_zero_when_target_missing(self) -> None:
        enemy = _enemy("obj02", CombatPhase.NORMAL)
        context = {
            enemy,
            OpenBreakable(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToNearEnemy)


def _stunned_grunt(slot: str, **overrides) -> Garcia:
    """A Grunt mid-hitstun by default (the ROM's $18-frame seed). Pass
    ``stun_timer=PEPPER_STUN_FRAMES`` for the long pepper-spray stun."""

    fields = dict(
        slot=slot,
        type_id=0x20,
        world_x=0,
        world_y=64,
        health=10,
        combat_phase=CombatPhase.STUNNED,
        targets_player=1,
        facing_left=False,
        stun_timer=HITSTUN_FRAMES,
    )
    fields.update(overrides)
    return Garcia(**fields)


class DetermineEmergencyStunnedTargetTests(unittest.TestCase):
    """A stunned Grunt is the one target that is not going anywhere: it
    cannot act and will still be standing there in a moment. Attacking it
    is capped so anything involving an enemy that *can* still act wins,
    without dropping so low that the actor abandons it."""

    def test_any_stun_loses_to_the_rear_attack_escape(self) -> None:
        # The case this cap exists for: a stunned body in front used to
        # score the punishable tier (60) and beat the $322A escape (55)
        # while a second, live enemy stood at the actor's back.
        myself = _myself(world_x=100, world_y=64, facing_left=False)
        behind = _enemy("obj02", CombatPhase.NORMAL, world_x=95, world_y=64)
        for frames in (HITSTUN_FRAMES, PEPPER_STUN_FRAMES):
            with self.subTest(stun_timer=frames):
                stunned = _stunned_grunt("obj01", world_x=130, stun_timer=frames)
                context = {
                    myself,
                    stunned,
                    behind,
                    Punch(actor_slot="P1", target_slot="obj01"),
                    RearAttack(actor_slot="P1", target_slot="obj02"),
                }

                result = determine_priority_verb(context)

                verbs = find_all(result, Verb)
                self.assertEqual(len(verbs), 1)
                self.assertIsInstance(verbs[0], RearAttack)

    def test_a_pepper_stunned_target_loses_to_a_strike_on_an_enemy_still_able_to_act(
        self,
    ) -> None:
        # $A0 frames is nearly three seconds of parked enemy: the tunnel
        # vision this cap exists to break.
        myself = _myself(world_x=100, world_y=64, facing_left=False)
        parked = _stunned_grunt("obj01", world_x=130, stun_timer=PEPPER_STUN_FRAMES)
        active = _enemy("obj02", CombatPhase.NORMAL, world_x=140, world_y=64)
        context = {
            myself,
            parked,
            active,
            Punch(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj02")

    def test_a_hitstunned_target_keeps_the_combo_going(self) -> None:
        # The other side of the same coin: $18 frames is the middle of the
        # ROM's own 3-hit chain, and it is the third hit that knocks the
        # enemy down. Switching to an equally punchable fresh enemy would
        # throw that away, so hitstun ranks just above a plain strike.
        myself = _myself(world_x=100, world_y=64, facing_left=False)
        combo_target = _stunned_grunt("obj01", world_x=130)
        active = _enemy("obj02", CombatPhase.NORMAL, world_x=140, world_y=64)
        context = {
            myself,
            combo_target,
            active,
            Punch(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")

    def test_a_pepper_stun_counted_down_into_hitstun_range_is_a_combo_again(self) -> None:
        # A pepper stun that has run down to its last frames is about to
        # end, which is exactly when treating it as a combo window is right.
        myself = _myself(world_x=100, world_y=64, facing_left=False)
        nearly_awake = _stunned_grunt("obj01", world_x=130, stun_timer=4)
        active = _enemy("obj02", CombatPhase.NORMAL, world_x=140, world_y=64)
        context = {
            myself,
            nearly_awake,
            active,
            Punch(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")

    def test_any_stun_still_beats_walking_off_to_another_enemy(self) -> None:
        # Lowered, not abandoned: nothing better on the table means keep
        # hitting the stunned body rather than fetching a distant enemy.
        myself = _myself(world_x=100, world_y=64, facing_left=False)
        far = _enemy("obj02", CombatPhase.NORMAL, world_x=300, world_y=64)
        for frames in (HITSTUN_FRAMES, PEPPER_STUN_FRAMES):
            with self.subTest(stun_timer=frames):
                stunned = _stunned_grunt("obj01", world_x=130, stun_timer=frames)
                context = {
                    myself,
                    stunned,
                    far,
                    Punch(actor_slot="P1", target_slot="obj01"),
                    WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
                }

                result = determine_priority_verb(context)

                verbs = find_all(result, Verb)
                self.assertEqual(len(verbs), 1)
                self.assertIsInstance(verbs[0], Punch)

    def test_any_stun_still_beats_retreating_and_advancing(self) -> None:
        # With nothing else bearing down, finishing the stunned enemy is
        # free damage and must beat both giving up ground and pushing on.
        # The committed enemy here is far enough away to produce no
        # IncomingMelee -- see the next test for when it is not.
        myself = _myself(world_x=100, world_y=64, facing_left=False)
        distant = _enemy("obj02", CombatPhase.ATTACKING, world_x=400, world_y=64)
        for frames in (HITSTUN_FRAMES, PEPPER_STUN_FRAMES):
            with self.subTest(stun_timer=frames):
                stunned = _stunned_grunt("obj01", world_x=130, stun_timer=frames)
                context = {
                    myself,
                    stunned,
                    distant,
                    Punch(actor_slot="P1", target_slot="obj01"),
                    RetreatFromDanger(actor_slot="P1", target_slot="obj02"),
                    WalkToAdvanceStage(actor_slot="P1", direction="right"),
                }

                result = determine_priority_verb(context)

                verbs = find_all(result, Verb)
                self.assertEqual(len(verbs), 1)
                self.assertIsInstance(verbs[0], Punch)

    def test_a_stun_loses_to_dealing_with_an_enemy_about_to_land_a_hit(self) -> None:
        """Reported from play: the AI took a punch in the back while hitting
        an enemy that was *already stunned*.

        That is the exact situation this whole ceiling exists for -- "a
        stunned enemy cannot act, cannot retaliate, and will still be
        standing there in a moment" -- but 21 and 19 both beat every response
        to the enemy that *can* act, so nothing ever interrupted the combo.
        The stunned body loses nothing by waiting a moment.
        """

        myself = _myself(world_x=100, world_y=64, facing_left=False)
        stunned = _stunned_grunt("obj01", world_x=130, stun_timer=HITSTUN_FRAMES)
        # Close enough behind to be an IncomingMelee this tick.
        behind = _enemy("obj02", CombatPhase.ATTACKING, world_x=55, world_y=64)
        context = {
            myself,
            stunned,
            behind,
            _camera(),
            Punch(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToNearEnemy)
        self.assertEqual(verbs[0].target_slot, "obj02")

    def test_a_live_target_is_still_worth_punching_under_the_same_threat(self) -> None:
        # The cap is about *parked* targets only. An enemy that can still act
        # is worth hitting even with another one closing in -- otherwise the
        # AI would never trade at all.
        myself = _myself(world_x=100, world_y=64, facing_left=False)
        live = _enemy("obj01", CombatPhase.NORMAL, world_x=130, world_y=64)
        behind = _enemy("obj02", CombatPhase.ATTACKING, world_x=55, world_y=64)
        context = {
            myself,
            live,
            behind,
            _camera(),
            Punch(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertIsInstance(verbs[0], Punch)

    def test_a_knocked_down_target_keeps_the_full_punishable_tier(self) -> None:
        # Only the *stun* is capped. A knockdown ends in a wake-up with
        # invulnerability, so that window really does have to be used now.
        myself = _myself(world_x=100, world_y=64, facing_left=False)
        knocked_down = _enemy("obj01", CombatPhase.KNOCKDOWN, world_x=130, world_y=64)
        active = _enemy("obj02", CombatPhase.NORMAL, world_x=140, world_y=64)
        context = {
            myself,
            knocked_down,
            active,
            Punch(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")

    def test_the_cap_never_raises_an_already_lower_score(self) -> None:
        # An unwarranted RearAttack scores 9; capping at 19 must not lift it
        # above the turn-around that decide.py offers for the same enemy.
        myself = _myself(world_x=100, world_y=64, facing_left=False)
        stunned_behind = _stunned_grunt("obj01", world_x=70)
        context = {
            myself,
            stunned_behind,
            RearAttack(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToNearEnemy)


class DetermineEmergencyGrabEnemyTests(unittest.TestCase):
    """GrabEnemy scores from the ``GrabOpportunity`` tokens inference raised
    for its own (actor, target) pair -- never from the verb's type."""

    def _grunt(self, slot: str, **overrides) -> Garcia:
        fields = dict(
            slot=slot,
            type_id=0x20,
            world_x=0,
            world_y=100,
            health=10,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=False,
        )
        fields.update(overrides)
        return Garcia(**fields)

    def test_clearing_the_rear_outranks_punching_the_same_enemy(self) -> None:
        # Axel at 100 facing right, one enemy in grab reach in front and one
        # inside the rear-threat box behind: the hold is what converts that
        # pincer into a backwards throw, so it must beat the plain strike.
        myself = _myself(world_x=100, world_y=100)
        front = self._grunt("front", world_x=130, world_y=100)
        behind = self._grunt("behind", world_x=60, world_y=100)
        context = {
            myself,
            front,
            behind,
            _camera(),
            GrabEnemy(actor_slot="P1", target_slot="front"),
            Punch(actor_slot="P1", target_slot="front"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], GrabEnemy)

    def test_clearing_the_rear_loses_to_the_escape_chord_against_a_commit(self) -> None:
        # An enemy already committed behind is not something to turn your
        # back on to walk into another body: the $322A escape wins.
        myself = _myself(world_x=100, world_y=100)
        front = self._grunt("front", world_x=130, world_y=100)
        behind = self._grunt(
            "behind", world_x=70, world_y=100, combat_phase=CombatPhase.ATTACKING
        )
        context = {
            myself,
            front,
            behind,
            _camera(),
            GrabEnemy(actor_slot="P1", target_slot="front"),
            RearAttack(actor_slot="P1", target_slot="behind"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], RearAttack)

    def test_grabbing_nora_outranks_punching_her(self) -> None:
        myself = _myself(world_x=100, world_y=100)
        nora = Nora(
            slot="nora",
            attack_ranges=(NORA_WHIP,),
            type_id=0x26,
            world_x=130,
            world_y=100,
            health=11,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
        )
        context = {
            myself,
            nora,
            _camera(),
            GrabEnemy(actor_slot="P1", target_slot="nora"),
            Punch(actor_slot="P1", target_slot="nora"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], GrabEnemy)

    def test_grabbing_nora_loses_to_a_free_hit_on_a_defenceless_enemy(self) -> None:
        # Her whip is a reason to prefer the hold in an ordinary fight, not a
        # reason to walk past an enemy that cannot defend itself at all.
        myself = _myself(world_x=100, world_y=100)
        nora = Nora(
            slot="nora",
            attack_ranges=(NORA_WHIP,),
            type_id=0x26,
            world_x=130,
            world_y=100,
            health=11,
            combat_phase=CombatPhase.NORMAL,
            targets_player=1,
            facing_left=True,
        )
        downed = self._grunt("downed", world_x=140, world_y=100, combat_phase=CombatPhase.KNOCKDOWN)
        context = {
            myself,
            nora,
            downed,
            _camera(),
            GrabEnemy(actor_slot="P1", target_slot="nora"),
            Punch(actor_slot="P1", target_slot="downed"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], Punch)

    def test_no_opportunity_left_drops_the_grab_out_of_contention(self) -> None:
        # The reason to close in is gone (lone ordinary enemy, no rear
        # threat), so the stale walk-in must not beat an ordinary punch.
        myself = _myself(world_x=100, world_y=100)
        front = self._grunt("front", world_x=130, world_y=100)
        context = {
            myself,
            front,
            _camera(),
            GrabEnemy(actor_slot="P1", target_slot="front"),
            Punch(actor_slot="P1", target_slot="front"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], Punch)


class DetermineEmergencyRearAttackTests(unittest.TestCase):
    """RearAttack's emergency only depends on the target's combat_phase, not
    on whether the candidate was triggered by the real band check or by a
    ClosingEnemy early-warning token -- confirms priority.py needed no
    change when could_rear_attack learned to react to ClosingEnemy."""

    def test_dangerous_target_wins_regardless_of_a_closing_enemy_token(self) -> None:
        dangerous = _enemy("objA", CombatPhase.ATTACKING)
        calm = _enemy("objB", CombatPhase.NORMAL)
        rear_dangerous = RearAttack(actor_slot="P1", target_slot="objA")
        rear_calm = RearAttack(actor_slot="P1", target_slot="objB")
        # objB's verb exists only because of the early-warning token, not
        # because it is in the real band -- must not out-rank a genuine
        # dangerous-phase target sitting in range.
        context = {
            dangerous,
            calm,
            rear_dangerous,
            rear_calm,
            ClosingEnemy(slot="objB"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIs(verbs[0], rear_dangerous)

    def test_loses_to_turning_around_when_the_chord_is_not_warranted(self) -> None:
        # The abuse case: a lone enemy at the actor's back, far enough out of
        # the punch dead zone that turning around and punching works. $322A
        # costs up to 21 frames of startup and hits only by current position,
        # so it must not be the reflex answer -- the turn-around
        # (WalkToNearEnemy, which decide.py now offers for this same enemy)
        # has to win.
        myself = _myself(world_x=100, world_y=100)  # Axel, facing right
        behind = _enemy("obj01", CombatPhase.NORMAL, world_x=70, world_y=100)
        context = {
            myself,
            behind,
            RearAttack(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToNearEnemy)

    def test_still_fires_when_it_is_the_only_option(self) -> None:
        # "Se poder usar, usar": nothing else reaches this enemy, so the
        # chord is still the verb -- de-preferring it must not mean
        # standing there doing nothing.
        myself = _myself(world_x=100, world_y=100)
        behind = _enemy("obj01", CombatPhase.NORMAL, world_x=70, world_y=100)
        context = {myself, behind, RearAttack(actor_slot="P1", target_slot="obj01")}

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], RearAttack)

    def test_outranks_turning_around_inside_the_punch_dead_zone(self) -> None:
        # dx=-6 is inside Axel's *usable* inner edge (punch_usable_inner_x,
        # 10 -- the 16px box edge less the body width that still overlaps
        # it): turning around leaves the enemy unhittable, so the chord is
        # the right tool and keeps its top-tier score.
        myself = _myself(world_x=100, world_y=100)
        behind = _enemy("obj01", CombatPhase.NORMAL, world_x=94, world_y=100)
        context = {
            myself,
            behind,
            RearAttack(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], RearAttack)

    def test_outranks_a_punch_while_boxed_in(self) -> None:
        # Flanked front and back: spending the turn hands the front enemy a
        # free hit, which is exactly what the chord exists for -- it must
        # beat punching either one.
        myself = _myself(world_x=100, world_y=100)
        behind = _enemy("obj01", CombatPhase.NORMAL, world_x=70, world_y=100)
        flanker = _enemy("obj02", CombatPhase.NORMAL, world_x=140, world_y=100)
        context = {
            myself,
            behind,
            flanker,
            RearAttack(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], RearAttack)

    def test_loses_to_a_punch_on_a_front_enemy_when_not_warranted(self) -> None:
        # Not boxed in (the punchable enemy is on the same side as nothing
        # else) and out of the dead zone: a fast, reliable strike wins.
        myself = _myself(world_x=100, world_y=100)
        behind = _enemy("obj01", CombatPhase.NORMAL, world_x=70, world_y=100)
        context = {
            myself,
            behind,
            RearAttack(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj01"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], Punch)


class DetermineEmergencyRetreatFromDangerTests(unittest.TestCase):
    def test_picks_the_closer_of_two_retreat_candidates(self) -> None:
        # Both distances stay inside reach.too_close_to_keep_approaching's
        # caution zone (Axel: punch_outer 50 + RETREAT_CAUTION_MARGIN 24), the
        # only range could_retreat_from_danger ever produces a candidate at.
        # An out-of-zone distance here would sit on the band's floor together
        # with everything else and make this pass or fail on the random
        # tie-break rather than on the ranking under test.
        # world_y sits inside the playable lane (LANE_Y_MIN..lane max): an
        # enemy outside it is not a live target at all, so no IncomingMelee
        # would be inferred and neither candidate would rank as a retreat.
        myself = _myself(world_x=0, world_y=64)
        near = _enemy("obj01", CombatPhase.ATTACKING, world_x=20, world_y=64)
        far = _enemy("obj02", CombatPhase.ATTACKING, world_x=70, world_y=64)
        context = {
            myself,
            near,
            far,
            RetreatFromDanger(actor_slot="P1", target_slot="obj01"),
            RetreatFromDanger(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertEqual(verbs[0].target_slot, "obj01")

    def test_outranks_walking_toward_a_different_far_enemy(self) -> None:
        # The actor can only do one thing -- backing away from an imminent,
        # not-yet-hittable threat must win over still approaching a
        # completely different, farther-off target.
        myself = _myself(world_x=0, world_y=64)
        dangerous_close = _enemy("obj01", CombatPhase.ATTACKING, world_x=60, world_y=64)
        calm_far = _enemy("obj02", CombatPhase.NORMAL, world_x=300, world_y=64)
        context = {
            myself,
            dangerous_close,
            calm_far,
            RetreatFromDanger(actor_slot="P1", target_slot="obj01"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], RetreatFromDanger)

    def test_loses_to_a_punch_on_a_different_enemy(self) -> None:
        # RetreatFromDanger's own docstring: "lower than any real attack so
        # attacking always wins once actually possible". Its band used to be
        # 30..20, which beat a plain Punch (20), a JumpAttack (18/28) and a
        # knife throw (21..25) -- so a dangerous enemy closing in made the
        # actor back away from a *different* enemy it could already hit.
        myself = _myself(world_x=0, world_y=64)
        dangerous_close = _enemy("obj01", CombatPhase.ATTACKING, world_x=20, world_y=64)
        punchable = _enemy("obj02", CombatPhase.NORMAL, world_x=40, world_y=64)
        context = {
            myself,
            dangerous_close,
            punchable,
            RetreatFromDanger(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], Punch)

    def test_loses_to_the_weakest_real_attack(self) -> None:
        # JumpAttack against a non-punishable target (18) is the lowest real
        # attack tier there is -- retreat must sit under even that.
        myself = _myself(world_x=0, world_y=64)
        dangerous_close = _enemy("obj01", CombatPhase.ATTACKING, world_x=20, world_y=64)
        kickable = _enemy("obj02", CombatPhase.NORMAL, world_x=60, world_y=64)
        context = {
            myself,
            dangerous_close,
            kickable,
            RetreatFromDanger(actor_slot="P1", target_slot="obj01"),
            JumpAttack(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], JumpAttack)

    def test_scores_zero_when_target_missing(self) -> None:
        # RetreatFromDanger for a target that has since vanished from the
        # context must not out-rank a real candidate for a present enemy.
        myself = _myself(world_x=0, world_y=64)
        present = _enemy("obj02", CombatPhase.NORMAL, world_x=10, world_y=64)
        context = {
            myself,
            present,
            RetreatFromDanger(actor_slot="P1", target_slot="obj01"),  # obj01 missing
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToNearEnemy)


class DetermineEmergencyProjectileSidestepTests(unittest.TestCase):
    def test_outranks_walking_toward_a_different_far_enemy(self) -> None:
        # A confirmed incoming projectile has no melee answer -- getting out
        # of its lane must win over still approaching an unrelated target.
        myself = _myself(world_x=100, world_y=64)
        projectile = Projectile(slot="obj10", world_x=150, world_y=64, vel_x=-5.0, vel_z=0.0, type_id=0x1E)
        calm_far = _enemy("obj02", CombatPhase.NORMAL, world_x=400, world_y=64)
        context = {
            myself,
            projectile,
            calm_far,
            ProjectileSidestep(actor_slot="P1", target_slot="obj10"),
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], ProjectileSidestep)

    def test_outranks_a_routine_punch_on_a_non_punishable_enemy(self) -> None:
        myself = _myself(world_x=100, world_y=64)
        projectile = Projectile(slot="obj10", world_x=150, world_y=64, vel_x=-5.0, vel_z=0.0, type_id=0x1E)
        punchable = _enemy("obj02", CombatPhase.NORMAL, world_x=120, world_y=64)
        context = {
            myself,
            projectile,
            punchable,
            ProjectileSidestep(actor_slot="P1", target_slot="obj10"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], ProjectileSidestep)

    def test_loses_to_a_punishable_punch(self) -> None:
        # A free hit on a punish window (60) beats dodging a throw that might
        # still be avoided on its own -- see the constant's own comment.
        myself = _myself(world_x=100, world_y=64)
        projectile = Projectile(slot="obj10", world_x=150, world_y=64, vel_x=-5.0, vel_z=0.0, type_id=0x1E)
        stunned = _enemy("obj02", CombatPhase.STUNNED, world_x=120, world_y=64)
        context = {
            myself,
            projectile,
            stunned,
            ProjectileSidestep(actor_slot="P1", target_slot="obj10"),
            Punch(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], Punch)

    def test_scores_zero_when_projectile_missing(self) -> None:
        myself = _myself(world_x=0, world_y=64)
        present = _enemy("obj02", CombatPhase.NORMAL, world_x=10, world_y=64)
        context = {
            myself,
            present,
            ProjectileSidestep(actor_slot="P1", target_slot="obj10"),  # obj10 missing
            WalkToNearEnemy(actor_slot="P1", target_slot="obj02"),
        }

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIsInstance(verbs[0], WalkToNearEnemy)


class DeterminePriorityTieBreakTests(unittest.TestCase):
    def test_priority_field_breaks_an_emergency_tie(self) -> None:
        enemy_a = _enemy("objA", CombatPhase.NORMAL)  # non-punishable -> emergency 20
        enemy_b = _enemy("objB", CombatPhase.NORMAL)  # non-punishable -> emergency 20
        low = Punch(actor_slot="P1", target_slot="objA", priority=5)
        high = Punch(actor_slot="P1", target_slot="objB", priority=50)
        context = {enemy_a, enemy_b, low, high}

        result = determine_priority_verb(context)

        verbs = find_all(result, Verb)
        self.assertEqual(len(verbs), 1)
        self.assertIs(verbs[0], high)


class DeterminePriorityTieTests(unittest.TestCase):
    """Ties between same-class verbs aimed at different targets are routine
    by design -- a ``could_*`` produces one candidate per valid target and
    never pre-selects -- so the tie-break runs constantly and its *stability*
    is what matters, not which candidate it favours."""

    def _tied_context(self):
        enemy_a = _enemy("objA", CombatPhase.NORMAL)
        enemy_b = _enemy("objB", CombatPhase.NORMAL)
        punch_a = Punch(actor_slot="P1", target_slot="objA")
        punch_b = Punch(actor_slot="P1", target_slot="objB")
        return {enemy_a, enemy_b, punch_a, punch_b}, punch_a, punch_b

    def test_exact_tie_picks_exactly_one(self) -> None:
        context, punch_a, punch_b = self._tied_context()

        verbs = find_all(determine_priority_verb(context), Verb)

        self.assertEqual(len(verbs), 1)
        self.assertIn(verbs[0], (punch_a, punch_b))

    def test_exact_tie_resolves_to_the_same_verb_every_time(self) -> None:
        # The regression that matters. This used to be random.choice, which
        # is defensible for one tick and disastrous over a run of them: the
        # whole decision is remade every poll, so re-rolling swapped targets
        # ~15 times a second and re-aimed the D-pad with each swap. Measured
        # live as the AI hunting between two enemies instead of committing.
        winners = set()
        for _ in range(50):
            context, _, _ = self._tied_context()
            winners.add(find_all(determine_priority_verb(context), Verb)[0])

        self.assertEqual(
            len(winners), 1, f"tie-break is not deterministic: {winners}"
        )


class AntonioVerbEmergencyTests(unittest.TestCase):
    def test_dodge_outranks_punching_antonio(self) -> None:
        myself = Myself(
            slot="P1",
            player_index=1,
            character_id=0,
            character_name="Axel",
            world_x=120,
            world_y=100,
            health=80,
            health_percent=100.0,
            lives=3,
            specials=1,
            held_weapon_type=0,
            facing_left=False,
            combat_phase=CombatPhase.NORMAL,
            action_state=0,
            is_airborne=False,
        )
        antonio = Antonio(
            slot="obj09",
            type_id=0x56,
            world_x=160,
            world_y=100,
            health=40,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
            facing_left=True,
            primary_state=2,
            boss_dist_x=40,
            boss_dist_lane=4,
        )
        context = {
            myself,
            antonio,
            Punch(actor_slot="P1", target_slot="obj09"),
            DodgeAntonioKick(actor_slot="P1", target_slot="obj09"),
        }
        winner = find_all(determine_priority_verb(context), Verb)[0]
        self.assertIsInstance(winner, DodgeAntonioKick)

    def test_hitting_the_boomerang_outranks_sidestepping_it(self) -> None:
        myself = Myself(
            slot="P1",
            player_index=1,
            character_id=0,
            character_name="Axel",
            world_x=100,
            world_y=100,
            health=80,
            health_percent=100.0,
            lives=3,
            specials=1,
            held_weapon_type=0,
            facing_left=False,
            combat_phase=CombatPhase.NORMAL,
            action_state=0,
            is_airborne=False,
        )
        boomerang = Projectile(
            slot="obj10", world_x=130, world_y=100, vel_x=-8.0, vel_z=0.0, type_id=0x96
        )
        context = {
            myself,
            boomerang,
            HitAntonioBoomerang(actor_slot="P1", target_slot="obj10"),
            ProjectileSidestep(actor_slot="P1", target_slot="obj10"),
        }
        winner = find_all(determine_priority_verb(context), Verb)[0]
        self.assertIsInstance(winner, HitAntonioBoomerang)

    def test_punching_the_boomerang_beats_jumping_the_kick(self) -> None:
        myself = Myself(
            slot="P1",
            player_index=1,
            character_id=0,
            character_name="Axel",
            world_x=100,
            world_y=100,
            health=80,
            health_percent=100.0,
            lives=3,
            specials=1,
            held_weapon_type=0,
            facing_left=False,
            combat_phase=CombatPhase.NORMAL,
            action_state=0,
            is_airborne=False,
        )
        antonio = Antonio(
            slot="obj09",
            type_id=0x56,
            world_x=160,
            world_y=100,
            health=40,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
            facing_left=True,
            primary_state=2,
            boss_dist_x=40,
            boss_dist_lane=4,
        )
        boomerang = Projectile(
            slot="obj10", world_x=130, world_y=100, vel_x=-8.0, vel_z=0.0, type_id=0x96
        )
        context = {
            myself,
            antonio,
            boomerang,
            HitAntonioBoomerang(actor_slot="P1", target_slot="obj10"),
            DodgeAntonioKick(actor_slot="P1", target_slot="obj09"),
        }
        winner = find_all(determine_priority_verb(context), Verb)[0]
        self.assertIsInstance(winner, HitAntonioBoomerang)


if __name__ == "__main__":
    unittest.main()
