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

    Produced by ``could_call_police`` when the actor has a special and either
    the boss that ends the round is alive on screen (``decide.
    level_end_boss_is_up``, whatever the health: the police on arrival), or
    at least one live enemy is in context and health_percent is below
    POLICE_HEALTH_PERCENT_THRESHOLD (or the higher
    POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE while on the last life, where
    a KO risks a continue/game-over instead of a free respawn). Otherwise the
    last resort and nothing more (user: "A AI está a depender muito da chamada
    da polícia!"): being surrounded or facing a mid-round boss is no reason.
    The twins get the arrival call only, never the panic one; Mr. X none; none under ``DebugNoPolice``.

    Raises emergency: 88 in either case.
    """

    priority: int = 0
    actor_slot: str
