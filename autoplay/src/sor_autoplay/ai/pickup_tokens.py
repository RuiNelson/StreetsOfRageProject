"""Floor-weapon Information token (a Walk-branch pickup decision consumes this elsewhere)."""

from __future__ import annotations

from dataclasses import dataclass

from .tokens import Information


@dataclass(frozen=True, slots=True, kw_only=True)
class Weapon(Information):
    slot: str
    world_x: int
    world_y: int
    weapon_type: int  # 0x08 knife .. 0x0C pepper spray
