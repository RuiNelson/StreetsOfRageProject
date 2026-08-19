"""Projectile ``Information`` tokens."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from ...hitboxes import Hitbox
from .tokens import Observed


@dataclass(frozen=True, slots=True, kw_only=True)
class Projectile(Observed):
    """Direct observation of a live projectile-kind object in flight.

    ``type_id`` distinguishes Jack's axe/torch helper (object_catalog.py
    type ``$28``) from every other projectile family: it is the one type
    whose object exists while still tethered to its owner's juggle, not
    only once thrown, so ``reach.jack_still_juggling`` needs it to tell the
    two apart.
    """

    slot: str
    world_x: int
    world_y: int
    vel_x: float
    vel_z: float
    type_id: int


@dataclass(frozen=True, slots=True, kw_only=True)
class StageObjects(Observed, ABC):
    """An inanimate object placed in the stage, observed directly from RAM."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Pit(StageObjects):
    """A floor gap (pit) the player can fall into.

    Observed from ``GameSnapshot.floor_holes`` (the ``hazards.py``
    collision-class scan); fields mirror ``FloorHole`` — an AABB of the
    open region, ``lane_y`` being the top lane in pixels.
    """

    world_x: int
    lane_y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Breakable(StageObjects):
    """Intact smashable prop (phone booth, crate, …) — punch to break.

    Observed from map entities with ``kind == "breakable"`` that are still
    intact (not debris). Blocks lateral progress until destroyed.
    """

    slot: str
    world_x: int
    world_y: int
    type_id: int
    # The prop's animation body box, rebuilt from the ROM shape tables.
    # This is what the prop *draws*, and it is not what stops a walking
    # actor: the wall is the per-type push-back rectangle in
    # ``sor_autoplay.prop_solids``, which navigation/execute route against
    # and which needs only ``type_id``. Kept for display and for anything
    # that wants the sprite's own extent.
    hitbox: Hitbox | None = None
