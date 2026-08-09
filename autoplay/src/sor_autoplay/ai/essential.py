"""Essential ``Information`` tokens not tied to any character or enemy type.

See ``AI.md``'s "Essential Tokens" section.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tokens import Observed


@dataclass(frozen=True, slots=True, kw_only=True)
class Stage(Observed):
    level_index: int
    direction: str  # "right" for level_index 0-5, "none" for 6, "left" for 7


@dataclass(frozen=True, slots=True, kw_only=True)
class CameraRange(Observed):
    left: float
    right: float
    top: float
    bottom: float


@dataclass(frozen=True, slots=True, kw_only=True)
class AnimationInProgress(Observed):
    slot: str  # "P1" or "P2" — which character this blocks from acting
