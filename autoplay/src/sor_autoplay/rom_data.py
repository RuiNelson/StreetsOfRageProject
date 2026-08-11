"""The static ROM tables the observer needs, read once per connection.

Everything here is cartridge ROM: it cannot change while the game runs, so
re-reading it per tick would cost link traffic for nothing. ``ObserverApp``
reads it when the link comes up and threads it through ``read_snapshot`` into
``world_map.parse_world_map``.

Kept separate from the two table modules it bundles so that ``hitboxes`` and
``attack_ranges`` stay pure over already-read bytes, testable without a link.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .attack_ranges import AnimationSets
from .hitboxes import ShapeTables


class MemorySource(Protocol):
    def read_memory(self, address: int, length: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class RomData:
    """Collision shapes plus every ordinary-enemy animation set."""

    shapes: ShapeTables
    animations: AnimationSets

    @classmethod
    def read(cls, client: MemorySource) -> RomData:
        return cls(
            shapes=ShapeTables.read(client),
            animations=AnimationSets.read(client),
        )
