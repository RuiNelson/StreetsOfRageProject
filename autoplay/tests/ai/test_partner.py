"""``do_not_harm_partner`` — the co-op courtesy filter (``ai/partner.py``).

Every test here builds the *post*-``generate_verb_tokens`` half of a context
by hand: the filter's whole contract is what it removes from a set of verbs
that already exist, so producing them through the real ``could_*`` chain
would only make the assertions depend on unrelated production gates.
"""

import unittest

from sor_autoplay.ai.decide import generate_verb_tokens
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.partner import do_not_harm_partner
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import (
    AttackHeldEnemy,
    Breakable,
    CallPolice,
    CounterGrab,
    Enemy,
    FlipHold,
    Garcia,
    GrabEnemy,
    HealthPickup,
    JumpAttack,
    LifePickup,
    MeleeWeaponAttack,
    Myself,
    OpenBreakable,
    Partner,
    Punch,
    RearAttack,
    ReleasePartner,
    ReleaseToRegrab,
    ScorePickup,
    SpecialPickup,
    Supplex,
    ThrowHeldEnemy,
    ThrowKnife,
    Verb,
    WalkToPickup,
    WalkToWeapon,
    Weapon,
    find_all,
)
from sor_autoplay.phases import CombatPhase


def make_myself(**overrides) -> Myself:
    fields = dict(
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
    fields.update(overrides)
    return Myself(**fields)


def make_partner(**overrides) -> Partner:
    fields = dict(
        slot="P2",
        player_index=2,
        character_id=2,
        character_name="Blaze",
        world_x=100,
        world_y=100,
        health=80,
        health_percent=100.0,
        lives=3,
        specials=1,
        held_weapon_type=0,
        facing_left=True,
        combat_phase=CombatPhase.NORMAL,
        action_state=0,
        is_airborne=False,
    )
    fields.update(overrides)
    return Partner(**fields)


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
    return Garcia(**fields)


def verbs(context) -> set[Verb]:
    return set(find_all(context, Verb))


class NoPartnerTests(unittest.TestCase):
    def test_no_partner_is_a_no_op(self):
        actor = make_myself()
        enemy = make_enemy(world_x=130)
        punch = Punch(actor_slot="P1", target_slot="obj01")
        context = {actor, enemy, punch}
        # Same object back, not merely an equal one: nothing to filter.
        self.assertIs(do_not_harm_partner(context), context)


class ForwardStrikeTests(unittest.TestCase):
    """A B press lands on whatever body is in the box -- ``$4478``."""

    def _context(self, verb, *, partner_x):
        return {
            make_myself(),
            make_partner(world_x=partner_x),
            make_enemy(world_x=130),
            verb,
        }

    def test_punch_withdrawn_with_partner_in_the_box(self):
        punch = Punch(actor_slot="P1", target_slot="obj01")
        self.assertEqual(verbs(do_not_harm_partner(self._context(punch, partner_x=130))), set())

    def test_punch_kept_with_partner_out_of_reach(self):
        punch = Punch(actor_slot="P1", target_slot="obj01")
        kept = do_not_harm_partner(self._context(punch, partner_x=220))
        self.assertEqual(verbs(kept), {punch})

    def test_punch_kept_with_partner_behind_the_actor(self):
        punch = Punch(actor_slot="P1", target_slot="obj01")
        # Facing right, so a body 30px to the left is behind: the forward
        # strike cannot reach it (reach.punch_would_connect).
        kept = do_not_harm_partner(self._context(punch, partner_x=70))
        self.assertEqual(verbs(kept), {punch})

    def test_armed_strike_withdrawn_too(self):
        swing = MeleeWeaponAttack(actor_slot="P1", target_slot="obj01", weapon_type=0x0A)
        context = {
            make_myself(held_weapon_type=0x0A),
            make_partner(world_x=125),
            make_enemy(world_x=130),
            swing,
        }
        self.assertEqual(verbs(do_not_harm_partner(context)), set())

    def test_grab_is_never_withdrawn(self):
        """``GrabEnemy`` presses nothing, so ``+$34`` stays zero."""

        grab = GrabEnemy(actor_slot="P1", target_slot="obj01")
        kept = do_not_harm_partner(self._context(grab, partner_x=130))
        self.assertEqual(verbs(kept), {grab})

    def test_a_throw_is_never_withdrawn(self):
        """Even straight down the partner's own lane: see partner.py."""

        throw = ThrowKnife(actor_slot="P1", target_slot="obj01")
        context = {
            make_myself(held_weapon_type=0x08),
            make_partner(world_x=150),
            make_enemy(world_x=180),
            throw,
        }
        self.assertEqual(verbs(do_not_harm_partner(context)), {throw})

    def test_call_police_is_never_withdrawn(self):
        """``$4478`` returns outright while a police special is active."""

        police = CallPolice(actor_slot="P1")
        kept = do_not_harm_partner(self._context(police, partner_x=130))
        self.assertEqual(verbs(kept), {police})


class RearAttackTests(unittest.TestCase):
    def test_chord_withdrawn_with_partner_in_the_rear_band(self):
        chord = RearAttack(actor_slot="P1", target_slot="obj01")
        context = {make_myself(), make_partner(world_x=75), make_enemy(world_x=75), chord}
        self.assertEqual(verbs(do_not_harm_partner(context)), set())

    def test_chord_kept_with_partner_in_front(self):
        chord = RearAttack(actor_slot="P1", target_slot="obj01")
        context = {make_myself(), make_partner(world_x=125), make_enemy(world_x=75), chord}
        self.assertEqual(verbs(do_not_harm_partner(context)), {chord})


class JumpAttackTests(unittest.TestCase):
    def test_grounded_launch_withdrawn_through_the_partner(self):
        hop = JumpAttack(actor_slot="P1", target_slot="obj01")
        # 55px: past Axel's punch outer (50), inside his kick's free flight (60).
        context = {make_myself(), make_partner(world_x=155), make_enemy(world_x=155), hop}
        self.assertEqual(verbs(do_not_harm_partner(context)), set())

    def test_airborne_jump_is_never_withdrawn(self):
        """Committed: withdrawing here loses the kick *and* the hold."""

        hop = JumpAttack(actor_slot="P1", target_slot="obj01")
        context = {
            make_myself(is_airborne=True),
            make_partner(world_x=155),
            make_enemy(world_x=155),
            hop,
        }
        self.assertEqual(verbs(do_not_harm_partner(context)), {hop})


class OpenBreakableTests(unittest.TestCase):
    def _context(self, *, prop_x):
        prop = Breakable(slot="obj09", world_x=prop_x, world_y=100, type_id=0x11)
        return prop, {
            make_myself(),
            make_partner(world_x=130),
            prop,
            OpenBreakable(actor_slot="P1", target_slot="obj09"),
        }

    def test_withdrawn_only_once_the_prop_is_actually_in_smash_range(self):
        _, context = self._context(prop_x=135)
        self.assertEqual(verbs(do_not_harm_partner(context)), set())

    def test_the_approach_survives(self):
        """Out of smash range no B is pressed, so nothing can hit anyone."""

        _, context = self._context(prop_x=400)
        self.assertEqual({type(v) for v in verbs(do_not_harm_partner(context))}, {OpenBreakable})


class WeaponClaimTests(unittest.TestCase):
    def _context(self, *, mine, theirs):
        return {
            make_myself(held_weapon_type=mine),
            make_partner(world_x=400, held_weapon_type=theirs),
            Weapon(slot="obj04", world_x=140, world_y=100, weapon_type=0x08),
            WalkToWeapon(actor_slot="P1", target_slot="obj04"),
        }

    def test_left_for_an_unarmed_partner(self):
        self.assertEqual(verbs(do_not_harm_partner(self._context(mine=0, theirs=0))), set())

    def test_left_for_a_worse_armed_partner(self):
        # Pepper (2) against the actor's bat (4).
        self.assertEqual(verbs(do_not_harm_partner(self._context(mine=0x0A, theirs=0x0C))), set())

    def test_taken_when_the_partner_is_the_better_armed(self):
        kept = do_not_harm_partner(self._context(mine=0x0C, theirs=0x0A))
        self.assertEqual({type(v) for v in verbs(kept)}, {WalkToWeapon})

    def test_taken_when_both_hold_the_same_rank(self):
        kept = do_not_harm_partner(self._context(mine=0x0A, theirs=0x0B))
        self.assertEqual({type(v) for v in verbs(kept)}, {WalkToWeapon})


class PickupClaimTests(unittest.TestCase):
    def _context(self, pickup, **partner_overrides):
        return {
            make_myself(),
            make_partner(world_x=400, **partner_overrides),
            pickup,
            WalkToPickup(actor_slot="P1", target_slot=pickup.slot),
        }

    def _food(self):
        return HealthPickup(
            slot="obj05", world_x=140, world_y=100, pickup_type=0x4B, health_delta=20
        )

    def test_food_left_for_the_hurt_partner(self):
        context = self._context(self._food(), health=20, health_percent=25.0)
        self.assertEqual(verbs(do_not_harm_partner(context)), set())

    def test_food_taken_when_the_partner_is_healthier(self):
        context = self._context(self._food())
        actor = next(t for t in context if isinstance(t, Myself))
        context = (context - {actor}) | {make_myself(health=20, health_percent=25.0)}
        kept = do_not_harm_partner(context)
        self.assertEqual({type(v) for v in verbs(kept)}, {WalkToPickup})

    def test_life_left_for_the_partner_on_fewer_lives(self):
        life = LifePickup(slot="obj06", world_x=140, world_y=100, pickup_type=0x4C)
        self.assertEqual(verbs(do_not_harm_partner(self._context(life, lives=1))), set())

    def test_life_taken_when_the_partner_has_more(self):
        life = LifePickup(slot="obj06", world_x=140, world_y=100, pickup_type=0x4C)
        kept = do_not_harm_partner(self._context(life, lives=5))
        self.assertEqual({type(v) for v in verbs(kept)}, {WalkToPickup})

    def test_special_and_score_are_never_claimed(self):
        special = SpecialPickup(slot="obj07", world_x=140, world_y=100, pickup_type=0x4F)
        score = ScorePickup(
            slot="obj08", world_x=140, world_y=100, pickup_type=0x3F, points=3000
        )
        for pickup in (special, score):
            with self.subTest(pickup=type(pickup).__name__):
                context = self._context(pickup, health=10, health_percent=12.5, lives=0)
                kept = do_not_harm_partner(context)
                self.assertEqual({type(v) for v in verbs(kept)}, {WalkToPickup})


class OtherActorTests(unittest.TestCase):
    def test_a_verb_belonging_to_another_actor_is_left_alone(self):
        punch = Punch(actor_slot="P2", target_slot="obj01")
        context = {make_myself(), make_partner(world_x=130), make_enemy(world_x=130), punch}
        self.assertEqual(verbs(do_not_harm_partner(context)), {punch})


class HoldOnPartnerTests(unittest.TestCase):
    """The body in hand is the partner: ``$3266`` linked ``+$4C`` to them."""

    HOLD_MOVES = (AttackHeldEnemy, Supplex, FlipHold, ThrowHeldEnemy, ReleaseToRegrab)

    def _context(self, verb, *, held):
        return {
            make_myself(action_state=0x66, held_enemy_slot=held),
            make_partner(
                world_x=120, action_state=0x7A, combat_phase=CombatPhase.HELD_BY_ENEMY
            ),
            make_enemy(slot="obj01", world_x=70, combat_phase=CombatPhase.GRABBED),
            verb,
        }

    def test_every_hold_move_is_withdrawn(self):
        for cls in self.HOLD_MOVES:
            with self.subTest(verb=cls.__name__):
                verb = cls(actor_slot="P1", target_slot="obj01")
                self.assertEqual(
                    verbs(do_not_harm_partner(self._context(verb, held="P2"))), set()
                )

    def test_hold_moves_on_an_enemy_are_left_alone(self):
        for cls in self.HOLD_MOVES:
            with self.subTest(verb=cls.__name__):
                verb = cls(actor_slot="P1", target_slot="obj01")
                kept = do_not_harm_partner(self._context(verb, held="obj01"))
                self.assertEqual(verbs(kept), {verb})

    def test_the_release_is_never_withdrawn(self):
        release = ReleasePartner(actor_slot="P1", target_slot="P2")
        kept = do_not_harm_partner(self._context(release, held="P2"))
        self.assertEqual(verbs(kept), {release})


class HeldByPartnerTests(unittest.TestCase):
    """The partner holds the actor: ``$34EA``/``$34E6`` put it in ``$78``/``$7A``."""

    def _held_actor(self):
        return make_myself(action_state=0x7A, combat_phase=CombatPhase.HELD_BY_ENEMY)

    def test_the_counter_is_withdrawn(self):
        counter = CounterGrab(actor_slot="P1")
        context = {
            self._held_actor(),
            make_partner(world_x=120, action_state=0x60, held_enemy_slot="P1"),
            counter,
        }
        self.assertEqual(verbs(do_not_harm_partner(context)), set())

    def test_the_counter_on_an_enemy_hold_is_kept(self):
        counter = CounterGrab(actor_slot="P1")
        context = {
            self._held_actor(),
            make_partner(world_x=300),
            make_enemy(world_x=120, combat_phase=CombatPhase.ATTACKING),
            counter,
        }
        self.assertEqual(verbs(do_not_harm_partner(context)), {counter})


class ReportedGrabPipelineTests(unittest.TestCase):
    """The whole loop as reported: the user on P1, the AI on P2.

    User: "The AI grabbed me and supplexed me, it shouldn't, because it should
    never hurt it's partner!"
    """

    def _run(self, context):
        context = set(context)
        context |= generate_inference_tokens(context)
        context |= generate_verb_tokens(context)
        context = do_not_harm_partner(context)
        return find_all(determine_priority_verb(context), Verb)

    def _ai(self, **overrides):
        return make_myself(
            slot="P2", player_index=2, character_id=2, character_name="Blaze", **overrides
        )

    def _user(self, **overrides):
        return make_partner(
            slot="P1", player_index=1, character_id=0, character_name="Axel", **overrides
        )

    def test_a_hold_on_the_user_ends_in_a_release(self):
        # From $66 the hold family used to offer Supplex outright, and from
        # $60 the knee and the flip into it -- aimed at the nearest enemy,
        # landed by the ROM on the user.
        for action_state in (0x60, 0x66):
            with self.subTest(action_state=hex(action_state)):
                context = {
                    self._ai(world_x=100, action_state=action_state, held_enemy_slot="P1"),
                    self._user(
                        world_x=118,
                        action_state=0x7A,
                        combat_phase=CombatPhase.HELD_BY_ENEMY,
                    ),
                    make_enemy(slot="obj01", world_x=160),
                }
                self.assertEqual(
                    self._run(context), [ReleasePartner(actor_slot="P2", target_slot="P1")]
                )

    def test_held_by_the_user_the_ai_does_not_counter(self):
        context = {
            self._ai(world_x=100, action_state=0x7A, combat_phase=CombatPhase.HELD_BY_ENEMY),
            self._user(
                world_x=118, action_state=0x60, facing_left=True, held_enemy_slot="P2"
            ),
            make_enemy(slot="obj01", world_x=200),
        }
        self.assertEqual(self._run(context), [])


if __name__ == "__main__":
    unittest.main()
