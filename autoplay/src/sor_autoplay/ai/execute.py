"""``execute_verb`` — dispatch the surviving ``Verb`` to controller input.

Per ``AI.md``: each handler steers the controller only as much as necessary
and returns immediately — never blocks/sleeps waiting for the verb to
play out.

CRITICAL button mapping (original scheme): Attack/Punch = physical B (0x0020),
Police special = physical A (0x0010), Jump = physical C (0x0040).
"""

from __future__ import annotations

import math
from contextvars import ContextVar

from .pathfind import Path, Point, PointGoal
from .tokens import (
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
from .tokens import (
    Myself,
    Partner,
    PUNCH_RANGE_Y,
    punch_inner_x,
    punch_outer_x,
    punch_usable_inner_x,
)
from .tokens import Antonio, Enemy, GrabReason, Souther
from .tokens import CameraRange, Stage
from .tokens import Breakable, Pit, Projectile
from .tokens import Pickup, Weapon
from .tokens import CallPolice
from .tokens import (
    NAME_ALPHABET_SIZE,
    NAME_LETTER_A,
    NAME_LETTER_I,
    HandleContinueMenu,
    HandleMrXDialog,
    InContinueMenu,
    InMrXDialog,
)
from .tokens import Context, Verb, find, find_all
from .tokens import (
    DodgeAntonioKick,
    DodgeSoutherSlash,
    ProjectileSidestep,
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from .gamepad import VirtualGamepad
from . import kinematics
from . import navigation as nav
from .decide import (
    BREAKABLE_PUNCH_X,
    BREAKABLE_APPROACH_Y,
    breakable_smash_outer_x,
    in_smash_range,
)
from .reach import (
    ANTONIO_KICK_LANE_BREAK,
    PIT_AVOID_MARGIN,
    REACH_SAFETY_MARGIN,
    SOUTHER_SLASH_DIST_MIN,
    SOUTHER_SLASH_LANE,
    enemy_behind_actor,
    enemy_lane_covers,
    grab_reasons,
    in_camera,
    in_playable_lane,
    incoming_melee_targets,
    live_enemies,
    pit_endangers,
)
from .. import prop_solids
from ..phases import is_dangerous, is_punishable
from ..world_map import LANE_Y_MIN

UP_MASK = 0x0001
DOWN_MASK = 0x0002
LEFT_MASK = 0x0004
RIGHT_MASK = 0x0008
PUNCH_MASK = 0x0020  # physical B
CALL_POLICE_MASK = 0x0010  # physical A
JUMP_MASK = 0x0040  # physical C
START_MASK = 0x0080
# $57D2 confirms a high-score letter on +$55 bits 5+6 (logical C / A after
# remap -- physical C / A in scheme 0). Bit 4 is physical B, the *back*
# key: on slot 0 it is a no-op, so pressing B to "type A" left the AI
# stuck on the first initial forever. Yes/No still accepts any $F0 face
# bit ($52AE); name-entry does not.
NAME_CONFIRM_MASK = JUMP_MASK
PUNCH_FRAMES = 4
CALL_POLICE_FRAMES = 4
DIALOG_FRAMES = 4
SUPPLEX_FRAMES = 4
THROW_KNIFE_FRAMES = 4
THROW_PEPPER_FRAMES = 4
REAR_ATTACK_FRAMES = 4
COUNTER_FRAMES = 3
TECH_RECOVER_FRAMES = 3
JUMP_ATTACK_LAUNCH_FRAMES = 3
JUMP_ATTACK_KICK_FRAMES = 4
HOLD_FRAMES = 4

# Per-axis deadband: stop steering once the target is within roughly one
# tick's worth of travel.
#
# The controller is a bang-bang actuator sampled far more slowly than the game
# runs. Ground walk is a couple of px per frame and the default poll is 33 ms
# (~2 frames at 60 Hz), so an exact-coordinate target is never landed on: the
# actor steps past it, the next tick sees the residual flip sign and commands
# the opposite direction, and it steps back. Live symptom: constant left/right
# shaking -- most visible while the AI is mainly travelling *vertically*,
# where the X residual is all that is left oscillating and the actor visibly
# vibrates instead of walking cleanly up or down the lane.
#
# X is the wider band because horizontal walk is the faster axis. Both stay
# well inside every arrival test that follows a walk (PICKUP_RANGE_*,
# BREAKABLE_PUNCH_X, punch_inner_x), so nothing that used to be reachable
# stops being reached -- the actor just stops hunting for a pixel it cannot
# stand on.
MOVE_DEADBAND_X = 5
MOVE_DEADBAND_Y = 3

# How far past MOVE_DEADBAND_X to aim a pure facing-correction nudge for
# OpenBreakable (see state_machine_open_breakable's wrong-facing branch).
# Small versus the punch band's own width (BREAKABLE_PUNCH_X and friends),
# so a body already in smash range but facing away steps just enough to
# clear the deadband and flip facing without walking back out of range --
# unlike _walk_to_breakable_target's stop point, which is anchored near the
# band's *outer* edge for the far-approach case and can be on the far side
# of the actor's current, already-adequate position.
# Must clear the goal-coverage test the router uses to judge "arrived": a
# PointGoal is satisfied once the actor's own body rect (grown by its
# tolerance) covers the point, and a small nudge is trivially already
# covered by a body that is itself NOMINAL_BODY_W/H (16x16) wide -- measured
# directly: an 8px nudge with a 5px tolerance read "already there" and
# produced zero movement, freezing the actor exactly like the one-frame
# press this replaced. 16 clears NOMINAL_BODY_W's own half-width (8) plus
# MOVE_DEADBAND_X (5) with margin, and is still small next to the punch
# band's own width (BREAKABLE_PUNCH_X and friends).
BREAKABLE_FACE_NUDGE_X = 16

# Hysteresis around dx == 0 for "which side of the target" decisions --
# facing (_face_toward_mask) and the near/far pick inside
# _walk_to_near_enemy_target. Both used to re-derive their answer from a raw
# sign test on actor.world_x vs the target every tick. Once the actor closes
# to melee range the two bodies sit almost exactly on top of each other, and
# a couple of px of ordinary walk/attack jitter flips that sign on
# essentially every tick. Because holding the resulting direction is what
# sets facing on the *next* tick, an un-margined flip there became a
# self-sustaining oscillation: cross -> command the opposite side -> facing
# flips -> now reads as crossed the other way -> command back... Live symptom:
# the AI visibly flipping left/right against a single, stationary-ish enemy,
# not just when switching targets. Comfortably above MOVE_DEADBAND_X (so
# residual walk-deadband jitter can never trip it) and well inside every
# character's stop_dx (32px..56px, see punch_inner_x/punch_outer_x), so the
# actual stopping distance from an enemy is unaffected.
DIRECTION_HYSTERESIS_X = 10

PICKUP_RANGE_X = 18
PICKUP_RANGE_Y = 14
LANE_EDGE_MARGIN = 6
# How far past a prop's push-back rectangle the straight-line dodge aims,
# and how close to it a lane has to be for the prop to count as in the way.
#
# A *clearance*, measured from the real edge -- it used to be a margin around
# the prop's origin instead, which only worked while the two were roughly the
# same thing. They are not: prop_solids' rectangles reach up to 28px behind
# an origin and only ever 4px in front of it. Small for the same reason
# PIT_DODGE_OVERSHOOT is small on the other side of that comparison -- it
# only has to exceed MOVE_DEADBAND_Y so the aim point cannot sit inside the
# deadband of a from_y that has not actually cleared the prop yet -- and
# small matters here: stage 5 stacks two rows of props with a 16px corridor
# between them, and any clearance wide enough to overshoot that corridor aims
# the dodge straight into the next prop down.
BREAKABLE_AVOID_Y = MOVE_DEADBAND_Y + 5
# Pit clearance (reach.PIT_AVOID_MARGIN) is shared with
# inference.check_for_safe_spots, which must reject the same ground this
# steers around.
#
# How far past PIT_AVOID_MARGIN's own boundary the pit dodge's Y target aims
# -- must exceed MOVE_DEADBAND_Y, or the target can land within the deadband
# of a from_y that has not actually reached the boundary yet, zeroing the Y
# mask bits while X is still frozen ("not cleared"): an empty mask, i.e. the
# actor freezes a few pixels short of escaping. See the dodge loop's own
# comment for the live-diagnosed deadlock this prevents.
PIT_DODGE_OVERSHOOT = MOVE_DEADBAND_Y + 5

# Stop just inside punch_outer_x — never walk onto the enemy.
WALK_TO_ENEMY_STOP_BUFFER = 4
# While still approaching a dangerous (ATTACKING/CHARGE) enemy and already
# near its exact lane, sidestep by this much instead of closing distance
# straight down its line of attack.
WALK_TO_ENEMY_LANE_SAFETY_Y = PUNCH_RANGE_Y + 16
# Below this much lane separation the actor has no meaningful "side" of the
# enemy to be on -- the raw compare is walk jitter -- so _approach_lane_y
# stops reading it and picks the side with room instead.
LANE_SIDE_DEADBAND_Y = 6
# The offset an Antonio approach aims for, rather than the generic sidestep
# above. The routed goal is a *region* with PUNCH_RANGE_Y of lane slack, so
# an aim of WALK_TO_ENEMY_LANE_SAFETY_Y is satisfied by arriving 16px out --
# which is exactly his `$16EAE` kick gate, satisfied. Adding the slack back
# puts the nearest acceptable arrival at 28px, clear of both his `$10` kick
# and `$14` dash windows with margin. Simulated over the real executor: 13px
# of arrival offset before, 28 after.
ANTONIO_APPROACH_LANE_Y = WALK_TO_ENEMY_LANE_SAFETY_Y + PUNCH_RANGE_Y
# The same construction for Souther, off his own gate rather than Antonio's.
# `$15EDA (souther_state1_active_combat)` refuses the slash whenever
# `+$52 >= $1C` (28px of lane), so 28 is the number the *arrival* has to
# clear, and the routed goal's PUNCH_RANGE_Y of lane slack has to be added on
# top of it for the nearest acceptable arrival to be 28 rather than 16.
#
# Paired with `_souther_pocket_stop_dx` (16px, inside the `$18` inner abort)
# this is ai-analysis/enemy-ai.md's "uncommittable corridor": the lane gate
# is unsatisfied for the whole approach, the inner abort is unsatisfied from
# the moment the lane is given up, and the two overlap, so there is no
# instant at which `$15EDA` can commit. Antonio's number happens to be the
# same 40 without the margin below; the two are written separately because
# they are derived from two different gates and only one of them is 28px
# wide -- which is exactly why only one of them needed the margin.
#
# `_approach_lane_y` stops actively widening the lane once
# `dy >= hold_offset - PUNCH_RANGE_Y` ("close enough, a further nudge is only
# jitter") -- and for Antonio that lands on WALK_TO_ENEMY_LANE_SAFETY_Y (28),
# a generic buffer that happens to sit 8-12px clear of his real 16/20px
# gates. For Souther, without the margin, the identical subtraction landed
# on SOUTHER_SLASH_LANE (28) *exactly* -- his own real gate, zero clearance.
# Measured live: the approach stopped adjusting lane the moment dy reached
# 28, and Souther, closing lane at 4px/tick while the actor holds still, was
# in his committed claw two ticks later at dy=21 -- `DodgeSoutherSlash` fired
# the same tick as the commit and had no time to matter. REACH_SAFETY_MARGIN
# is the cushion already used elsewhere in this file to deny his gates
# rather than sit on them (`_souther_pocket_stop_dx`); it belongs here for
# the identical reason.
SOUTHER_APPROACH_LANE_Y = SOUTHER_SLASH_LANE + PUNCH_RANGE_Y + REACH_SAFETY_MARGIN
# A Breakable is itself a solid obstacle -- walking straight to its exact
# (world_x, world_y) means walking into it from whatever angle happens to be
# a straight line, which can mean approaching from directly above/below and
# getting stuck against its collision. Stop just inside smash range on
# whichever side the actor already occupies, at the same Y, instead.
#
# Must exceed MOVE_DEADBAND_X: the deadband stops the walk-in's RIGHT/LEFT
# hold as soon as the actor is within MOVE_DEADBAND_X of the stop point --
# not only once it has actually reached it -- so the real resting distance
# from the prop can be up to (BREAKABLE_PUNCH_X - BREAKABLE_STOP_BUFFER) +
# MOVE_DEADBAND_X. With the old buffer of 4 (< MOVE_DEADBAND_X's 5) that
# worst case landed at 37px, one past BREAKABLE_PUNCH_X's 36 -- in_smash_range
# then stayed false forever against a target that, unlike an enemy, never
# moves to close the last pixel itself: the actor arrived and never threw a
# punch. Live-diagnosed; keep this comfortably above MOVE_DEADBAND_X.
BREAKABLE_STOP_BUFFER = 12
# How far outside a prop's push-back rectangle the straight-line approach
# aims when the stop buffer alone would put the stop point inside it. Past
# MOVE_DEADBAND_X, so the deadband cannot let the walk settle on the wall
# itself and spend the approach being pushed back out of it.
BREAKABLE_WALL_GAP_X = MOVE_DEADBAND_X + 1
# Slack around the prop's blocking X column so the around-path starts
# before the exact body edge, and so a one-pixel walk jitter on that edge
# cannot flip between "still in the column, hold Y" and "clear, converge Y".
BREAKABLE_AROUND_SLACK_X = MOVE_DEADBAND_X


def press_no_button(gamepad: VirtualGamepad) -> None:
    gamepad.release()


def _press(gamepad: VirtualGamepad, mask: int, *, frames: int) -> None:
    """Issue a pure button press, dropping any stale directional hold first.

    ``hold_buttons`` is a *sticky* latch (gamepad.py's module docstring):
    whatever direction the previous tick's walk verb held stays held
    until something changes it, and ``SharedGamepadState.press`` deliberately
    re-arms it after the press. So a walk tick followed by an attack tick
    left the actor still walking through the strike -- past the enemy and out
    of its own punch band, or straight over the pickup it had just pressed B
    to collect. A press-only handler owns no movement, so it must clear that
    hold. ``VirtualGamepad.hold`` short-circuits when the mask is unchanged,
    making this free on every tick except the walk→press transition.
    """

    gamepad.hold(0)
    gamepad.press(mask, frames=frames)


def _hold_steered(gamepad: VirtualGamepad, mask: int) -> None:
    """Hold ``mask``, routing its left/right bits through the gamepad's
    virtual X axis first.

    Every walk-verb handler still decides a direction the same way it always
    did (deadbands, hysteresis, prop dodges); this is only the last step
    before that decision reaches the controller. ``gamepad.steer_x`` reports
    a side only once it has been requested for ``AXIS_RAMP_TICKS``
    consecutive ticks, so a single-tick flip in the computed mask no longer
    flips the physical D-pad -- it just nudges the axis one step and, most of
    the time, gets reported back as still centered. Up/Down and every other
    bit pass through unchanged: the reported oscillation was left/right only.
    """

    if mask & RIGHT_MASK:
        x_direction = 1
    elif mask & LEFT_MASK:
        x_direction = -1
    else:
        x_direction = 0
    steered = gamepad.steer_x(x_direction)
    mask &= ~(LEFT_MASK | RIGHT_MASK)
    if steered > 0:
        mask |= RIGHT_MASK
    elif steered < 0:
        mask |= LEFT_MASK
    gamepad.hold(mask)


def _find_actor(context: Context, slot: str) -> Myself | Partner | None:
    for actor in (find(context, Myself), find(context, Partner)):
        if actor is not None and actor.slot == slot:
            return actor
    return None


def _lane_bounds(context: Context) -> tuple[float, float]:
    camera = find(context, CameraRange)
    lo = float(LANE_Y_MIN) + LANE_EDGE_MARGIN
    hi = (float(camera.bottom) if camera is not None else 0x70) - LANE_EDGE_MARGIN
    if hi < lo:
        return float(LANE_Y_MIN), float(camera.bottom if camera else 0x70)
    return lo, hi


def _clamp_target_y(context: Context, y: int) -> int:
    lo, hi = _lane_bounds(context)
    return int(max(lo, min(hi, y)))


def _pit_dodge_target_y(context: Context, pit: Pit, from_y: int) -> int:
    """Which side of ``pit`` to clear to, as an absolute lane coordinate.

    The dodge target must clear the danger boundary by more than
    MOVE_DEADBAND_Y, not land exactly on it: live-diagnosed deadlock --
    aiming at danger_top/danger_bottom itself means that once ``from_y``
    drifts to within MOVE_DEADBAND_Y of that same point, the Y mask bits go
    quiet (deadband) *while X is still frozen and "not cleared" is still
    true* (the boundary is inclusive on both checks), so the whole mask goes
    to 0 and the actor freezes a few pixels short of actually escaping.
    ``PIT_DODGE_OVERSHOOT`` pushes the aim point far enough past the boundary
    that "not cleared" and "within the deadband of the target" can never both
    hold at once.

    **Which** side is picked from the pit's own danger edges, never from the
    lane midpoint. Reading it off ``from_y < (lo + hi) / 2`` -- as this used
    to -- is a feedback loop of exactly the kind
    ``_walk_to_near_enemy_target`` and ``_walk_to_breakable_target`` already
    document, and a permanent one here because the pit dodge *freezes X*:
    nothing else is moving to break the tie. The lane midpoint has nothing to
    do with the pit and routinely falls **inside** its danger band, and the
    old rule steered the actor *toward* that midpoint (upper half aimed
    below, lower half aimed above) -- so the actor crossed it, the pick
    flipped, and it crossed back. Reproduced on the tick harness with a
    96x40 pit at lane 40..80 (danger 32..88, lane midpoint 57, inside it):
    the actor stopped dead at the pit's edge and alternated UP/DOWN between
    y=56 and y=60 forever, X frozen, never advancing the stage.

    The nearer danger edge is stable where the lane midpoint is not, because
    it is *self-reinforcing*: the flip point is the band's own centre and the
    chosen direction always moves the actor **away** from it, so a pick can
    never undo itself. It is also the shortest way out.

    A side only counts when its aim point survives the lane clamp still clear
    of the danger band; otherwise ``_clamp_target_y`` drags it back inside,
    the Y bits go quiet while X is frozen, and the mask collapses to 0 --
    which for ``state_machine_walk_to_advance_stage`` is worse than useless,
    since its ``or mask`` fallback then commands the raw lateral direction
    straight into the pit. When neither side clears, the roomier lane edge is
    the best available answer (an impassable pit: press against the edge and
    stall rather than walk in), and it is still picked from the pit and the
    lane alone, so it cannot oscillate either.
    """

    lo, hi = _lane_bounds(context)
    pit_bottom = pit.lane_y + pit.height
    danger_top = pit.lane_y - PIT_AVOID_MARGIN
    danger_bottom = pit_bottom + PIT_AVOID_MARGIN
    above = danger_top - PIT_DODGE_OVERSHOOT
    below = danger_bottom + PIT_DODGE_OVERSHOOT

    can_go_up = above >= lo
    can_go_down = below <= hi
    if can_go_up and can_go_down:
        return above if (from_y - danger_top) <= (danger_bottom - from_y) else below
    if can_go_up:
        return above
    if can_go_down:
        return below
    return lo if (danger_top - lo) >= (hi - danger_bottom) else hi


def _breakable_block_x(prop: Breakable) -> tuple[int, int]:
    """X span the actor's own position cannot be inside.

    The ROM's per-type push-back rectangle (``prop_solids``), not the prop's
    animation body box: the two are different rectangles, and it is this one
    the game tests the actor's position against. Origin-space is also what
    the caller wants -- ``_walk_to_breakable_target`` compares
    ``actor.world_x`` to it directly.
    """

    solid = prop_solids.solid_box(prop.type_id, prop.world_x, prop.world_y)
    return solid.x0, solid.x1


def _clamp_mask_to_lane(context: Context, from_y: int, mask: int) -> int:
    """Never hold into the lane clamp."""

    lo, hi = _lane_bounds(context)
    if from_y >= hi:
        mask &= ~DOWN_MASK
    if from_y <= lo:
        mask &= ~UP_MASK
    return mask


def _clamp_mask_to_camera(context: Context, from_x: int, mask: int) -> int:
    """Never hold into the camera's walk clamp.

    ``$43AA`` keeps the player in ``camera_x + $20 .. + $120``. WalkToAdvance
    Stage's 40px lookahead sits *past* that edge, so the router keeps asking
    for RIGHT (or LEFT on stage 8) while the ROM undoes every step: the
    first-level wave gate at world x=1504, with a sidewalk trash can in
    frame that is not even an object. Holding the blocked direction does
    nothing and looks like the actor is stuck on that scenery.
    """

    camera = find(context, CameraRange)
    if camera is None:
        return mask
    if from_x >= camera.right - MOVE_DEADBAND_X:
        mask &= ~RIGHT_MASK
    if from_x <= camera.left + MOVE_DEADBAND_X:
        mask &= ~LEFT_MASK
    return mask


def _clamp_mask(context: Context, from_x: int, from_y: int, mask: int) -> int:
    return _clamp_mask_to_camera(context, from_x, _clamp_mask_to_lane(context, from_y, mask))


# The HUD wants to draw the planner's actual output, but every routed
# handler is reached through _HANDLERS' generic (verb, context, gamepad)
# dispatch, which cannot carry an extra parameter without widening every
# other handler's signature to match. A ContextVar sidesteps that: only
# execute_tick (the one entry point that already knows whether a caller
# wants a trace) sets it, only _routed_mask (the one place a route is
# actually produced) reads it, and nothing in between has to know it exists.
# Safe without locking because a tick runs synchronously start to finish on
# one thread (app.py's single poll thread runs P1 then P2 in turn).
_ROUTE_TRACE: ContextVar[dict[str, Path] | None] = ContextVar("_ROUTE_TRACE", default=None)


def _routed_mask(
    context: Context,
    actor: Myself | Partner,
    goal,
    *,
    solids,
    dangers,
    enough_contact: float = 0.0,
    maximize_contact: bool = False,
    fallback,
) -> int:
    """First vector of a planned route, or ``fallback()`` when there is none.

    Only the **first** vector, and the whole route is thrown away and rebuilt
    next tick. That looks wasteful and is not: the world moves under a plan
    -- enemies walk, crates break, phases flip -- so a plan kept across ticks
    is a plan that is quietly wrong, while a search of this playfield costs
    well under a millisecond against a 33 ms tick.

    An empty mask means one of two very different things, and they must not
    be confused. Either the goal is already satisfied -- stand still, which
    is the answer -- or the actor is boxed in on every side and the search
    produced nothing at all. Only the second falls back.
    """

    path = nav.plan_route(
        context,
        actor,
        goal,
        solids=solids,
        dangers=dangers,
        enough_contact=enough_contact,
        maximize_contact=maximize_contact,
    )
    sink = _ROUTE_TRACE.get()
    if sink is not None:
        sink[actor.slot] = path
    mask = nav.first_vector_mask(path)
    if not mask and not goal.is_reached(nav.body_rect(actor)):
        mask = fallback()
    return _clamp_mask(context, actor.world_x, actor.world_y, mask)


def _movement_mask(
    context: Context,
    from_x: int,
    from_y: int,
    to_x: int,
    to_y: int,
    *,
    ignore_slots: frozenset[str] = frozenset(),
) -> int:
    """Build a D-pad mask, clamped to lane bounds and steered around props."""

    to_y = _clamp_target_y(context, to_y)
    camera = find(context, CameraRange)
    # Nudge path around intact breakables sitting on the straight-line route.
    for prop in find_all(context, Breakable):
        # The prop we are walking *to* smash (OpenBreakable) is not an
        # obstacle on the way to something else -- it is the destination.
        # Dodging it here pushes Y off the smash lane while the walk-in
        # closes X, so the actor arrives beside the crate a full
        # BREAKABLE_AVOID_Y off the punch band and never strikes.
        if prop.slot in ignore_slots:
            continue
        # world_map tracks entities up to two screens beyond each camera edge
        # (hunt-target lookahead), far past what's actually walkable right
        # now. Without this filter, a breakable anywhere in that huge tracked
        # radius could trip the dodge below on nearly every walk verb —
        # and since it always steers toward smaller Y ("up") whenever the
        # actor is in the lane's lower half (the common case), that made the
        # AI drift up constantly for reasons that had nothing to do with
        # what was actually on screen.
        if camera is not None and not (
            camera.left <= prop.world_x <= camera.right
            and camera.top <= prop.world_y <= camera.bottom
        ):
            continue
        # Prop between us and target on X, same lane band.
        between = (from_x < prop.world_x < to_x) or (to_x < prop.world_x < from_x)
        if not between:
            continue
        # The band to steer out of is the prop's own push-back rectangle
        # (prop_solids), not a fixed margin around its origin. The ROM's
        # rectangles are not centred on the origin -- a round-5 prop's runs
        # from 20px behind it to 4px in front -- so a symmetric margin aims
        # the dodge at a lane that is still solid as often as not. On stage
        # 5's stacked fence that meant dodging one prop by walking into the
        # one below it.
        solid = prop_solids.solid_box(prop.type_id, prop.world_x, prop.world_y)
        top = solid.y0 - BREAKABLE_AVOID_Y
        bottom = solid.y1 + BREAKABLE_AVOID_Y
        if not (top <= from_y <= bottom or top <= to_y <= bottom):
            continue
        if abs(prop.world_x - from_x) > abs(to_x - from_x):
            continue
        # Step vertically around the prop (prefer away from lane edge).
        lo, hi = _lane_bounds(context)
        if from_y < (lo + hi) / 2:
            to_y = _clamp_target_y(context, bottom)
        else:
            to_y = _clamp_target_y(context, top)

    # Nudge path around floor pits — same camera-filtered, path-intersecting
    # dodge idiom as the breakable loop above, but keyed off the pit's own
    # AABB (world_x/lane_y/width/height) instead of a fixed point margin,
    # since a pit's footprint is directly observed rather than assumed.
    #
    # A pit is a rectangle, not a line, so nudging to_y while still closing
    # to_x at the same time (the way the breakable dodge above does) is not
    # enough to clear it: the mask holds both axes at once, which walks the
    # actor diagonally, and a wide/tall enough pit -- or a close enough
    # approach -- means the diagonal still cuts through the footprint before
    # Y finishes clearing it. Live-diagnosed: the AI kept falling in.
    # Instead, X is held at from_x (frozen -- no L/R bit at all) for as long
    # as the actor's *current* Y still sits inside the pit's own band; only
    # once from_y has actually cleared it (not merely been asked to) does X
    # resume toward the original to_x. Recomputed fresh every tick from the
    # live position, so this self-corrects if the actor drifts back in.
    for pit in find_all(context, Pit):
        pit_right = pit.world_x + pit.width
        pit_bottom = pit.lane_y + pit.height
        pit_center_x = (pit.world_x + pit_right) / 2
        pit_center_y = (pit.lane_y + pit_bottom) / 2
        if camera is not None and not (
            camera.left <= pit_center_x <= camera.right
            and camera.top <= pit_center_y <= camera.bottom
        ):
            continue
        between = (from_x < pit_center_x < to_x) or (to_x < pit_center_x < from_x)
        if not between:
            continue
        if abs(pit_center_x - from_x) > abs(to_x - from_x):
            continue
        danger_top = pit.lane_y - PIT_AVOID_MARGIN
        danger_bottom = pit_bottom + PIT_AVOID_MARGIN
        if from_y < danger_top or from_y > danger_bottom:
            # Already clear vertically -- safe to keep closing X this tick.
            #
            # Strict, because ``reach.pit_endangers``' own band is inclusive
            # on both edges: with `<=`/`>=` here the two disagreed about the
            # single boundary pixel, and that one pixel was enough to
            # deadlock. The escape stops the moment this says "clear", so the
            # actor settled exactly on ``danger_top`` -- where
            # ``_movement_mask`` let X run while ``_pit_escape_mask`` still
            # read ``pit_endangers`` as true and overrode with a lateral
            # shove. Reproduced on the tick harness: having cleared a 96px
            # pit's band and walked across it, the actor reached the pit's
            # exact centre X and was pushed back LEFT, then stalled. Both
            # sides must mean the same thing by "clear of this pit on Y".
            continue
        to_y = _clamp_target_y(context, _pit_dodge_target_y(context, pit, from_y))
        to_x = from_x

    mask = 0
    if to_x - from_x > MOVE_DEADBAND_X:
        mask |= RIGHT_MASK
    elif from_x - to_x > MOVE_DEADBAND_X:
        mask |= LEFT_MASK
    # Smaller world_y = back of stage = "up".
    if to_y - from_y > MOVE_DEADBAND_Y:
        mask |= DOWN_MASK
    elif from_y - to_y > MOVE_DEADBAND_Y:
        mask |= UP_MASK

    return _clamp_mask(context, from_x, from_y, mask)


def _face_toward_mask(actor: Myself | Partner, target_x: int) -> int:
    dx = target_x - actor.world_x
    if dx < -DIRECTION_HYSTERESIS_X:
        return LEFT_MASK
    if dx > DIRECTION_HYSTERESIS_X:
        return RIGHT_MASK
    return 0


def _face_prop_mask(actor: Myself | Partner, prop: Breakable, context: Context) -> int:
    """Which way to turn before hitting ``prop`` -- never "stay as you are".

    ``_face_toward_mask`` answers 0 inside ``DIRECTION_HYSTERESIS_X``, and it
    is right to for an enemy: the two bodies end up almost on top of each
    other, ordinary jitter flips the raw sign every tick, and holding the
    resulting direction is what sets facing, so the flip feeds itself. None
    of that reasoning survives a target that cannot move. What is left is the
    failure mode: measured live, the actor stood 10px from a round-5 prop --
    exactly the hysteresis width -- facing away from it, threw 2,300 punches
    into empty air over 76 seconds and never turned round, because every one
    of them asked for no direction at all.

    Ten pixels away *is* hitting distance: the same run broke the identical
    prop from 11px while facing it. So a prop gets the raw sign, and the
    dead-centre case gets the fixed, non-input-derived tie-break
    ``_walk_to_breakable_target`` already uses for the same reason -- the
    stage's own progress direction, which cannot oscillate.
    """

    dx = prop.world_x - actor.world_x
    if dx > 0:
        return RIGHT_MASK
    if dx < 0:
        return LEFT_MASK
    stage = find(context, Stage)
    direction = stage.direction if stage is not None else "right"
    return LEFT_MASK if direction == "left" else RIGHT_MASK


def _facing_prop(actor: Myself | Partner, prop: Breakable) -> bool:
    """Whether a forward strike from here would actually be aimed at ``prop``.

    ``in_smash_range`` is origin-to-origin and ignores facing, so a body
    standing in range but looking the other way still reads as "punch now".
    The ROM samples facing at the start of the attack, and B plus a turn on
    the very same press is sampled as the *current* (pre-turn) facing -- a
    committed miss. Measured live: Blaze at dx=13 from a type-$11 booth,
    facing away, pressed B+RIGHT every tick and never connected.

    A prior fix answered this with a bare one-frame turn press
    (``_press(gamepad, face, frames=1)``) before punching. Measured live
    over a multi-minute run that press did not reliably register at all --
    caught frozen at the same position and action byte for **60 seconds**
    with no enemy nearby to jostle it loose. Every reliable turn elsewhere
    in this codebase holds the direction continuously through
    ``_hold_steered`` instead of an isolated press; see
    ``state_machine_open_breakable``'s wrong-facing branch, which walks the
    last bit toward the smash pocket (facing flips as a side effect of
    holding a direction to walk in it) rather than trying to turn in place.
    """

    dx = prop.world_x - actor.world_x
    if dx > 0:
        return not actor.facing_left
    if dx < 0:
        return actor.facing_left
    return True


def _back_direction_mask(actor: Myself | Partner) -> int:
    """Opposite of facing — used for hold-throw (B+back)."""

    return RIGHT_MASK if actor.facing_left else LEFT_MASK


def _aim_point(verb: Verb, actor: Myself | Partner, target: Enemy) -> Enemy:
    """The target where this verb's own move will meet it (``kinematics``).

    The executor aims at the same point the decision was made about. Facing
    is the reason it matters: holding a direction is what sets facing, and
    the press lands a few frames later, so pointing at a stale position can
    commit the strike at the side the enemy has just left -- the identical
    mistake ``inference.check_for_targets_in_reach`` avoids when producing
    the verb. A stationary target aims at itself.
    """

    return kinematics.target_at_impact(type(verb), actor, target)


def _dead_zone_stop_dx(actor: Myself | Partner, target: Enemy, stop_dx: int) -> int:
    """Close *past* the enemy's own reach when it has a hole to stand in.

    Some enemies cannot hit what is pressed against them: every attack they
    own starts further out than contact, so there is a pocket between their
    body and the inner edge of their reach where they are defenceless.
    ``Enemy.min_reach`` is that inner edge, extracted from the ROM's own
    shape tables, and today it picks out exactly one type -- Nora, whose whip
    (shape ``$22``) covers 32 to 80 px.

    Stopping at the actor's own punch edge ignores it completely: 46px for
    Axel is *inside* the whip band, so the AI parked itself squarely where
    she hits and nowhere else, which is what "the AI cannot deal with Noras"
    looks like from the sofa. The rest of the pipeline already knows about
    the pocket -- ``reach.in_enemy_dead_zone``, ``reach.grab_reasons``'
    ``DEAD_ZONE`` -- but the approach that decides where to *stand* never
    consulted it.

    So when the pocket exists and the actor can still land its own strike
    from inside it, aim there instead. The floor is the punch's usable inner
    edge: closer than that and the pocket is safe but unhittable, which is
    the grab's business (``DEAD_ZONE``), not this walk's. The margin
    matches ``reach``'s own, so "inside the dead zone" means the same thing
    to the verb that walks there and to the predicate that judges it.
    """

    dead_zone = target.min_reach
    if dead_zone <= 0:
        return stop_dx
    inside = dead_zone - REACH_SAFETY_MARGIN
    floor = punch_usable_inner_x(actor.character_id) + WALK_TO_ENEMY_STOP_BUFFER
    return max(floor, min(stop_dx, inside))


def _souther_pocket_stop_dx(actor: Myself | Partner, target: Enemy, stop_dx: int) -> int:
    """Stand inside Souther's own state-1 inner abort, not at punch's outer edge.

    ``reach.SOUTHER_SLASH_DIST_MIN`` (24px) is where ``$15EDA
    (souther_state1_active_combat)`` cannot *begin* the slash at all -- see
    that constant's own docstring for the ROM evidence. Stopping at the
    punch's outer edge instead (46px for Axel) sits squarely inside his
    state-1 commit window (the velocity-selected ``$50``/``$58``/``$68``
    bands), which is exactly where the claw comes from: measured live, 220 of
    240 health lost across a full fight went in during the wind-up that
    follows that commit. Aiming for the pocket denies the commit outright
    instead of merely giving the actor a worse angle to be hit from.

    Only while he is **not** already ``strike_is_committed()``. Once the claw
    is out, this same distance is where ``$161C6
    (souther_state2_claw_dash)`` *resolves* -- reach.SOUTHER_SLASH_DIST_MIN's
    own docstring says so -- so it has stopped being a pocket and become the
    thing being dodged; ``DodgeSoutherSlash`` owns that window, not this stop
    point.
    """

    if not isinstance(target, Souther) or target.strike_is_committed():
        return stop_dx
    inside = SOUTHER_SLASH_DIST_MIN - REACH_SAFETY_MARGIN
    floor = punch_usable_inner_x(actor.character_id) + WALK_TO_ENEMY_STOP_BUFFER
    return max(floor, min(stop_dx, inside))


def _crossing_would_walk_into_the_swing(actor: Myself | Partner, target: Enemy) -> bool:
    """True while starting the walk into a dead-zone enemy would cross a
    live swing.

    Only for an enemy that *has* a dead zone, and only from outside its
    whole reach -- the two conditions that make waiting a real tactic rather
    than passivity. Nora is the case: her whip covers 32..80px, so outside 80
    she cannot touch the actor at all, and the pocket under 32 is the place
    to be. Between them is her band, and it has to be crossed.

    Which is where the hits came from. With the approach aiming for the
    pocket, a live recording had her land 9 of her 10 hits at ~80px -- the
    far edge of her reach, catching the actor as it set off. So the crossing
    waits for the swing to end; her engage-and-swing (state ``$08``) is
    stationary, so waiting outside it costs nothing, and the moment she stops
    the actor walks all the way through to the pocket.

    Deliberately *not* general. Holding ground against an ordinary enemy --
    one whose reach starts at its own feet, so there is no safe distance
    short of out of range -- was measured and is simply passivity: it walks
    up and hits you anyway, while you have stopped attacking. That
    experiment cost 20% of the AI's damage output and raised the damage it
    took. The difference here is that "outside 80px" is a place Nora
    genuinely cannot reach.
    """

    if target.min_reach <= 0 or not is_dangerous(target.combat_phase):
        return False
    if target.max_reach <= 0:
        return False
    if not enemy_lane_covers(target, actor):
        # The swing is not aimed anywhere near this lane, so there is nothing
        # to wait out -- and waiting anyway was expensive: gating on the X
        # gap alone cost half the AI's stage progress in a live recording
        # (1487px against 2579-3255) because it sat out swings it was never
        # in the line of.
        return False
    gap = abs(target.world_x - actor.world_x)
    return gap > target.max_reach + REACH_SAFETY_MARGIN


def _lane_offset_while_closing(target: Enemy) -> int | None:
    """The lane offset this enemy's own ROM gate makes mandatory, or ``None``.

    Not-``None`` for a live boss whose committed move is *lane-gated*,
    regardless of what he is doing this instant -- which is the difference
    from the generic ``is_dangerous`` test below. For those, an approach that
    keeps more lane than the gate allows cannot arm the move at all, however
    the X distance closes; "hold the actor's current lane", which is what the
    generic branch does, is a coin flip on exactly that question.

    Two bosses qualify, from two separately derived numbers:

    - **Antonio**, whose ``$16EAE`` power kick needs the target within
      ``$10`` (16px) of his lane and whose ``$16E74`` dash/boomerang commit
      needs ``$14`` (20px). ``ANTONIO_APPROACH_LANE_Y`` clears both;
    - **Souther**, whose ``$15EDA (souther_state1_active_combat)`` slash
      commit needs ``+$52 < $1C`` (28px). ``SOUTHER_APPROACH_LANE_Y`` is that
      gate plus the routed goal's own lane slack.

    Souther is the case where the offset is not merely safer but *closes the
    gate for the entire approach*: his commit also needs ``+$50 >= $18``, and
    the pocket ``_souther_pocket_stop_dx`` stops in is inside that, so the
    lane offset covers the walk in and the inner abort covers the arrival,
    with an overlap rather than a gap between them. See
    ai-analysis/enemy-ai.md, "The uncommittable corridor".

    An earlier attempt at this for Souther measured *worse* (2 lives / 177 s
    against 1 / 89 s) and was scoped back to Antonio. That measurement is not
    evidence against the corridor: it was taken while ``_approach_lane_y``
    could not converge a lane at all, so holding an offset only deepened a
    stalemate the actor had no way out of. Re-measured after that fix, with
    ``--no-food`` so a heal cannot flatter it.
    """

    if target.is_defeated:
        return None
    if isinstance(target, Antonio):
        return ANTONIO_APPROACH_LANE_Y
    if isinstance(target, Souther):
        if is_punishable(target.combat_phase) or target.strike_is_committed():
            # The offset exists to deny `$15EDA`, and `$15EDA` is not on the
            # call path of any of these states: the hit reaction `$03`, the
            # lethal gate `$05`, the police reaction `$0A`, or the committed
            # claw. Holding it anyway is not merely pointless, it is what
            # loses the fight -- these are 47% of his ticks, they are the
            # only ground the hold can be taken from, and the approach was
            # spending all of them standing off-lane waiting for a commit
            # that cannot come.
            #
            # Measured over a 3669-tick trace: `grab_reasons` offered
            # `SOUTHER_ON_PUNISH` on 1672 ticks and `grab_would_connect` was
            # true on **11**, with the actor parked at dx=76, dl=26 for 1136
            # of them -- which is this function's own offset, to the pixel.
            # (`DodgeSoutherSlash` owns the committed case, and it wants the
            # lane too.)
            return None
        return SOUTHER_APPROACH_LANE_Y
    return None


def _holds_lane_offset_while_closing(target: Enemy) -> bool:
    """Whether the approach must stay off this enemy's lane the whole way in."""

    return _lane_offset_while_closing(target) is not None


# The subset of GrabReason that means "already helpless, nothing left to
# deny" rather than "grabbable in general" -- see _approach_lane_y.
_ON_PUNISH_GRAB_REASONS = frozenset({GrabReason.ANTONIO_ON_PUNISH, GrabReason.SOUTHER_ON_PUNISH})


def _approach_lane_y(
    actor: Myself | Partner, target: Enemy, context: Context, *, alongside: bool
) -> int:
    """Which lane to aim at while closing on ``target``.

    Shared by the routed goal and the straight-line fallback for the same
    reason ``_enemy_stop_dx`` is: the two must not disagree about where the
    approach is going. Once ``alongside`` on X the answer is always the
    enemy's own lane -- the approach is over and the strike or the hold needs
    the alignment.

    A boss already in one of its own *punishable* primaries is the other
    case that forces exact convergence, ahead of the generic bands below.
    Those bands are sized for a *punch* -- ``WALK_TO_ENEMY_LANE_SAFETY_Y`` is
    ``PUNCH_RANGE_Y`` plus slack -- and Souther's ``$03``/``$05``/``$0A`` or a
    punishable Antonio need the much tighter ``reach.GRAB_RANGE_Y`` instead.
    Measured live against Souther's police-reaction window (``$0A``, the
    longest helpless state in the fight): the approach reached dy=26 while
    closing, landed inside the punch band's own "close enough" branch below,
    and parked there for the rest of the window -- ``grab_reasons`` stayed
    ``SOUTHER_ON_PUNISH`` for hundreds of ticks and ``grab_would_connect``
    never once went true, because 26px is comfortably inside the 28px punch
    band and just as comfortably outside the 10px grab range.

    Deliberately narrower than "``grab_reasons`` is nonempty": Antonio's
    ``ANTONIO_WALK_IN`` fires for any live, ready, ungrabbed Antonio, at any
    range -- that is the reason the lane-offset approach below exists at all,
    and converging early on its strength alone reopens his kick gate (broke
    three ``test_an_antonio_approach_*`` fixtures, all at his own
    ``CombatPhase.NORMAL``, when tried). Only the two *on-punish* reasons --
    the boss already helpless, nothing left to deny -- earn the bypass.
    ``enemies=[]`` is safe here: both boss branches of ``grab_reasons``
    return before ever touching that argument.
    """

    if alongside or grab_reasons(context, actor, target, []) & _ON_PUNISH_GRAB_REASONS:
        return target.world_y
    dy = abs(target.world_y - actor.world_y)
    gated = _lane_offset_while_closing(target)
    hold_offset = gated if gated is not None else WALK_TO_ENEMY_LANE_SAFETY_Y
    clear_of_the_line = (
        hold_offset - PUNCH_RANGE_Y if gated is not None else WALK_TO_ENEMY_LANE_SAFETY_Y
    )
    if dy > hold_offset:
        # Clear of the line -- but "clear" must not also mean "and never any
        # closer". Returning ``actor.world_y`` here holds *whatever* offset
        # the actor happens to have, however wide, and that is a deadlock
        # rather than a plan: ``strike_goal`` builds its region around the
        # lane this function names, so an approach 68px off-lane walks to the
        # right X on its own lane, reports arrival, and stands there. Nothing
        # is in range, so nothing attacks; the goal is met, so nothing moves.
        # Measured against Souther, who fights from the top two rows of the
        # band: the actor spent a 90 s fight at lane 59-88 against a boss at
        # 0-27, holding no button for 4600 of 6513 approach ticks and landing
        # one punch. ``alongside`` was supposed to converge the lane, but it
        # only becomes true inside ``stop_dx`` on X, and against a boss that
        # keeps re-opening the X gap the two conditions never coincide.
        #
        # So close the lane down to the offset the approach actually wants,
        # on the side the actor is **already** on. That side is what makes
        # this safe to do for every enemy rather than Antonio alone: the aim
        # point lies strictly between the two bodies (dy is greater than the
        # offset), so it can never route the walk across the target's own
        # lane, which is the risk the midpoint rule below carries and the
        # reason that rule stays scoped.
        side = 1 if actor.world_y > target.world_y else -1
        return int(target.world_y + side * hold_offset)
    if dy >= clear_of_the_line:
        # Inside the band the approach wants; holding the current lane is
        # enough, and a further nudge would only be jitter.
        return actor.world_y
    if not (
        _holds_lane_offset_while_closing(target) or is_dangerous(target.combat_phase)
    ):
        return actor.world_y
    # Leave the line, aiming at a *fixed* lane rather than a displacement
    # from the actor's own, so repeated ticks converge on one point instead
    # of stepping away forever.
    lo, hi = _lane_bounds(context)
    if not _holds_lane_offset_while_closing(target):
        # Side from the lane band's own midpoint, which does not move tick to
        # tick -- ``actor.world_y`` vs ``target.world_y`` crosses zero on a
        # couple of px of walk jitter while both bodies converge, and the
        # live symptom of reading it was the actor darting up and down by a
        # full 2 * WALK_TO_ENEMY_LANE_SAFETY_Y against one barely-moving
        # enemy.
        #
        # The Antonio branch below reads the side instead, and measurably
        # should, but that is **scoped to him on purpose**: it is measured on
        # his fight and nowhere else. Souther crosses lanes constantly and
        # grunts arrive in crowds, so a side that can flip is a real risk
        # there and an unmeasured one -- see autoplay/CLAUDE.md.
        offset = (
            WALK_TO_ENEMY_LANE_SAFETY_Y
            if target.world_y >= (lo + hi) / 2
            else -WALK_TO_ENEMY_LANE_SAFETY_Y
        )
        return int(target.world_y + offset)

    # A lane-gated boss: the side is the one the actor is **already on**, so
    # the walk never crosses the lane it is leaving. The midpoint rule above
    # puts the aim point on the far side whenever he sits between the actor
    # and the middle of the band, and the actor then walks straight through
    # his own gate -- simulated over the real executor against Antonio, an
    # approach starting 20px clear crossed to 5px and then 2px while still
    # 130px away on X. Crossing is exactly what the offset exists to prevent,
    # so the side rule is part of the gate denial and not a separate taste.
    #
    # The jitter the midpoint rule exists for is answered by a deadband: an
    # actor within LANE_SIDE_DEADBAND_Y of his lane has no side worth
    # reading, and only then does the room in the band decide.
    dy_signed = actor.world_y - target.world_y
    if abs(dy_signed) >= LANE_SIDE_DEADBAND_Y:
        offset = hold_offset if dy_signed > 0 else -hold_offset
    else:
        offset = (
            hold_offset
            if target.world_y < (lo + hi) / 2
            else -hold_offset
        )
    aim = target.world_y + offset
    if not lo <= aim <= hi:
        # No room that side of him; the band's other side is all there is,
        # and crossing is then unavoidable rather than chosen.
        aim = target.world_y - offset
    return int(aim)


def _lane_release_dx(actor: Myself | Partner, target: Enemy, stop_dx: int) -> int:
    """The X gap at which the approach may finally converge onto the lane.

    ``stop_dx`` -- where the strike lands from -- for everything ordinary.
    For a boss the offset is *denying a gate* rather than dodging a swing,
    though, and then the honest boundary is the gate's own, not the
    approach's: giving the lane up any later leaves the actor holding an
    offset it no longer needs, inside a range where the enemy cannot commit
    anyway, waiting on an X gap the enemy is actively opening.

    Souther is that case and the reason this exists. ``$15EDA
    (souther_state1_active_combat)`` aborts the slash outright below ``$18``
    (24px) -- ``reach.SOUTHER_SLASH_DIST_MIN`` -- while ``_souther_pocket_
    stop_dx`` stops at 16, so the eight pixels between them were a band where
    the actor was already safe and still refusing to line the punch up.
    Measured live: 3 punches thrown in a whole fight, with the approach
    holding a 40px lane offset the entire time. Handing the lane over at the
    ROM's own boundary closes that band.

    Only while he is not already committed -- once the claw is out, 24px is
    where ``$161C6`` *resolves* rather than a pocket, which is
    ``_souther_pocket_stop_dx``'s own rule and ``DodgeSoutherSlash``'s window.
    """

    if isinstance(target, Souther) and not target.strike_is_committed():
        return max(stop_dx, SOUTHER_SLASH_DIST_MIN - 1)
    return stop_dx


def _walk_to_near_enemy_target(
    actor: Myself | Partner, target: Enemy, context: Context
) -> tuple[int, int]:
    """Stopping point for approaching ``target``.

    Stops just inside the actor's punch outer edge (never overlaps the
    enemy, per AI-Goals.md's "não se deve aproximar mais do que o
    suficiente"). Converges the actor's Y onto the enemy's lane so the
    eventual punch lands (dy must clear PUNCH_RANGE_Y) — except while a
    dangerous enemy is still far away, where it aims for an offset lane
    instead of closing distance straight down the enemy's line of attack.

    Live testing showed gating this offset on the actor already sitting on
    the enemy's exact lane (``on_lane``) reacted too late: the approach
    converges onto that lane over several ticks regardless (nothing else
    holds it off), so by the time the gate opened the enemy had often
    already reached ATTACKING and landed a hit before the sidestep could
    take effect. Aiming for the offset lane for the whole dangerous approach
    avoids ever walking down the enemy's exact line in the first place.

    Within ``DIRECTION_HYSTERESIS_X`` of the enemy on X, which side to aim
    for is read off ``actor.facing_left`` instead of the live position
    compare below: this close, ``actor.world_x`` vs ``target.world_x`` is
    noise (see ``DIRECTION_HYSTERESIS_X``'s own comment), and picking the far
    side on a spurious flip would jump the stop point by a full
    ``2 * stop_dx`` -- a large, visible direction change for what is really
    still the same encounter.

    The offset lane's up/down side is picked from ``target.world_y`` against
    the lane's own fixed midpoint (``_lane_bounds``), not from
    ``actor.world_y`` vs ``target.world_y``: while approaching, both bodies
    are converging onto the same Y, so their *relative* compare crosses zero
    on essentially every tick from a couple of px of ordinary walk jitter --
    and unlike the X pick above, there is no persisted "facing" on the
    vertical axis to fall back on. Picking the side from the target's
    position against the fixed lane midpoint sidesteps the noise instead of
    damping it: the midpoint doesn't move tick to tick, so the pick is
    already stable without needing a hysteresis band. Live symptom before
    this: the actor darting up/down (a full ``2 * WALK_TO_ENEMY_LANE_SAFETY_Y``
    swing) against a single, barely-moving dangerous enemy.
    """

    stop_dx = _enemy_stop_dx(actor, target)

    if _crossing_would_walk_into_the_swing(actor, target):
        return actor.world_x, actor.world_y

    release_dx = _lane_release_dx(actor, target, stop_dx)
    dx = target.world_x - actor.world_x
    if abs(dx) <= DIRECTION_HYSTERESIS_X:
        approach_from_right = actor.facing_left
    elif enemy_behind_actor(actor, target):
        # Aim for the *far* side, so the movement mask points at the enemy
        # rather than away from it. Holding a direction is what sets facing,
        # so this is the turn-around: after a tick the enemy is in front and
        # could_punch covers it normally. Stopping on the near side (the
        # branch below) would instead back the actor away while still facing
        # the wrong way, leaving the slow RearAttack chord as the only thing
        # that could reach it.
        approach_from_right = actor.world_x <= target.world_x
    else:
        approach_from_right = actor.world_x > target.world_x
    target_x = target.world_x + stop_dx if approach_from_right else target.world_x - stop_dx

    # ``_approach_lane_y`` owns all three cases: arrived on X (converge onto
    # the enemy's lane so the punch lands), still approaching while standing
    # in a line of attack the enemy owns (leave the line), and otherwise hold
    # the current lane.
    #
    # The last of those used to aim at ``target.world_y`` instead -- converge
    # onto the enemy's lane from however far away. Combined with the sidestep
    # case that made the lane aim flip by a full
    # ``2 * WALK_TO_ENEMY_LANE_SAFETY_Y`` every time the enemy's phase crossed
    # ``is_dangerous``, which in a real fight is every few ticks: commit ->
    # sidestep off the lane, recover -> converge back onto it, commit again ->
    # back off. Measured on the tick harness as a steady UP/DOWN alternation
    # for the whole approach, and the last source of the reported up/down
    # darting after the target churn was fixed. Holding the lane removes the
    # phase dependence entirely while serving the original intent better than
    # converging did: the actor simply never walks down the enemy's line in
    # the first place.
    dx = abs(target.world_x - actor.world_x)
    target_y = _approach_lane_y(actor, target, context, alongside=abs(dx) <= release_dx)

    return target_x, target_y


def _walk_toward_target(
    verb: Verb,
    context: Context,
    gamepad: VirtualGamepad,
    target_type: type,
    compute_target,
) -> None:
    """Shared body for every state machine that is nothing but "find the
    (actor, target) pair and steer toward a computed point": look both up,
    release when either is missing, otherwise hand the pair to
    ``compute_target`` and steer there.

    ``WalkToNearEnemy``, ``RetreatFromDanger`` and ``ProjectileSidestep``
    used to repeat this lookup/guard/steer shell verbatim, each differing
    only in which token type the target slot resolves to and which
    ``_*_target`` function computes the stopping point.
    """

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, target_type, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    target_x, target_y = compute_target(actor, target, context)
    _hold_steered(
        gamepad,
        _movement_mask(context, actor.world_x, actor.world_y, target_x, target_y),
    )


def _enemy_stop_dx(actor: Myself | Partner, target: Enemy) -> int:
    """How far from an enemy's origin this actor wants to stand.

    Split out of ``_walk_to_near_enemy_target`` so the routed approach and
    the straight-line fallback cannot disagree about it. Everything tactical
    lives here -- the punch's own outer edge, the dead-zone pocket some
    enemies have (``_dead_zone_stop_dx``), and Souther's own inner-abort
    pocket (``_souther_pocket_stop_dx``) -- while the route itself is
    geometry the path finder owns. The two pockets never both apply (a
    ``Souther`` has no extracted ``attack_ranges``, so ``_dead_zone_stop_dx``
    is a no-op on one and passes its input straight through).
    """

    outer = punch_outer_x(actor.character_id, actor.held_weapon_type)
    inner = punch_inner_x(actor.character_id)
    stop_dx = _dead_zone_stop_dx(actor, target, max(inner, outer - WALK_TO_ENEMY_STOP_BUFFER))
    return _souther_pocket_stop_dx(actor, target, stop_dx)


def state_machine_walk_to_near_enemy(
    verb: WalkToNearEnemy, context: Context, gamepad: VirtualGamepad
) -> None:
    """Walk until the punch would land, and no further.

    The destination is a *region* -- everywhere the strike connects from --
    rather than a computed point, so the search stops at the first position
    that can act instead of converging on one chosen spot. ``enough_contact``
    is what "would land" means: at least ``MIN_STRIKE_CONTACT_Y`` px of lane
    margin to spare, so an arrival that only clips the edge of the punch band
    does not count. It is deliberately a floor and not a preference -- an
    enemy is a moving target, and spending steps perfecting an alignment it
    is about to invalidate is how an approach turns into a dance.

    Every *other* live enemy, and the ground each of them can currently
    strike, is an obstacle (``navigation.plan_route``'s first pass), so the
    approach no longer walks down a third party's line of attack. The target
    itself is exempt: it is the destination.
    """

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Enemy, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    if _crossing_would_walk_into_the_swing(actor, target):
        _hold_steered(gamepad, 0)
        return

    stop_dx = _enemy_stop_dx(actor, target)
    # Close on X in the actor's *own* lane, and only converge onto the
    # enemy's once alongside it. The straight-line approach reached the same
    # conclusion the hard way (see ``_walk_to_near_enemy_target``): a
    # diagonal converges the lane early and then walks the last stretch
    # straight down the enemy's line of attack, which is the ground it hits.
    # Routing cannot fix that by itself, because the enemy being approached
    # is exempt from its own danger set -- its reach *contains* the place the
    # actor is trying to stand.
    alongside = abs(target.world_x - actor.world_x) <= _lane_release_dx(
        actor, target, stop_dx
    )
    # An enemy at the actor's back gets the *far* band only. Holding a
    # direction is what sets facing, so aiming past the enemy is the turn-
    # around; letting the search pick the near band by cost would back the
    # actor off still facing the wrong way, leaving the slow chord as the
    # only thing that could reach it.
    side = "both"
    if abs(target.world_x - actor.world_x) <= DIRECTION_HYSTERESIS_X:
        # Practically on top of it: the raw position compare is noise here
        # (see DIRECTION_HYSTERESIS_X), and crossing to the far band would
        # walk through the enemy and end up facing away from it. Step out on
        # the side the actor already faces from, which keeps it facing the
        # enemy the whole time.
        side = "right" if actor.facing_left else "left"
    elif enemy_behind_actor(actor, target):
        side = "right" if actor.world_x <= target.world_x else "left"
    goal = nav.strike_goal(
        nav.body_rect(actor),
        actor.world_x,
        actor.world_y,
        target.world_x,
        _approach_lane_y(actor, target, context, alongside=alongside),
        stop_dx=stop_dx,
        lane_slack=PUNCH_RANGE_Y,
        inner_dx=punch_usable_inner_x(actor.character_id),
        side=side,
    )
    # The target stops counting as a hazard only once the actor is alongside
    # it -- from there its reach *contains* the ground the actor is trying to
    # stand on, so keeping it would make the goal unreachable. While still
    # closing, it is a hazard like any other, which is what keeps the
    # approach off its line of attack instead of walking straight down it.
    body, origin = nav.actor_footprint(actor)
    solids, dangers = nav.obstacle_sets(
        context,
        body=body,
        origin=origin,
        ignore_enemy_slots=frozenset({target.slot}) if alongside else frozenset(),
    )

    def straight_line() -> int:
        target_x, target_y = _walk_to_near_enemy_target(actor, target, context)
        return _movement_mask(context, actor.world_x, actor.world_y, target_x, target_y)

    _hold_steered(
        gamepad,
        _routed_mask(
            context,
            actor,
            goal,
            solids=solids,
            dangers=dangers,
            enough_contact=nav.MIN_STRIKE_CONTACT_Y,
            fallback=straight_line,
        ),
    )


# How far to step back per tick while retreating -- roughly clears the
# RETREAT_CAUTION_MARGIN zone decide.py gates this verb on, without
# being a single-tick teleport. Also the X step _safe_spot_candidates offers
# below -- one retreat tick's worth of travel is one retreat tick's worth of
# travel, whichever candidate is chosen.
RETREAT_FROM_DANGER_DISTANCE = 32

# The lane step _safe_spot_candidates offers alongside the straight retreat.
# Clears PUNCH_RANGE_Y so a sidestep actually leaves the attacker's line
# rather than shuffling inside it.
SAFE_SPOT_STEP_Y = 24

# Minimum clearance improvement a sidestep/diagonal candidate must offer
# over the plain X-away retreat (the first candidate _safe_spot_candidates
# returns) before _find_safe_spot prefers it. Without this, two candidates
# scoring within a couple of px of each other on ordinary position jitter
# flipped which one won every tick -- and since the candidates differ in
# whether they add a Y step at all, that flip read live as the actor
# darting into a vertical/diagonal dash instead of holding a steady retreat
# line. Comfortably above the noise one tick of movement can introduce,
# well below the real clearance gap a genuinely better sidestep provides.
SAFE_SPOT_PREFERENCE_MARGIN = 12


def _safe_spot_candidates(actor: Myself | Partner, threat: Enemy) -> list[tuple[int, int]]:
    """Steps worth considering: away on X, and the two sidesteps, alone or
    combined with the retreat. Standing still is not a candidate -- this
    only exists to answer "back off to *where*".

    Within ``DIRECTION_HYSTERESIS_X`` of the threat, which way is "away" is
    read off ``actor.facing_left`` instead of the raw compare (same
    convention as ``_back_direction_mask``: right when facing left) -- an
    actor already backed into caution range sits close enough to its threat
    that a couple of px of jitter would otherwise flip every candidate
    here, including the sidesteps, to the opposite side on consecutive
    ticks.
    """

    dx = threat.world_x - actor.world_x
    if abs(dx) <= DIRECTION_HYSTERESIS_X:
        away = RETREAT_FROM_DANGER_DISTANCE if actor.facing_left else -RETREAT_FROM_DANGER_DISTANCE
    else:
        away = -RETREAT_FROM_DANGER_DISTANCE if dx >= 0 else RETREAT_FROM_DANGER_DISTANCE
    return [
        (actor.world_x + away, actor.world_y),
        (actor.world_x + away, actor.world_y + SAFE_SPOT_STEP_Y),
        (actor.world_x + away, actor.world_y - SAFE_SPOT_STEP_Y),
        (actor.world_x, actor.world_y + SAFE_SPOT_STEP_Y),
        (actor.world_x, actor.world_y - SAFE_SPOT_STEP_Y),
    ]


def _inside_pit(context: Context, world_x: int, world_y: int) -> bool:
    return any(pit_endangers(pit, world_x, world_y) for pit in find_all(context, Pit))


def _find_safe_spot(actor: Myself | Partner, context: Context) -> tuple[int, int] | None:
    """The best nearby point to back off to, weighed by clearance from
    every live enemy -- or ``None`` if no candidate survives.

    Computed lazily, only when ``_retreat_from_danger_target`` actually
    needs a destination for this actor, rather than for every actor, every
    tick, regardless of whether anything is retreating.

    Candidates are reachability-gated, not chosen by clearance/lane/camera/
    pit geometry alone: each survivor is routed through ``nav.plan_route``
    (the same solids/danger obstacle sets and danger-then-solids-only
    fallback ``WalkToNearEnemy``/``OpenBreakable`` use) and dropped if the
    route does not reach it, so a spot that reads as clear in isolation but
    sits behind a breakable or another enemy's reach is not returned as if
    it were free. The threatening enemies themselves are excluded from that
    danger set -- the actor is fleeing because it is already next to them,
    so their own reach would otherwise cover the ground between the actor
    and every candidate and disable the gate entirely (the same reasoning
    ``_walk_to_near_enemy_target``'s ``alongside`` exemption documents for
    the opposite verb) -- while unrelated enemies' danger and every
    breakable/pit stay real obstacles.
    """

    enemies = live_enemies(context)
    if not enemies:
        return None
    threat_slots = incoming_melee_targets(context, actor)
    threatening = [enemy for enemy in enemies if enemy.slot in threat_slots]
    if not threatening:
        return None
    nearest = min(
        threatening,
        key=lambda e: math.hypot(e.world_x - actor.world_x, e.world_y - actor.world_y),
    )

    camera = find(context, CameraRange)
    threatening_slots = frozenset(enemy.slot for enemy in threatening)
    body, origin = nav.actor_footprint(actor)
    solids, dangers = nav.obstacle_sets(
        context,
        body=body,
        origin=origin,
        ignore_enemy_slots=threatening_slots,
    )

    # index 0 (the plain X-away retreat) is the stability anchor: every
    # other candidate must clear it by SAFE_SPOT_PREFERENCE_MARGIN to win,
    # so a near-tie keeps resolving to the same simple retreat instead of
    # flipping to a sidestep on ordinary jitter (see that constant's
    # comment).
    best: tuple[float, tuple[int, int]] | None = None
    anchor_clearance: float | None = None
    for index, (candidate_x, candidate_y) in enumerate(_safe_spot_candidates(actor, nearest)):
        if not in_playable_lane(candidate_y, context):
            continue
        if camera is not None and not in_camera(camera, candidate_x, candidate_y):
            continue
        if _inside_pit(context, candidate_x, candidate_y):
            continue
        # The candidate itself is clear, but the straight-line route to it
        # might not be -- a crate, a pit, or an unrelated enemy's reach can
        # sit between the actor and an otherwise fine spot. nav.plan_route
        # already tries a danger-free route first and falls back to
        # solids-only when no such route exists (a busy screen should not
        # make every retreat "unreachable"), so this reuses that same
        # policy rather than reinventing it.
        path = nav.plan_route(
            context,
            actor,
            PointGoal(Point(candidate_x, candidate_y)),
            solids=solids,
            dangers=dangers,
        )
        if not path.reached:
            continue
        clearance = min(
            math.hypot(enemy.world_x - candidate_x, enemy.world_y - candidate_y)
            for enemy in enemies
        )
        if index == 0:
            anchor_clearance = clearance
            score = clearance
        elif anchor_clearance is None:
            score = clearance
        else:
            score = clearance - SAFE_SPOT_PREFERENCE_MARGIN
        if best is None or score > best[0]:
            best = (score, (candidate_x, candidate_y))
    return best[1] if best is not None else None


def _retreat_from_danger_target(
    actor: Myself | Partner, target: Enemy, context: Context
) -> tuple[int, int]:
    """Where to back off to.

    Prefers ``_find_safe_spot`` for this actor: it has already weighed the
    sidesteps against the straight retreat by clearance from every live
    enemy, and rejected candidates that leave the lane, leave the camera,
    or land on a pit. Falls back to stepping directly away from ``target``
    on X, holding the current lane, when no safe spot was found -- backing
    off blindly still beats standing in the attack.

    Within ``DIRECTION_HYSTERESIS_X`` of the target, which way is "away" is
    read off ``actor.facing_left`` instead of the live position compare --
    the same reasoning as ``_walk_to_near_enemy_target``'s own X pick: this
    close, the raw compare is noise, and flipping it flips the full
    ``2 * RETREAT_FROM_DANGER_DISTANCE`` retreat direction on a spurious
    tick.
    """

    spot = _find_safe_spot(actor, context)
    if spot is not None:
        return spot

    dx = target.world_x - actor.world_x
    if abs(dx) <= DIRECTION_HYSTERESIS_X:
        flee_right = actor.facing_left
    else:
        flee_right = dx < 0
    target_x = (
        actor.world_x + RETREAT_FROM_DANGER_DISTANCE
        if flee_right
        else actor.world_x - RETREAT_FROM_DANGER_DISTANCE
    )
    return target_x, actor.world_y


def state_machine_retreat_from_danger(
    verb: RetreatFromDanger, context: Context, gamepad: VirtualGamepad
) -> None:
    """Back off to ``_retreat_from_danger_target``'s point, routed.

    The destination itself is untouched -- safe-spot preference, hysteresis-
    anchored fallback direction, all still `_retreat_from_danger_target`'s
    call, tuned from live measurement. What was missing was *how* to get
    there: an un-routed retreat walks a straight line, which can cross
    another enemy's body or reach band, or cut through ground a pit actually
    blocks even where the straight-line dodge in `_movement_mask` happens to
    miss it -- exactly the geometry `navigation.py`'s obstacle sets exist to
    avoid.

    Every live enemy counts as danger here, not only the one being fled --
    unlike the approach verbs there is no "target is exempt" case: retreating
    is never trying to stand *in* anyone's reach, so nothing needs to be
    excused from its own danger set the way `state_machine_walk_to_near_
    enemy` excuses the enemy it is walking up to.

    Tolerance is `MOVE_DEADBAND_X`, the same scale `_movement_mask`'s own
    deadbands already treat as "close enough to stop steering" -- a `PointGoal`
    would otherwise never be satisfied on a lattice whose steps don't land
    exactly on an arbitrary target pixel.
    """

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Enemy, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return

    target_x, target_y = _retreat_from_danger_target(actor, target, context)
    goal = PointGoal(Point(target_x, target_y), tolerance=MOVE_DEADBAND_X)
    body, origin = nav.actor_footprint(actor)
    solids, dangers = nav.obstacle_sets(context, body=body, origin=origin)

    def straight_line() -> int:
        return _movement_mask(context, actor.world_x, actor.world_y, target_x, target_y)

    _hold_steered(
        gamepad,
        _routed_mask(
            context,
            actor,
            goal,
            solids=solids,
            dangers=dangers,
            fallback=straight_line,
        ),
    )


# How far to step off a projectile's lane per tick -- comfortably past
# inference.PROJECTILE_LANE_SLACK (24) so the step actually clears the band
# check_for_incoming_projectiles used to judge the throw a threat, rather
# than landing just inside it.
PROJECTILE_SIDESTEP_DISTANCE = 40

# How far clear of *Souther's own lane* the dodge aims -- an absolute
# clearance, not a step length, because the side pick is derived from his lane
# rather than from the actor's (see _souther_slash_sidestep_target). The claw
# dash resolves only with the target within $18 (24px) of its lane
# ($161C6 souther_state2_claw_dash) and the state-1 commit gate at
# $15EDA needs $1C (28px), so this has to clear 28 -- plus more than
# MOVE_DEADBAND_Y, or the Y bits go quiet while X is still frozen and the actor
# stalls a few px short of actually escaping, the same deadlock
# PIT_DODGE_OVERSHOOT exists to prevent.
SOUTHER_SLASH_LANE_CLEARANCE = 0x1C + MOVE_DEADBAND_Y + 5


def _projectile_sidestep_target(
    actor: Myself | Partner, projectile: Projectile, context: Context
) -> tuple[int, int]:
    """Where to step to clear the projectile's own lane.

    A lateral step only -- X holds at the actor's current position, since the
    projectile's danger is entirely about sharing its Y column
    (``inference._projectile_threatens`` is lane-gated, not X-gated: it only
    cares that the throw is heading toward the actor's X). Which way to step
    is picked the same way ``_movement_mask``'s own prop/pit dodges pick a
    side -- away from the nearer lane edge -- rather than away from the
    projectile's Y, since the actor already shares that Y (that is what made
    the throw a threat) and stepping "away from it" is therefore not a stable
    direction: it would flip every tick as ordinary walk jitter nudges which
    side of the projectile's Y the actor's own Y reads as.
    """

    lo, hi = _lane_bounds(context)
    if actor.world_y < (lo + hi) / 2:
        return actor.world_x, actor.world_y + PROJECTILE_SIDESTEP_DISTANCE
    return actor.world_x, actor.world_y - PROJECTILE_SIDESTEP_DISTANCE


def _souther_slash_sidestep_target(
    actor: Myself | Partner, souther: Souther, context: Context
) -> tuple[int, int]:
    """Where to step to make Souther's committed claw dash overshoot.

    X holds, as it does for a thrown weapon:
    ``$161C6 (souther_state2_claw_dash)`` closes the X gap itself at 8px/frame,
    far faster than any character walks, so contesting X is pointless. What it
    never does is write ``+$20`` -- the dash cannot correct lane once committed
    -- and it only resolves with the target inside ``$18`` of its lane, so the
    lane is the whole fight.

    **Which** side is picked from **Souther's own lane**, never from the lane
    midpoint, the same way ``_pit_dodge_target_y`` picks from the pit's danger
    edges and for exactly the same reason. The midpoint rule
    ``_projectile_sidestep_target`` above uses steers the actor *toward* the
    middle of the lane and across it (upper half aims down, lower half aims
    up), so the pick undoes itself the moment the actor crosses -- harmless for
    a throw, which is over in a tick or two, and a permanent oscillation here,
    because this dodge freezes X and the claw lasts many ticks. Caught on the
    tick harness (``tests/ai/test_stability.py``): with the actor at lane 60 in
    a 0..112 lane, the commanded lane direction reversed 18 times in 40 ticks,
    alternating UP/DOWN across the midpoint at 56.

    Souther's own lane is stable because it is self-reinforcing: the flip point
    is his lane, and the chosen direction always moves the actor further from
    it. A side only counts if its aim point survives the lane clamp still clear
    of the band; when neither does, the roomier side is the best answer
    available and is still picked from his lane and the lane bounds alone, so
    it cannot oscillate either.
    """

    lo, hi = _lane_bounds(context)
    above = souther.world_y - SOUTHER_SLASH_LANE_CLEARANCE
    below = souther.world_y + SOUTHER_SLASH_LANE_CLEARANCE
    can_go_up = above >= lo
    can_go_down = below <= hi

    dy = actor.world_y - souther.world_y
    if dy < 0 and can_go_up:
        return actor.world_x, int(above)
    if dy > 0 and can_go_down:
        return actor.world_x, int(below)
    if can_go_up and can_go_down:
        # Exactly on his lane: no sign to read, so fall back to whichever side
        # has more room. One tick of movement gives the test above a sign, and
        # from then on it reinforces itself.
        roomier_is_up = (souther.world_y - lo) >= (hi - souther.world_y)
        return actor.world_x, int(above if roomier_is_up else below)
    if can_go_up:
        return actor.world_x, int(above)
    if can_go_down:
        return actor.world_x, int(below)
    roomier_is_up = (souther.world_y - lo) >= (hi - souther.world_y)
    return actor.world_x, int(lo if roomier_is_up else hi)


def state_machine_projectile_sidestep(
    verb: ProjectileSidestep, context: Context, gamepad: VirtualGamepad
) -> None:
    """Step off the lane, routed around whatever else is standing in it.

    Same two-pass planning as ``state_machine_walk_to_near_enemy``, not the
    straight line ``_walk_toward_target`` gives every other lookup/guard/
    steer verb: a plain sidestep has no notion of "this enemy is the
    destination, exempt it", so every live enemy's body and committed reach
    counts as danger here, unlike the near-enemy approach's target exemption.
    The destination itself is unchanged from before this routed --
    ``_projectile_sidestep_target`` still owns which way is safe from the
    throw; this only changes how the actor gets there.

    A thrown weapon is time-critical in a way a walk-in or a retreat is not,
    which makes the router's own detours a real risk here in principle. In
    practice the step is short (PROJECTILE_SIDESTEP_DISTANCE, 40px) and
    purely lateral, so the fast path -- danger-aware planning reaching the
    goal on the first pass -- is the case that matters, and it costs the same
    single vector as the straight line would. The only way this gets slower
    than a straight step is a body or reach square parked exactly on the 40px
    lane the actor would have taken, in which case the straight line was
    about to walk into it -- eating that enemy's incidental reach while
    clearing the thrown lane is the better trade of the two, not a
    regression.
    """

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Projectile, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return

    target_x, target_y = _projectile_sidestep_target(actor, target, context)
    goal = nav.PointGoal(nav.Point(target_x, target_y), tolerance=MOVE_DEADBAND_X)
    body, origin = nav.actor_footprint(actor)
    solids, dangers = nav.obstacle_sets(context, body=body, origin=origin)

    def straight_line() -> int:
        return _movement_mask(context, actor.world_x, actor.world_y, target_x, target_y)

    _hold_steered(
        gamepad,
        _routed_mask(
            context,
            actor,
            goal,
            solids=solids,
            dangers=dangers,
            fallback=straight_line,
        ),
    )


def _antonio_lane_break_target(
    actor: Myself | Partner, antonio: Antonio, context: Context
) -> tuple[int, int]:
    """Where to step to put ``reach.ANTONIO_KICK_LANE_BREAK`` of lane between
    the actor and Antonio.

    X holds: the gate's X half is 80-120px wide depending on how the actor is
    moving, so contesting it means retreating most of the arena, while the
    lane half is 16px and can be left in about three ticks. Side is picked
    from **his** lane, never the lane midpoint, the same self-reinforcing
    rule ``_souther_slash_sidestep_target`` and ``_pit_dodge_target_y`` use.
    """

    lo, hi = _lane_bounds(context)
    clearance = ANTONIO_KICK_LANE_BREAK + MOVE_DEADBAND_Y
    above = antonio.world_y - clearance
    below = antonio.world_y + clearance
    can_go_up = above >= lo
    can_go_down = below <= hi

    dy = actor.world_y - antonio.world_y
    if dy < 0 and can_go_up:
        return actor.world_x, int(above)
    if dy > 0 and can_go_down:
        return actor.world_x, int(below)
    if can_go_up and can_go_down:
        roomier_is_up = (antonio.world_y - lo) >= (hi - antonio.world_y)
        return actor.world_x, int(above if roomier_is_up else below)
    if can_go_up:
        return actor.world_x, int(above)
    if can_go_down:
        return actor.world_x, int(below)
    return actor.world_x, actor.world_y


def state_machine_dodge_antonio_kick(
    verb: DodgeAntonioKick, context: Context, gamepad: VirtualGamepad
) -> None:
    """Hop the kick that is already coming; step out of the one that is not.

    **Committed** (`verb.committed`, primary `$02` or tactical `$08`) is the
    original behaviour: a ground sidestep does not leave the ROM's
    X-velocity gate in time once the strike is locked in (measured: minutes
    of sidestep, 0 damage dealt), so this reuses the jump-kick state machine
    and the airborne B edge punishes. Inside punch range that hop is in
    place -- a directed hop from there lands past him, facing away, and the
    grab on landing never happens.

    **Uncommitted** is the opposite input for the opposite situation: the
    gate is merely satisfiable, there are ~10 ticks before it fires, and
    `$16EAE` cannot start at all with the target more than `$10` (16px) off
    his lane. So this walks that 16px rather than jumping into it. Hopping
    here is what the trace caught the AI doing -- five of nine kick onsets
    had `JumpAttack` holding the tick through the whole warning.
    """

    if verb.committed:
        state_machine_jump_attack(verb, context, gamepad)
        return

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Antonio, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    target_x, target_y = _antonio_lane_break_target(actor, target, context)
    goal = nav.PointGoal(nav.Point(target_x, target_y), tolerance=MOVE_DEADBAND_X)
    body, origin = nav.actor_footprint(actor)
    solids, dangers = nav.obstacle_sets(context, body=body, origin=origin)

    def straight_line() -> int:
        return _movement_mask(context, actor.world_x, actor.world_y, target_x, target_y)

    _hold_steered(
        gamepad,
        _routed_mask(
            context, actor, goal, solids=solids, dangers=dangers, fallback=straight_line
        ),
    )


def state_machine_dodge_souther_slash(
    verb: DodgeSoutherSlash, context: Context, gamepad: VirtualGamepad
) -> None:
    """Step off the lane the claw dash resolves on -- and never jump.

    Deliberately *not* delegating to ``state_machine_jump_attack`` the way
    ``state_machine_dodge_antonio_kick`` does. Against Antonio the hop is the
    answer because his dash tracks lane; against Souther the hop is the one
    input ``$16234 (souther_counter_jump_attack)`` watches for, and it answers a
    jump-attack action state inside 120px x 18px by promoting him straight to
    the committed claw with every distance gate bypassed. So this reuses the
    routed lateral step instead, planned exactly like
    ``state_machine_projectile_sidestep``: every live enemy counts as danger
    (a dodge is never trying to stand in anyone's reach) and only the
    destination differs.
    """

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Souther, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return

    target_x, target_y = _souther_slash_sidestep_target(actor, target, context)
    goal = nav.PointGoal(nav.Point(target_x, target_y), tolerance=MOVE_DEADBAND_X)
    body, origin = nav.actor_footprint(actor)
    solids, dangers = nav.obstacle_sets(context, body=body, origin=origin)

    def straight_line() -> int:
        return _movement_mask(context, actor.world_x, actor.world_y, target_x, target_y)

    _hold_steered(
        gamepad,
        _routed_mask(
            context,
            actor,
            goal,
            solids=solids,
            dangers=dangers,
            fallback=straight_line,
        ),
    )


def state_machine_hit_antonio_boomerang(
    verb: HitAntonioBoomerang, context: Context, gamepad: VirtualGamepad
) -> None:
    """Face the boomerang and press B -- the same input as a punch."""

    actor = _find_actor(context, verb.actor_slot)
    projectile = find(context, Projectile, slot=verb.target_slot)
    face = 0
    if actor is not None and projectile is not None:
        face = _face_toward_mask(actor, projectile.world_x)
    _press(gamepad, PUNCH_MASK | face, frames=PUNCH_FRAMES)


def state_machine_walk_to_advance_stage(
    verb: WalkToAdvanceStage, context: Context, gamepad: VirtualGamepad
) -> None:
    """Keep making lateral progress in ``verb.direction`` -- the AI's
    lowest-priority fallback, produced only when nothing more important
    scores. Routed like ``WalkToNearEnemy``/``OpenBreakable``'s Y-dodging,
    but with one deliberate difference: this verb has no target token and no
    "arrived" state of its own, only a lookahead point that is re-picked
    every tick, so the guarantee that matters here is not "the router found
    *something*" but "the D-pad still carries verb.direction's bit no matter
    what the router found".
    """

    actor = _find_actor(context, verb.actor_slot)
    if actor is None:
        _hold_steered(gamepad, RIGHT_MASK if verb.direction == "right" else LEFT_MASK)
        return
    if actor.is_airborne or actor.action_base in JUMP_CROUCH_ACTIONS:
        # Finish a hop the pathfinder launched last tick -- do not start
        # walking mid-crouch or the hold $384E samples is lost.
        landing = nav.hop_landing_x(context, actor, verb.direction)
        target_x = landing if landing is not None else (
            actor.world_x + (40 if verb.direction == "right" else -40)
        )
        _jump_toward(actor, target_x, gamepad)
        return
    # Pure lateral advance — do not add accidental Up/Down.
    mask = RIGHT_MASK if verb.direction == "right" else LEFT_MASK
    # If a breakable sits immediately ahead, approach with a slight Y offset
    # so the next tick can smash rather than walk forever into it. The 40px
    # lookahead always clears MOVE_DEADBAND_X, so a routed vector's own L/R
    # bit (when it has one at all) always agrees with the plain `mask`
    # fallback -- the `or mask` below only ever matters for its Y bits' side
    # effects, or for a route with no lateral component this tick, never for
    # overriding a direction the axis hasn't reached full deflection on yet.
    ahead_x = actor.world_x + (40 if verb.direction == "right" else -40)

    def straight_line() -> int:
        return (
            _movement_mask(context, actor.world_x, actor.world_y, ahead_x, actor.world_y)
            or mask
        )

    # A vertical strip, not a point on the current lane. This verb does not
    # care which Y it advances on; pinning the lookahead to actor.world_y
    # made a pit on that lane an unreachable point (every covering cell sat
    # in the hole) and the search's best effort walked straight into it
    # while the lane still had room above or below. The strip says "get
    # 40px forward, take whichever Y is clear".
    goal = nav.advance_goal(context, ahead_x)
    # Solids only (breakables + pits) -- deliberately no danger obstacles,
    # unlike WalkToNearEnemy/OpenBreakable. Tried it: nav.plan_route's two
    # passes are "avoid danger and reach the goal, else ignore danger
    # entirely and reach it through solids alone" -- right when the goal is a
    # real destination, but this verb's goal slides forward with the actor
    # every tick, and once a nearby dangerous enemy's own reach box is wide
    # enough to contain that strip, the danger-aware pass can never "reach"
    # it (arriving there always means standing inside the thing being
    # avoided), so plan_route falls straight through to the solids-only pass
    # -- which does not know danger exists at all -- and the actor walks
    # straight at the enemy, worse than doing nothing. Measured on a
    # synthetic sweep (an ATTACKING enemy with a 48px reach box placed so
    # the lookahead lands inside it): the actor closed to within the reach
    # box for several ticks with no dodge at all before the danger-aware
    # pass happened to briefly succeed, confirming the failure mode rather
    # than curing it. Solids alone do not have this problem -- a breakable
    # or pit is real geometry the lookahead is never placed *inside* of the
    # way a 40px-ahead mark routinely lands inside a nearby enemy's reach --
    # and matches exactly what the pre-routing ad-hoc dodge already avoided
    # for this verb, so nothing about its danger handling regresses; only
    # the breakable/pit detour quality improves.
    body, origin = nav.actor_footprint(actor)
    solids = nav.solid_obstacles(context, body=body, origin=origin)
    path = nav.plan_route(context, actor, goal, solids=solids, dangers=())
    sink = _ROUTE_TRACE.get()
    if sink is not None:
        sink[actor.slot] = path
    if not path.reached:
        # Pathfinder cannot walk to the strip -- typically a pit that spans
        # the playable Y. Hop over if the landing is in kick range; otherwise
        # follow the best-effort first vector (up to the pit wall) and never
        # inject raw RIGHT/LEFT, which is how this verb used to walk in.
        landing = nav.hop_landing_x(context, actor, verb.direction)
        if landing is not None:
            _jump_toward(actor, landing, gamepad)
            return
        routed = nav.first_vector_mask(path)
        _hold_steered(gamepad, _clamp_mask(context, actor.world_x, actor.world_y, routed))
        return
    # The final `or mask` is the same short-circuit idiom the pre-routing
    # code used, not a bitwise merge: when the routed mask is already
    # non-zero (including a Y-only vector with no lateral bit, exactly the
    # shape a frozen-X pit dodge produces) it is used as-is, and `mask` only
    # substitutes in when the router comes back completely empty. That is
    # deliberate, not a gap -- PitDodgeSideStabilityTests below asserts a
    # pit dodge must *not* carry the lateral bit while X is still frozen, the
    # same property the ad-hoc `_movement_mask(...) or mask` line guaranteed
    # before this change. What both versions guarantee is: the actor is
    # never left holding nothing (`mask` covers the router's total-failure
    # case) and is never handed a direction that walks it back into what it
    # is actively dodging (the router's own vector, whatever it is, always
    # wins over the raw `mask`) -- see BreakableAdvanceStabilityTests in
    # test_stability.py for the cross-verb regression this whole fallback
    # discipline exists to protect against.
    routed = nav.first_vector_mask(path) or straight_line()
    # `or mask` must not re-introduce a direction the camera clamp just
    # stripped: at a wave gate the lookahead is past the walk edge, the
    # router asks for it, the ROM refuses, and forcing the bit back is
    # how the actor stands there holding RIGHT forever.
    held = routed or mask
    _hold_steered(gamepad, _clamp_mask(context, actor.world_x, actor.world_y, held))


def state_machine_melee_strike(verb: Verb, context: Context, gamepad: VirtualGamepad) -> None:
    """Shared handler for ``Punch`` / ``MeleeWeaponAttack`` -- identical
    B-button press regardless of which (if any) weapon is held; only the
    ROM-side move that resolves from it differs."""

    actor = _find_actor(context, getattr(verb, "actor_slot", None))
    target = find(context, Enemy, slot=getattr(verb, "target_slot", None))
    face = 0
    if actor is not None and target is not None:
        # Facing, unlike the throws below, is taken from the observed
        # position: the strike's own damaging span is what covers the
        # target's movement (inference.check_for_targets_in_reach), and
        # turning toward where a body *will* be is how the actor ends up
        # swinging past one standing next to it.
        face = _face_toward_mask(actor, target.world_x)
    _press(gamepad, PUNCH_MASK | face, frames=PUNCH_FRAMES)





def state_machine_rear_attack(verb: RearAttack, context: Context, gamepad: VirtualGamepad) -> None:
    _press(gamepad, PUNCH_MASK | JUMP_MASK, frames=REAR_ATTACK_FRAMES)


def state_machine_counter_grab(verb: CounterGrab, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, verb.actor_slot)
    if actor is None:
        gamepad.release()
        return
    base = actor.action_base
    if actor.counter_window_open:
        _press(gamepad, PUNCH_MASK, frames=COUNTER_FRAMES)
        return
    if base == 0x7A:
        _press(gamepad, JUMP_MASK, frames=COUNTER_FRAMES)
        return
    if base in (0x78, 0x7C):
        gamepad.release()
        return
    _press(gamepad, JUMP_MASK, frames=COUNTER_FRAMES)


def state_machine_tech_recover(verb: TechRecover, context: Context, gamepad: VirtualGamepad) -> None:
    # A held Up plus a *fresh* C edge, every tick this verb wins -- the
    # ROM requires a new C press, not a held-over one (controls-and-input.md
    # "C must be a fresh edge while Up is held").
    _press(gamepad, JUMP_MASK | UP_MASK, frames=TECH_RECOVER_FRAMES)


def state_machine_call_police(verb: CallPolice, context: Context, gamepad: VirtualGamepad) -> None:
    _press(gamepad, CALL_POLICE_MASK, frames=CALL_POLICE_FRAMES)


def _name_entry_letter_mask(current: int, target: int) -> int:
    """One Left/Right edge toward ``target``, or 0 when already there.

    $57D2 wraps the 0..26 alphabet (A..Z, END) on both edges, so the short
    way around is at most 13 steps.
    """

    delta = (target - current) % NAME_ALPHABET_SIZE
    if delta == 0:
        return 0
    if delta <= NAME_ALPHABET_SIZE // 2:
        return RIGHT_MASK
    return LEFT_MASK


def _name_entry_target_letter(name_slot: int) -> int | None:
    """Letter the AI wants in this slot, or ``None`` to finish the entry.

    Slot is object+$60 (0/2/4 for the three initials). ``AI `` is A then I
    then finish: the third character stays the cleared-to-zero space.
    """

    if name_slot == 0:
        return NAME_LETTER_A
    if name_slot == 2:
        return NAME_LETTER_I
    return None


def state_machine_handle_continue_menu(
    verb: HandleContinueMenu, context: Context, gamepad: VirtualGamepad
) -> None:
    menu = find(context, InContinueMenu, slot=verb.actor_slot)
    if menu is None:
        press_no_button(gamepad)
        return
    if menu.name_entry:
        target = _name_entry_target_letter(menu.name_slot)
        if target is None:
            _press(gamepad, START_MASK, frames=DIALOG_FRAMES)
            return
        step = _name_entry_letter_mask(menu.name_letter_index, target)
        if step:
            _press(gamepad, step, frames=DIALOG_FRAMES)
            return
        _press(gamepad, NAME_CONFIRM_MASK, frames=DIALOG_FRAMES)
        return
    if menu.selects_no:
        # $52AE toggles +$63 on any UP/DOWN edge of the global press byte.
        _press(gamepad, UP_MASK, frames=DIALOG_FRAMES)
        return
    _press(gamepad, PUNCH_MASK, frames=DIALOG_FRAMES)


def state_machine_handle_mr_x_dialog(
    verb: HandleMrXDialog, context: Context, gamepad: VirtualGamepad
) -> None:
    dialog = find(context, InMrXDialog, slot=verb.actor_slot)
    if dialog is None:
        press_no_button(gamepad)
        return
    # $120EC reads *held* +$54: Down sets bit 3 (NO), a face bit confirms.
    if not dialog.selects_no:
        gamepad.hold(DOWN_MASK)
        return
    _press(gamepad, PUNCH_MASK, frames=DIALOG_FRAMES)


# The jump, state by state (controls-and-input.md "Action state machine"),
# facing bit cleared: $10 jump-start -- a fixed 5-frame crouch -- then $12
# free flight, $16 jump attack, $14 land. A held-weapon jump runs the
# parallel $3C-$43 family through the same physics helpers, hence the second
# id in each set; ``decide.could_jump_attack`` declines to jump while armed
# in the first place, so those are belt-and-braces.
#
# Every state is named explicitly rather than inferred from ``is_airborne``,
# because that property spans the whole family and the states do not accept
# the same inputs at all. Two ways to get it wrong, both measured live:
#
# - **B during the crouch does nothing.** $3914 turns B into the kick only
#   from free flight, on a fresh edge of +$55 bit 4 -- but the AI re-decides
#   every ~2 frames while ``_press`` holds each button for 4, so a B issued
#   in the crouch is simply still held when free flight starts, no edge ever
#   arrives, and the actor sails through the whole arc without attacking.
# - **B on the landing frame becomes a punch.** $14 is still "airborne" by
#   that property, but the actor is on the ground by the time the press is
#   read, so it comes out as an ordinary punch aimed where the kick had been
#   heading -- 100px away, after the flight carried it there. Recorded in a
#   live run: a kick at a knocked-down enemy sliding away finished with a
#   punch thrown at empty air on touchdown.
JUMP_CROUCH_ACTIONS = frozenset({0x10, 0x3C})
JUMP_FREE_FLIGHT_ACTIONS = frozenset({0x12, 0x3E})
JUMP_ATTACK_ACTIONS = frozenset({0x16, 0x42})
JUMP_LAND_ACTIONS = frozenset({0x14, 0x40})


def _hop_without_x_carry(actor: Myself | Partner, target: Enemy) -> bool:
    """True when a directed hop at this distance would fly past ``target``.

    Antonio's punish is the grab on landing. A directed hop from inside
    punch range carries ~3 px/frame for the whole flight and lands on his
    far side, facing away -- ``grab_would_connect`` then fails (he is
    behind) and the next live tick hops again. Measured live: a full
    Antonio fight under the directed opener was 374 ``JumpAttack`` and
    0 ``GrabEnemy``.
    """

    if not isinstance(target, Antonio):
        return False
    return abs(target.world_x - actor.world_x) <= punch_outer_x(actor.character_id)


def _jump_toward(
    actor: Myself | Partner,
    target_x: int,
    gamepad: VirtualGamepad,
    *,
    horizontal: bool = True,
) -> None:
    """Hold a jump toward ``target_x`` -- launch, crouch, kick, or air steer.

    Shared by ``JumpAttack`` and a ``WalkToAdvanceStage`` hop over a pit the
    pathfinder cannot walk around. Kick in free flight: the extra hang time
    is how a hop clears a gap the walk could not.

    ``horizontal=False`` is an in-place hop: ``$384E`` reads the held
    direction at the end of the crouch, so any leftover LEFT/RIGHT from
    the walk-in becomes carry. Against Antonio inside punch range that
    carry is how the actor lands past him and never grabs.
    """

    face = 0
    if horizontal:
        face = _face_toward_mask(actor, target_x)
        if face == 0:
            face = LEFT_MASK if actor.facing_left else RIGHT_MASK
    base = actor.action_base
    if base in JUMP_FREE_FLIGHT_ACTIONS:
        _press(gamepad, PUNCH_MASK, frames=JUMP_ATTACK_KICK_FRAMES)
        if face:
            gamepad.hold(face)
        return
    if base in JUMP_CROUCH_ACTIONS:
        if face:
            gamepad.hold(face)
        else:
            gamepad.hold(0)
        return
    if base in JUMP_ATTACK_ACTIONS or base in JUMP_LAND_ACTIONS or actor.is_airborne:
        if face:
            gamepad.hold(face)
        else:
            gamepad.hold(0)
        return
    _press(gamepad, JUMP_MASK | face, frames=JUMP_ATTACK_LAUNCH_FRAMES)
    if face:
        gamepad.hold(face)


def state_machine_jump_attack(verb: JumpAttack, context: Context, gamepad: VirtualGamepad) -> None:
    """C to launch, then one clean B edge once free flight has started.

    Four distinct states, because the ROM has four and they take different
    inputs (see JUMP_CROUCH_ACTIONS above):

    - **grounded**: C plus the direction to travel in;
    - **crouch ($10)**: the direction only, *no buttons at all*;
    - **free flight ($12)**: the kick edge -- B;
    - **already kicking ($16)**: nothing to press.

    Two ROM facts drive the whole shape, and getting either wrong is a kick
    that never happens or a kick that hits nothing:

    **The launch direction must be held continuously, off the axis ramp.**
    ``$384E`` reads the held direction once, at the end of the crouch, and
    that read is the only thing that gives the kick its +-3.0 px/frame of
    carry. The crouch is 5 frames; the virtual X axis needs
    ``gamepad.AXIS_RAMP_TICKS`` (3 ticks = ~6 frames) to reach an edge, and
    ``_press`` clears the hold before every press. So anything that routes
    this through ``_hold_steered`` arrives too late and the actor jumps
    **straight up** -- measured on the flight harness: the first jump of an
    encounter never moved on X at all, kicked empty air where it stood, and
    only the *second* jump carried, because by then the axis had ramped from
    the previous flight's holds. Every branch here therefore calls
    ``gamepad.hold`` directly, exactly as the launch already did.

    **B must be a fresh edge, and only in free flight.** ``$3914`` turns B
    into the kick from free flight alone, on a rising edge of ``+$55`` bit 4.
    The AI re-decides every ~2 frames and ``_press`` holds each button for 4,
    so a B issued during the crouch is simply *still held* when free flight
    begins, produces no new edge there, and the kick never fires -- the
    reported "jumps at an enemy it could kick and never attacks". Leaving the
    crouch button-free is what guarantees the edge.
    """

    actor = _find_actor(context, verb.actor_slot)
    if actor is None:
        gamepad.release()
        return
    target = find(context, Enemy, slot=verb.target_slot)
    if target is None:
        # No target → do not hop in place.
        gamepad.release()
        return
    face = _face_toward_mask(actor, target.world_x)
    if (
        face == 0
        and not actor.is_airborne
        and actor.action_base not in (
            JUMP_CROUCH_ACTIONS | JUMP_FREE_FLIGHT_ACTIONS | JUMP_ATTACK_ACTIONS | JUMP_LAND_ACTIONS
        )
        and not isinstance(target, Antonio)
    ):
        # Already overlapping on X — punch, don't jump. Antonio is the
        # exception: overlapping him on X is exactly when the hop has to
        # go straight up over the kick/dash. A grounded B here is the
        # $16EAE zero-velocity trigger, and DodgeAntonioKick reuses this
        # handler, so the fallback would turn a dodge into a punch.
        _press(gamepad, PUNCH_MASK, frames=PUNCH_FRAMES)
        return
    _jump_toward(
        actor,
        target.world_x,
        gamepad,
        horizontal=not _hop_without_x_carry(actor, target),
    )


def state_machine_grab_enemy(verb: GrabEnemy, context: Context, gamepad: VirtualGamepad) -> None:
    """Walk into the target — direction only, never an attack button.

    Two ROM facts shape this handler (see ``reach.GRAB_RANGE_Y``). The
    contact code that becomes a hold is only reported while the actor's
    outgoing damage ``+$34`` is zero, so pressing B here would produce a hit
    instead of the grab. And the same test first requires the actor's own
    attack box to be non-empty, which is a *walking* frame's box: standing
    still touching the enemy is not enough, the actor has to keep walking
    into it. That is why the movement mask's deadband falls back to the
    facing direction instead of releasing -- at that point the two bodies
    already overlap and the last thing to do is stop pressing.
    """

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Enemy, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    # Aim at the enemy itself, with none of _walk_to_near_enemy_target's stop
    # buffer: overlapping is the whole point of this verb. Lead the walk-in
    # (_aim_point) rather than chasing the enemy's current position -- the
    # walk takes as long as it takes, and steering at where the body already
    # was is what turns a pursuit into a tail-chase.
    aim = _aim_point(verb, actor, target)
    mask = _movement_mask(context, actor.world_x, actor.world_y, aim.world_x, aim.world_y)
    if not mask & (LEFT_MASK | RIGHT_MASK):
        mask |= _face_toward_mask(actor, aim.world_x) or (
            LEFT_MASK if actor.facing_left else RIGHT_MASK
        )
    _hold_steered(gamepad, mask)


def state_machine_supplex(verb: Supplex, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, verb.actor_slot)
    if actor is None:
        gamepad.release()
        return
    base = actor.action_base
    if base == 0x66:
        _press(gamepad, PUNCH_MASK, frames=SUPPLEX_FRAMES)
    elif base == 0x60:
        # Should have been FlipHold, but finish the crossover if we land here.
        _press(gamepad, JUMP_MASK, frames=SUPPLEX_FRAMES)
    else:
        _press(gamepad, PUNCH_MASK, frames=SUPPLEX_FRAMES)


def state_machine_attack_held_enemy(verb: AttackHeldEnemy, context: Context, gamepad: VirtualGamepad) -> None:
    # Front-hold B alone (Up/Down ignored by ROM for throw; no L/R = knee).
    # The cleared hold matters here: a leftover walk direction would turn this
    # knee into the B+back throw below.
    _press(gamepad, PUNCH_MASK, frames=HOLD_FRAMES)


def state_machine_throw_held_enemy(verb: ThrowHeldEnemy, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, verb.actor_slot)
    if actor is None:
        gamepad.release()
        return
    # B + back (L/R opposite facing) — controls-and-input.md hold section.
    back = _back_direction_mask(actor)
    _press(gamepad, PUNCH_MASK | back, frames=HOLD_FRAMES)


def state_machine_flip_hold(verb: FlipHold, context: Context, gamepad: VirtualGamepad) -> None:
    # Front-hold C → back hold $66; next tick Supplex finishes.
    _press(gamepad, JUMP_MASK, frames=HOLD_FRAMES)


def state_machine_release_grab(verb: ReleaseGrab, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Enemy, slot=verb.target_slot)
    if actor is None:
        gamepad.release()
        return
    if target is None:
        # Walk opposite current facing to break the link.
        mask = _back_direction_mask(actor)
        _hold_steered(gamepad, mask)
        return
    # Walk away from the held body. Within DIRECTION_HYSTERESIS_X, use
    # facing (same fallback as the target-is-None branch above) instead of
    # the raw compare -- the two bodies are still overlapping right after a
    # release, so a couple of px of jitter would otherwise flip which way is
    # "away" every tick.
    dx = target.world_x - actor.world_x
    if abs(dx) <= DIRECTION_HYSTERESIS_X:
        # Same convention as _back_direction_mask above: right when facing left.
        away_right = actor.facing_left
    else:
        away_right = dx < 0
    away_x = actor.world_x + (20 if away_right else -20)
    _hold_steered(
        gamepad,
        _movement_mask(context, actor.world_x, actor.world_y, away_x, actor.world_y),
    )


def _throw_ranged_weapon(verb: Verb, context: Context, gamepad: VirtualGamepad, *, frames: int) -> None:
    """Shared body for ``ThrowKnife``/``ThrowPepper``: identical B press
    aimed at the interception point, differing only in the frame count."""

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Enemy, slot=verb.target_slot)
    face = 0
    if actor is not None and target is not None:
        face = _face_toward_mask(actor, _aim_point(verb, actor, target).world_x)
    _press(gamepad, PUNCH_MASK | face, frames=frames)


def state_machine_throw_knife(verb: ThrowKnife, context: Context, gamepad: VirtualGamepad) -> None:
    _throw_ranged_weapon(verb, context, gamepad, frames=THROW_KNIFE_FRAMES)


def state_machine_throw_pepper(verb: ThrowPepper, context: Context, gamepad: VirtualGamepad) -> None:
    _throw_ranged_weapon(verb, context, gamepad, frames=THROW_PEPPER_FRAMES)


def _walk_to_item(verb: Verb, context: Context, gamepad: VirtualGamepad, target_type: type) -> None:
    """Shared body for ``WalkToWeapon``/``WalkToPickup``: identical arrival
    test (press once inside pickup range, otherwise keep closing) --
    differing only in which token type the target slot resolves to.

    The walk itself is routed (``_routed_mask``) the same way
    ``state_machine_walk_to_near_enemy`` is, but this is the simplest of the
    routed approaches: no side-selection subtlety, and unlike a punch's
    annulus (a dead zone under the fist), standing on top of a weapon or
    pickup is exactly the point. The goal reuses ``strike_goal`` with
    ``inner_dx=0`` (one plain region, not a two-sided band) and
    ``stop_dx``/``lane_slack`` set to ``PICKUP_RANGE_X``/``PICKUP_RANGE_Y`` --
    not a ``PointGoal`` with a single scalar tolerance, because that would
    grow the arrival test symmetrically on both axes and stop disagreeing
    with the asymmetric ``PICKUP_RANGE_X``/``_Y`` check above only by
    accident. Measured on this very approach: a ``PointGoal`` tolerance wide
    enough to satisfy the X axis let the router call the goal "reached" (and
    the route mask go quiet) up to 4px short on Y, freezing the actor there
    forever since ``_routed_mask`` never falls back once ``goal.is_reached``
    is true. ``strike_goal``'s region is built from the same
    origin-vs-threshold sentence the check above already states, so the two
    can never disagree. Every live enemy and its active reach is an obstacle
    (``nav.obstacle_sets``' danger pass), which is the bug this fixes: the
    old straight line had no enemy awareness at all, so grabbing a pickup
    could walk straight through a live enemy's body or its active attack
    band when a slightly longer route around it existed.
    """

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, target_type, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    if abs(target.world_x - actor.world_x) <= PICKUP_RANGE_X and abs(target.world_y - actor.world_y) <= PICKUP_RANGE_Y:
        _press(gamepad, PUNCH_MASK, frames=PUNCH_FRAMES)
        return

    goal = nav.strike_goal(
        nav.body_rect(actor),
        actor.world_x,
        actor.world_y,
        target.world_x,
        target.world_y,
        stop_dx=PICKUP_RANGE_X,
        lane_slack=PICKUP_RANGE_Y,
    )
    body, origin = nav.actor_footprint(actor)
    solids, dangers = nav.obstacle_sets(context, body=body, origin=origin)

    def straight_line() -> int:
        return _movement_mask(
            context, actor.world_x, actor.world_y, target.world_x, target.world_y
        )

    _hold_steered(
        gamepad,
        _routed_mask(
            context,
            actor,
            goal,
            solids=solids,
            dangers=dangers,
            fallback=straight_line,
        ),
    )


def state_machine_walk_to_weapon(verb: WalkToWeapon, context: Context, gamepad: VirtualGamepad) -> None:
    _walk_to_item(verb, context, gamepad, Weapon)


def state_machine_walk_to_pickup(verb: WalkToPickup, context: Context, gamepad: VirtualGamepad) -> None:
    _walk_to_item(verb, context, gamepad, Pickup)


def _walk_to_breakable_target(
    actor: Myself | Partner, target: Breakable, context: Context
) -> tuple[int, int]:
    """Stopping point for approaching ``target``: a Breakable is a solid
    obstacle, so stop just inside smash range on whichever side the actor
    already occupies rather than walking to the breakable's exact (and
    unreachable) center.

    Smash range is a *side* pocket (same lane, X offset). A straight line
    from above or below the crate to that pocket cuts through the solid, so
    while the actor still shares the prop's blocking X column the Y target
    is held at the actor's own lane -- walk out to the smash X first, then
    converge on Y from the side. Without that around-path the actor pins
    itself against the body and never arrives at a point that can punch.

    Standing essentially *on* the prop, which side that is has to be decided
    by something the AI does not itself change every tick. Reading it off
    ``actor.facing_left`` -- the idiom ``_walk_to_near_enemy_target`` uses --
    is a facing-feedback loop here, because unlike an enemy a prop never
    moves to break the symmetry: press left, facing goes left, the stop point
    jumps to the far side, press right, facing goes right, and back. Measured
    live: **107 seconds** of a 200s run at one prop, LEFT held on 244 ticks
    and RIGHT on 240, the virtual steering axis cancelling almost all of it
    (2242 ticks with no direction on the pad at all) while the actor never
    moved a pixel on X.

    The stage's own progress direction is the anchor instead: fixed for the
    whole level, so it cannot oscillate, and it leaves the actor on the side
    it is coming from -- already lined up to carry on once the prop is gone.

    Stage 7 (``AI.md``: "in stage 7, progression does not require lateral
    movement") reports ``direction == "none"``, which has no lateral anchor
    to read. Falling back to ``actor.facing_left`` there -- as this used to
    -- reintroduces the exact live-measured oscillation above, since a
    stage-7 breakable is exactly the "dx within hysteresis" case this whole
    branch exists for. So "none" gets the same fixed, non-input-derived
    answer as "right" rather than the feedback-prone one: stable is more
    important than which side, and either side reaches smash range equally
    well from dead center.
    """

    # Inside the prop's own reach window: near enough that in_smash_range is
    # true, far enough that the push-back rectangle is not what stops the
    # walk. Aiming at the reach minus the deadband buffer alone put the stop
    # point *inside* the wall for every prop whose wall is wider than that,
    # leaving the actor to arrive by bumping into it.
    outer = breakable_smash_outer_x(target)
    wall = prop_solids.solid_half_width(target.type_id)
    stop_dx = max(0, min(outer, max(outer - BREAKABLE_STOP_BUFFER, wall + BREAKABLE_WALL_GAP_X)))
    dx = target.world_x - actor.world_x
    if abs(dx) <= DIRECTION_HYSTERESIS_X:
        stage = find(context, Stage)
        direction = stage.direction if stage is not None else "right"
        approach_from_right = direction == "left"
    else:
        approach_from_right = dx < 0
    target_x = target.world_x + stop_dx if approach_from_right else target.world_x - stop_dx
    # Smash range is a side pocket (same lane, X offset). Walking a
    # straight line from above/below the crate to that pocket cuts through
    # the solid -- the actor pins itself against the body and never arrives.
    # While still sharing the prop's blocking X column, hold Y and walk out
    # to the smash X first; the next tick, now beside it, converges on Y.
    # ``at_smash_x`` is the escape for a stop point that still lands inside
    # the column plus its slack: once X has arrived, Y must be allowed to
    # move or the actor freezes off-lane.
    lo_x, hi_x = _breakable_block_x(target)
    in_column = (
        lo_x - BREAKABLE_AROUND_SLACK_X
        <= actor.world_x
        <= hi_x + BREAKABLE_AROUND_SLACK_X
    )
    at_smash_x = abs(actor.world_x - target_x) <= MOVE_DEADBAND_X
    if in_column and not at_smash_x:
        return target_x, actor.world_y
    return target_x, target.world_y


def state_machine_open_breakable(
    verb: OpenBreakable, context: Context, gamepad: VirtualGamepad
) -> None:
    """Close the distance, then hit it -- one verb, both halves.

    The switch is ``decide.in_smash_range``, the same predicate
    ``priority._emergency_open_breakable`` scores with, so the tier the verb
    won on and the action it takes can never describe different situations.

    The approach ``maximize_contact``s: a crate does not move, so there is
    nothing to lose by spending a step or two lining the punch band up square
    with its face, and a lot to lose by arriving at the corner of the smash
    pocket -- the strike then depends on a lane the actor is only just inside
    of. It is the opposite trade from an enemy approach, and for the opposite
    reason: the target holds still.

    In range but facing the wrong way (``_facing_prop``) is answered by a
    small routed walk toward the correct side rather than turning in place:
    this game has no turn-without-walking input, and every reliable facing
    change elsewhere in this codebase is a side effect of holding a
    direction through ``_hold_steered``, never a bare press -- measured
    live, a one-frame turn-only press left the actor frozen at the same
    position and action byte for 60 seconds. The nudge target is
    deliberately *not* ``_walk_to_breakable_target``'s far-approach pocket:
    that stop point is anchored near the band's outer edge for the "still
    walking in" case and can sit on the far side of a position that is
    already perfectly good to strike from, which would walk the actor back
    out of range just to fix facing. ``BREAKABLE_FACE_NUDGE_X`` is sized
    only to clear the movement deadband, small enough to stay inside the
    punch band it is already standing in -- but a raw straight-line step
    that size is not itself obstacle-aware, and a tight corridor (stage 5's
    2x2 prop fence, 16px between rows) can put another prop's push-back box
    right there: caught live by ``Stage5PropFenceTests`` walking a nudge
    straight into the neighbour's wall. Routed the same way every other
    small positional correction in this file is (``_retreat_from_danger_
    target``'s idiom: a ``PointGoal`` plus ``nav.obstacle_sets``), so the
    pathfinder steps around a solid instead of into it.

    The crate is exempt from its own obstacle set (``ignore``) -- it is the
    destination, not something to route around -- while every *other* crate
    and pit still is, which is what replaces the hand-written around-path
    this used to need to get out of the prop's own column.
    """

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Breakable, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return

    if in_smash_range(actor, target):
        if not _facing_prop(actor, target):
            face = _face_prop_mask(actor, target, context)
            toward_target = BREAKABLE_FACE_NUDGE_X if face == RIGHT_MASK else -BREAKABLE_FACE_NUDGE_X
            # A step toward the target is also a step toward the punch
            # band's own inner dead zone -- and right at
            # DIRECTION_HYSTERESIS_X, which is exactly punch_usable_inner_x
            # for Axel, there is no headroom left at all. Stepping in
            # anyway crossed below the true inner edge, in_smash_range's
            # own recovery walked straight back out to the edge it just
            # left (undoing the very turn that recovery was answering), and
            # the two alternated forever -- caught live driving the exact
            # dx == DIRECTION_HYSTERESIS_X geometry the original stall had.
            # Backing away first (away from the target, which does not
            # touch facing since it is the same direction the actor is
            # already -- wrongly -- facing) buys room for a real toward-
            # target step next tick that lands *at* the inner edge rather
            # than past it.
            headroom = abs(target.world_x - actor.world_x) - punch_usable_inner_x(
                actor.character_id
            )
            nudge_x = toward_target if headroom >= BREAKABLE_FACE_NUDGE_X else -toward_target
            # ...but never into the camera's walk clamp. `$43AA` simply undoes
            # a step past `camera_x + $20`, so the route comes back as a vector
            # `_clamp_mask` then strips, and `_routed_mask` does not reach its
            # fallback because the goal is not what failed -- the mask is. The
            # result is a **permanent** freeze: in smash range, facing away,
            # commanding nothing. Recorded live at world x=2458 against a
            # round-1 booth: 6919 consecutive ticks, mask `0x0` on every one,
            # `OpenBreakable` winning every tick and the prop untouched.
            #
            # Backing away is only ever the *preferred* half of this nudge (it
            # buys room for a clean toward-step next tick, see above); toward
            # the prop still fixes facing, which is the whole job here. So a
            # blocked away-step becomes a toward-step rather than nothing.
            away_bit = LEFT_MASK if nudge_x < 0 else RIGHT_MASK
            if not _clamp_mask_to_camera(context, actor.world_x, away_bit):
                nudge_x = toward_target
            nudge_x_target = actor.world_x + nudge_x
            nudge_goal = PointGoal(Point(nudge_x_target, actor.world_y), tolerance=MOVE_DEADBAND_X)
            body, origin = nav.actor_footprint(actor)
            solids, dangers = nav.obstacle_sets(context, body=body, origin=origin)

            def face_nudge_straight_line() -> int:
                return _movement_mask(
                    context,
                    actor.world_x,
                    actor.world_y,
                    nudge_x_target,
                    actor.world_y,
                    ignore_slots=frozenset({target.slot}),
                )

            nudge_mask = _routed_mask(
                context,
                actor,
                nudge_goal,
                solids=solids,
                dangers=dangers,
                fallback=face_nudge_straight_line,
            )
            # The invariant this branch cannot give up: it exists to change
            # facing, facing only changes by holding a direction, so
            # commanding nothing is never a valid outcome here. Any remaining
            # way to reach an empty mask -- a clamp on the far side, a route
            # boxed in by props -- ends in the one direction that is always
            # both meaningful and available: toward the prop itself.
            _hold_steered(gamepad, nudge_mask or _clamp_mask(
                context, actor.world_x, actor.world_y, face
            ))
            return
        _press(
            gamepad,
            PUNCH_MASK | _face_prop_mask(actor, target, context),
            frames=PUNCH_FRAMES,
        )
        return

    # The crate stays in its own obstacle set. It is the destination *and* a
    # solid, and dropping it -- the way an approached enemy is dropped --
    # routes the actor straight through it: from directly above, the shortest
    # line to the smash pocket is down through the box. The goal is the
    # pocket beside it, so the two never contradict each other.
    # Standing essentially on the prop, the two sides cost the same and the
    # search picks one arbitrarily -- which is how the actor ended up *past*
    # the crate, where ``could_open_breakable`` stops calling it "ahead" and
    # hands the tick to WalkToAdvanceStage, back into the crate, forever. So
    # the tie is broken the way the straight-line approach already breaks it:
    # by the stage's own progress direction, fixed for the whole level and
    # therefore unable to oscillate, leaving the actor on the side it is
    # coming from. Anywhere else the sides genuinely differ, and cost decides.
    side = "both"
    if abs(target.world_x - actor.world_x) <= DIRECTION_HYSTERESIS_X:
        stage = find(context, Stage)
        direction = stage.direction if stage is not None else "right"
        side = "right" if direction == "left" else "left"
    goal = nav.strike_goal(
        nav.body_rect(actor),
        actor.world_x,
        actor.world_y,
        target.world_x,
        target.world_y,
        stop_dx=breakable_smash_outer_x(target),
        lane_slack=BREAKABLE_APPROACH_Y,
        inner_dx=punch_usable_inner_x(actor.character_id),
        side=side,
    )
    body, origin = nav.actor_footprint(actor)
    solids, dangers = nav.obstacle_sets(context, body=body, origin=origin)

    def straight_line() -> int:
        target_x, target_y = _walk_to_breakable_target(actor, target, context)
        return _movement_mask(
            context,
            actor.world_x,
            actor.world_y,
            target_x,
            target_y,
            ignore_slots=frozenset({target.slot}),
        )

    _hold_steered(
        gamepad,
        _routed_mask(
            context,
            actor,
            goal,
            solids=solids,
            dangers=dangers,
            maximize_contact=True,
            fallback=straight_line,
        ),
    )


_HANDLERS = {
    WalkToNearEnemy: state_machine_walk_to_near_enemy,
    RetreatFromDanger: state_machine_retreat_from_danger,
    ProjectileSidestep: state_machine_projectile_sidestep,
    DodgeAntonioKick: state_machine_dodge_antonio_kick,
    DodgeSoutherSlash: state_machine_dodge_souther_slash,
    HitAntonioBoomerang: state_machine_hit_antonio_boomerang,
    WalkToAdvanceStage: state_machine_walk_to_advance_stage,
    Punch: state_machine_melee_strike,
    MeleeWeaponAttack: state_machine_melee_strike,
    RearAttack: state_machine_rear_attack,
    CounterGrab: state_machine_counter_grab,
    TechRecover: state_machine_tech_recover,
    CallPolice: state_machine_call_police,
    HandleContinueMenu: state_machine_handle_continue_menu,
    HandleMrXDialog: state_machine_handle_mr_x_dialog,
    JumpAttack: state_machine_jump_attack,
    GrabEnemy: state_machine_grab_enemy,
    Supplex: state_machine_supplex,
    AttackHeldEnemy: state_machine_attack_held_enemy,
    ThrowHeldEnemy: state_machine_throw_held_enemy,
    FlipHold: state_machine_flip_hold,
    ReleaseGrab: state_machine_release_grab,
    ThrowKnife: state_machine_throw_knife,
    ThrowPepper: state_machine_throw_pepper,
    WalkToWeapon: state_machine_walk_to_weapon,
    WalkToPickup: state_machine_walk_to_pickup,
    OpenBreakable: state_machine_open_breakable,
}


def execute_verb(verb: Verb, context: Context, gamepad: VirtualGamepad) -> None:
    handler = _HANDLERS.get(type(verb))
    if handler is None:
        press_no_button(gamepad)
        return
    handler(verb, context, gamepad)


def _pit_escape_mask(context: Context, actor: Myself) -> int | None:
    """A movement mask that walks ``actor`` clear of a ``Pit``'s danger zone
    it currently stands in, or ``None`` when it doesn't.

    Falling in costs a full life (player-health-lives-and-combat.md's
    ``$01C0`` fall-boundary check). Every *other* pit-awareness in this
    module only ever comes up incidentally, mid-route to some unrelated
    destination -- nothing reacts to the actor already standing in the
    danger zone with no walk verb underway to steer it. This is that
    reaction; see ``execute_tick``.

    The actual escape geometry -- freeze X, clear Y first (a pit is a
    rectangle, not a line: moving both axes at once can still cut through
    it) -- lives in ``_movement_mask``'s own pit-dodge loop, the one
    definition of that behaviour. So this only has to hand it a target on
    the far side of the pit along X; ``_movement_mask`` recognises the same
    pit sits between here and there and takes over from there. Which side
    is arbitrary -- ``execute_tick`` re-checks ``pit_endangers`` fresh every
    tick and stops calling this the moment the actor clears the pit on
    *either* axis, which ``_movement_mask``'s Y-first dodge always reaches
    well before X could ever travel as far as this target.

    Never returns 0 while ``pit_endangers`` holds. ``_movement_mask`` is
    built to guarantee that on its own (``PIT_DODGE_OVERSHOOT``), but this
    is the one place in the whole pipeline where "the actor believes it is
    in a pit" is known for certain -- so it is also the right place to
    refuse categorically to hand back "do nothing" for that belief,
    independent of whatever combination of deadbands and margins produced
    it. Freezing a few pixels short of safety while still convinced it is
    in danger is exactly the deadlock this rules out, live-diagnosed.
    """

    for pit in find_all(context, Pit):
        if not pit_endangers(pit, actor.world_x, actor.world_y):
            continue
        pit_center_x = pit.world_x + pit.width / 2
        if actor.world_x < pit_center_x:
            far_x = pit.world_x + pit.width + PIT_AVOID_MARGIN + MOVE_DEADBAND_X + 1
        else:
            far_x = pit.world_x - PIT_AVOID_MARGIN - MOVE_DEADBAND_X - 1
        mask = _movement_mask(context, actor.world_x, actor.world_y, far_x, actor.world_y)
        if mask != 0:
            return mask
        # Same side ``_movement_mask``'s own dodge would have chosen, so the
        # two can never disagree about which way out is which. This used to
        # read `DOWN if actor.world_y < pit_center_y else UP`, which is the
        # direction *toward* the pit's centre -- the exact opposite of this
        # fallback's own stated job, and a push deeper into the hole on the
        # one tick the pipeline is certain the actor is standing in one.
        target_y = _pit_dodge_target_y(context, pit, actor.world_y)
        if target_y != actor.world_y:
            return DOWN_MASK if target_y > actor.world_y else UP_MASK
        pit_center_y = pit.lane_y + pit.height / 2
        return UP_MASK if actor.world_y < pit_center_y else DOWN_MASK
    return None


def execute_tick(
    verb: Verb | None,
    context: Context,
    gamepad: VirtualGamepad,
    *,
    route_trace: dict[str, Path] | None = None,
) -> None:
    """The one place every tick's controller output actually comes from --
    ``AgentLoop.tick`` calls this instead of choosing between
    ``press_no_button``/``execute_verb`` itself, so the pit override below
    applies whichever of those two the rest of the pipeline would otherwise
    have reached.

    Pit danger is deliberately not a ``Verb`` decide.py/priority.py rank
    against everything else: it is a constraint on *how* the actor is
    allowed to move right now, the same kind of thing ``_movement_mask``'s
    own pit/breakable dodge already is for a walk verb's path, not a
    competing intent. Overriding here, unconditionally, is what makes it
    apply regardless of which verb -- if any -- won this tick, including
    a plain melee strike or no verb at all, neither of which any Pit token
    reaches otherwise.

    ``route_trace``, keyed by actor slot, is filled with the planner's most
    recent :class:`~sor_autoplay.ai.pathfind.Path` whenever a routed handler
    (``WalkToNearEnemy``, ``OpenBreakable`` today) actually plans one --
    HUD-only, never read back into the pipeline. Omitted (the default),
    nothing records anything and this call is exactly as before.
    """

    token = _ROUTE_TRACE.set(route_trace) if route_trace is not None else None
    try:
        actor = find(context, Myself)
        # A jump flies over pits in Z. pit_endangers is a lane-plane test,
        # so mid-air it reads "standing in the hole" the moment X overlaps
        # and this override would freeze the launch vx -- the stage-4
        # suicide when the kick was actually clearing the gap. Grounded
        # only: once airborne the trajectory is committed.
        if actor is not None and not actor.is_airborne:
            mask = _pit_escape_mask(context, actor)
            if mask is not None:
                _hold_steered(gamepad, mask)
                return
        if verb is None:
            press_no_button(gamepad)
            return
        execute_verb(verb, context, gamepad)
    finally:
        if token is not None:
            _ROUTE_TRACE.reset(token)
