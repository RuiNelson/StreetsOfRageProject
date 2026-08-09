"""Playable-character ``Information`` tokens (``Myself`` / ``Partner``).

Per ``AI.md``: character identity (Axel/Adam/Blaze) is a plain attribute
rather than a subclass, since playable characters do not otherwise differ in
token structure.

Action-state conventions (``controls-and-input.md``,
``player-health-lives-and-combat.md``):

- ``+$30`` bit 0 = facing left; even base is the action family.
- Front hold ``$60`` / back hold ``$66`` accept B/C edges for knee/throw/suplex.
- Enemy-held sequence ``$78`` → ``$7A`` → optional crossover ``$7C`` → counter
  ``$7E``; ``action_flags`` bit 7 is the post-crossover B window (``+$58``).
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from sor_autoplay.phases import CombatPhase

from .tokens import Observed

# Measured normal-punch attack boxes facing right (controls-and-input.md):
# outer X edge of +$64; inner X is the dead zone (body already past the box).
# Usable centre-to-centre is a few px past the outer edge (victim body ~13 wide).
PUNCH_INNER_X: dict[int, int] = {0: 16, 1: 8, 2: 18}  # Axel, Adam, Blaze
PUNCH_OUTER_X: dict[int, int] = {0: 50, 1: 48, 2: 60}  # slightly inside measured outer
PUNCH_RANGE_Y = 12  # attack box Y is ±8; leave a small lane slack
DEFAULT_PUNCH_INNER_X = 14
DEFAULT_PUNCH_OUTER_X = 48


def punch_inner_x(character_id: int | None) -> int:
    if character_id is None:
        return DEFAULT_PUNCH_INNER_X
    return PUNCH_INNER_X.get(character_id, DEFAULT_PUNCH_INNER_X)


def punch_outer_x(character_id: int | None) -> int:
    if character_id is None:
        return DEFAULT_PUNCH_OUTER_X
    return PUNCH_OUTER_X.get(character_id, DEFAULT_PUNCH_OUTER_X)


@dataclass(frozen=True, slots=True, kw_only=True)
class Character(Observed, ABC):
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
    is_airborne: bool  # from MapEntity.is_airborne; JumpAttack C-then-B
    # player +$58: bit 7 = grab-counter B window after C crossover ($7C).
    action_flags: int = 0

    @property
    def action_base(self) -> int:
        """Action family with facing bit cleared."""

        return self.action_state & 0xFE

    @property
    def counter_window_open(self) -> bool:
        """True when the held-by-enemy counter accepts a B edge (``+$58`` bit 7)."""

        return bool(self.action_flags & 0x80)


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayableCharacter(Character, ABC):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Myself(PlayableCharacter):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Partner(PlayableCharacter):
    pass
