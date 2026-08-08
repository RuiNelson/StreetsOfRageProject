"""Generic ``Enemy`` observation token.

Phase A intentionally has no per-enemy-type subclasses (e.g. ``Garcia``) —
see ``AI.md``'s class hierarchy sketch for that future work.
"""

from __future__ import annotations

from dataclasses import dataclass

from sor_autoplay.phases import CombatPhase

from .tokens import Information


@dataclass(frozen=True, slots=True, kw_only=True)
class Enemy(Information):
    slot: str  # e.g. "obj07" — MapEntity.slot
    type_id: int
    world_x: int
    world_y: int
    health: int | None
    combat_phase: CombatPhase
    targets_player: int | None  # 1 or 2, or None — from MapEntity.targets_player
    facing_left: bool
