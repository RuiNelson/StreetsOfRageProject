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

Three consequences of that same ROM routine bound what is filtered here:

- ``+$34`` must be nonzero, so ``GrabEnemy`` — a walk-in that deliberately
  presses nothing (see ``AI.md``'s "Grabbing an enemy") — cannot hurt the
  partner and is left alone;
- the routine returns immediately while a police special is active, so
  ``CallPolice`` is not friendly fire and is never withdrawn;
- the hold moves (``AttackHeldEnemy``/``Supplex``/``ThrowHeldEnemy``/
  ``FlipHold``) apply their damage to the body already in the actor's hands.
  A thrown body is its own object with its own collisions and no decoded
  player path, so nothing here withdraws them; if that turns out to hurt a
  partner standing behind the throw, this is the place to add it.

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

Everything here is a no-op without a ``Partner`` token, which is the
ordinary single-player case: ``observe.py`` only builds one while the other
player is actually playable.
"""

from __future__ import annotations

from typing import Callable

from . import reach
from .decide import in_smash_range
from .tokens import (
    Breakable,
    Context,
    HealthPickup,
    HitAntonioBoomerang,
    JumpAttack,
    LifePickup,
    MeleeWeaponAttack,
    Myself,
    OpenBreakable,
    Partner,
    Pickup,
    Punch,
    RearAttack,
    Token,
    Verb,
    WalkToPickup,
    WalkToWeapon,
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
    """The kick's own band — but only while the launch is still a decision.

    Once airborne the actor is committed (``AI.md``, "Committing to a
    jump"): the trajectory is fixed, and withdrawing the verb mid-flight
    hands the tick to ``press_no_button``, which releases the controller and
    costs the kick *and* the launch direction. Not kicking does not un-fly
    the jump, so an airborne ``JumpAttack`` is never withdrawn here.
    """

    if actor.is_airborne:
        return False
    return reach.in_jump_attack_band(actor, partner)


def _rear_attack_hits_partner(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """The ``$322A`` chord's real box, on the side the partner stands."""

    return reach.in_rear_band(actor, partner)


def _weapon_belongs_to_partner(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """Leave a ground weapon alone while the partner is the worse armed.

    ``could_walk_to_weapon`` only ever produces a genuine upgrade for
    ``Myself`` (``reach.weapon_upgrade_rank``), so the question left here is
    purely who needs it more: an unarmed partner, or one holding a weapon
    ranked below the actor's own (``weapon_rank``: knife 5 > bat/pipe 4 >
    bottle 3 > pepper 2), needs it more than an actor who is already the
    better armed of the two.
    """

    theirs = weapon_rank(partner.held_weapon_type)
    return theirs == 0 or theirs < weapon_rank(actor.held_weapon_type)


def _pickup_belongs_to_partner(
    context: Context, actor: Myself, partner: Partner, verb: Verb
) -> bool:
    """Leave food to the hurter of the two, and a 1UP to the poorer of them.

    Only the two consumables whose value is exactly the resource being
    compared: a ``SpecialPickup`` and a ``ScorePickup`` are not claimed by
    either half of this rule and stay collectable.
    """

    pickup = find(context, Pickup, slot=verb.target_slot)
    if isinstance(pickup, HealthPickup):
        return partner.health_percent < actor.health_percent
    if isinstance(pickup, LifePickup):
        return partner.lives < actor.lives
    return False


# Verbs whose own attack box can land on the partner ($4478).
_HARM_TESTS: dict[type[Verb], WithdrawTest] = {
    Punch: _forward_strike_hits_partner,
    MeleeWeaponAttack: _forward_strike_hits_partner,
    HitAntonioBoomerang: _forward_strike_hits_partner,
    OpenBreakable: _open_breakable_hits_partner,
    JumpAttack: _jump_attack_hits_partner,
    RearAttack: _rear_attack_hits_partner,
}

# Verbs that would take a floor item the partner needs more.
_CLAIM_TESTS: dict[type[Verb], WithdrawTest] = {
    WalkToWeapon: _weapon_belongs_to_partner,
    WalkToPickup: _pickup_belongs_to_partner,
}

_WITHDRAW_TESTS: dict[type[Verb], WithdrawTest] = {**_HARM_TESTS, **_CLAIM_TESTS}


def withdrawn_verbs(context: Context) -> set[Verb]:
    """Every ``Verb`` in ``context`` this filter refuses, possibly empty."""

    partner = find(context, Partner)
    actor = find(context, Myself)
    if partner is None or actor is None:
        return set()

    withdrawn: set[Verb] = set()
    for verb in find_all(context, Verb):
        test = _WITHDRAW_TESTS.get(type(verb))
        if test is None:
            continue
        # Only this agent's own verbs: decide._actors yields Myself alone,
        # so a verb parametrized on anyone else is not ours to withdraw.
        if getattr(verb, "actor_slot", None) != actor.slot:
            continue
        if test(context, actor, partner, verb):
            withdrawn.add(verb)
    return withdrawn


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
