"""``determine_priority_decision`` — rank ``Decision`` tokens by emergency.

Per ``AI.md``: this also performs target selection, since ranking by
emergency and keeping only the highest-ranked ``Decision`` is what collapses
several same-type candidates (e.g. a ``Punch`` against each of two nearby
enemies) down to one.

Each ``_emergency_*`` function below computes its score from the
``Information`` tokens present in the ``Context`` — per the matching
concrete ``Decision`` class's ``Raises emergency: ...`` docstring line —
never from the decision's type alone. The module constants are named
*contributions* consulted when their token condition holds; they are not
applied unconditionally.
"""

from __future__ import annotations

import logging
import math
import random
from collections.abc import Callable

from ..phases import CombatPhase, is_dangerous
from . import reach
from .decide import (
    HEALTH_CRITICAL_PERCENT,
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
    JumpAttack,
    AttackHeldEnemy,
    Punch,
    RearAttack,
    ReleaseGrab,
    SmashBreakable,
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
from .tokens import IncomingMelee, PunishWindow, Surrounded, WeaponUpgrade
from .tokens import (
    HealthPickup,
    LifePickup,
    Pickup,
    ScorePickup,
    SpecialPickup,
)
from .tokens import CallPolice
from .tokens import Context, Decision, find, find_all
from .tokens import (
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToBreakable,
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
# Ceiling (never a raise -- see _emergency) for any Attack whose target is a
# stunned Grunt. Deliberately wedged between WalkToNearEnemy's base (14) and
# a plain Punch (20):
#
# - above every Walk tier, so the actor keeps hitting the stunned body when
#   nothing better exists instead of wandering off to fetch another enemy;
# - above RetreatFromDanger (17..15), preserving "attacking always wins once
#   actually possible";
# - below a plain strike on an enemy that can still act (20), and far below
#   the RearAttack escape (55/60), so a second enemy anywhere near always
#   gets dealt with first.
_EMERGENCY_ATTACK_STUNNED = 19
_EMERGENCY_HOLD_THROW = 70  # throw held body into rear threat
_EMERGENCY_HOLD_SUPPLEX = 68
_EMERGENCY_HOLD_FLIP = 66
_EMERGENCY_HOLD_KNEE = 64
_EMERGENCY_HOLD_RELEASE = 50
_EMERGENCY_JUMP_ATTACK_PUNISHABLE = 28  # below punch; never prefer hop over strike
_EMERGENCY_JUMP_ATTACK_DEFAULT = 18
_EMERGENCY_THROW_KNIFE = 25
_EMERGENCY_THROW_PEPPER = 25
_EMERGENCY_SMASH_BREAKABLE = 16
_EMERGENCY_WALK_TO_BREAKABLE = 14
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
    a different decision type's tier. This is what lets ``could_*``
    functions (decide.py) stop pre-selecting a single "best" candidate
    themselves and produce one Decision per possibility instead, per
    AI.md's own worked example (several ``Punch`` candidates collapsing to
    one only in ``determine_priority_decision``): the ranking still favours
    the closest/best option, it just happens here instead of inside the
    could_* function.

    A handful of coarse buckets was tried first and discarded: with several
    enemies clustered together (the common case), most fell into the same
    bucket and tied every tick, so determine_priority_decision's random
    tie-break kept flipping the target -- confirmed live against a running
    host. One point per ``step_px`` makes an exact tie between two distinct
    candidates rare in practice.
    """

    return max(floor, base - int(distance // step_px))


def _emergency_counter_grab(decision: CounterGrab, context: Context) -> int:
    actor = _find_actor(context, decision.actor_slot)
    if actor is not None and actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
        return _EMERGENCY_COUNTER_GRAB
    return _EMERGENCY_DEFAULT


def _emergency_tech_recover(decision: TechRecover, context: Context) -> int:
    actor = _find_actor(context, decision.actor_slot)
    if actor is not None and actor.throw_tech_ready:
        return _EMERGENCY_TECH_RECOVER
    return _EMERGENCY_DEFAULT


def _emergency_call_police(decision: CallPolice, context: Context) -> int:
    actor = _find_actor(context, decision.actor_slot)
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


def _emergency_rear_attack(decision: RearAttack, context: Context) -> int:
    target = find(context, Enemy, slot=decision.target_slot)
    actor = _find_actor(context, decision.actor_slot)
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


def _emergency_melee_strike(decision: Decision, context: Context) -> int:
    """Shared scoring for ``Punch`` / ``SwingBatOrPipe`` /
    ``StabWithKnifeOrBottle`` / ``SprayPepper`` -- same formula regardless
    of held weapon, since none of these has evidence of a different
    punishable-phase payoff."""

    target = find(context, Enemy, slot=getattr(decision, "target_slot", None))
    if target is None:
        return _EMERGENCY_DEFAULT
    if _is_punish_window(context, target.slot):
        return _EMERGENCY_PUNCH_PUNISHABLE
    return _EMERGENCY_PUNCH_DEFAULT


def _emergency_jump_attack(decision: JumpAttack, context: Context) -> int:
    target = find(context, Enemy, slot=decision.target_slot)
    if target is None:
        return _EMERGENCY_DEFAULT
    if _is_punish_window(context, target.slot):
        return _EMERGENCY_JUMP_ATTACK_PUNISHABLE
    return _EMERGENCY_JUMP_ATTACK_DEFAULT


def _emergency_smash_breakable(decision: SmashBreakable, context: Context) -> int:
    target = find(context, Breakable, slot=decision.target_slot)
    if target is None:
        return _EMERGENCY_DEFAULT
    return _EMERGENCY_SMASH_BREAKABLE


def _emergency_walk_to_breakable(decision: WalkToBreakable, context: Context) -> int:
    target = find(context, Breakable, slot=decision.target_slot)
    actor = _find_actor(context, decision.actor_slot)
    if target is None or actor is None:
        return _EMERGENCY_DEFAULT
    distance = math.hypot(target.world_x - actor.world_x, target.world_y - actor.world_y)
    return _distance_emergency(distance, base=_EMERGENCY_WALK_TO_BREAKABLE, floor=8, step_px=15)


def _emergency_walk_to_weapon(decision: WalkToWeapon, context: Context) -> int:
    upgrade = next(
        (
            token
            for token in find_all(context, WeaponUpgrade)
            if token.actor_slot == decision.actor_slot
            and token.target_slot == decision.target_slot
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
    # different decision type's tier.
    return _EMERGENCY_WALK_TO_WEAPON_BASE + rank


def _emergency_walk_to_near_enemy(decision: WalkToNearEnemy, context: Context) -> int:
    target = find(context, Enemy, slot=decision.target_slot)
    actor = _find_actor(context, decision.actor_slot)
    if target is None or actor is None:
        return _EMERGENCY_DEFAULT
    distance = math.hypot(target.world_x - actor.world_x, target.world_y - actor.world_y)
    return _distance_emergency(distance, base=_EMERGENCY_WALK_TO_NEAR_ENEMY, floor=8, step_px=15)


def _emergency_retreat_from_danger(decision: RetreatFromDanger, context: Context) -> int:
    target = find(context, Enemy, slot=decision.target_slot)
    actor = _find_actor(context, decision.actor_slot)
    if target is None or actor is None:
        return _EMERGENCY_DEFAULT
    threatening = any(
        token.actor_slot == decision.actor_slot and token.target_slot == decision.target_slot
        for token in find_all(context, IncomingMelee)
    )
    if not threatening:
        # The commit this decision was produced for is over (or the enemy
        # left the caution box): nothing left to back away from.
        return _EMERGENCY_DEFAULT
    distance = math.hypot(target.world_x - actor.world_x, target.world_y - actor.world_y)
    # Closer to the still-dangerous, not-yet-hittable enemy is more urgent to
    # back away from -- stays above WalkToNearEnemy(14) so this wins over
    # still approaching the same target, below any real attack's tier.
    # step_px is wider than the other distance-scored decisions' 15 because
    # this band is only three points tall (15..17, wedged between
    # WalkToNearEnemy and JumpAttack); 25px spreads those three points across
    # reach.too_close_to_keep_approaching's whole caution zone instead of
    # saturating at the floor a third of the way into it.
    return _distance_emergency(distance, base=_EMERGENCY_RETREAT_FROM_DANGER, floor=15, step_px=25)


def _emergency_walk_to_advance_stage(decision: WalkToAdvanceStage, context: Context) -> int:
    if _advance_blocking_enemies(context):
        return _EMERGENCY_DEFAULT
    return _EMERGENCY_WALK_TO_ADVANCE_STAGE


def _emergency_thrown_weapon(decision: Decision, context: Context, weight: int) -> int:
    """Shared range check for the two attack-thrown weapons (knife, pepper —
    items-and-weapons.md's ``$21E6``): beyond melee, within throw range."""

    target = find(context, Enemy, slot=getattr(decision, "target_slot", None))
    actor = _find_actor(context, getattr(decision, "actor_slot", None))
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


def _emergency_throw_knife(decision: ThrowKnife, context: Context) -> int:
    return _emergency_thrown_weapon(decision, context, _EMERGENCY_THROW_KNIFE)


def _emergency_throw_pepper(decision: ThrowPepper, context: Context) -> int:
    return _emergency_thrown_weapon(decision, context, _EMERGENCY_THROW_PEPPER)


def _emergency_walk_to_pickup(decision: WalkToPickup, context: Context) -> int:
    pickup = find(context, Pickup, slot=decision.target_slot)
    actor = _find_actor(context, decision.actor_slot)
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


def _held_enemy_emergency(weight: int) -> Callable[[Decision, Context], int]:
    """Build an ``_emergency_*`` for a hold move: ``weight`` only while its
    target ``Enemy`` is actually held (``CombatPhase.GRABBED``)."""

    def _emergency(decision: Decision, context: Context) -> int:
        target = find(context, Enemy, slot=getattr(decision, "target_slot", None))
        if target is not None and target.combat_phase is CombatPhase.GRABBED:
            return weight
        return _EMERGENCY_DEFAULT

    return _emergency


_EMERGENCY_FUNCS: dict[type[Decision], Callable[[Decision, Context], int]] = {
    CounterGrab: _emergency_counter_grab,
    TechRecover: _emergency_tech_recover,
    CallPolice: _emergency_call_police,
    RearAttack: _emergency_rear_attack,
    Punch: _emergency_melee_strike,
    SwingBatOrPipe: _emergency_melee_strike,
    StabWithKnifeOrBottle: _emergency_melee_strike,
    SprayPepper: _emergency_melee_strike,
    SmashBreakable: _emergency_smash_breakable,
    ThrowHeldEnemy: _held_enemy_emergency(_EMERGENCY_HOLD_THROW),
    Supplex: _held_enemy_emergency(_EMERGENCY_HOLD_SUPPLEX),
    FlipHold: _held_enemy_emergency(_EMERGENCY_HOLD_FLIP),
    AttackHeldEnemy: _held_enemy_emergency(_EMERGENCY_HOLD_KNEE),
    ReleaseGrab: _held_enemy_emergency(_EMERGENCY_HOLD_RELEASE),
    JumpAttack: _emergency_jump_attack,
    ThrowKnife: _emergency_throw_knife,
    ThrowPepper: _emergency_throw_pepper,
    WalkToBreakable: _emergency_walk_to_breakable,
    WalkToWeapon: _emergency_walk_to_weapon,
    WalkToPickup: _emergency_walk_to_pickup,
    WalkToNearEnemy: _emergency_walk_to_near_enemy,
    RetreatFromDanger: _emergency_retreat_from_danger,
    WalkToAdvanceStage: _emergency_walk_to_advance_stage,
}


def _target_is_stunned(context: Context, target_slot: str | None) -> bool:
    """Whether this decision's target is a ``Grunt`` frozen on a timed stun.

    Only ordinary enemies have the ROM counter behind ``is_stunned``; a
    ``Boss``, a ``Breakable`` or a missing target all answer no.
    """

    if target_slot is None:
        return False
    target = find(context, Enemy, slot=target_slot)
    return isinstance(target, Grunt) and target.is_stunned


def _emergency(decision: Decision, context: Context) -> int:
    func = _EMERGENCY_FUNCS.get(type(decision))
    score = _EMERGENCY_DEFAULT if func is None else func(decision, context)
    if isinstance(decision, Attack) and _target_is_stunned(
        context, getattr(decision, "target_slot", None)
    ):
        # A stunned enemy is the one target that is *not* going anywhere:
        # it cannot act, cannot retaliate, and will still be standing there
        # in a moment. Hitting it is worth doing when nothing else is on the
        # table, but it must never outrank dealing with an enemy that can
        # still act -- which is what the punishable tier (60) made it do,
        # above even the RearAttack escape (55) with a second enemy live at
        # the actor's back.
        return min(score, _EMERGENCY_ATTACK_STUNNED)
    return score


def determine_priority_decision(context: Context) -> Context:
    """Keep every ``Information`` token; collapse ``Decision`` tokens to one."""

    decisions = find_all(context, Decision)
    if not decisions:
        return context

    scored = [(_emergency(decision, context), decision) for decision in decisions]
    max_emergency = max(score for score, _ in scored)
    top_emergency = [decision for score, decision in scored if score == max_emergency]

    max_priority = max(decision.priority for decision in top_emergency)
    tied = [decision for decision in top_emergency if decision.priority == max_priority]

    if len(tied) == 1:
        winner = tied[0]
    else:
        # tied entries are never literally the same object here: Context is
        # a set of frozen/hashable Decision dataclasses, so two candidates
        # with identical priority/actor_slot/target_slot would already have
        # deduplicated into one. Log full repr (not just the class name) so
        # that distinguishing field -- almost always a different
        # target_slot/actor_slot -- is visible instead of looking like a
        # duplicate.
        details = ", ".join(sorted(repr(decision) for decision in tied))
        logger.warning(
            "determine_priority_decision: %d decisions tied at emergency=%d "
            "priority=%d (%s); picking one at random. Assign distinct "
            "priorities to break this deterministically.",
            len(tied),
            max_emergency,
            max_priority,
            details,
        )
        winner = random.choice(tied)

    return {token for token in context if not isinstance(token, Decision)} | {winner}
