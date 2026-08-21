"""Geometry and target-filtering shared by the whole AI pipeline.

These predicates used to be private helpers inside ``decide.py``, recomputed
independently by ``priority.py`` (through cross-module imports of those
privates) and deliberately *duplicated* by ``inference.py``, which must not
import ``decide``. Keeping them here gives every stage one definition to
agree on: ``decide.py``/``priority.py``/``execute.py`` call the same
functions directly, each tick, rather than reading a value pre-computed
into a token -- the single shared definition is what keeps them from
disagreeing, not a cache.

Nothing in this module reads RAM or produces tokens -- it only answers
questions about tokens already in the context.

Every predicate here is about *this instant*. When a caller needs "will this
still be true when my move actually lands", it projects the enemy first
(``kinematics.py`` owns the lead times and ``enemy_projected``, re-exported
below) and asks the same question at that future position -- the geometry is
not duplicated for the predictive case.
"""

from __future__ import annotations

import math

from ..phases import CombatPhase, is_dangerous, is_punishable, should_ignore_as_target
from ..world_map import LANE_Y_MAX_DEFAULT, LANE_Y_MIN, lane_y_max_for_level
from .kinematics import enemy_projected, enemy_projected_without_crossing
from .tokens import (
    Antonio,
    BODY_OVERLAP_X,
    CameraRange,
    Context,
    Enemy,
    GrabReason,
    Grunt,
    Jack,
    PlayableCharacter,
    Pit,
    Projectile,
    PUNCH_RANGE_Y,
    Souther,
    Stage,
    Surrounded,
    Weapon,
    find,
    find_all,
    punch_inner_x,
    punch_usable_inner_x,
    punch_outer_x,
    rear_attack_behind_max_x,
    rear_attack_behind_min_x,
    rear_attack_front_max_x,
    weapon_rank,
)

# Slack for an enemy that reads as nominally "behind" while standing
# essentially on top of the actor. The *grab* keeps it: its contact test
# ($AAA0) reads a walking frame's box, which starts at the actor's own origin,
# so a body a few px the wrong side genuinely can still touch it.
GRAB_BEHIND_TOLERANCE_X = 4


def punch_behind_tolerance_x(character_id: int | None) -> int:
    """How far *behind* the actor a forward strike can still reach a body.

    Derived, not chosen: the punch box starts at ``punch_inner_x`` px **in
    front** (8 for Adam, 16 Axel, 18 Blaze) and a body reaches about
    ``BODY_OVERLAP_X`` past its own centre, so a body centred behind the
    actor would have to span the whole dead zone to touch the box. It cannot,
    for any of the three characters -- this evaluates to 0 for all of them
    today, and would only become non-zero for a character whose box began
    inside its own body.

    It used to be a flat 4px of slack, and that flat number was a real,
    measured failure: Adam jump-kicks past an enemy, lands 4px beyond it, and
    then stands there punching *forward* into empty air for as long as the
    enemy stays put -- the strike is aimed the way he faces, and the enemy is
    behind him. Refusing it hands the tick to ``could_walk_to_near_enemy``,
    whose turn-around aims past the enemy, flips facing, and lets the very
    next tick punch it properly.
    """

    return max(0, BODY_OVERLAP_X - punch_inner_x(character_id))

# Taking a hold of an enemy is not an input at all -- it is a *contact*
# result. ``$AAA0`` (the shared contact routine) tests the actor's own attack
# box (+$64) against the enemy's body box and reports code 3, the grab code,
# only when the actor's outgoing damage ``+$34`` is **zero** (a walking frame,
# never a strike's active frames, which report the damage code 2 instead), the
# actor is not already holding anything (``+$4C == 0``) and the two are within
# 8px of elevation. ``$3266`` then converts that code into a hold before any
# button is even read -- front hold ``$60`` when the two face each other, back
# hold ``$66`` (one B away from a suplex) when the actor is behind the enemy
# facing the same way. So the AI grabs by *walking into* an enemy without
# attacking, which is why this band is not a hitbox measurement: it is how far
# out the walk-in is still worth committing to. It reuses the actor's own
# unarmed punch outer edge -- the distance the rest of the pipeline already
# treats as close-combat range for that character -- with a lane tolerance
# tighter than a punch's, since two bodies have to actually overlap.
GRAB_RANGE_Y = 10

# Jump-kick is a *horizontal* attack — never a stationary hop.
JUMP_ATTACK_MIN_DX = 28  # must leave punch outer / need air travel
# Early-kick free-flight range per character_id (controls-and-input.md
# "Closed-form trajectory summary"): 60/69/75 px -- Axel's real reach is well
# short of Blaze's, so a flat cap either strands Axel mid-air or under-uses
# Blaze's longer kick.
JUMP_ATTACK_MAX_DX_BY_CHARACTER: dict[int, int] = {0: 60, 1: 69, 2: 75}  # Axel, Adam, Blaze
JUMP_ATTACK_MAX_DX_DEFAULT = 72
JUMP_ATTACK_RANGE_Y = 14

# Box around the actor inside which another enemy counts as "the other side is
# covered too" for RearAttack -- i.e. close enough to land a free hit while the
# actor spends frames turning around. A *hitting* distance, which is why it is
# the chord's own reach.
REAR_THREAT_X = 56
REAR_THREAT_Y = 24

# How close an enemy has to be to count as part of *this fight* -- the box
# ``inference.check_for_surrounded`` judges encirclement with.
#
# Deliberately no longer REAR_THREAT_X/Y. Those describe "can it hit me from
# there", and reusing them for "am I boxed in" made the judgment far too tight
# to survive the actor's own movement: traced on the tick harness, an actor
# with three enemies around it walked **12 px** toward one of them, the third
# fell out of the 56px box, the crowd count dropped 3 -> 2 with both survivors
# on one side, and ``Surrounded`` vanished. Everything keyed on it vanished
# with it -- including the grab opportunity the actor was in the middle of
# walking in to take, which is why a crowd read as "the AI starts a grab and
# then just punches" from the sofa.
#
# X is anchored to the distance the AI itself already treats as "still worth
# walking to": ``priority._emergency_walk_to_near_enemy`` scores an enemy down
# from 14 to its floor of 8 one point per 15 px, so it saturates at 90 px --
# inside that, the pipeline considers an enemy part of the current engagement.
# 96 is just past it, and comfortably more than one exchange's worth of the
# actor's own walking, so stepping toward one enemy cannot delete another.
#
# Lane is the approach's own sidestep expressed the same way execute.py's
# WALK_TO_ENEMY_LANE_SAFETY_Y is (PUNCH_RANGE_Y + 16 = 28): an enemy still
# within roughly that of the actor's lane has *not* been left behind, so it is
# still part of the fight. Kept here rather than imported, since inference.py
# must not depend on the executor.
SURROUNDED_NEAR_X = 96
SURROUNDED_NEAR_Y = PUNCH_RANGE_Y + 20  # 32

# Extra px beyond punch_outer_x where a still-approaching dangerous enemy
# switches from "keep walking closer" to "back off instead" (see
# could_retreat_from_danger) -- approximate on purpose: this is a caution
# buffer, not a hitbox measurement.
RETREAT_CAUTION_MARGIN = 24
# The caution zone is a box, not an X-only band. Attacks in this game only
# connect within roughly a lane of each other (PUNCH_RANGE_Y), so a committed
# enemy several lanes away is not a reason to back off -- and treating it as
# one made the AI refuse to approach *and* walk backwards from a threat it
# was never in line with. Kept below execute.WALK_TO_ENEMY_LANE_SAFETY_Y
# (PUNCH_RANGE_Y + 16) so the sidestep that verb's executor performs
# actually leaves this zone instead of retreating from its own dodge.
RETREAT_CAUTION_MARGIN_Y = PUNCH_RANGE_Y + 12

# Hysteresis band on top of the caution zone, for the *approach* half of the
# decision only (decide.could_walk_to_near_enemy).
#
# Retreating and approaching used to switch on the exact same boundary --
# too_close_to_keep_approaching -- with nothing between them. That is a
# textbook limit cycle, and it reproduced immediately when the pipeline was
# driven over synthetic ticks against a single ATTACKING enemy: one retreat
# step (RETREAT_FROM_DANGER_DISTANCE) carries the actor a few px past the
# boundary, which flips is_incoming_melee false, which un-skips
# could_walk_to_near_enemy, which walks straight back in and re-arms the
# threat on the very next tick. The observed period was *one tick* -- a
# LEFT/RIGHT alternation at the full poll rate, plus a slow lane drift from
# the walk verb's own sidestep, exactly the "changes direction very often,
# in jumps and up/down, with a single enemy, not during the attack" the user
# reported.
#
# So the approach must not resume the instant the retreat trigger clears: it
# stays suppressed until the actor is this much *beyond* the caution zone.
# Between the two thresholds the actor simply holds its ground rather than
# oscillating -- the right answer against a committed attacker anyway, and it
# lifts by itself the moment the enemy leaves its dangerous phase, since the
# suppression is gated on that phase and not on distance alone.
#
# Sized well above what either body covers in a single tick (the actor walks
# a few px per 33ms poll; the fastest committed closer measured, Signal's
# slide, is ~2.5px/frame) so neither can traverse the whole band in one
# sample and re-arm the cycle -- but kept small enough that the actor still
# closes to punch range promptly once the threat passes.
APPROACH_RELEASE_MARGIN = 16

# Clearance kept beyond a Pit's own footprint — falling in costs a full life
# (player-health-lives-and-combat.md's $01C0 fall-boundary check).
PIT_AVOID_MARGIN = 8


def pit_endangers(pit: Pit, world_x: int, world_y: int, *, margin: int = PIT_AVOID_MARGIN) -> bool:
    """True when ``(world_x, world_y)`` sits inside ``pit``'s footprint plus
    ``margin`` -- close enough that a fall is a real risk, not just nearby.

    The one definition of "standing in a pit's danger zone", shared by
    ``inference.check_for_safe_spots`` (reject a retreat candidate here) and
    ``execute._pit_escape_mask`` (the actor's own current position).
    """

    return (
        pit.world_x - margin <= world_x <= pit.world_x + pit.width + margin
        and pit.lane_y - margin <= world_y <= pit.lane_y + pit.height + margin
    )


def any_pit_endangers(context: Context, world_x: int, world_y: int) -> bool:
    """True when ``(world_x, world_y)`` sits in the danger zone of *any*
    ``Pit`` in ``context``.

    The shared "is this even a destination worth aiming at" check for every
    ``could_walk_to_*`` generator: a target sitting on a pit -- an enemy the
    game lured there, a pickup or weapon spawned on top of one -- is not
    reachable at all without standing in the danger zone first, so nothing
    should ever produce a walk toward it in the first place. Live-diagnosed:
    without this, a walk verb aimed squarely at a pit-adjacent target left
    the actor endlessly re-approaching the one point ``execute._pit_escape_
    mask`` had just pushed it away from, reading as the actor turning left
    then right in place at the pit's own edge.
    """

    return any(pit_endangers(pit, world_x, world_y) for pit in find_all(context, Pit))


# Slack added to an enemy's *extracted* reach before treating the actor as
# standing inside it. The reach itself is exact -- it is the ROM's own shape
# record -- but the sample is not: at the 33ms default poll an enemy covers a
# few pixels between two observations, and it may also step forward during its
# own startup frames. Half a tile absorbs both without pretending the box is
# bigger than it is.
REACH_SAFETY_MARGIN = 8

# Souther's state 1 -> state 2 commit gate at $15EDA
# (souther_state1_active_combat) has an inner abort (`cmpi.w #$0018,d2 / bcs`):
# he cannot *begin* the slash from inside 24px and has to walk back out first.
# Shared with execute.py (the approach's own stop point, ``_souther_pocket_
# stop_dx``) and inference.py (the fuller commit-gate geometry, ``check_for_
# souther_slash``) -- lives here rather than in either, per this module's own
# charter as the one shared definition, the same reason ``REACH_SAFETY_MARGIN``
# above does. Not a safe pocket once he is *already* committed: $161C6
# (souther_state2_claw_dash) resolves an already-in-progress dash at
# +$50 in [$18,$40), the same band -- this constant only denies the state-1
# start, so a caller must gate on ``Souther.strike_is_committed()`` too.
SOUTHER_SLASH_DIST_MIN = 0x18  # 24px

# How far ahead a Grunt's own committed velocity (grunt_vel_x/grunt_vel_y) is
# trusted to extrapolate -- shared between inference.check_for_closing_enemies
# (the rear-band early warning) and check_for_incoming_melee's predictive
# extension below, so "soon" means the same thing to both. ~200ms: one missed
# poll plus margin for the slowest measured RearAttack startup (Adam, 21
# frames).
#
# In **60 Hz frames**, which is the unit those velocity fields are actually
# in -- the ROM integrates them once per frame ($17AB8, see
# Enemy.predict_position_after_n_frames). This constant used to be a count of
# AI poll *ticks* multiplied straight into a per-frame velocity, which
# projected only half the distance its own "~200ms" docstring described,
# since a tick is ~2 frames at the 33ms default poll.
#
# Not every closing enemy has a reach box to test against: enemy-ai.md's
# "Signal's slide is velocity, not a hitbox" documents a real ROM case
# (Signal state $0A) that sets +$1C/+$20 directly with no attack shape at
# all -- the danger *is* the velocity, tested here by the enemy's own body
# reaching the caution zone, not by anything in attack_ranges.py.
CLOSING_ENEMY_THREAT_FRAMES = 12


def jump_attack_max_dx(character_id: int | None) -> int:
    if character_id is None:
        return JUMP_ATTACK_MAX_DX_DEFAULT
    return JUMP_ATTACK_MAX_DX_BY_CHARACTER.get(character_id, JUMP_ATTACK_MAX_DX_DEFAULT)


def enemy_behind_actor(actor: PlayableCharacter, enemy: Enemy) -> bool:
    if actor.facing_left:
        return enemy.world_x > actor.world_x
    return enemy.world_x < actor.world_x


def enemy_in_front(actor: PlayableCharacter, enemy: Enemy) -> bool:
    return not enemy_behind_actor(actor, enemy)


def in_camera(camera: CameraRange, world_x: int, world_y: int) -> bool:
    return camera.left <= world_x <= camera.right and camera.top <= world_y <= camera.bottom


def in_playable_lane(world_y: int, context: Context) -> bool:
    """False for an enemy positioned outside the level's actual walkable Y
    band -- e.g. stage 1's scripted "behind a door" placeholder, which is a
    real Enemy object (tracked, health, combat_phase) at an anomalously high
    world_y the player can never physically reach. Without this filter the
    AI repeatedly commits to attacks/chases against a target it can never
    connect with, and it can also block could_walk_to_advance_stage
    forever the same way an abandoned 0-HP straggler does."""

    stage = find(context, Stage)
    lane_max = lane_y_max_for_level(stage.level_index) if stage is not None else LANE_Y_MAX_DEFAULT
    return LANE_Y_MIN <= world_y <= lane_max


def live_enemies(context: Context) -> list[Enemy]:
    """Every enemy still worth acting on.

    Three independent ways to stop being one, and all three are needed:

    - ``should_ignore_as_target`` -- the phase says so (DEATH, or a SCRIPTED
      sequence like the police-special sweep);
    - ``Enemy.is_defeated`` -- the *health word* says so, which the phase can
      lag behind by a long time: the ROM's lethal check is signed, so
      ``$8000``-``$FFFF`` is already dead while the object sits there with a
      stale action family. Without this the AI chases, ranks and punches
      corpses, and blocks its own stage advance behind them;
    - ``in_playable_lane`` -- it is somewhere the player can never reach
      (stage 1's scripted "behind a door" placeholder is a real, tracked
      Enemy at an unreachable lane).
    """

    return [
        e
        for e in find_all(context, Enemy)
        if not should_ignore_as_target(e.combat_phase)
        and not e.is_defeated
        and in_playable_lane(e.world_y, context)
    ]


# How far apart the two bodies of a live hold sit. Not a band the AI aims
# with -- the hold already happened -- only the fallback identity test for
# "which of these enemies is the one in my hands", used when the ROM's own
# +$4C link (PlayableCharacter.held_enemy_slot) did not resolve. Measured
# live on Antonio: 40px on X with the actor in front hold $60, 32px the
# other way after the C crossover into back hold $66, both at lane 0.
HELD_CONTACT_X = 48
HELD_CONTACT_Y = 12


def in_held_contact(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """Whether ``enemy`` is close enough to be the body ``actor`` is holding.

    Deliberately not directional, unlike ``grab_would_connect``: a crossover
    (front hold ``$60`` --C--> back hold ``$66``) teleports the actor to the
    enemy's other side, so the held body is on whichever side the animation
    left it.
    """

    return (
        abs(enemy.world_x - actor.world_x) <= HELD_CONTACT_X
        and abs(enemy.world_y - actor.world_y) <= HELD_CONTACT_Y
    )


def held_enemy(actor: PlayableCharacter, enemies: list[Enemy]) -> Enemy | None:
    """The enemy in ``actor``'s hands right now, or ``None``.

    Three sources, most authoritative first:

    1. ``actor.held_enemy_slot`` -- the ROM's own hold link at ``+$4C``
       (``$3266`` writes it, ``$AAA0`` refuses a fresh grab while it is set).
    2. an enemy whose own phase already decodes ``GRABBED`` -- true for
       ordinary enemies (``$0500``) and for a later boss only in its
       ``$06``-``$09`` throw-cleanup states.
    3. the nearest enemy still in ``in_held_contact``.

    (2) and (3) exist because a *held later boss* announces nothing: measured
    live, a held Antonio sits in primary ``$04``, which is also his ordinary
    hit reaction, and the player's ``+$60`` keeps reading either ``$00`` or
    the weapon the actor is still carrying. Without this the whole hold
    family scored ``_EMERGENCY_DEFAULT`` and the AI stood in a live front
    hold on him for an entire round-1 fight.
    """

    if not actor.is_holding_enemy:
        return None
    if actor.held_enemy_slot is not None:
        for enemy in enemies:
            if enemy.slot == actor.held_enemy_slot:
                return enemy
    def _distance(enemy: Enemy) -> float:
        return math.hypot(enemy.world_x - actor.world_x, enemy.world_y - actor.world_y)

    grabbed = [e for e in enemies if e.combat_phase is CombatPhase.GRABBED]
    if grabbed:
        return min(grabbed, key=_distance)
    contact = [e for e in enemies if in_held_contact(actor, e)]
    if contact:
        return min(contact, key=_distance)
    return None


def on_screen_enemies(context: Context) -> list[Enemy]:
    camera = find(context, CameraRange)
    enemies = live_enemies(context)
    if camera is None:
        return enemies
    return [e for e in enemies if in_camera(camera, e.world_x, e.world_y)]


def in_punch_band(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """Raw distance box only -- ignores facing. Callers that want "a strike
    would actually connect" want :func:`punch_would_connect` instead."""

    dx = abs(enemy.world_x - actor.world_x)
    dy = abs(enemy.world_y - actor.world_y)
    if dy > PUNCH_RANGE_Y:
        return False
    outer = punch_outer_x(actor.character_id, actor.held_weapon_type)
    # The *usable* inner edge: a body centred just inside the box's own edge
    # still overlaps it, and treating it as unhittable had the AI dithering
    # in punching range (see tokens/character.py's BODY_OVERLAP_X).
    return punch_usable_inner_x(actor.character_id) <= dx <= outer


def punch_would_connect(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """``in_punch_band`` *and* the enemy is actually in front (within the
    small behind tolerance). Punch is a forward strike, so the raw band on
    its own describes a dead zone the actor cannot hit."""

    if not in_punch_band(actor, enemy):
        return False
    return (
        enemy_in_front(actor, enemy)
        or abs(enemy.world_x - actor.world_x)
        <= punch_behind_tolerance_x(actor.character_id)
    )


def grab_would_connect(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """True when walking into ``enemy`` would end in a hold.

    Mirrors ``punch_would_connect``'s shape on purpose: the contact test the
    ROM runs (``$AAA0``, see ``GRAB_RANGE_Y``) reads the actor's *attack*
    box, which is oriented forward, so an enemy strictly behind the actor is
    not walked into -- it is turned toward first, and only then grabbed.
    """

    dx = abs(enemy.world_x - actor.world_x)
    dy = abs(enemy.world_y - actor.world_y)
    if dy > GRAB_RANGE_Y:
        return False
    if dx > punch_outer_x(actor.character_id):
        return False
    return enemy_in_front(actor, enemy) or dx <= GRAB_BEHIND_TOLERANCE_X


def in_rear_band(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """Inside the ``$322A`` chord's real reach on the enemy's own side.

    The behind and front bands differ per character (Axel/Blaze have zero
    forward reach), so this must pick the side-specific band, never their
    union -- and the behind band has an *inner* edge as well as an outer one
    (``rear_attack_behind_min_x``): Axel's box starts 8px behind him, Blaze's
    5px. A body closer than that sits under the box, exactly as one inside
    ``punch_inner_x`` sits under the punch, and no amount of pressing B+C
    will touch it.
    """

    dx = enemy.world_x - actor.world_x
    dy = abs(enemy.world_y - actor.world_y)
    if dy > PUNCH_RANGE_Y:
        return False
    adx = abs(dx)
    if enemy_behind_actor(actor, enemy):
        return (
            rear_attack_behind_min_x(actor.character_id)
            <= adx
            <= rear_attack_behind_max_x(actor.character_id)
        )
    front_max = rear_attack_front_max_x(actor.character_id)
    if front_max <= 0:
        # Axel and Blaze have *no* forward reach with this chord. A `<=`
        # against a zero-width band still matches dx == 0, which is where a
        # jump kick that lands exactly on its target leaves the actor -- so
        # the AI answered "nothing can hit this" with a backfist aimed the
        # other way. `check_for_closing_enemies` already guards the same
        # zero-band case explicitly; this is the matching guard on the band
        # itself.
        return False
    return adx <= front_max


def in_jump_attack_band(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """True when a jump kick is the move that covers this gap: in front, in
    lane, inside the kick's own free-flight range.

    The min-dx gate (beyond the actor's own punch outer edge -- no point
    hopping somewhere a punch already reaches) only applies while still
    grounded: that is the launch decision. Once already airborne the actor
    is committed to a fixed trajectory (controls-and-input.md "Free
    flight": no mid-air lane control, only limited air steer) and closing
    distance is no longer optional, so the min-dx gate must not also
    disqualify the follow-through B edge (``$3914``) once the flight has
    naturally carried the actor closer than that edge -- see execute.py's
    ``state_machine_jump_attack`` airborne branch, which this band gates.

    Antonio is the one grounded exception to that min-dx: a standing B is
    his ``$16EAE`` kick trigger, so the hop is the opener inside punch
    range too. Lane and facing still have to hold -- a jump kick is
    horizontal, and hopping at an Antonio off the lane kicks empty air.
    """

    dx = abs(enemy.world_x - actor.world_x)
    dy = abs(enemy.world_y - actor.world_y)
    if dy > JUMP_ATTACK_RANGE_Y:
        return False
    min_dx = 0 if actor.is_airborne else max(JUMP_ATTACK_MIN_DX, punch_outer_x(actor.character_id))
    if isinstance(enemy, Antonio):
        min_dx = 0
    if dx < min_dx:
        return False
    if dx > jump_attack_max_dx(actor.character_id):
        return False
    return enemy_in_front(actor, enemy)


def rear_threats(actor: PlayableCharacter, enemies: list[Enemy]) -> list[Enemy]:
    return [
        e
        for e in enemies
        if enemy_behind_actor(actor, e)
        and abs(e.world_x - actor.world_x) <= REAR_THREAT_X
        and abs(e.world_y - actor.world_y) <= REAR_THREAT_Y
    ]


def rear_attack_is_warranted(
    actor: PlayableCharacter, enemy: Enemy, enemies: list[Enemy]
) -> bool:
    """True when the ``$322A`` chord is the *right* answer to ``enemy``
    sitting in the rear band -- not merely a possible one.

    The chord is slow (up to 21 frames of startup, controls-and-input.md's
    measured timings) and hits only by current position, so it whiffs
    whenever the target moves during startup and leaves the actor in its
    recovery frames. Turning around and punching is faster and far more
    reliable, and turning is free: holding the D-pad toward a behind enemy
    flips facing, after which ``could_punch`` covers it normally (see
    ``execute._walk_to_near_enemy_target``). So the chord is reserved for
    the two cases where turning around does not actually solve anything --
    exactly the "escape when boxed in / punch dead-zone" intent
    ``priority._EMERGENCY_REAR_ATTACK`` has always documented:

    1. **Punch dead zone** -- the target is closer than ``punch_inner_x``,
       so it stays unhittable by a normal strike even after the turn.
    2. **Boxed in** -- another live enemy is close on the actor's opposite
       side, so spending the turn hands that one a free hit.
    3. **Jack, when he is facing the actor** -- his axe juggle and shared
       lunge punish a turn-and-punch: the extra frames spent flipping
       facing are the ones he uses to throw or slide. The chord hits him
       where he is, now. The opposite geometry -- the actor already on
       *his* back, just facing the wrong way (a jump kick that overshot)
       -- is a grab, not a chord: ``enemy_forward_dx < 0`` means turn
       around and take the hold (``grab_reasons`` includes
       ``JACK_FROM_BEHIND``).
    """

    if isinstance(enemy, Jack):
        # On his back: the chord would fire the wrong way. Walk around
        # to face him and grab.
        return enemy_forward_dx(enemy, actor) >= 0

    if abs(enemy.world_x - actor.world_x) < punch_usable_inner_x(actor.character_id):
        return True

    target_behind = enemy_behind_actor(actor, enemy)
    return any(
        other is not enemy
        and enemy_behind_actor(actor, other) is not target_behind
        and abs(other.world_x - actor.world_x) <= REAR_THREAT_X
        and abs(other.world_y - actor.world_y) <= REAR_THREAT_Y
        for other in enemies
    )


def enemy_actionable(
    actor: PlayableCharacter, enemy: Enemy, enemies: list[Enemy]
) -> bool:
    """True when an existing melee/rear-attack verb would actually fire
    on this enemy right now -- not just whether it sits inside
    ``in_punch_band``'s raw distance box.

    Live testing showed that mismatch created a dead zone: an enemy sitting
    behind the actor, beyond RearAttack's own real band but still inside the
    punch box by raw distance, made ``could_walk_to_near_enemy`` skip it as
    "already in range" while nothing could actually hit it, leaving the
    actor standing still and undefended.

    The rear band only counts when ``rear_attack_is_warranted`` agrees:
    ``could_rear_attack`` no longer fires on band membership alone, so
    treating a merely-in-band enemy as actionable would recreate that same
    vacuum -- nothing attacking it, and ``could_walk_to_near_enemy``
    declining to turn toward it.

    Answered about the observed position only, unlike ``connects``' bands,
    which sweep their move's own timeline: this is the "stop walking, you
    can already hit it" signal, and a future-tense answer to it halts the
    approach while the enemy is still out of reach. See
    ``decide._actionable_targets``.
    """

    if in_rear_band(actor, enemy) and rear_attack_is_warranted(actor, enemy, enemies):
        return True
    return punch_would_connect(actor, enemy)


def enemy_forward_dx(enemy: Enemy, actor: PlayableCharacter) -> int:
    """How far ahead of ``enemy``, along its own facing, ``actor`` stands.

    Negative means behind it. This is the coordinate an ``AttackRange`` is
    expressed in, since a range is stored forward-oriented and mirrors with
    the enemy rather than being re-extracted per facing.
    """

    dx = actor.world_x - enemy.world_x
    return -dx if enemy.facing_left else dx


def enemy_can_reach(
    enemy: Enemy, actor: PlayableCharacter, *, margin: int = REACH_SAFETY_MARGIN
) -> bool | None:
    """Would any of this enemy's real attacks cover the actor from here?

    ``None`` means *unknown*, not *no*: bosses have no extracted animation
    set, and a session without ROM table access has no ranges at all. Callers
    must fall back on their own margins for that case rather than treating
    the enemy as harmless.
    """

    if not enemy.attack_ranges:
        return None
    forward_dx = enemy_forward_dx(enemy, actor)
    lane_dy = actor.world_y - enemy.world_y
    return any(
        rng.forward_min - margin <= forward_dx <= rng.forward_max + margin
        and rng.lane_min - margin <= lane_dy <= rng.lane_max + margin
        for rng in enemy.attack_ranges
    )


def enemy_lane_covers(
    enemy: Enemy, actor: PlayableCharacter, *, margin: int = REACH_SAFETY_MARGIN
) -> bool:
    """Is the actor in the *lane* any of this enemy's attacks sweep?

    The lane half of ``enemy_can_reach``, on its own. An attack in this game
    only connects within roughly a lane of its target, so a reach that is
    long on X says nothing about a target standing well above or below it --
    and treating a long reach as dangerous regardless of lane makes an actor
    wait out swings that were never aimed anywhere near it.

    ``False`` when nothing was extracted, which is the same "unknown" every
    other reach predicate reports; callers must not read it as "safe".
    """

    lane_dy = actor.world_y - enemy.world_y
    return any(
        rng.lane_min - margin <= lane_dy <= rng.lane_max + margin
        for rng in enemy.attack_ranges
    )


def in_enemy_dead_zone(
    enemy: Enemy, actor: PlayableCharacter, *, margin: int = REACH_SAFETY_MARGIN
) -> bool:
    """True when the actor stands inside *every* one of this enemy's attacks.

    Not merely "not currently covered": closer than the nearest edge of every
    range it has, so it cannot hit the actor without first backing off. Nora
    is the case this exists for -- her whip (shape ``$22``) starts 32px out,
    so pressing against her is safe from the only attack she owns.

    Conservative on purpose: the margin *shrinks* the dead zone here, where
    it widens the reach in ``enemy_can_reach``. Both err toward "the enemy
    can hit me".
    """

    if not enemy.attack_ranges:
        return False
    forward_dx = enemy_forward_dx(enemy, actor)
    if forward_dx < 0:
        # Behind it. Turning around is free, so this is not a dead zone in
        # any useful sense -- it is just a bad moment for the enemy.
        return False
    return all(forward_dx < rng.forward_min - margin for rng in enemy.attack_ranges)


def too_close_to_keep_approaching(
    actor: PlayableCharacter, enemy: Enemy, *, extra_margin: int = 0
) -> bool:
    """True when walking the last stretch risks arriving as the hit lands.

    Prefers the enemy's own extracted reach: the caution box below was always
    an admitted approximation built from the *actor's* punch range, which has
    nothing to do with how far the enemy can hit. It stays as the fallback
    for an enemy whose ranges are unknown (every boss, and any session
    without ROM tables).

    ``extra_margin`` widens whichever of the two the caller lands on. It
    exists for ``decide.could_walk_to_near_enemy``'s hysteresis band -- see
    ``APPROACH_RELEASE_MARGIN`` -- and defaults to 0, so the threat judgment
    itself (``inference.check_for_incoming_melee``) is unchanged.
    """

    reachable = enemy_can_reach(enemy, actor, margin=REACH_SAFETY_MARGIN + extra_margin)
    if reachable is not None:
        return reachable

    dx = abs(enemy.world_x - actor.world_x)
    dy = abs(enemy.world_y - actor.world_y)
    if dy > RETREAT_CAUTION_MARGIN_Y + extra_margin:
        return False
    outer = punch_outer_x(actor.character_id, actor.held_weapon_type)
    return dx <= outer + RETREAT_CAUTION_MARGIN + extra_margin


def enemy_will_close_soon(
    actor: PlayableCharacter, enemy: Enemy, *, frames: int = CLOSING_ENEMY_THREAT_FRAMES
) -> bool:
    """Will ``enemy`` be caution-close *soon*, even though it is not yet?

    ``too_close_to_keep_approaching`` alone is reactive: it only sees the
    enemy's *current* position, so a fast committed mover -- Signal's slide
    is the ROM-confirmed case (enemy-ai.md "Signal's slide is velocity, not
    a hitbox"), ~2.5 px/frame with no attack shape at all -- can close from
    "outside every band" to "already landing" between two polls with no
    warning. This projects the enemy ``frames`` ahead by its own velocity
    (``Enemy.predict_position_after_n_frames``) and re-tests the same caution
    predicate there.

    A stationary enemy (``grunt_vel_x == grunt_vel_y == 0``, true for every
    ``Boss`` and any ``Grunt`` not currently moving) projects to itself, so
    this degrades to ``too_close_to_keep_approaching`` and never fires an
    extra warning that current-position logic would not already have
    caught.
    """

    return too_close_to_keep_approaching(actor, enemy_projected(enemy, frames))


# The committed dash at $161C6 (souther_state2_claw_dash): +$1C = $00080000,
# i.e. 8px per 60Hz frame, and it resolves only with the target inside $18
# (24px) of its lane. Used by souther_dash_arrives_soon, which exists because
# a Boss populates neither attack_ranges nor grunt_vel_*, so both of
# is_incoming_melee's ordinary tests report "no threat" while he closes
# faster than any grunt.
SOUTHER_DASH_SPEED_X = 8.0
SOUTHER_DASH_RESOLVE_LANE = 0x18  # 24px


def souther_dash_arrives_soon(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """Souther's committed claw dash, which neither test above can see.

    Both of them are blind to it, for the same underlying reason: a ``Boss``
    populates neither ``attack_ranges`` (so ``too_close_to_keep_approaching``
    falls back to a caution box built from the *actor's* punch reach, ~46px)
    nor ``grunt_vel_x``/``grunt_vel_y`` (so ``enemy_will_close_soon`` projects
    him to standing still). The dash at ``$161C6
    (souther_state2_claw_dash)`` closes at ``$00080000`` -- 8px per 60Hz
    frame, faster than any character walks -- so from 90px he arrives in
    about eleven frames while both checks report no threat at all.

    Lane is part of the test rather than slack around it: the dash writes
    only ``+$1C`` and resolves only with the target inside ``$18`` of its
    lane, so an actor already off that lane is genuinely not about to be hit
    -- which is exactly what ``DodgeSoutherSlash`` is spending the tick
    achieving.
    """

    if not isinstance(enemy, Souther) or not enemy.strike_is_committed():
        return False
    if abs(enemy.world_y - actor.world_y) >= SOUTHER_DASH_RESOLVE_LANE:
        return False
    travel = SOUTHER_DASH_SPEED_X * CLOSING_ENEMY_THREAT_FRAMES
    return abs(enemy.world_x - actor.world_x) <= travel


def is_incoming_melee(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """Is ``enemy`` committed and close enough to land on ``actor`` -- now,
    or soon on its own current velocity?

    A dangerous phase alone is not a threat (an enemy swinging at nothing
    three lanes away is not), and neither is proximity alone.
    ``too_close_to_keep_approaching`` alone only sees the enemy's *current*
    position, which misses a committed fast mover: Signal's slide is the
    ROM-confirmed case (enemy-ai.md "Signal's slide is velocity, not a
    hitbox") -- state ``$0A`` sets ``+$1C``/``+$20`` directly (~2.5 px/frame
    toward the target) with no attack shape anywhere in its animation set, so
    ``Enemy.attack_ranges`` is empty for it and there is nothing for a static
    reach check to find. ``enemy_will_close_soon`` re-tests the same caution
    predicate ``CLOSING_ENEMY_THREAT_FRAMES`` frames ahead, so a
    dangerous-phase enemy already closing distance is judged incoming before
    it arrives, not only once it has. ``souther_dash_arrives_soon`` is the
    third path, for the one enemy invisible to both the other tests -- see
    its own docstring.
    """

    if not is_dangerous(enemy.combat_phase):
        return False
    return (
        too_close_to_keep_approaching(actor, enemy)
        or enemy_will_close_soon(actor, enemy)
        or souther_dash_arrives_soon(actor, enemy)
    )


def incoming_melee_targets(context: Context, actor: PlayableCharacter) -> set[str]:
    """Slots of on-screen enemies ``is_incoming_melee`` judges about to land
    on ``actor``. Only on-screen enemies qualify -- an off-screen one cannot
    connect this tick."""

    return {enemy.slot for enemy in on_screen_enemies(context) if is_incoming_melee(actor, enemy)}


# Kick gate at $16EAE (enemy-ai.md "Body state machine"): X thresholds
# selected by the target's +$1C velocity relative to Antonio's facing, and
# a lane window of $10 (or $08 when +$61 is set -- we use the looser $10
# so we never miss a kick). Distances are the ROM's own +$50/+ $52 words.
#
# After the ROM signs velocity into Antonio's facing frame (`neg` if he
# faces left), `bmi` (moving *against* his facing, i.e. toward him) uses
# $78; the non-negative / backing-away path uses $50. Standing still is
# its own path at $50 or $68 -- we take the wider $68 so a kick is never
# missed.
ANTONIO_KICK_DIST_STATIONARY = 0x68  # 104px
ANTONIO_KICK_DIST_CLOSING = 0x78  # 120px; target walking into him
ANTONIO_KICK_DIST_AWAY = 0x50  # 80px; target walking off
ANTONIO_KICK_LANE = 0x10  # 16px
# Dash/throw commit at $16E74: X in [$28, $78) and lane < $14. This is
# the opening hit of the fight -- he dashes as soon as the actor walks
# into that window. The token covers it too: a sidestep cannot leave a
# lane he tracks, so the same hop is the answer.
ANTONIO_DASH_DIST_MIN = 0x28  # 40px
ANTONIO_DASH_DIST_MAX = 0x78  # 120px
ANTONIO_DASH_LANE = 0x14  # 20px
# High-word of a 16.16 velocity is "zero" for the ROM's `tst.w $1C`. A
# couple of tenths of a pixel of walk jitter must not flip the path.
ANTONIO_STATIONARY_VEL = 0.5
# Primary $02 is the committed kick ($171CC).
ANTONIO_KICK_PRIMARY_STATE = 0x02

# Souther's state 1 -> state 2 commit gate at $15EDA
# (souther_state1_active_combat). Same shape as Antonio's $16EAE kick gate: the
# X window is picked by the sign of the *target's* +$1C velocity after the ROM
# signs it into Souther's own facing frame (`neg` when +$60 is nonzero), so
# `bmi` -- walking into him -- gets the widest window.
SOUTHER_SLASH_DIST_CLOSING = 0x68  # 104px; target walking into him
SOUTHER_SLASH_DIST_STATIONARY = 0x58  # 88px
SOUTHER_SLASH_DIST_AWAY = 0x50  # 80px; target walking off
# Lane gate: $0A when +$61 is set, else $1C. We take the wider $1C for the same
# reason the Antonio constants above take their wider pair -- never miss a
# strike by under-stating the box.
SOUTHER_SLASH_LANE = 0x1C  # 28px
# Primary $02 is the whole committed claw ($16118 souther_state2_claw_commit).
SOUTHER_SLASH_PRIMARY_STATE = 0x02

# The X reach of "do not jump near Souther". $16234
# (souther_counter_jump_attack) is where the number comes from: $162A4
# (souther_flag_target_jump_attack) arms +$79 from the *player's* own action
# state ($16/$17/$42/$43 -- the unarmed and armed jump-attack pairs), and
# $16234 then forces Souther straight to primary $02 with the claw spawned,
# bypassing every distance band, the inner abort and the +$66/+$77 gates.
SOUTHER_JUMP_COUNTER_DIST_X = 0x78  # 120px
# Two gates the ROM has here are deliberately **not** reproduced, both
# live-diagnosed after the AI was seen jumping straight into the claws:
#
# * $16234's own lane window ($12, 18px). The jump is horizontal, so the
#   *flight* cannot leave the lane it started on -- but Souther closes lane at
#   4px/frame ($15F98/$160D0), which erases an 18px gap in about five frames,
#   well inside the flight's own ~25. Gating on lane let the AI launch from
#   just off-lane and get counter-hit anyway.
#
# * "is the counter armed" ($15EDA and $16158 call $16234; $1619E/$161C6 do
#   not). Reading that as "then a jump is safe there" was the actual error:
#   the reason the dash handlers skip the counter is that he is *already
#   attacking*, with the type-$98 claw live and carrying hitbox/damage
#   descriptor $225C. Not being countered is not the same as not being hit,
#   and that window is the most dangerous one, not the safe one.
#
# What is genuinely safe is a Souther who cannot act at all, which
# is_punishable already names -- and there the grab outranks the hop anyway.


def _antonio_kick_distance_threshold(antonio: Antonio, actor: PlayableCharacter) -> int:
    """The ROM's X window for the 1->2 kick, given how the actor is moving.

    ``$16EAE`` reads the target's ``+$1C`` high word. Zero is the
    standing-still path (thresholds ``$50``/``$68`` selected by facing and
    ``+$31`` bit 1 -- we take the wider ``$68`` so a kick is never
    missed). Non-zero is signed relative to Antonio's facing ``+$60``:
    negative (moving *against* his facing, i.e. approaching him -- the
    ROM's ``bmi`` path) uses ``$78``, non-negative (backing away) uses
    ``$50``. Same reading as ``ANTONIO_KICK_DIST_CLOSING``/``_AWAY``'s own
    comments above, which is what this function returns.
    """

    vel = actor.vel_x
    if abs(vel) < ANTONIO_STATIONARY_VEL:
        return ANTONIO_KICK_DIST_STATIONARY
    # Sign into Antonio's facing frame the way $16EB4 does: negate if he
    # faces left, then `bmi` is "moving against his facing" = toward him.
    relative = -vel if antonio.facing_left else vel
    if relative < 0:
        return ANTONIO_KICK_DIST_CLOSING
    return ANTONIO_KICK_DIST_AWAY


def antonio_will_kick(antonio: Antonio, actor: PlayableCharacter) -> bool:
    """True when Antonio's kick gate is already satisfied, or the kick is on.

    Already-committed (primary ``$02`` / ``CombatPhase.ATTACKING``) is
    always a kick. The predictive half mirrors ``$16E54``-``$16F0E``:
    target available, in the velocity-selected X window, and inside the
    ``$10`` lane window. ``boss_dist_*`` are the ROM's own ``+$50``/``+$52``
    words; we fall back to a computed gap if they were not populated.
    """

    if antonio.target_unavailable:
        return False
    if antonio.combat_phase in (
        CombatPhase.DEATH,
        CombatPhase.GRABBED,
        CombatPhase.RECOVERY,
    ):
        return False

    dist_x = antonio.boss_dist_x or abs(antonio.world_x - actor.world_x)
    dist_lane = antonio.boss_dist_lane or abs(antonio.world_y - actor.world_y)
    if antonio.primary_state == ANTONIO_KICK_PRIMARY_STATE:
        return dist_lane < ANTONIO_KICK_LANE
    # Already in the dash/throw commit (tactical $08): a locked-in ground
    # strike. Do *not* also fire on the uncommitted dash *window* -- that
    # window is the whole fight range, and treating it as a kick made
    # DodgeAntonioKick win every tick and never attack.
    if antonio.tactical == 0x08:
        return dist_lane < ANTONIO_DASH_LANE and dist_x < ANTONIO_DASH_DIST_MAX
    if dist_lane >= ANTONIO_KICK_LANE:
        return False
    return dist_x < _antonio_kick_distance_threshold(antonio, actor)


def _souther_slash_distance_threshold(souther: Souther, actor: PlayableCharacter) -> int:
    """The ROM's X window for the 1->2 claw commit, given the actor's motion.

    ``$15EDA (souther_state1_active_combat)`` reads the target's ``+$1C``, and
    ``beq`` on it is the standing-still path (``$58``). Non-zero is negated when
    ``+$60`` is nonzero -- signed into Souther's own frame -- so the ``bmi``
    path is "walking into him" and takes the widest window (``$68``), while
    ``bpl`` (backing away) takes the tightest (``$50``).

    The same reading as Antonio's ``_antonio_kick_distance_threshold``, and the
    same practical consequence: closing the distance is what lets him start
    from furthest out.
    """

    vel = actor.vel_x
    if abs(vel) < ANTONIO_STATIONARY_VEL:
        return SOUTHER_SLASH_DIST_STATIONARY
    relative = -vel if souther.facing_left else vel
    if relative < 0:
        return SOUTHER_SLASH_DIST_CLOSING
    return SOUTHER_SLASH_DIST_AWAY


def souther_will_slash(souther: Souther, actor: PlayableCharacter) -> bool:
    """True when Souther's commit gate is satisfied, or the claw is already on.

    Already-committed (primary ``$02``) is always a slash. The predictive half
    mirrors ``$15EDA``: target available, ``+$66`` hard-hold clear, inside the
    lane window, and inside the velocity-selected X window but **outside** the
    ``$18`` inner abort -- that abort is a real part of the gate, not a
    conservatism, so leaving it out would report a slash from a range the ROM
    refuses to start one at.
    """

    if souther.target_unavailable:
        return False
    if souther.combat_phase in (
        CombatPhase.DEATH,
        CombatPhase.GRABBED,
        CombatPhase.RECOVERY,
    ):
        return False

    dist_x = souther.boss_dist_x or abs(souther.world_x - actor.world_x)
    dist_lane = souther.boss_dist_lane or abs(souther.world_y - actor.world_y)
    if souther.primary_state == SOUTHER_SLASH_PRIMARY_STATE:
        return True
    if dist_lane >= SOUTHER_SLASH_LANE:
        return False
    if dist_x < SOUTHER_SLASH_DIST_MIN:
        return False
    return dist_x < _souther_slash_distance_threshold(souther, actor)


def souther_would_punish_jump(actor: PlayableCharacter, context: Context) -> bool:
    """True when a jump attack launched now would be countered by a live Souther.

    Keyed on the actor alone, because ``$162A4
    (souther_flag_target_jump_attack)`` reads the player's own action state and
    nothing about the jump's target: a hop aimed at an unrelated grunt inside
    the box is answered identically.

    A jump near a live Souther loses in two independent ways, which is why this
    does not test whether ``$16234`` is currently on his call path (see the
    constants above): while he can still choose, the jump-attack action state
    hands him the counter; while he is already dashing, the type-``$98`` claw
    is a live attack object and the flight lands in it. The only Souther worth
    hopping at is one who cannot act -- and there a grab (``GrabReason.
    SOUTHER_ON_PUNISH``) outranks the hop anyway.

    The X half-width is widened by the character's own free-flight reach
    (``jump_attack_max_dx``), because ``+$79`` stays set for as long as
    the kick action does and Souther re-tests every frame of the flight rather
    than only its onset: a launch from just outside 120px flies straight in.
    """

    flight = jump_attack_max_dx(actor.character_id)
    for souther in find_all(context, Souther):
        if souther.is_defeated or is_punishable(souther.combat_phase):
            continue
        if abs(souther.world_x - actor.world_x) < SOUTHER_JUMP_COUNTER_DIST_X + flight:
            return True
    return False


def weapon_upgrade_rank(
    actor: PlayableCharacter, weapon: Weapon, camera: CameraRange | None
) -> int | None:
    """This weapon's rank if it is a genuine upgrade for ``actor`` right now,
    else ``None``.

    "Genuine upgrade" means: still usable (``wear < 3``), in camera, and a
    higher ``weapon_rank`` than whatever ``actor`` already holds. Returns the
    rank itself rather than a bare bool, since ``priority.
    _emergency_walk_to_weapon`` scores by how much of an upgrade it is, not
    just whether it is one.
    """

    if camera is None:
        return None
    if weapon.wear >= 3 or not in_camera(camera, weapon.world_x, weapon.world_y):
        return None
    rank = weapon_rank(weapon.weapon_type)
    if rank <= weapon_rank(actor.held_weapon_type):
        return None
    return rank


def connects(band, actor: PlayableCharacter, enemy: Enemy, frames) -> bool:
    """True when ``band`` holds at any frame of this move's own timeline.

    A move is not an instant -- a punch damages for 10 frames, Adam's chord
    for 18 -- so the target only has to be inside the box at *one* of the
    frames ``kinematics.connect_frames`` names, and frame 0 (the observed
    position) is always one of them. That last part is what keeps the
    prediction additive: it can offer an attack the raw position does not,
    and can never take away one it does.
    """

    return any(
        band(actor, enemy_projected_without_crossing(actor, enemy, frame))
        for frame in frames
    )


# Projectiles outside this time-to-impact window are not "incoming" yet.
PROJECTILE_THREAT_TICKS = 30
PROJECTILE_LANE_SLACK = 24
CAUTION_RANGE_X = 40

# object_catalog.py's Jack axe/torch helper. Unlike every other projectile
# family, this object exists while still tethered to Jack's own juggle
# animation, not only once thrown -- so its momentary spin velocity can
# point straight at the actor and satisfy projectile_threatens without a
# real throw ever happening.
JACK_PROJECTILE_TYPE_ID = 0x28

# The juggled axe/torch stays within this radius of Jack himself; once
# thrown it opens that gap on the very next tick. Generous enough to cover
# the juggle's own spin without needing exact ROM offsets.
JACK_JUGGLE_ATTACH_RADIUS = 40

# Antonio's linked boomerang (object_catalog.py type $96). Same attach
# problem as Jack's axe: the object exists while still in his hand, and
# punching it then is just standing still in front of him.
ANTONIO_BOOMERANG_TYPE_ID = 0x96
ANTONIO_BOOMERANG_ATTACH_RADIUS = 40

# Souther's linked claw/afterimage (object_catalog.py types $98/$99, created by
# $16C2E (souther_create_claw) / $16BC6 (souther_create_afterimage)). These are
# animation-synchronized attack objects that live and die with the claw
# sequence, never thrown -- so unlike Antonio's $96 they are withheld from
# an incoming-projectile threat *unconditionally* rather than only while
# attached. The claw is answered by DodgeSoutherSlash, which reads Souther's
# own state; a ProjectileSidestep competing with it would just split the tick.
SOUTHER_CLAW_TYPE_IDS = frozenset({0x98, 0x99})


def projectile_ticks_to_impact(projectile: Projectile, actor: PlayableCharacter) -> float:
    """Ticks until this projectile's own X reaches ``actor``'s, treating a
    stationary hazard (``vel_x == 0``) as already arrived.

    Shared by ``projectile_threatens`` (the gate) and
    ``priority._emergency_projectile_sidestep`` (the score), so a target
    running away scores the same distance both stages agree it is at.
    """

    if projectile.vel_x == 0:
        return 0.0
    return abs(projectile.world_x - actor.world_x) / abs(projectile.vel_x)


def projectile_threatens(projectile: Projectile, actor: PlayableCharacter) -> bool:
    """True when the projectile is heading toward the actor in-lane soon.

    Stage-hazard projectiles with zero X velocity (e.g. a vertical press) are
    treated as threats when already overlapping the actor's X column.
    """

    if abs(projectile.world_y - actor.world_y) > PROJECTILE_LANE_SLACK:
        return False

    dx = projectile.world_x - actor.world_x
    if projectile.vel_x == 0:
        # Stationary/vertical hazard: only if already on or past the actor's X.
        return abs(dx) <= CAUTION_RANGE_X

    heading_toward = (dx > 0 and projectile.vel_x < 0) or (dx < 0 and projectile.vel_x > 0)
    if not heading_toward:
        return False
    return projectile_ticks_to_impact(projectile, actor) <= PROJECTILE_THREAT_TICKS


def antonio_still_holding_boomerang(projectile: Projectile, context: Context) -> bool:
    """True when this is Antonio's boomerang and it is still in his hand.

    Type ``$96`` exists for the whole wind-up/catch, not only once thrown
    (object_catalog.py). Punching or sidestepping it then is standing still
    in front of Antonio -- the kick trigger. Matched to a live ``Antonio``
    within ``ANTONIO_BOOMERANG_ATTACH_RADIUS``, the same attach test Jack's
    axe uses.
    """

    if projectile.type_id != ANTONIO_BOOMERANG_TYPE_ID:
        return False
    for antonio in find_all(context, Antonio):
        if (
            abs(projectile.world_x - antonio.world_x) <= ANTONIO_BOOMERANG_ATTACH_RADIUS
            and abs(projectile.world_y - antonio.world_y) <= ANTONIO_BOOMERANG_ATTACH_RADIUS
        ):
            # Still on him unless it already has a real independent throw
            # velocity. A follow-along attached object tracks him at his
            # own walk speed, well under a thrown boomerang.
            if abs(projectile.vel_x) < 2.0:
                return True
    return False


def is_souther_claw(projectile: Projectile) -> bool:
    """True for Souther's linked claw/afterimage objects (types ``$98``/``$99``).

    Withheld from an incoming-projectile threat for the whole of their
    existence, not just while attached: enemy-ai.md describes them as
    animation-synchronized attack/afterimage objects, and ``$161C6
    (souther_state2_claw_dash)`` re-creates the afterimage every dash tick
    from Souther's own position. They have no independent flight to
    intercept, so the only honest answer is Souther's own state, which
    ``DodgeSoutherSlash`` reads.
    """

    return projectile.type_id in SOUTHER_CLAW_TYPE_IDS


def jack_still_juggling(projectile: Projectile, context: Context) -> bool:
    """True when this is Jack's axe/torch and he has not released it yet.

    The weapon spins tethered to him for the whole juggle, so its
    instantaneous velocity can momentarily point straight at the actor and
    read exactly like an incoming throw. Matched to whichever live,
    still-juggling (``has_projectile``) Jack sits within
    ``JACK_JUGGLE_ATTACH_RADIUS`` of it, since the object carries no
    explicit owner slot.
    """

    if projectile.type_id != JACK_PROJECTILE_TYPE_ID:
        return False
    for jack in find_all(context, Jack):
        if not jack.has_projectile:
            continue
        if (
            abs(projectile.world_x - jack.world_x) <= JACK_JUGGLE_ATTACH_RADIUS
            and abs(projectile.world_y - jack.world_y) <= JACK_JUGGLE_ATTACH_RADIUS
        ):
            return True
    return False


# Enemy phases a hold can actually be taken on. Deliberately not
# ``is_punishable``: that set includes KNOCKDOWN (a body on the floor, which
# the contact test cannot hold) and GRABBED (already held). ATTACKING/CHARGE
# are excluded for the opposite reason -- walking into a committed enemy is
# how the actor takes the hit instead of the hold. What is left is an enemy
# standing on its feet and able to be walked into: free to act, frozen on a
# timed stun, stuck on geometry, or in the tail of its own move.
GRABBABLE_PHASES = frozenset(
    {
        CombatPhase.NORMAL,
        CombatPhase.STUNNED,
        CombatPhase.BLOCKED,
        CombatPhase.RECOVERY,
    }
)

# The shared later-boss hit reaction. $03 and $04 both decode as RECOVERY
# (phases.py), but they are not the same situation: measured live over a full
# Souther fight, $03 held 4% of ticks and $04 held 70%. $04 is where he sits,
# so keying the punish grab on is_punishable handed the top of the emergency
# table to a walk-in that never converted, for most of the fight.
SOUTHER_HIT_REACTION_PRIMARY = 0x03


def actor_is_surrounded(context: Context, actor_slot: str) -> bool:
    """True when ``actor_slot`` carries a live ``Surrounded`` judgment."""

    return any(token.actor_slot == actor_slot for token in find_all(context, Surrounded))


def grab_reasons(
    context: Context,
    actor: PlayableCharacter,
    target: Enemy,
    enemies: list[Enemy],
) -> frozenset[GrabReason]:
    """Every reason a hold on ``target`` beats a strike, right now.

    Not "every enemy that could be grabbed": a grab costs the actor its
    attack for the walk-in and locks both bodies together, so this only
    reports the situations where that trade pays off -- see ``GrabReason``.
    Whether the grab is *reachable* is a separate question, answered by
    ``grab_would_connect``; ``decide.could_grab_enemy`` requires both.

    Most reasons are ``Grunt``-only. Antonio and Souther are the exceptions:
    after a landed hit both sit in the shared later-boss ``RECOVERY`` states
    (primary ``$03``/``$04``), and a hold-then-suplex beats following up with
    another strike -- for Antonio because a grounded punch is his own kick trigger,
    for Souther because ``$15EDA (souther_state1_active_combat)`` cannot
    re-arm the claw from recovery, so the walk-in is free. Bongo, the twins,
    Abadede and Mr. X stay out of scope.

    ``enemies`` should be every on-screen enemy for this actor (the same set
    ``target`` was drawn from) -- ``DODGE_CHARGE`` and ``CLEAR_REAR`` both
    judge ``target`` against the rest of that group.
    """

    if actor.is_holding_enemy:
        # The ROM refuses a fresh grab outright while the actor already has a
        # body: $AAA0 only issues its grab code when the actor's own +$4C is
        # clear. Walking into anything from here is never the answer -- the
        # hold family owns the tick (decide.could_hold_actions).
        return frozenset()

    if target.combat_phase not in GRABBABLE_PHASES:
        return frozenset()

    if isinstance(target, Antonio):
        if is_punishable(target.combat_phase):
            return frozenset({GrabReason.ANTONIO_ON_PUNISH})
        # Ready, and already at contact range: the hold still beats the hop,
        # which is the only other thing available against him. See
        # GrabReason.ANTONIO_WALK_IN -- the range gate is grab_would_connect,
        # which decide.could_grab_enemy requires anyway, so this reason never
        # starts a walk across his kick window.
        return frozenset({GrabReason.ANTONIO_WALK_IN})
    if isinstance(target, Souther):
        # Only the *brief* hit reaction, primary $03 -- deliberately not the
        # whole of is_punishable the way Antonio's is.
        #
        # Measured live over a full 120s Souther fight: he sits in primary
        # $04 for 70% of it (2304 of 3304 ticks) against 4% in $03, and both
        # decode as RECOVERY. Keyed on is_punishable, the grab therefore
        # scored 61+14 = 75 -- the top of the table -- for most of the
        # fight, and the walk-in never converted: 2318 ticks of GrabEnemy,
        # and Souther lost 11 health in two minutes while the actor lost a
        # whole life. $04 is where he *sits*, not a window.
        if target.primary_state == SOUTHER_HIT_REACTION_PRIMARY:
            return frozenset({GrabReason.SOUTHER_ON_PUNISH})
        return frozenset()
    if not isinstance(target, Grunt):
        return frozenset()

    reasons: set[GrabReason] = set()
    candidate_dx = target.world_x - actor.world_x
    # Committed enemies already judged able to land on this actor. A charge
    # coming in from behind the body being grabbed is what DODGE_CHARGE
    # answers -- Signal's hitbox-less slide above all.
    charging = [enemy for enemy in enemies if is_incoming_melee(actor, enemy)]
    if any(
        other.slot != target.slot
        # Same side of the actor, and further out than the body being
        # grabbed: the charge is coming in *through* it.
        and (other.world_x - actor.world_x) * candidate_dx > 0
        and abs(other.world_x - actor.world_x) > abs(candidate_dx)
        for other in charging
    ):
        reasons.add(GrabReason.DODGE_CHARGE)
    if actor_is_surrounded(context, actor.slot):
        # Boxed in: a body in the hands beats a strike whichever side the
        # crowd is on. CLEAR_REAR below only covers the subset with a
        # *confirmed rear* enemy.
        reasons.add(GrabReason.WHILE_SURROUNDED)
    # A rear threat that *is* the candidate is not a pincer -- the actor
    # would be walking backwards into the same enemy it is already worried
    # about, and grab_would_connect (forward only) would not have offered
    # it anyway.
    if any(other.slot != target.slot for other in rear_threats(actor, enemies)):
        reasons.add(GrabReason.CLEAR_REAR)
    if isinstance(target, Jack) and enemy_forward_dx(target, actor) < 0:
        # Facing away: the hold lands before the axe or the lunge can turn
        # around. The opposite geometry -- Jack at the actor's back -- is
        # RearAttack, not a backwards walk-in.
        reasons.add(GrabReason.JACK_FROM_BEHIND)
    if target.min_reach > 0:
        # Every attack it owns starts further out than contact -- read from
        # the ROM shape its animations select, not from the enemy's type.
        # See GrabReason.DEAD_ZONE.
        reasons.add(GrabReason.DEAD_ZONE)
    return frozenset(reasons)
