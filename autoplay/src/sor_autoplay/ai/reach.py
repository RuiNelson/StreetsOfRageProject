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

The four band predicates (``in_punch_band``/``punch_would_connect``,
``in_rear_band``, ``in_jump_attack_band``) and the facing helpers take a
``Character``, not an ``Enemy``, although their parameter is still named
``enemy`` for every caller that has one: the ROM asks the identical question
about the *other player*. ``$4478 (resolve_player_vs_player_collision)``
tests the attacker's attack box ``+$64`` against the other player's body box
``+$70``, exactly as ``$450C`` does for an enemy, so ``partner.py``'s
friendly-fire filter answers "would this strike land on the partner" by
calling these rather than measuring the same boxes a second time.

Every predicate here is about *this instant*. When a caller needs "will this
still be true when my move actually lands", it projects the enemy first
(``kinematics.py`` owns the lead times and ``enemy_projected``, re-exported
below) and asks the same question at that future position -- the geometry is
not duplicated for the predictive case.
"""

from __future__ import annotations

import math

from .. import hazards
from ..phases import CombatPhase, is_dangerous, is_punishable, should_ignore_as_target
from ..world_map import (
    CAMERA_X_MIN,
    LANE_Y_MAX_DEFAULT,
    LANE_Y_MIN,
    LANE_Y_MIN_ENEMY,
    lane_y_max_for_level,
)
from . import jump_kick
from .kinematics import (
    AI_LATENCY_FRAMES,
    FRAMES_PER_TICK,
    WALK_SPEED_LANE,
    WALK_SPEED_X,
    enemy_projected,
    enemy_projected_without_crossing,
)
from .tokens import (
    Antonio,
    BODY_OVERLAP_X,
    CameraRange,
    Character,
    Context,
    Enemy,
    GrabReason,
    Grunt,
    Jack,
    PlayableCharacter,
    Pickup,
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
# treats as close-combat range for that character -- and, since ``$AAA0``
# reads that same forward attack box, the same lane tolerance.
#
# It used to be 10 against the punch's 12, "since two bodies have to actually
# overlap" -- and they do overlap there: the bodies are 16px tall, so a 12px
# lane gap is still an overlap, and the box the ROM tests is the punch's own.
# The two pixels were not free. ``decide._actionable_targets`` stops the
# approach the moment ``punch_would_connect`` is true, which is exactly
# ``PUNCH_RANGE_Y``, so an approach settles at 12px of lane and the grab --
# the *plan* against Antonio and Souther -- was unreachable by two pixels
# from the position the AI itself chose to stop at. Reproduced on the tick
# harness against a stationary Souther: alongside, in the pocket, punching
# at dy=12 for every remaining tick and never once offering the hold.
GRAB_RANGE_Y = PUNCH_RANGE_Y

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
# Used here for the dash-arrival clock (``frames_until_melee_lands``); the
# engage's own copy, with the rest of his commit gate, is ``souther.POCKET_DX``.
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


def enemy_behind_actor(actor: PlayableCharacter, enemy: Character) -> bool:
    if actor.facing_left:
        return enemy.world_x > actor.world_x
    return enemy.world_x < actor.world_x


def enemy_in_front(actor: PlayableCharacter, enemy: Character) -> bool:
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


def in_targetable_lane(world_y: int, context: Context) -> bool:
    """``in_playable_lane``'s question asked about an *enemy* rather than a
    stand point: is this body somewhere the actor can still fight it?

    Same ceiling, two pixels lower a floor, and the two pixels are the whole
    point. The ROM clamps the two kinds of body with two different routines:
    players to ``$02..$70`` (``$44 0A``, inside
    ``$43AA (clamp_players_to_gameplay_bounds)``) and enemies to ``$00..$70``
    (``$17AB8``, ai-analysis/enemy-ai.md). Souther spends about a quarter of
    a round-2 fight standing in those top two rows, and judging him by the
    *player's* floor dropped him out of ``live_enemies`` outright: no target,
    so no approach, no attack and no ranking -- the AI fell through to
    ``WalkToAdvanceStage`` and walked away from a live boss. Measured over a
    90 s fight, 2228 of 10220 ticks.

    A lane the actor cannot stand in is not a lane it cannot *hit*: from the
    player floor at ``$02`` an enemy at ``$00`` is 2px away, and every strike
    in the game reaches ``PUNCH_RANGE_Y`` (12px) of lane. The unreachable
    placeholder this filter exists for -- stage 1's scripted "behind a door"
    enemy -- sits far past the *ceiling*, which both bands still reject.
    """

    stage = find(context, Stage)
    lane_max = lane_y_max_for_level(stage.level_index) if stage is not None else LANE_Y_MAX_DEFAULT
    return LANE_Y_MIN_ENEMY <= world_y <= lane_max


# How far below the round's own street surface (hazards.base_floor_z) an
# ordinary enemy's world_z may sit and still count as "on the ground". Round
# 5's HakuRo (ai-analysis/enemy-ai.md, "HakuRo: rising from below deck")
# measured 52px ($34, the ROM's own one-shot +$18 offset at
# haku_ro_type25_dispatcher's state $13 entry, $0000E952) below the surface
# while stuck -- a live capture also showed it can sit there frozen
# indefinitely (the same handler re-tests cam_x+$80/+$100 against its own
# world_x every tick and does not touch +$18/+$24 at all until that clears,
# so nothing here can assume "a few ticks and it settles"). A wide margin
# keeps ordinary float/lane jitter of a body actually on the floor from ever
# tripping this; 52px of slack is nowhere near it.
EMERGING_FLOOR_MARGIN_Z = 24


def enemy_still_emerging(enemy: Enemy, context: Context) -> bool:
    """True while this enemy's body has not reached the round's floor yet.

    Ordinary enemies do not otherwise move on the Z axis at all -- this is a
    generic geometry check (any type, any round with a similar rise-from-
    below mechanic), not a HakuRo- or round-5-specific one, because the ROM
    fact it reads is generic: ``hazards.base_floor_z`` is the same per-round
    street surface ``hazards.is_wall_class`` already measures a raised class
    against, and ``Enemy.world_z`` (+$18) is read from the object table for
    every ordinary enemy and boss uniformly by ``world_map.py``. A ``Boss``
    never has this field populated (it tracks its own elevation as
    ``ground_z``/``vel_z``), so it reads its default 0 and this is always
    ``False`` for one.

    Without a ``Stage`` token in context (should not happen once gameplay
    has started) this reads conservatively as ``False`` -- never suppress a
    target from a missing token rather than a real measurement.
    """

    stage = find(context, Stage)
    if stage is None:
        return False
    return enemy.world_z > hazards.base_floor_z(stage.level_index) + EMERGING_FLOOR_MARGIN_Z


def live_enemies(context: Context) -> list[Enemy]:
    """Every enemy still worth acting on.

    Four independent ways to stop being one, and all four are needed:

    - ``should_ignore_as_target`` -- the phase says so (DEATH, or a SCRIPTED
      sequence like the police-special sweep);
    - ``Enemy.is_defeated`` -- the *health word* says so, which the phase can
      lag behind by a long time: the ROM's lethal check is signed, so
      ``$8000``-``$FFFF`` is already dead while the object sits there with a
      stale action family. Without this the AI chases, ranks and punches
      corpses, and blocks its own stage advance behind them;
    - ``in_targetable_lane`` -- it is somewhere the actor can neither reach
      nor hit (stage 1's scripted "behind a door" placeholder is a real,
      tracked Enemy past the lane ceiling). Deliberately the *enemy* band and
      not ``in_playable_lane``'s player band: see that function;
    - ``enemy_still_emerging`` -- it is visible and carries a real state/
      health/hitbox, but is physically below the round's own floor and not
      yet a body the actor can touch (round 5's HakuRo jumping up from below
      the boat's deck; see that function and
      ai-analysis/enemy-ai.md's "HakuRo: rising from below deck"). Left
      unfiltered, this reads as a completely ordinary, on-screen, targetable
      enemy -- HakuRo has no entry in ``phases.py``'s per-type table, so its
      state ``$13`` decodes as ``UNKNOWN`` rather than something
      ``should_ignore_as_target`` already excludes -- and the AI walked up
      to it and punched it every tick for as long as it stayed frozen there,
      which measured live is indefinitely (the ROM handler will not resume
      integrating its height until the camera scrolls close enough, and nothing
      advances the camera while the AI is busy fighting it).
    """

    return [
        e
        for e in find_all(context, Enemy)
        if not should_ignore_as_target(e.combat_phase)
        and not e.is_defeated
        and in_targetable_lane(e.world_y, context)
        and not enemy_still_emerging(e, context)
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

    ``None`` too while (1) names the other player
    (``PlayableCharacter.is_holding_player``): no enemy is in hand then, and
    (2) and (3) would name a bystander for the hold family to knee and
    suplex *through* the partner.
    """

    if not actor.is_holding_enemy:
        return None
    if actor.is_holding_player:
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


# ``CameraRange`` is the player's *walk clamp* (``camera_x + $20 .. + $120``),
# not the visible CRT: ``observe.py`` builds it from ``world_map``'s
# ``camera_left``/``camera_right``, which are that clamp. The screen is 320px
# wide against the clamp's 256, so a 32px strip down each side is plainly
# visible and fought in while sitting outside ``in_camera`` -- exactly what
# ``world_map``'s own note means by "combat still uses the full CRT-relative
# 0..320 X band". Souther backs into the left strip constantly: 1462 of 10220
# ticks of a measured round-2 fight, each one a tick where the boss was on
# screen, in front of the actor, and invisible to every verb that asks
# ``on_screen_enemies``.
SCREEN_STRIP_X = CAMERA_X_MIN  # 32px each side; (320 - $100) / 2


def in_visible_screen(camera: CameraRange, world_x: int, world_y: int) -> bool:
    """``in_camera`` widened from the walk clamp to the CRT -- see
    ``SCREEN_STRIP_X``. Use this to ask "can the actor see and fight it";
    ``in_camera`` stays the question "may the actor stand there"."""

    return (
        camera.left - SCREEN_STRIP_X <= world_x <= camera.right + SCREEN_STRIP_X
        and camera.top <= world_y <= camera.bottom
    )


def on_screen_enemies(context: Context) -> list[Enemy]:
    camera = find(context, CameraRange)
    enemies = live_enemies(context)
    if camera is None:
        return enemies
    return [e for e in enemies if in_visible_screen(camera, e.world_x, e.world_y)]


def in_punch_band(actor: PlayableCharacter, enemy: Character) -> bool:
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


def punch_would_connect(actor: PlayableCharacter, enemy: Character) -> bool:
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


# --- Walking into the other player ($4478) ---------------------------------
#
# A walk into the other player is a hold on them, exactly as a walk into an
# enemy is. ``$4478 (resolve_player_vs_player_collision)`` tests each player's
# attack box (``+$64``) against the other's body box (``+$70``), inclusively
# on every axis, and when the walker's outgoing damage ``+$34`` is zero and
# both players' actions read 1 in the table at ``$45D4`` (idle ``$02``, every
# walk ``$06``-``$0F``, the armed ground family ``$30``-``$3B``; a jump reads
# 2, which hits but never grabs), it writes grab contact (``+$7C`` = 3) and
# ``$3266`` takes the front ``$60`` / back ``$66`` hold on them.
#
# The box a walk puts out is decoded straight from the ROM: ``$1F20`` holds
# each character's animation set, ``$2F2C`` plays animations 4/5 for every
# walk action (24/25 armed, the same boxes), and every frame of them names one
# attack shape starting at the origin -- ``$4D`` (Axel, 0..16), ``$CF`` (Adam,
# 0..20), ``$8F`` (Blaze, 0..19), mirrored by the next id in ``$1ABA8``.
# Blaze's 19 is also what ``tools/souther_hold_lab.py`` measured live.
# Standing still puts out none: a released pad drops the walk to idle ``$02``
# (``$2E6C``), animation 0, whose frame names no attack box, and ``$4140``
# then parks ``+$64`` at world X 0 (P1) or ``$10`` (P2), where no body in play
# can be.
#
# **A lane walk counts too.** The D-pad table at ``$2D00`` sends Up alone to
# ``$0A`` and Down alone to ``$0E``, both through ``$2EE8``, which keeps the
# facing bit: the same animations 4/5, the box facing the way the actor
# already faces. Only an X press turns it (Right is ``$06``, Left ``$07``).
WALK_BOX_REACH_X: dict[int, int] = {0: 16, 1: 20, 2: 19}  # Axel, Adam, Blaze
# The longest of the three. This reach keeps the actor *out* of contact, so an
# unknown character must never be assumed to reach less than it can.
# (``souther.WALK_BOX_REACH_X`` keeps its own, deliberately narrower fallback:
# there the reach decides whether a walk-in is attempted at all.)
DEFAULT_WALK_BOX_REACH_X = 20
# How far a standing or walking player's body box reaches from its own origin,
# either facing: the idle frames lean furthest (Axel 0..13, Blaze 2..12, Adam
# -5..+7), and a partner turns or starts to walk without notice.
PLAYER_BODY_REACH_X: dict[int, int] = {0: 13, 1: 7, 2: 12}
DEFAULT_PLAYER_BODY_REACH_X = 13
# Every player shape uses lane extent 0 (-8..+8), and ``$450C`` compares with
# ``bgt``/``blt``/``bge``: two lanes exactly 16 apart still touch. (``$AB88``,
# the enemy-contact test behind ``souther.GRAB_LANE``, compares strictly.)
PLAYER_CONTACT_LANE_Y = 16
# How long one tick's mask walks before the next tick can change it: the hold
# itself, plus the age of the snapshot it was decided from.
WALK_SWEEP_FRAMES = FRAMES_PER_TICK + AI_LATENCY_FRAMES


def walk_box_reach_x(character_id: int | None) -> int:
    """How far ``character_id``'s walking box reaches ahead of its origin."""

    if character_id is None:
        return DEFAULT_WALK_BOX_REACH_X
    return WALK_BOX_REACH_X.get(character_id, DEFAULT_WALK_BOX_REACH_X)


def player_body_span_x(player: PlayableCharacter) -> tuple[int, int]:
    """Where ``player``'s body box can be on X over the next few frames.

    The widest ground body the character has about its origin, widened by the
    box ``+$70`` actually holds this frame wherever that reaches further (a
    hurt frame, say).
    """

    if player.character_id is None:
        body = DEFAULT_PLAYER_BODY_REACH_X
    else:
        body = PLAYER_BODY_REACH_X.get(player.character_id, DEFAULT_PLAYER_BODY_REACH_X)
    lo, hi = player.world_x - body, player.world_x + body
    box = player.hitbox
    if box is not None and not box.is_degenerate:
        lo, hi = min(lo, box.x0), max(hi, box.x1)
    return lo, hi


def _walk_speed(table: dict[int, float], character_id: int | None) -> float:
    """``table``'s speed for this character, the fastest when it is unknown:
    a sweep that comes up short is contact it failed to see."""

    fastest = max(table.values())
    if character_id is None:
        return fastest
    return table.get(character_id, fastest)


def walking_box_would_grab(
    actor: PlayableCharacter,
    other: PlayableCharacter,
    *,
    step_x: int,
    step_y: int,
) -> bool:
    """Would one tick of walking put ``actor``'s walking box on ``other``?

    ``step_x``/``step_y`` are the walk's directions, each -1, 0 or +1 (right
    and down positive); both 0 is standing still, which puts out no box. The
    box faces ``step_x`` when there is one and the actor's current facing
    otherwise -- see ``WALK_BOX_REACH_X`` for why a lane walk keeps it.

    The walk is swept over ``WALK_SWEEP_FRAMES`` at the character's ROM walk
    speed (``kinematics.WALK_SPEED_X``/``WALK_SPEED_LANE``), and so is
    ``other``'s own X velocity (``+$1C``): a partner walking in closes the gap
    as surely as the actor does. Their lane velocity is not observed, so it is
    not swept.
    """

    if not step_x and not step_y:
        return False
    frames = WALK_SWEEP_FRAMES
    travel_x = step_x * _walk_speed(WALK_SPEED_X, actor.character_id) * frames
    travel_y = step_y * _walk_speed(WALK_SPEED_LANE, actor.character_id) * frames

    dy = other.world_y - actor.world_y
    if dy - max(0.0, travel_y) > PLAYER_CONTACT_LANE_Y:
        return False
    if dy - min(0.0, travel_y) < -PLAYER_CONTACT_LANE_Y:
        return False

    # The body's span relative to the actor's origin, swept by how the two
    # close on each other over the tick.
    closing = other.vel_x * frames - travel_x
    lo, hi = player_body_span_x(other)
    lo = lo - actor.world_x + min(0.0, closing)
    hi = hi - actor.world_x + max(0.0, closing)
    facing_left = step_x < 0 if step_x else actor.facing_left
    reach_x = walk_box_reach_x(actor.character_id)
    box_lo, box_hi = (-reach_x, 0) if facing_left else (0, reach_x)
    return lo <= box_hi and hi >= box_lo


def in_rear_band(actor: PlayableCharacter, enemy: Character) -> bool:
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


def in_jump_attack_band(actor: PlayableCharacter, enemy: Character) -> bool:
    """True when a jump kick is the move that covers this gap -- and the
    kick would really land on ``enemy``'s body.

    Two questions. The first is policy, and unchanged in spirit: in front;
    grounded, past the actor's own punch outer edge (no point hopping where a
    punch already reaches) and no further than the kicked flight itself
    carries the actor (``jump_kick.landing_distance`` -- 67/77/84 px, the lab's
    own landings; a kick launched from further away connects only if the
    target keeps still for the whole flight).

    The second used to be a distance band -- dx within 50/48/60..60/69/75 and
    14 px of lane -- and is now the ROM's own physics (``ai/jump_kick.py``):
    the flight launched now, with the kick edge on either free-flight update
    the executor can land it on, puts its box on the body. That is what the
    band never could say: the box rides high enough near the top of the arc
    to pass clean over a standing body (Blaze's does not even come out for 6
    updates), and low enough on the way up and down to reach far past 60 px
    -- as far as ~110 px for Axel -- which is what let a kick aimed at an
    enemy land on the partner behind it.

    Once airborne the question is only whether B pressed now still connects
    (``jump_kick.airborne_hits``), with no min-dx: the flight has already
    carried the actor where it carries it. When the floor under that flight
    is unknown, the old distance band answers instead.
    """

    if not enemy_in_front(actor, enemy):
        return False
    dx = abs(enemy.world_x - actor.world_x)
    if actor.is_airborne:
        hit = jump_kick.airborne_hits(actor, enemy)
        if hit is not None:
            return hit
        return (
            abs(enemy.world_y - actor.world_y) <= JUMP_ATTACK_RANGE_Y
            and dx <= jump_attack_max_dx(actor.character_id)
        )
    min_dx = max(JUMP_ATTACK_MIN_DX, punch_outer_x(actor.character_id))
    if dx < min_dx or dx > jump_kick.landing_distance(actor.character_id):
        return False
    return jump_kick.launch_hits(actor, enemy)


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

    (Jack is never a chord target: ``EngageJack`` owns him.)
    """

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
    -- which is what ``EngageSouther``'s claw escape spends the tick
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


def frames_until_melee_lands(actor: PlayableCharacter, enemy: Enemy) -> int | None:
    """How many 60 Hz frames before this enemy's committed attack can reach
    ``actor`` -- ``None`` when it is not coming at all.

    ``is_incoming_melee`` answers *whether*; a caller deciding what it still
    has time to do needs *when*, and the two must not disagree, so this is
    built out of the same three tests rather than out of new arithmetic:

    - already inside its own reach (``too_close_to_keep_approaching``) is
      **0**: nothing about the current frame stops the blow;
    - a committed Souther claw dash gets its own answer, because a ``Boss``
      populates no velocity for the generic path to extrapolate: ``$161C6``
      closes at ``SOUTHER_DASH_SPEED_X`` and resolves at
      ``SOUTHER_SLASH_DIST_MIN``, so the frames left are the gap between them
      over that speed;
    - otherwise the enemy's own ROM velocity is walked forward one frame at a
      time (``kinematics.enemy_projected``, the same projection
      ``enemy_will_close_soon`` uses) until the caution box it is closing on
      is satisfied. Scanning rather than dividing keeps this answering the
      *same predicate* the "is it incoming" side answers, which a
      distance-over-speed shortcut would quietly stop doing the moment either
      side's geometry changed.

    Beyond ``CLOSING_ENEMY_THREAT_FRAMES`` the answer is ``None``: past that
    horizon a constant velocity is not evidence of anything (see
    ``kinematics.MAX_LEAD_FRAMES``), and "not coming" is the honest reading.
    """

    if not is_dangerous(enemy.combat_phase):
        return None
    if too_close_to_keep_approaching(actor, enemy):
        return 0
    if souther_dash_arrives_soon(actor, enemy):
        gap = abs(enemy.world_x - actor.world_x) - SOUTHER_SLASH_DIST_MIN
        return max(0, int(gap / SOUTHER_DASH_SPEED_X))
    for frames in range(1, CLOSING_ENEMY_THREAT_FRAMES + 1):
        if too_close_to_keep_approaching(actor, enemy_projected(enemy, frames)):
            return frames
    return None


def frames_until_any_melee_lands(
    actor: PlayableCharacter,
    enemies: list[Enemy],
    *,
    ignore_slots: frozenset[str] = frozenset(),
) -> int | None:
    """The soonest of ``frames_until_melee_lands`` over ``enemies``.

    ``ignore_slots`` is for the body already in the actor's hands: it is not a
    threat while held, and a caller asking "how long have I got" means from
    everything *else*.
    """

    soonest: int | None = None
    for enemy in enemies:
        if enemy.slot in ignore_slots or enemy.is_defeated:
            continue
        frames = frames_until_melee_lands(actor, enemy)
        if frames is None:
            continue
        if soonest is None or frames < soonest:
            soonest = frames
    return soonest


def incoming_melee_targets(context: Context, actor: PlayableCharacter) -> set[str]:
    """Slots of on-screen enemies ``is_incoming_melee`` judges about to land
    on ``actor``. Only on-screen enemies qualify -- an off-screen one cannot
    connect this tick."""

    return {enemy.slot for enemy in on_screen_enemies(context) if is_incoming_melee(actor, enemy)}


# Antonio's kick and dash gates -- and every other part of his AI -- live in
# ``antonio.py``, with the side-dependent lane gate the ROM actually applies
# (``$08`` above his lane, ``$10`` level or below).

# Souther's claw commit (``$15EDA``) and the geometry around it live in
# ``souther.py``, with the lane gate the ROM actually applies: ``$0A`` for a
# target above his lane (``+$61``), ``$1C`` level or below.

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
    is a live attack object and the flight lands in it.

    **Including while he is punishable**, which is the one exemption this used
    to make and the ROM does not support. `$16234` is not on the call path of
    the shared hit-reaction states `$03`/`$04`, so a hop launched *during* his
    recovery cannot be countered on that tick -- but the flight is ~45 frames
    and his recovery is a handful, and `$162A4` is re-run from
    `$16294 (souther_select_target)` on every single state-1 tick against the
    player's live action state, which stays `$16`/`$17` for the whole flight.
    So the counter arms itself the instant he leaves recovery, with the actor
    still in the air. Measured: with this exemption in place the AI spent 298
    of 3541 fight ticks airborne against him. A punishable Souther is a walk-in
    and a hold (``EngageSouther``), never a hop.

    The X half-width is widened by the character's own free-flight reach
    (``jump_attack_max_dx``), because ``+$79`` stays set for as long as
    the kick action does and Souther re-tests every frame of the flight rather
    than only its onset: a launch from just outside 120px flies straight in.
    """

    flight = jump_attack_max_dx(actor.character_id)
    for souther in find_all(context, Souther):
        if souther.is_defeated:
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


# ``$3136 (find_close_interaction_target)``'s search box, read straight off the
# routine (``addi.w #$ffec`` / ``#$0028`` on X, ``#$fff0`` / ``#$0020`` on the
# lane, ``#$fff8`` / ``+8`` on height). Every grounded B press calls it before
# committing to a strike -- ``$3028 (player_normal_attack_input)``'s first
# press and combo continuation alike, and the held-weapon swing path -- and a
# match turns the press into a pickup instead. The compares are inclusive
# (``bgt``/``blt``) and there is no nearest-first ranking: the first eligible
# object in object-table slot order wins.
B_PRESS_PICKUP_X = 0x14  # 20
B_PRESS_PICKUP_Y = 0x10  # 16


def _object_slot_order(slot: str) -> int:
    """Object-table index of an ``objNN`` slot -- the order ``$3136`` scans in."""

    if slot.startswith("obj"):
        try:
            return int(slot[3:])
        except ValueError:
            pass
    return 1 << 16


def item_a_b_press_takes(context: Context, actor: PlayableCharacter) -> Pickup | Weapon | None:
    """The floor item a grounded B press would pick up right now, or ``None``.

    ``$3136`` accepts a free weapon (``+$51`` clear, wear ``< 3``) -- even with
    a weapon already in hand, which it lets go of -- and the six consumable
    types. ``Weapon``/``Pickup`` tokens exist only for free ground items, so
    the wear is the one test left to make here. The height test (``±8``) is
    always met by a grounded actor and an item on its floor, and an airborne B
    is the jump kick (``$3914``), which never reaches ``$3136``.

    So a punch thrown with food at the actor's feet is not a punch: it eats
    the food. That is how the AI used to take food the partner needed more
    while fighting beside it (user: "a IA a usar um item de recuperação de
    vida quando o partner precisa mais dele").
    """

    if actor.is_airborne:
        return None
    candidates = [
        item
        for item in (*find_all(context, Weapon), *find_all(context, Pickup))
        if abs(item.world_x - actor.world_x) <= B_PRESS_PICKUP_X
        and abs(item.world_y - actor.world_y) <= B_PRESS_PICKUP_Y
        and not (isinstance(item, Weapon) and item.wear >= 3)
    ]
    return min(candidates, key=lambda item: _object_slot_order(item.slot), default=None)


# --- Whose fight it is -------------------------------------------------------
#
# User: "a IA a tentar atacar o mesmo inimigo que o partner já está a atacar ou
# perto de atacar, estuda bem o assunto e evita isso!". A human's intent is not
# observable, but what their character can hit is, and it is the same geometry
# the AI's own attacks are judged by.
#
# "Perto de atacar" is a few steps short of strike reach, facing it, on its
# lane band. A walk covers 3.0 px per 30 Hz update, so 24 px is about a quarter
# of a second: the partner arriving at the enemy, not merely passing by it.
PARTNER_ENGAGE_APPROACH_X = 24
PARTNER_ENGAGE_LANE_SLACK_Y = 8


def partner_is_engaging(partner: PlayableCharacter, enemy: Enemy) -> bool:
    """Is the other player attacking ``enemy`` right now, or about to?

    - holding it (their ``+$4C`` names it);
    - in the air, with a kick whose flight lands on it
      (``jump_kick.airborne_arc`` -- B assumed if it is not out yet);
    - on the ground, with a forward strike of theirs reaching it now
      (``punch_would_connect``, armed or not), or with it in front of them, on
      their lane band, within ``PARTNER_ENGAGE_APPROACH_X`` of that reach.

    Never while the partner is the one held: an enemy holding the partner is
    the one fight the AI is welcome in, and friendly fire keeps its strikes
    off the partner's own body.
    """

    if partner.held_enemy_slot == enemy.slot:
        return True
    if partner.combat_phase is CombatPhase.HELD_BY_ENEMY:
        return False
    if partner.is_airborne:
        steps = jump_kick.airborne_arc(partner)
        if not steps:
            return False
        ground = partner.ground_z if partner.ground_z is not None else partner.world_z
        body = jump_kick.enemy_body(enemy, ground_z=float(ground))
        return jump_kick.first_hit_frame(steps, lambda frame: body, inclusive=False) is not None
    if punch_would_connect(partner, enemy):
        return True
    if not enemy_in_front(partner, enemy):
        return False
    dx = abs(enemy.world_x - partner.world_x)
    dy = abs(enemy.world_y - partner.world_y)
    reach_x = punch_outer_x(partner.character_id, partner.held_weapon_type)
    return (
        dx <= reach_x + PARTNER_ENGAGE_APPROACH_X
        and dy <= PUNCH_RANGE_Y + PARTNER_ENGAGE_LANE_SLACK_Y
    )


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
# family, this object exists while still tethered to Jack's own juggle, not
# only once thrown -- its own +$30 says which (ai/jack.py: 1 juggled, 2 tossed
# high, 3 dropped, 4 thrown, and a thrown one flies only once +$31 bit 1 is
# set, on his release frame).
JACK_PROJECTILE_TYPE_ID = 0x28
JACK_AXE_THROWN = 4
JACK_AXE_RELEASED_BIT = 0x02

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
# attached. They carry no attack box of their own either -- the claw's box
# is Souther's *own* animation (souther.py) -- and EngageSouther reads his
# state; a ProjectileSidestep competing with it would just split the tick.
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

    A projectile with zero X velocity is a threat when already on or near the
    actor's X column. (Round 6's press used to come through here too; it is a
    ``Press`` now, and its drop zone is not its lane -- see ``ai/press.py``.)
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
    if projectile.state in (1, 2, 3):
        # Out, back or knocked away ($17272's states 1-3): off his hand.
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
    ``EngageSouther`` reads.
    """

    return projectile.type_id in SOUTHER_CLAW_TYPE_IDS


def jack_still_juggling(projectile: Projectile, context: Context) -> bool:
    """True when this is one of Jack's axes and not a released throw.

    Only a thrown axe (its own ``+$30`` = 4) past its release (``+$31`` bit
    1, set on his animation's frame 1) has a flight to step off: a juggled
    one rides his hand (``$FCB6``), a tossed one hangs high over him, a
    dropped one tests no contact, and a thrown one still waiting sits 64 px
    over his head (``ai/jack.py``). The object's own state says which --
    the old guess by distance from him called a throw released point-blank
    "still juggling" and let it land.
    """

    if projectile.type_id != JACK_PROJECTILE_TYPE_ID:
        return False
    return not (
        projectile.state == JACK_AXE_THROWN and projectile.flags_31 & JACK_AXE_RELEASED_BIT
    )


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

    Every reason is ``Grunt``-only. Antonio and Souther are not cases here
    at all -- each one's hold is his engage's own walk-in (``EngageAntonio``/
    ``antonio.plan_engage``, ``EngageSouther``/``souther.plan_engage``).
    Bongo, the twins, Abadede and Mr. X stay out of scope.

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
    if target.min_reach > 0:
        # Every attack it owns starts further out than contact -- read from
        # the ROM shape its animations select, not from the enemy's type.
        # See GrabReason.DEAD_ZONE.
        reasons.add(GrabReason.DEAD_ZONE)
    return frozenset(reasons)
