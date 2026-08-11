import unittest

from sor_autoplay.attack_ranges import (
    MELEE_WEAPON_REACH_X,
    MIN_REACH_GAIN,
    AnimationSets,
    AttackRange,
    attack_ranges_for_object,
    attack_ranges_for_set,
    held_weapon_range,
)
from sor_autoplay.hitboxes import ShapeTables

SET_BASE = 0x1FC70  # garcia_animation_set, so ANIMATION_SET_FOR_TYPE resolves


def _shape_tables(records: dict[int, tuple[int, int, int, int, int]]) -> ShapeTables:
    """Shape table holding ``{box_id: (x0, width, lane_id, z0, height)}``.

    Lane id 0 is defined as -8..+8, the extent every ordinary enemy box in
    the real tables uses.
    """

    table = bytearray(5 * 256)
    for box_id, record in records.items():
        table[5 * box_id : 5 * box_id + 5] = bytes(b & 0xFF for b in record)
    return ShapeTables(
        object_shapes=bytes(table),
        player_shapes=bytes(table),
        lane_extents=bytes([0xF8, 0x10]) * 8,  # -8, +16 -> lane -8..+8
    )


def _animation_set(animations: list[list[tuple[int, int]]], *, mirror_odd: bool = True) -> bytes:
    """Build a set from ``[[(attack_id, body_id), ...], ...]`` per animation.

    Mirrors the real layout described in attack_ranges.py: a word offset
    table, then one animation record each (frame count, duration, word offset
    table), then the frame records pooled after them. ``mirror_odd`` appends a
    left-facing duplicate of every animation, the way the ROM stores them, so
    the extractor's even-only walk is actually exercised.
    """

    if mirror_odd:
        animations = [anim for anim in animations for _ in range(2)]

    header_bytes = 2 * len(animations)
    anim_records: list[bytes] = []
    frame_blob = bytearray()
    anim_offsets: list[int] = []

    # Lay the animation records out first so frame offsets can point past them.
    anim_size = [2 + 2 * len(anim) for anim in animations]
    cursor = header_bytes
    for size in anim_size:
        anim_offsets.append(cursor)
        cursor += size
    frame_base = cursor

    for anim, anim_offset in zip(animations, anim_offsets):
        table = bytearray()
        for attack_id, body_id in anim:
            record_at = frame_base + len(frame_blob)
            frame_blob += bytes([1, attack_id, body_id, 0, 0, 0, 0, 0])
            table += (record_at - anim_offset).to_bytes(2, "big")
        anim_records.append(bytes([len(anim), 4]) + bytes(table))

    header = b"".join(off.to_bytes(2, "big") for off in anim_offsets)
    return header + b"".join(anim_records) + bytes(frame_blob)


def _sets(block: bytes) -> AnimationSets:
    return AnimationSets(blocks={SET_BASE: block})


class AttackRangeValueTests(unittest.TestCase):
    def _whip(self) -> AttackRange:
        # Nora's real numbers (shape $22 of $242F8's animation 10).
        return AttackRange(
            shape_id=0x22,
            animation=10,
            forward_min=32,
            forward_max=80,
            lane_min=-12,
            lane_max=10,
            height_min=-44,
            height_max=-20,
        )

    def test_dead_zone_is_a_positive_minimum(self) -> None:
        self.assertTrue(self._whip().has_dead_zone)
        punch = AttackRange(
            shape_id=1,
            animation=0,
            forward_min=0,
            forward_max=40,
            lane_min=-8,
            lane_max=8,
            height_min=-50,
            height_max=-44,
        )
        self.assertFalse(punch.has_dead_zone)

    def test_covers_only_between_the_two_edges(self) -> None:
        whip = self._whip()
        self.assertTrue(whip.covers(50, 0))
        self.assertFalse(whip.covers(20, 0))  # inside the dead zone
        self.assertFalse(whip.covers(90, 0))  # past the tip
        self.assertFalse(whip.covers(50, 40))  # wrong lane

    def test_covers_nothing_behind_the_enemy(self) -> None:
        self.assertFalse(self._whip().covers(-50, 0))

    def test_projected_mirrors_with_facing(self) -> None:
        whip = self._whip()

        right = whip.projected(world_x=100, lane_y=60, world_z=0, facing_left=False)
        self.assertEqual((right.x0, right.x1), (132, 180))

        left = whip.projected(world_x=100, lane_y=60, world_z=0, facing_left=True)
        self.assertEqual((left.x0, left.x1), (20, 68))
        # Lane and height do not mirror.
        self.assertEqual((left.y0, left.y1), (48, 70))


class AttackRangeExtractionTests(unittest.TestCase):
    def test_extracts_a_reaching_box_and_skips_the_mirrored_twin(self) -> None:
        tables = _shape_tables({1: (0, 40, 0, -50, 6), 2: (-9, 18, 0, -60, 60)})
        block = _animation_set([[(1, 2)]])

        ranges = attack_ranges_for_set(_sets(block), tables, SET_BASE)

        self.assertEqual(len(ranges), 1)
        self.assertEqual((ranges[0].forward_min, ranges[0].forward_max), (0, 40))
        self.assertEqual(ranges[0].shape_id, 1)

    def test_skips_a_contact_box_that_does_not_out_reach_its_own_body(self) -> None:
        # Signal's idle animation is the real case: an attack box 11px out
        # against a 9px body box, presented so $AA22 reports interaction.
        tables = _shape_tables({61: (-11, 22, 0, -60, 60), 2: (-9, 18, 0, -60, 60)})
        block = _animation_set([[(61, 2)]])

        self.assertEqual(attack_ranges_for_set(_sets(block), tables, SET_BASE), ())

    def test_the_reach_gain_is_the_boundary(self) -> None:
        body = (-9, 18, 0, -60, 60)  # forward edge at +9
        tables = _shape_tables({1: (0, 9 + MIN_REACH_GAIN, 0, -50, 6), 2: body})
        self.assertEqual(len(attack_ranges_for_set(_sets(_animation_set([[(1, 2)]])), tables, SET_BASE)), 1)

        tables = _shape_tables({1: (0, 9 + MIN_REACH_GAIN - 1, 0, -50, 6), 2: body})
        self.assertEqual(attack_ranges_for_set(_sets(_animation_set([[(1, 2)]])), tables, SET_BASE), ())

    def test_one_range_per_shape_however_many_frames_use_it(self) -> None:
        tables = _shape_tables({1: (0, 40, 0, -50, 6), 2: (-9, 18, 0, -60, 60)})
        block = _animation_set([[(1, 2), (1, 2), (0, 2), (1, 2)]])

        self.assertEqual(len(attack_ranges_for_set(_sets(block), tables, SET_BASE)), 1)

    def test_ranges_are_ordered_by_reach(self) -> None:
        tables = _shape_tables(
            {
                1: (0, 40, 0, -50, 6),
                3: (24, 48, 0, -56, 16),
                2: (-9, 18, 0, -60, 60),
            }
        )
        block = _animation_set([[(1, 2)], [(3, 2)]])

        ranges = attack_ranges_for_set(_sets(block), tables, SET_BASE)

        self.assertEqual([r.forward_max for r in ranges], [40, 72])

    def test_a_frame_with_no_attack_box_contributes_nothing(self) -> None:
        tables = _shape_tables({2: (-9, 18, 0, -60, 60)})
        block = _animation_set([[(0, 2), (0, 2)]])

        self.assertEqual(attack_ranges_for_set(_sets(block), tables, SET_BASE), ())

    def test_unknown_set_base_is_empty_not_an_error(self) -> None:
        tables = _shape_tables({1: (0, 40, 0, -50, 6)})
        self.assertEqual(attack_ranges_for_set(_sets(b""), tables, 0xDEAD), ())


class HeldWeaponRangeTests(unittest.TestCase):
    def test_bat_and_pipe_add_their_measured_reach(self) -> None:
        for weapon_type in (0x0A, 0x0B):
            rng = held_weapon_range(weapon_type)
            self.assertIsNotNone(rng)
            self.assertEqual(rng.forward_max, MELEE_WEAPON_REACH_X)

    def test_unmeasured_weapons_return_nothing_rather_than_a_guess(self) -> None:
        for weapon_type in (0x00, 0x08, 0x09, 0x0C):
            self.assertIsNone(held_weapon_range(weapon_type))

    def test_an_armed_enemy_keeps_its_own_ranges_too(self) -> None:
        tables = _shape_tables({1: (0, 40, 0, -50, 6), 2: (-9, 18, 0, -60, 60)})
        sets = _sets(_animation_set([[(1, 2)]]))

        unarmed = attack_ranges_for_object(sets, tables, type_id=0x20)
        armed = attack_ranges_for_object(sets, tables, type_id=0x20, held_weapon_type=0x0A)

        self.assertEqual(len(unarmed), 1)
        self.assertEqual(len(armed), 2)
        self.assertEqual(max(r.forward_max for r in armed), 40)

    def test_a_type_with_no_animation_set_still_gains_its_weapon(self) -> None:
        tables = _shape_tables({})
        # Type $30 is Abadede: no labelled animation set, so nothing extracted.
        armed = attack_ranges_for_object(
            _sets(b""), tables, type_id=0x30, held_weapon_type=0x0B
        )

        self.assertEqual(len(armed), 1)
        self.assertEqual(armed[0].forward_max, MELEE_WEAPON_REACH_X)


if __name__ == "__main__":
    unittest.main()
