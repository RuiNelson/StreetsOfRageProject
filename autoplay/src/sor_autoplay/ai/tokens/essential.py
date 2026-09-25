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
    """Where the actor can stand now, what the screen shows, and how far the
    corridor lets it go (user: "A IA não tem bem noção dos limites
    esquerda/direita de câmara (janela visível) e até onde pode se deslocar
    no mundo do jogo").

    ``left``/``right`` are ``$43AA``'s walk clamp, ``camera_x + $20 .. +
    $120``: no player origin stands outside it this frame. The visible screen
    is 32 px wider on each side (``visible_left``/``visible_right``,
    ``reach.SCREEN_STRIP_X``). ``reach_left``/``reach_right`` are the same
    clamp at the camera's own X bounds (``$FFE01E``/``$FFE01A`` + ``$20`` /
    ``+ $120``): the camera follows the player only between them, so that is
    as far as a walk can ever take the actor before the next wave gate opens.
    ``None`` when the bounds were not read; then only the clamp is known.
    """

    left: float
    right: float
    top: float
    bottom: float
    reach_left: float | None = None
    reach_right: float | None = None

    @property
    def visible_left(self) -> float:
        return self.left - CAMERA_CLAMP_LEFT

    @property
    def visible_right(self) -> float:
        return self.right + CAMERA_CLAMP_LEFT

    @property
    def world_left(self) -> float:
        """The farthest left an origin can get in this corridor."""

        return self.left if self.reach_left is None else min(self.left, self.reach_left)

    @property
    def world_right(self) -> float:
        """The farthest right an origin can get in this corridor."""

        return self.right if self.reach_right is None else max(self.right, self.reach_right)

    @property
    def scrolls_left(self) -> bool:
        """Walking into the left clamp can still move the camera."""

        return self.world_left < self.left

    @property
    def scrolls_right(self) -> bool:
        return self.world_right > self.right


# $43AA's clamp in screen X: the origin stays in $20..$120 of the 320 px
# screen, so the visible screen reaches $20 past it on each side.
CAMERA_CLAMP_LEFT = 0x20
CAMERA_CLAMP_RIGHT = 0x120


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


@dataclass(frozen=True, slots=True, kw_only=True)
class MrXOffice(Essential):
    """Round 8's last room: Mr. X's offer has run.

    Observed while ``$FFDE00 (mr_x_offer_flag)`` is set on level index 7 --
    it stays set from the offer through his fight. The Garcias the room sends
    (two, two more, then two with him, replaced as they die) are his helpers,
    and ``EngageMrX`` owns them, before he appears as well as after.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugNoFood(Essential):
    """Harness switch: leave every ``HealthPickup`` on the floor.

    **Not an observation.** Nothing in the ROM produces this; it is added by
    the runner (``--no-food``) so a boss fight can be *scored* without the
    arena's food flattering the result. Health eaten mid-fight hides damage
    the AI actually took -- ``boss_fight.py``'s ``damage_taken`` is a running
    minimum, so hits landed after a heal cost nothing on paper -- and a plan
    that only survives because it ate is not a plan.

    The AI must never come to depend on the token *existing*: it can only
    ever remove an option (``decide._food_is_spoken_for``), never add one, so
    a session without it behaves exactly as before.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugNoPolice(Essential):
    """Harness switch: never call the police special.

    **Not an observation**, exactly like ``DebugNoFood``: added by the runner
    (``--no-police``) so a fight is *scored* on what the plan itself does
    (user: "The police is allowed for Souther/Antonio, just don't test with
    the police on"). The special is ``$16A60``'s flat 10 off a later boss and
    a screen sweep otherwise; a measured fight it helped win measures the
    special, not the plan. It only ever removes ``CallPolice``
    (``decide.could_call_police``), never adds anything.
    """
