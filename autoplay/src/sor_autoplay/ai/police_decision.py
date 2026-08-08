"""The sole concrete ``Decision`` descending directly from the abstract class."""

from __future__ import annotations

from dataclasses import dataclass

from .tokens import Decision


@dataclass(frozen=True, slots=True, kw_only=True)
class CallPolice(Decision):
    priority: int = 0
    actor_slot: str
