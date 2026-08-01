"""Standard Mega Drive button mapping used by the agents.

Matches ROM logical layout after ``remap_player_gameplay_input`` with
``control_scheme == 0`` (OPTIONS default):

| Physical | Logical role | ``Buttons`` mask |
|---|---|---|
| B | Attack / pickup | ``Buttons.B`` |
| C | Jump | ``Buttons.C`` |
| A | Police special | ``Buttons.A`` |

Host ``--altControls`` is **not** supported: that path remaps A/X/Y and
separates pickup from attack. Agents assume the classic 3-button layout only.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from megadrive_remote import Buttons
except ImportError:  # pragma: no cover - tests use pure masks
    from enum import IntFlag

    class Buttons(IntFlag):  # type: ignore[no-redef]
        NONE = 0
        UP = 1 << 0
        DOWN = 1 << 1
        LEFT = 1 << 2
        RIGHT = 1 << 3
        A = 1 << 4
        B = 1 << 5
        C = 1 << 6
        START = 1 << 7


# Semantic aliases for standard controls (scheme 0).
ATTACK = Buttons.B
JUMP = Buttons.C
SPECIAL = Buttons.A
# Rear / escape attack = attack+jump chord (either order edge-or-hold).
REAR_ATTACK = Buttons.B | Buttons.C

STANDARD_CONTROLS = {
    "scheme": 0,
    "alt_controls": False,
    "attack": int(ATTACK),
    "jump": int(JUMP),
    "special": int(SPECIAL),
    "rear_attack": int(REAR_ATTACK),
}


@dataclass(frozen=True, slots=True)
class Intent:
    """High-level one-tick intent before conversion to a button mask."""

    left: bool = False
    right: bool = False
    up: bool = False  # toward back of stage (smaller lane Y)
    down: bool = False  # toward front of stage (larger lane Y)
    attack: bool = False
    jump: bool = False
    special: bool = False
    rear_attack: bool = False
    # Menu / dialogue: confirm any face button (use attack).
    confirm: bool = False
    note: str = ""

    def empty(self) -> bool:
        return not any(
            (
                self.left,
                self.right,
                self.up,
                self.down,
                self.attack,
                self.jump,
                self.special,
                self.rear_attack,
                self.confirm,
            )
        )


def mask_from_intent(intent: Intent) -> int:
    """Convert an intent into a standard-controls button mask."""

    mask = int(Buttons.NONE)
    if intent.left:
        mask |= int(Buttons.LEFT)
    if intent.right:
        mask |= int(Buttons.RIGHT)
    if intent.up:
        mask |= int(Buttons.UP)
    if intent.down:
        mask |= int(Buttons.DOWN)
    if intent.special:
        mask |= int(SPECIAL)
    if intent.rear_attack:
        mask |= int(REAR_ATTACK)
    else:
        if intent.attack or intent.confirm:
            mask |= int(ATTACK)
        if intent.jump:
            mask |= int(JUMP)
    return mask
