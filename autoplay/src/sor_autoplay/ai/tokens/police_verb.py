"""The police-special ``Attack`` verb.

``CallPolice`` is the A-button police special: an attack, so it descends
from ``Attack`` rather than directly from ``Verb``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .attack_verbs import Attack


@dataclass(frozen=True, slots=True, kw_only=True)
class CallPolice(Attack):
    """The A-button police special — a screen-clearing attack.

    Produced by ``could_call_police`` when the actor has a special, at
    least one live enemy is in context, and either health_percent is below
    POLICE_HEALTH_PERCENT_THRESHOLD (or the higher
    POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE while on the last life, where
    a KO risks a continue/game-over instead of a free respawn), or a
    ``Surrounded`` names the actor while it is below the laxer
    POLICE_HEALTH_PERCENT_THRESHOLD_SURROUNDED -- being boxed in is the
    other situation only this move answers, since it is the one attack that
    clears every side at once. A special with nobody to sweep is a waste.

    Raises emergency: (Myself when health_percent is below that same
    lives-aware threshold)×88, Surrounded×80.
    """

    priority: int = 0
    actor_slot: str
