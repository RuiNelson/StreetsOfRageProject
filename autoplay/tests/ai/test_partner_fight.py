"""Leave the partner's fight to them.

User: "a IA a tentar atacar o mesmo inimigo que o partner já está a atacar ou
perto de atacar, estuda bem o assunto e evita isso!". Four pieces:

- ``reach.partner_is_engaging``: what counts as the partner fighting an enemy;
- ``partner.PartnerFightTracker``: the claim, and its memory across ticks;
- ``partner.do_not_harm_partner``: the actor's attacks on a claimed enemy
  withdrawn, bar self-defence;
- the whole pipeline: with two enemies, the actor goes for the one the
  partner is not fighting.
"""

import unittest

from sor_autoplay.ai import reach
from sor_autoplay.ai.decide import generate_verb_tokens
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.partner import (
    PARTNER_FIGHT_MEMORY_FRAMES,
    PartnerFightTracker,
    do_not_harm_partner,
)
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.kinematics import FRAMES_PER_TICK
from sor_autoplay.ai.tokens import (
    CameraRange,
    Garcia,
    GrabEnemy,
    JumpAttack,
    Myself,
    Partner,
    PartnerFight,
    Punch,
    Verb,
    WalkToNearEnemy,
    find_all,
)
from sor_autoplay.phases import CombatPhase

CAMERA = CameraRange(left=0, right=400, top=0, bottom=200)


def make_myself(**overrides) -> Myself:
    fields = dict(
        slot="P1",
        player_index=1,
        character_id=0,
        character_name="Axel",
        world_x=100,
        world_y=80,
        world_z=160,
        ground_z=160,
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


def make_partner(**overrides) -> Partner:
    fields = dict(
        slot="P2",
        player_index=2,
        character_id=2,
        character_name="Blaze",
        world_x=300,
        world_y=80,
        world_z=160,
        ground_z=160,
        health=80,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=True,
        combat_phase=CombatPhase.NORMAL,
        action_state=0x03,
        is_airborne=False,
    )
    fields.update(overrides)
    return Partner(**fields)


def make_enemy(slot: str = "obj01", **overrides) -> Garcia:
    fields = dict(
        slot=slot,
        type_id=0x20,
        world_x=270,
        world_y=80,
        health=10,
        combat_phase=CombatPhase.NORMAL,
        targets_player=2,
        facing_left=False,
    )
    fields.update(overrides)
    return Garcia(**fields)


def verbs(context) -> set[Verb]:
    return set(find_all(context, Verb))


class PartnerIsEngagingTests(unittest.TestCase):
    def test_a_strike_of_theirs_that_reaches_it(self) -> None:
        self.assertTrue(reach.partner_is_engaging(make_partner(), make_enemy(world_x=270)))

    def test_a_few_steps_short_and_facing_it(self) -> None:
        # Blaze's punch reaches 60; 20 more is her arriving, not passing.
        self.assertTrue(reach.partner_is_engaging(make_partner(), make_enemy(world_x=220)))
        self.assertFalse(reach.partner_is_engaging(make_partner(), make_enemy(world_x=200)))

    def test_not_behind_them(self) -> None:
        self.assertFalse(
            reach.partner_is_engaging(make_partner(facing_left=False), make_enemy(world_x=270))
        )

    def test_not_off_their_lane(self) -> None:
        self.assertFalse(
            reach.partner_is_engaging(make_partner(), make_enemy(world_x=270, world_y=110))
        )

    def test_holding_it_wherever_it_stands(self) -> None:
        holding = make_partner(action_state=0x61, held_enemy_slot="obj01")
        self.assertTrue(reach.partner_is_engaging(holding, make_enemy(world_x=900)))

    def test_not_while_the_partner_is_the_one_held(self) -> None:
        held = make_partner(action_state=0x7B, combat_phase=CombatPhase.HELD_BY_ENEMY)
        self.assertFalse(reach.partner_is_engaging(held, make_enemy(world_x=270)))

    def test_a_kick_in_flight_that_lands_on_it(self) -> None:
        flying = make_partner(
            world_z=146,
            vel_x=-3.375,
            vel_z=-6.59375,
            action_state=0x13,
            is_airborne=True,
        )
        self.assertTrue(reach.partner_is_engaging(flying, make_enemy(world_x=240)))
        self.assertFalse(reach.partner_is_engaging(flying, make_enemy(world_x=100)))


class TrackerTests(unittest.TestCase):
    def test_claims_what_the_partner_engages(self) -> None:
        tracker = PartnerFightTracker()
        context = {make_myself(), make_partner(), make_enemy("obj01"), make_enemy("obj02", world_x=140)}
        self.assertEqual(tracker.update(context), {PartnerFight(enemy_slot="obj01")})

    def test_the_claim_outlives_a_short_gap_and_then_lapses(self) -> None:
        tracker = PartnerFightTracker()
        tracker.update({make_myself(), make_partner(), make_enemy(world_x=270)})
        knocked_back = {make_myself(), make_partner(), make_enemy(world_x=150)}
        memory_ticks = PARTNER_FIGHT_MEMORY_FRAMES // FRAMES_PER_TICK
        for _ in range(memory_ticks):
            self.assertEqual(tracker.update(knocked_back), {PartnerFight(enemy_slot="obj01")})
        self.assertEqual(tracker.update(knocked_back), set())

    def test_no_partner_no_claims(self) -> None:
        tracker = PartnerFightTracker()
        self.assertEqual(tracker.update({make_myself(), make_enemy()}), set())

    def test_a_body_that_is_gone_is_forgotten(self) -> None:
        tracker = PartnerFightTracker()
        tracker.update({make_myself(), make_partner(), make_enemy(world_x=270)})
        tracker.update({make_myself(), make_partner()})
        # The slot reused for a fresh enemy far from the partner is nobody's.
        fresh = {make_myself(), make_partner(), make_enemy(world_x=140)}
        self.assertEqual(tracker.update(fresh), set())


class FilterTests(unittest.TestCase):
    def _context(self, verb, *, claimed=True, **enemy):
        tokens = {make_myself(), make_partner(), make_enemy(**enemy), verb}
        if claimed:
            tokens.add(PartnerFight(enemy_slot="obj01"))
        return tokens

    def test_attacks_on_the_partners_enemy_are_withdrawn(self) -> None:
        for verb in (
            WalkToNearEnemy(actor_slot="P1", target_slot="obj01"),
            Punch(actor_slot="P1", target_slot="obj01"),
            JumpAttack(actor_slot="P1", target_slot="obj01"),
            GrabEnemy(actor_slot="P1", target_slot="obj01"),
        ):
            with self.subTest(verb=type(verb).__name__):
                self.assertEqual(verbs(do_not_harm_partner(self._context(verb))), set())

    def test_an_enemy_nobody_claims_is_fair_game(self) -> None:
        walk = WalkToNearEnemy(actor_slot="P1", target_slot="obj01")
        self.assertEqual(verbs(do_not_harm_partner(self._context(walk, claimed=False))), {walk})

    def test_self_defence_is_never_withdrawn(self) -> None:
        # Committed and on top of the actor: answered whoever claims it.
        punch = Punch(actor_slot="P1", target_slot="obj01")
        context = self._context(
            punch, world_x=125, combat_phase=CombatPhase.ATTACKING, facing_left=True
        )
        self.assertEqual(verbs(do_not_harm_partner(context)), {punch})

    def test_a_kick_already_in_the_air_is_never_withdrawn(self) -> None:
        hop = JumpAttack(actor_slot="P1", target_slot="obj01")
        context = {
            make_myself(is_airborne=True, action_state=0x16),
            make_partner(),
            make_enemy(),
            PartnerFight(enemy_slot="obj01"),
            hop,
        }
        self.assertEqual(verbs(do_not_harm_partner(context)), {hop})


class PipelineTests(unittest.TestCase):
    def _run(self, *enemies):
        tracker = PartnerFightTracker()
        context = {make_myself(), make_partner(), CAMERA, *enemies}
        context |= generate_inference_tokens(context)
        context |= tracker.update(context)
        context |= generate_verb_tokens(context)
        context = do_not_harm_partner(context)
        return find_all(determine_priority_verb(context), Verb)

    def test_the_actor_takes_the_enemy_the_partner_is_not_fighting(self) -> None:
        theirs = make_enemy("obj01", world_x=270)
        free = make_enemy("obj02", world_x=160, targets_player=1, facing_left=True)
        winner = self._run(theirs, free)
        self.assertEqual(len(winner), 1)
        self.assertEqual(winner[0].target_slot, "obj02")

    def test_with_only_the_partners_enemy_left_the_actor_leaves_it(self) -> None:
        winner = self._run(make_enemy("obj01", world_x=270))
        self.assertFalse(any(getattr(v, "target_slot", None) == "obj01" for v in winner))


if __name__ == "__main__":
    unittest.main()
