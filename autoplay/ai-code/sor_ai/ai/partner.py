"""``do_not_harm_partner`` — the co-op courtesy filter of ``AI.md``'s loop.

This is the one stage of the pipeline that only ever *removes* ``Verb``
tokens. It runs between ``generate_verb_tokens`` and
``determine_priority_verb``, so a withdrawn verb is never ranked, never
executed, and never shown as a pending candidate: it is not that the strike
is a bad idea and should score lower, it is that the strike must not be
offered at all while the partner is standing in it.

**Friendly fire is real, and it is the ROM's own box test.**
``$4478 (resolve_player_vs_player_collision)`` runs once per gameplay frame
and compares the attacker's attack box (``+$64``) against the *other
player's body box* (``+$70``) — the same box-against-body shape ``$450C``
uses for enemies — turning the attack descriptor into the other player's
reaction whenever the attacker's outgoing damage ``+$34`` is nonzero
(``player-health-lives-and-combat.md``, "Player-versus-player contact").
That is exactly the geometry ``reach.punch_would_connect`` /
``reach.in_rear_band`` / ``reach.in_jump_attack_band`` already answer, so
this module asks *them* about the ``Partner`` rather than measuring a second
time — the rule this codebase replaced its inference cache with: whenever
two stages need the same judgment, both call the same function.

Four consequences of that same ROM routine bound what is filtered here:

- ``+$34`` must be nonzero, so ``GrabEnemy`` — a walk-in that deliberately
  presses nothing (see ``AI.md``'s "Grabbing an enemy") — cannot hurt the
  partner and is left alone. What any walk *can* do to them is take hold of
  them (the next point), and that is a rule about how the actor moves rather
  than which verb it runs: ``execute.execute_tick`` keeps every walk's box
  off the partner, whatever verb is walking;
- the routine returns immediately while a police special is active, so
  ``CallPolice`` is not friendly fire and is never withdrawn;
- with no damage out, the same contact is a **grab** between the players,
  and ``$3266`` takes the same front/back hold on the partner it takes on an
  enemy, linking ``+$4C`` to the partner's object. The hold moves
  (``AttackHeldEnemy``/``Supplex``/``ThrowHeldEnemy``/``FlipHold``/
  ``ReleaseToRegrab``) act on that body whatever enemy they name, so they
  are withdrawn exactly while the link names the partner (user: "The AI
  grabbed me and supplexed me, it shouldn't, because it should never hurt
  it's partner!"); ``decide.could_hold_actions`` offers ``ReleasePartner``
  in their place. A thrown *enemy* is its own object with no decoded player
  path, so throwing one is left alone;
- the grab runs the other way too: ``$34EA``/``$34E6`` put the player held
  by the other player into ``$78``/``$7A``, the family an enemy grab uses,
  so it reads ``HELD_BY_ENEMY`` -- and ``CounterGrab``'s C then B would
  throw the partner. It is withdrawn while the partner's own ``+$4C`` names
  the actor, and nothing replaces it: the hold is the partner's to end.

The two attack-thrown weapons (``$21E6 (player_release_thrown_weapon)``
issues its throw command for the knife ``$08`` and the pepper ``$0C``, and
for nothing else) are not filtered either. A version of this filter did
withdraw them while the partner shared the flight lane in front of the
actor, on the grounds that ``$5D84 (launch_released_weapon)``'s projectile
has no decoded player path either way -- **removed on the user's own call**:
catching the partner with a throw is close to impossible in play, and the
lane test cost real throws to buy a hazard that does not happen.

The second half of this filter is not about harm at all but about **not
taking what the partner needs more** — the coordination ``AI.md``'s
*Process* section asks for ("preferring to leave a health item on the floor
for the partner if the partner needs it more than ``Myself`` does"). It is
expressed the same way, as a withdrawal, because a verb the actor should not
take is exactly a verb that should never reach the ranking.

The item rule itself is ``item_is_the_partners`` (the user's: the actor
takes food only while it is strictly the hurter, a weapon unless the partner
is strictly the worse armed -- a tie is the actor's -- and a 1UP to the one
with fewer lives). ``execute``'s partner pad asks it too, because any
grounded B beside an item picks the item up (``$3136``).

The third half is **leaving the partner's fight to them** (user: "a IA a
tentar atacar o mesmo inimigo que o partner já está a atacar ou perto de
atacar, estuda bem o assunto e evita isso!"): ``PartnerFightTracker`` marks
the enemies the partner is fighting or about to (``reach.
partner_is_engaging``, remembered ``PARTNER_FIGHT_MEMORY_FRAMES``), and the
actor's attacks on them, and walks to them, are withdrawn -- bar
self-defence and a kick already in the air.

Everything here is a no-op without a ``Partner`` token, which is the
ordinary single-player case: ``observe.py`` only builds one while the other
player is actually playable.
"""

from __future__ import annotations

from typing import Callable

from . import jump_kick, kinematics, reach
from .decide import in_smash_range
from .tokens import (
    AttackHeldEnemy,
    Breakable,
    Context,
    CounterGrab,
    EngageAbadede,
    EngageAntonio,
    EngageBongo,
    EngageJack,
    EngageSouther,
    Enemy,
    FlipHold,
    GrabEnemy,
    HealthPickup,
    HitAntonioBoomerang,
    HitTable,
    JumpAttack,
    LifePickup,
    MeleeWeaponAttack,
    Myself,
    OpenBreakable,
    Partner,
    PartnerFight,
    Pickup,
    Punch,
    RearAttack,
    ReleaseToRegrab,
    Supplex,
    ThrowHeldEnemy,
    ThrowKnife,
    ThrowPepper,
    Token,
    Verb,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
    Weapon,
    find,
    find_all,
    weapon_rank,
)

# One test per concrete Verb class: "would this verb, executed now, land on
# the partner (or take what the partner needs more)?". Same
# ``type(verb) -> function`` dispatch priority.py and execute.py already use.
# A class with no entry here is never withdrawn.
WithdrawTest = Callable[[Context, Myself, Partner, Verb], bool]


def _forward_strike_hits_partner(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """B, armed or not, into the partner's body — ``$4478``'s own test."""

    return reach.punch_would_connect(actor, partner)


def _open_breakable_hits_partner(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """The same strike, but only on the ticks ``OpenBreakable`` actually
    strikes.

    That verb spans the approach *and* the B press (``AI.md``: one verb for
    the whole prop interaction), switching on ``decide.in_smash_range`` —
    so out of smash range no button is pressed and there is nothing to
    withdraw. Withdrawing the approach as well would stall the actor in
    front of a prop for as long as the partner happened to stand nearby,
    and the next tick re-asks this question anyway.
    """

    prop = find(context, Breakable, slot=verb.target_slot)
    if prop is None or not in_smash_range(actor, prop):
        return False
    return reach.punch_would_connect(actor, partner)


def _jump_attack_hits_partner(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """The kick's own flight -- but only while the launch is still a decision.

    Not a distance band: the flight launched now toward the verb's target,
    update by update, with its kick box on every update it is out
    (``jump_kick.launch_hits_player``). The band this replaced stopped at
    60/69/75 px, and a kick really lands on a standing body as far as ~110
    px away (Axel) -- so a partner standing a little beyond the enemy was
    kicked by a launch this filter had passed (user: "a IA não tem bem ideia
    do ataque de pontapé no ar").

    Once airborne the actor is committed (``AI.md``, "Committing to a
    jump"): the trajectory is fixed, and withdrawing the verb mid-flight
    hands the tick to ``press_no_button``, which releases the controller and
    costs the launch direction. So an airborne ``JumpAttack`` is never
    withdrawn here; the executor instead holds back the B edge itself while
    the kick would still land on the partner
    (``execute.state_machine_jump_attack``).
    """

    if actor.is_airborne:
        return False
    target = find(context, Enemy, slot=verb.target_slot)
    if target is not None:
        direction = jump_kick.launch_direction(actor, target)
    else:
        direction = -1 if actor.facing_left else 1
    return jump_kick.launch_hits_player(actor, partner, direction=direction)


def _rear_attack_hits_partner(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """The ``$322A`` chord's real box, on the side the partner stands."""

    return reach.in_rear_band(actor, partner)


def item_is_the_partners(actor: Myself, partner: Partner, item: Pickup | Weapon) -> bool:
    """Whether ``item`` is the partner's to take rather than ``actor``'s.

    The user's rule: "A IA só deve usar items de recuperação se estiver sem
    partner, ou se tiver partner, a personagem dela precisar mais do item que
    o partner. O mesmo para armas, só apanhar uma arma se tiver na mão nenhuma
    ou uma pior, e se o partner não tiver uma melhor (no caso de empate,
    tentar pegar)". Read as a question of who needs it more:

    - **food** is the actor's only while the actor is strictly the hurter of
      the two -- equally hurt leaves it for the partner;
    - a **weapon** is the partner's only while the partner is strictly the
      worse armed (``weapon_rank``: knife 5 > bat/pipe 4 > bottle 3 >
      pepper 2, unarmed 0), so a tie -- both unarmed included -- is the
      actor's to try. Whether it is an upgrade for the actor at all is
      ``reach.weapon_upgrade_rank``'s question, asked before this one;
    - a **1UP** goes to the one with fewer lives, a tie being the actor's.

    ``SpecialPickup`` and ``ScorePickup`` are claimed by neither. Shared by
    the walk-to-item withdrawals below and by ``execute``'s partner pad, which
    must not let a B press pick one up either (``$3136`` turns any grounded B
    near an item into a pickup -- ``reach.item_a_b_press_takes``).
    """

    if isinstance(item, HealthPickup):
        return not actor.health_percent < partner.health_percent
    if isinstance(item, LifePickup):
        return partner.lives < actor.lives
    if isinstance(item, Weapon):
        return weapon_rank(partner.held_weapon_type) < weapon_rank(actor.held_weapon_type)
    return False


def _weapon_belongs_to_partner(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """``WalkToWeapon`` toward a weapon that is the partner's.

    ``could_walk_to_weapon`` only ever produces a genuine upgrade for
    ``Myself`` (``reach.weapon_upgrade_rank``), so the question left here is
    purely who needs it more -- ``item_is_the_partners``.
    """

    weapon = find(context, Weapon, slot=verb.target_slot)
    return weapon is not None and item_is_the_partners(actor, partner, weapon)


def _pickup_belongs_to_partner(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """``WalkToPickup`` toward a consumable that is the partner's."""

    pickup = find(context, Pickup, slot=verb.target_slot)
    return pickup is not None and item_is_the_partners(actor, partner, pickup)


def _hold_move_lands_on_partner(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """A hold move acts on the body in hand, and ``+$4C`` says whose it is.

    Whatever enemy the verb names, the ROM delivers the knee, the throw, the
    crossover and the suplex to the object ``+$4C`` links -- the partner,
    once the actor has walked into them (``PlayableCharacter.
    is_holding_player``).
    """

    return actor.held_enemy_slot == partner.slot


def _counter_throws_partner(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """C then B throws whoever holds the actor -- here, the partner.

    The partner's own hold link is the witness: ``$3266`` writes ``+$4C`` on
    the holder, and ``observe.py`` fills ``held_enemy_slot`` from it only
    while the action byte is a hold.
    """

    return partner.held_enemy_slot == actor.slot


def _targets_the_partners_fight(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """An attack, or the walk to one, aimed at an enemy that is the
    partner's fight (``PartnerFight``).

    User: "a IA a tentar atacar o mesmo inimigo que o partner já está a
    atacar ou perto de atacar, estuda bem o assunto e evita isso!". Two
    bodies on one enemy is two players in each other's way -- the kick or
    punch aimed at it passes through the partner's space, the grab takes
    the body from under their combo -- so the actor picks another enemy, and
    with none left it waits rather than joins.

    Two exceptions. **Self-defence**: an enemy whose committed attack is
    about to land on the actor (``reach.is_incoming_melee``) is answered
    whoever else is fighting it. **A kick already in the air**: the flight is
    committed, and withdrawing it would release the pad mid-flight.
    """

    slot = getattr(verb, "target_slot", None)
    if slot is None or not any(
        claim.enemy_slot == slot for claim in find_all(context, PartnerFight)
    ):
        return False
    if isinstance(verb, JumpAttack) and actor.is_airborne:
        return False
    enemy = find(context, Enemy, slot=slot)
    return enemy is None or not reach.is_incoming_melee(actor, enemy)


# Verbs whose own attack box can land on the partner ($4478).
_HARM_TESTS: dict[type[Verb], WithdrawTest] = {
    Punch: _forward_strike_hits_partner,
    MeleeWeaponAttack: _forward_strike_hits_partner,
    HitAntonioBoomerang: _forward_strike_hits_partner,
    HitTable: _forward_strike_hits_partner,
    OpenBreakable: _open_breakable_hits_partner,
    JumpAttack: _jump_attack_hits_partner,
    RearAttack: _rear_attack_hits_partner,
}

# Verbs that attack an enemy, or walk to attack one -- left alone while the
# enemy is the partner's fight.
_FIGHT_TESTS: dict[type[Verb], WithdrawTest] = {
    verb_cls: _targets_the_partners_fight
    for verb_cls in (
        WalkToNearEnemy,
        Punch,
        MeleeWeaponAttack,
        JumpAttack,
        GrabEnemy,
        RearAttack,
        ThrowKnife,
        ThrowPepper,
        EngageSouther,
        EngageAntonio,
        EngageBongo,
        EngageAbadede,
        EngageJack,
    )
}

# Verbs that act on the body in the actor's hands, or on whoever holds the
# actor -- the partner, once the two players have grabbed each other.
_HOLD_TESTS: dict[type[Verb], WithdrawTest] = {
    AttackHeldEnemy: _hold_move_lands_on_partner,
    Supplex: _hold_move_lands_on_partner,
    ThrowHeldEnemy: _hold_move_lands_on_partner,
    FlipHold: _hold_move_lands_on_partner,
    ReleaseToRegrab: _hold_move_lands_on_partner,
    CounterGrab: _counter_throws_partner,
}

# Verbs that would take a floor item the partner needs more.
_CLAIM_TESTS: dict[type[Verb], WithdrawTest] = {
    WalkToWeapon: _weapon_belongs_to_partner,
    WalkToPickup: _pickup_belongs_to_partner,
}

def _merged(*tables: dict[type[Verb], WithdrawTest]) -> dict[type[Verb], tuple[WithdrawTest, ...]]:
    """Every table's test for each class, in table order: a ``Punch`` has to
    miss the partner *and* leave the partner's enemy alone."""

    merged: dict[type[Verb], tuple[WithdrawTest, ...]] = {}
    for table in tables:
        for verb_cls, test in table.items():
            merged[verb_cls] = merged.get(verb_cls, ()) + (test,)
    return merged


_WITHDRAW_TESTS = _merged(_HARM_TESTS, _HOLD_TESTS, _FIGHT_TESTS, _CLAIM_TESTS)


def withdrawn_verbs(context: Context) -> set[Verb]:
    """Every ``Verb`` in ``context`` this filter refuses, possibly empty."""

    partner = find(context, Partner)
    actor = find(context, Myself)
    if partner is None or actor is None:
        return set()

    withdrawn: set[Verb] = set()
    for verb in find_all(context, Verb):
        tests = _WITHDRAW_TESTS.get(type(verb), ())
        if not tests:
            continue
        # Only this agent's own verbs: decide._actors yields Myself alone,
        # so a verb parametrized on anyone else is not ours to withdraw.
        if getattr(verb, "actor_slot", None) != actor.slot:
            continue
        if any(test(context, actor, partner, verb) for test in tests):
            withdrawn.add(verb)
    return withdrawn


# How long an enemy stays the partner's after the last tick they were seen
# fighting it. A combo knocks the body back out of reach between hits and the
# partner steps in again; a claim that lapsed in that gap sent the AI in for
# it, and back out the moment the partner stepped back in. Three quarters of
# a second, in 60 Hz frames.
PARTNER_FIGHT_MEMORY_FRAMES = 45


class PartnerFightTracker:
    """Which enemies are the partner's fight, remembered across ticks.

    Each tick asks ``reach.partner_is_engaging`` of every live enemy and
    answers one ``PartnerFight`` token per enemy engaged now or within the
    last ``PARTNER_FIGHT_MEMORY_FRAMES``. The same kind of cross-tick fact as
    ``observe``'s trackers (a single snapshot is not a transition), owned per
    ``AgentLoop`` for the same reason, and fed the *observed* context rather
    than the snapshot because the judgment is made of tokens: the partner's
    reach, their kick in flight, the enemy's body.

    A slot that stops being a live enemy is forgotten at once, so a slot the
    game reuses for a fresh enemy starts unclaimed. Without a ``Partner`` in
    the context there is nobody to leave anything to, and every claim goes.
    """

    def __init__(self) -> None:
        self._ticks_since: dict[str, int] = {}

    def update(self, context: Context) -> set[Token]:
        partner = find(context, Partner)
        if partner is None:
            self._ticks_since = {}
            return set()
        ticks_since: dict[str, int] = {}
        for enemy in reach.live_enemies(context):
            if reach.partner_is_engaging(partner, enemy):
                ticks_since[enemy.slot] = 0
            elif enemy.slot in self._ticks_since:
                ticks_since[enemy.slot] = self._ticks_since[enemy.slot] + 1
        self._ticks_since = ticks_since
        return {
            PartnerFight(enemy_slot=slot)
            for slot, ticks in ticks_since.items()
            if kinematics.frames_for_ticks(ticks) <= PARTNER_FIGHT_MEMORY_FRAMES
        }


def do_not_harm_partner(context: Context) -> Context:
    """Return ``context`` without the verbs that would harm ``Partner``.

    A no-op — the same context object — when no ``Partner`` is present, and
    the only stage of the loop that removes verbs rather than adding them,
    which is why ``AI.md``'s loop assigns its result (``context = ...``)
    instead of unioning it.
    """

    withdrawn: set[Token] = set(withdrawn_verbs(context))
    if not withdrawn:
        return context
    return context - withdrawn
