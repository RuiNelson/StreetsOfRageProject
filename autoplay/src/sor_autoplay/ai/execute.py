"""``execute_decision`` — dispatch the surviving ``Decision`` to controller input.

Per ``AI.md``: each handler steers the controller only as much as necessary
and returns immediately — never blocks/sleeps waiting for the decision to
play out.

CRITICAL button mapping, verified against
``StreetsOfRageRecompilation/ai-analysis/controls-and-input.md`` and the
``sampleOneJoypadBody`` comment in ``StreetsOfRageRecompilation/SoRControls.cpp``
for the original (non-altControls) scheme: Attack/Punch is physical button B
(0x0020), Police special is physical button A (0x0010). This is the reverse
of the naive "A=attack" assumption — do not change it without re-reading
those two files.

Button masks are plain ints (matching ``megadrive_remote.Buttons``' values)
rather than an import of that enum, so this module — and everything that
imports it, including ``app.py`` at module load time — never forces
``megadrive_remote`` onto ``sys.path`` before ``_ensure_megadrive_remote_on_path``
has a chance to run.
"""

from __future__ import annotations

from .attack_decisions import CounterGrab, JumpAttack, Punch, RearAttack, Supplex, ThrowKnife
from .character import Myself, Partner
from .enemy import Enemy
from .pickup_tokens import Pickup, Weapon
from .police_decision import CallPolice
from .tokens import Context, Decision, find
from .walk_decisions import (
    Sidestep,
    WalkToAdvanceStage,
    WalkToCoordinate,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from .gamepad import VirtualGamepad

UP_MASK = 0x0001
DOWN_MASK = 0x0002
LEFT_MASK = 0x0004
RIGHT_MASK = 0x0008
PUNCH_MASK = 0x0020  # physical B — verified mapping, see module docstring
CALL_POLICE_MASK = 0x0010  # physical A — verified mapping, see module docstring
JUMP_MASK = 0x0040  # physical C
PUNCH_FRAMES = 4
CALL_POLICE_FRAMES = 4
SUPPLEX_FRAMES = 4
THROW_KNIFE_FRAMES = 4
REAR_ATTACK_FRAMES = 4
COUNTER_FRAMES = 3
JUMP_ATTACK_LAUNCH_FRAMES = 3
JUMP_ATTACK_KICK_FRAMES = 4

# ROM $3136 pickup search: ±20 X, ±16 lane Y. Stay inside that box before B.
PICKUP_RANGE_X = 18
PICKUP_RANGE_Y = 14


def press_no_button(gamepad: VirtualGamepad) -> None:
    """The AI.md 'do nothing' case."""

    gamepad.release()


def _find_actor(context: Context, slot: str) -> Myself | Partner | None:
    for actor in (find(context, Myself), find(context, Partner)):
        if actor is not None and actor.slot == slot:
            return actor
    return None


def _movement_mask(from_x: int, from_y: int, to_x: int, to_y: int) -> int:
    mask = 0
    if to_x > from_x:
        mask |= RIGHT_MASK
    elif to_x < from_x:
        mask |= LEFT_MASK
    # world_map.py convention: smaller world_y = back of stage = "up".
    if to_y > from_y:
        mask |= DOWN_MASK
    elif to_y < from_y:
        mask |= UP_MASK
    return mask


def _face_toward_mask(actor: Myself | Partner, target_x: int) -> int:
    """Hold the facing direction so attack boxes aim at the target."""

    if target_x < actor.world_x:
        return LEFT_MASK
    if target_x > actor.world_x:
        return RIGHT_MASK
    return 0


def _execute_walk_to_near_enemy(decision: WalkToNearEnemy, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Enemy, slot=decision.target_slot)
    if actor is None or target is None:
        return

    gamepad.hold(_movement_mask(actor.world_x, actor.world_y, target.world_x, target.world_y))


def _execute_walk_to_advance_stage(
    decision: WalkToAdvanceStage, context: Context, gamepad: VirtualGamepad
) -> None:
    gamepad.hold(RIGHT_MASK if decision.direction == "right" else LEFT_MASK)


def _execute_sidestep(decision: Sidestep, context: Context, gamepad: VirtualGamepad) -> None:
    if decision.direction == "up":
        gamepad.hold(UP_MASK)
    elif decision.direction == "down":
        gamepad.hold(DOWN_MASK)


def _execute_punch(decision: Punch, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Enemy, slot=decision.target_slot)
    face = 0
    if actor is not None and target is not None:
        face = _face_toward_mask(actor, target.world_x)
    # Face + attack edge together so the punch aims the right way.
    gamepad.press(PUNCH_MASK | face, frames=PUNCH_FRAMES)


def _execute_rear_attack(decision: RearAttack, context: Context, gamepad: VirtualGamepad) -> None:
    # Simultaneous B+C chord ($322A). Do not hold a direction — the rear box
    # is behind the current facing.
    gamepad.press(PUNCH_MASK | JUMP_MASK, frames=REAR_ATTACK_FRAMES)


def _execute_counter_grab(decision: CounterGrab, context: Context, gamepad: VirtualGamepad) -> None:
    """Enemy-held counter: C starts crossover; B throws while the window is open.

    From controls-and-input.md:
      $7A held → C edge → $7C crossover → returns to $7A with +$58 bit 7
      → B edge → $7E counter throw
    """

    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        return
    base = actor.action_base
    if actor.counter_window_open:
        # Post-crossover B window (player +$58 bit 7).
        gamepad.press(PUNCH_MASK, frames=COUNTER_FRAMES)
        return
    if base == 0x7A:
        # Stable held state — C starts the crossover.
        gamepad.press(JUMP_MASK, frames=COUNTER_FRAMES)
        return
    if base in (0x78, 0x7C):
        # Acquire or mid-crossover — wait for the next actionable state.
        gamepad.release()
        return
    # Fallback: try C (crossover entry) if state is unexpected but still held.
    gamepad.press(JUMP_MASK, frames=COUNTER_FRAMES)


def _execute_call_police(decision: CallPolice, context: Context, gamepad: VirtualGamepad) -> None:
    gamepad.press(CALL_POLICE_MASK, frames=CALL_POLICE_FRAMES)


def _execute_jump_attack(decision: JumpAttack, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        return
    target = find(context, Enemy, slot=decision.target_slot)
    face = 0
    if target is not None:
        face = _face_toward_mask(actor, target.world_x)
    if not actor.is_airborne:
        # Hold direction into the jump so launch X velocity aims at the foe.
        gamepad.press(JUMP_MASK | face, frames=JUMP_ATTACK_LAUNCH_FRAMES)
    else:
        gamepad.press(PUNCH_MASK | face, frames=JUMP_ATTACK_KICK_FRAMES)


def _execute_supplex(decision: Supplex, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        return
    base = actor.action_base
    if base == 0x66:
        # Back hold → B is suplex.
        gamepad.press(PUNCH_MASK, frames=SUPPLEX_FRAMES)
    elif base == 0x60:
        # Front hold → C crosses to back hold; next ticks finish with B.
        gamepad.press(JUMP_MASK, frames=SUPPLEX_FRAMES)
    else:
        gamepad.press(PUNCH_MASK, frames=SUPPLEX_FRAMES)


def _execute_throw_knife(decision: ThrowKnife, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Enemy, slot=decision.target_slot)
    face = 0
    if actor is not None and target is not None:
        face = _face_toward_mask(actor, target.world_x)
    # Face the target so the ROM front-cone scan does not flip to melee stab
    # against a different body, and the throw launches the right way.
    gamepad.press(PUNCH_MASK | face, frames=THROW_KNIFE_FRAMES)


def _execute_walk_to_coordinate(decision: WalkToCoordinate, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        return
    gamepad.hold(_movement_mask(actor.world_x, actor.world_y, decision.target_x, decision.target_y))


def _execute_walk_to_weapon(decision: WalkToWeapon, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Weapon, slot=decision.target_slot)
    if actor is None or target is None:
        return
    if abs(target.world_x - actor.world_x) <= PICKUP_RANGE_X and abs(target.world_y - actor.world_y) <= PICKUP_RANGE_Y:
        gamepad.press(PUNCH_MASK, frames=PUNCH_FRAMES)
    else:
        gamepad.hold(_movement_mask(actor.world_x, actor.world_y, target.world_x, target.world_y))


def _execute_walk_to_pickup(decision: WalkToPickup, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Pickup, slot=decision.target_slot)
    if actor is None or target is None:
        return
    if abs(target.world_x - actor.world_x) <= PICKUP_RANGE_X and abs(target.world_y - actor.world_y) <= PICKUP_RANGE_Y:
        # Same B edge as weapons: $3136 find_close_interaction_target.
        gamepad.press(PUNCH_MASK, frames=PUNCH_FRAMES)
    else:
        gamepad.hold(_movement_mask(actor.world_x, actor.world_y, target.world_x, target.world_y))


_HANDLERS = {
    WalkToNearEnemy: _execute_walk_to_near_enemy,
    WalkToAdvanceStage: _execute_walk_to_advance_stage,
    Sidestep: _execute_sidestep,
    Punch: _execute_punch,
    RearAttack: _execute_rear_attack,
    CounterGrab: _execute_counter_grab,
    CallPolice: _execute_call_police,
    JumpAttack: _execute_jump_attack,
    Supplex: _execute_supplex,
    ThrowKnife: _execute_throw_knife,
    WalkToCoordinate: _execute_walk_to_coordinate,
    WalkToWeapon: _execute_walk_to_weapon,
    WalkToPickup: _execute_walk_to_pickup,
}


def execute_decision(decision: Decision, context: Context, gamepad: VirtualGamepad) -> None:
    handler = _HANDLERS.get(type(decision))
    if handler is None:
        press_no_button(gamepad)
        return
    handler(decision, context, gamepad)
