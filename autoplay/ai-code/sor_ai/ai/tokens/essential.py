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
    """The camera's visible world rectangle.

    ``left``/``right`` are the players' walk clamp (``$43AA``): the camera's
    X plus ``$20`` .. ``$120``, or plus ``0`` .. ``$140`` under ``--widescreen``
    (``widescreen``). ``scroll_x`` is the camera's own X, which a hand-built
    token may leave out (``origin_x`` then assumes the plain clamp).
    ``scroll_open`` is whether walking can scroll the camera, false at a locked
    wave gate or in a boss arena (``world_map.camera_scroll_is_open``).
    """

    left: float
    right: float
    top: float
    bottom: float
    scroll_x: float | None = None
    widescreen: bool = False
    scroll_open: bool = True

    @property
    def origin_x(self) -> float:
        """The camera's X (sprite space 0): what ``cam_x`` means in the ROM."""

        return self.scroll_x if self.scroll_x is not None else self.left - 0x20

    @property
    def center_x(self) -> float:
        """The middle of the visible playfield: the camera's X plus ``$A0``,
        which both walk clamps are centred on."""

        return (self.left + self.right) / 2


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
class PlayerDuel(Essential):
    """Mr. X's betrayal duel: the two players fight each other.

    Observed while ``$FFDE00 (mr_x_offer_flag)`` is set, ``$FFFA43
    (duel_damage_modifier)`` is nonzero and the offer's state is ``$22``-``$29``.
    ``$11F74 (mr_x_offer_compare_2p_choices)`` sends two different answers to
    ``$11FA8 (mr_x_offer_start_duel)``, which sets the byte; ``$11E72
    (mr_x_offer_wait_duel_end)`` moves the state on once one player is out, and
    clears the byte only if that player is P2, so the byte alone would read as a
    duel through the survivor's fight with Mr. X. For as long as it holds, the other
    player is no ``Partner`` but a ``RivalPlayer``: ``$4478`` deals the attack
    descriptor's damage (tripled) to them like to any enemy.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class DebugMrXAccept(Essential):
    """Harness switch: answer YES to Mr. X instead of NO.

    Only for measuring the betrayal duel without a human: one AI accepts, the
    other refuses, and ``$11F74`` starts the duel. Never on in play.
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


@dataclass(frozen=True, slots=True, kw_only=True)
class SixButtonLayout(Essential):
    """The player is on ENHANCED 6: the 6-button layout.

    Added by ``AgentLoop`` from that player's scheme in the game data
    (``sor_remote.SoRClient.refresh_schemes``), not read from RAM: its presence swaps the buttons that differ -- the rear
    attack is A, the police special X, a pickup Y and the knife throw Z -- and
    B stops picking things up (``execute.rear_attack_mask`` and the other
    mask helpers, ``reach.item_a_b_press_takes``). Without it every mask is
    the original three-button scheme's, as before.
    """
