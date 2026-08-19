"""``Attack``-branch ``Verb`` tokens.

No separate ``Combo`` class: ``$3028 (player_normal_attack_input)`` is
documented as "normal-attack entry and combo continuation" -- one input, so
a melee strike executed every tick already produces the chain.

``GrabEnemy`` *is* its own class, though, because a grab is not that same
input at all. ``$AAA0`` reports contact code 3 only while the actor's
outgoing damage ``+$34`` is zero, and ``$3266`` turns that code into a hold
at the very top of the ground-action priority chain, before any button is
read (player-health-lives-and-combat.md's "Input and action selection").
A grab is therefore something a strike actively *prevents*: it is taken by
walking into an enemy without attacking.

``Punch`` and ``MeleeWeaponAttack`` both issue the identical physical
B-button press (see ``execute.py``'s shared ``state_machine_melee_strike``)
-- the ROM resolves a different move, reach, and damage purely from the
actor's held weapon type at execution time, which is why ``MeleeWeaponAttack``
carries that type as a plain ``weapon_type`` field rather than one class per
weapon group: nothing in this codebase ever branches on which weapon group
fired, only the ROM itself does, from state already on the actor.

``RearAttack`` is the simultaneous B+C chord (``$322A``): reaches *behind*
the player. ``CounterGrab`` is the enemy-held sequence (C crossover then B
throw) from ``controls-and-input.md``. ``GrabMechanics`` groups every move
that grabs a foe, exploits a held grab, or reacts to being grabbed.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Verb


@dataclass(frozen=True, slots=True, kw_only=True)
class Attack(Verb, ABC):
    """A verb that strikes a target — a foe, a prop, or a held body.

    Branch-wide emergency rule: whatever a concrete subclass's own
    ``Raises emergency`` line says, an attack whose target is a **stunned**
    ``Grunt`` (``Grunt.is_stunned``) is capped -- never raised -- by how
    much of the stun is left, read from the target's own ``stun_timer``:

    - a **hitstun** (at most ``phases.HITSTUN_FRAMES``) caps at
      ``priority._EMERGENCY_ATTACK_HITSTUN``, just above a plain strike, so
      the actor finishes the ROM's own 3-hit chain -- whose third hit is
      what knocks the enemy down -- instead of turning to an equally
      punchable fresh enemy;
    - anything longer is the ``$A0``-frame pepper-spray stun and caps at
      ``priority._EMERGENCY_ATTACK_LONG_STUN``, *below* a plain strike: that
      body is parked for nearly three seconds and anything that can still
      act matters more.

    Both stay far below the ``RearAttack`` escape, so a real threat
    elsewhere interrupts either one, and above every ``Walk`` tier, so the
    actor never walks off mid-stun to fetch a different enemy.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class MeleeAttacks(Attack, ABC):
    """Close-combat attacks that need no weapon.

    The family is exactly ``Punch`` / ``JumpAttack`` / ``RearAttack`` --
    all fire only while the actor is unarmed. ``MeleeWeaponAttack`` is the
    held-weapon melee sibling; ``WeaponAttacks`` groups the *thrown*
    weapon attacks (``ThrowKnife`` / ``ThrowPepper``); ``SmashBreakable``
    (hits a prop, not a foe) is a separate ``Attack`` branch, as is
    ``GrabMechanics``.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class GrabMechanics(Attack, ABC):
    """Any move that grabs a foe, exploits a held grab, or counters a grab.

    Covers taking the hold (``GrabEnemy``), the hold-move family
    (``AttackHeldEnemy`` / ``Supplex`` / ``ThrowHeldEnemy`` / ``FlipHold`` /
    ``ReleaseGrab``) and the reaction to being grabbed by an enemy
    (``CounterGrab``).
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class GrabEnemy(GrabMechanics):
    """Walk into an enemy, without attacking, to take a hold of it.

    Produced by ``could_grab_enemy`` for an unarmed, free-to-act actor when
    ``reach.grab_would_connect`` holds for the same enemy (possible) and
    ``reach.grab_reasons`` returns at least one reason (worth it), and
    ``reach.is_incoming_melee`` does not hold for it -- walking into a
    committed attack is how the actor gets hit rather than the hold.

    Raises emergency: (reach.grab_reasons includes CLEAR_REAR)×58,
    (reach.grab_reasons includes JACK_FROM_BEHIND)×56,
    (reach.grab_reasons includes ANTONIO_ON_PUNISH)×61,
    (reach.grab_reasons includes DEAD_ZONE)×30.

    The rear tier sits above every strike on an enemy that can still act
    (punch 20, jump 18/28), above the unwarranted ``RearAttack`` chord
    (9/11) and above the warranted chord against a rear enemy that is not
    itself committed (55): with a body available in front, throwing it
    backwards deals with that enemy *and* clears the actor's back, which the
    chord's own docstring admits it often whiffs at. It stays below the
    chord against an enemy already committed behind (60) -- there is no time
    to walk into anything then -- and below every hold move on a hold that
    already exists (64..70): using the hold beats taking another one.
    """

    priority: int = 17
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Punch(MeleeAttacks):
    """Basic B-button punch while unarmed; repeated contact also triggers
    the grab.

    Produced by ``could_punch`` when the actor holds no weapon and
    ``reach.punch_would_connect`` names an enemy its forward strike
    would connect with.

    Raises emergency: (target is punishable)×60, Enemy×20; plus
    the armed/boss target-class raise (see priority._with_target_class).
    """

    priority: int = 10
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MeleeWeaponAttack(Attack):
    """B-button melee strike while holding a weapon (bat/pipe, knife/bottle,
    or pepper spray) — as opposed to ``MeleeAttacks`` (unarmed) and
    ``WeaponAttacks`` (thrown).

    Same B-button press as ``Punch``, but the ROM resolves a different move,
    reach, and damage purely from ``weapon_type``, the pickup type the actor
    holds at execution time: bat/pipe ($0A/$0B), knife/bottle ($08/$09), or
    pepper spray ($0C). One class rather than one per weapon group
    (``SwingBatOrPipe``/``StabWithKnifeOrBottle``/``SprayPepper`` before this)
    because nothing here ever branched on which of the three fired — every
    could_*, emergency and execute handler was already the identical shared
    function, keyed by nothing but the class -- ``weapon_type`` carries the
    one real distinction. For the two weapon groups whose own melee reach has
    not been separately measured (knife/bottle, pepper), ``could_melee_
    weapon_attack`` reuses the unarmed punch band as the closest available
    evidence; bat/pipe uses its own measured 36px reach
    (weapons-range-and-damage.md), shorter than any character's unarmed
    punch_outer_x.

    Produced by ``could_melee_weapon_attack`` once per actor holding one of
    these weapon types, for an enemy ``reach.punch_would_connect`` names as
    connecting.

    Raises emergency: (Enemy when in a punishable phase)×60, Enemy×20.
    """

    priority: int = 10
    actor_slot: str
    target_slot: str
    weapon_type: int


@dataclass(frozen=True, slots=True, kw_only=True)
class WeaponAttacks(Attack, ABC):
    """Attacks that require holding a weapon (e.g. ``ThrowKnife``,
    ``ThrowPepper`` — the only two weapon types the ROM attack-throws,
    per items-and-weapons.md's ``$21E6 (player_release_thrown_weapon)``).

    Distinct from ``MeleeWeaponAttack``: this branch is specifically the
    *thrown* use of a held weapon, not its close-combat use.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ThrowKnife(WeaponAttacks):
    """Throw the held knife at an out-of-melee-range enemy.

    Produced by ``could_throw_knife`` once per on-screen enemy, when the
    actor holds a knife (type $08) and that enemy is beyond melee but
    within knife range -- never just the nearest; determine_priority_
    verb picks among the candidates.

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
    never just the nearest; determine_priority_verb picks among the
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

    Produced by ``could_jump_attack`` for a target ``reach.in_jump_attack_
    band`` names (forward, outside punch outer, within the kick's max ΔX)
    for which ``reach.is_incoming_melee`` does not hold against the actor --
    the kick's own travel would otherwise deliver it into a committed
    attack, airborne and unable to change its mind.

    Raises emergency: a committed Antonio kick gate×56, (target is
    punishable)×28, (Nora, not currently dangerous, within
    priority.NORA_RECOVERY_PUNISH_TICKS of her own last attack)×24,
    Enemy×18. Against a live Antonio the hop is also offered anywhere
    inside the kick's free-flight range (not only past punch outer);
    punch still wins in punch range, the grab still wins on hitstun.
    """

    priority: int = 8  # below basic punch priority (10)
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenBreakable(Attack):
    """Deal with an intact prop: close the distance if needed, then B.

    One verb rather than the former ``WalkToBreakable`` + ``SmashBreakable``
    pair. Splitting them described the *executor's* two states, not two
    intents: nothing ever wanted to walk to a prop without smashing it, and
    the walk half could win a tick, be re-proposed the next, and never hand
    over cleanly if the ranking drifted between the two tiers in between.
    The intent is "open that prop"; how far away the actor happens to be is
    the executor's problem (``execute.state_machine_open_breakable``) and the
    ranking's input, not a second verb.

    Produced by ``could_open_breakable`` once per in-camera ``Breakable``
    that is either already in smash range or ahead on the stage path --
    never a crate already behind (walking back to one, then advancing
    past it again, is the WalkToAdvanceStage limit cycle), and never just
    the nearest; determine_priority_verb picks among them.

    Raises emergency: (Breakable in smash range)×16, Breakable×14 otherwise,
    closer scoring higher (distance-scored; see
    priority._emergency_open_breakable).
    """

    priority: int = 9
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RearAttack(MeleeAttacks):
    """Simultaneous B+C rear/escape attack (``$322A``).

    Produced by ``could_rear_attack`` for a target ``reach.in_rear_band``
    names -- an enemy inside the character-specific ``$322A`` attack box
    (measured live, controls-and-input.md): behind the player for all
    three characters
    (Axel/Adam/Blaze up to 40/42/53px), and additionally in front only for
    Adam (up to 14px — his chord is a forward-reaching hop, not a backfist).

    Raises emergency, when ``reach.rear_attack_is_warranted`` holds --
    boxed in, punch dead zone, or ``Jack`` facing the actor (his axe and
    lunge punish a turn-and-punch): (Enemy when in a dangerous phase)×60,
    Enemy×55. On Jack's back the chord is refused -- turn and grab (``reach.
    grab_reasons`` includes ``JACK_FROM_BEHIND``). Otherwise, with a
    turn-and-punch available:
    (Enemy when in a dangerous phase)×11, Enemy×9.

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


@dataclass(frozen=True, slots=True, kw_only=True)
class HitAntonioBoomerang(MeleeAttacks):
    """Timed B-punch that knocks Antonio's boomerang (type ``$96``) away
    the moment it would hit the actor.

    Produced by ``could_hit_antonio_boomerang`` when an in-flight type-``$96``
    ``Projectile`` is heading at the actor, in lane, and inside the punch
    box at punch-connect time (startup + pipeline latency). Not produced
    while the boomerang is still attached to Antonio -- punching his hand
    is just standing still in front of him, which is how his kick starts.

    Raises emergency: (reach.projectile_threatens for this boomerang)×62 --
    above DodgeAntonioKick (58), because jumping into a boomerang that is
    already in the punch box is a free hit, and a punch is faster than the
    kick's own startup.
    """

    priority: int = 25
    actor_slot: str
    target_slot: str  # Projectile.slot of the boomerang

