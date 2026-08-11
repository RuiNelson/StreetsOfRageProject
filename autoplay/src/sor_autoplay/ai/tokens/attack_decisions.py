"""``Attack``-branch ``Decision`` tokens.

No separate ``Combo``/``GrabEnemy`` classes: ``$3028
(player_normal_attack_input)`` is documented as "normal-attack entry and
combo continuation," and a grab is an emergent side effect of repeated
melee-strike contact once the target's own state permits it -- there is no
distinct input for either, so a melee strike (executed every tick) already
produces both.

``Punch``, ``SwingBatOrPipe``, ``StabWithKnifeOrBottle``, and ``SprayPepper``
all issue the identical physical B-button press (see ``execute.py``'s shared
``_execute_melee_strike``) -- the ROM resolves a different move, reach, and
damage purely from the actor's held weapon type. They are kept as distinct
``Decision`` classes (rather than one ``Punch`` covering every held weapon)
because they are not the same move: different animation, hitbox, and damage
per weapons-range-and-damage.md / items-and-weapons.md, even though nothing
about the *input* differs.

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

    The family is exactly ``Punch`` / ``JumpAttack`` / ``RearAttack`` --
    all fire only while the actor is unarmed. ``MeleeWeaponAttacks`` groups
    the held-weapon melee siblings (``SwingBatOrPipe`` / ``StabWithKnife
    OrBottle`` / ``SprayPepper``); ``WeaponAttacks`` groups the *thrown*
    weapon attacks (``ThrowKnife`` / ``ThrowPepper``); ``SmashBreakable``
    (hits a prop, not a foe) is a separate ``Attack`` branch, as is
    ``GrabMechanics``.
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
    """Basic B-button punch while unarmed; repeated contact also triggers
    the grab.

    Produced by ``could_punch`` when the actor holds no weapon and an
    ``InPunchReach`` names an enemy its forward strike would connect with.

    Raises emergency: (PunishWindow for the target)×60, Enemy×20.
    """

    priority: int = 10
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MeleeWeaponAttacks(Attack, ABC):
    """Close-combat attacks that require holding a specific weapon type —
    as opposed to ``MeleeAttacks`` (unarmed) and ``WeaponAttacks`` (thrown).

    Same B-button press as ``Punch``, but the ROM resolves a different move,
    reach, and damage depending on the held weapon: ``SwingBatOrPipe``
    (bat/pipe, $0A/$0B), ``StabWithKnifeOrBottle`` (knife/bottle, $08/$09),
    ``SprayPepper`` (pepper spray, $0C).
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class SwingBatOrPipe(MeleeWeaponAttacks):
    """B-button swing while holding a bat or pipe (types $0A/$0B).

    Produced by ``could_swing_bat_or_pipe`` when an enemy sits within the
    weapon's measured 36px reach (weapons-range-and-damage.md), shorter than
    any character's unarmed punch_outer_x.

    Raises emergency: (Enemy when in a punishable phase)×60, Enemy×20.
    """

    priority: int = 10
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class StabWithKnifeOrBottle(MeleeWeaponAttacks):
    """B-button stab while holding a knife or bottle (types $08/$09), used
    when the enemy is too close to throw the knife instead.

    Produced by ``could_stab_with_knife_or_bottle`` when an enemy sits
    within the actor's unarmed punch band (this weapon's own melee reach
    has not been separately measured, so the unarmed table is reused as the
    closest available evidence).

    Raises emergency: (Enemy when in a punishable phase)×60, Enemy×20.
    """

    priority: int = 10
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SprayPepper(MeleeWeaponAttacks):
    """B-button melee spray while holding pepper spray (type $0C), used
    when the enemy is too close to throw it instead.

    Produced by ``could_spray_pepper`` when an enemy sits within the
    actor's unarmed punch band (this weapon's own melee reach has not been
    separately measured, so the unarmed table is reused as the closest
    available evidence).

    Raises emergency: (Enemy when in a punishable phase)×60, Enemy×20.
    """

    priority: int = 10
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WeaponAttacks(Attack, ABC):
    """Attacks that require holding a weapon (e.g. ``ThrowKnife``,
    ``ThrowPepper`` — the only two weapon types the ROM attack-throws,
    per items-and-weapons.md's ``$21E6 (player_release_thrown_weapon)``).

    Distinct from ``MeleeWeaponAttacks``: this branch is specifically the
    *thrown* use of a held weapon, not its close-combat use.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ThrowKnife(WeaponAttacks):
    """Throw the held knife at an out-of-melee-range enemy.

    Produced by ``could_throw_knife`` once per on-screen enemy, when the
    actor holds a knife (type $08) and that enemy is beyond melee but
    within knife range -- never just the nearest; determine_priority_
    decision picks among the candidates.

    Raises emergency: (Enemy when beyond melee and within knife range)×25,
    closer scoring higher (distance-scored; see
    priority._emergency_thrown_weapon).
    """

    priority: int = 11
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ThrowPepper(WeaponAttacks):
    """Throw the held pepper spray at an out-of-melee-range enemy.

    On hit it immobilizes the target rather than dealing the raw damage a
    knife throw does (items-and-weapons.md), making it a crowd-control tool.

    Produced by ``could_throw_pepper`` once per on-screen enemy, when the
    actor holds pepper spray (type $0C) and that enemy is beyond melee but
    within throw range (reusing ``ThrowKnife``'s measured range constants —
    pepper's own effective throw range has not been separately measured) --
    never just the nearest; determine_priority_decision picks among the
    candidates.

    Raises emergency: (Enemy when beyond melee and within throw range)×25,
    closer scoring higher (distance-scored; see
    priority._emergency_thrown_weapon).
    """

    priority: int = 11
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Supplex(GrabMechanics):
    """Back-hold B — true suplex. Front-hold uses FlipHold first.

    Produced by ``could_hold_actions`` while the actor is in a confirmed
    back hold (base $66).

    Raises emergency: (Enemy when in the GRABBED phase)×68.
    """

    priority: int = 13
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AttackHeldEnemy(GrabMechanics):
    """Front-hold B (knee) — keeps the grab and damages.

    Produced by ``could_hold_actions`` in front hold (base $60) with no
    rear threat, or in an unknown hold-ish state.

    Raises emergency: (Enemy when in the GRABBED phase)×64.
    """

    priority: int = 14
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ThrowHeldEnemy(GrabMechanics):
    """Front-hold B+back — throws the held foe (useful vs a rear threat).

    Produced by ``could_hold_actions`` in front hold (base $60) when a
    rear threat is present.

    Raises emergency: (Enemy when in the GRABBED phase)×70.
    """

    priority: int = 16
    actor_slot: str
    target_slot: str  # held / primary target slot (for context)


@dataclass(frozen=True, slots=True, kw_only=True)
class FlipHold(GrabMechanics):
    """Front-hold C — crossover to back hold, then Supplex next ticks.

    Produced by ``could_hold_actions`` in front hold (base $60) as the
    crossover alternate to a knee or throw.

    Raises emergency: (Enemy when in the GRABBED phase)×66.
    """

    priority: int = 15
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ReleaseGrab(GrabMechanics):
    """Walk away opposite the held enemy to drop the grab.

    Produced by ``could_hold_actions`` in an unknown hold-ish state so the
    AI never idles inside a hold.

    Raises emergency: (Enemy when in the GRABBED phase)×50.
    """

    priority: int = 12
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class JumpAttack(MeleeAttacks):
    """Jump-kick only — never a stationary hop. Requires horizontal aim.

    Produced by ``could_jump_attack`` for an ``InJumpAttackReach`` target
    (forward, outside punch outer, within the kick's max ΔX) that has no
    ``IncomingMelee`` against the actor -- the kick's own travel would
    otherwise deliver it into a committed attack, airborne and unable to
    change its mind.

    Raises emergency: (PunishWindow for the target)×28, Enemy×18.
    """

    priority: int = 8  # below basic punch priority (10)
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SmashBreakable(Attack):
    """B near an intact prop (same input as punch; ROM hits the prop).

    Produced by ``could_smash_breakable`` when an intact Breakable is in
    smash range.

    Raises emergency: Breakable×16.
    """

    priority: int = 9
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RearAttack(MeleeAttacks):
    """Simultaneous B+C rear/escape attack (``$322A``).

    Produced by ``could_rear_attack`` for an ``InRearReach`` target -- an
    enemy inside the character-specific ``$322A`` attack box (measured live,
    controls-and-input.md): behind the player for all three characters
    (Axel/Adam/Blaze up to 40/42/53px), and additionally in front only for
    Adam (up to 14px — his chord is a forward-reaching hop, not a backfist).

    Raises emergency, when ``reach.rear_attack_is_warranted`` holds --
    i.e. the actor is boxed in between two enemies, or the target is inside
    the punch dead zone, the two cases where turning around solves nothing:
    (Enemy when in a dangerous phase)×60, Enemy×55. Otherwise, with a
    turn-and-punch available: (Enemy when in a dangerous phase)×11,
    Enemy×9.

    The chord costs up to 21 frames of startup and hits only by current
    position, so it whiffs whenever the target drifts during that window and
    leaves the actor in its recovery frames. That is why band membership
    alone does not make it preferred: it stays a produced, usable option,
    but ranks under the ``WalkToNearEnemy`` turn-around
    (``execute._walk_to_near_enemy_target``) that reaches the same enemy
    faster and more reliably. For Adam only, the forward reach of his hop
    ($322A is a hop for him, not a backfist) means the same applies to a
    body closed inside 14px in front.
    """

    priority: int = 15
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CounterGrab(GrabMechanics):
    """Enemy-held counter: C edge then B edge while the window is open.

    Produced by ``could_counter_grab`` while the actor is held by an enemy
    (HELD_BY_ENEMY) and the counter is not already running.

    Raises emergency: (Myself when held by an enemy)×100 — the player is
    already grabbed and this is the only useful action.
    """

    priority: int = 40
    actor_slot: str

