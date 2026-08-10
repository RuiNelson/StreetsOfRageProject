"""``Recovery``-branch ``Decision`` tokens.

Not ``Attack`` (strikes nothing), not ``Walk`` (no movement target), not
``GrabMechanics`` (not about a hold) -- a distinct family for actions whose
whole purpose is escaping or shortening a bad state the actor is already in.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Decision


@dataclass(frozen=True, slots=True, kw_only=True)
class Recovery(Decision, ABC):
    """A decision that escapes or shortens a bad state the actor is in,
    rather than acting on an enemy, prop, or held body."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TechRecover(Recovery):
    """Fresh C-edge + Up held: the bounce-cancel landing tech
    (controls-and-input.md "C+Up landing tech") that skips the knockdown
    bounce and lands like a jump instead.

    Produced by ``could_tech_recover`` while the actor's throw-tech window
    is armed and still open (``PlayableCharacter.throw_tech_ready``) --
    only specific special/boss hold-throw choreography arms it; an ordinary
    street-enemy throw never does, so this correctly never fires there.

    Raises emergency: (Myself when throw_tech_ready)×90 -- while this window
    is open the actor is airborne/hurt and free to act at nothing else, so
    it is scored just under CounterGrab's "only useful action" 100.
    """

    priority: int = 30
    actor_slot: str
