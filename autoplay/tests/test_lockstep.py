"""Lockstep mode (``--lockstep``): capture, step grouping, RAM snapshots.

The AI-driven clock: while an AI is engaged the host is frozen and each
pipeline tick is replayed through ``step_input`` for exactly
``LOCKSTEP_FRAMES_PER_TICK`` frames, instead of wall-clock polling. These
tests pin the plumbing -- what the tick commanded is what gets stepped --
without needing a live host.
"""

import unittest

from sor_autoplay.app import (
    LOCKSTEP_FRAMES_PER_TICK,
    ObserverApp,
    _group_step_masks,
    _LockstepCapture,
    build_parser,
)
from sor_autoplay.state import WORK_RAM_SIZE, snapshot_from_work_ram


class LockstepCaptureTests(unittest.TestCase):
    def test_hold_is_replayed_until_changed(self):
        capture = _LockstepCapture()
        capture.hold_buttons(player1=0x0008, player2=0)
        self.assertEqual(capture.next_frame_masks(), (0x0008, 0))
        self.assertEqual(capture.next_frame_masks(), (0x0008, 0))

    def test_press_plays_its_frames_then_falls_back_to_hold(self):
        capture = _LockstepCapture()
        capture.hold_buttons(player1=0x0008, player2=0)
        capture.press_buttons(player1=0x0010, player2=0, frames=2)
        self.assertEqual(capture.next_frame_masks(), (0x0010, 0))
        self.assertEqual(capture.next_frame_masks(), (0x0010, 0))
        self.assertEqual(capture.next_frame_masks(), (0x0008, 0))

    def test_players_drain_independently(self):
        capture = _LockstepCapture()
        capture.hold_buttons(player1=0x0008, player2=0x0004)
        capture.press_buttons(player1=0x0010, player2=0x0004, frames=1)
        # P1's edge plays once; P2's payload is its own hold, so it reads
        # unchanged throughout.
        self.assertEqual(capture.next_frame_masks(), (0x0010, 0x0004))
        self.assertEqual(capture.next_frame_masks(), (0x0008, 0x0004))

    def test_press_pending_tracks_frames_left(self):
        capture = _LockstepCapture()
        self.assertFalse(capture.press_pending(1))
        # A press carries the full two-player payload (SharedGamepadState.press
        # folds the other player's hold into the same call), so both sides
        # count down together.
        capture.press_buttons(player1=0x0010, player2=0, frames=1)
        self.assertTrue(capture.press_pending(1))
        self.assertTrue(capture.press_pending(2))
        capture.next_frame_masks()
        self.assertFalse(capture.press_pending(1))
        self.assertFalse(capture.press_pending(2))

    def test_reset_clears_holds_and_presses(self):
        capture = _LockstepCapture()
        capture.hold_buttons(player1=0x0008, player2=0x0004)
        capture.press_buttons(player1=0x0010, player2=0, frames=4)
        capture.reset()
        self.assertEqual(capture.next_frame_masks(), (0, 0))
        self.assertFalse(capture.press_pending(1))


class GroupStepMasksTests(unittest.TestCase):
    def test_stable_tick_is_one_step_call(self):
        self.assertEqual(
            _group_step_masks([(0x0008, 0), (0x0008, 0)]),
            [(0x0008, 0, 2, 2)],
        )

    def test_press_edge_mid_tick_splits_into_two_calls(self):
        self.assertEqual(
            _group_step_masks([(0x0010, 0), (0x0008, 0)]),
            [(0x0010, 0, 1, 1), (0x0008, 0, 1, 1)],
        )

    def test_released_frames_step_as_released(self):
        self.assertEqual(
            _group_step_masks([(0, 0), (0, 0)]),
            [(0, 0, 0, 2)],
        )

    def test_every_group_is_a_valid_step_input_call(self):
        for masks in (
            [(0x0008, 0), (0x0008, 0)],
            [(0x0010, 0x0020), (0, 0)],
            [(0, 0), (0x0008, 0)],
        ):
            groups = _group_step_masks(masks)
            covered = sum(total for _, _, _, total in groups)
            self.assertEqual(covered, len(masks))
            for _, _, held, total in groups:
                self.assertLessEqual(held, total)


class SnapshotFromWorkRamTests(unittest.TestCase):
    def test_zeroed_ram_builds_a_connected_snapshot(self):
        snapshot = snapshot_from_work_ram(
            bytes(WORK_RAM_SIZE), uptime_frames=42
        )
        self.assertTrue(snapshot.connected)
        self.assertEqual(snapshot.raw["uptime_frames"], 42)
        self.assertEqual(len(snapshot.players), 2)

    def test_matches_the_tick_cadence(self):
        self.assertEqual(LOCKSTEP_FRAMES_PER_TICK, 2)

    def test_truncated_ram_raises(self):
        with self.assertRaises(ValueError):
            snapshot_from_work_ram(b"")


class LockstepWiringTests(unittest.TestCase):
    def test_flag_parses(self):
        args = build_parser().parse_args(["--lockstep"])
        self.assertTrue(args.lockstep)
        args = build_parser().parse_args([])
        self.assertFalse(args.lockstep)

    def test_lockstep_app_binds_the_capture_not_the_live_latch(self):
        app = ObserverApp(host="127.0.0.1", port=6767, lockstep=True)
        try:
            self.assertIs(app._gamepad_state._client, app._capture)
        finally:
            app.stop()

    def test_realtime_app_keeps_the_live_proxy(self):
        app = ObserverApp(host="127.0.0.1", port=6969)
        try:
            self.assertIsNot(app._gamepad_state._client, app._capture)
        finally:
            app.stop()

    def test_start_poller_picks_the_loop(self):
        seen = []

        class FakeThread:
            def __init__(self, target, name, daemon):
                seen.append(target)

            def start(self):
                pass

        import threading

        real_thread = threading.Thread
        threading.Thread = FakeThread
        try:
            app = ObserverApp(host="127.0.0.1", port=6767, lockstep=True)
            try:
                app.start_poller()
                self.assertEqual(seen, [app._lockstep_loop])
            finally:
                app.stop()
            seen.clear()
            app = ObserverApp(host="127.0.0.1", port=6969)
            try:
                app.start_poller()
                self.assertEqual(seen, [app._poll_loop])
            finally:
                app.stop()
        finally:
            threading.Thread = real_thread


if __name__ == "__main__":
    unittest.main()
