"""Translate the PPO policy's continuous output into Mega Drive input."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


ACTION_SIZE = 6
FRAMES_PER_ACTION = 12
RADIUS_NOISE_THRESHOLD = 0.25
BUTTON_THRESHOLD = 0.5

# Keep these protocol values dependency-free so action tests and event
# monitoring do not need the training stack or remote package installed.
UP = 1 << 0
DOWN = 1 << 1
LEFT = 1 << 2
RIGHT = 1 << 3
A = 1 << 4
B = 1 << 5
C = 1 << 6
START = 1 << 7

ACTION_LOW = (-1.0, -1.0, 0.0, 0.0, 0.0, 0.0)
ACTION_HIGH = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

# Screen coordinates: +x moves right and +y moves down.
_DIRECTIONS = (
    ("right", RIGHT),
    ("down_right", DOWN | RIGHT),
    ("down", DOWN),
    ("down_left", DOWN | LEFT),
    ("left", LEFT),
    ("up_left", UP | LEFT),
    ("up", UP),
    ("up_right", UP | RIGHT),
)


@dataclass(frozen=True)
class DecodedAction:
    """One fixed 12-frame action interval."""

    buttons: int
    held_frames: int
    total_frames: int
    direction: str | None


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, float(value)))


def decode_action(action: Sequence[float]) -> DecodedAction:
    """Quantize ``[x, y, radius, A, B, C]`` into controller input."""

    if len(action) != ACTION_SIZE:
        raise ValueError(f"action must contain exactly {ACTION_SIZE} values")

    x = _clamp(action[0], -1.0, 1.0)
    y = _clamp(action[1], -1.0, 1.0)
    radius = _clamp(action[2], 0.0, 1.0)

    if radius <= RADIUS_NOISE_THRESHOLD:
        return DecodedAction(0, 0, FRAMES_PER_ACTION, None)

    # The open interval above 0.25 maps monotonically to 1..12 frames.
    normalized = (radius - RADIUS_NOISE_THRESHOLD) / (
        1.0 - RADIUS_NOISE_THRESHOLD
    )
    held_frames = min(
        FRAMES_PER_ACTION,
        max(1, math.ceil(normalized * FRAMES_PER_ACTION)),
    )

    buttons = 0
    direction: str | None = None
    if x != 0.0 or y != 0.0:
        angle = math.atan2(y, x)
        sector = int(math.floor((angle + math.pi / 8.0) / (math.pi / 4.0))) % 8
        direction, direction_buttons = _DIRECTIONS[sector]
        buttons |= direction_buttons

    if float(action[3]) > BUTTON_THRESHOLD:
        buttons |= A
    if float(action[4]) > BUTTON_THRESHOLD:
        buttons |= B
    if float(action[5]) > BUTTON_THRESHOLD:
        buttons |= C

    return DecodedAction(
        buttons=buttons,
        held_frames=held_frames,
        total_frames=FRAMES_PER_ACTION,
        direction=direction,
    )
