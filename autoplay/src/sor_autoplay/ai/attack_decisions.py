"""``Attack``-branch ``Decision`` tokens.

No separate ``Combo``/``GrabEnemy`` classes: ``$3028
(player_normal_attack_input)`` is documented as "normal-attack entry and
combo continuation," and a grab is an emergent side effect of repeated
``Punch`` contact once the target's own state permits it -- there is no
distinct input for either, so ``Punch`` (executed every tick) already
produces both.
"""

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


@dataclass(frozen=True, slots=True, kw_only=True)
class ThrowKnife(Attack):
    priority: int = 11
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Supplex(Attack):
    priority: int = 13
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class JumpAttack(Attack):
    priority: int = 17
    actor_slot: str
    target_slot: str
