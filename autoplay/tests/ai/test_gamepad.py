import unittest
from unittest.mock import MagicMock, call

from sor_autoplay.ai.gamepad import NONE_MASK, SharedGamepadState, VirtualGamepad

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

    def test_press_targets_the_named_player_only(self) -> None:
        client = MagicMock()
        state = SharedGamepadState(client)

        state.press(2, C, frames=3)

        client.press_buttons.assert_called_once_with(player2=C, frames=3)

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
        client.press_buttons.assert_called_once_with(player1=A, frames=2)

    def test_invalid_player_index_is_rejected(self) -> None:
        client = MagicMock()
        state = SharedGamepadState(client)
        with self.assertRaises(ValueError):
            VirtualGamepad(state, player_index=0)


if __name__ == "__main__":
    unittest.main()
