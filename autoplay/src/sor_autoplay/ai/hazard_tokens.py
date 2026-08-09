"""Projectile ``Information`` tokens.

``Projectile`` is a direct observation, built by ``observe.py`` in this
package. ``IncomingProjectile`` is an inference output, constructed by
``inference.py`` from ``Projectile`` tokens; it lives here only because
``inference.py`` imports the shape from this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tokens import Information


@dataclass(frozen=True, slots=True, kw_only=True)
class Projectile(Information):
    """Direct observation of a live projectile-kind object in flight."""

    slot: str
    world_x: int
    world_y: int
    vel_x: float
    vel_z: float


@dataclass(frozen=True, slots=True, kw_only=True)
class IncomingProjectile(Information):
    """Inference output (built elsewhere): a Projectile judged to be a threat."""

    slot: str
    world_x: int
    world_y: int
    vel_x: float
    vel_z: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Breakable(Information):
    """Intact smashable prop (phone booth, crate, …) — punch to break.

    Observed from map entities with ``kind == "breakable"`` that are still
    intact (not debris). Blocks lateral progress until destroyed.
    """

    slot: str
    world_x: int
    world_y: int
    type_id: int
