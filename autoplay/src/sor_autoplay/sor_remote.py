"""Streets of Rage remote input: actions through the execution data.

The game reads the keyboard and gamepads itself and binds them to actions
(``StreetsOfRageRecompilation/SoRInput``); it no longer reads the Mega Drive
buttons ``MegaDriveClient``'s gamepad commands send. A client's input goes
through the remote-access execution-data buffer instead, as a binary
document the game reads once a frame (``SoRRemoteInput``), and the game
answers in the game-data buffer (``GET_GAME_DATA``). Both are packed with
``struct``, big-endian, and built to grow -- a container, then tagged records,
an unknown tag skipped. The layout is ``SoRRemoteInput.hpp``'s; change both
together:

- container ``magic:4s, version:H, record count:H, serial:I``;
- record ``tag:H, length:H`` and the payload;
- client -> game, magic ``SORX``: ``PLAYER_INPUT`` (``player:B, flags:B,
  held:H, seq:I, count:H`` then ``count`` x ``actions:H, frames:H``);
- game -> client, magic ``SORG``: ``PLAYER_STATUS`` (``player:B, scheme:B,
  seq:I, end frame:Q``).

:class:`SoRClient` keeps ``MegaDriveClient``'s gamepad API -- ``hold_buttons``,
``queue_press_buttons``, ``press_buttons``, ``release_buttons``,
``step_input`` -- with the Mega Drive masks the AI already speaks, and turns
each player's mask into actions with the mapping of that player's scheme
(the one ``ai/execute.py`` picks its buttons by). The scheme is the player's
own, set in the game (OPTIONS > CONTROLS, ``controls.yaml``): the client
queries it (``PLAYER_STATUS``) on connecting and again at most every
``SCHEME_REFRESH_S``, and never sets it. Their timing is the old
commands': a queued press starts on the next sampled frame, replaces the
held mask while it plays, and one queued behind another waits for it and a
released frame.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Iterable, Sequence

from megadrive_remote import MegaDriveClient, StepResult

from sor_ai.remote_input import (  # noqa: F401 -- also this module's public names
    ACTION_UP,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_RIGHT,
    ACTION_START,
    ACTION_SPECIAL,
    ACTION_PUNCH,
    ACTION_JUMP,
    ACTION_BACK_ATTACK,
    ACTION_PICKUP,
    ACTION_THROW,
    SCHEME_ORIGINAL3,
    SCHEME_ENHANCED6,
    INPUT_MAGIC,
    STATUS_MAGIC,
    VERSION,
    HEADER,
    RECORD,
    PLAYER_INPUT,
    ENTRY,
    PLAYER_STATUS,
    TAG_PLAYER_INPUT,
    TAG_PLAYER_STATUS,
    FLAG_QUEUE,
    MAX_ENTRY_FRAMES,
    PlayerInput,
    PlayerStatus,
    InputDocument,
    md_buttons_to_actions,
    run_lengths,
    _split,
    pack_input,
    _records,
    unpack_input,
    unpack_ai_assist,
    unpack_status,
)

# How stale the queried schemes may get: a player who changes theirs in
# OPTIONS > CONTROLS is followed within this long.
SCHEME_REFRESH_S = 1.0

class SoRClient(MegaDriveClient):
    """``MegaDriveClient`` whose gamepad commands go through the execution data.

    Each player's scheme is queried from the game (``GET_GAME_DATA``'s
    ``PLAYER_STATUS``): on connecting, whenever :meth:`refresh_schemes` is
    called, and before a mask is mapped or :meth:`enhanced` answers once the
    last reading is ``SCHEME_REFRESH_S`` old.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._input_lock = threading.RLock()
        self._enhanced = {1: False, 2: False}
        self._schemes_read_at: float | None = None
        # A fresh client must never repeat the previous one's document or
        # sequence numbers byte for byte (the game drops left-over input
        # until the buffer changes, and a seq it has seen starts nothing).
        start = int.from_bytes(os.urandom(4), "big") & 0x3FFFFFFF
        self._serial = start
        self._seq = {1: start, 2: start}
        self._players = {1: PlayerInput(seq=start), 2: PlayerInput(seq=start)}
        self._release = {1: 0, 2: 0}

    # -- connection

    def connect(self) -> "SoRClient":
        super().connect()
        with self._input_lock:
            self._send()
        self.refresh_schemes()
        return self

    def restart_game(self, *, timeout_ms: int = 5_000) -> None:
        super().restart_game(timeout_ms=timeout_ms)
        with self._input_lock:
            self._release = {1: 0, 2: 0}
            for player in (1, 2):
                self._players[player] = PlayerInput(seq=self._next_seq(player))
            self._send()

    # -- schemes

    def refresh_schemes(self) -> dict[int, PlayerStatus]:
        """Query each player's scheme from the game."""

        status = unpack_status(self.get_game_data())
        with self._input_lock:
            for player in (1, 2):
                if player in status:
                    self._enhanced[player] = status[player].enhanced
            self._schemes_read_at = time.monotonic()
        return status

    def enhanced(self, player: int) -> bool:
        """Whether ``player`` is on ENHANCED 6 (re-queried once stale)."""

        self._refresh_if_stale()
        with self._input_lock:
            return self._enhanced[player]

    def ai_assist(self) -> bool:
        """Whether the game's own AI plays P2: this client's P2 input is ignored."""

        return unpack_ai_assist(self.get_game_data())

    def player_status(self) -> dict[int, PlayerStatus]:
        return unpack_status(self.get_game_data())

    # -- the gamepad API, as actions

    def hold_buttons(self, *, player1: int = 0, player2: int = 0) -> None:
        self._refresh_if_stale()
        with self._input_lock:
            for player, mask in ((1, player1), (2, player2)):
                record = self._players[player]
                self._players[player] = PlayerInput(
                    self._actions(player, mask), record.seq, record.queue, record.schedule
                )
            self._send()

    def queue_press_buttons(self, *, player: int, buttons: int, frames: int = 1) -> int:
        if player not in (1, 2):
            raise ValueError("player must be 1 or 2")
        frames = self._positive(frames, "frames")
        now = self.get_game_uptime_frames()
        self._refresh_if_stale()
        with self._input_lock:
            # From the next sampled frame, or after the running press and a
            # released frame.
            previous = self._release[player]
            start = previous + 1 if previous >= now + 1 else now + 1
            release = start + frames
            self._release[player] = release
            record = self._players[player]
            self._players[player] = PlayerInput(
                record.held,
                self._next_seq(player),
                True,
                ((self._actions(player, buttons), frames),),
            )
            self._send()
        return release

    def press_buttons(
        self,
        *,
        player1: int = 0,
        player2: int = 0,
        frames: int = 1,
        timeout_ms: int | None = None,
    ) -> None:
        """Both masks for ``frames`` frames from the next one, then both
        players released (as ``PRESS_BUTTONS`` did); returns once played."""

        frames = self._positive(frames, "frames")
        self._refresh_if_stale()
        with self._input_lock:
            for player, mask in ((1, player1), (2, player2)):
                self._players[player] = PlayerInput(
                    0, self._next_seq(player), False, ((self._actions(player, mask), frames),)
                )
                self._release[player] = 0
            self._send()
        if timeout_ms is None:
            timeout_ms = max(1_000, frames * 50 + 1_000)
        self.wait_vsync(frames + 1, timeout_ms=timeout_ms)

    def release_buttons(self) -> None:
        with self._input_lock:
            for player in (1, 2):
                self._players[player] = PlayerInput(0, self._next_seq(player))
                self._release[player] = 0
            self._send()

    def step_input(
        self,
        *,
        player1: int = 0,
        player2: int = 0,
        held_frames: int,
        total_frames: int,
        timeout_ms: int | None = None,
    ) -> StepResult:
        """Lockstep: both masks for ``held_frames`` of ``total_frames``."""

        released = total_frames - held_frames
        masks = [(player1, player2)] * held_frames + [(0, 0)] * released
        return self.step_frames(masks, timeout_ms=timeout_ms)

    def step_frames(
        self, masks: Sequence[tuple[int, int]], *, timeout_ms: int | None = None
    ) -> StepResult:
        """Lockstep: one ``(player1, player2)`` mask pair per frame, in one
        document and one ``STEP_INPUT``."""

        if not masks:
            raise ValueError("step_frames needs at least one frame")
        self._refresh_if_stale()
        with self._input_lock:
            for index, player in enumerate((1, 2)):
                schedule = run_lengths(self._actions(player, pair[index]) for pair in masks)
                self._players[player] = PlayerInput(0, self._next_seq(player), False, schedule)
                self._release[player] = 0
            self._send()
        return super().step_input(
            player1=0, player2=0, held_frames=0, total_frames=len(masks), timeout_ms=timeout_ms
        )

    # -- internals

    def _refresh_if_stale(self) -> None:
        read_at = self._schemes_read_at
        if read_at is None or time.monotonic() - read_at >= SCHEME_REFRESH_S:
            self.refresh_schemes()

    def _actions(self, player: int, mask: int) -> int:
        return md_buttons_to_actions(mask, enhanced=self._enhanced[player])

    def _next_seq(self, player: int) -> int:
        self._seq[player] = (self._seq[player] + 1) & 0xFFFFFFFF
        return self._seq[player]

    def _send(self) -> None:
        self._serial = (self._serial + 1) & 0xFFFFFFFF
        document = InputDocument(dict(self._players), self._serial)
        self.set_execution_data(pack_input(document))
