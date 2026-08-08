"""Projectile / danger-zone ``Information`` tokens.

``Projectile`` is a direct observation, built by ``observe.py`` in this
package. ``IncomingProjectile`` and ``DangerZone`` are inference outputs,
constructed elsewhere (the other engineer's ``inference.py``) from
``Projectile`` and ``Enemy`` tokens respectively; they live here only because
``inference.py`` imports the shapes from this module.
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
class DangerZone(Information):
    """Inference output (built elsewhere): an area to avoid/react to."""

    slot: str  # which player this danger zone concerns, e.g. "P1"
    left: float
    right: float
    top: float
    bottom: float
    threat_level: int
