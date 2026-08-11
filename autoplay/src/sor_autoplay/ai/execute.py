"""``execute_decision`` — dispatch the surviving ``Decision`` to controller input.

Per ``AI.md``: each handler steers the controller only as much as necessary
and returns immediately — never blocks/sleeps waiting for the decision to
play out.

CRITICAL button mapping (original scheme): Attack/Punch = physical B (0x0020),
Police special = physical A (0x0010), Jump = physical C (0x0040).
"""

from __future__ import annotations

from .tokens import (
    CounterGrab,
    FlipHold,
    JumpAttack,
    AttackHeldEnemy,
    Punch,
    RearAttack,
    ReleaseGrab,
    SmashBreakable,
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
from .tokens import Breakable, Pit
from .tokens import Pickup, Weapon
from .tokens import CallPolice
from .tokens import Context, Decision, find, find_all
from .tokens import (
    RetreatFromDanger,
    WalkToAdvanceStage,
    WalkToBreakable,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from .gamepad import VirtualGamepad
from .decide import BREAKABLE_PUNCH_X, _enemy_behind_actor
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

PICKUP_RANGE_X = 18
PICKUP_RANGE_Y = 14
LANE_EDGE_MARGIN = 6
BREAKABLE_AVOID_X = 28
BREAKABLE_AVOID_Y = 22
# Clearance kept beyond a Pit's own footprint — falling in costs a full life
# (player-health-lives-and-combat.md's $01C0 fall-boundary check), so this
# stays smaller than BREAKABLE_AVOID_Y only because the pit's real height is
# already added on top of it (see the dodge loop below).
PIT_AVOID_MARGIN = 8
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
BREAKABLE_STOP_BUFFER = 4


def press_no_button(gamepad: VirtualGamepad) -> None:
    gamepad.release()


def _press(gamepad: VirtualGamepad, mask: int, *, frames: int) -> None:
    """Issue a pure button press, dropping any stale directional hold first.

    ``hold_buttons`` is a *sticky* latch (gamepad.py's module docstring):
    whatever direction the previous tick's walk decision held stays held
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
        # radius could trip the dodge below on nearly every walk decision —
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


def _walk_to_near_enemy_target(actor: Myself | Partner, target: Enemy) -> tuple[int, int]:
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
    """

    outer = punch_outer_x(actor.character_id, actor.held_weapon_type)
    inner = punch_inner_x(actor.character_id)
    stop_dx = max(inner, outer - WALK_TO_ENEMY_STOP_BUFFER)

    if _enemy_behind_actor(actor, target):
        # Aim for the *far* side, so the movement mask points at the enemy
        # rather than away from it. Holding a direction is what sets facing,
        # so this is the turn-around: after a tick the enemy is in front and
        # could_punch covers it normally. Stopping on the near side (the
        # branch below) would instead back the actor away while still facing
        # the wrong way, leaving the slow RearAttack chord as the only thing
        # that could reach it.
        target_x = (
            target.world_x - stop_dx
            if actor.world_x > target.world_x
            else target.world_x + stop_dx
        )
    elif actor.world_x <= target.world_x:
        target_x = target.world_x - stop_dx
    else:
        target_x = target.world_x + stop_dx

    dx = abs(target.world_x - actor.world_x)
    if is_dangerous(target.combat_phase) and dx > stop_dx:
        offset = WALK_TO_ENEMY_LANE_SAFETY_Y if actor.world_y >= target.world_y else -WALK_TO_ENEMY_LANE_SAFETY_Y
        target_y = target.world_y + offset
    else:
        target_y = target.world_y

    return target_x, target_y


def _execute_walk_to_near_enemy(decision: WalkToNearEnemy, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Enemy, slot=decision.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    target_x, target_y = _walk_to_near_enemy_target(actor, target)
    gamepad.hold(_movement_mask(context, actor.world_x, actor.world_y, target_x, target_y))


# How far to step back per tick while retreating -- roughly clears the
# RETREAT_CAUTION_MARGIN zone decide.py gates this decision on, without
# being a single-tick teleport.
RETREAT_FROM_DANGER_DISTANCE = 32


def _retreat_from_danger_target(actor: Myself | Partner, target: Enemy) -> tuple[int, int]:
    """Step directly away from ``target`` on X, holding the current lane."""

    if actor.world_x <= target.world_x:
        target_x = actor.world_x - RETREAT_FROM_DANGER_DISTANCE
    else:
        target_x = actor.world_x + RETREAT_FROM_DANGER_DISTANCE
    return target_x, actor.world_y


def _execute_retreat_from_danger(
    decision: RetreatFromDanger, context: Context, gamepad: VirtualGamepad
) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Enemy, slot=decision.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    target_x, target_y = _retreat_from_danger_target(actor, target)
    gamepad.hold(_movement_mask(context, actor.world_x, actor.world_y, target_x, target_y))


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


def _execute_melee_strike(decision: Decision, context: Context, gamepad: VirtualGamepad) -> None:
    """Shared handler for ``Punch`` / ``SwingBatOrPipe`` /
    ``StabWithKnifeOrBottle`` / ``SprayPepper`` -- identical B-button press
    regardless of which (if any) weapon is held; only the ROM-side move that
    resolves from it differs."""

    actor = _find_actor(context, getattr(decision, "actor_slot", None))
    target = find(context, Enemy, slot=getattr(decision, "target_slot", None))
    face = 0
    if actor is not None and target is not None:
        face = _face_toward_mask(actor, target.world_x)
    _press(gamepad, PUNCH_MASK | face, frames=PUNCH_FRAMES)


def _execute_smash_breakable(decision: SmashBreakable, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Breakable, slot=decision.target_slot)
    face = 0
    if actor is not None and target is not None:
        face = _face_toward_mask(actor, target.world_x)
    _press(gamepad, PUNCH_MASK | face, frames=PUNCH_FRAMES)


def _execute_rear_attack(decision: RearAttack, context: Context, gamepad: VirtualGamepad) -> None:
    _press(gamepad, PUNCH_MASK | JUMP_MASK, frames=REAR_ATTACK_FRAMES)


def _execute_counter_grab(decision: CounterGrab, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
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


def _execute_tech_recover(decision: TechRecover, context: Context, gamepad: VirtualGamepad) -> None:
    # A held Up plus a *fresh* C edge, every tick this decision wins -- the
    # ROM requires a new C press, not a held-over one (controls-and-input.md
    # "C must be a fresh edge while Up is held").
    _press(gamepad, JUMP_MASK | UP_MASK, frames=TECH_RECOVER_FRAMES)


def _execute_call_police(decision: CallPolice, context: Context, gamepad: VirtualGamepad) -> None:
    _press(gamepad, CALL_POLICE_MASK, frames=CALL_POLICE_FRAMES)


def _execute_jump_attack(decision: JumpAttack, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        gamepad.release()
        return
    target = find(context, Enemy, slot=decision.target_slot)
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


def _execute_supplex(decision: Supplex, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
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


def _execute_attack_held_enemy(decision: AttackHeldEnemy, context: Context, gamepad: VirtualGamepad) -> None:
    # Front-hold B alone (Up/Down ignored by ROM for throw; no L/R = knee).
    # The cleared hold matters here: a leftover walk direction would turn this
    # knee into the B+back throw below.
    _press(gamepad, PUNCH_MASK, frames=HOLD_FRAMES)


def _execute_throw_held_enemy(decision: ThrowHeldEnemy, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        gamepad.release()
        return
    # B + back (L/R opposite facing) — controls-and-input.md hold section.
    back = _back_direction_mask(actor)
    _press(gamepad, PUNCH_MASK | back, frames=HOLD_FRAMES)


def _execute_flip_hold(decision: FlipHold, context: Context, gamepad: VirtualGamepad) -> None:
    # Front-hold C → back hold $66; next tick Supplex finishes.
    _press(gamepad, JUMP_MASK, frames=HOLD_FRAMES)


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
    _press(gamepad, PUNCH_MASK | face, frames=THROW_KNIFE_FRAMES)


def _execute_throw_pepper(decision: ThrowPepper, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Enemy, slot=decision.target_slot)
    face = 0
    if actor is not None and target is not None:
        face = _face_toward_mask(actor, target.world_x)
    _press(gamepad, PUNCH_MASK | face, frames=THROW_PEPPER_FRAMES)


def _execute_walk_to_weapon(decision: WalkToWeapon, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Weapon, slot=decision.target_slot)
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


def _execute_walk_to_pickup(decision: WalkToPickup, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Pickup, slot=decision.target_slot)
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
    unreachable) center."""

    stop_dx = max(0, BREAKABLE_PUNCH_X - BREAKABLE_STOP_BUFFER)
    if actor.world_x <= target.world_x:
        target_x = target.world_x - stop_dx
    else:
        target_x = target.world_x + stop_dx
    return target_x, target.world_y


def _execute_walk_to_breakable(
    decision: WalkToBreakable, context: Context, gamepad: VirtualGamepad
) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Breakable, slot=decision.target_slot)
    if actor is None or target is None:
        gamepad.release()
        return
    target_x, target_y = _walk_to_breakable_target(actor, target)
    gamepad.hold(_movement_mask(context, actor.world_x, actor.world_y, target_x, target_y))


_HANDLERS = {
    WalkToNearEnemy: _execute_walk_to_near_enemy,
    RetreatFromDanger: _execute_retreat_from_danger,
    WalkToAdvanceStage: _execute_walk_to_advance_stage,
    Punch: _execute_melee_strike,
    SwingBatOrPipe: _execute_melee_strike,
    StabWithKnifeOrBottle: _execute_melee_strike,
    SprayPepper: _execute_melee_strike,
    SmashBreakable: _execute_smash_breakable,
    RearAttack: _execute_rear_attack,
    CounterGrab: _execute_counter_grab,
    TechRecover: _execute_tech_recover,
    CallPolice: _execute_call_police,
    JumpAttack: _execute_jump_attack,
    Supplex: _execute_supplex,
    AttackHeldEnemy: _execute_attack_held_enemy,
    ThrowHeldEnemy: _execute_throw_held_enemy,
    FlipHold: _execute_flip_hold,
    ReleaseGrab: _execute_release_grab,
    ThrowKnife: _execute_throw_knife,
    ThrowPepper: _execute_throw_pepper,
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
