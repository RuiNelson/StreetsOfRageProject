"""``Walk``-branch ``Decision`` tokens."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Decision


@dataclass(frozen=True, slots=True, kw_only=True)
class Walk(Decision, ABC):
    """A decision to move the actor somewhere or toward something."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToNearEnemy(Walk):
    """Walk to a nearby on-screen enemy to bring it into attack range.

    Produced by ``should_walk_to_near_enemy`` when an on-screen enemy exists
    and no enemy is already within punch or rear range. Falls back to the
    nearest live enemy ahead in the stage's scroll direction when nothing
    is on-screen (e.g. the next wave, tracked on the world map but not yet
    in camera) -- never one behind, so this never walks backward for an
    abandoned off-screen leftover.

    Raises emergency: Enemy×14.
    """

    priority: int = 20
    actor_slot: str
    target_slot: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToAdvanceStage(Walk):
    """Walk in the stage's progress direction to scroll it.

    Produced by ``should_walk_to_advance_stage`` when no live Enemy token
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

    Produced by ``should_walk_to_weapon`` when an in-camera Weapon token
    ranks higher than the actor's held weapon.

    Raises emergency: (Weapon when its rank beats the held weapon's)×8.
    """

    priority: int = 22
    actor_slot: str
    target_slot: str  # Weapon.slot


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkToPickup(Walk):
    """Walk to (and B-pickup) a free ground consumable.

    Produced by ``should_walk_to_pickup`` when a useful Pickup token is in
    camera for the actor.

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
class WalkToBreakable(Walk):
    """Approach an intact prop to smash it (or clear the path).

    Produced by ``should_walk_to_breakable`` when an in-camera Breakable
    lies beyond smash range ahead of the actor.

    Raises emergency: Breakable×14.
    """

    priority: int = 12
    actor_slot: str
    target_slot: str
