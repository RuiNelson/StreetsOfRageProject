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
from collections.abc import Callable

from ..phases import HITSTUN_FRAMES, CombatPhase, is_dangerous
from . import reach
from .decide import (
    HEALTH_CRITICAL_PERCENT,
    in_smash_range,
    POLICE_HEALTH_PERCENT_THRESHOLD,
    POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE,
    thrown_weapon_impact_point,
    thrown_weapon_would_connect,
    _advance_blocking_breakables,
    _advance_blocking_enemies,
)
from .tokens import (
    Attack,
    CounterGrab,
    DodgeAntonioKick,
    FlipHold,
    GrabEnemy,
    HitAntonioBoomerang,
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
from .tokens import Antonio, Boss, Breakable, Enemy, Grunt, Jack, Nora
from .tokens import (
    AntonioIsGoingToKick,
    GrabOpportunity,
    GrabAntonioOnPunish,
    GrabIntoDeadZone,
    GrabJackFromBehind,
    GrabToClearRear,
    IncomingMelee,
    IncomingProjectile,
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
    is_weapon_type,
)
from .tokens import CallPolice
from .tokens import HandleContinueMenu, HandleMrXDialog, InContinueMenu, InMrXDialog
from .tokens import Context, Verb, find, find_all
from .tokens import (
    ProjectileSidestep,
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)

logger = logging.getLogger(__name__)

# 0-100 emergency scale.
_EMERGENCY_COUNTER_GRAB = 100  # already held — only useful action
# UI prompts lock the actor: continue / Mr. X are the only useful action
# while their Observed token is present (combat verbs may still be generated
# during the Mr. X offer because Myself is still playable).
_EMERGENCY_HANDLE_CONTINUE = 99
_EMERGENCY_HANDLE_MR_X = 99
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
# The same ceiling again, for the case the two above do not cover: another
# enemy is *about to hit the actor* (an `IncomingMelee` naming a different
# target) while the current one is parked.
#
# This is the user-reported case, and the whole reason `_stunned_target_
# ceiling` exists in the first place -- "a stunned enemy cannot act, cannot
# retaliate, and will still be standing there in a moment, so it must never
# outrank dealing with one that can". The two ceilings above did not achieve
# it: 21 and 19 both beat `WalkToNearEnemy`'s realistic 11..14, so the AI
# kept comboing a stunned body while a second enemy walked up behind it and
# punched it in the back. The parked target loses nothing by waiting -- that
# is what "parked" means.
#
# Placed just under WalkToNearEnemy's own base (14) rather than at 0, so the
# turn-and-face wins while the threat is genuinely close (its distance
# scoring puts it at 11..14 inside ~45px) and the punish still wins over a
# distant one. On an exact tie the `priority` field settles it in the walk's
# favour anyway (20 vs 10).
_EMERGENCY_ATTACK_PARKED_UNDER_THREAT = 10
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
# Caught Jack from behind: take the hold before he turns. Above every
# strike on an enemy that can still act (20) and above the jump-kick
# punish (28), just under clearing a pincer (58) -- a rear threat still
# outranks finishing Jack -- and under the chord against a *committed*
# Jack at the actor's own back (60), which has no time to walk in.
_EMERGENCY_GRAB_JACK_FROM_BEHIND = 56
# An enemy whose every attack starts further out than contact (Nora, per the
# extracted ranges) has nothing to answer a body pressed against it, so
# holding it beats trading strikes -- but it is an improvement on an ordinary
# fight, not an escape from a bad one, so it sits just above the
# jump-kick-on-a-punishable tier (28) and well under the punish/escape tiers.
_EMERGENCY_GRAB_DEAD_ZONE = 30
# Antonio in hitstun: grab-then-suplex instead of standing still to
# combo him. The boss raise (+14) is applied on top, so this must
# clear punch-on-punish (60+14 = 74): otherwise an injected or stale
# Punch still wins the tick and the hold never starts. Below
# CounterGrab/TechRecover/CallPolice (100/90/88). Hold moves on an
# existing grab (64..70) do not coexist -- could_grab skips while
# holding.
_EMERGENCY_GRAB_ANTONIO_ON_PUNISH = 61
_EMERGENCY_HOLD_THROW = 70  # throw held body into rear threat
_EMERGENCY_HOLD_SUPPLEX = 68
_EMERGENCY_HOLD_FLIP = 66
_EMERGENCY_HOLD_KNEE = 64
_EMERGENCY_HOLD_RELEASE = 50
_EMERGENCY_JUMP_ATTACK_PUNISHABLE = 28  # below punch; never prefer hop over strike
# Nora specifically, freshly out of her own whip engage-and-swing or lunge
# (Nora.ticks_since_last_attack -- observe.NoraAttackTracker) but not (yet)
# re-armed and not in any ROM-confirmed PunishWindow phase, so this sits
# below a real punish window (28) -- it is a probabilistic opening, not a
# guaranteed one; her post-swing decision table was not traced to a hard
# minimum-recovery number -- and above the plain default (18), so closing
# the gap with a kick is preferred over a routine approach or a lower-
# urgency target elsewhere for as long as the window looks fresh.
_EMERGENCY_JUMP_ATTACK_NORA_RECOVERY = 24
_EMERGENCY_JUMP_ATTACK_DEFAULT = 18
# How many ticks after Nora's own attack ends she still counts as "freshly"
# vulnerable for the tier above. Not a ROM-confirmed minimum recovery time --
# deliberately conservative, comparable to reach.CLOSING_ENEMY_THREAT_FRAMES's
# own "how far ahead is trusted" horizon at the same ~33ms poll default.
NORA_RECOVERY_PUNISH_TICKS = 10
_EMERGENCY_THROW_KNIFE = 25
_EMERGENCY_THROW_PEPPER = 25
# One verb, two tiers -- the same two the former SmashBreakable (flat 16 in
# range) and WalkToBreakable (14 down to 8 by distance) carried, so merging
# them changed no ranking: being in range is simply the top of OpenBreakable's
# own scale rather than a different verb.
_EMERGENCY_OPEN_BREAKABLE_IN_RANGE = 16
_EMERGENCY_OPEN_BREAKABLE_APPROACH = 14
# WalkToNearEnemy's floor is 8 (see below), and an enemy is present on screen
# almost continuously in this game, so any tier at or under 8 can *never* win
# against it -- not "loses when an enemy is close", but mathematically
# unreachable the instant any enemy exists anywhere in camera. That was a
# live bug, not a design choice: with the old base of 3 (range 5..8), a
# WalkToWeapon could tie WalkToNearEnemy's floor at best (rank 5, knife) and
# never actually beat it, so the AI left upgrade weapons on the floor to go
# fight instead. Raised so every rank clears the floor outright and the top
# ranks (bat/pipe 4, knife 5) also beat a normal HealthPickup (15) -- "a
# weapon upgrade is usually more durable value" (WalkToPickup's own
# docstring) -- while staying under the weakest real attack tier
# (_EMERGENCY_JUMP_ATTACK_DEFAULT, 18) so an already-possible strike is never
# abandoned to fetch a weapon.
_EMERGENCY_WALK_TO_WEAPON = 17  # reference value: knife (rank 5) via _EMERGENCY_WALK_TO_WEAPON_BASE
_EMERGENCY_WALK_TO_WEAPON_BASE = 12  # + weapon_rank (2..5) -> 14..17
_EMERGENCY_WALK_TO_PICKUP_CRITICAL_HEALTH = 50
_EMERGENCY_WALK_TO_PICKUP_HEALTH = 15
_EMERGENCY_WALK_TO_PICKUP_LIFE = 12
# Special and Score raised for the same floor-of-8 reason as the weapon tiers
# above (Score was 3, mathematically unreachable whenever any enemy existed
# anywhere on screen -- the AI never once fetched a score pickup mid-stage).
# Kept strictly below Life(12) and Health(15), and Special kept above Score,
# preserving the original value-driven ordering Health > Life > Special >
# Score; both now clear the floor.
_EMERGENCY_WALK_TO_PICKUP_SPECIAL = 11
_EMERGENCY_WALK_TO_PICKUP_SCORE = 9
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
# A confirmed incoming projectile (Jack's thrown axe/torch, or any other
# Projectile inference judges a real threat) has no melee answer at all --
# only getting out of its lane does. Sits above every ordinary approach/
# retreat tier so the actor clears the lane before the weapon lands, but
# below a guaranteed PunishWindow strike (60) and the RearAttack/
# GrabToClearRear escapes (55/58/60): those stay the right answer even with
# a projectile also in flight, since abandoning a free hit to dodge a throw
# that might still be avoided on its own trades a certain gain for an
# uncertain one.
_EMERGENCY_PROJECTILE_SIDESTEP = 45  # sooner-to-impact scoring higher, floor 30
# Punching Antonio's incoming boomerang (type $96) back. Above the kick
# dodge: jumping into a boomerang that is already in the punch box is
# how the opening hit of the fight lands. The kick's own startup is
# longer than a punch, so the boomerang is answered first.
_EMERGENCY_HIT_ANTONIO_BOOMERANG = 62
# Sidestep / hop out of Antonio's kick window. Above HitAntonioBoomerang
# and every strike on an Antonio that can still act: standing still to
# punch is exactly what arms the kick ($16EAE zero-velocity path).
_EMERGENCY_DODGE_ANTONIO_KICK = 58
# Jump-kick over a kick that is already coming -- used only while the
# actor is airborne/crouching (DodgeAntonioKick is suppressed then). Just
# under the grounded dodge so a hop that has already started is not
# abandoned, well above a routine jump (18).
_EMERGENCY_JUMP_OVER_ANTONIO_KICK = 56
# Lowest of any verb that still scores. Must sit under every other live
# candidate -- including ScorePickup (9), SpecialPickup (11), LifePickup
# (12), and WalkToNearEnemy's floor (8) -- so stage advance is only chosen
# when nothing else applies. The previous 12 beat pickups and distant
# approaches; the blocking-enemy / blocking-breakable gates already zero
# this verb when those targets exist, so the high floor is no longer needed
# to win those contests.
_EMERGENCY_WALK_TO_ADVANCE_STAGE = 1
# Added to an engagement verb (walk-in, strike, grab, throw) whose target
# is an armed ordinary enemy or a Boss. Sized to dominate WalkToNearEnemy's
# 6-point distance span (base 14, floor 8) so a far armed foe still beats a
# close unarmed one, and a far boss still beats a close armed one. Bosses
# are excepted from the armed bonus -- they get this larger raise instead.
_EMERGENCY_ARMED_TARGET = 7
_EMERGENCY_BOSS_TARGET = 14
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


def _enemy_is_armed(target: Enemy) -> bool:
    """Whether this ordinary enemy is carrying a weapon right now.

    A pickup ($08-$0C) on ``held_weapon_type``, or Jack still juggling his
    axe/torch. Bosses are not "armed" in this sense -- they have their own
    raise -- so callers check ``Boss`` first.
    """

    if is_weapon_type(target.held_weapon_type):
        return True
    return isinstance(target, Jack) and target.has_projectile


def _target_class_bonus(target: Enemy | None) -> int:
    """How much extra an engagement verb is worth against this enemy.

    Bosses first, then armed ordinary enemies, then everyone else. The
    bonuses dominate distance scoring so the class rank cannot lose to a
    closer but less important body.
    """

    if target is None:
        return 0
    if isinstance(target, Boss):
        return _EMERGENCY_BOSS_TARGET
    if _enemy_is_armed(target):
        return _EMERGENCY_ARMED_TARGET
    return 0


def _with_target_class(score: int, target: Enemy | None) -> int:
    """Apply the boss/armed raise to a score that already qualified.

    A 0 stays 0: a verb whose own condition failed (target gone, threat
    over, out of range) must not be revived by who it was aimed at.
    """

    if score <= _EMERGENCY_DEFAULT:
        return score
    return score + _target_class_bonus(target)


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


def _emergency_handle_continue_menu(verb: HandleContinueMenu, context: Context) -> int:
    menu = find(context, InContinueMenu, slot=verb.actor_slot)
    if menu is not None:
        return _EMERGENCY_HANDLE_CONTINUE
    return _EMERGENCY_DEFAULT


def _emergency_handle_mr_x_dialog(verb: HandleMrXDialog, context: Context) -> int:
    dialog = find(context, InMrXDialog, slot=verb.actor_slot)
    if dialog is not None:
        return _EMERGENCY_HANDLE_MR_X
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
        score = _EMERGENCY_REAR_ATTACK_DANGEROUS if dangerous else _EMERGENCY_REAR_ATTACK
    else:
        score = (
            _EMERGENCY_REAR_ATTACK_UNWARRANTED_DANGEROUS
            if dangerous
            else _EMERGENCY_REAR_ATTACK_UNWARRANTED
        )
    return _with_target_class(score, target)


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
        return _with_target_class(_EMERGENCY_PUNCH_PUNISHABLE, target)
    return _with_target_class(_EMERGENCY_PUNCH_DEFAULT, target)


def _emergency_jump_attack(verb: JumpAttack, context: Context) -> int:
    target = find(context, Enemy, slot=verb.target_slot)
    if target is None:
        return _EMERGENCY_DEFAULT
    if (
        isinstance(target, Antonio)
        and target.strike_is_committed()
        and any(
            token.actor_slot == verb.actor_slot and token.target_slot == verb.target_slot
            for token in find_all(context, AntonioIsGoingToKick)
        )
    ):
        return _with_target_class(_EMERGENCY_JUMP_OVER_ANTONIO_KICK, target)
    if _is_punish_window(context, target.slot):
        return _with_target_class(_EMERGENCY_JUMP_ATTACK_PUNISHABLE, target)
    if (
        isinstance(target, Nora)
        and not is_dangerous(target.combat_phase)
        and target.ticks_since_last_attack <= NORA_RECOVERY_PUNISH_TICKS
    ):
        return _with_target_class(_EMERGENCY_JUMP_ATTACK_NORA_RECOVERY, target)
    return _with_target_class(_EMERGENCY_JUMP_ATTACK_DEFAULT, target)


def _emergency_dodge_antonio_kick(verb: DodgeAntonioKick, context: Context) -> int:
    if any(
        token.actor_slot == verb.actor_slot and token.target_slot == verb.target_slot
        for token in find_all(context, AntonioIsGoingToKick)
    ):
        return _EMERGENCY_DODGE_ANTONIO_KICK
    return _EMERGENCY_DEFAULT


def _emergency_hit_antonio_boomerang(verb: HitAntonioBoomerang, context: Context) -> int:
    from .tokens import Projectile

    projectile = find(context, Projectile, slot=verb.target_slot)
    if projectile is None:
        return _EMERGENCY_DEFAULT
    return _EMERGENCY_HIT_ANTONIO_BOOMERANG


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
    if any(isinstance(token, GrabJackFromBehind) for token in opportunities):
        score = max(score, _EMERGENCY_GRAB_JACK_FROM_BEHIND)
    if any(isinstance(token, GrabIntoDeadZone) for token in opportunities):
        score = max(score, _EMERGENCY_GRAB_DEAD_ZONE)
    if any(isinstance(token, GrabAntonioOnPunish) for token in opportunities):
        score = max(score, _EMERGENCY_GRAB_ANTONIO_ON_PUNISH)
    return _with_target_class(score, find(context, Enemy, slot=verb.target_slot))


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
    # higher -- e.g. knife (rank 5) reaches 17, pepper (rank 2) sits lower at
    # 14. Every rank clears WalkToNearEnemy's floor (8) outright, and stays
    # below the weakest real attack tier (_EMERGENCY_JUMP_ATTACK_DEFAULT, 18)
    # so it never crosses into a different verb type's tier.
    return _EMERGENCY_WALK_TO_WEAPON_BASE + rank


def _emergency_walk_to_near_enemy(verb: WalkToNearEnemy, context: Context) -> int:
    target = find(context, Enemy, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if target is None or actor is None:
        return _EMERGENCY_DEFAULT
    distance = math.hypot(target.world_x - actor.world_x, target.world_y - actor.world_y)
    return _with_target_class(
        _distance_emergency(distance, base=_EMERGENCY_WALK_TO_NEAR_ENEMY, floor=8, step_px=15),
        target,
    )


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


def _emergency_projectile_sidestep(verb: ProjectileSidestep, context: Context) -> int:
    """Sooner-to-impact scores higher, using the same ticks-to-impact
    ``inference._projectile_threatens`` computed to promote this
    ``IncomingProjectile`` in the first place -- reusing ``_distance_emergency``
    with a tick count standing in for its usual pixel distance, since both
    are "how much runway is left before this needs to be answered"."""

    projectile = find(context, IncomingProjectile, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if projectile is None or actor is None:
        return _EMERGENCY_DEFAULT
    if projectile.vel_x == 0:
        ticks = 0.0
    else:
        ticks = abs(projectile.world_x - actor.world_x) / abs(projectile.vel_x)
    return _distance_emergency(
        ticks, base=_EMERGENCY_PROJECTILE_SIDESTEP, floor=30, step_px=2
    )


def _emergency_walk_to_advance_stage(verb: WalkToAdvanceStage, context: Context) -> int:
    if _advance_blocking_enemies(context) or _advance_blocking_breakables(context):
        return _EMERGENCY_DEFAULT
    return _EMERGENCY_WALK_TO_ADVANCE_STAGE


def _emergency_thrown_weapon(verb: Verb, context: Context, weight: int) -> int:
    """Shared range check for the two attack-thrown weapons (knife, pepper —
    items-and-weapons.md's ``$21E6``): beyond melee, within throw range.

    Judged at the interception point, exactly as ``decide`` judged it when
    producing the verb (``decide.thrown_weapon_impact_point``) -- the two must
    agree about *where* the target is, or a verb could be produced and then
    scored 0 for being out of a range it was never measured against. The
    distance that scores one candidate against another is that same flight
    distance, so a target running away ranks below one standing still at the
    same current gap.
    """

    target = find(context, Enemy, slot=getattr(verb, "target_slot", None))
    actor = _find_actor(context, getattr(verb, "actor_slot", None))
    if target is None or actor is None:
        return _EMERGENCY_DEFAULT
    if not thrown_weapon_would_connect(actor, target, type(verb)):
        return _EMERGENCY_DEFAULT
    # Rank by how far the weapon actually has to fly, so a target running
    # away scores below one standing still at the same instantaneous gap.
    impact = thrown_weapon_impact_point(actor, target, type(verb))
    distance = math.hypot(impact.world_x - actor.world_x, impact.world_y - actor.world_y)
    return _with_target_class(
        _distance_emergency(distance, base=weight, floor=weight - 4, step_px=15),
        target,
    )


def _emergency_throw_knife(verb: ThrowKnife, context: Context) -> int:
    return _emergency_thrown_weapon(verb, context, _EMERGENCY_THROW_KNIFE)


def _emergency_throw_pepper(verb: ThrowPepper, context: Context) -> int:
    return _emergency_thrown_weapon(verb, context, _EMERGENCY_THROW_PEPPER)


def _emergency_walk_to_pickup(verb: WalkToPickup, context: Context) -> int:
    pickup = find(context, Pickup, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if pickup is None:
        # Target gone this tick -- same answer every other _emergency_* gives
        # for a missing target. Returning the ScorePickup tier instead kept a
        # verb aimed at nothing ranked above WalkToAdvanceStage(1).
        return _EMERGENCY_DEFAULT
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
    HandleContinueMenu: _emergency_handle_continue_menu,
    HandleMrXDialog: _emergency_handle_mr_x_dialog,
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
    ProjectileSidestep: _emergency_projectile_sidestep,
    DodgeAntonioKick: _emergency_dodge_antonio_kick,
    HitAntonioBoomerang: _emergency_hit_antonio_boomerang,
    WalkToAdvanceStage: _emergency_walk_to_advance_stage,
}


def _other_enemy_is_incoming(context: Context, actor_slot: str, target_slot: str) -> bool:
    """Is something *other than* this target about to hit the actor?

    Reads the `IncomingMelee` judgments inference already made, so "about to
    hit me" has one definition across the pipeline.
    """

    return any(
        token.actor_slot == actor_slot and token.target_slot != target_slot
        for token in find_all(context, IncomingMelee)
    )


def _stunned_target_ceiling(
    context: Context, actor_slot: str | None, target_slot: str | None
) -> int | None:
    """The emergency ceiling for attacking ``target_slot``, or ``None``.

    ``None`` means "not a parked target, no ceiling": only ordinary enemies
    have the ROM counter behind ``is_stunned``, so a ``Boss``, a
    ``Breakable`` or a missing target never gets one.

    A **stunned** target is parked: it cannot act, cannot retaliate, and will
    still be there in a moment. So when another enemy is about to land a hit
    on the actor (`_other_enemy_is_incoming`), finishing the combo is worth
    less than turning to face the one that can actually hurt it -- reported
    from play as taking a punch in the back while hitting an enemy that was
    already stunned, and the reason this ceiling exists at all.

    A **knockdown** is deliberately not treated the same way: that window
    ends in a wake-up with invulnerability, so unlike a stun it really does
    have to be used now.

    The remaining time decides which ceiling, read from the target's
    ``PunishWindow`` (the token that exists precisely so this does not have
    to go back to raw observation fields) and falling back to the Grunt's
    own counter if no window is in context. Above ``HITSTUN_FRAMES`` the
    timer either belongs to the long pepper-spray stun or to Nora's own
    "feign injury" recovery (``phases.py``'s ``0x26`` table, state ``$0C``
    seeds ``$80`` -- 128 frames), and both only count down. A pepper stun
    that *has* counted down into hitstun range is about to end, which is
    exactly when treating it as a combo window is right again.
    """

    if target_slot is None:
        return None
    target = find(context, Enemy, slot=target_slot)
    if not (isinstance(target, Grunt) and target.is_stunned):
        return None
    if actor_slot is not None and _other_enemy_is_incoming(context, actor_slot, target_slot):
        return _EMERGENCY_ATTACK_PARKED_UNDER_THREAT
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
        ceiling = _stunned_target_ceiling(
            context,
            getattr(verb, "actor_slot", None),
            getattr(verb, "target_slot", None),
        )
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
        # Break the tie *deterministically and stably*, never at random.
        #
        # This used to be random.choice, on the reasoning that verbs scoring
        # identically are equally good so any of them will do. That is true
        # of a single tick in isolation and false of a run of them: the same
        # decision is remade from scratch every poll, so re-rolling a tie
        # each time turns "either is fine" into "swap between them ~15 times
        # a second". Candidates that tie are overwhelmingly the *same verb
        # class aimed at different targets* -- one WalkToNearEnemy per
        # reachable enemy, one Punch per enemy in range, by design (a could_*
        # never pre-selects a best candidate) -- and their targets sit in
        # different directions, so each re-roll re-aims the D-pad. Live
        # symptom: the AI visibly hunting between two enemies instead of
        # committing to either. Scoring was already made near-continuous
        # (_distance_emergency) to make ties rarer, but ties remain routine
        # at the floor of a distance-scored band and at any flat tier, so
        # rarer was never enough on its own.
        #
        # repr is a stable total order over frozen dataclasses -- it depends
        # only on field values, so the same set of candidates yields the same
        # winner on every tick, which is exactly the stickiness this needs.
        # Nothing here has to be *optimal*: reaching this line means the
        # pipeline already judged these candidates equally urgent, so the
        # only property that matters is that the answer stops changing.
        winner = min(tied, key=repr)
        logger.debug(
            "determine_priority_verb: %d verbs tied at emergency=%d "
            "priority=%d (%s); resolved deterministically to %r.",
            len(tied),
            max_emergency,
            max_priority,
            ", ".join(sorted(repr(verb) for verb in tied)),
            winner,
        )

    return {token for token in context if not isinstance(token, Verb)} | {winner}
