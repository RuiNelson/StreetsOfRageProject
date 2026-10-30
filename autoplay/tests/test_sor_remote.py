"""``sor_remote``: the input document, the status, and SoRClient's gamepad API."""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "MegaDriveEnvironment" / "python" / "src"))

from megadrive_remote._protocol import Command  # noqa: E402

from sor_autoplay import sor_remote as sr  # noqa: E402

A, B, C, START, X, Y, Z = 0x010, 0x020, 0x040, 0x080, 0x100, 0x200, 0x400
UP, LEFT, RIGHT = 0x001, 0x004, 0x008


def _status(*players: tuple[int, int, int, int]) -> bytes:
    records = b"".join(
        struct.pack(">HH", sr.TAG_PLAYER_STATUS, sr.PLAYER_STATUS.size) + sr.PLAYER_STATUS.pack(*player)
        for player in players
    )
    return sr.HEADER.pack(sr.STATUS_MAGIC, sr.VERSION, len(players), 0) + records


class FakeClient(sr.SoRClient):
    """SoRClient over a fake link: records every document and STEP_INPUT."""

    def __init__(self, enhanced: dict[int, bool] | None = None, **kwargs) -> None:
        super().__init__("127.0.0.1", 1, **kwargs)
        self.documents: list[sr.InputDocument] = []
        self.steps: list[bytes] = []
        self.frame = 100
        enhanced = enhanced or {}
        self.status = _status(*((p, 2 if enhanced.get(p) else 1, 0, 0) for p in (1, 2)))
        self.status_reads = 0
        self.vsyncs = 0

    def set_execution_data(self, data) -> None:
        self.documents.append(sr.unpack_input(bytes(data)))

    def get_game_uptime_frames(self) -> int:
        return self.frame

    def get_game_data(self) -> bytes:
        self.status_reads += 1
        return self.status

    def wait_vsync(self, count: int = 1, *, timeout_ms=None) -> None:
        self.vsyncs += count

    def _request(self, command, payload=b"", **kwargs):
        assert command == Command.STEP_INPUT
        self.steps.append(payload)
        return struct.pack(">Q", self.frame) + bytes(65_536)

    @property
    def last(self) -> sr.InputDocument:
        return self.documents[-1]


class CodecTests(unittest.TestCase):
    def test_an_input_document_round_trips(self):
        document = sr.InputDocument(
            players={
                1: sr.PlayerInput(held=sr.ACTION_LEFT, seq=7, queue=True, schedule=((sr.ACTION_PUNCH, 4),)),
                2: sr.PlayerInput(held=0, seq=9),
            },
            serial=42,
        )
        self.assertEqual(sr.unpack_input(sr.pack_input(document)), document)

    def test_the_layout_is_the_games(self):
        data = sr.pack_input(sr.InputDocument({1: sr.PlayerInput(held=0x0041, seq=3)}, 5))
        self.assertEqual(data[:4], b"SORX")
        self.assertEqual(struct.unpack(">HHI", data[4:12]), (1, 1, 5))
        self.assertEqual(struct.unpack(">HH", data[12:16]), (sr.TAG_PLAYER_INPUT, 10))
        self.assertEqual(struct.unpack(">BBHIH", data[16:26]), (1, 0, 0x0041, 3, 0))

    def test_a_long_entry_is_split_to_fit_sixteen_bits(self):
        data = sr.pack_input(sr.InputDocument({1: sr.PlayerInput(seq=1, schedule=((1, 70_000),))}))
        schedule = sr.unpack_input(data).players[1].schedule
        self.assertEqual(schedule, ((1, 65_535), (1, 4_465)))

    def test_status_reads_each_player(self):
        status = sr.unpack_status(_status((1, 2, 11, 500), (2, 1, 0, 0)))
        self.assertTrue(status[1].enhanced)
        self.assertEqual((status[1].seq, status[1].end_frame), (11, 500))
        self.assertFalse(status[2].enhanced)
        self.assertEqual(sr.unpack_status(b""), {})

    def test_another_magic_is_refused(self):
        with self.assertRaises(ValueError):
            sr.unpack_status(sr.pack_input(sr.InputDocument()))

    def test_run_lengths(self):
        self.assertEqual(sr.run_lengths([1, 1, 2, 0, 0]), ((1, 2), (2, 1), (0, 2)))


class MappingTests(unittest.TestCase):
    def test_original_3_is_the_three_buttons(self):
        self.assertEqual(sr.md_buttons_to_actions(A, enhanced=False), sr.ACTION_SPECIAL)
        self.assertEqual(sr.md_buttons_to_actions(B | C, enhanced=False), sr.ACTION_PUNCH | sr.ACTION_JUMP)
        self.assertEqual(sr.md_buttons_to_actions(X | Y | Z, enhanced=False), 0)

    def test_enhanced_6_is_the_old_alt_controls_layout(self):
        self.assertEqual(sr.md_buttons_to_actions(A, enhanced=True), sr.ACTION_BACK_ATTACK)
        self.assertEqual(sr.md_buttons_to_actions(X, enhanced=True), sr.ACTION_SPECIAL)
        self.assertEqual(sr.md_buttons_to_actions(Y, enhanced=True), sr.ACTION_PICKUP)
        self.assertEqual(sr.md_buttons_to_actions(Z, enhanced=True), sr.ACTION_THROW)

    def test_directions_and_start_are_themselves(self):
        self.assertEqual(
            sr.md_buttons_to_actions(UP | RIGHT | START, enhanced=False),
            sr.ACTION_UP | sr.ACTION_RIGHT | sr.ACTION_START,
        )


class SoRClientTests(unittest.TestCase):
    def test_the_document_never_sets_a_scheme(self):
        client = FakeClient()
        client.hold_buttons(player1=RIGHT)
        data = sr.pack_input(client.last)
        tags = []
        at = sr.HEADER.size
        while at < len(data):
            tag, length = sr.RECORD.unpack_from(data, at)
            tags.append(tag)
            at += sr.RECORD.size + length
        self.assertEqual(set(tags), {sr.TAG_PLAYER_INPUT})

    def test_each_players_scheme_is_queried_from_the_game(self):
        client = FakeClient(enhanced={1: True, 2: False})
        self.assertTrue(client.enhanced(1))
        self.assertFalse(client.enhanced(2))

    def test_the_query_is_repeated_only_once_stale(self):
        client = FakeClient(enhanced={1: True})
        client.enhanced(1)
        client.hold_buttons(player1=RIGHT)
        client.queue_press_buttons(player=1, buttons=B)
        self.assertEqual(client.status_reads, 1)
        client._schemes_read_at -= sr.SCHEME_REFRESH_S
        client.hold_buttons(player1=0)
        self.assertEqual(client.status_reads, 2)

    def test_a_scheme_changed_in_the_game_is_followed(self):
        client = FakeClient(enhanced={1: False})
        client.queue_press_buttons(player=1, buttons=A, frames=1)
        self.assertEqual(client.last.players[1].schedule, ((sr.ACTION_SPECIAL, 1),))
        client.status = _status((1, 2, 0, 0), (2, 1, 0, 0))
        client._schemes_read_at -= sr.SCHEME_REFRESH_S
        client.queue_press_buttons(player=1, buttons=A, frames=1)
        self.assertEqual(client.last.players[1].schedule, ((sr.ACTION_BACK_ATTACK, 1),))

    def test_a_hold_changes_the_held_actions_not_the_schedule(self):
        client = FakeClient()
        client.hold_buttons(player1=RIGHT | B, player2=LEFT)
        first = client.last
        self.assertEqual(first.players[1].held, sr.ACTION_RIGHT | sr.ACTION_PUNCH)
        self.assertEqual(first.players[2].held, sr.ACTION_LEFT)
        client.hold_buttons(player1=0, player2=LEFT)
        self.assertEqual(client.last.players[1].seq, first.players[1].seq)
        self.assertEqual(client.last.players[1].held, 0)

    def test_every_document_differs(self):
        client = FakeClient()
        client.hold_buttons(player1=RIGHT)
        client.hold_buttons(player1=RIGHT)
        self.assertNotEqual(client.documents[0].serial, client.documents[1].serial)

    def test_a_queued_press_is_one_scheduled_entry_from_the_next_frame(self):
        client = FakeClient()
        client.hold_buttons(player1=RIGHT)
        release = client.queue_press_buttons(player=1, buttons=B, frames=4)
        record = client.last.players[1]
        self.assertEqual(release, 101 + 4)
        self.assertTrue(record.queue)
        self.assertEqual(record.schedule, ((sr.ACTION_PUNCH, 4),))
        self.assertEqual(record.held, sr.ACTION_RIGHT)

    def test_a_press_behind_another_follows_a_released_frame(self):
        client = FakeClient()
        first = client.queue_press_buttons(player=1, buttons=B, frames=4)
        seq = client.last.players[1].seq
        second = client.queue_press_buttons(player=1, buttons=C, frames=2)
        self.assertEqual(second, first + 1 + 2)
        self.assertEqual(client.last.players[1].seq, seq + 1)
        client.frame = 200
        self.assertEqual(client.queue_press_buttons(player=1, buttons=B, frames=1), 202)

    def test_the_enhanced_mapping_is_used_for_an_enhanced_player(self):
        client = FakeClient(enhanced={1: True})
        client.queue_press_buttons(player=1, buttons=Y, frames=1)
        self.assertEqual(client.last.players[1].schedule, ((sr.ACTION_PICKUP, 1),))

    def test_release_cancels_holds_and_schedules(self):
        client = FakeClient()
        client.hold_buttons(player1=RIGHT, player2=LEFT)
        client.queue_press_buttons(player=2, buttons=B, frames=3)
        seq = {player: client.last.players[player].seq for player in (1, 2)}
        client.release_buttons()
        for player in (1, 2):
            record = client.last.players[player]
            self.assertEqual((record.held, record.schedule), (0, ()))
            self.assertGreater(record.seq, seq[player])

    def test_a_blocking_press_plays_then_releases_both(self):
        client = FakeClient()
        client.hold_buttons(player1=RIGHT)
        client.press_buttons(player1=START, frames=3)
        record = client.last.players[1]
        self.assertEqual((record.held, record.schedule, record.queue), (0, ((sr.ACTION_START, 3),), False))
        self.assertEqual(client.vsyncs, 4)

    def test_step_frames_is_one_document_and_one_step(self):
        client = FakeClient()
        result = client.step_frames([(B, 0), (RIGHT, LEFT)])
        self.assertEqual(len(client.documents), 1)
        self.assertEqual(client.last.players[1].schedule, ((sr.ACTION_PUNCH, 1), (sr.ACTION_RIGHT, 1)))
        self.assertEqual(client.last.players[2].schedule, ((0, 1), (sr.ACTION_LEFT, 1)))
        self.assertFalse(client.last.players[1].queue)
        p1, p2, held, total, _ = struct.unpack(">HH2xIII", client.steps[0])
        self.assertEqual((p1, p2, held, total), (0, 0, 0, 2))
        self.assertEqual(result.frame, 100)

    def test_step_input_keeps_its_held_then_released_frames(self):
        client = FakeClient()
        client.step_input(player1=B, held_frames=1, total_frames=3)
        self.assertEqual(client.last.players[1].schedule, ((sr.ACTION_PUNCH, 1), (0, 2)))

    def test_the_gamepad_and_the_loop_take_the_games_scheme(self):
        from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
        from sor_autoplay.ai.loop import AgentLoop

        client = FakeClient(enhanced={1: True, 2: False})
        state = SharedGamepadState(client)
        pad1 = VirtualGamepad(state, player_index=1)
        pad2 = VirtualGamepad(state, player_index=2)
        self.assertTrue(pad1.enhanced)
        self.assertFalse(pad2.enhanced)
        loop = AgentLoop(pad1)
        loop.six_button = False  # what a caller set is overruled by the game
        self.assertTrue(loop._six_button())

    def test_two_clients_never_share_a_first_document(self):
        self.assertNotEqual(FakeClient()._serial, FakeClient()._serial)


if __name__ == "__main__":
    unittest.main()
