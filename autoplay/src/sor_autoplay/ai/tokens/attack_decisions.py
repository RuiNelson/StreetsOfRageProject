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

    Produced by ``should_punch`` when an enemy sits within the actor's punch
    band. A held bat/pipe shortens that band to its own measured 36px reach
    (weapons-range-and-damage.md) instead of the unarmed per-character table.

    Raises emergency: (Enemy when in a punishable phase)×60, Enemy×20.
    """

    priority: int = 10
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WeaponAttacks(Attack, ABC):
    """Attacks that require holding a weapon (e.g. ``ThrowKnife``,
    ``ThrowPepper`` — the only two weapon types the ROM attack-throws,
    per items-and-weapons.md's ``$21E6 (player_release_thrown_weapon)``)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ThrowKnife(WeaponAttacks):
    """Throw the held knife at an out-of-melee-range enemy.

    Produced by ``should_throw_knife`` when the actor holds a knife (type
    $08) and the nearest enemy is beyond melee but within knife range.

    Raises emergency: (Enemy when beyond melee and within knife range)×25.
    """

    priority: int = 11
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ThrowPepper(WeaponAttacks):
    """Throw the held pepper spray at an out-of-melee-range enemy.

    On hit it immobilizes the target rather than dealing the raw damage a
    knife throw does (items-and-weapons.md), making it a crowd-control tool.

    Produced by ``should_throw_pepper`` when the actor holds pepper spray
    (type $0C) and the nearest enemy is beyond melee but within throw range
    (reusing ``ThrowKnife``'s measured range constants — pepper's own
    effective throw range has not been separately measured).

    Raises emergency: (Enemy when beyond melee and within throw range)×25.
    """

    priority: int = 11
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Supplex(GrabMechanics):
    """Back-hold B — true suplex. Front-hold uses FlipHold first.

    Produced by ``should_hold_actions`` while the actor is in a confirmed
    back hold (base $66).

    Raises emergency: (Enemy when in the GRABBED phase)×68.
    """

    priority: int = 13
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AttackHeldEnemy(GrabMechanics):
    """Front-hold B (knee) — keeps the grab and damages.

    Produced by ``should_hold_actions`` in front hold (base $60) with no
    rear threat, or in an unknown hold-ish state.

    Raises emergency: (Enemy when in the GRABBED phase)×64.
    """

    priority: int = 14
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ThrowHeldEnemy(GrabMechanics):
    """Front-hold B+back — throws the held foe (useful vs a rear threat).

    Produced by ``should_hold_actions`` in front hold (base $60) when a
    rear threat is present.

    Raises emergency: (Enemy when in the GRABBED phase)×70.
    """

    priority: int = 16
    actor_slot: str
    target_slot: str  # held / primary target slot (for context)


@dataclass(frozen=True, slots=True, kw_only=True)
class FlipHold(GrabMechanics):
    """Front-hold C — crossover to back hold, then Supplex next ticks.

    Produced by ``should_hold_actions`` in front hold (base $60) as the
    crossover alternate to a knee or throw.

    Raises emergency: (Enemy when in the GRABBED phase)×66.
    """

    priority: int = 15
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ReleaseGrab(GrabMechanics):
    """Walk away opposite the held enemy to drop the grab.

    Produced by ``should_hold_actions`` in an unknown hold-ish state so the
    AI never idles inside a hold.

    Raises emergency: (Enemy when in the GRABBED phase)×50.
    """

    priority: int = 12
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class JumpAttack(MeleeAttacks):
    """Jump-kick only — never a stationary hop. Requires horizontal aim.

    Produced by ``should_jump_attack`` when a forward enemy sits in the
    horizontal jump band (outside punch outer, within the max ΔX).

    Raises emergency: (Enemy when in a punishable phase)×28, Enemy×18.
    """

    priority: int = 8  # below basic punch priority (10)
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SmashBreakable(Attack):
    """B near an intact prop (same input as punch; ROM hits the prop).

    Produced by ``should_smash_breakable`` when an intact Breakable is in
    smash range.

    Raises emergency: Breakable×16.
    """

    priority: int = 9
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RearAttack(MeleeAttacks):
    """Simultaneous B+C rear/escape attack (``$322A``).

    Produced by ``should_rear_attack`` when an enemy sits inside the
    character-specific ``$322A`` attack box (measured live,
    controls-and-input.md): behind the player for all three characters
    (Axel/Adam/Blaze up to 40/42/53px), and additionally in front only for
    Adam (up to 14px — his chord is a forward-reaching hop, not a backfist).

    Raises emergency: (Enemy when in a dangerous phase)×60, Enemy×55.

    Prefer when a close threat sits behind the player. For Adam only, also
    prefer it when a body has closed inside his hop's forward reach.
    """

    priority: int = 15
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CounterGrab(GrabMechanics):
    """Enemy-held counter: C edge then B edge while the window is open.

    Produced by ``should_counter_grab`` while the actor is held by an enemy
    (HELD_BY_ENEMY) and the counter is not already running.

    Raises emergency: (Myself when held by an enemy)×100 — the player is
    already grabbed and this is the only useful action.
    """

    priority: int = 40
    actor_slot: str

