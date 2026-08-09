"""Floor-item ``Information`` tokens: weapons and consumable pickups.

Weapon damage ranking (``items-and-weapons.md`` / ``weapons-range-and-damage.md``):

    knife 5 > bat/pipe 4 > bottle 3 > pepper 2

``weapon_rank`` exposes that order so ``should_walk_to_weapon`` can treat a
higher rank as an upgrade. Pepper is weakest by raw damage; its immobilize
utility is a separate inference concern, not a pickup rank boost.

Consumable types and effect indices match ``$3136`` /
``items-and-weapons.md``:

| Type | Effect index | Effect |
| ---: | ---: | --- |
| ``$47`` | 0 | Full health (+80, clamp 80) |
| ``$4B`` | 1 | Small health (+20, clamp 80) |
| ``$4C`` | 2 | Extra life |
| ``$4F`` | 3 | Extra police special |
| ``$3F`` | 4 | 3,000 score |
| ``$40`` | 5 | 10,000 score |
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Observed

# ROM init damage at weapon +$34 — also the upgrade rank for floor pickups.
WEAPON_DAMAGE: dict[int, int] = {
    0x08: 5,  # knife
    0x0A: 4,  # baseball bat
    0x0B: 4,  # steel pipe
    0x09: 3,  # bottle
    0x0C: 2,  # pepper spray
}

WEAPON_TYPE_MIN = 0x08
WEAPON_TYPE_MAX = 0x0C

# Pickup type → (effect index, health delta if any). Health deltas match
# $6A04/$6A08: full food +$50 (80), apple +$14 (20).
_PICKUP_EFFECT: dict[int, int] = {
    0x47: 0,
    0x4B: 1,
    0x4C: 2,
    0x4F: 3,
    0x3F: 4,
    0x40: 5,
}

HEALTH_DELTA: dict[int, int] = {
    0x47: 80,
    0x4B: 20,
}

PLAYER_MAX_HEALTH = 80


def weapon_rank(weapon_type: int) -> int:
    """Return the damage-based upgrade rank of a weapon type (0 if unarmed/unknown)."""

    return WEAPON_DAMAGE.get(weapon_type & 0xFF, 0)


def is_weapon_type(type_id: int) -> bool:
    return WEAPON_TYPE_MIN <= (type_id & 0xFF) <= WEAPON_TYPE_MAX


def is_pickup_type(type_id: int) -> bool:
    return (type_id & 0xFF) in _PICKUP_EFFECT


@dataclass(frozen=True, slots=True, kw_only=True)
class Weapon(Observed):
    """Free ground weapon eligible for ``$3136`` pickup (``+$51==0``, wear ``<$3``)."""

    slot: str
    world_x: int
    world_y: int
    weapon_type: int  # 0x08 knife .. 0x0C pepper spray
    wear: int = 0  # object +$50; usable while < 3


@dataclass(frozen=True, slots=True, kw_only=True)
class Pickup(Observed, ABC):
    """Free ground consumable (``kind==pickup`` and ``+$51==0``)."""

    slot: str
    world_x: int
    world_y: int
    pickup_type: int


@dataclass(frozen=True, slots=True, kw_only=True)
class HealthPickup(Pickup):
    """Food: full (``$47``, +80) or small apple (``$4B``, +20)."""

    health_delta: int  # 80 or 20


@dataclass(frozen=True, slots=True, kw_only=True)
class LifePickup(Pickup):
    """Extra-life item (``$4C``)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SpecialPickup(Pickup):
    """Extra police-special item (``$4F``)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ScorePickup(Pickup):
    """Score bonus: 3,000 (``$3F``) or 10,000 (``$40``)."""

    points: int


def pickup_class_for_type(type_id: int) -> type[Pickup] | None:
    """Map a consumable object type to its concrete ``Pickup`` subclass."""

    t = type_id & 0xFF
    if t in (0x47, 0x4B):
        return HealthPickup
    if t == 0x4C:
        return LifePickup
    if t == 0x4F:
        return SpecialPickup
    if t in (0x3F, 0x40):
        return ScorePickup
    return None


def build_pickup_token(
    *,
    slot: str,
    world_x: int,
    world_y: int,
    pickup_type: int,
) -> Pickup | None:
    """Construct the concrete consumable token for a free ground pickup entity."""

    t = pickup_type & 0xFF
    cls = pickup_class_for_type(t)
    if cls is None:
        return None
    if cls is HealthPickup:
        return HealthPickup(
            slot=slot,
            world_x=world_x,
            world_y=world_y,
            pickup_type=t,
            health_delta=HEALTH_DELTA.get(t, 20),
        )
    if cls is LifePickup:
        return LifePickup(slot=slot, world_x=world_x, world_y=world_y, pickup_type=t)
    if cls is SpecialPickup:
        return SpecialPickup(slot=slot, world_x=world_x, world_y=world_y, pickup_type=t)
    if cls is ScorePickup:
        points = 10000 if t == 0x40 else 3000
        return ScorePickup(
            slot=slot,
            world_x=world_x,
            world_y=world_y,
            pickup_type=t,
            points=points,
        )
    return None
