"""``Walk``-branch ``Decision`` tokens."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Decision


@dataclass(frozen=True, slots=True, kw_only=True)
class Walk(Decision, ABC):
    """A decision to move the actor somewhere or toward something."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToNearEnemy(Walk):
    """Walk to a nearby on-screen enemy to bring it into attack range.

    Raises emergency: Enemy×14.
    """

    priority: int = 20
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToAdvanceStage(Walk):
    """Walk in the stage's progress direction to scroll it.

    Raises emergency: (no live Enemy anywhere)×12.

    Lowest of the Walk/Attack priorities: per AI.md, "picking up a weapon
    carries a higher priority than advancing to the next stage" -- this is
    the fallback when nothing more specific applies.
    """

    priority: int = 5
    actor_slot: str
    direction: str  # "left" | "right"


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToWeapon(Walk):
    """Walk to pick up a free ground weapon that outranks the held one.

    Raises emergency: (Weapon when its rank beats the held weapon's)×8.
    """

    priority: int = 22
    actor_slot: str
    target_slot: str  # Weapon.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToPickup(Walk):
    """Walk to (and B-pickup) a free ground consumable.

    Raises emergency: (HealthPickup when the actor's health is critical)×50,
    HealthPickup×15, LifePickup×12, SpecialPickup×9, ScorePickup×3.

    Priority sits above stage advance and below weapons: a needed health item
    outranks wandering, but a weapon upgrade is usually more durable value
    unless health is critical (emergency ranking handles that case).
    """

    priority: int = 18
    actor_slot: str
    target_slot: str  # Pickup.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToBreakable(Walk):
    """Approach an intact prop to smash it (or clear the path).

    Raises emergency: Breakable×14.
    """

    priority: int = 12
    actor_slot: str
    target_slot: str
