"""Essential ``Information`` tokens not tied to any character or enemy type.

See ``AI.md``'s "Essential Tokens" section. ``Essential`` groups the shared
scene-wide observations: the current stage, the camera's frame, any
animation currently blocking a playable character, and the continue / Mr. X
UI prompts.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Observed


@dataclass(frozen=True, slots=True, kw_only=True)
class Essential(Observed, ABC):
    """A scene-wide observation not tied to a specific character or enemy."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Stage(Essential):
    """The current stage and its progress direction."""

    level_index: int
    direction: str  # "right" for level_index 0-5, "none" for 6, "left" for 7


@dataclass(frozen=True, slots=True, kw_only=True)
class CameraRange(Essential):
    """The camera's visible world rectangle."""

    left: float
    right: float
    top: float
    bottom: float


@dataclass(frozen=True, slots=True, kw_only=True)
class AnimationInProgress(Essential):
    """A playable character currently locked in an animation."""

    slot: str  # "P1" or "P2" — which character this blocks from acting


@dataclass(frozen=True, slots=True, kw_only=True)
class InContinueMenu(Essential):
    """This player's object is the type-$0F continue / name-entry UI.

    Observed while the actor is dead and the ROM has replaced their
    playable object with the continue prompt (player-health-lives-and-
    combat.md). ``name_entry`` is object+$4B bit7: the high-score initials
    screen that runs *before* Yes/No when the score qualifies. ``selects_no``
    is the Yes/No cursor (object+$63 nonzero); it is always False during
    name-entry, where that byte is the letter index instead.
    """

    slot: str
    name_entry: bool
    selects_no: bool
    name_slot: int = 0
    name_letter_index: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class InMrXDialog(Essential):
    """This player's Mr. X offer-choice UI is live.

    Observed when ``$FFDE00 (mr_x_offer_flag)`` is set *and* object+$59
    bit 4 marks this player's choice as active (story-mode-and-campaign-
    flow.md §7.4). ``selects_no`` is object+$59 bit 3.
    """

    slot: str
    selects_no: bool
