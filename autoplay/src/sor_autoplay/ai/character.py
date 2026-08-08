"""Playable-character ``Information`` tokens (``Myself`` / ``Partner``).

Per ``AI.md``: character identity (Axel/Adam/Blaze) is a plain attribute
rather than a subclass, since playable characters do not otherwise differ in
token structure.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from sor_autoplay.phases import CombatPhase

from .tokens import Information


@dataclass(frozen=True, slots=True, kw_only=True)
class Character(Information, ABC):
    slot: str  # "P1" or "P2"
    player_index: int  # 1 or 2
    character_id: int | None
    character_name: str
    world_x: int
    world_y: int
    health: int
    health_percent: float
    lives: int
    specials: int
    held_weapon_type: int  # 0 = none; else the weapon type id (0x08-0x0C)
    facing_left: bool
    combat_phase: CombatPhase
    action_state: int  # raw byte at +$30; front-hold $60 vs back-hold $66
    is_airborne: bool  # from MapEntity.is_airborne; future JumpAttack C-then-B


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayableCharacter(Character, ABC):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Myself(PlayableCharacter):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Partner(PlayableCharacter):
    pass
