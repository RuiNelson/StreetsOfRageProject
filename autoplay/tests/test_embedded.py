"""``sor_ai.embedded``: what the ``sor`` host runs, against a fake host."""

from __future__ import annotations

import unittest

from sor_ai import embedded
from sor_ai.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_ai.remote_input import (
    ACTION_JUMP,
    ACTION_PUNCH,
    STATUS_MAGIC,
    TAG_HOST_MODE,
    HEADER,
    RECORD,
    VERSION,
    unpack_ai_assist,
    unpack_input,
)

RAM_SIZE = 0x10000
_MD_B, _MD_C = 0x020, 0x040


class FakeHost:
    def __init__(self, frames=()) -> None:
        self.frames = list(frames)
        self.documents: list[bytes] = []
        self.lines: list[str] = []
        self.now = 0

    def stop_requested(self) -> bool:
        return not self.frames

    def wait_frame(self, timeout: float):
        return self.frames.pop(0)

    def current_frame(self) -> int:
        return self.now

    def read_memory(self, address: int, length: int) -> bytes:
        return bytes(length)

    def set_input(self, document: bytes) -> None:
        self.documents.append(document)

    def widescreen(self) -> bool:
        return False

    def log(self, text: str) -> None:
        self.lines.append(text)


def _p2(document: bytes):
    return unpack_input(document).players[2]


class InProcessClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = FakeHost()
        self.client = embedded.InProcessClient(self.host)

    def test_a_hold_speaks_only_for_p2_in_actions(self) -> None:
        self.client.six_button = True
        self.client.hold_buttons(player1=_MD_B, player2=_MD_C)
        players = unpack_input(self.host.documents[-1]).players
        self.assertEqual(list(players), [2])
        self.assertEqual(players[2].held, ACTION_JUMP)

    def test_a_queued_press_starts_next_frame_and_reports_its_release(self) -> None:
        self.host.now = 100
        self.assertEqual(self.client.queue_press_buttons(player=2, buttons=_MD_B, frames=4), 105)
        record = _p2(self.host.documents[-1])
        self.assertTrue(record.queue)
        self.assertEqual(record.schedule, ((ACTION_PUNCH, 4),))

    def test_a_press_behind_another_waits_for_it_and_a_released_frame(self) -> None:
        self.host.now = 100
        self.client.queue_press_buttons(player=2, buttons=_MD_B, frames=4)
        self.host.now = 102
        self.assertEqual(self.client.queue_press_buttons(player=2, buttons=_MD_B, frames=2), 108)

    def test_each_press_is_a_new_sequence_and_a_hold_keeps_it(self) -> None:
        self.client.queue_press_buttons(player=2, buttons=_MD_B)
        first = _p2(self.host.documents[-1]).seq
        self.client.hold_buttons(player2=_MD_C)
        self.assertEqual(_p2(self.host.documents[-1]).seq, first)
        self.client.queue_press_buttons(player=2, buttons=_MD_B)
        self.assertNotEqual(_p2(self.host.documents[-1]).seq, first)

    def test_the_other_seat_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.client.queue_press_buttons(player=1, buttons=_MD_B)

    def test_works_as_the_pads_client(self) -> None:
        pad = VirtualGamepad(SharedGamepadState(self.client), player_index=2)
        self.client.six_button = True
        self.assertTrue(pad.enhanced)
        self.host.now = 50
        pad.press(_MD_B, frames=4)
        self.assertTrue(pad.press_pending(52))
        self.assertFalse(pad.press_pending(55))


class RunTests(unittest.TestCase):
    def _run(self, *frames) -> FakeHost:
        host = FakeHost(frames)
        embedded.run(host)
        return host

    def test_blank_ram_plays_nothing_and_fails_nothing(self) -> None:
        ram = bytes(RAM_SIZE)
        host = self._run((2, ram, False), (4, ram, False))
        self.assertIn("2 ticks", host.lines[-1])
        self.assertIn("0 failed", host.lines[-1])

    def test_skipped_frames_are_counted(self) -> None:
        ram = bytes(RAM_SIZE)
        host = self._run((2, ram, False), (10, ram, False))
        self.assertIn("3 skipped", host.lines[-1])

    def test_a_restart_clears_what_the_game_was_told(self) -> None:
        ram = bytes(RAM_SIZE)
        host = self._run((100, ram, False), (2, ram, False))
        record = _p2(host.documents[-1])
        self.assertEqual((record.held, record.schedule), (0, ()))

    def test_a_failing_tick_is_reported_once_and_the_game_goes_on(self) -> None:
        host = self._run((2, b"short", False), (4, b"short", False))
        self.assertIn("2 failed", host.lines[-1])


class HostModeTests(unittest.TestCase):
    def _document(self, flags: int) -> bytes:
        return (
            HEADER.pack(STATUS_MAGIC, VERSION, 1, 0)
            + RECORD.pack(TAG_HOST_MODE, 1)
            + bytes([flags])
        )

    def test_the_bit_is_read(self) -> None:
        self.assertTrue(unpack_ai_assist(self._document(1)))
        self.assertFalse(unpack_ai_assist(self._document(0)))

    def test_an_older_host_says_no(self) -> None:
        self.assertFalse(unpack_ai_assist(HEADER.pack(STATUS_MAGIC, VERSION, 0, 0)))


if __name__ == "__main__":
    unittest.main()
