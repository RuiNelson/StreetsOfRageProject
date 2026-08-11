import unittest
from unittest.mock import MagicMock

from sor_autoplay.hitboxes import (
    CACHED_BOX_BYTES,
    LANE_EXTENT_COUNT,
    OBJ_ATTACK_BOX_ID,
    OBJ_BODY_BOX_ID,
    OBJ_CACHED_ATTACK_BOX,
    OBJECT_SHAPE_COUNT,
    ROM_LANE_EXTENT_TABLE,
    ROM_OBJECT_SHAPE_TABLE,
    ROM_PLAYER_SHAPE_TABLE,
    Box,
    ShapeTables,
    build_box,
    cached_box,
    object_boxes,
    uses_player_shape_table,
)


def _tables(
    *,
    object_records: dict[int, tuple[int, int, int, int, int]] | None = None,
    player_records: dict[int, tuple[int, int, int, int, int]] | None = None,
    lane_records: dict[int, tuple[int, int]] | None = None,
) -> ShapeTables:
    def shapes(records) -> bytes:
        table = bytearray(OBJECT_SHAPE_COUNT * 5)
        for box_id, record in (records or {}).items():
            table[box_id * 5 : box_id * 5 + 5] = bytes(b & 0xFF for b in record)
        return bytes(table)

    lanes = bytearray(LANE_EXTENT_COUNT * 2)
    for lane_id, record in (lane_records or {}).items():
        lanes[lane_id * 2 : lane_id * 2 + 2] = bytes(b & 0xFF for b in record)

    return ShapeTables(
        object_shapes=shapes(object_records),
        player_shapes=shapes(player_records),
        lane_extents=bytes(lanes),
    )


class TableGeometryTests(unittest.TestCase):
    """The three tables sit back to back in ROM, which is what fixes two of
    the three record counts."""

    def test_object_table_spans_up_to_the_lane_table(self) -> None:
        self.assertEqual(
            ROM_OBJECT_SHAPE_TABLE + OBJECT_SHAPE_COUNT * 5, ROM_LANE_EXTENT_TABLE
        )

    def test_lane_table_spans_up_to_the_player_table(self) -> None:
        self.assertEqual(
            ROM_LANE_EXTENT_TABLE + LANE_EXTENT_COUNT * 2, ROM_PLAYER_SHAPE_TABLE
        )


class BuildBoxTests(unittest.TestCase):
    def test_builds_every_edge_from_the_object_origin(self) -> None:
        # $AB88: each axis is origin + s8(first byte), then + s8(second byte).
        # The lane pair comes from its own table, indexed by record[2].
        tables = _tables(
            object_records={1: (8, 20, 3, -40, 24)},
            lane_records={3: (-6, 12)},
        )

        box = build_box(tables, box_id=1, world_x=100, lane_y=60, world_z=200)

        self.assertEqual(
            box, Box(x0=108, x1=128, y0=54, y1=66, z0=160, z1=184)
        )

    def test_sign_extends_the_second_byte_too(self) -> None:
        # $AB88 runs ext.w on both bytes. weapons-range-and-damage.md
        # describes the second as an unsigned width, but the ROM does not
        # treat it that way -- a record with the high bit set builds an
        # inverted (degenerate) box rather than a 200px-wide one.
        tables = _tables(object_records={1: (0, 0xC0, 0, 0, 0)}, lane_records={0: (0, 8)})

        box = build_box(tables, box_id=1, world_x=100, lane_y=0, world_z=0)

        self.assertEqual(box.x1, 100 - 64)
        self.assertTrue(box.is_degenerate)

    def test_box_id_zero_means_no_box(self) -> None:
        # $AAA0 tests the id and skips the overlap check entirely.
        tables = _tables(object_records={1: (0, 20, 0, 0, 8)}, lane_records={0: (0, 8)})

        self.assertIsNone(build_box(tables, box_id=0, world_x=0, lane_y=0, world_z=0))

    def test_out_of_range_box_id_does_not_raise(self) -> None:
        tables = _tables()

        self.assertIsNone(
            build_box(tables, box_id=OBJECT_SHAPE_COUNT + 5, world_x=0, lane_y=0, world_z=0)
        )

    def test_selects_the_table_by_flag(self) -> None:
        tables = _tables(
            object_records={1: (0, 10, 0, 0, 1)},
            player_records={1: (0, 99, 0, 0, 1)},
            lane_records={0: (0, 8)},
        )

        from_object = build_box(tables, box_id=1, world_x=0, lane_y=0, world_z=0)
        from_player = build_box(
            tables, box_id=1, world_x=0, lane_y=0, world_z=0, player_table=True
        )

        self.assertEqual(from_object.x1, 10)
        self.assertEqual(from_player.x1, 99)


class PlayerShapeTableTypeTests(unittest.TestCase):
    def test_onihime_yasha_borrows_the_player_table(self) -> None:
        # $AB24 special-cases type $58 and only type $58.
        self.assertTrue(uses_player_shape_table(0x58))
        self.assertFalse(uses_player_shape_table(0x20))
        self.assertFalse(uses_player_shape_table(0x55))


class ObjectBoxesTests(unittest.TestCase):
    def test_reads_attack_and_body_ids_from_the_slot(self) -> None:
        tables = _tables(
            object_records={4: (0, 30, 0, 0, 8), 7: (0, 13, 0, 0, 8)},
            lane_records={0: (-8, 16)},
        )
        slot = bytearray(0x80)
        slot[OBJ_ATTACK_BOX_ID] = 4
        slot[OBJ_BODY_BOX_ID] = 7

        attack, body = object_boxes(
            tables, bytes(slot), type_id=0x20, world_x=100, lane_y=50, world_z=0
        )

        self.assertEqual(attack.x1 - attack.x0, 30)
        self.assertEqual(body.x1 - body.x0, 13)

    def test_no_attack_box_on_a_non_hitting_frame(self) -> None:
        tables = _tables(object_records={7: (0, 13, 0, 0, 8)}, lane_records={0: (-8, 16)})
        slot = bytearray(0x80)
        slot[OBJ_ATTACK_BOX_ID] = 0  # idle frame
        slot[OBJ_BODY_BOX_ID] = 7

        attack, body = object_boxes(
            tables, bytes(slot), type_id=0x20, world_x=100, lane_y=50, world_z=0
        )

        self.assertIsNone(attack)
        self.assertIsNotNone(body)


class CachedBoxTests(unittest.TestCase):
    """Players -- and only players -- cache their boxes at +$64/+$70."""

    def test_reads_six_absolute_words(self) -> None:
        slot = bytearray(0x80)
        words = (300, 340, 50, 66, -40, -8)
        for i, value in enumerate(words):
            slot[OBJ_CACHED_ATTACK_BOX + i * 2 : OBJ_CACHED_ATTACK_BOX + i * 2 + 2] = (
                int(value).to_bytes(2, "big", signed=True)
            )

        box = cached_box(bytes(slot), OBJ_CACHED_ATTACK_BOX)

        self.assertEqual(box, Box(x0=300, x1=340, y0=50, y1=66, z0=-40, z1=-8))

    def test_degenerate_fill_reads_as_no_box(self) -> None:
        # $4140's no-box path memfills the 12 bytes with a constant, which
        # collapses every axis to zero width.
        for fill in (b"\x00" * CACHED_BOX_BYTES, b"\x00\x10" * 6):
            with self.subTest(fill=fill):
                slot = bytearray(0x80)
                slot[OBJ_CACHED_ATTACK_BOX : OBJ_CACHED_ATTACK_BOX + CACHED_BOX_BYTES] = fill

                self.assertIsNone(cached_box(bytes(slot), OBJ_CACHED_ATTACK_BOX))


class BoxOverlapTests(unittest.TestCase):
    def test_overlap_requires_all_three_axes(self) -> None:
        attack = Box(x0=100, x1=140, y0=50, y1=66, z0=-40, z1=-8)
        same_lane = Box(x0=130, x1=143, y0=55, y1=71, z0=-40, z1=-8)
        other_lane = Box(x0=130, x1=143, y0=90, y1=106, z0=-40, z1=-8)
        overhead = Box(x0=130, x1=143, y0=55, y1=71, z0=-90, z1=-60)

        self.assertTrue(attack.overlaps(same_lane))
        self.assertFalse(attack.overlaps(other_lane))
        self.assertFalse(attack.overlaps(overhead))


class ShapeTablesReadTests(unittest.TestCase):
    def test_reads_each_table_from_its_rom_address_once(self) -> None:
        client = MagicMock()
        client.read_memory.side_effect = lambda address, length: bytes(length)

        ShapeTables.read(client)

        addresses = [call.args[0] for call in client.read_memory.call_args_list]
        self.assertEqual(
            sorted(addresses),
            sorted([ROM_OBJECT_SHAPE_TABLE, ROM_PLAYER_SHAPE_TABLE, ROM_LANE_EXTENT_TABLE]),
        )
