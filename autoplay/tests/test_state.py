import unittest
from unittest.mock import patch

from sor_autoplay.memory_map import (
    MAX_HEALTH,
    OBJ_CHARACTER_ID,
    OBJ_CONTINUE_CHOICE,
    OBJ_CONTINUE_UI_FLAGS,
    OBJ_HEALTH,
    OBJ_TYPE,
    OBJECT_SLOT_SIZE,
)
from sor_autoplay.state import snapshot_from_memory_blocks
from sor_autoplay.world_map import CAMERA_BYTES


def _put_u8(buf: bytearray, offset: int, value: int) -> None:
    buf[offset] = value & 0xFF


def _put_u16(buf: bytearray, offset: int, value: int) -> None:
    buf[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def _put_u32(buf: bytearray, offset: int, value: int) -> None:
    buf[offset : offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "big")


class StateSnapshotTests(unittest.TestCase):
    def test_ingame_two_player_snapshot(self) -> None:
        globals_block = bytearray(0x40)
        timer_block = bytearray(4)
        objects = bytearray(0x100)

        # game_state=$16 in-game, level 0, wave 1, player_mode both
        _put_u16(globals_block, 0x00, 0x0016)
        _put_u16(globals_block, 0x02, 0x0000)
        _put_u16(globals_block, 0x04, 0x0001)
        _put_u32(globals_block, 0x08, 0x00012345)  # score P1 BCD 012345
        _put_u32(globals_block, 0x10, 0x00000010)  # score P2 BCD 000010
        _put_u8(globals_block, 0x18, 0x03)  # both players
        _put_u16(globals_block, 0x1A, 0x0003)
        _put_u16(globals_block, 0x1C, 0x0002)
        _put_u8(globals_block, 0x1E, 0x00)  # Axel
        _put_u8(globals_block, 0x1F, 0x02)  # Blaze
        _put_u8(globals_block, 0x20, 0x03)  # lives P1
        _put_u8(globals_block, 0x21, 0x01)  # specials P1
        _put_u8(globals_block, 0x23, 0x02)  # lives P2
        _put_u8(globals_block, 0x24, 0x01)  # specials P2

        _put_u16(timer_block, 0, 0x0040)
        _put_u8(timer_block, 2, 0x40)

        # P1 active Axel full health
        _put_u8(objects, OBJ_TYPE, 0x01)
        _put_u16(objects, OBJ_HEALTH, MAX_HEALTH)
        _put_u8(objects, OBJ_CHARACTER_ID, 0x00)

        # P2 active Blaze half health
        p2 = OBJECT_SLOT_SIZE
        _put_u8(objects, p2 + OBJ_TYPE, 0x01)
        _put_u16(objects, p2 + OBJ_HEALTH, MAX_HEALTH // 2)
        _put_u8(objects, p2 + OBJ_CHARACTER_ID, 0x02)

        snap = snapshot_from_memory_blocks(
            globals_block=bytes(globals_block),
            timer_block=bytes(timer_block),
            objects_block=bytes(objects),
            stop_clock=0,
        )

        self.assertTrue(snap.connected)
        self.assertEqual(snap.game_mode, "In-game")
        self.assertEqual(snap.level_display, 1)
        self.assertEqual(snap.wave, 1)
        self.assertEqual(snap.time_left, 40)
        self.assertTrue(snap.timer_valid)
        self.assertEqual(snap.p1.character_name, "Axel")
        self.assertEqual(snap.p1.health_percent, 100.0)
        self.assertEqual(snap.p1.lives, 3)
        self.assertEqual(snap.p1.specials, 1)
        self.assertEqual(snap.p1.score, 12345)
        self.assertEqual(snap.p2.character_name, "Blaze")
        self.assertEqual(snap.p2.health_percent, 50.0)
        self.assertEqual(snap.p2.lives, 2)
        self.assertEqual(snap.p2.score, 10)

    def test_torn_health_read_clamps_to_max(self) -> None:
        """A mid-write/garbage health value above MAX_HEALTH but below the old
        `MAX_HEALTH * 2` no-op ceiling (e.g. 120) must still clamp to 80, not
        pass through unclamped into the raw `.health` field."""
        globals_block = bytearray(0x40)
        timer_block = bytearray(4)
        objects = bytearray(0x100)

        _put_u16(globals_block, 0x00, 0x0016)
        _put_u8(globals_block, 0x18, 0x01)  # P1 only
        _put_u8(objects, OBJ_TYPE, 0x01)
        _put_u16(objects, OBJ_HEALTH, MAX_HEALTH + 40)  # 120, garbage read
        _put_u8(objects, OBJ_CHARACTER_ID, 0x00)

        snap = snapshot_from_memory_blocks(
            globals_block=bytes(globals_block),
            timer_block=bytes(timer_block),
            objects_block=bytes(objects),
        )
        self.assertEqual(snap.p1.health, MAX_HEALTH)
        self.assertEqual(snap.p1.health_percent, 100.0)

    def test_one_player_menu_snapshot(self) -> None:
        globals_block = bytearray(0x40)
        timer_block = bytearray(4)
        objects = bytearray(0x100)

        _put_u16(globals_block, 0x00, 0x0012)  # mode menu
        _put_u8(globals_block, 0x18, 0x01)  # P1 only
        _put_u8(globals_block, 0x1E, 0x01)  # Adam selected
        _put_u8(globals_block, 0x20, 0x05)
        _put_u8(globals_block, 0x21, 0x00)

        snap = snapshot_from_memory_blocks(
            globals_block=bytes(globals_block),
            timer_block=bytes(timer_block),
            objects_block=bytes(objects),
        )
        self.assertEqual(snap.game_mode, "Mode menu")
        self.assertTrue(snap.p1.mode_active)
        self.assertFalse(snap.p2.mode_active)
        # Mode menu is outside the campaign resource window; character is blanked.
        self.assertEqual(snap.p1.character_name, "—")
        self.assertIsNone(snap.p1.health)
        self.assertFalse(snap.timer_valid)

    def test_continue_ui_fields_from_object(self) -> None:
        globals_block = bytearray(0x40)
        timer_block = bytearray(4)
        objects = bytearray(0x100)

        _put_u16(globals_block, 0x00, 0x0016)
        _put_u8(globals_block, 0x18, 0x00)  # mode bit cleared
        _put_u16(globals_block, 0x1A, 0x0002)
        _put_u8(globals_block, 0x1E, 0x00)
        _put_u8(globals_block, 0x20, 0x00)

        _put_u8(objects, OBJ_TYPE, 0x0F)
        _put_u8(objects, OBJ_CONTINUE_UI_FLAGS, 0x80)
        _put_u8(objects, OBJ_CONTINUE_CHOICE, 0x01)

        snap = snapshot_from_memory_blocks(
            globals_block=bytes(globals_block),
            timer_block=bytes(timer_block),
            objects_block=bytes(objects),
        )
        self.assertTrue(snap.p1.is_continue_ui)
        self.assertFalse(snap.p1.is_playable)
        self.assertTrue(snap.p1.name_entry_active)
        self.assertTrue(snap.p1.continue_selects_no)
        self.assertEqual(snap.p1.continues, 2)
        self.assertEqual(snap.raw["p1_name_entry"], 1)
        self.assertEqual(snap.raw["p1_continue_no"], 1)

    def test_character_select_keeps_selection(self) -> None:
        globals_block = bytearray(0x40)
        timer_block = bytearray(4)
        objects = bytearray(0x100)

        _put_u16(globals_block, 0x00, 0x0022)
        _put_u8(globals_block, 0x18, 0x01)
        _put_u8(globals_block, 0x1E, 0x01)  # Adam
        _put_u8(globals_block, 0x20, 0x03)
        _put_u8(globals_block, 0x21, 0x00)

        snap = snapshot_from_memory_blocks(
            globals_block=bytes(globals_block),
            timer_block=bytes(timer_block),
            objects_block=bytes(objects),
        )
        self.assertEqual(snap.game_mode, "Character select")
        self.assertEqual(snap.p1.character_name, "Adam")
        self.assertEqual(snap.p1.lives, 3)


class ElevatorStageHazardTests(unittest.TestCase):
    """Stage 7 (level_index 6) is an elevator: its moving platform is not
    represented by the class-0/2 collision map the same way ordinary terrain
    is, so both pit and barrier detection would read class-map noise instead
    of real hazards. Barrier solids were already skipped there; pits need
    the identical carve-out, or a phantom ``Pit`` token reaches the AI
    pipeline (``ai/observe.py`` builds one per ``snapshot.floor_holes``
    entry, unconditionally) and the HUD draws a hole that was never there.
    """

    def _ingame_blocks(self, *, level_index: int) -> tuple[bytes, bytes, bytes, bytes]:
        globals_block = bytearray(0x40)
        timer_block = bytearray(4)
        objects = bytearray(0x100)
        camera_block = bytearray(CAMERA_BYTES)

        _put_u16(globals_block, 0x00, 0x0016)  # in-game
        _put_u16(globals_block, 0x02, level_index)
        _put_u8(globals_block, 0x18, 0x01)  # P1 only
        _put_u8(objects, OBJ_TYPE, 0x01)
        _put_u16(objects, OBJ_HEALTH, MAX_HEALTH)
        _put_u8(objects, OBJ_CHARACTER_ID, 0x00)

        return bytes(globals_block), bytes(timer_block), bytes(objects), bytes(camera_block)

    def test_holes_and_barriers_skipped_on_the_elevator_stage(self) -> None:
        globals_block, timer_block, objects, camera_block = self._ingame_blocks(level_index=6)

        with patch("sor_autoplay.state.holes_for_level") as holes_mock, patch(
            "sor_autoplay.state.barriers_for_level"
        ) as barriers_mock:
            snap = snapshot_from_memory_blocks(
                globals_block=globals_block,
                timer_block=timer_block,
                objects_block=objects,
                camera_block=camera_block,
                collision_map=b"\x11" * 64,
                blockmap_stride=8,
            )

        holes_mock.assert_not_called()
        barriers_mock.assert_not_called()
        self.assertEqual(snap.floor_holes, ())
        self.assertEqual(snap.floor_barriers, ())

    def test_holes_and_barriers_computed_on_an_ordinary_stage(self) -> None:
        globals_block, timer_block, objects, camera_block = self._ingame_blocks(level_index=0)

        with patch("sor_autoplay.state.holes_for_level") as holes_mock, patch(
            "sor_autoplay.state.barriers_for_level"
        ) as barriers_mock:
            holes_mock.return_value = ("a-hole",)
            barriers_mock.return_value = ("a-barrier",)
            snap = snapshot_from_memory_blocks(
                globals_block=globals_block,
                timer_block=timer_block,
                objects_block=objects,
                camera_block=camera_block,
                collision_map=b"\x11" * 64,
                blockmap_stride=8,
            )

        holes_mock.assert_called_once()
        barriers_mock.assert_called_once()
        self.assertEqual(snap.floor_holes, ("a-hole",))
        self.assertEqual(snap.floor_barriers, ("a-barrier",))


if __name__ == "__main__":
    unittest.main()
