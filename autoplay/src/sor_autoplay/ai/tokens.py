"""Base ``Token``/``Information``/``Decision`` hierarchy and context lookup.

Per ``AI.md``: a ``Token`` never embeds another ``Token`` by value. Any
relationship between two tokens is expressed as a reference to the related
token's ``slot`` identifier (the stable per-tick id ``world_map.py`` already
assigns, e.g. ``"P1"`` / ``"obj07"``) and resolved with :func:`find` /
:func:`find_all` rather than held directly.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import TypeVar

TokenT = TypeVar("TokenT", bound="Token")


@dataclass(frozen=True, slots=True, kw_only=True)
class Token(ABC):
    """Common base for every ``Information`` and ``Decision``.

    ``priority`` only breaks ties between ``Decision`` tokens that
    :func:`determine_priority_decision <sor_autoplay.ai.priority.determine_priority_decision>`
    ranks as equally emergent; it plays no role in emergency ranking itself.
    """

    priority: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class Information(Token, ABC):
    """A directly observed or inferred state of the game."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Decision(Token, ABC):
    """A deliberated, parametrized intent — not yet a control signal."""


# The AI loop's working set for one player, one tick. Plain ``set`` (not a
# richer index) matches AI.md's process loop, which builds and narrows this
# collection with ``|=`` and set comprehensions.
Context = set[Token]


def find(context: Context, cls: type[TokenT], *, slot: str | None = None) -> TokenT | None:
    """Return one token of type ``cls`` from ``context``, or ``None``.

    ``slot`` narrows to a token whose ``slot`` attribute matches (for tokens
    that reference a specific entity, e.g. an ``Enemy``). Tokens without a
    ``slot`` attribute never match a ``slot``-qualified lookup.
    """

    for token in context:
        if not isinstance(token, cls):
            continue
        if slot is not None and getattr(token, "slot", None) != slot:
            continue
        return token
    return None


def find_all(context: Context, cls: type[TokenT]) -> list[TokenT]:
    """Return every token of type ``cls`` in ``context``, in no particular order."""

    return [token for token in context if isinstance(token, cls)]
