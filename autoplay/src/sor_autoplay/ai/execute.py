"""``execute_decision`` — dispatch the surviving ``Decision`` to controller input.

Per ``AI.md``: each handler steers the controller only as much as necessary
and returns immediately — never blocks/sleeps waiting for the decision to
play out.

CRITICAL button mapping (original scheme): Attack/Punch = physical B (0x0020),
Police special = physical A (0x0010), Jump = physical C (0x0040).
"""

from __future__ import annotations

from .attack_decisions import (
    CounterGrab,
    FlipHold,
    JumpAttack,
    KneeStrike,
    Punch,
    RearAttack,
    ReleaseGrab,
    SmashBreakable,
    Supplex,
    ThrowHeldEnemy,
    ThrowKnife,
)
from .character import Myself, Partner
from .enemy import Enemy
from .essential import CameraRange
from .hazard_tokens import Breakable
from .pickup_tokens import Pickup, Weapon
from .police_decision import CallPolice
from .tokens import Context, Decision, find, find_all
from .walk_decisions import (
    Sidestep,
    WalkToAdvanceStage,
    WalkToBreakable,
    WalkToCoordinate,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from .gamepad import VirtualGamepad
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
REAR_ATTACK_FRAMES = 4
COUNTER_FRAMES = 3
JUMP_ATTACK_LAUNCH_FRAMES = 3
JUMP_ATTACK_KICK_FRAMES = 4
HOLD_FRAMES = 4

PICKUP_RANGE_X = 18
PICKUP_RANGE_Y = 14
LANE_EDGE_MARGIN = 6
BREAKABLE_AVOID_X = 28
BREAKABLE_AVOID_Y = 22


def press_no_button(gamepad: VirtualGamepad) -> None:
    gamepad.release()


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
    # Nudge path around intact breakables sitting on the straight-line route.
    for prop in find_all(context, Breakable):
        # Prop between us and target on X, same lane band.
        between = (from_x < prop.world_x < to_x) or (to_x < prop.world_x < from_x)
        if not between:
            continue
        if abs(prop.world_y - from_y) > BREAKABLE_AVOID_Y and abs(prop.world_y - to_y) > BREAKABLE_AVOID_Y:
            continue
        if abs(prop.world_x - from_x) > abs(to_x - from_x):
            continue
        # Sidestep vertically around the prop (prefer away from lane edge).
        lo, hi = _lane_bounds(context)
        if from_y < (lo + hi) / 2:
            to_y = _clamp_target_y(context, prop.world_y + BREAKABLE_AVOID_Y)
        else:
            to_y = _clamp_target_y(context, prop.world_y - BREAKABLE_AVOID_Y)

    mask = 0
    if to_x > from_x:
        mask |= RIGHT_MASK
    elif to_x < from_x:
        mask |= LEFT_MASK
    # Smaller world_y = back of stage = "up".
    if to_y > from_y:
        mask |= DOWN_MASK
    elif to_y < from_y:
        mask |= UP_MASK

    # Never hold into the lane clamp.
    lo, hi = _lane_bounds(context)
    if from_y >= hi:
        mask &= ~DOWN_MASK
    if from_y <= lo:
        mask &= ~UP_MASK
    return mask


def _face_toward_mask(actor: Myself | Partner, target_x: int) -> int:
    if target_x < actor.world_x:
        return LEFT_MASK
    if target_x > actor.world_x:
        return RIGHT_MASK
    return 0


def _back_direction_mask(actor: Myself | Partner) -> int:
    """Opposite of facing — used for hold-throw (B+back)."""

    return RIGHT_MASK if actor.facing_left else LEFT_MASK


def _execute_walk_to_near_enemy(decision: WalkToNearEnemy, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Enemy, slot=decision.target_slot)
    if actor is None or target is None:
        return
    gamepad.hold(
        _movement_mask(context, actor.world_x, actor.world_y, target.world_x, target.world_y)
    )


def _execute_walk_to_advance_stage(
    decision: WalkToAdvanceStage, context: Context, gamepad: VirtualGamepad
) -> None:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        gamepad.hold(RIGHT_MASK if decision.direction == "right" else LEFT_MASK)
        return
    # Pure lateral advance — do not add accidental Up/Down.
    mask = RIGHT_MASK if decision.direction == "right" else LEFT_MASK
    # If a breakable sits immediately ahead, approach with a slight Y offset
    # so the next tick can smash rather than walk forever into it.
    ahead_x = actor.world_x + (40 if decision.direction == "right" else -40)
    gamepad.hold(
        _movement_mask(context, actor.world_x, actor.world_y, ahead_x, actor.world_y) or mask
    )


def _execute_sidestep(decision: Sidestep, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    lo, hi = _lane_bounds(context)
    if decision.direction == "up":
        if actor is not None and actor.world_y <= lo:
            gamepad.release()
            return
        gamepad.hold(UP_MASK)
    elif decision.direction == "down":
        if actor is not None and actor.world_y >= hi:
            gamepad.release()
            return
        gamepad.hold(DOWN_MASK)


def _execute_punch(decision: Punch, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Enemy, slot=decision.target_slot)
    face = 0
    if actor is not None and target is not None:
        face = _face_toward_mask(actor, target.world_x)
    gamepad.press(PUNCH_MASK | face, frames=PUNCH_FRAMES)


def _execute_smash_breakable(decision: SmashBreakable, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Breakable, slot=decision.target_slot)
    face = 0
    if actor is not None and target is not None:
        face = _face_toward_mask(actor, target.world_x)
    gamepad.press(PUNCH_MASK | face, frames=PUNCH_FRAMES)


def _execute_rear_attack(decision: RearAttack, context: Context, gamepad: VirtualGamepad) -> None:
    gamepad.press(PUNCH_MASK | JUMP_MASK, frames=REAR_ATTACK_FRAMES)


def _execute_counter_grab(decision: CounterGrab, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        return
    base = actor.action_base
    if actor.counter_window_open:
        gamepad.press(PUNCH_MASK, frames=COUNTER_FRAMES)
        return
    if base == 0x7A:
        gamepad.press(JUMP_MASK, frames=COUNTER_FRAMES)
        return
    if base in (0x78, 0x7C):
        gamepad.release()
        return
    gamepad.press(JUMP_MASK, frames=COUNTER_FRAMES)


def _execute_call_police(decision: CallPolice, context: Context, gamepad: VirtualGamepad) -> None:
    gamepad.press(CALL_POLICE_MASK, frames=CALL_POLICE_FRAMES)


def _execute_jump_attack(decision: JumpAttack, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        return
    target = find(context, Enemy, slot=decision.target_slot)
    if target is None:
        # No target → do not hop in place.
        gamepad.release()
        return
    face = _face_toward_mask(actor, target.world_x)
    if face == 0:
        # Already overlapping on X — punch, don't jump.
        gamepad.press(PUNCH_MASK, frames=PUNCH_FRAMES)
        return
    if not actor.is_airborne:
        # Launch with horizontal hold so crouch→flight carries ±3 px/frame.
        gamepad.press(JUMP_MASK | face, frames=JUMP_ATTACK_LAUNCH_FRAMES)
        gamepad.hold(face)
    else:
        gamepad.press(PUNCH_MASK | face, frames=JUMP_ATTACK_KICK_FRAMES)


def _execute_supplex(decision: Supplex, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        return
    base = actor.action_base
    if base == 0x66:
        gamepad.press(PUNCH_MASK, frames=SUPPLEX_FRAMES)
    elif base == 0x60:
        # Should have been FlipHold, but finish the crossover if we land here.
        gamepad.press(JUMP_MASK, frames=SUPPLEX_FRAMES)
    else:
        gamepad.press(PUNCH_MASK, frames=SUPPLEX_FRAMES)


def _execute_knee_strike(decision: KneeStrike, context: Context, gamepad: VirtualGamepad) -> None:
    # Front-hold B alone (Up/Down ignored by ROM for throw; no L/R = knee).
    gamepad.press(PUNCH_MASK, frames=HOLD_FRAMES)


def _execute_throw_held_enemy(decision: ThrowHeldEnemy, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        return
    # B + back (L/R opposite facing) — controls-and-input.md hold section.
    back = _back_direction_mask(actor)
    gamepad.press(PUNCH_MASK | back, frames=HOLD_FRAMES)


def _execute_flip_hold(decision: FlipHold, context: Context, gamepad: VirtualGamepad) -> None:
    # Front-hold C → back hold $66; next tick Supplex finishes.
    gamepad.press(JUMP_MASK, frames=HOLD_FRAMES)


def _execute_release_grab(decision: ReleaseGrab, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Enemy, slot=decision.target_slot)
    if actor is None:
        gamepad.release()
        return
    if target is None:
        # Walk opposite current facing to break the link.
        mask = _back_direction_mask(actor)
        gamepad.hold(mask)
        return
    # Walk away from the held body.
    away_x = actor.world_x + (20 if actor.world_x >= target.world_x else -20)
    gamepad.hold(
        _movement_mask(context, actor.world_x, actor.world_y, away_x, actor.world_y)
    )


def _execute_throw_knife(decision: ThrowKnife, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Enemy, slot=decision.target_slot)
    face = 0
    if actor is not None and target is not None:
        face = _face_toward_mask(actor, target.world_x)
    gamepad.press(PUNCH_MASK | face, frames=THROW_KNIFE_FRAMES)


def _execute_walk_to_coordinate(decision: WalkToCoordinate, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        return
    gamepad.hold(
        _movement_mask(
            context, actor.world_x, actor.world_y, decision.target_x, decision.target_y
        )
    )


def _execute_walk_to_weapon(decision: WalkToWeapon, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Weapon, slot=decision.target_slot)
    if actor is None or target is None:
        return
    if abs(target.world_x - actor.world_x) <= PICKUP_RANGE_X and abs(target.world_y - actor.world_y) <= PICKUP_RANGE_Y:
        gamepad.press(PUNCH_MASK, frames=PUNCH_FRAMES)
    else:
        gamepad.hold(
            _movement_mask(
                context, actor.world_x, actor.world_y, target.world_x, target.world_y
            )
        )


def _execute_walk_to_pickup(decision: WalkToPickup, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Pickup, slot=decision.target_slot)
    if actor is None or target is None:
        return
    if abs(target.world_x - actor.world_x) <= PICKUP_RANGE_X and abs(target.world_y - actor.world_y) <= PICKUP_RANGE_Y:
        gamepad.press(PUNCH_MASK, frames=PUNCH_FRAMES)
    else:
        gamepad.hold(
            _movement_mask(
                context, actor.world_x, actor.world_y, target.world_x, target.world_y
            )
        )


def _execute_walk_to_breakable(
    decision: WalkToBreakable, context: Context, gamepad: VirtualGamepad
) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Breakable, slot=decision.target_slot)
    if actor is None or target is None:
        return
    gamepad.hold(
        _movement_mask(context, actor.world_x, actor.world_y, target.world_x, target.world_y)
    )


_HANDLERS = {
    WalkToNearEnemy: _execute_walk_to_near_enemy,
    WalkToAdvanceStage: _execute_walk_to_advance_stage,
    Sidestep: _execute_sidestep,
    Punch: _execute_punch,
    SmashBreakable: _execute_smash_breakable,
    RearAttack: _execute_rear_attack,
    CounterGrab: _execute_counter_grab,
    CallPolice: _execute_call_police,
    JumpAttack: _execute_jump_attack,
    Supplex: _execute_supplex,
    KneeStrike: _execute_knee_strike,
    ThrowHeldEnemy: _execute_throw_held_enemy,
    FlipHold: _execute_flip_hold,
    ReleaseGrab: _execute_release_grab,
    ThrowKnife: _execute_throw_knife,
    WalkToCoordinate: _execute_walk_to_coordinate,
    WalkToWeapon: _execute_walk_to_weapon,
    WalkToPickup: _execute_walk_to_pickup,
    WalkToBreakable: _execute_walk_to_breakable,
}


def execute_decision(decision: Decision, context: Context, gamepad: VirtualGamepad) -> None:
    handler = _HANDLERS.get(type(decision))
    if handler is None:
        press_no_button(gamepad)
        return
    handler(decision, context, gamepad)
