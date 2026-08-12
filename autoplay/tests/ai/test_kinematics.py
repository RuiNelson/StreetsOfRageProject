"""Tests for ``ai/kinematics.py`` and ``Enemy.predict_position_after_n_frames``.

Two things are checked here. First the arithmetic itself -- the prediction is
in 60 Hz game frames (the unit the ROM integrates velocity in), and the
interception solve accounts for the target's own movement. Second, and more
important structurally: **every** concrete ``Attack`` verb has a kinematic
model registered, so an attack added later cannot quietly go back to aiming at
a stale position.
"""

import sys
import unittest
from abc import ABC

from sor_autoplay.ai import kinematics
from sor_autoplay.ai.tokens import (
    Abadede,
    Attack,
    Garcia,
    JumpAttack,
    Myself,
    Punch,
    RearAttack,
    Signal,
    ThrowKnife,
    ThrowPepper,
)
from sor_autoplay.phases import CombatPhase

AXEL, ADAM, BLAZE = 0, 1, 2


def _myself(**overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=AXEL,
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


def _garcia(**overrides) -> Garcia:
    fields = dict(
        slot="obj01",
        type_id=0x20,
        world_x=200,
        world_y=100,
        health=11,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
    )
    fields.update(overrides)
    return Garcia(**fields)


def _abadede(**overrides) -> Abadede:
    fields = dict(
        slot="obj09",
        type_id=0x30,
        world_x=200,
        world_y=100,
        health=40,
        combat_phase=CombatPhase.NORMAL,
        targets_player=1,
        facing_left=True,
    )
    fields.update(overrides)
    return Abadede(**fields)


class PredictPositionTests(unittest.TestCase):
    def test_applies_velocity_once_per_frame(self) -> None:
        # Signal's slide: ~2.5 px per 60 Hz frame on X (enemy-ai.md $00E568).
        signal = Signal(
            slot="obj01",
            type_id=0x24,
            world_x=300,
            world_y=100,
            health=11,
            combat_phase=CombatPhase.ATTACKING,
            targets_player=1,
            facing_left=True,
            grunt_vel_x=-2.5,
            grunt_vel_y=2.0,
        )

        self.assertEqual(signal.predict_position_after_n_frames(12), (270, 124))

    def test_zero_frames_is_the_current_position(self) -> None:
        garcia = _garcia(grunt_vel_x=-2.75, grunt_vel_y=2.125)

        self.assertEqual(
            garcia.predict_position_after_n_frames(0),
            (garcia.world_x, garcia.world_y),
        )

    def test_a_stationary_enemy_predicts_to_itself(self) -> None:
        garcia = _garcia()

        self.assertEqual(garcia.predict_position_after_n_frames(30), (200, 100))

    def test_a_boss_predicts_to_itself(self) -> None:
        # A Boss never populates the ordinary-enemy velocity fields, so the
        # honest prediction is "no better guess than where it stands".
        self.assertEqual(_abadede().predict_position_after_n_frames(30), (200, 100))

    def test_rounds_to_whole_pixels(self) -> None:
        garcia = _garcia(world_x=200, grunt_vel_x=-2.75)

        # 3 frames * 2.75 = 8.25 px.
        self.assertEqual(garcia.predict_position_after_n_frames(3)[0], 192)


class InterceptFramesTests(unittest.TestCase):
    def test_a_stationary_target_is_gap_over_speed(self) -> None:
        actor = _myself(world_x=100)
        garcia = _garcia(world_x=200, grunt_vel_x=0.0)

        frames = kinematics.intercept_frames(actor, garcia, approach_speed=10.0)

        self.assertEqual(frames, 10)

    def test_a_target_walking_in_is_met_sooner(self) -> None:
        actor = _myself(world_x=100)
        closing = _garcia(world_x=200, grunt_vel_x=-10.0)

        self.assertLess(
            kinematics.intercept_frames(actor, closing, approach_speed=10.0),
            kinematics.intercept_frames(
                actor, _garcia(world_x=200, grunt_vel_x=0.0), approach_speed=10.0
            ),
        )

    def test_a_target_walking_away_is_met_later(self) -> None:
        actor = _myself(world_x=100)
        fleeing = _garcia(world_x=200, grunt_vel_x=10.0)

        self.assertGreater(
            kinematics.intercept_frames(actor, fleeing, approach_speed=16.0),
            kinematics.intercept_frames(
                actor, _garcia(world_x=200, grunt_vel_x=0.0), approach_speed=16.0
            ),
        )

    def test_an_uncatchable_target_reports_the_trust_horizon(self) -> None:
        # Fleeing at exactly the approach speed: never caught. Reported as
        # the horizon rather than infinity, so the projection simply lands
        # outside every band.
        actor = _myself(world_x=100)
        fleeing = _garcia(world_x=200, grunt_vel_x=3.0)

        self.assertEqual(
            kinematics.intercept_frames(actor, fleeing, approach_speed=3.0),
            kinematics.MAX_LEAD_FRAMES,
        )

    def test_the_side_the_target_is_on_does_not_change_the_answer(self) -> None:
        # Mirrored setup: enemy to the left, closing rightwards.
        actor = _myself(world_x=100)
        right = kinematics.intercept_frames(
            actor, _garcia(world_x=200, grunt_vel_x=-2.0), approach_speed=4.0
        )
        left = kinematics.intercept_frames(
            actor, _garcia(world_x=0, grunt_vel_x=2.0), approach_speed=4.0
        )

        self.assertEqual(right, left)

    def test_a_free_gap_is_subtracted_before_the_divide(self) -> None:
        actor = _myself(world_x=100)
        garcia = _garcia(world_x=200, grunt_vel_x=0.0)

        self.assertEqual(
            kinematics.intercept_frames(
                actor, garcia, approach_speed=10.0, gap_closed=50.0
            ),
            5,
        )

    def test_a_target_already_inside_the_free_gap_needs_no_travel(self) -> None:
        actor = _myself(world_x=100)
        garcia = _garcia(world_x=120, grunt_vel_x=0.0)

        self.assertEqual(
            kinematics.intercept_frames(
                actor, garcia, approach_speed=3.0, gap_closed=50.0
            ),
            0,
        )


class LeadFramesTests(unittest.TestCase):
    def test_a_punch_leads_by_its_measured_startup(self) -> None:
        # Axel/Adam 3 frames, Blaze 5 (controls-and-input.md "Measured
        # normal punch"), plus the pipeline's own poll latency.
        for character_id, startup in ((AXEL, 3), (ADAM, 3), (BLAZE, 5)):
            with self.subTest(character_id=character_id):
                self.assertEqual(
                    kinematics.melee_strike_lead_frames(_myself(character_id=character_id)),
                    kinematics.AI_LATENCY_FRAMES + startup,
                )

    def test_adams_chord_leads_far_longer_than_axels(self) -> None:
        # 21 frames against 3 (controls-and-input.md "Measured chord
        # timing") -- the whole reason RearAttack aimed at a current
        # position whiffs for Adam.
        axel = kinematics.rear_attack_lead_frames(_myself(character_id=AXEL))
        adam = kinematics.rear_attack_lead_frames(_myself(character_id=ADAM))

        self.assertEqual(adam - axel, 18)

    def test_a_walking_target_is_predicted_clear_of_adams_chord(self) -> None:
        # An enemy walking away at an ordinary grunt speed covers more than
        # the depth of Adam's own chord box during his 21-frame wind-up.
        adam = _myself(character_id=ADAM, world_x=100)
        garcia = _garcia(world_x=130, grunt_vel_x=2.0)

        lead = kinematics.rear_attack_lead_frames(adam, garcia)
        predicted_x, _ = garcia.predict_position_after_n_frames(lead)

        self.assertGreater(predicted_x - garcia.world_x, 40)

    def test_a_jump_kick_leads_by_crouch_plus_flight(self) -> None:
        actor = _myself(character_id=AXEL, world_x=100)
        # 100px out; the kick's box covers the last punch_outer_x (50), so
        # 50px of flight at 3.0 px/frame ~ 17 frames, plus the 5-frame
        # crouch and the poll latency.
        garcia = _garcia(world_x=200, grunt_vel_x=0.0)

        self.assertEqual(
            kinematics.jump_attack_lead_frames(actor, garcia),
            kinematics.AI_LATENCY_FRAMES + kinematics.JUMP_CROUCH_FRAMES + 17,
        )

    def test_a_jump_kick_leads_further_for_a_further_target(self) -> None:
        actor = _myself(world_x=100)

        near = kinematics.jump_attack_lead_frames(actor, _garcia(world_x=170))
        far = kinematics.jump_attack_lead_frames(actor, _garcia(world_x=230))

        self.assertGreater(far, near)

    def test_an_airborne_actor_only_leads_by_its_own_latency(self) -> None:
        # The crouch and most of the flight are already behind it, and the
        # trajectory is fixed -- only the B edge is left.
        actor = _myself(world_x=100, is_airborne=True)

        self.assertEqual(
            kinematics.jump_attack_lead_frames(actor, _garcia(world_x=200)),
            kinematics.AI_LATENCY_FRAMES,
        )

    def test_a_grab_walk_in_uses_the_roms_own_walk_speed(self) -> None:
        # Blaze walks 3.25 px/frame against Adam's 2.5 ($3670/$3706/$379C),
        # so the same gap is a shorter walk-in for her.
        blaze = kinematics.grab_lead_frames(
            _myself(character_id=BLAZE, world_x=100), _garcia(world_x=220)
        )
        adam = kinematics.grab_lead_frames(
            _myself(character_id=ADAM, world_x=100), _garcia(world_x=220)
        )

        self.assertLess(blaze, adam)

    def test_pepper_leads_further_than_a_knife_at_the_same_range(self) -> None:
        # 6 px/frame against 16 (weapons-range-and-damage.md section 4).
        actor = _myself(world_x=100)
        garcia = _garcia(world_x=190)

        self.assertGreater(
            kinematics.throw_pepper_lead_frames(actor, garcia),
            kinematics.throw_knife_lead_frames(actor, garcia),
        )

    def test_a_held_or_static_or_aimless_move_leads_by_nothing(self) -> None:
        # Not an omission: a held body travels with the actor, a prop does
        # not move, and the police special has no aim point at all.
        actor = _myself()
        for model in (
            kinematics.held_target_lead_frames,
            kinematics.static_target_lead_frames,
            kinematics.no_aim_point_lead_frames,
        ):
            with self.subTest(model=model.__name__):
                self.assertEqual(model(actor, _garcia()), 0)

    def test_every_lead_stays_inside_the_trust_horizon(self) -> None:
        actor = _myself(world_x=100)
        # Far away and fleeing: the worst case for every model.
        fleeing = _garcia(world_x=400, grunt_vel_x=3.0)

        for verb_cls, model in kinematics.ATTACK_LEAD_FRAMES.items():
            with self.subTest(verb=verb_cls.__name__):
                lead = model(actor, fleeing)
                self.assertGreaterEqual(lead, 0)
                self.assertLessEqual(lead, kinematics.MAX_LEAD_FRAMES)


def _concrete_attacks() -> list[type[Attack]]:
    """Every instantiable ``Attack`` subclass, however deeply nested.

    Two wrinkles in walking ``__subclasses__`` over this hierarchy:

    - the branch ABCs (``MeleeAttacks``, ``GrabMechanics``,
      ``MeleeWeaponAttacks``, ``WeaponAttacks``) are plain dataclasses with
      no abstract methods, so they are recognised the way they are declared:
      by listing ``ABC`` among their own bases;
    - every token here is ``@dataclass(slots=True)``, which cannot add
      ``__slots__`` to an existing class and therefore *replaces* it with a
      new one. The original stays registered as a subclass of ``Attack``, so
      the walk yields two objects per verb -- the live one bound to its
      module, and a discarded pre-slots twin of the same name. Only the
      former is ever instantiated, and it is the one the registry keys on.
    """

    found: list[type[Attack]] = []
    stack = list(Attack.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if ABC in cls.__bases__:
            continue
        if getattr(sys.modules[cls.__module__], cls.__name__, None) is not cls:
            continue  # pre-slots twin, see above
        found.append(cls)
    return found


class RegistryTotalityTests(unittest.TestCase):
    def test_every_concrete_attack_verb_has_a_kinematic_model(self) -> None:
        missing = [
            cls.__name__
            for cls in _concrete_attacks()
            if cls not in kinematics.ATTACK_LEAD_FRAMES
        ]

        self.assertEqual(
            missing,
            [],
            "every concrete Attack must declare how it predicts its target: "
            "add it to kinematics.ATTACK_LEAD_FRAMES (a zero-lead model is a "
            "valid answer -- see held_target_lead_frames)",
        )

    def test_the_registry_names_no_verb_that_is_not_an_attack(self) -> None:
        for verb_cls in kinematics.ATTACK_LEAD_FRAMES:
            with self.subTest(verb=verb_cls.__name__):
                self.assertTrue(issubclass(verb_cls, Attack))

    def test_lead_frames_dispatches_through_the_registry(self) -> None:
        actor = _myself(character_id=BLAZE)

        self.assertEqual(
            kinematics.lead_frames(Punch, actor),
            kinematics.melee_strike_lead_frames(actor),
        )
        self.assertEqual(
            kinematics.lead_frames(RearAttack, actor),
            kinematics.rear_attack_lead_frames(actor),
        )

    def test_target_at_impact_moves_the_target_by_its_own_lead(self) -> None:
        actor = _myself(character_id=AXEL, world_x=100)
        garcia = _garcia(world_x=200, grunt_vel_x=-2.0)

        punched = kinematics.target_at_impact(Punch, actor, garcia)
        kicked = kinematics.target_at_impact(JumpAttack, actor, garcia)

        # The kick's lead is much longer, so it predicts much further along
        # the same approach.
        self.assertLess(kicked.world_x, punched.world_x)
        self.assertLess(punched.world_x, garcia.world_x)

    def test_the_thrown_weapons_predict_differently_from_each_other(self) -> None:
        actor = _myself(world_x=100)
        garcia = _garcia(world_x=190, grunt_vel_x=-2.0)

        knife = kinematics.target_at_impact(ThrowKnife, actor, garcia)
        pepper = kinematics.target_at_impact(ThrowPepper, actor, garcia)

        self.assertLess(pepper.world_x, knife.world_x)


if __name__ == "__main__":
    unittest.main()
