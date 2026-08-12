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
from .tokens import Myself, Partner, PUNCH_RANGE_Y, punch_inner_x, punch_outer_x
from .tokens import Enemy
from .tokens import CameraRange
from .tokens import Breakable, Pit, SafeSpot
from .tokens import Pickup, Weapon
from .tokens import CallPolice
from .tokens import Context, Verb, find, find_all
from .tokens import (
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from .gamepad import VirtualGamepad
from .decide import BREAKABLE_PUNCH_X, in_smash_range
from .reach import PIT_AVOID_MARGIN, enemy_behind_actor
from ..phases import is_dangerous
from ..world_map import LANE_Y_MIN

UP_MASK = 0x0001
DOWN_MASK = 0x0002
LEFT_MASK = 0x0004
RIGHT_MASK = 0x0008
PUNCH_MASK = 0x0020  # physical B
CALL_POLICE_MASK = 0x0010  # physical A
JUMP_MASK = 0x0040  # physical C
PUNCH_FRAMES = 4
CALL_POLICE_FRAMES = 4
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
BREAKABLE_AVOID_X = 28
BREAKABLE_AVOID_Y = 22
# Pit clearance (reach.PIT_AVOID_MARGIN) stays smaller than BREAKABLE_AVOID_Y
# only because the pit's real height is already added on top of it (see the
# dodge loop below). It is shared with inference.check_for_safe_spots, which
# must reject the same ground this steers around.

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


def _movement_mask(
    context: Context,
    from_x: int,
    from_y: int,
    to_x: int,
    to_y: int,
) -> int:
    """Build a D-pad mask, clamped to lane bounds and steered around props."""

    to_y = _clamp_target_y(context, to_y)
    camera = find(context, CameraRange)
    # Nudge path around intact breakables sitting on the straight-line route.
    for prop in find_all(context, Breakable):
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
        half_height = (pit_bottom - pit.lane_y) / 2 + PIT_AVOID_MARGIN
        if abs(pit_center_y - from_y) > half_height and abs(pit_center_y - to_y) > half_height:
            continue
        if abs(pit_center_x - from_x) > abs(to_x - from_x):
            continue
        lo, hi = _lane_bounds(context)
        if from_y < (lo + hi) / 2:
            to_y = _clamp_target_y(context, pit_bottom + PIT_AVOID_MARGIN)
        else:
            to_y = _clamp_target_y(context, pit.lane_y - PIT_AVOID_MARGIN)

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

    # Never hold into the lane clamp.
    lo, hi = _lane_bounds(context)
    if from_y >= hi:
        mask &= ~DOWN_MASK
    if from_y <= lo:
        mask &= ~UP_MASK
    return mask


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

    outer = punch_outer_x(actor.character_id, actor.held_weapon_type)
    inner = punch_inner_x(actor.character_id)
    stop_dx = max(inner, outer - WALK_TO_ENEMY_STOP_BUFFER)

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


def state_machine_walk_to_near_enemy(verb: WalkToNearEnemy, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Enemy, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    target_x, target_y = _walk_to_near_enemy_target(actor, target, context)
    gamepad.hold(_movement_mask(context, actor.world_x, actor.world_y, target_x, target_y))


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
    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Enemy, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    target_x, target_y = _retreat_from_danger_target(actor, target, context)
    gamepad.hold(_movement_mask(context, actor.world_x, actor.world_y, target_x, target_y))


def state_machine_walk_to_advance_stage(
    verb: WalkToAdvanceStage, context: Context, gamepad: VirtualGamepad
) -> None:
    actor = _find_actor(context, verb.actor_slot)
    if actor is None:
        gamepad.hold(RIGHT_MASK if verb.direction == "right" else LEFT_MASK)
        return
    # Pure lateral advance — do not add accidental Up/Down.
    mask = RIGHT_MASK if verb.direction == "right" else LEFT_MASK
    # If a breakable sits immediately ahead, approach with a slight Y offset
    # so the next tick can smash rather than walk forever into it.
    ahead_x = actor.world_x + (40 if verb.direction == "right" else -40)
    gamepad.hold(
        _movement_mask(context, actor.world_x, actor.world_y, ahead_x, actor.world_y) or mask
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


def state_machine_jump_attack(verb: JumpAttack, context: Context, gamepad: VirtualGamepad) -> None:
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
    if face == 0:
        # Already overlapping on X — punch, don't jump.
        _press(gamepad, PUNCH_MASK, frames=PUNCH_FRAMES)
        return
    if not actor.is_airborne:
        # Launch with horizontal hold so crouch→flight carries ±3 px/frame.
        _press(gamepad, JUMP_MASK | face, frames=JUMP_ATTACK_LAUNCH_FRAMES)
        gamepad.hold(face)
    else:
        _press(gamepad, PUNCH_MASK | face, frames=JUMP_ATTACK_KICK_FRAMES)


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
    # buffer: overlapping is the whole point of this verb.
    mask = _movement_mask(context, actor.world_x, actor.world_y, target.world_x, target.world_y)
    if not mask & (LEFT_MASK | RIGHT_MASK):
        mask |= _face_toward_mask(actor, target.world_x) or (
            LEFT_MASK if actor.facing_left else RIGHT_MASK
        )
    gamepad.hold(mask)


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
        gamepad.hold(mask)
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
    gamepad.hold(
        _movement_mask(context, actor.world_x, actor.world_y, away_x, actor.world_y)
    )


def state_machine_throw_knife(verb: ThrowKnife, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Enemy, slot=verb.target_slot)
    face = 0
    if actor is not None and target is not None:
        face = _face_toward_mask(actor, target.world_x)
    _press(gamepad, PUNCH_MASK | face, frames=THROW_KNIFE_FRAMES)


def state_machine_throw_pepper(verb: ThrowPepper, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Enemy, slot=verb.target_slot)
    face = 0
    if actor is not None and target is not None:
        face = _face_toward_mask(actor, target.world_x)
    _press(gamepad, PUNCH_MASK | face, frames=THROW_PEPPER_FRAMES)


def state_machine_walk_to_weapon(verb: WalkToWeapon, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Weapon, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    if abs(target.world_x - actor.world_x) <= PICKUP_RANGE_X and abs(target.world_y - actor.world_y) <= PICKUP_RANGE_Y:
        _press(gamepad, PUNCH_MASK, frames=PUNCH_FRAMES)
    else:
        gamepad.hold(
            _movement_mask(
                context, actor.world_x, actor.world_y, target.world_x, target.world_y
            )
        )


def state_machine_walk_to_pickup(verb: WalkToPickup, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Pickup, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    if abs(target.world_x - actor.world_x) <= PICKUP_RANGE_X and abs(target.world_y - actor.world_y) <= PICKUP_RANGE_Y:
        _press(gamepad, PUNCH_MASK, frames=PUNCH_FRAMES)
    else:
        gamepad.hold(
            _movement_mask(
                context, actor.world_x, actor.world_y, target.world_x, target.world_y
            )
        )


def _walk_to_breakable_target(actor: Myself | Partner, target: Breakable) -> tuple[int, int]:
    """Stopping point for approaching ``target``: a Breakable is a solid
    obstacle, so stop just inside smash range on whichever side the actor
    already occupies rather than walking to the breakable's exact (and
    unreachable) center.

    Within ``DIRECTION_HYSTERESIS_X`` of the prop, which side counts as
    "already occupies" is read off ``actor.facing_left`` instead of the raw
    compare, same as ``_walk_to_near_enemy_target``'s X pick -- otherwise a
    couple of px of approach jitter right at the prop flips the stop point
    by a full ``2 * stop_dx``.
    """

    stop_dx = max(0, BREAKABLE_PUNCH_X - BREAKABLE_STOP_BUFFER)
    dx = target.world_x - actor.world_x
    if abs(dx) <= DIRECTION_HYSTERESIS_X:
        approach_from_right = actor.facing_left
    else:
        approach_from_right = dx < 0
    target_x = target.world_x + stop_dx if approach_from_right else target.world_x - stop_dx
    return target_x, target.world_y


def state_machine_open_breakable(
    verb: OpenBreakable, context: Context, gamepad: VirtualGamepad
) -> None:
    """Close the distance, then hit it -- one verb, both halves.

    The switch is ``decide.in_smash_range``, the same predicate
    ``priority._emergency_open_breakable`` scores with, so the tier the verb
    won on and the action it takes can never describe different situations.
    """

    actor = _find_actor(context, verb.actor_slot)
    target = find(context, Breakable, slot=verb.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    if in_smash_range(actor, target):
        _press(gamepad, PUNCH_MASK | _face_toward_mask(actor, target.world_x), frames=PUNCH_FRAMES)
        return
    target_x, target_y = _walk_to_breakable_target(actor, target)
    gamepad.hold(_movement_mask(context, actor.world_x, actor.world_y, target_x, target_y))


_HANDLERS = {
    WalkToNearEnemy: state_machine_walk_to_near_enemy,
    RetreatFromDanger: state_machine_retreat_from_danger,
    WalkToAdvanceStage: state_machine_walk_to_advance_stage,
    Punch: state_machine_melee_strike,
    SwingBatOrPipe: state_machine_melee_strike,
    StabWithKnifeOrBottle: state_machine_melee_strike,
    SprayPepper: state_machine_melee_strike,
    RearAttack: state_machine_rear_attack,
    CounterGrab: state_machine_counter_grab,
    TechRecover: state_machine_tech_recover,
    CallPolice: state_machine_call_police,
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
