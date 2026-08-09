"""``Enemy`` observation token and its per-type/boss-family subclasses.

Per ``ai-analysis/enemy-ai.md`` and ``world_map.py``'s ``MapEntity``: ordinary
enemies ($20-$2A) all share one object layout, so only Jack ($27) needs an
extra field (``family_state`` bit 0, weapon attached). Bosses split into two
families by which ``MapEntity`` fields the ``elif style.kind == "boss":``
branch actually populates: Abadede/Mr. X use a bespoke target pointer and
leave the tactical/pair_role/boss_dist_*/mode_flags/target_unavailable/
phase_timer/ground_z fields meaningless, while Souther/Antonio/Bongo/
Onihime-Yasha (all sharing type $58, distinguished only by ``pair_role`` at
runtime) fully populate them.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .character import Character


@dataclass(frozen=True, slots=True, kw_only=True)
class Enemy(Character):
    type_id: int
    targets_player: int | None  # 1 or 2, or None — from MapEntity.targets_player


@dataclass(frozen=True, slots=True, kw_only=True)
class Garcia(Enemy):
    """Types $20-$23."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Signal(Enemy):
    """Type $24."""


@dataclass(frozen=True, slots=True, kw_only=True)
class HakuRo(Enemy):
    """Types $25, $2A."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Nora(Enemy):
    """Type $26."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Jack(Enemy):
    """Type $27."""

    has_projectile: bool  # family_state bit 0 -- "weapon attached"


@dataclass(frozen=True, slots=True, kw_only=True)
class Boss(Enemy, ABC):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class BespokeBoss(Boss, ABC):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Abadede(BespokeBoss):
    """Type $30."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MrX(BespokeBoss):
    """Type $35."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LaterBoss(Boss, ABC):
    tactical: int
    pair_role: int
    boss_dist_x: int
    boss_dist_lane: int
    mode_flags: int
    target_unavailable: int
    phase_timer: int
    ground_z: int | None
    vel_x: float
    vel_z: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Souther(LaterBoss):
    """Type $55."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Antonio(LaterBoss):
    """Type $56."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Bongo(LaterBoss):
    """Type $57."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Onihime(LaterBoss):
    """Type $58. The ROM runs two same-type instances (Onihime + Yasha),
    distinguished at runtime by pair_role, not by different type ids."""


_TYPE_TO_CLASS: dict[int, type[Enemy]] = {
    0x20: Garcia,
    0x21: Garcia,
    0x22: Garcia,
    0x23: Garcia,
    0x24: Signal,
    0x25: HakuRo,
    0x2A: HakuRo,
    0x26: Nora,
    0x27: Jack,
    0x30: Abadede,
    0x35: MrX,
    0x55: Souther,
    0x56: Antonio,
    0x57: Bongo,
    0x58: Onihime,
}


def enemy_class_for_type(type_id: int) -> type[Enemy]:
    """Map a MapEntity.type_id to its concrete Enemy/Boss subclass.

    Falls back to the generic Enemy for anything unrecognized, matching
    object_catalog.py's own "unknown ranges still plot" fallback philosophy.
    """

    return _TYPE_TO_CLASS.get(type_id & 0xFF, Enemy)
