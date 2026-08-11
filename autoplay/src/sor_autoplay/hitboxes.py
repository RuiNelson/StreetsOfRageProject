"""Reconstruct the ROM's real collision AABBs for any object.

Two different mechanisms produce the same shape of box, and the difference
matters for anything that wants to *observe* them:

* **Players** cache their boxes in work RAM. ``$4140`` runs in the player
  update path (its only call site is ``$1CC6`` inside ``sub_001bdc``, which
  identifies itself as player code by testing the character id at ``+$50``)
  and writes six absolute words at ``+$64`` (attack) and ``+$70`` (body).
  Those are readable directly -- see :func:`cached_box`.

* **Enemies and every other object cache nothing.** ``$AA34`` walks the
  registered-object list and both players, and ``$AAA0`` resolves contact by
  calling ``$AB24`` with a *box id* -- the enemy's own ``+$2`` (attack) or
  ``+$3`` (body), written per animation frame -- which rebuilds the AABB from
  ROM shape tables on the spot, every test, and throws it away. There is no
  enemy hitbox to read out of RAM; it has to be reconstructed the same way
  the ROM builds it, which is what :func:`build_box` does.

  (This is also why ``enemy-ai.md``'s object-field table can list ``+$64`` as
  a target pointer and ``+$70/+$72`` as attacker/player pointers without
  contradicting the player layout above: those offsets only hold boxes for
  objects that run ``$4140``.)

``$AB24`` / ``$AB88``, transcribed::

    a5 = $01A68E                      ; object shape table
    if object.type (+$0) == $58:      ; Onihime/Yasha borrow the player table
        a5 = $01ABA8
    a3 = a5 + 5 * box_id              ; 5-byte record

    x0 = object.x    (+$10) + s8(rec[0]);  x1 = x0 + s8(rec[1])
    lane = $01AB8E + 2 * rec[2]       ; lane extents live in their own table
    y0 = object.lane (+$14) + s8(lane[0]); y1 = y0 + s8(lane[1])
    z0 = object.z    (+$18) + s8(rec[3]);  z1 = z0 + s8(rec[4])

Every edge is an absolute world coordinate, and every table byte is
sign-extended (``ext.w d5`` in ``$AB88`` -- including the second one, which
``weapons-range-and-damage.md`` describes as an unsigned width). A box id of
zero means the frame has no box of that kind at all: ``$AAA0`` tests the id
and skips the overlap check entirely.

Mirroring is *not* done here. ``$AB24`` computes a side selector into ``d6``
and never reads it back; the shape table instead carries separate forward and
backward records (``$06``/``$07``, ``$0C``/``$0D``, ``$12``/``$13``), and the
animation data picks the one matching facing. So a reconstructed box is
already correctly oriented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# ROM table addresses, read straight off the routines above.
ROM_OBJECT_SHAPE_TABLE = 0x01A68E
ROM_LANE_EXTENT_TABLE = 0x01AB8E
ROM_PLAYER_SHAPE_TABLE = 0x01ABA8

SHAPE_RECORD_BYTES = 5
LANE_RECORD_BYTES = 2

# The three tables sit back to back, so two of the three sizes are exact:
# $1A68E..$1AB8E is 0x500 bytes of 5-byte records, and $1AB8E..$1ABA8 is 26
# bytes of 2-byte lane pairs.
OBJECT_SHAPE_COUNT = (ROM_LANE_EXTENT_TABLE - ROM_OBJECT_SHAPE_TABLE) // SHAPE_RECORD_BYTES
LANE_EXTENT_COUNT = (ROM_PLAYER_SHAPE_TABLE - ROM_LANE_EXTENT_TABLE) // LANE_RECORD_BYTES
# The player table's end is not bounded by a known neighbour. Read the same
# span as the object table: over-reading is harmless (records are only ever
# indexed by a box id the game itself produced) and it costs one 1280-byte
# read, once, of static ROM.
PLAYER_SHAPE_COUNT = OBJECT_SHAPE_COUNT

# Onihime/Yasha ($58) is the one non-player object $AB24 builds from the
# player shape table instead of the object one.
PLAYER_SHAPE_TABLE_TYPES = frozenset({0x58})

# Object fields holding this frame's box ids (written by the animation
# engine; zero means "no box of this kind on this frame").
OBJ_ATTACK_BOX_ID = 0x02
OBJ_BODY_BOX_ID = 0x03

# Player-only cached boxes: six absolute words each, [x0, x1, y0, y1, z0, z1].
OBJ_CACHED_ATTACK_BOX = 0x64
OBJ_CACHED_BODY_BOX = 0x70
CACHED_BOX_WORDS = 6
CACHED_BOX_BYTES = CACHED_BOX_WORDS * 2


class MemorySource(Protocol):
    def read_memory(self, address: int, length: int) -> bytes: ...


def _s8(value: int) -> int:
    return value - 0x100 if value >= 0x80 else value


def _s16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big", signed=True)


@dataclass(frozen=True, slots=True)
class Box:
    """An absolute-world-coordinate AABB, exactly as the ROM compares them.

    ``y`` is the lane (depth) axis and ``z`` is height; the HUD map plots
    ``x``/``y`` only, matching how it already ignores ``world_z``.
    """

    x0: int
    x1: int
    y0: int
    y1: int
    z0: int
    z1: int

    @property
    def is_degenerate(self) -> bool:
        """True when the box cannot overlap anything.

        ``$4140``'s no-box path fills the cached words with a constant
        (``memfill_long_12``), which collapses every axis to zero width --
        that, not a specific fill value, is what "the frame has no attack"
        actually looks like in RAM.
        """

        return self.x1 <= self.x0 or self.y1 <= self.y0

    def overlaps(self, other: Box) -> bool:
        """The ROM's own test ($AB88, run per axis, X then lane then Z)."""

        return (
            self.x0 < other.x1
            and other.x0 < self.x1
            and self.y0 < other.y1
            and other.y0 < self.y1
            and self.z0 < other.z1
            and other.z0 < self.z1
        )


@dataclass(frozen=True, slots=True)
class ShapeTables:
    """The three static ROM tables ``$AB24`` indexes.

    Read once per connection: they are ROM, so they never change, and a
    per-tick re-read would cost 1.3 KB of link traffic for nothing.
    """

    object_shapes: bytes
    player_shapes: bytes
    lane_extents: bytes

    @classmethod
    def read(cls, client: MemorySource) -> ShapeTables:
        return cls(
            object_shapes=client.read_memory(
                ROM_OBJECT_SHAPE_TABLE, OBJECT_SHAPE_COUNT * SHAPE_RECORD_BYTES
            ),
            player_shapes=client.read_memory(
                ROM_PLAYER_SHAPE_TABLE, PLAYER_SHAPE_COUNT * SHAPE_RECORD_BYTES
            ),
            lane_extents=client.read_memory(
                ROM_LANE_EXTENT_TABLE, LANE_EXTENT_COUNT * LANE_RECORD_BYTES
            ),
        )

    def shape_record(self, box_id: int, *, player_table: bool) -> bytes | None:
        table = self.player_shapes if player_table else self.object_shapes
        start = box_id * SHAPE_RECORD_BYTES
        record = table[start : start + SHAPE_RECORD_BYTES]
        return record if len(record) == SHAPE_RECORD_BYTES else None

    def lane_record(self, lane_id: int) -> bytes | None:
        start = lane_id * LANE_RECORD_BYTES
        record = self.lane_extents[start : start + LANE_RECORD_BYTES]
        return record if len(record) == LANE_RECORD_BYTES else None


def build_box(
    tables: ShapeTables,
    *,
    box_id: int,
    world_x: int,
    lane_y: int,
    world_z: int,
    player_table: bool = False,
) -> Box | None:
    """Rebuild one AABB the way ``$AB24`` does, or ``None`` for no box.

    ``None`` covers both a zero ``box_id`` (the frame carries no box of this
    kind -- ``$AAA0`` skips the overlap test outright) and an id that falls
    outside the table, which should not happen for ids the game produced but
    must not raise if it does.
    """

    if box_id == 0:
        return None
    record = tables.shape_record(box_id, player_table=player_table)
    if record is None:
        return None
    lane = tables.lane_record(record[2])
    if lane is None:
        return None

    x0 = world_x + _s8(record[0])
    y0 = lane_y + _s8(lane[0])
    z0 = world_z + _s8(record[3])
    return Box(
        x0=x0,
        x1=x0 + _s8(record[1]),
        y0=y0,
        y1=y0 + _s8(lane[1]),
        z0=z0,
        z1=z0 + _s8(record[4]),
    )


def uses_player_shape_table(type_id: int) -> bool:
    return type_id in PLAYER_SHAPE_TABLE_TYPES


def object_boxes(
    tables: ShapeTables,
    slot: bytes,
    *,
    type_id: int,
    world_x: int,
    lane_y: int,
    world_z: int,
) -> tuple[Box | None, Box | None]:
    """``(attack_box, body_box)`` for a non-player object.

    Positions are passed in rather than re-decoded here so this stays a pure
    function over already-decoded coordinates -- ``world_map`` owns the
    fixed-point conventions.
    """

    player_table = uses_player_shape_table(type_id)
    build = lambda box_id: build_box(  # noqa: E731 - three identical bound args
        tables,
        box_id=box_id,
        world_x=world_x,
        lane_y=lane_y,
        world_z=world_z,
        player_table=player_table,
    )
    return build(slot[OBJ_ATTACK_BOX_ID]), build(slot[OBJ_BODY_BOX_ID])


def cached_box(slot: bytes, offset: int) -> Box | None:
    """Read a player's already-built box straight out of its object.

    Returns ``None`` when the six words are degenerate, which is how the
    no-box path leaves them (see :attr:`Box.is_degenerate`).
    """

    if len(slot) < offset + CACHED_BOX_BYTES:
        return None
    box = Box(
        x0=_s16(slot, offset),
        x1=_s16(slot, offset + 2),
        y0=_s16(slot, offset + 4),
        y1=_s16(slot, offset + 6),
        z0=_s16(slot, offset + 8),
        z1=_s16(slot, offset + 10),
    )
    return None if box.is_degenerate else box
