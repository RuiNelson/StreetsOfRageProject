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
    at least one on-screen enemy exists and none carries an
    ``ActionableTarget`` for this actor yet (``reach.enemy_actionable``:
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
    see priority._emergency_walk_to_near_enemy).
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
    ``decide._advance_blocking_enemies``) -- and the stage has a progress
    direction.

    Raises emergency: (no blocking Enemy anywhere)×12.

    Lowest of the Walk/Attack priorities: per AI.md, "picking up a weapon
    carries a higher priority than advancing to the next stage" -- this is
    the fallback when nothing more specific applies.
    """

    priority: int = 5
    actor_slot: str
    direction: str  # "left" | "right"


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToWeapon(Walk):
    """Walk to pick up a free ground weapon that outranks the held one.

    Produced by ``could_walk_to_weapon`` once per ``WeaponUpgrade`` -- the
    inference that a ground weapon is in camera, still usable, and better
    than what this actor holds -- never just the best one;
    determine_priority_verb picks among the candidates.

    Raises emergency: WeaponUpgrade×3+rank
    (rank 2..5, so a better upgrade among several outranks a lesser one;
    see priority._emergency_walk_to_weapon).
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
    HealthPickup×15, LifePickup×12, SpecialPickup×9, ScorePickup×3.

    Priority sits above stage advance and below weapons: a needed health item
    outranks wandering, but a weapon upgrade is usually more durable value
    unless health is critical (emergency ranking handles that case).
    """

    priority: int = 18
    actor_slot: str
    target_slot: str  # Pickup.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class RetreatFromDanger(Walk):
    """Back away from a dangerous enemy that is not yet actionable, instead
    of closing the last stretch of distance into its committed attack.

    Produced by ``could_retreat_from_danger`` once per ``IncomingMelee``
    (an on-screen enemy in a dangerous phase, close enough that continuing
    to approach risks arriving right as its hit lands) that carries no
    ``ActionableTarget`` -- not really hittable yet -- and is not behind the
    actor; never just the nearest, determine_priority_verb picks among
    the candidates.
    ``could_walk_to_near_enemy`` skips producing a candidate for the same
    enemy in this zone, so the two never compete for the same target.

    Raises emergency: IncomingMelee×17, closer scoring higher
    (distance-scored; see
    priority._emergency_retreat_from_danger) -- higher than
    WalkToNearEnemy(14) so this wins over still approaching, lower than any
    real attack (the lowest being JumpAttack×18) so attacking always wins
    once actually possible.
    """

    priority: int = 21
    actor_slot: str
    target_slot: str
