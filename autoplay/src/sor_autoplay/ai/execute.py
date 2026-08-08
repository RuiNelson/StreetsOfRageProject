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

from .attack_decisions import Punch
from .character import Myself, Partner
from .enemy import Enemy
from .police_decision import CallPolice
from .tokens import Context, Decision, find
from .walk_decisions import Sidestep, WalkToNearEnemy
from .gamepad import VirtualGamepad

UP_MASK = 0x0001
DOWN_MASK = 0x0002
LEFT_MASK = 0x0004
RIGHT_MASK = 0x0008
PUNCH_MASK = 0x0020  # physical B — verified mapping, see module docstring
CALL_POLICE_MASK = 0x0010  # physical A — verified mapping, see module docstring
PUNCH_FRAMES = 4
CALL_POLICE_FRAMES = 4


def press_no_button(gamepad: VirtualGamepad) -> None:
    """The AI.md 'do nothing' case."""

    gamepad.release()


def _find_actor(context: Context, slot: str) -> Myself | Partner | None:
    for actor in (find(context, Myself), find(context, Partner)):
        if actor is not None and actor.slot == slot:
            return actor
    return None


def _execute_walk_to_near_enemy(decision: WalkToNearEnemy, context: Context, gamepad: VirtualGamepad) -> None:
    actor = _find_actor(context, decision.actor_slot)
    target = find(context, Enemy, slot=decision.target_slot)
    if actor is None or target is None:
        return

    mask = 0
    if target.world_x > actor.world_x:
        mask |= RIGHT_MASK
    elif target.world_x < actor.world_x:
        mask |= LEFT_MASK
    # world_map.py convention: smaller world_y = back of stage = "up".
    if target.world_y > actor.world_y:
        mask |= DOWN_MASK
    elif target.world_y < actor.world_y:
        mask |= UP_MASK
    gamepad.hold(mask)


def _execute_sidestep(decision: Sidestep, context: Context, gamepad: VirtualGamepad) -> None:
    if decision.direction == "up":
        gamepad.hold(UP_MASK)
    elif decision.direction == "down":
        gamepad.hold(DOWN_MASK)


def _execute_punch(decision: Punch, context: Context, gamepad: VirtualGamepad) -> None:
    gamepad.press(PUNCH_MASK, frames=PUNCH_FRAMES)


def _execute_call_police(decision: CallPolice, context: Context, gamepad: VirtualGamepad) -> None:
    gamepad.press(CALL_POLICE_MASK, frames=CALL_POLICE_FRAMES)


_HANDLERS = {
    WalkToNearEnemy: _execute_walk_to_near_enemy,
    Sidestep: _execute_sidestep,
    Punch: _execute_punch,
    CallPolice: _execute_call_police,
}


def execute_decision(decision: Decision, context: Context, gamepad: VirtualGamepad) -> None:
    handler = _HANDLERS.get(type(decision))
    if handler is None:
        press_no_button(gamepad)
        return
    handler(decision, context, gamepad)
