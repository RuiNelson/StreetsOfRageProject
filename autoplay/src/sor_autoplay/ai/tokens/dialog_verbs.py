"""``Dialog``-branch ``Verb`` tokens.

UI prompts the AI has to answer through the controller -- not combat, not
walking, not recovery. Each is the only useful action while its matching
``Essential`` token is in context.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Verb

# High-score initials the AI always types (A, I, then finish so the third
# character stays the cleared-to-zero space). $57D2's alphabet is 0=A ..
# 25=Z, 26=END; confirming END or pressing Start after two letters leaves
# the unused slot as 0, which the score table renders as a space.
CONTINUE_INITIALS = "AI "
NAME_LETTER_A = 0
NAME_LETTER_I = 8
NAME_LETTER_END = 26
NAME_ALPHABET_SIZE = 27


@dataclass(frozen=True, slots=True, kw_only=True)
class Dialog(Verb, ABC):
    """A verb that answers a game UI prompt rather than acting in combat."""


@dataclass(frozen=True, slots=True, kw_only=True)
class HandleContinueMenu(Dialog):
    """Always continue, and type ``AI `` on the high-score name entry.

    Produced by ``could_handle_continue_menu`` whenever ``InContinueMenu``
    is in context. Yes/No toggles on an UP/DOWN edge of ``$FFFC05`` and a
    face button confirms (``$52AE``); name-entry walks the letter index at
    object+$62 with Left/Right, confirms with C or A (``$57D2`` bits 5+6 --
    B is backspace and a no-op on the first slot), and finishes with Start.

    Raises emergency: (InContinueMenu)×99 -- the only useful action while
    the type-$0F object owns the slot.
    """

    priority: int = 0
    actor_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class HandleMrXDialog(Dialog):
    """Always refuse Mr. X's offer (held Down, then a face button).

    Produced by ``could_handle_mr_x_dialog`` whenever ``InMrXDialog`` is in
    context. ``$120EC`` reads *held* object+$54: Down sets +$59 bit 3 (NO),
    any remapped face bit registers the choice (story-mode-and-campaign-
    flow.md §7.4). Accepting writes the bad ending; the AI never does.

    Raises emergency: (InMrXDialog)×99 -- control is locked to this prompt.
    """

    priority: int = 0
    actor_slot: str
