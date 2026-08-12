import unittest
from unittest.mock import MagicMock, call

from sor_autoplay.ai.gamepad import AXIS_RAMP_TICKS, NONE_MASK, SharedGamepadState, VirtualGamepad

RIGHT = 0x0008
LEFT = 0x0004
A = 0x0010
C = 0x0040


class SharedGamepadStateTests(unittest.TestCase):
    def test_hold_sends_both_masks_together(self) -> None:
        client = MagicMock()
        state = SharedGamepadState(client)

        state.hold(1, RIGHT)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=NONE_MASK)

    def test_hold_for_one_player_preserves_the_other_players_mask(self) -> None:
        client = MagicMock()
        state = SharedGamepadState(client)

        state.hold(1, RIGHT)
        client.hold_buttons.reset_mock()
        state.hold(2, LEFT)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=LEFT)

    def test_hold_is_a_noop_when_the_mask_is_unchanged(self) -> None:
        client = MagicMock()
        state = SharedGamepadState(client)

        state.hold(1, RIGHT)
        client.hold_buttons.reset_mock()
        state.hold(1, RIGHT)

        client.hold_buttons.assert_not_called()

    def test_release_holds_none_for_that_player_only(self) -> None:
        client = MagicMock()
        state = SharedGamepadState(client)
        state.hold(1, RIGHT)
        state.hold(2, LEFT)
        client.hold_buttons.reset_mock()

        state.release(1)

        client.hold_buttons.assert_called_once_with(player1=NONE_MASK, player2=LEFT)

    def test_press_folds_in_the_other_players_current_hold(self) -> None:
        """Regression: PRESS_BUTTONS applies *both* players' masks in one
        payload (RemoteAccess::pressButtons), so a call naming only the
        acting player would silently zero the other player's hold for the
        press's duration."""

        client = MagicMock()
        state = SharedGamepadState(client)
        state.hold(1, RIGHT)
        client.press_buttons.reset_mock()

        state.press(2, C, frames=3)

        client.press_buttons.assert_called_once_with(player1=RIGHT, player2=C, frames=3)

    def test_press_rearms_both_holds_after_the_server_clears_them(self) -> None:
        """Regression: RemoteAccess::pressButtons's ReleaseGuard clears both
        players' remote state to none once ``frames`` completes, regardless
        of which player pressed. Without an explicit re-arm, the next
        same-mask hold() would see an unchanged cache and skip re-sending
        (hold()'s no-op short-circuit), silently freezing that player even
        though the server no longer holds anything."""

        client = MagicMock()
        state = SharedGamepadState(client)
        state.hold(1, RIGHT)
        state.hold(2, LEFT)
        client.hold_buttons.reset_mock()

        state.press(1, C, frames=2)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=LEFT)

    def test_hold_after_press_is_a_noop_because_press_already_rearmed_it(self) -> None:
        """End-to-end version of the freeze bug: walk right, punch, then try
        to keep walking right. Before the fix, the server's latch was
        cleared by the press but the cache still said RIGHT, so a later
        same-mask hold() would wrongly no-op against a server that actually
        held nothing. The fix moves the re-arm into press() itself, so the
        server is already back in sync by the time press() returns and this
        later hold() is a *correct* no-op, not a dropped command."""

        client = MagicMock()
        state = SharedGamepadState(client)
        state.hold(1, RIGHT)

        state.press(1, A, frames=2)
        client.hold_buttons.reset_mock()
        state.hold(1, RIGHT)

        client.hold_buttons.assert_not_called()
        self.assertEqual(state.held(1), RIGHT)

    def test_invalid_player_index_is_rejected(self) -> None:
        client = MagicMock()
        state = SharedGamepadState(client)
        with self.assertRaises(ValueError):
            state.hold(3, RIGHT)

    def test_reset_resyncs_cache_without_sending_a_command(self) -> None:
        client = MagicMock()
        state = SharedGamepadState(client)
        state.hold(1, RIGHT)
        client.hold_buttons.reset_mock()

        state.reset()

        client.hold_buttons.assert_not_called()
        self.assertEqual(state.held(1), NONE_MASK)

    def test_hold_after_reset_resends_the_same_looking_mask(self) -> None:
        """A reconnect drops the remote's own latch to none even though our
        cache still remembers the pre-reconnect mask; reset() must make the
        next identical hold() actually re-send instead of no-op'ing."""

        client = MagicMock()
        state = SharedGamepadState(client)
        state.hold(1, RIGHT)
        state.reset()
        client.hold_buttons.reset_mock()

        state.hold(1, RIGHT)

        client.hold_buttons.assert_called_once_with(player1=RIGHT, player2=NONE_MASK)


class VirtualGamepadTests(unittest.TestCase):
    def test_two_players_share_one_link_without_clobbering_each_other(self) -> None:
        """Regression: HOLD_BUTTONS latches both masks per call, so two
        independent per-player callers must route through one shared state
        or the second call silently zeroes the first player's hold."""

        client = MagicMock()
        state = SharedGamepadState(client)
        p1 = VirtualGamepad(state, player_index=1)
        p2 = VirtualGamepad(state, player_index=2)

        p1.hold(RIGHT)
        p2.hold(LEFT)

        self.assertEqual(p1.held, RIGHT)
        self.assertEqual(p2.held, LEFT)
        client.hold_buttons.assert_has_calls(
            [
                call(player1=RIGHT, player2=NONE_MASK),
                call(player1=RIGHT, player2=LEFT),
            ]
        )

    def test_press_does_not_change_the_held_mask(self) -> None:
        client = MagicMock()
        state = SharedGamepadState(client)
        pad = VirtualGamepad(state, player_index=1)
        pad.hold(RIGHT)

        pad.press(A, frames=2)

        self.assertEqual(pad.held, RIGHT)
        client.press_buttons.assert_called_once_with(player1=A, player2=NONE_MASK, frames=2)

    def test_invalid_player_index_is_rejected(self) -> None:
        client = MagicMock()
        state = SharedGamepadState(client)
        with self.assertRaises(ValueError):
            VirtualGamepad(state, player_index=0)


class VirtualGamepadSteerXTests(unittest.TestCase):
    """The virtual left/right axis: a per-tick direction request only turns
    into an actual reported side after AXIS_RAMP_TICKS consecutive ticks
    asking for it, which is what stops a single flipped tick's decision from
    reaching the controller as a flipped button."""

    def _pad(self) -> VirtualGamepad:
        return VirtualGamepad(SharedGamepadState(MagicMock()), player_index=1)

    def test_center_reports_neither_side(self) -> None:
        pad = self._pad()

        self.assertEqual(pad.steer_x(0), 0)

    def test_a_single_tick_of_a_direction_does_not_reach_the_edge(self) -> None:
        pad = self._pad()

        self.assertEqual(pad.steer_x(1), 0)

    def test_sustained_direction_reaches_the_edge_after_ramp_ticks(self) -> None:
        pad = self._pad()

        results = [pad.steer_x(1) for _ in range(AXIS_RAMP_TICKS)]

        self.assertEqual(results, [0] * (AXIS_RAMP_TICKS - 1) + [1])

    def test_sustained_left_reaches_the_opposite_edge(self) -> None:
        pad = self._pad()

        results = [pad.steer_x(-1) for _ in range(AXIS_RAMP_TICKS)]

        self.assertEqual(results, [0] * (AXIS_RAMP_TICKS - 1) + [-1])

    def test_a_single_contrary_tick_only_pulls_one_step_back(self) -> None:
        # At the edge after a sustained hold, one tick asking for the
        # opposite side immediately drops the report to "neither" (it no
        # longer clears the edge threshold) but the axis itself only moved
        # one step, not all the way to center.
        pad = self._pad()
        for _ in range(AXIS_RAMP_TICKS):
            pad.steer_x(1)

        self.assertEqual(pad.steer_x(-1), 0)
        # Confirm it is one step short of the edge, not reset: one more
        # tick of the same direction reaches the edge, not two more.
        self.assertEqual(pad.steer_x(1), 1)

    def test_reversing_from_one_edge_to_the_other_takes_the_full_traverse(self) -> None:
        # Center-to-edge is AXIS_RAMP_TICKS ticks, so edge-to-edge (through
        # center) is 2x that -- the axis must actually cross zero, not jump.
        pad = self._pad()
        for _ in range(AXIS_RAMP_TICKS):
            pad.steer_x(1)

        results = [pad.steer_x(-1) for _ in range(2 * AXIS_RAMP_TICKS)]

        self.assertEqual(results, [0] * (2 * AXIS_RAMP_TICKS - 1) + [-1])

    def test_releasing_the_direction_falls_back_toward_center(self) -> None:
        pad = self._pad()
        for _ in range(AXIS_RAMP_TICKS):
            pad.steer_x(1)

        # Every neutral tick pulls one step back; reaching center again
        # takes as many ticks as it took to leave it.
        results = [pad.steer_x(0) for _ in range(AXIS_RAMP_TICKS)]

        self.assertEqual(results, [0] * AXIS_RAMP_TICKS)
        self.assertEqual(pad.steer_x(0), 0)

    def test_release_resets_the_axis_immediately(self) -> None:
        pad = self._pad()
        for _ in range(AXIS_RAMP_TICKS):
            pad.steer_x(1)

        pad.release()

        # From a hard reset, a fresh sustained direction needs the full
        # AXIS_RAMP_TICKS again -- confirming release() didn't just leave it
        # one step short of the edge the way a single neutral tick would.
        results = [pad.steer_x(1) for _ in range(AXIS_RAMP_TICKS - 1)]
        self.assertEqual(results, [0] * (AXIS_RAMP_TICKS - 1))


if __name__ == "__main__":
    unittest.main()
