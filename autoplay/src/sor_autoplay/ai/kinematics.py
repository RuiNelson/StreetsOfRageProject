"""Where a target will be when a move actually arrives -- the AI's time axis.

``reach.py`` answers *geometry* ("is that enemy inside this band"), always
about the instant the snapshot was taken. Nothing in a Mega Drive beat-em-up
lands at that instant: every attack costs startup frames, a jump kick costs a
crouch plus a flight, a thrown knife costs travel, and the AI's own poll adds
a frame or two on top. This module owns that delay and turns it into a
prediction, so an attack is judged against where its target will be **when it
connects** instead of where the target stood when the decision was made.

Three things make that possible without tuning anything:

- ``Enemy.predict_position_after_n_frames`` -- the enemy's own ROM velocity
  (``+$1C``/``+$20``, integrated once per 60 Hz frame by ``$17AB8``),
  extrapolated at constant speed;
- measured move timings from ``ai-analysis/controls-and-input.md`` (punch and
  chord startup, jump crouch and launch velocity) and
  ``weapons-range-and-damage.md`` (thrown weapon speeds);
- the ground walk speeds the ROM's own tables hold, for the two "attacks"
  that are really approaches (a grab walk-in, a jump kick's flight).

Everything here is expressed in **60 Hz game frames**, never AI poll ticks.
Those are different units -- the default poll is 33 ms, about 2 frames
(``app.DEFAULT_POLL_MS`` / ``app.ASSUMED_HZ``) -- and mixing them is a silent
factor-of-two error, which is exactly what a velocity in px per *frame*
multiplied by a *tick* count used to be. ``FRAMES_PER_TICK`` is the one
conversion point.

**A prediction may only ever add an attack, never take one away.** An attack
is not an instant: a punch damages for 10 frames (3-12), Adam's chord for 18,
so the honest question is "is the target inside the box at *any* damaging
frame", and frame 0 -- the position actually observed -- is always one of the
frames sampled. Judging a move at a single future instant instead is a real
regression, measured over a swept pipeline: an enemy walking *into* Axel from
20px projects into the punch's own inner dead zone, which deleted the
``Punch``, handed the tick to ``WalkToNearEnemy`` and had the actor walk into
enemies it should have hit -- and at 8px it promoted the slow ``RearAttack``
chord at point-blank range instead. So ``ATTACK_CONNECT_FRAMES`` gives each
attack the *set* of frames its band should be tested at, always starting at
0, and ``inference`` takes the union.

For the same reason the lead of a *travelling* move is only its dead time,
not its whole flight: a jump kick's lead is the 5-frame crouch it spends on
the ground, because that is the part the launch decision cannot see, while
how far the flight itself reaches is already what ``reach.in_jump_attack_
band`` measures. Leading by the full flight instead launches kicks from
100+px on the assumption that the target keeps walking in for the whole
25 frames -- airborne, committed, and short if it stops.

Every concrete attack verb has an entry in that register and
``tests/ai/test_kinematics.py`` fails if one is added without one. Several
are legitimately just ``(0,)``, and say why in their own model function -- a
held enemy travels with the actor, a crate does not move, and the police
special has no aim point at all -- because "nothing to predict" is a
kinematic result here, not an omission.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from .tokens import (
    Attack,
    AttackHeldEnemy,
    CallPolice,
    CounterGrab,
    Enemy,
    FlipHold,
    GrabEnemy,
    JumpAttack,
    OpenBreakable,
    PlayableCharacter,
    Punch,
    RearAttack,
    ReleaseGrab,
    SprayPepper,
    StabWithKnifeOrBottle,
    Supplex,
    SwingBatOrPipe,
    ThrowHeldEnemy,
    ThrowKnife,
    ThrowPepper,
    punch_outer_x,
)

# The emulated machine's frame rate, and the AI's own sample period expressed
# in those frames (app.DEFAULT_POLL_MS = 33 ms at app.ASSUMED_HZ = 60). Kept
# as literals rather than imported from app.py: this module is part of the
# decision pipeline, which never imports the CLI/observer layer, and the poll
# period is a knob the user can move while these are the *nominal* figures
# every measured constant below was taken at.
FRAMES_PER_SECOND = 60
FRAMES_PER_TICK = 2

# The pipeline's own delay, on top of any move's startup: the snapshot a
# decision is made from is already up to one poll old by the time the press
# reaches the emulator (observe -> infer -> decide -> rank -> execute all run
# between two polls). One tick, deliberately -- not a tuned fudge factor.
AI_LATENCY_FRAMES = FRAMES_PER_TICK

# How far a constant-velocity extrapolation is trusted at all. Half a second
# of an enemy holding exactly its current velocity is already generous: the
# scripted lunges (enemy-ai.md's Signal slide, Nora/Jack's shared lunge) do
# hold one, but an ordinary chase re-steers constantly. Every lead below is
# clamped to this, so an unreachable target (one fleeing about as fast as the
# actor can close) produces a far-away prediction that simply fails the band
# check, rather than an arbitrarily large one.
MAX_LEAD_FRAMES = 30

# Measured startup, in frames, from a B edge out of grounded idle $02 to the
# first nonzero outgoing damage +$34 (controls-and-input.md "Measured normal
# punch"), per character_id: Axel, Adam, Blaze.
PUNCH_STARTUP_FRAMES: dict[int, int] = {0: 3, 1: 3, 2: 5}
DEFAULT_PUNCH_STARTUP_FRAMES = 4

# The same measurement for the B+C chord ($322A, controls-and-input.md
# "Measured chord timing"). Adam's is nearly eight times Axel's, because his
# chord is a different move entirely ($22 -> $24, a hop). This is the single
# strongest reason this module exists: that manuscript's own conclusion is
# that "a caller that presses B+C once the target is already in range arms
# the hit after the target has walked through the box -- early for Axel,
# hopelessly early for Adam".
REAR_ATTACK_STARTUP_FRAMES: dict[int, int] = {0: 3, 1: 21, 2: 7}
DEFAULT_REAR_ATTACK_STARTUP_FRAMES = 10

# Those same two tables also give each move's *damaging* span -- the punch
# stays active for 10 frames after its startup, the chord for 10/18/16 -- and
# that span is why frame 0 always stays in the sample set below rather than
# being replaced by the startup frame: a target inside the box when it was
# observed is still inside it for part of a move fired now. It is deliberately
# **not** used to extend the lead. Sweeping the whole span instead had Axel
# throwing punches at a target 74px away because it would arrive by the span's
# last frame -- which is arithmetically true, and useless: the punch animation
# locks the actor for its whole length, so it flails in place instead of
# closing the distance.

# How close two bodies can actually get. An idle player's body box (+$70) is
# X +0..+13 (controls-and-input.md), and an enemy's is about the same width,
# so an approach stops at roughly this separation -- the ROM resolves the
# contact there rather than letting one walk through the other. Used to clamp
# a prediction, never to measure a reach.
BODY_CONTACT_GAP_X = 13

# Jump-kick launch (controls-and-input.md "Jump press and crouch" /
# "Launch"): $1FC0 holds action $10 for a fixed 5-frame crouch (jump anim
# bank frame-0 duration) before $384E sets X velocity to +-3.0 px/frame when
# a direction is held. Free flight carries that velocity unchanged unless
# air steer is applied, so the horizontal part of a kick is a constant-speed
# approach and the gap closes at exactly this rate.
JUMP_CROUCH_FRAMES = 5
JUMP_LAUNCH_SPEED_X = 3.0

# Ground walk speed, px per frame, read out of the ROM's own per-character
# walk-speed tables at $3670 (Axel) / $3706 (Adam) / $379C (Blaze) -- the
# tables $3614 loads through the character id at +$50, indexed by the action
# with its facing bit cleared, one signed byte for X and the next for lane,
# each scaled by /16 (the routine sign-extends the byte, swaps it into the
# high word and asr.l #4, i.e. byte * $1000 in 16.16). Entry $06 is the
# straight horizontal walk; $08/$0C are the diagonals and $0A/$0E the
# verticals, which is why the lane figures below are smaller. The jump rows
# are zero, matching the manuscript's "walk momentum does not carry into a
# jump".
#
# Not currently in any manuscript -- extracted here from the ROM directly.
WALK_SPEED_X: dict[int, float] = {0: 3.0, 1: 2.5, 2: 3.25}
WALK_SPEED_LANE: dict[int, float] = {0: 2.375, 1: 1.5, 2: 1.625}
# Adam's, the slowest: an unknown character must never be assumed to close
# faster than it can, which would predict an intercept that never happens.
DEFAULT_WALK_SPEED_X = 2.5

# Thrown weapon horizontal speed, px per frame (weapons-range-and-damage.md
# section 4 "Geometry: pickup, throw spawn, speeds", corroborated by
# items-and-weapons.md's own +$1C table). A knife crosses the screen in a
# handful of frames; pepper spray is slow enough that a walking target moves
# a real distance during the flight.
THROWN_WEAPON_SPEED_X: dict[int, float] = {0x08: 16.0, 0x0C: 6.0}
DEFAULT_THROWN_WEAPON_SPEED_X = 6.0


def frames_for_ticks(ticks: float) -> int:
    """AI poll ticks -> 60 Hz game frames (the unit everything here uses)."""

    return int(round(ticks * FRAMES_PER_TICK))


def punch_startup_frames(character_id: int | None) -> int:
    if character_id is None:
        return DEFAULT_PUNCH_STARTUP_FRAMES
    return PUNCH_STARTUP_FRAMES.get(character_id, DEFAULT_PUNCH_STARTUP_FRAMES)


def rear_attack_startup_frames(character_id: int | None) -> int:
    if character_id is None:
        return DEFAULT_REAR_ATTACK_STARTUP_FRAMES
    return REAR_ATTACK_STARTUP_FRAMES.get(character_id, DEFAULT_REAR_ATTACK_STARTUP_FRAMES)


def walk_speed_x(character_id: int | None) -> float:
    if character_id is None:
        return DEFAULT_WALK_SPEED_X
    return WALK_SPEED_X.get(character_id, DEFAULT_WALK_SPEED_X)


def thrown_weapon_speed_x(weapon_type: int) -> float:
    return THROWN_WEAPON_SPEED_X.get(weapon_type, DEFAULT_THROWN_WEAPON_SPEED_X)


def enemy_projected(enemy: Enemy, frames: int) -> Enemy:
    """``enemy``, ``frames`` ahead, as a token the band checks can consume.

    A thin wrapper over ``Enemy.predict_position_after_n_frames``: the
    prediction itself belongs to the enemy (it is its own velocity), while
    rebuilding a token at those coordinates -- so ``reach.py``'s geometry can
    be reused unchanged against a future position -- belongs here. A
    stationary enemy, and every ``Boss``, projects to itself.
    """

    world_x, world_y = enemy.predict_position_after_n_frames(frames)
    return replace(enemy, world_x=world_x, world_y=world_y)


def intercept_frames(
    actor: PlayableCharacter,
    enemy: Enemy,
    *,
    approach_speed: float,
    gap_closed: float = 0.0,
) -> int:
    """Frames for something leaving ``actor`` at ``approach_speed`` px/frame
    to cover the X gap to ``enemy``, given the enemy's own X velocity.

    The classic one-dimensional pursuit: the gap shrinks at the approach
    speed *minus* however fast the enemy is moving away along the same axis
    (so a target walking in is caught sooner, one walking away later). A
    target fleeing at or above the approach speed is never caught, which is
    reported as ``MAX_LEAD_FRAMES`` rather than infinity -- the projection at
    that horizon lands far outside every band, which is the right answer
    ("that move does not reach this target") without any special case.

    ``gap_closed`` is how much of the distance the move covers for free --
    a punch does not have to travel the whole way to the enemy's centre, it
    only has to reach its own outer edge -- and is subtracted from the gap
    before the division.

    X only, deliberately. Lane (Y) has no independent approach speed to
    solve against for any of these moves: a jump freezes lane velocity at
    takeoff entirely (controls-and-input.md "There is no mid-air lane
    control"), and the lane part of the prediction is still applied, since
    ``enemy_projected`` moves both axes.
    """

    gap = abs(enemy.world_x - actor.world_x) - gap_closed
    if gap <= 0:
        return 0
    toward_actor = -1.0 if enemy.world_x > actor.world_x else 1.0
    # Positive = the enemy is closing the same gap from its side.
    enemy_closing = enemy.grunt_vel_x * toward_actor
    closing_speed = approach_speed + enemy_closing
    if closing_speed <= 0:
        return MAX_LEAD_FRAMES
    return min(MAX_LEAD_FRAMES, int(round(gap / closing_speed)))


def _clamped(frames: float) -> int:
    return max(0, min(MAX_LEAD_FRAMES, int(round(frames))))


def startup_window(startup: int) -> tuple[int, ...]:
    """The two frames a stationary move's band should be tested at.

    Frame 0 -- the position actually observed, the answer the pipeline gave
    before any of this existed -- and the frame the hit arms on, which is the
    move's own startup plus the pipeline's latency. Nothing beyond that: the
    lead a move earns is the dead time before it can hurt anything, not the
    whole span it stays dangerous for (see the note by the startup tables).
    """

    return (0, AI_LATENCY_FRAMES + startup)


def enemy_projected_without_crossing(
    actor: PlayableCharacter, enemy: Enemy, frames: int
) -> Enemy:
    """``enemy`` projected ``frames`` ahead, but never *into* ``actor``.

    Straight-line extrapolation happily walks an approaching body through the
    actor and out the other side, which no enemy ever does: two bodies stop
    at contact, and ``$AAA0`` resolves that contact (a hit, or a hold) first.
    Left unclamped it invented threats out of nothing -- an enemy 8px in front
    of Axel, walking in, predicted to 22px *behind* him, landed inside the
    rear band and promoted the slow ``RearAttack`` chord at point-blank range
    against something standing in front of him. Clamping to the actor's exact
    X was not enough either: dx=0 sits inside the degenerate zero-width front
    band Axel and Blaze have, so it produced the same chord a different way.

    An approach therefore stops at ``BODY_CONTACT_GAP_X``, and an enemy
    already closer than that is left where it is. A target moving away, or
    already past the actor, is projected normally.
    """

    projected = enemy_projected(enemy, frames)
    side = enemy.world_x - actor.world_x
    if side == 0:
        return projected
    gap = abs(side)
    limit = min(gap, BODY_CONTACT_GAP_X)
    if abs(projected.world_x - actor.world_x) >= limit and (
        (projected.world_x - actor.world_x) * side > 0
    ):
        return projected
    nearest_x = actor.world_x + (limit if side > 0 else -limit)
    return replace(projected, world_x=nearest_x)


def melee_strike_lead_frames(actor: PlayableCharacter, target: object = None) -> int:
    """``Punch`` and its held-weapon siblings: latency plus the B-button
    startup measured for this character (3/3/5 frames).

    The same figure for all four verbs on purpose -- they issue the identical
    B press and the ROM picks the move from the held weapon
    (``execute.state_machine_melee_strike``); no separate startup has been
    measured for a bat swing, a stab or a spray, so reusing the unarmed
    number is the closest available evidence, exactly as
    ``decide.could_stab_with_knife_or_bottle`` reuses the unarmed band.
    """

    return _clamped(AI_LATENCY_FRAMES + punch_startup_frames(actor.character_id))


def melee_strike_connect_frames(
    actor: PlayableCharacter, target: object = None
) -> tuple[int, ...]:
    """Now, and the frame the punch arms on: startup 3 (5 for Blaze) plus
    the poll latency, so about 10px of an ordinary walk."""

    return startup_window(punch_startup_frames(actor.character_id))


def rear_attack_connect_frames(
    actor: PlayableCharacter, target: object = None
) -> tuple[int, ...]:
    """Now, and the frame the chord arms on -- frame 3 for Axel, **21** for
    Adam. Adam's wind-up alone lets a walking target cross most of his own
    42px box, which is the case this whole module exists for."""

    return startup_window(rear_attack_startup_frames(actor.character_id))


def travelling_connect_frames(
    lead_model: Callable[..., int]
) -> Callable[..., tuple[int, ...]]:
    """Now, and the moment a travelling move arrives.

    For a kick, a grab walk-in or a thrown weapon there is no damaging span to
    sweep -- there is a journey, and the only two moments worth testing are
    the observed one and the arrival. Keeping the observed one is what makes
    the prediction purely additive.
    """

    def _frames(actor: PlayableCharacter, target: object = None) -> tuple[int, ...]:
        lead = lead_model(actor, target)
        return (0,) if lead <= 0 else (0, lead)

    return _frames


def _now_only(actor: PlayableCharacter, target: object = None) -> tuple[int, ...]:
    """Just the observed instant, for a move with nothing to predict.

    Three unrelated reasons land here, each spelled out on its own model
    below: a held body travels with the actor (``held_target_lead_frames``),
    a prop does not move at all (``static_target_lead_frames``), and a
    screen-wide special or a grab counter has no aim point in the first place
    (``no_aim_point_lead_frames``).
    """

    return (0,)


def rear_attack_lead_frames(actor: PlayableCharacter, target: object = None) -> int:
    """``RearAttack``: latency plus the measured $322A startup (3/21/7).

    Adam's 21 frames are the whole point. At an ordinary walk his target
    covers well over 40 px during his wind-up -- more than the entire depth
    of his chord box -- so aiming the chord at a *current* position is how it
    whiffs, which is precisely what that verb's own docstring describes.
    """

    return _clamped(AI_LATENCY_FRAMES + rear_attack_startup_frames(actor.character_id))


def jump_attack_lead_frames(actor: PlayableCharacter, target: object = None) -> int:
    """``JumpAttack``: the crouch, and only the crouch.

    ``$1FC0`` holds action ``$10`` for a fixed 5 frames before ``$384E`` sets
    the launch velocity, so the target keeps walking for that whole time
    after the decision is taken and the actor is still on the ground, unable
    to see it. That dead time is what this leads by.

    Deliberately *not* the flight as well. The flight's own reach is already
    what ``reach.in_jump_attack_band`` measures (the ROM's 60/69/75 px
    free-flight range), and solving the full interception there instead made
    the AI launch from over 100 px on the assumption that the target would
    keep closing for all 25 frames of crouch-plus-flight -- committed,
    airborne, and landing far short the moment it stopped.

    Airborne, even the crouch is behind the actor: only the B edge is left,
    so the lead is the pipeline's own latency.
    """

    if actor.is_airborne:
        return AI_LATENCY_FRAMES
    return AI_LATENCY_FRAMES + JUMP_CROUCH_FRAMES


def grab_lead_frames(actor: PlayableCharacter, target: object = None) -> int:
    """``GrabEnemy``: the walk-in is the move, so its travel *is* the lead.

    A hold is a contact result, not a button (``reach.GRAB_RANGE_Y``): the
    actor walks into the enemy at its own ROM walk speed and the ROM converts
    the contact. So the question this answers is "where will that enemy be
    when I get there", solved at the character's real ground speed
    (``WALK_SPEED_X``) against the enemy's own -- which also, correctly,
    reports ``MAX_LEAD_FRAMES`` for a target walking away as fast as the
    actor walks, since the walk-in would never catch it.
    """

    if not isinstance(target, Enemy):
        return AI_LATENCY_FRAMES
    travel = intercept_frames(
        actor,
        target,
        approach_speed=walk_speed_x(actor.character_id),
        gap_closed=punch_outer_x(actor.character_id),
    )
    return _clamped(AI_LATENCY_FRAMES + travel)


def _thrown_weapon_lead_frames(
    actor: PlayableCharacter, target: object, weapon_type: int
) -> int:
    """Startup plus the projectile's own flight time to the intercept point.

    The weapon leaves the hand at a fixed horizontal speed (knife 16 px per
    frame, pepper 6) and flies level, so the interception is the same
    one-dimensional solve as everything else here -- with the difference
    that pepper's 6 px/frame is slow enough for a walking target to cover a
    real distance mid-flight, which is what makes this worth computing rather
    than assuming a hit-scan.

    The release frame itself has not been measured for either weapon; the B
    press is the same input as a punch, so the punch startup is reused, and
    is small next to the flight time in any case.
    """

    if not isinstance(target, Enemy):
        return AI_LATENCY_FRAMES
    flight = intercept_frames(
        actor, target, approach_speed=thrown_weapon_speed_x(weapon_type)
    )
    return _clamped(
        AI_LATENCY_FRAMES + punch_startup_frames(actor.character_id) + flight
    )


def throw_knife_lead_frames(actor: PlayableCharacter, target: object = None) -> int:
    return _thrown_weapon_lead_frames(actor, target, 0x08)


def throw_pepper_lead_frames(actor: PlayableCharacter, target: object = None) -> int:
    return _thrown_weapon_lead_frames(actor, target, 0x0C)


def held_target_lead_frames(actor: PlayableCharacter, target: object = None) -> int:
    """Zero, and that is the kinematic answer, not a missing one.

    Every hold move (knee, suplex, throw, flip, release) acts on a body the
    ROM has locked to the actor's own position: the two move together, so
    their *relative* velocity is zero and any lead time predicts exactly the
    current relative position. There is nothing to aim at.
    """

    return 0


def static_target_lead_frames(actor: PlayableCharacter, target: object = None) -> int:
    """Zero: ``OpenBreakable``'s target is a crate/barrel/phone box.

    Props do not move, so the smash lands wherever the prop already is, and
    the approach is the actor's own travel -- steering the executor already
    does, tick by tick, against a fixed point. The prediction is the identity
    for the same reason a stationary enemy projects to itself.
    """

    return 0


def no_aim_point_lead_frames(actor: PlayableCharacter, target: object = None) -> int:
    """Zero: the move has no target position to lead at all.

    ``CallPolice`` is a scripted screen-wide sweep -- the ROM removes every
    ordinary enemy on screen regardless of where it stands -- and
    ``CounterGrab`` is a reaction to being held, resolved by input timing
    (a C edge then a B edge inside the ROM's own window) rather than by
    geometry.
    """

    return 0


# Every concrete ``Attack``, and the frames at which its band should be
# tested: the damaging window for a move that stands still, (0, lead) for one
# that travels to its target, and (0,) for one with nothing to predict.
# ``inference`` takes the union over these, so a prediction can only ever add
# an attack option -- never delete the one the observed position already
# offered. Totality is enforced by ``tests/ai/test_kinematics.py``: a new
# attack verb without an entry fails the suite, so "which attacks reason
# about time" can never drift away from "all of them".
ATTACK_CONNECT_FRAMES: dict[type[Attack], Callable[..., tuple[int, ...]]] = {
    Punch: melee_strike_connect_frames,
    SwingBatOrPipe: melee_strike_connect_frames,
    StabWithKnifeOrBottle: melee_strike_connect_frames,
    SprayPepper: melee_strike_connect_frames,
    RearAttack: rear_attack_connect_frames,
    JumpAttack: travelling_connect_frames(jump_attack_lead_frames),
    GrabEnemy: travelling_connect_frames(grab_lead_frames),
    ThrowKnife: travelling_connect_frames(throw_knife_lead_frames),
    ThrowPepper: travelling_connect_frames(throw_pepper_lead_frames),
    Supplex: _now_only,
    AttackHeldEnemy: _now_only,
    ThrowHeldEnemy: _now_only,
    FlipHold: _now_only,
    ReleaseGrab: _now_only,
    OpenBreakable: _now_only,
    CallPolice: _now_only,
    CounterGrab: _now_only,
}


def connect_frames(
    verb_cls: type[Attack], actor: PlayableCharacter, target: object = None
) -> tuple[int, ...]:
    """Every frame at which ``verb_cls`` could connect, 0 always included.

    ``inference.check_for_targets_in_reach`` tests its band at each of these
    and takes the union; ``execute``/``decide`` use ``lead_frames`` below when
    they need the single moment the move is aimed at.
    """

    model = ATTACK_CONNECT_FRAMES.get(verb_cls)
    if model is None:
        return (0, AI_LATENCY_FRAMES)
    return model(actor, target)


def lead_frames(
    verb_cls: type[Attack], actor: PlayableCharacter, target: object = None
) -> int:
    """The single frame ``verb_cls`` is *aimed* at: the last it can connect on.

    Facing and steering need one point, not a window (``execute._aim_point``,
    ``decide.thrown_weapon_impact_point``), and the far end of the window is
    the conservative choice for both -- it is where the move is still going
    when everything earlier has missed.
    """

    return max(connect_frames(verb_cls, actor, target))


def target_at_impact(
    verb_cls: type[Attack], actor: PlayableCharacter, enemy: Enemy
) -> Enemy:
    """``enemy`` where ``verb_cls`` would actually meet it, for ``actor``."""

    return enemy_projected(enemy, lead_frames(verb_cls, actor, enemy))
