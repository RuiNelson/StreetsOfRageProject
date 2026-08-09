"""Projectile ``Information`` tokens.

``Projectile`` is a direct observation, built by ``observe.py`` in this
package. ``IncomingProjectile`` is an inference output, constructed by
``inference.py`` from ``Projectile`` tokens; it lives here only because
``inference.py`` imports the shape from this module.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .tokens import Inferred, Observed


@dataclass(frozen=True, slots=True, kw_only=True)
class Projectile(Observed):
    """Direct observation of a live projectile-kind object in flight."""

    slot: str
    world_x: int
    world_y: int
    vel_x: float
    vel_z: float


@dataclass(frozen=True, slots=True, kw_only=True)
class IncomingProjectile(Inferred):
    """Inference output (built elsewhere): a Projectile judged to be a threat."""

    slot: str
    world_x: int
    world_y: int
    vel_x: float
    vel_z: float


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
