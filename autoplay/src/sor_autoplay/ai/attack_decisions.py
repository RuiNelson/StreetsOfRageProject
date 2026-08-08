"""``Attack``-branch ``Decision`` tokens (Phase A: ``Punch`` only)."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Decision


@dataclass(frozen=True, slots=True, kw_only=True)
class Attack(Decision, ABC):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Punch(Attack):
    priority: int = 10
    actor_slot: str
    target_slot: str
