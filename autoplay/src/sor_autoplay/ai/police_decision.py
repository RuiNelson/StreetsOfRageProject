"""The police-special ``Attack`` decision.

``CallPolice`` is the A-button police special: an attack, so it descends
from ``Attack`` rather than directly from ``Decision``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .attack_decisions import Attack


@dataclass(frozen=True, slots=True, kw_only=True)
class CallPolice(Attack):
    priority: int = 0
    actor_slot: str
