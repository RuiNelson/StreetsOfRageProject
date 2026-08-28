"""``Walk``-branch ``Verb`` tokens."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Verb


@dataclass(frozen=True, slots=True, kw_only=True)
class Walk(Verb, ABC):
    """A verb to move the actor somewhere or toward something."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToNearEnemy(Walk):
    """Walk to a nearby on-screen enemy to bring it into attack range.

    Produced by ``could_walk_to_near_enemy`` once per reachable enemy when
    at least one on-screen enemy exists and it is not yet actionable for
    this actor (``reach.enemy_actionable``:
    within rear range *and* worth the RearAttack chord there, or within
    punch range and actually in front -- not just inside the punch box's raw
    distance, which ignores facing and would otherwise make this skip a
    behind enemy Punch itself refuses to hit, leaving the actor
    undefended) -- never just the nearest;
    determine_priority_verb picks among the candidates. Falls back to
    every live enemy ahead in the stage's scroll direction when nothing is
    on-screen (e.g. the next wave, tracked on the world map but not yet in
    camera) -- never one behind, so this never walks backward for an
    abandoned off-screen leftover.

    For an enemy at the actor's *back* this verb is the turn-around:
    holding the D-pad toward it is what sets facing, after which
    ``could_punch`` covers it normally (see
    ``execute._walk_to_near_enemy_target``). That makes it the fast,
    reliable alternative to the slow, whiff-prone ``RearAttack`` chord --
    which is why the rear band no longer counts as actionable on its own
    (``reach.rear_attack_is_warranted``) and why the dangerous-enemy
    caution-zone skip below is front-only.

    Raises emergency: Enemy×14, closer scoring higher (distance-scored;
    see priority._emergency_walk_to_near_enemy). An armed ordinary enemy
    adds ``priority._EMERGENCY_ARMED_TARGET`` and a ``Boss`` adds
    ``priority._EMERGENCY_BOSS_TARGET``, so a far armed foe still outranks
    a close unarmed one and a boss outranks both.
    """

    priority: int = 20
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToAdvanceStage(Walk):
    """Walk in the stage's progress direction to scroll it.

    Produced by ``could_walk_to_advance_stage`` when no live Enemy token
    remains anywhere -- except an off-screen enemy already at 0 health,
    which nothing in this pipeline will ever chase down to finish off (see
    ``decide._advance_blocking_enemies``) -- no on-camera Breakable sits
    on the stage path (``decide._advance_blocking_breakables``), and the
    stage has a progress direction.

    Raises emergency: (no blocking Enemy or ahead Breakable)×1.

    Lowest emergency of any verb that still scores: per AI.md, "picking up
    a weapon carries a higher priority than advancing to the next stage"
    -- this is the fallback when nothing more specific applies, and it
    must lose to every other live candidate (including a ScorePickup).
    """

    priority: int = 5
    actor_slot: str
    direction: str  # "left" | "right"


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToWeapon(Walk):
    """Walk to pick up a free ground weapon that outranks the held one.

    Produced by ``could_walk_to_weapon`` once per weapon
    ``reach.weapon_upgrade_rank`` judges an upgrade -- in camera, still
    usable, and better than what this actor holds -- never just the best
    one; determine_priority_verb picks among the candidates.

    Raises emergency: (weapon_upgrade_rank)×12+rank
    (rank 2..5, so a better upgrade among several outranks a lesser one, and
    every rank clears WalkToNearEnemy's floor(8) outright rather than merely
    tying it -- see priority._emergency_walk_to_weapon).
    """

    priority: int = 22
    actor_slot: str
    target_slot: str  # Weapon.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToPickup(Walk):
    """Walk to (and B-pickup) a free ground consumable.

    Produced by ``could_walk_to_pickup`` once per useful Pickup token in
    camera for the actor -- never just the best one; determine_priority_
    verb picks among the candidates via the already per-target emergency
    tiers below.

    Raises emergency: (HealthPickup when the actor's health is critical)×50,
    HealthPickup×15, LifePickup×12, SpecialPickup×11, ScorePickup×9.

    Priority sits above stage advance and below weapons: a needed health item
    outranks wandering, but a weapon upgrade is usually more durable value
    unless health is critical (emergency ranking handles that case).
    """

    priority: int = 18
    actor_slot: str
    target_slot: str  # Pickup.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class RetreatFromDanger(Walk):
    """Give up ground to a dangerous enemy, when the exchange is one the
    actor cannot currently afford to take.

    Produced by ``could_retreat_from_danger`` once per on-screen enemy
    ``reach.is_incoming_melee`` judges about to land on the actor (a
    dangerous phase, close enough that continuing to approach risks
    arriving right as its hit lands) that is not yet actionable -- not
    really hittable yet -- and **only while ``decide._retreat_is_worth_it``**:
    the actor is hurt, or ``Surrounded``. Danger alone is deliberately not
    enough, since no enemy can be defeated without standing in the range it
    hits back from. Never just the nearest; determine_priority_verb picks
    among the candidates.
    That same predicate decides which verb owns the enemy: while it holds,
    ``could_walk_to_near_enemy`` stands off; while it does not, that verb
    closes in and this one produces nothing. Exactly one of the two ever
    holds a given enemy, from whichever side it stands on.

    Raises emergency: (reach.is_incoming_melee for this target)×17, closer
    scoring higher (distance-scored; see
    priority._emergency_retreat_from_danger) -- higher than
    WalkToNearEnemy(14) so this wins over still approaching, lower than any
    real attack (the lowest being JumpAttack×18) so attacking always wins
    once actually possible.
    """

    priority: int = 21
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectileSidestep(Walk):
    """Step off an incoming projectile's own lane rather than stand in it.

    Produced by ``could_projectile_sidestep`` once per observed
    ``Projectile`` ``reach.projectile_threatens`` judges approaching, in
    lane, and within the impact window for this actor. Jack's thrown
    axe/torch (object_catalog.py type ``$28``) is the case this was built
    for -- an unarmed punch into the juggle trades hits (see
    ``could_punch``'s Jack exception; a held weapon still swings) and once
    he lets go, the axe/torch itself is a fast
    in-lane projectile with no answer but getting out of its way. While he
    is still juggling it, though, ``reach.jack_still_juggling`` keeps it out
    of consideration entirely -- the weapon's own spin can point its
    velocity straight at the actor without ever being thrown, and this verb
    has nothing to sidestep in that case. The verb still reacts to any other
    ``Projectile`` ``reach.projectile_threatens`` judges a threat, not just
    his.

    Raises emergency: (reach.projectile_threatens for this projectile)×45,
    sooner-to-impact scoring higher, floor 30 (see
    priority._emergency_projectile_sidestep) -- above every ordinary
    approach/retreat tier so the actor clears the lane before the weapon
    lands, below a guaranteed strike on a punishable target (60) and the
    RearAttack/CLEAR_REAR grab escapes, which stay the right answer even
    with a projectile also in flight.
    """

    priority: int = 23
    actor_slot: str
    target_slot: str  # Projectile.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class DodgeAntonioKick(Walk):
    """Leave Antonio's kick lane -- or hop over the kick -- before it lands.

    Produced by ``could_dodge_antonio_kick`` once per live Antonio whose kick
    gate (``reach.antonio_will_kick``) is live and who has already locked in
    the kick (primary ``$02``) or the dash/throw (tactical ``$08``). A
    predicted ``$16EAE`` window is not enough: sidestepping that made the AI
    leave hop range forever and never take the hold. The executor hops
    over the committed strike. The opener hop on a live Antonio is
    ``JumpAttack``, not this.

    Raises emergency: a committed Antonio kick gate×58 -- above every
    strike on an Antonio that can still act (20). A punish grab on
    hitstun (61+boss) outranks this, but the two do not coexist: a
    recovering Antonio does not satisfy the kick gate. Below
    CounterGrab/TechRecover/CallPolice, which stay the only answers to
    those situations.
    """

    priority: int = 24
    actor_slot: str
    target_slot: str  # Antonio.slot
    # False while his gate is merely *satisfiable* -- the ~10 ticks of warning
    # `reach.antonio_will_kick` gives before he actually commits, measured
    # over nine onsets in one fight (9-12 ticks on seven of them, 0 on the two
    # at his entrance). Committed is the old behaviour: hop the strike that is
    # already coming. Uncommitted is a pure lane step that *denies the gate*,
    # since `$16EAE` needs the target within `$10` (16px) of his lane and
    # nothing at all happens outside it.
    committed: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class DodgeSoutherSlash(Walk):
    """Step off the lane Souther's committed claw dash resolves on.

    Produced by ``could_dodge_souther_slash`` once per ``Souther`` whose
    ``strike_is_committed()`` holds (primary ``$02``). A lane step is the whole
    answer here, and specifically **not** a hop: the dash at
    ``$161C6 (souther_state2_claw_dash)`` writes only ``+$1C``, so it cannot
    follow a lane change once committed, and it only resolves with the target
    within ``$18`` (24px) of its lane -- while a jump is the one input
    ``$16234 (souther_counter_jump_attack)`` punishes outright. The exact
    mirror of ``DodgeAntonioKick``, whose dash *does* track lane and therefore
    has to be hopped instead.

    Raises emergency: a committed Souther claw gate×46 -- above every
    approach/retreat tier and above ProjectileSidestep's own ceiling (45), so
    the claw is answered first when both are live. Below the real escapes
    (RearAttack 55/60, the punish grab 61) and below
    CounterGrab/TechRecover/CallPolice.
    """

    priority: int = 24
    actor_slot: str
    target_slot: str  # Souther.slot
