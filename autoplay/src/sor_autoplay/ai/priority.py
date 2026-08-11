"""``determine_priority_verb`` — rank ``Verb`` tokens by emergency.

Per ``AI.md``: this also performs target selection, since ranking by
emergency and keeping only the highest-ranked ``Verb`` is what collapses
several same-type candidates (e.g. a ``Punch`` against each of two nearby
enemies) down to one.

Each ``_emergency_*`` function below computes its score from the
``Information`` tokens present in the ``Context`` — per the matching
concrete ``Verb`` class's ``Raises emergency: ...`` docstring line —
never from the verb's type alone. The module constants are named
*contributions* consulted when their token condition holds; they are not
applied unconditionally.
"""

from __future__ import annotations

import logging
import math
import random
from collections.abc import Callable

from ..phases import HITSTUN_FRAMES, CombatPhase, is_dangerous
from . import reach
from .decide import (
    HEALTH_CRITICAL_PERCENT,
    in_smash_range,
    KNIFE_MELEE_X,
    KNIFE_RANGE_X,
    KNIFE_RANGE_Y,
    POLICE_HEALTH_PERCENT_THRESHOLD,
    POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE,
    _advance_blocking_enemies,
)
from .tokens import (
    Attack,
    CounterGrab,
    FlipHold,
    GrabEnemy,
    JumpAttack,
    AttackHeldEnemy,
    Punch,
    RearAttack,
    OpenBreakable,
    ReleaseGrab,
    SprayPepper,
    StabWithKnifeOrBottle,
    Supplex,
    SwingBatOrPipe,
    TechRecover,
    ThrowHeldEnemy,
    ThrowKnife,
    ThrowPepper,
)
from .tokens import Myself, Partner
from .tokens import Breakable, Enemy, Grunt
from .tokens import (
    GrabOpportunity,
    GrabToClearRear,
    GrabToNeutralizeWhip,
    IncomingMelee,
    PunishWindow,
    Surrounded,
    WeaponUpgrade,
)
from .tokens import (
    HealthPickup,
    LifePickup,
    Pickup,
    ScorePickup,
    SpecialPickup,
)
from .tokens import CallPolice
from .tokens import Context, Verb, find, find_all
from .tokens import (
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)

logger = logging.getLogger(__name__)

# 0-100 emergency scale.
_EMERGENCY_COUNTER_GRAB = 100  # already held — only useful action
_EMERGENCY_TECH_RECOVER = 90  # narrow window, free to act at nothing else
_EMERGENCY_CALL_POLICE = 88
# Boxed in but not yet at the health thresholds above: still the only move
# that clears every side at once, so it outranks every strike, but it sits
# below the "about to die" call so the two are never confused.
_EMERGENCY_CALL_POLICE_SURROUNDED = 80
_EMERGENCY_REAR_ATTACK = 55  # escape when boxed in / punch dead-zone
_EMERGENCY_REAR_ATTACK_DANGEROUS = 60  # escape a commit from behind
# The same chord when turning around *is* available (decide.
# _rear_attack_is_warranted says no): still a usable option, no longer a
# preferred one. $322A costs up to 21 frames of startup and hits only by
# current position, so it whiffs whenever the target drifts during that
# window; a turn-and-punch is faster and far more reliable. These sit below
# every real strike and below WalkToNearEnemy's realistic in-band range
# (12..14 -- the rear band is at most 53px), so the turn-around wins when it
# exists and the chord still fires when nothing better is on the table.
_EMERGENCY_REAR_ATTACK_UNWARRANTED = 9
_EMERGENCY_REAR_ATTACK_UNWARRANTED_DANGEROUS = 11
_EMERGENCY_PUNCH_PUNISHABLE = 60
_EMERGENCY_PUNCH_DEFAULT = 20
# Ceilings (never a raise -- see _emergency) for an Attack whose target is a
# stunned Grunt. Which one applies depends on how much of the stun is left,
# because the ROM's two stuns are not the same situation at all.
#
# A **hitstun** ($18 frames, seeded by the hit itself) is the middle of a
# combo: the ROM's own 3-hit chain is what actually knocks an enemy down,
# and each landed hit re-seeds the timer. So it stays just above a plain
# strike (20), which is what keeps the actor finishing the combo instead of
# turning to a fresh enemy that happens to be equally punchable. It still
# sits far below the RearAttack escape (55/60), so a real threat elsewhere
# interrupts the combo -- as it should.
_EMERGENCY_ATTACK_HITSTUN = 21
# A **pepper-spray stun** ($A0 frames, nearly three seconds) is the opposite:
# the enemy is parked. Hitting it must lose to a strike on anything that can
# still act (20), while staying above every Walk tier (WalkToNearEnemy peaks
# at 14) and above RetreatFromDanger (17..15) -- lowered, not abandoned, so
# the actor still finishes it off when nothing better is on the table
# instead of walking away to fetch another enemy.
_EMERGENCY_ATTACK_LONG_STUN = 19
# Taking a hold (GrabEnemy), one tier per GrabOpportunity present.
#
# Clearing the rear is the strong case: with an enemy behind and a grabbable
# body in front, the hold converts the pincer into ThrowHeldEnemy's B+back
# throw straight into the enemy behind. It therefore outranks every strike on
# an enemy that can still act (20), and the warranted RearAttack chord when
# the rear enemy is not itself committed (55) -- the chord is slow and hits
# only by current position. It stays under the chord against an enemy already
# committed behind (_EMERGENCY_REAR_ATTACK_DANGEROUS, 60): there is no time to
# walk into anything then.
_EMERGENCY_GRAB_CLEAR_REAR = 58
# Nora's whip is a reach weapon with nothing to answer a body pressed against
# it, so holding her is better than trading punches -- but it is an
# improvement on an ordinary fight, not an escape from a bad one, so it sits
# just above the jump-kick-on-a-punishable tier (28) and well under the
# punish/escape tiers.
_EMERGENCY_GRAB_NEUTRALIZE_WHIP = 30
_EMERGENCY_HOLD_THROW = 70  # throw held body into rear threat
_EMERGENCY_HOLD_SUPPLEX = 68
_EMERGENCY_HOLD_FLIP = 66
_EMERGENCY_HOLD_KNEE = 64
_EMERGENCY_HOLD_RELEASE = 50
_EMERGENCY_JUMP_ATTACK_PUNISHABLE = 28  # below punch; never prefer hop over strike
_EMERGENCY_JUMP_ATTACK_DEFAULT = 18
_EMERGENCY_THROW_KNIFE = 25
_EMERGENCY_THROW_PEPPER = 25
# One verb, two tiers -- the same two the former SmashBreakable (flat 16 in
# range) and WalkToBreakable (14 down to 8 by distance) carried, so merging
# them changed no ranking: being in range is simply the top of OpenBreakable's
# own scale rather than a different verb.
_EMERGENCY_OPEN_BREAKABLE_IN_RANGE = 16
_EMERGENCY_OPEN_BREAKABLE_APPROACH = 14
_EMERGENCY_WALK_TO_WEAPON = 8  # reference value: knife (rank 5) via _EMERGENCY_WALK_TO_WEAPON_BASE
_EMERGENCY_WALK_TO_WEAPON_BASE = 3  # + weapon_rank (2..5) -> 5..8
_EMERGENCY_WALK_TO_PICKUP_CRITICAL_HEALTH = 50
_EMERGENCY_WALK_TO_PICKUP_HEALTH = 15
_EMERGENCY_WALK_TO_PICKUP_LIFE = 12
_EMERGENCY_WALK_TO_PICKUP_SPECIAL = 9
_EMERGENCY_WALK_TO_PICKUP_SCORE = 3
_EMERGENCY_WALK_TO_NEAR_ENEMY = 14
# Must sit in the gap between WalkToNearEnemy's base (14) and the *lowest*
# real attack tier (_EMERGENCY_JUMP_ATTACK_DEFAULT, 18) -- backing off an
# imminent threat outranks still walking toward one, but never outranks
# actually hitting something, per RetreatFromDanger's own docstring
# ("lower than any real attack so attacking always wins once actually
# possible"). The previous 30/20 band broke that: it beat a plain Punch
# (20), a JumpAttack (18/28) and a knife throw (21..25), so a dangerous
# enemy closing in made the actor back away from a *different* enemy it
# could already hit.
_EMERGENCY_RETREAT_FROM_DANGER = 17  # closer scoring higher, floor 15
# No live enemy left anywhere (on-screen or not) → push stage (was 5).
_EMERGENCY_WALK_TO_ADVANCE_STAGE = 12
_EMERGENCY_DEFAULT = 0


def _find_actor(context: Context, slot: str) -> Myself | Partner | None:
    for actor in (find(context, Myself), find(context, Partner)):
        if actor is not None and actor.slot == slot:
            return actor
    return None


def _distance_emergency(distance: float, *, base: int, floor: int, step_px: float) -> int:
    """Near-continuous distance scoring: ``base`` at distance 0, dropping by
    1 every ``step_px`` pixels, floored at ``floor`` -- both must stay
    inside the caller's own established emergency band, never crossing into
    a different verb type's tier. This is what lets ``could_*``
    functions (decide.py) stop pre-selecting a single "best" candidate
    themselves and produce one Verb per possibility instead, per
    AI.md's own worked example (several ``Punch`` candidates collapsing to
    one only in ``determine_priority_verb``): the ranking still favours
    the closest/best option, it just happens here instead of inside the
    could_* function.

    A handful of coarse buckets was tried first and discarded: with several
    enemies clustered together (the common case), most fell into the same
    bucket and tied every tick, so determine_priority_verb's random
    tie-break kept flipping the target -- confirmed live against a running
    host. One point per ``step_px`` makes an exact tie between two distinct
    candidates rare in practice.
    """

    return max(floor, base - int(distance // step_px))


def _emergency_counter_grab(verb: CounterGrab, context: Context) -> int:
    actor = _find_actor(context, verb.actor_slot)
    if actor is not None and actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
        return _EMERGENCY_COUNTER_GRAB
    return _EMERGENCY_DEFAULT


def _emergency_tech_recover(verb: TechRecover, context: Context) -> int:
    actor = _find_actor(context, verb.actor_slot)
    if actor is not None and actor.throw_tech_ready:
        return _EMERGENCY_TECH_RECOVER
    return _EMERGENCY_DEFAULT


def _emergency_call_police(verb: CallPolice, context: Context) -> int:
    actor = _find_actor(context, verb.actor_slot)
    if actor is None:
        return _EMERGENCY_DEFAULT
    threshold = (
        POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE
        if actor.lives <= 1
        else POLICE_HEALTH_PERCENT_THRESHOLD
    )
    if actor.health_percent < threshold:
        return _EMERGENCY_CALL_POLICE
    if any(token.actor_slot == actor.slot for token in find_all(context, Surrounded)):
        return _EMERGENCY_CALL_POLICE_SURROUNDED
    return _EMERGENCY_DEFAULT


def _emergency_rear_attack(verb: RearAttack, context: Context) -> int:
    target = find(context, Enemy, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if target is None:
        return _EMERGENCY_DEFAULT
    dangerous = is_dangerous(target.combat_phase)
    # Two tiers, not one: the chord earns a top-tier score only where turning
    # around solves nothing -- boxed in between two enemies, or a target
    # inside the punch dead zone. Everywhere else it drops below the
    # turn-and-punch that decide.could_walk_to_near_enemy offers for the same
    # enemy, which is what stops the AI reaching for a slow, whiff-prone
    # reversal as its reflex answer to anything at its back.
    warranted = actor is not None and reach.rear_attack_is_warranted(
        actor, target, reach.live_enemies(context)
    )
    if warranted:
        return _EMERGENCY_REAR_ATTACK_DANGEROUS if dangerous else _EMERGENCY_REAR_ATTACK
    return (
        _EMERGENCY_REAR_ATTACK_UNWARRANTED_DANGEROUS
        if dangerous
        else _EMERGENCY_REAR_ATTACK_UNWARRANTED
    )


def _is_punish_window(context: Context, target_slot: str | None) -> bool:
    """Whether inference judged this target defenceless this tick.

    Reads the ``PunishWindow`` token rather than re-testing the phase, so
    "free damage" has one definition across the pipeline -- including the
    stunned phases, which carry the ROM's own remaining-frames count.
    """

    return any(token.target_slot == target_slot for token in find_all(context, PunishWindow))


def _emergency_melee_strike(verb: Verb, context: Context) -> int:
    """Shared scoring for ``Punch`` / ``SwingBatOrPipe`` /
    ``StabWithKnifeOrBottle`` / ``SprayPepper`` -- same formula regardless
    of held weapon, since none of these has evidence of a different
    punishable-phase payoff."""

    target = find(context, Enemy, slot=getattr(verb, "target_slot", None))
    if target is None:
        return _EMERGENCY_DEFAULT
    if _is_punish_window(context, target.slot):
        return _EMERGENCY_PUNCH_PUNISHABLE
    return _EMERGENCY_PUNCH_DEFAULT


def _emergency_jump_attack(verb: JumpAttack, context: Context) -> int:
    target = find(context, Enemy, slot=verb.target_slot)
    if target is None:
        return _EMERGENCY_DEFAULT
    if _is_punish_window(context, target.slot):
        return _EMERGENCY_JUMP_ATTACK_PUNISHABLE
    return _EMERGENCY_JUMP_ATTACK_DEFAULT


def _emergency_grab_enemy(verb: GrabEnemy, context: Context) -> int:
    """The best tier among the ``GrabOpportunity`` tokens for this pair.

    Several opportunities can hold at once (a whip enemy in front *and* a
    body at the actor's back); the strongest reason is what the grab is
    worth. No opportunity left this tick -- the rear enemy moved off, the
    target stopped being grabbable -- means there is no longer a reason to
    close in, so the walk-in drops out of contention entirely.
    """

    opportunities = [
        token
        for token in find_all(context, GrabOpportunity)
        if token.actor_slot == verb.actor_slot
        and token.target_slot == verb.target_slot
    ]
    if not opportunities:
        return _EMERGENCY_DEFAULT

    score = _EMERGENCY_DEFAULT
    if any(isinstance(token, GrabToClearRear) for token in opportunities):
        score = max(score, _EMERGENCY_GRAB_CLEAR_REAR)
    if any(isinstance(token, GrabToNeutralizeWhip) for token in opportunities):
        score = max(score, _EMERGENCY_GRAB_NEUTRALIZE_WHIP)
    return score


def _emergency_open_breakable(verb: OpenBreakable, context: Context) -> int:
    """In smash range is the top tier; otherwise score by how far the walk-in
    still is, so several props rank against each other."""

    target = find(context, Breakable, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if target is None or actor is None:
        return _EMERGENCY_DEFAULT
    if in_smash_range(actor, target):
        return _EMERGENCY_OPEN_BREAKABLE_IN_RANGE
    distance = math.hypot(target.world_x - actor.world_x, target.world_y - actor.world_y)
    return _distance_emergency(
        distance, base=_EMERGENCY_OPEN_BREAKABLE_APPROACH, floor=8, step_px=15
    )


def _emergency_walk_to_weapon(verb: WalkToWeapon, context: Context) -> int:
    upgrade = next(
        (
            token
            for token in find_all(context, WeaponUpgrade)
            if token.actor_slot == verb.actor_slot
            and token.target_slot == verb.target_slot
        ),
        None,
    )
    if upgrade is None:
        # No upgrade judgment for this pair this tick: the weapon is gone,
        # out of camera, worn out, or no longer better than what is held.
        return _EMERGENCY_DEFAULT
    rank = upgrade.rank
    # Scales with how much of an upgrade this weapon is (rank 2..5) instead
    # of a flat weight, so a better upgrade among several candidates ranks
    # higher -- e.g. knife (rank 5) reaches the original flat value 8,
    # pepper (rank 2) sits lower at 5. Stays inside the gap between
    # ScorePickup (3) and SpecialPickup (9) so it never crosses into a
    # different verb type's tier.
    return _EMERGENCY_WALK_TO_WEAPON_BASE + rank


def _emergency_walk_to_near_enemy(verb: WalkToNearEnemy, context: Context) -> int:
    target = find(context, Enemy, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if target is None or actor is None:
        return _EMERGENCY_DEFAULT
    distance = math.hypot(target.world_x - actor.world_x, target.world_y - actor.world_y)
    return _distance_emergency(distance, base=_EMERGENCY_WALK_TO_NEAR_ENEMY, floor=8, step_px=15)


def _emergency_retreat_from_danger(verb: RetreatFromDanger, context: Context) -> int:
    target = find(context, Enemy, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if target is None or actor is None:
        return _EMERGENCY_DEFAULT
    threatening = any(
        token.actor_slot == verb.actor_slot and token.target_slot == verb.target_slot
        for token in find_all(context, IncomingMelee)
    )
    if not threatening:
        # The commit this verb was produced for is over (or the enemy
        # left the caution box): nothing left to back away from.
        return _EMERGENCY_DEFAULT
    distance = math.hypot(target.world_x - actor.world_x, target.world_y - actor.world_y)
    # Closer to the still-dangerous, not-yet-hittable enemy is more urgent to
    # back away from -- stays above WalkToNearEnemy(14) so this wins over
    # still approaching the same target, below any real attack's tier.
    # step_px is wider than the other distance-scored verbs' 15 because
    # this band is only three points tall (15..17, wedged between
    # WalkToNearEnemy and JumpAttack); 25px spreads those three points across
    # reach.too_close_to_keep_approaching's whole caution zone instead of
    # saturating at the floor a third of the way into it.
    return _distance_emergency(distance, base=_EMERGENCY_RETREAT_FROM_DANGER, floor=15, step_px=25)


def _emergency_walk_to_advance_stage(verb: WalkToAdvanceStage, context: Context) -> int:
    if _advance_blocking_enemies(context):
        return _EMERGENCY_DEFAULT
    return _EMERGENCY_WALK_TO_ADVANCE_STAGE


def _emergency_thrown_weapon(verb: Verb, context: Context, weight: int) -> int:
    """Shared range check for the two attack-thrown weapons (knife, pepper —
    items-and-weapons.md's ``$21E6``): beyond melee, within throw range."""

    target = find(context, Enemy, slot=getattr(verb, "target_slot", None))
    actor = _find_actor(context, getattr(verb, "actor_slot", None))
    if target is None or actor is None:
        return _EMERGENCY_DEFAULT
    dx = abs(target.world_x - actor.world_x)
    dy = abs(target.world_y - actor.world_y)
    beyond_melee = not (dx <= KNIFE_MELEE_X and dy <= KNIFE_RANGE_Y)
    within_range = dx <= KNIFE_RANGE_X and dy <= KNIFE_RANGE_Y
    if not (beyond_melee and within_range):
        return _EMERGENCY_DEFAULT
    distance = math.hypot(dx, dy)
    return _distance_emergency(distance, base=weight, floor=weight - 4, step_px=15)


def _emergency_throw_knife(verb: ThrowKnife, context: Context) -> int:
    return _emergency_thrown_weapon(verb, context, _EMERGENCY_THROW_KNIFE)


def _emergency_throw_pepper(verb: ThrowPepper, context: Context) -> int:
    return _emergency_thrown_weapon(verb, context, _EMERGENCY_THROW_PEPPER)


def _emergency_walk_to_pickup(verb: WalkToPickup, context: Context) -> int:
    pickup = find(context, Pickup, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if pickup is None:
        return _EMERGENCY_WALK_TO_PICKUP_SCORE
    if isinstance(pickup, HealthPickup):
        # Same threshold decide._pickup_is_useful uses to decide the pickup
        # is worth walking to at all -- a second literal here would silently
        # diverge from it.
        if actor is not None and actor.health_percent < HEALTH_CRITICAL_PERCENT:
            return _EMERGENCY_WALK_TO_PICKUP_CRITICAL_HEALTH
        return _EMERGENCY_WALK_TO_PICKUP_HEALTH
    if isinstance(pickup, LifePickup):
        return _EMERGENCY_WALK_TO_PICKUP_LIFE
    if isinstance(pickup, SpecialPickup):
        return _EMERGENCY_WALK_TO_PICKUP_SPECIAL
    if isinstance(pickup, ScorePickup):
        return _EMERGENCY_WALK_TO_PICKUP_SCORE
    return _EMERGENCY_WALK_TO_PICKUP_SCORE


def _held_enemy_emergency(weight: int) -> Callable[[Verb, Context], int]:
    """Build an ``_emergency_*`` for a hold move: ``weight`` only while its
    target ``Enemy`` is actually held (``CombatPhase.GRABBED``)."""

    def _emergency(verb: Verb, context: Context) -> int:
        target = find(context, Enemy, slot=getattr(verb, "target_slot", None))
        if target is not None and target.combat_phase is CombatPhase.GRABBED:
            return weight
        return _EMERGENCY_DEFAULT

    return _emergency


_EMERGENCY_FUNCS: dict[type[Verb], Callable[[Verb, Context], int]] = {
    CounterGrab: _emergency_counter_grab,
    TechRecover: _emergency_tech_recover,
    CallPolice: _emergency_call_police,
    RearAttack: _emergency_rear_attack,
    Punch: _emergency_melee_strike,
    SwingBatOrPipe: _emergency_melee_strike,
    StabWithKnifeOrBottle: _emergency_melee_strike,
    SprayPepper: _emergency_melee_strike,
    OpenBreakable: _emergency_open_breakable,
    GrabEnemy: _emergency_grab_enemy,
    ThrowHeldEnemy: _held_enemy_emergency(_EMERGENCY_HOLD_THROW),
    Supplex: _held_enemy_emergency(_EMERGENCY_HOLD_SUPPLEX),
    FlipHold: _held_enemy_emergency(_EMERGENCY_HOLD_FLIP),
    AttackHeldEnemy: _held_enemy_emergency(_EMERGENCY_HOLD_KNEE),
    ReleaseGrab: _held_enemy_emergency(_EMERGENCY_HOLD_RELEASE),
    JumpAttack: _emergency_jump_attack,
    ThrowKnife: _emergency_throw_knife,
    ThrowPepper: _emergency_throw_pepper,
    WalkToWeapon: _emergency_walk_to_weapon,
    WalkToPickup: _emergency_walk_to_pickup,
    WalkToNearEnemy: _emergency_walk_to_near_enemy,
    RetreatFromDanger: _emergency_retreat_from_danger,
    WalkToAdvanceStage: _emergency_walk_to_advance_stage,
}


def _stunned_target_ceiling(context: Context, target_slot: str | None) -> int | None:
    """The emergency ceiling for attacking ``target_slot``, or ``None``.

    ``None`` means "not a stunned target, no ceiling": only ordinary enemies
    have the ROM counter behind ``is_stunned``, so a ``Boss``, a
    ``Breakable`` or a missing target never gets one.

    The remaining time decides which ceiling, read from the target's
    ``PunishWindow`` (the token that exists precisely so this does not have
    to go back to raw observation fields) and falling back to the Grunt's
    own counter if no window is in context. Above ``HITSTUN_FRAMES`` the
    timer can only belong to the long pepper-spray stun, since that is the
    larger of the ROM's two seeds and both only count down. A pepper stun
    that *has* counted down into hitstun range is about to end, which is
    exactly when treating it as a combo window is right again.
    """

    if target_slot is None:
        return None
    target = find(context, Enemy, slot=target_slot)
    if not (isinstance(target, Grunt) and target.is_stunned):
        return None
    window = next(
        (token for token in find_all(context, PunishWindow) if token.target_slot == target_slot),
        None,
    )
    frames_left = window.frames_left if window is not None else target.stun_timer
    if frames_left > HITSTUN_FRAMES:
        return _EMERGENCY_ATTACK_LONG_STUN
    return _EMERGENCY_ATTACK_HITSTUN


def _emergency(verb: Verb, context: Context) -> int:
    func = _EMERGENCY_FUNCS.get(type(verb))
    score = _EMERGENCY_DEFAULT if func is None else func(verb, context)
    if isinstance(verb, Attack):
        # A stunned enemy cannot act, cannot retaliate, and will still be
        # standing there in a moment, so it must never outrank dealing with
        # one that can -- which is what the punishable tier (60) made it do,
        # above even the RearAttack escape (55) with a second enemy live at
        # the actor's back. Strictly a ceiling: an attack already ranked
        # lower keeps its own score.
        ceiling = _stunned_target_ceiling(context, getattr(verb, "target_slot", None))
        if ceiling is not None:
            return min(score, ceiling)
    return score


def determine_priority_verb(context: Context) -> Context:
    """Keep every ``Information`` token; collapse ``Verb`` tokens to one."""

    verbs = find_all(context, Verb)
    if not verbs:
        return context

    scored = [(_emergency(verb, context), verb) for verb in verbs]
    max_emergency = max(score for score, _ in scored)
    top_emergency = [verb for score, verb in scored if score == max_emergency]

    max_priority = max(verb.priority for verb in top_emergency)
    tied = [verb for verb in top_emergency if verb.priority == max_priority]

    if len(tied) == 1:
        winner = tied[0]
    else:
        # tied entries are never literally the same object here: Context is
        # a set of frozen/hashable Verb dataclasses, so two candidates
        # with identical priority/actor_slot/target_slot would already have
        # deduplicated into one. Log full repr (not just the class name) so
        # that distinguishing field -- almost always a different
        # target_slot/actor_slot -- is visible instead of looking like a
        # duplicate.
        details = ", ".join(sorted(repr(verb) for verb in tied))
        logger.warning(
            "determine_priority_verb: %d verbs tied at emergency=%d "
            "priority=%d (%s); picking one at random. Assign distinct "
            "priorities to break this deterministically.",
            len(tied),
            max_emergency,
            max_priority,
            details,
        )
        winner = random.choice(tied)

    return {token for token in context if not isinstance(token, Verb)} | {winner}
