"""``Enemy`` observation token and its per-type/boss-family subclasses.

Per ``ai-analysis/enemy-ai.md`` and ``world_map.py``'s ``MapEntity``: ordinary
enemies ($20-$2A) all share one object layout, so only Jack ($27) needs an
extra field (``family_state`` bit 0, weapon attached). Every boss is a direct
``Boss`` subclass. The tactical/pair_role/boss_dist_*/mode_flags/
target_unavailable/phase_timer/ground_z/vel_* fields live on ``Boss`` with
defaults: Abadede/Mr. X use a bespoke target pointer and leave them at their
defaults (meaningless there), while Souther/Antonio/Bongo/Onihime-Yasha (all
sharing type $58, distinguished only by ``pair_role`` at runtime) fully
populate them.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .character import Character


@dataclass(frozen=True, slots=True, kw_only=True)
class Enemy(Character):
    """A hostile on-screen actor that can be hit and defeated."""

    type_id: int
    targets_player: int | None  # 1 or 2, or None — from MapEntity.targets_player


@dataclass(frozen=True, slots=True, kw_only=True)
class Grunt(Enemy, ABC):
    """An ordinary (non-boss) enemy."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Garcia(Grunt):
    """Garcia ordinary enemy (types $20-$23)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Signal(Grunt):
    """Signal ordinary enemy (type $24)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class HakuRo(Grunt):
    """HakuRo ordinary enemy (types $25, $2A)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Nora(Grunt):
    """Nora ordinary enemy (type $26)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Jack(Grunt):
    """Jack ordinary enemy (type $27); may carry a weapon."""

    has_projectile: bool  # family_state bit 0 -- "weapon attached"


@dataclass(frozen=True, slots=True, kw_only=True)
class Boss(Enemy, ABC):
    """A boss enemy with its own tactical state and behaviour fields."""

    tactical: int = 0  # boss +$67 substate; Abadede police latch when set
    pair_role: int = 0  # later-type +$5D (1/2) twin role when kind==boss
    boss_dist_x: int = 0  # later-type +$50 abs X to target
    boss_dist_lane: int = 0  # later-type +$52 abs lane to target
    mode_flags: int = 0  # later-type +$7B; twin bit1 = grab/throw AI path
    target_unavailable: int = 0  # later-type +$77 from $179F8
    phase_timer: int = 0  # later-type +$78 jump/throw timeline counter
    ground_z: int | None = None  # later-type +$4C ground/landing height
    vel_x: float = 0.0  # +$20 signed 16.16, ROM units per tick
    vel_z: float = 0.0  # +$24 signed 16.16, ROM units per tick


@dataclass(frozen=True, slots=True, kw_only=True)
class Abadede(Boss):
    """Abadede boss (type $30)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MrX(Boss):
    """Mr. X boss (type $35)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Souther(Boss):
    """Souther boss (type $55)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Antonio(Boss):
    """Antonio boss (type $56)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Bongo(Boss):
    """Bongo boss (type $57)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Onihime(Boss):
    """Onihime/Yasha twin boss (type $58).

    The ROM runs two same-type instances (Onihime + Yasha), distinguished at
    runtime by pair_role, not by different type ids.
    """


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
