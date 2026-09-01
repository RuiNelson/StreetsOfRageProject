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

from ..phases import HITSTUN_FRAMES, CombatPhase, is_dangerous, is_punishable
from . import kinematics, reach
from .decide import (
    HEALTH_CRITICAL_PERCENT,
    in_smash_range,
    POLICE_HEALTH_PERCENT_THRESHOLD,
    POLICE_HEALTH_PERCENT_THRESHOLD_BOSS,
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
    DodgeSoutherSlash,
    FlipHold,
    GrabEnemy,
    HitAntonioBoomerang,
    JumpAttack,
    AttackHeldEnemy,
    MeleeWeaponAttack,
    Punch,
    RearAttack,
    OpenBreakable,
    ReleaseGrab,
    Supplex,
    TechRecover,
    ThrowHeldEnemy,
    ThrowKnife,
    ThrowPepper,
)
from .tokens import Myself, Partner
from .tokens import Antonio, Boss, Breakable, Enemy, Grunt, Jack, Nora, Souther
from .tokens import (
    GrabReason,
    Surrounded,
)
from .tokens import (
    HealthPickup,
    LifePickup,
    Pickup,
    ScorePickup,
    SpecialPickup,
    Weapon,
    is_weapon_type,
)
from .tokens import CameraRange
from .tokens import CallPolice
from .tokens import Projectile
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
# enemy is *about to hit the actor* (`reach.is_incoming_melee` true for a
# different target) while the current one is parked.
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
# Taking a hold (GrabEnemy), one tier per reach.grab_reasons reason present.
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
# A committed charge coming in from behind the body being grabbed -- Signal's
# slide is the case (enemy-ai.md: "velocity, not a hitbox", so nothing to
# sidestep and ~2.5 px/frame to do it in, and it costs a knockdown).
#
# Same tier as being surrounded, and for the same reason: both are situations
# a strike does not answer, where the hold is the escape *and* the damage. It
# therefore also outranks the $322A chord (60) -- the actor is not turning to
# swing at a slide it cannot reach, it is taking a body out of the charge's
# line and suplexing it.
_EMERGENCY_GRAB_TO_DODGE_CHARGE = 61
# Boxed in by a crowd: take a hold rather than trade strikes with it.
#
# The only grab tier that outranks the chord, and deliberately so. Measured on
# the pipeline before this existed, both halves of the user-reported "the AI
# does not deal well when surrounded":
#
# - three enemies in the close box with none strictly *behind* produced no
#   grab reason at all (CLEAR_REAR needs a confirmed rear enemy), so
#   the winning verb was a plain Punch(20) thrown into the crowd;
# - in a real pincer the grab *was* offered, and lost anyway --
#   _EMERGENCY_REAR_ATTACK_DANGEROUS(60) beat _EMERGENCY_GRAB_CLEAR_REAR(58).
#
# That second case is the one worth being precise about, because 60 is not an
# arbitrary number: it is "escape a commit from behind", and walking into a
# committed attack is normally how the actor takes the hit instead of the
# hold. It does not apply here. A grab candidate has already passed
# reach.grab_would_connect *and* GRABBABLE_PHASES, so the body is within contact range and
# is itself not mid-swing -- there is no walk across the room to be punished
# for. And the hold answers the pincer better than the chord does: the chord
# hits one enemy by current position and whiffs if it drifts, while the hold
# removes one body outright and could_hold_actions then throws it *into* the
# rear threat (ThrowHeldEnemy, B+back), which is the "especially if the thrown
# enemy hits other enemies" case.
#
# So: above the chord (60) and above punch-on-punish (60), below
# HitAntonioBoomerang(62) -- an incoming projectile still has to be answered
# first -- and below every hold move (64..70), which cannot coexist anyway
# since could_grab_enemy skips while already holding. Shares 61 with
# ANTONIO_ON_PUNISH, which is coherent rather than a collision: both say
# "the hold is the answer here", and _emergency_grab_enemy takes the max over
# whichever opportunities hold.
_EMERGENCY_GRAB_WHILE_SURROUNDED = 61
# Antonio in hitstun: grab-then-suplex instead of standing still to
# combo him. The boss raise (+14) is applied on top, so this must
# clear punch-on-punish (60+14 = 74): otherwise an injected or stale
# Punch still wins the tick and the hold never starts. Below
# CounterGrab/TechRecover/CallPolice (100/90/88). Hold moves on an
# existing grab (64..70) do not coexist -- could_grab skips while
# holding.
_EMERGENCY_GRAB_ANTONIO_ON_PUNISH = 61
# Souther in hitstun: identical reasoning and identical tier. He has more
# health than Antonio ($20 vs $18 from $17EDC boss_init_combat_stats), so the
# suplex chain is worth more here, and the same "must clear punch-on-punish
# once the boss raise is applied to both" arithmetic applies.
_EMERGENCY_GRAB_SOUTHER_ON_PUNISH = 61
# Taking the hold on a *ready* Antonio, from contact range. Has to clear the
# hop it replaces -- _EMERGENCY_JUMP_ATTACK_ANTONIO_OPENER (22), which is
# raised by the same _EMERGENCY_BOSS_TARGET as this is, so comparing the raw
# tiers is the right comparison -- while staying well below the punish grab
# (61): a hold on a boss who cannot act is still strictly better than one on
# a boss who can. Above _EMERGENCY_GRAB_DEAD_ZONE (30) because this is the
# whole plan against him rather than an improvement on an exchange.
_EMERGENCY_GRAB_ANTONIO_WALK_IN = 35
# Taking the hold on a *ready* Souther, from contact range -- the chase. Same
# tier as Antonio's walk-in and for the same reason: it is the plan against
# him rather than an improvement on an exchange, so it has to clear the
# strike it replaces (_EMERGENCY_PUNCH_DEFAULT, 20, with the same boss raise
# applied to both) while staying well below the punish grab (61), since a
# hold on a boss who cannot act is still strictly better than one on a boss
# who can. Unlike Antonio's, the thing it displaces is a punch rather than a
# hop -- against Souther the hop is refused outright ($16234 counters it) --
# and the punch is not lost: reach.SOUTHER_WALK_IN_STALL_TICKS hands the tick
# straight back to it if the walk-in is not converting.
_EMERGENCY_GRAB_SOUTHER_WALK_IN = 35
_EMERGENCY_HOLD_THROW = 70  # throw held body into rear threat
_EMERGENCY_HOLD_SUPPLEX = 68
_EMERGENCY_HOLD_FLIP = 66
# A fresh knee must clear FlipHold's fixed 66 -- see
# _emergency_attack_held_enemy -- so "milk the hold" wins the front-hold
# choice while young, and the moment the hold outlasts
# kinematics.hold_knee_budget_frames this reverts to _EMERGENCY_DEFAULT and
# FlipHold's constant tier finishes it.
#
# Never competes with Supplex(68): that only ever appears on a *back* hold,
# which is a different branch of decide.could_hold_actions. It **can** now
# meet Throw(70), which wins -- and that ordering is the point rather than an
# accident: the throw is only offered from a front hold when there is a rear
# threat to throw into, or when something is landing too soon for a knee to
# finish (decide.could_hold_actions, on kinematics' measured frame counts).
_EMERGENCY_HOLD_KNEE_FRESH = 67
_EMERGENCY_HOLD_RELEASE = 50
# The knee budget moved to frames and to kinematics.py -- see
# ``kinematics.hold_knee_budget_frames``. It was six *ticks*, which is not a
# unit the game has: at ~2 frames a tick that is 12 frames against a knee's
# measured 17-18, so the budget expired before the first knee could finish
# and the flip won the very next tick. The replacement is three knees' worth
# of frames, compared against ``kinematics.frames_for_ticks(hold_ticks)``.
#
# Still not a ROM-confirmed escape timer -- none is decoded (enemy-ai.md's
# later-boss grabbee states $06-$09 name no such counter) -- so how *many*
# knees stays a judgment. How long a knee takes no longer is.
_EMERGENCY_JUMP_ATTACK_PUNISHABLE = 28  # below punch; never prefer hop over strike
# Hop on a live Antonio. Must clear _EMERGENCY_PUNCH_DEFAULT (20) so the
# opener is the jump-kick even if a Punch is still in context: standing
# still to throw that punch is $16EAE's zero-velocity kick trigger.
# Below the committed jump-over (56) and the grounded dodge (58).
_EMERGENCY_JUMP_ATTACK_ANTONIO_OPENER = 22
# Nora specifically, freshly out of her own whip engage-and-swing or lunge
# (Nora.ticks_since_last_attack -- observe.NoraAttackTracker) but not (yet)
# re-armed and not in any ROM-confirmed is_punishable phase, so this sits
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
# below a guaranteed strike on a punishable target (60) and the RearAttack/
# CLEAR_REAR grab escapes (55/58/60): those stay the right answer even with
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
# Step off the lane of Souther's committed claw dash. Deliberately *not* at the
# Antonio dodge's 58: that tier had to beat the strike-on-a-live-boss because
# standing still is what arms Antonio's kick, whereas Souther's own commit gate
# narrows when the actor stands still ($58) and widens when it walks in ($68),
# so there is nothing here to out-rank a punch for. What this does have to beat
# is every approach/retreat tier and ProjectileSidestep's ceiling (45), so the
# claw is answered before an unrelated throw. Below the real escapes
# (RearAttack 55/60, the punish grab 61) and below
# CounterGrab/TechRecover/CallPolice.
_EMERGENCY_DODGE_SOUTHER_SLASH = 46
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
    """Mirrors ``decide._police_is_worth_it``'s three reasons, same tiers.

    A live ``Boss`` scores the *same* top tier as "about to die"
    (``_EMERGENCY_CALL_POLICE``, 88), not a lesser one: ``$16A60``'s flat
    -10 HP is worth roughly a third of a later-boss's whole health bar in
    one press, which is an order of magnitude better than the special's
    ordinary value against a street enemy and easily worth outranking a
    combo in progress once it applies at all (``decide._police_is_worth_it``
    already keeps it from firing outside the boss's own laxer health gate).
    """

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
    if (
        any(not boss.is_defeated for boss in find_all(context, Boss))
        and actor.health_percent < POLICE_HEALTH_PERCENT_THRESHOLD_BOSS
    ):
        return _EMERGENCY_CALL_POLICE
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


def _emergency_melee_strike(verb: Verb, context: Context) -> int:
    """Shared scoring for ``Punch`` / ``MeleeWeaponAttack`` -- same formula
    regardless of held weapon, since none of these has evidence of a
    different punishable-phase payoff."""

    target = find(context, Enemy, slot=getattr(verb, "target_slot", None))
    if target is None:
        return _EMERGENCY_DEFAULT
    if is_punishable(target.combat_phase):
        return _with_target_class(_EMERGENCY_PUNCH_PUNISHABLE, target)
    return _with_target_class(_EMERGENCY_PUNCH_DEFAULT, target)


def _emergency_jump_attack(verb: JumpAttack, context: Context) -> int:
    target = find(context, Enemy, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if target is None:
        return _EMERGENCY_DEFAULT
    if isinstance(target, Antonio):
        if (
            target.strike_is_committed()
            and actor is not None
            and reach.antonio_will_kick(target, actor)
        ):
            return _with_target_class(_EMERGENCY_JUMP_OVER_ANTONIO_KICK, target)
        if not is_punishable(target.combat_phase):
            return _with_target_class(_EMERGENCY_JUMP_ATTACK_ANTONIO_OPENER, target)
    if is_punishable(target.combat_phase):
        return _with_target_class(_EMERGENCY_JUMP_ATTACK_PUNISHABLE, target)
    if (
        isinstance(target, Nora)
        and not is_dangerous(target.combat_phase)
        and target.ticks_since_last_attack <= NORA_RECOVERY_PUNISH_TICKS
    ):
        return _with_target_class(_EMERGENCY_JUMP_ATTACK_NORA_RECOVERY, target)
    return _with_target_class(_EMERGENCY_JUMP_ATTACK_DEFAULT, target)


# Stepping out of a kick gate that has not fired yet. Must clear the hop it
# replaces (_EMERGENCY_JUMP_ATTACK_ANTONIO_OPENER 22 plus the boss raise's 14
# = 36) and stay under the walk-in hold (_EMERGENCY_GRAB_ANTONIO_WALK_IN 35 +
# 14 = 49): with the hold available the hold is the better answer, since a
# held Antonio cannot kick at all, and only out of its range is leaving the
# lane the best thing on the table.
_EMERGENCY_BREAK_ANTONIO_KICK_LANE = 42


def _emergency_dodge_antonio_kick(verb: DodgeAntonioKick, context: Context) -> int:
    target = find(context, Antonio, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if target is not None and actor is not None and reach.antonio_will_kick(target, actor):
        if not verb.committed:
            return _EMERGENCY_BREAK_ANTONIO_KICK_LANE
        return _EMERGENCY_DODGE_ANTONIO_KICK
    return _EMERGENCY_DEFAULT


def _emergency_dodge_souther_slash(verb: DodgeSoutherSlash, context: Context) -> int:
    target = find(context, Souther, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if target is not None and actor is not None and reach.souther_will_slash(target, actor):
        return _EMERGENCY_DODGE_SOUTHER_SLASH
    return _EMERGENCY_DEFAULT


def _emergency_hit_antonio_boomerang(verb: HitAntonioBoomerang, context: Context) -> int:
    projectile = find(context, Projectile, slot=verb.target_slot)
    if projectile is None:
        return _EMERGENCY_DEFAULT
    return _EMERGENCY_HIT_ANTONIO_BOOMERANG


# Score per GrabReason, looked up by _emergency_grab_enemy. See the
# _EMERGENCY_GRAB_* constants above for why each tier is where it is.
_GRAB_REASON_SCORE: dict[GrabReason, int] = {
    GrabReason.CLEAR_REAR: _EMERGENCY_GRAB_CLEAR_REAR,
    GrabReason.JACK_FROM_BEHIND: _EMERGENCY_GRAB_JACK_FROM_BEHIND,
    GrabReason.DEAD_ZONE: _EMERGENCY_GRAB_DEAD_ZONE,
    GrabReason.ANTONIO_ON_PUNISH: _EMERGENCY_GRAB_ANTONIO_ON_PUNISH,
    GrabReason.ANTONIO_WALK_IN: _EMERGENCY_GRAB_ANTONIO_WALK_IN,
    GrabReason.SOUTHER_ON_PUNISH: _EMERGENCY_GRAB_SOUTHER_ON_PUNISH,
    GrabReason.SOUTHER_WALK_IN: _EMERGENCY_GRAB_SOUTHER_WALK_IN,
    GrabReason.WHILE_SURROUNDED: _EMERGENCY_GRAB_WHILE_SURROUNDED,
    GrabReason.DODGE_CHARGE: _EMERGENCY_GRAB_TO_DODGE_CHARGE,
}


def _emergency_grab_enemy(verb: GrabEnemy, context: Context) -> int:
    """The best tier among the ``reach.grab_reasons`` for this pair.

    Several reasons can hold at once (a whip enemy in front *and* a body at
    the actor's back); the strongest reason is what the grab is worth. No
    reason left this tick -- the rear enemy moved off, the target stopped
    being grabbable -- means there is no longer a reason to close in, so the
    walk-in drops out of contention entirely.
    """

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Enemy, slot=verb.target_slot)
    if actor is None or target is None:
        return _EMERGENCY_DEFAULT

    reasons = reach.grab_reasons(context, actor, target, reach.on_screen_enemies(context))
    if not reasons:
        return _EMERGENCY_DEFAULT

    score = max(_GRAB_REASON_SCORE[reason] for reason in reasons)
    return _with_target_class(score, target)



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
    weapon = find(context, Weapon, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    camera = find(context, CameraRange)
    rank = None if weapon is None or actor is None else reach.weapon_upgrade_rank(actor, weapon, camera)
    if rank is None:
        # No upgrade judgment for this pair this tick: the weapon is gone,
        # out of camera, worn out, or no longer better than what is held.
        return _EMERGENCY_DEFAULT
    # Scales with how much of an upgrade this weapon is (rank 2..5) instead
    # of a flat weight, so a better upgrade among several candidates ranks
    # higher -- e.g. knife (rank 5) reaches 17, pepper (rank 2) sits lower at
    # 14. Every rank clears WalkToNearEnemy's floor (8) outright, and stays
    # below the weakest real attack tier (_EMERGENCY_JUMP_ATTACK_DEFAULT, 18)
    # so it never crosses into a different verb type's tier.
    #
    # ...unless a boss kick already covers the actor, in which case the whole
    # detour is refused -- see _boss_attack_gate_is_live.
    if _boss_attack_gate_is_live(context, verb.actor_slot):
        return _EMERGENCY_DEFAULT
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
    if not reach.is_incoming_melee(actor, target):
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
    """Sooner-to-impact scores higher, using the same
    ``reach.projectile_ticks_to_impact`` ``decide.could_projectile_sidestep``
    used to judge this a threat in the first place -- reusing
    ``_distance_emergency`` with a tick count standing in for its usual pixel
    distance, since both are "how much runway is left before this needs to
    be answered"."""

    projectile = find(context, Projectile, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if projectile is None or actor is None:
        return _EMERGENCY_DEFAULT
    ticks = reach.projectile_ticks_to_impact(projectile, actor)
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


def _boss_attack_gate_is_live(context: Context, actor_slot: str | None) -> bool:
    """True while a live Antonio's own kick gate already covers the actor.

    An item detour is a walk that ignores the boss, and ``$16EAE`` punishes
    exactly that: the X window it kicks from is picked by the *target's* own
    velocity (up to 120px while closing, 104px standing still) with a 16px
    lane window, and the hit is 20 damage -- a quarter of the health bar, for
    an apple. Measured over three round-1 fights, four of the eight hits
    Antonio landed came while the winning verb was ``WalkToPickup`` or
    ``WalkToWeapon``; a pipe is worth even less than the apple, since
    ``decide._could_melee_strike`` refuses every grounded B on him, so an
    armed actor has no ground attack against him at all.

    Antonio only, deliberately: Souther's fight has its own measured balance
    (see ``autoplay/CLAUDE.md``) and giving him the same gate is untested.
    """

    actor = _find_actor(context, actor_slot)
    if actor is None:
        return False
    return any(
        not antonio.is_defeated and reach.antonio_will_kick(antonio, actor)
        for antonio in find_all(context, Antonio)
    )


def _emergency_walk_to_pickup(verb: WalkToPickup, context: Context) -> int:
    pickup = find(context, Pickup, slot=verb.target_slot)
    actor = _find_actor(context, verb.actor_slot)
    if (
        not isinstance(pickup, HealthPickup)
        and _boss_attack_gate_is_live(context, verb.actor_slot)
    ):
        # Health used to be exempt here as "the one thing worth a kick".
        # It no longer needs the exemption: against Antonio the food is not
        # taken at all (decide._food_is_spoken_for), so no HealthPickup verb
        # reaches this function during his fight. The isinstance check stays
        # for every other boss, where the exemption still means what it said.
        return _EMERGENCY_DEFAULT
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


def _emergency_attack_held_enemy(verb: AttackHeldEnemy, context: Context) -> int:
    """The knee: full tier while the hold is young, otherwise stand down.

    ``_EMERGENCY_HOLD_KNEE_FRESH`` (67) beats ``FlipHold``'s fixed 66 for as
    long as the hold has run less than ``kinematics.hold_knee_budget_frames``,
    milking a few knees
    before the flip->suplex finish is allowed to win -- see
    ``observe.HoldTracker`` for why this is tick-based rather than reading a
    ROM escape counter (none is decoded). Once the hold ages past that, this
    drops to ``_EMERGENCY_DEFAULT`` so ``FlipHold``'s own constant score
    finishes it, the same as it always did before this existed.

    ``hold_ticks`` is converted to frames before the comparison rather than
    the budget being converted to ticks: everything about a move's length in
    this codebase lives in frames (``kinematics``'s own docstring), and the
    poll period is a knob the user can move while a knee is 17 frames
    whatever the AI is doing.
    """

    if not _target_is_in_hand(verb, context):
        return _EMERGENCY_DEFAULT
    actor = _find_actor(context, verb.actor_slot)
    if actor is not None and kinematics.frames_for_ticks(
        actor.hold_ticks
    ) > kinematics.hold_knee_budget_frames(actor.character_id):
        return _EMERGENCY_DEFAULT
    return _EMERGENCY_HOLD_KNEE_FRESH


def _target_is_in_hand(verb: Verb, context: Context) -> bool:
    """Whether this hold move's target really is the body in the actor's hands.

    ``CombatPhase.GRABBED`` answers it for an ordinary enemy (``$0500``) and
    for a later boss only during the ``$06``-``$09`` throw cleanup. It is
    **not** enough on its own: measured live, an Antonio held in a front hold
    sits in primary ``$04`` -- decoded ``RECOVERY``, the same byte as his
    ordinary hit reaction -- so every hold move scored ``_EMERGENCY_DEFAULT``,
    lost the tick to the walk-in that had already succeeded, and the AI stood
    there holding him until the stage timer ran out. ``reach.held_enemy``
    covers that case from the ROM's own ``+$4C`` hold link.
    """

    target = find(context, Enemy, slot=getattr(verb, "target_slot", None))
    if target is None:
        return False
    if target.combat_phase is CombatPhase.GRABBED:
        return True
    actor = _find_actor(context, getattr(verb, "actor_slot", None))
    if actor is None:
        return False
    in_hand = reach.held_enemy(actor, reach.live_enemies(context))
    return in_hand is not None and in_hand.slot == target.slot


def _held_enemy_emergency(weight: int) -> Callable[[Verb, Context], int]:
    """Build an ``_emergency_*`` for a hold move: ``weight`` only while its
    target ``Enemy`` really is the body in the actor's hands
    (``_target_is_in_hand``)."""

    def _emergency(verb: Verb, context: Context) -> int:
        return weight if _target_is_in_hand(verb, context) else _EMERGENCY_DEFAULT

    return _emergency


_EMERGENCY_FUNCS: dict[type[Verb], Callable[[Verb, Context], int]] = {
    HandleContinueMenu: _emergency_handle_continue_menu,
    HandleMrXDialog: _emergency_handle_mr_x_dialog,
    CounterGrab: _emergency_counter_grab,
    TechRecover: _emergency_tech_recover,
    CallPolice: _emergency_call_police,
    RearAttack: _emergency_rear_attack,
    Punch: _emergency_melee_strike,
    MeleeWeaponAttack: _emergency_melee_strike,
    OpenBreakable: _emergency_open_breakable,
    GrabEnemy: _emergency_grab_enemy,
    ThrowHeldEnemy: _held_enemy_emergency(_EMERGENCY_HOLD_THROW),
    Supplex: _held_enemy_emergency(_EMERGENCY_HOLD_SUPPLEX),
    FlipHold: _held_enemy_emergency(_EMERGENCY_HOLD_FLIP),
    AttackHeldEnemy: _emergency_attack_held_enemy,
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
    DodgeSoutherSlash: _emergency_dodge_souther_slash,
    HitAntonioBoomerang: _emergency_hit_antonio_boomerang,
    WalkToAdvanceStage: _emergency_walk_to_advance_stage,
}


def _other_enemy_is_incoming(context: Context, actor_slot: str, target_slot: str) -> bool:
    """Is something *other than* this target about to hit the actor?

    Reads ``reach.is_incoming_melee``, the same shared judgment
    ``decide.py`` uses, so "about to hit me" has one definition across the
    pipeline.
    """

    actor = _find_actor(context, actor_slot)
    if actor is None:
        return False
    return any(
        enemy.slot != target_slot and reach.is_incoming_melee(actor, enemy)
        for enemy in reach.on_screen_enemies(context)
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

    A **knockdown** keeps its full tier while nothing is about to hit the
    actor: that window ends in a wake-up with invulnerability, so unlike a
    stun it really does have to be used now. Under an incoming attack it is
    capped like a stun anyway, and for a sharper version of the same reason --
    a body on the floor that is *about to become invulnerable* is the worst
    thing on screen to trade a hit for. Live-reported against Souther ("ataca
    o outro inimigo"): with his claw committed two steps away, punching a
    knocked-down grunt scored 60 against the dodge's 46 and won the tick.

    The remaining time decides which ceiling, read straight from the
    stunned Grunt's own ``stun_timer`` (+$50). Above ``HITSTUN_FRAMES`` the
    timer either belongs to the long pepper-spray stun or to Nora's own
    "feign injury" recovery (``phases.py``'s ``0x26`` table, state ``$0C``
    seeds ``$80`` -- 128 frames), and both only count down. A pepper stun
    that *has* counted down into hitstun range is about to end, which is
    exactly when treating it as a combo window is right again.
    """

    if target_slot is None:
        return None
    target = find(context, Enemy, slot=target_slot)
    if not isinstance(target, Grunt):
        return None
    parked = target.is_stunned or target.combat_phase is CombatPhase.KNOCKDOWN
    if not parked:
        return None
    if actor_slot is not None and _other_enemy_is_incoming(context, actor_slot, target_slot):
        return _EMERGENCY_ATTACK_PARKED_UNDER_THREAT
    if not target.is_stunned:
        # A knockdown with nothing incoming: no ceiling at all, exactly as
        # before. Only the branch above is new for it.
        return None
    frames_left = target.stun_timer
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
