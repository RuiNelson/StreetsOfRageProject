"""``Attack``-branch ``Decision`` tokens.

No separate ``Combo``/``GrabEnemy`` classes: ``$3028
(player_normal_attack_input)`` is documented as "normal-attack entry and
combo continuation," and a grab is an emergent side effect of repeated
``Punch`` contact once the target's own state permits it -- there is no
distinct input for either, so ``Punch`` (executed every tick) already
produces both.

``RearAttack`` is the simultaneous B+C chord (``$322A``): reaches *behind*
the player. ``CounterGrab`` is the enemy-held sequence (C crossover then B
throw) from ``controls-and-input.md``. ``GrabMechanics`` groups every move
that grabs a foe, exploits a held grab, or reacts to being grabbed.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Decision


@dataclass(frozen=True, slots=True, kw_only=True)
class Attack(Decision, ABC):
    """A decision that strikes a target — a foe, a prop, or a held body."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MeleeAttacks(Attack, ABC):
    """Close-combat attacks that need no weapon.

    The family is exactly ``Punch`` / ``JumpAttack`` / ``RearAttack``.
    ``ThrowKnife`` (needs a held weapon) and ``SmashBreakable`` (hits a prop,
    not a foe) are separate ``Attack`` branches, as is ``GrabMechanics``.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class GrabMechanics(Attack, ABC):
    """Any move that grabs a foe, exploits a held grab, or counters a grab.

    Covers the hold-move family (``AttackHeldEnemy`` / ``Supplex`` /
    ``ThrowHeldEnemy`` / ``FlipHold`` / ``ReleaseGrab``) and the reaction to
    being grabbed by an enemy (``CounterGrab``).
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class Punch(MeleeAttacks):
    """Basic B-button punch; repeated contact also triggers the grab.

    Raises emergency: (Enemy when in a punishable phase)×60, Enemy×20.
    """

    priority: int = 10
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WeaponAttacks(Attack, ABC):
    """Attacks that require holding a weapon (e.g. ``ThrowKnife``)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ThrowKnife(WeaponAttacks):
    """Throw the held knife at an out-of-melee-range enemy.

    Raises emergency: (Enemy when beyond melee and within knife range)×25.
    """

    priority: int = 11
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Supplex(GrabMechanics):
    """Back-hold B — true suplex. Front-hold uses FlipHold first.

    Raises emergency: (Enemy when held)×68.
    """

    priority: int = 13
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AttackHeldEnemy(GrabMechanics):
    """Front-hold B (knee) — keeps the grab and damages.

    Raises emergency: (Enemy when held)×64.
    """

    priority: int = 14
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ThrowHeldEnemy(GrabMechanics):
    """Front-hold B+back — throws the held foe (useful vs a rear threat).

    Raises emergency: (Enemy when held)×70.
    """

    priority: int = 16
    actor_slot: str
    target_slot: str  # held / primary target slot (for context)


@dataclass(frozen=True, slots=True, kw_only=True)
class FlipHold(GrabMechanics):
    """Front-hold C — crossover to back hold, then Supplex next ticks.

    Raises emergency: (Enemy when held)×66.
    """

    priority: int = 15
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ReleaseGrab(GrabMechanics):
    """Walk away opposite the held enemy to drop the grab.

    Raises emergency: (Enemy when held)×50.
    """

    priority: int = 12
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class JumpAttack(MeleeAttacks):
    """Jump-kick only — never a stationary hop. Requires horizontal aim.

    Raises emergency: (Enemy when in a punishable phase)×28, Enemy×18.
    """

    priority: int = 8  # below basic punch priority (10)
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SmashBreakable(Attack):
    """B near an intact prop (same input as punch; ROM hits the prop).

    Raises emergency: Breakable×16.
    """

    priority: int = 9
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RearAttack(MeleeAttacks):
    """Simultaneous B+C rear/escape attack (``$322A``).

    Raises emergency: (Enemy when in a dangerous phase)×60, Enemy×55.

    Prefer when a close threat sits behind the player, or when a body has
    closed inside the punch's inner dead zone (punch cannot connect).
    """

    priority: int = 15
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CounterGrab(GrabMechanics):
    """Enemy-held counter: C edge then B edge while the window is open.

    Raises emergency: (Myself when held by an enemy)×100 — the player is
    already grabbed and this is the only useful action.
    """

    priority: int = 40
    actor_slot: str

