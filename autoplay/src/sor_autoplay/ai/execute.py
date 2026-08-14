"""``execute_verb`` — dispatch the surviving ``Verb`` to controller input.

Per ``AI.md``: each handler steers the controller only as much as necessary
and returns immediately — never blocks/sleeps waiting for the verb to
play out.

CRITICAL button mapping (original scheme): Attack/Punch = physical B (0x0020),
Police special = physical A (0x0010), Jump = physical C (0x0040).
"""

from __future__ import annotations

from .tokens import (
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
from .tokens import (
    Myself,
    Partner,
    PUNCH_RANGE_Y,
    punch_inner_x,
    punch_outer_x,
    punch_usable_inner_x,
)
from .tokens import Enemy
from .tokens import CameraRange, Stage
from .tokens import Breakable, Pit, Projectile, SafeSpot
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
    BREAKABLE_BLOCK_X,
    BREAKABLE_PUNCH_X,
    BREAKABLE_PUNCH_Y,
    in_smash_range,
)
from .reach import (
    PIT_AVOID_MARGIN,
    REACH_SAFETY_MARGIN,
    enemy_behind_actor,
    enemy_lane_covers,
    pit_endangers,
)
from ..phases import is_dangerous
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
BREAKABLE_AVOID_Y = 22
# Pit clearance (reach.PIT_AVOID_MARGIN) stays smaller than BREAKABLE_AVOID_Y
# only because the pit's real height is already added on top of it (see the
# dodge loop below). It is shared with inference.check_for_safe_spots, which
# must reject the same ground this steers around.
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
    """X span the actor cannot walk through.

    The prop's real body when we have one (``Breakable.hitbox``), otherwise
    the ``BREAKABLE_BLOCK_X`` margin around its origin -- the constant
    ``decide.py`` already named for this and nothing else was reading.
    """

    box = prop.hitbox
    if box is not None and not box.is_degenerate:
        return box.x0, box.x1
    return prop.world_x - BREAKABLE_BLOCK_X, prop.world_x + BREAKABLE_BLOCK_X


def _clamp_mask_to_lane(context: Context, from_y: int, mask: int) -> int:
    """Never hold into the lane clamp."""

    lo, hi = _lane_bounds(context)
    if from_y >= hi:
        mask &= ~DOWN_MASK
    if from_y <= lo:
        mask &= ~UP_MASK
    return mask


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

    mask = nav.route_mask(
        context,
        actor,
        goal,
        solids=solids,
        dangers=dangers,
        enough_contact=enough_contact,
        maximize_contact=maximize_contact,
    )
    if not mask and not goal.is_reached(nav.body_rect(actor)):
        mask = fallback()
    return _clamp_mask_to_lane(context, actor.world_y, mask)


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
        if abs(prop.world_y - from_y) > BREAKABLE_AVOID_Y and abs(prop.world_y - to_y) > BREAKABLE_AVOID_Y:
            continue
        if abs(prop.world_x - from_x) > abs(to_x - from_x):
            continue
        # Step vertically around the prop (prefer away from lane edge).
        lo, hi = _lane_bounds(context)
        if from_y < (lo + hi) / 2:
            to_y = _clamp_target_y(context, prop.world_y + BREAKABLE_AVOID_Y)
        else:
            to_y = _clamp_target_y(context, prop.world_y - BREAKABLE_AVOID_Y)

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

    return _clamp_mask_to_lane(context, from_y, mask)


def _face_toward_mask(actor: Myself | Partner, target_x: int) -> int:
    dx = target_x - actor.world_x
    if dx < -DIRECTION_HYSTERESIS_X:
        return LEFT_MASK
    if dx > DIRECTION_HYSTERESIS_X:
        return RIGHT_MASK
    return 0


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
    the pocket -- ``reach.in_enemy_dead_zone``, ``GrabIntoDeadZone`` -- but
    the approach that decides where to *stand* never consulted it.

    So when the pocket exists and the actor can still land its own strike
    from inside it, aim there instead. The floor is the punch's usable inner
    edge: closer than that and the pocket is safe but unhittable, which is
    the grab's business (``GrabIntoDeadZone``), not this walk's. The margin
    matches ``reach``'s own, so "inside the dead zone" means the same thing
    to the verb that walks there and to the predicate that judges it.
    """

    dead_zone = target.min_reach
    if dead_zone <= 0:
        return stop_dx
    inside = dead_zone - REACH_SAFETY_MARGIN
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

    dx = abs(target.world_x - actor.world_x)
    dy = abs(target.world_y - actor.world_y)
    if dx <= stop_dx:
        # Arrived on X. Converge onto the enemy's lane so the punch lands
        # (dy must clear PUNCH_RANGE_Y) -- this is the only place that aims
        # at the enemy's own lane, and by now the approach is over.
        target_y = target.world_y
    elif is_dangerous(target.combat_phase) and dy < WALK_TO_ENEMY_LANE_SAFETY_Y:
        # Still approaching a committed enemy and standing in its line of
        # attack: leave the line, aiming at a *fixed* lane rather than a
        # displacement from the actor's own, so repeated ticks converge on
        # one point instead of stepping away forever.
        lo, hi = _lane_bounds(context)
        offset = (
            WALK_TO_ENEMY_LANE_SAFETY_Y
            if target.world_y >= (lo + hi) / 2
            else -WALK_TO_ENEMY_LANE_SAFETY_Y
        )
        target_y = target.world_y + offset
    else:
        # Still approaching, and not standing in a committed enemy's line:
        # hold the current lane.
        #
        # This branch used to aim at ``target.world_y`` -- converge onto the
        # enemy's lane from however far away. Combined with the branch above
        # that made the lane aim flip by a full
        # ``2 * WALK_TO_ENEMY_LANE_SAFETY_Y`` every time the enemy's phase
        # crossed ``is_dangerous``, which in a real fight is every few ticks:
        # commit -> sidestep off the lane, recover -> converge back onto it,
        # commit again -> back off. Measured on the tick harness as a steady
        # UP/DOWN alternation for the whole approach, and the last source of
        # the reported up/down darting after the target churn was fixed.
        #
        # Holding the lane removes the phase dependence entirely while still
        # serving the original intent better than converging did: the actor
        # simply never walks down the enemy's line in the first place, which
        # is what the sidestep above was compensating for after the fact.
        target_y = actor.world_y

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
    lives here -- the punch's own outer edge, and the dead-zone pocket some
    enemies have (``_dead_zone_stop_dx``) -- while the route itself is
    geometry the path finder owns.
    """

    outer = punch_outer_x(actor.character_id, actor.held_weapon_type)
    inner = punch_inner_x(actor.character_id)
    return _dead_zone_stop_dx(actor, target, max(inner, outer - WALK_TO_ENEMY_STOP_BUFFER))


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
    alongside = abs(target.world_x - actor.world_x) <= stop_dx
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
        target.world_y if alongside else actor.world_y,
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
    solids, dangers = nav.obstacle_sets(
        context,
        block_x=BREAKABLE_BLOCK_X,
        body=nav.body_rect(actor),
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
# being a single-tick teleport.
RETREAT_FROM_DANGER_DISTANCE = 32


def _retreat_from_danger_target(
    actor: Myself | Partner, target: Enemy, context: Context
) -> tuple[int, int]:
    """Where to back off to.

    Prefers the ``SafeSpot`` inference for this actor: it has already
    weighed the sidesteps against the straight retreat by clearance from
    every live enemy, and rejected candidates that leave the lane, leave the
    camera, or land on a pit. Falls back to stepping directly away from
    ``target`` on X, holding the current lane, when no safe spot was found
    -- backing off blindly still beats standing in the attack.

    Within ``DIRECTION_HYSTERESIS_X`` of the target, which way is "away" is
    read off ``actor.facing_left`` instead of the live position compare --
    the same reasoning as ``_walk_to_near_enemy_target``'s own X pick: this
    close, the raw compare is noise, and flipping it flips the full
    ``2 * RETREAT_FROM_DANGER_DISTANCE`` retreat direction on a spurious
    tick.
    """

    for spot in find_all(context, SafeSpot):
        if spot.actor_slot == actor.slot:
            return spot.world_x, spot.world_y

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
    _walk_toward_target(verb, context, gamepad, Enemy, _retreat_from_danger_target)


# How far to step off a projectile's lane per tick -- comfortably past
# inference.PROJECTILE_LANE_SLACK (24) so the step actually clears the band
# check_for_incoming_projectiles used to judge the throw a threat, rather
# than landing just inside it.
PROJECTILE_SIDESTEP_DISTANCE = 40


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
        target_y = actor.world_y + PROJECTILE_SIDESTEP_DISTANCE
    else:
        target_y = actor.world_y - PROJECTILE_SIDESTEP_DISTANCE
    return actor.world_x, target_y


def state_machine_projectile_sidestep(
    verb: ProjectileSidestep, context: Context, gamepad: VirtualGamepad
) -> None:
    _walk_toward_target(verb, context, gamepad, Projectile, _projectile_sidestep_target)


def state_machine_dodge_antonio_kick(
    verb: DodgeAntonioKick, context: Context, gamepad: VirtualGamepad
) -> None:
    """Hop over the kick/dash, then kick.

    A ground sidestep never leaves the ROM's X-velocity kick gate
    (measured: minutes of sidestep, 0 damage dealt). Reuses the jump-
    kick state machine so the airborne B edge punishes.
    """

    state_machine_jump_attack(verb, context, gamepad)


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
    actor = _find_actor(context, verb.actor_slot)
    if actor is None:
        _hold_steered(gamepad, RIGHT_MASK if verb.direction == "right" else LEFT_MASK)
        return
    # Pure lateral advance — do not add accidental Up/Down.
    mask = RIGHT_MASK if verb.direction == "right" else LEFT_MASK
    # If a breakable sits immediately ahead, approach with a slight Y offset
    # so the next tick can smash rather than walk forever into it. The 40px
    # lookahead always clears MOVE_DEADBAND_X, so _movement_mask's own L/R
    # bit always agrees with the plain `mask` fallback -- `or mask` only
    # ever matters for its Y bits' side effects, never for overriding a
    # direction the axis hasn't reached full deflection on yet.
    ahead_x = actor.world_x + (40 if verb.direction == "right" else -40)
    _hold_steered(
        gamepad,
        _movement_mask(context, actor.world_x, actor.world_y, ahead_x, actor.world_y) or mask,
    )


def state_machine_melee_strike(verb: Verb, context: Context, gamepad: VirtualGamepad) -> None:
    """Shared handler for ``Punch`` / ``SwingBatOrPipe`` /
    ``StabWithKnifeOrBottle`` / ``SprayPepper`` -- identical B-button press
    regardless of which (if any) weapon is held; only the ROM-side move that
    resolves from it differs."""

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
    base = actor.action_base

    if base in JUMP_FREE_FLIGHT_ACTIONS:
        # The one state the kick edge works from. Pressed on its own, with
        # the direction re-held afterwards -- _press clears the hold, and air
        # steer ($38C0) still reads it for the rest of the flight.
        _press(gamepad, PUNCH_MASK, frames=JUMP_ATTACK_KICK_FRAMES)
        gamepad.hold(face)
        return
    if base in JUMP_CROUCH_ACTIONS:
        # Hold the travel direction for $384E to read, and leave every button
        # alone so the B that starts the kick is a fresh edge.
        gamepad.hold(face or (LEFT_MASK if actor.facing_left else RIGHT_MASK))
        return
    if base in JUMP_ATTACK_ACTIONS or base in JUMP_LAND_ACTIONS or actor.is_airborne:
        # Already kicking (it stays active until landing), touching down, or
        # any other airborne state: nothing to press. Keep the air steer.
        gamepad.hold(face)
        return
    if face == 0:
        # Already overlapping on X — punch, don't jump.
        _press(gamepad, PUNCH_MASK, frames=PUNCH_FRAMES)
        return
    # Grounded: launch, then hold the direction through the crouch.
    _press(gamepad, JUMP_MASK | face, frames=JUMP_ATTACK_LAUNCH_FRAMES)
    gamepad.hold(face)


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
    differing only in which token type the target slot resolves to."""

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, target_type, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    if abs(target.world_x - actor.world_x) <= PICKUP_RANGE_X and abs(target.world_y - actor.world_y) <= PICKUP_RANGE_Y:
        _press(gamepad, PUNCH_MASK, frames=PUNCH_FRAMES)
    else:
        _hold_steered(
            gamepad,
            _movement_mask(
                context, actor.world_x, actor.world_y, target.world_x, target.world_y
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

    stop_dx = max(0, BREAKABLE_PUNCH_X - BREAKABLE_STOP_BUFFER)
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
    # ``at_smash_x`` is the escape when the smash pocket itself sits inside
    # the fallback column (BREAKABLE_BLOCK_X is wider than stop_dx): once
    # X has arrived, Y must be allowed to move or the actor freezes off-lane.
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
        _press(gamepad, PUNCH_MASK | _face_toward_mask(actor, target.world_x), frames=PUNCH_FRAMES)
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
        stop_dx=BREAKABLE_PUNCH_X,
        lane_slack=BREAKABLE_PUNCH_Y,
        inner_dx=punch_usable_inner_x(actor.character_id),
        side=side,
    )
    solids, dangers = nav.obstacle_sets(
        context,
        block_x=BREAKABLE_BLOCK_X,
        body=nav.body_rect(actor),
        keep_reachable_within=BREAKABLE_PUNCH_X,
    )

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
    HitAntonioBoomerang: state_machine_hit_antonio_boomerang,
    WalkToAdvanceStage: state_machine_walk_to_advance_stage,
    Punch: state_machine_melee_strike,
    SwingBatOrPipe: state_machine_melee_strike,
    StabWithKnifeOrBottle: state_machine_melee_strike,
    SprayPepper: state_machine_melee_strike,
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


def execute_tick(verb: Verb | None, context: Context, gamepad: VirtualGamepad) -> None:
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
    """

    actor = find(context, Myself)
    if actor is not None:
        mask = _pit_escape_mask(context, actor)
        if mask is not None:
            _hold_steered(gamepad, mask)
            return
    if verb is None:
        press_no_button(gamepad)
        return
    execute_verb(verb, context, gamepad)
