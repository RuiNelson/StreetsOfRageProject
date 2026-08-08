"""``Attack``-branch ``Decision`` tokens.

No separate ``Combo``/``GrabEnemy`` classes: ``$3028
(player_normal_attack_input)`` is documented as "normal-attack entry and
combo continuation," and a grab is an emergent side effect of repeated
``Punch`` contact once the target's own state permits it -- there is no
distinct input for either, so ``Punch`` (executed every tick) already
produces both.

``RearAttack`` is the simultaneous B+C chord (``$322A``): reaches *behind*
the player. ``CounterGrab`` is the enemy-held sequence (C crossover then B
throw) from ``controls-and-input.md``.
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


@dataclass(frozen=True, slots=True, kw_only=True)
class RearAttack(Attack):
    """Simultaneous B+C rear/escape attack (``$322A``).

    Prefer when a close threat sits behind the player, or when a body has
    closed inside the punch's inner dead zone (punch cannot connect).
    """

    priority: int = 15
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CounterGrab(Attack):
    """Enemy-held counter: C edge then B edge while the window is open.

    Highest emergency among attacks — the player is already grabbed.
    """

    priority: int = 40
    actor_slot: str

