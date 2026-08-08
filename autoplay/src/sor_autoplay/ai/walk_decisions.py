"""``Walk``-branch ``Decision`` tokens."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Decision


@dataclass(frozen=True, slots=True, kw_only=True)
class Walk(Decision, ABC):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToNearEnemy(Walk):
    priority: int = 20
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Sidestep(Walk):
    priority: int = 30
    actor_slot: str
    threat_slot: str
    direction: str  # "up" | "down"


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToAdvanceStage(Walk):
    # Lowest of the Walk/Attack priorities: per AI.md, "picking up a weapon
    # carries a higher priority than advancing to the next stage" -- this is
    # the fallback when nothing more specific applies.
    priority: int = 5
    actor_slot: str
    direction: str  # "left" | "right"


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToCoordinate(Walk):
    priority: int = 25
    actor_slot: str
    target_x: int
    target_y: int


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToWeapon(Walk):
    priority: int = 22
    actor_slot: str
    target_slot: str  # Weapon.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToPickup(Walk):
    """Walk to (and B-pickup) a free ground consumable.

    Priority sits above stage advance and below weapons: a needed health item
    outranks wandering, but a weapon upgrade is usually more durable value
    unless health is critical (emergency ranking handles that case).
    """

    priority: int = 18
    actor_slot: str
    target_slot: str  # Pickup.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToBreakable(Walk):
    """Approach an intact prop to smash it (or clear the path)."""

    priority: int = 12
    actor_slot: str
    target_slot: str
