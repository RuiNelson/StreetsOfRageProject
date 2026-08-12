"""Geometry and target-filtering shared by the whole AI pipeline.

These predicates used to be private helpers inside ``decide.py``, recomputed
independently by ``priority.py`` (through cross-module imports of those
privates) and deliberately *duplicated* by ``inference.py``, which must not
import ``decide``. Keeping them here gives every stage one definition to
agree on: ``inference.py`` turns them into ``TargetInReach`` tokens once per
tick, ``decide.py``/``priority.py`` read those tokens, and ``execute.py``
reuses the same lane/pit clearance values it has to steer around.

Nothing in this module reads RAM or produces tokens -- it only answers
questions about tokens already in the context.

Every predicate here is about *this instant*. When a caller needs "will this
still be true when my move actually lands", it projects the enemy first
(``kinematics.py`` owns the lead times and ``enemy_projected``, re-exported
below) and asks the same question at that future position -- the geometry is
not duplicated for the predictive case.
"""

from __future__ import annotations

from ..phases import should_ignore_as_target
from ..world_map import LANE_Y_MAX_DEFAULT, LANE_Y_MIN, lane_y_max_for_level
from .kinematics import enemy_projected
from .tokens import (
    CameraRange,
    Context,
    Enemy,
    PlayableCharacter,
    Pit,
    PUNCH_RANGE_Y,
    Stage,
    find,
    find_all,
    punch_inner_x,
    punch_outer_x,
    rear_attack_behind_max_x,
    rear_attack_front_max_x,
)

# Punch is a forward strike, but ``_could_melee_strike`` has always allowed a
# few pixels of slack for an enemy that is nominally "behind" while standing
# essentially on top of the actor.
PUNCH_BEHIND_TOLERANCE_X = 4

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
# covered too" for RearAttack, and as a crowd member for Surrounded.
REAR_THREAT_X = 56
REAR_THREAT_Y = 24

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
# boundary, which deletes the IncomingMelee token, which un-skips
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


def targets_of(context: Context, cls: type, actor_slot: str) -> set[str]:
    """Target slots of every ``cls`` token in ``context`` for one actor.

    ``find``/``find_all`` match on a ``slot`` attribute, which the
    actor-and-target inference tokens deliberately do not have (they
    reference two tokens, not one), so this is their lookup.
    """

    return {
        token.target_slot
        for token in find_all(context, cls)
        if getattr(token, "actor_slot", None) == actor_slot
    }


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
    return [
        e
        for e in find_all(context, Enemy)
        if not should_ignore_as_target(e.combat_phase) and in_playable_lane(e.world_y, context)
    ]


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
    return punch_inner_x(actor.character_id) <= dx <= outer


def punch_would_connect(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """``in_punch_band`` *and* the enemy is actually in front (within the
    small behind tolerance). Punch is a forward strike, so the raw band on
    its own describes a dead zone the actor cannot hit."""

    if not in_punch_band(actor, enemy):
        return False
    return (
        enemy_in_front(actor, enemy)
        or abs(enemy.world_x - actor.world_x) <= PUNCH_BEHIND_TOLERANCE_X
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
    return enemy_in_front(actor, enemy) or dx <= PUNCH_BEHIND_TOLERANCE_X


def in_rear_band(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """Inside the ``$322A`` chord's real reach on the enemy's own side.

    The behind and front bands differ per character (Axel/Blaze have zero
    forward reach), so this must pick the side-specific band, never their
    union.
    """

    dx = enemy.world_x - actor.world_x
    dy = abs(enemy.world_y - actor.world_y)
    if dy > PUNCH_RANGE_Y:
        return False
    adx = abs(dx)
    if enemy_behind_actor(actor, enemy):
        return adx <= rear_attack_behind_max_x(actor.character_id)
    return adx <= rear_attack_front_max_x(actor.character_id)


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
    """

    dx = abs(enemy.world_x - actor.world_x)
    dy = abs(enemy.world_y - actor.world_y)
    if dy > JUMP_ATTACK_RANGE_Y:
        return False
    min_dx = 0 if actor.is_airborne else max(JUMP_ATTACK_MIN_DX, punch_outer_x(actor.character_id))
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
    """

    if abs(enemy.world_x - actor.world_x) < punch_inner_x(actor.character_id):
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
    actor: PlayableCharacter,
    enemy: Enemy,
    enemies: list[Enemy],
    *,
    punch_at: Enemy | None = None,
    rear_at: Enemy | None = None,
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

    ``punch_at``/``rear_at`` are the same enemy projected to where each of
    those two moves would meet it (``kinematics``), and default to the enemy
    itself. Any caller that also produces ``InPunchReach``/``InRearReach``
    from projected positions must pass them -- ``inference.check_for_targets_
    in_reach`` does -- because this answers "one of those two attacks would
    fire", and judging the same bands at a different instant would contradict
    the very tokens it is meant to agree with.
    """

    rear_target = enemy if rear_at is None else rear_at
    punch_target = enemy if punch_at is None else punch_at
    if in_rear_band(actor, rear_target) and rear_attack_is_warranted(
        actor, rear_target, enemies
    ):
        return True
    return punch_would_connect(actor, punch_target)


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
