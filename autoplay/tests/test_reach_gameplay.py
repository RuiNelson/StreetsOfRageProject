import unittest

from sor_autoplay import memory_map as mm
from sor_autoplay.reach_gameplay import (
    A_MASK,
    CHARACTER_CONFIRM_SETTLE_VSYNCS,
    GAMEPLAY_UPDATE,
    LEFT_MASK,
    RIGHT_MASK,
    START_MASK,
    TAP_FRAMES,
    ReachGameplayError,
    ReachGameplayResult,
    reach_gameplay,
)


class FakeClient:
    """Scripted client: every wait 'succeeds' immediately; final reads come
    from a fixed address->value map, so tests can assert both the exact
    button sequence sent and the validation branches."""

    def __init__(self, *, final_values: dict[int, int]) -> None:
        self.final_values = final_values
        self.press_calls: list[int] = []
        self.press_frames: list[int] = []
        self.vsync_waits: list[int] = []
        self.restart_called = False
        self.ping_called = False

    def ping(self) -> None:
        self.ping_called = True

    def restart_game(self, *, timeout_ms: int) -> None:
        self.restart_called = True

    def press_buttons(self, *, player1: int = 0, player2: int = 0, frames: int = 1, timeout_ms=None) -> None:
        self.press_calls.append(player1)
        self.press_frames.append(frames)

    def wait_vsync(self, count: int = 1, *, timeout_ms=None) -> None:
        self.vsync_waits.append(count)

    def wait_memory_equals(self, address, expected, *, width=1, mask=None, timeout_ms=1000):
        return expected

    def read_value(self, address: int, width: int = 1) -> int:
        return self.final_values[address]


def _valid_final_values(*, character_id: int) -> dict[int, int]:
    return {
        mm.ADDR_P1_OBJECT + mm.OBJ_CHARACTER_ID: character_id,
        mm.ADDR_P1_CHARACTER_ID: character_id,
        mm.ADDR_P1_OBJECT + mm.OBJ_HEALTH: mm.MAX_HEALTH,
        mm.ADDR_P1_OBJECT + mm.OBJ_TYPE: mm.OBJ_TYPE_ACTIVE_PLAYER,
        mm.ADDR_GAME_STATE: GAMEPLAY_UPDATE,
        mm.ADDR_SOUND_MUSIC_VOICE_BANK: 0x1234,
    }


class ReachGameplayHappyPathTests(unittest.TestCase):
    def test_axel_sends_start_start_a_right_a(self) -> None:
        client = FakeClient(final_values=_valid_final_values(character_id=0))

        result = reach_gameplay(client, "axel")

        self.assertTrue(client.restart_called)
        self.assertTrue(client.ping_called)
        self.assertEqual(
            client.press_calls, [START_MASK, START_MASK, A_MASK, RIGHT_MASK, A_MASK]
        )
        self.assertEqual(
            result,
            ReachGameplayResult(
                character="axel",
                character_id=0,
                game_state=GAMEPLAY_UPDATE,
                health=mm.MAX_HEALTH,
                player_object_type=mm.OBJ_TYPE_ACTIVE_PLAYER,
            ),
        )

    def test_adam_has_no_direction_slot_default_needs_no_tap(self) -> None:
        client = FakeClient(final_values=_valid_final_values(character_id=1))

        reach_gameplay(client, "adam")

        self.assertEqual(client.press_calls, [START_MASK, START_MASK, A_MASK, A_MASK])

    def test_blaze_sends_left_direction_tap(self) -> None:
        client = FakeClient(final_values=_valid_final_values(character_id=2))

        reach_gameplay(client, "blaze")

        self.assertEqual(
            client.press_calls, [START_MASK, START_MASK, A_MASK, LEFT_MASK, A_MASK]
        )

    def test_character_name_is_case_insensitive(self) -> None:
        client = FakeClient(final_values=_valid_final_values(character_id=0))
        reach_gameplay(client, "AXEL")  # must not raise

    def test_taps_hold_more_than_one_frame(self) -> None:
        """Regression: a 1-frame press raced the ROM's per-frame press-edge
        sampling under real (non-lockstep) timing and occasionally missed
        the character-select confirm entirely."""

        client = FakeClient(final_values=_valid_final_values(character_id=0))

        reach_gameplay(client, "axel")

        self.assertTrue(all(frames == TAP_FRAMES for frames in client.press_frames))
        self.assertGreater(TAP_FRAMES, 1)

    def test_settles_before_the_character_select_confirm(self) -> None:
        client = FakeClient(final_values=_valid_final_values(character_id=0))

        reach_gameplay(client, "axel")

        # Last press overall is the character-select A confirm; the vsync
        # wait immediately preceding its press+settle pair is the multi-frame
        # settle (index -3: ..., settle, tap-A's own post-press wait(1), and
        # nothing waits after that tap in this run).
        self.assertEqual(client.press_calls[-1], A_MASK)
        self.assertEqual(client.vsync_waits[-3], CHARACTER_CONFIRM_SETTLE_VSYNCS)


class ReachGameplayValidationTests(unittest.TestCase):
    def test_unknown_character_raises_without_touching_the_client(self) -> None:
        client = FakeClient(final_values={})
        with self.assertRaises(ValueError):
            reach_gameplay(client, "garcia")
        self.assertFalse(client.restart_called)

    def test_left_gameplay_state_raises(self) -> None:
        values = _valid_final_values(character_id=0)
        values[mm.ADDR_GAME_STATE] = 0x0018  # round-clear, not gameplay
        client = FakeClient(final_values=values)

        with self.assertRaises(ReachGameplayError):
            reach_gameplay(client, "axel")

    def test_character_id_mismatch_raises(self) -> None:
        values = _valid_final_values(character_id=0)
        values[mm.ADDR_P1_CHARACTER_ID] = 2  # persisted as blaze, not axel
        client = FakeClient(final_values=values)

        with self.assertRaises(ReachGameplayError):
            reach_gameplay(client, "axel")

    def test_uninitialized_player_object_raises(self) -> None:
        values = _valid_final_values(character_id=0)
        values[mm.ADDR_P1_OBJECT + mm.OBJ_HEALTH] = 0x10  # not full health yet
        client = FakeClient(final_values=values)

        with self.assertRaises(ReachGameplayError):
            reach_gameplay(client, "axel")

    def test_silent_music_bank_raises(self) -> None:
        values = _valid_final_values(character_id=0)
        values[mm.ADDR_SOUND_MUSIC_VOICE_BANK] = 0
        client = FakeClient(final_values=values)

        with self.assertRaises(ReachGameplayError):
            reach_gameplay(client, "axel")


if __name__ == "__main__":
    unittest.main()
