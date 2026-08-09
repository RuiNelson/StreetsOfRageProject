"""The police-special ``Attack`` decision.

``CallPolice`` is the A-button police special: an attack, so it descends
from ``Attack`` rather than directly from ``Decision``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .attack_decisions import Attack


@dataclass(frozen=True, slots=True, kw_only=True)
class CallPolice(Attack):
    """The A-button police special — a screen-clearing attack.

    Produced by ``should_call_police`` when the actor has a special and
    health_percent is below POLICE_HEALTH_PERCENT_THRESHOLD.

    Raises emergency: (Myself when health_percent is below
    POLICE_HEALTH_PERCENT_THRESHOLD)×88.
    """

    priority: int = 0
    actor_slot: str
