"""``Walk``-branch ``Decision`` tokens (Phase A: approach and sidestep only)."""

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
