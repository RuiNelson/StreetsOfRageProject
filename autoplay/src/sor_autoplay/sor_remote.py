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
  held:H, seq:I, count:H`` then ``count`` x ``actions:H, frames:H``) and
  ``SCHEME_OVERRIDE`` (``player:B, scheme:B``);
- game -> client, magic ``SORG``: ``PLAYER_STATUS`` (``player:B, scheme:B,
  seq:I, end frame:Q``).

:class:`SoRClient` keeps ``MegaDriveClient``'s gamepad API -- ``hold_buttons``,
``queue_press_buttons``, ``press_buttons``, ``release_buttons``,
``step_input`` -- with the Mega Drive masks the AI already speaks, and turns
each player's mask into actions with the mapping of that player's scheme
(the one ``ai/execute.py`` picks its buttons by). Their timing is the old
commands': a queued press starts on the next sampled frame, replaces the
held mask while it plays, and one queued behind another waits for it and a
released frame.
"""

from __future__ import annotations

import os
import struct
import threading
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from megadrive_remote import MegaDriveClient, StepResult

# Actions (SoRControlsConfig::Action), one bit each.
ACTION_UP = 1 << 0
ACTION_DOWN = 1 << 1
ACTION_LEFT = 1 << 2
ACTION_RIGHT = 1 << 3
ACTION_START = 1 << 4
ACTION_SPECIAL = 1 << 5
ACTION_PUNCH = 1 << 6
ACTION_JUMP = 1 << 7
ACTION_BACK_ATTACK = 1 << 8
ACTION_PICKUP = 1 << 9
ACTION_THROW = 1 << 10

SCHEME_ORIGINAL3 = 1
SCHEME_ENHANCED6 = 2
SCHEMES = {"original3": SCHEME_ORIGINAL3, "enhanced6": SCHEME_ENHANCED6}

INPUT_MAGIC = b"SORX"
STATUS_MAGIC = b"SORG"
VERSION = 1

HEADER = struct.Struct(">4sHHI")
RECORD = struct.Struct(">HH")
PLAYER_INPUT = struct.Struct(">BBHIH")
ENTRY = struct.Struct(">HH")
SCHEME_OVERRIDE = struct.Struct(">BB")
PLAYER_STATUS = struct.Struct(">BBIQ")

TAG_PLAYER_INPUT = 0x0001
TAG_SCHEME_OVERRIDE = 0x0002
TAG_PLAYER_STATUS = 0x0101

FLAG_QUEUE = 0x01

MAX_ENTRY_FRAMES = 0xFFFF

# Mega Drive mask bits (megadrive_remote.Buttons).
_MD_UP, _MD_DOWN, _MD_LEFT, _MD_RIGHT = 0x001, 0x002, 0x004, 0x008
_MD_A, _MD_B, _MD_C, _MD_START = 0x010, 0x020, 0x040, 0x080
_MD_X, _MD_Y, _MD_Z = 0x100, 0x200, 0x400


@dataclass(frozen=True)
class PlayerInput:
    """One player's record: the steady state and the latest schedule."""

    held: int = 0
    seq: int = 0
    queue: bool = False
    schedule: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class PlayerStatus:
    scheme: int
    seq: int
    end_frame: int

    @property
    def enhanced(self) -> bool:
        return self.scheme == SCHEME_ENHANCED6


@dataclass(frozen=True)
class InputDocument:
    players: dict[int, PlayerInput] = field(default_factory=dict)
    scheme_overrides: dict[int, int] = field(default_factory=dict)
    serial: int = 0


def md_buttons_to_actions(mask: int, *, enhanced: bool) -> int:
    """A Mega Drive mask as actions, by the scheme's buttons.

    ORIGINAL 3: A Special, B Punch, C Jump. ENHANCED 6 (the former
    ``--altControls`` layout): B Punch, C Jump, A Back Attack, X Special, Y
    Pick Item, Z Throw Knife. Directions and Start are themselves.
    """

    mask = int(mask)
    actions = 0
    for bit, action in (
        (_MD_UP, ACTION_UP),
        (_MD_DOWN, ACTION_DOWN),
        (_MD_LEFT, ACTION_LEFT),
        (_MD_RIGHT, ACTION_RIGHT),
        (_MD_START, ACTION_START),
        (_MD_B, ACTION_PUNCH),
        (_MD_C, ACTION_JUMP),
    ):
        if mask & bit:
            actions |= action
    if enhanced:
        for bit, action in (
            (_MD_A, ACTION_BACK_ATTACK),
            (_MD_X, ACTION_SPECIAL),
            (_MD_Y, ACTION_PICKUP),
            (_MD_Z, ACTION_THROW),
        ):
            if mask & bit:
                actions |= action
    elif mask & _MD_A:
        actions |= ACTION_SPECIAL
    return actions


def run_lengths(actions: Iterable[int]) -> tuple[tuple[int, int], ...]:
    """Consecutive equal per-frame actions as ``(actions, frames)`` entries."""

    entries: list[list[int]] = []
    for value in actions:
        if entries and entries[-1][0] == value and entries[-1][1] < MAX_ENTRY_FRAMES:
            entries[-1][1] += 1
        else:
            entries.append([value, 1])
    return tuple((value, frames) for value, frames in entries)


def _split(schedule: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    entries = []
    for actions, frames in schedule:
        while frames > 0:
            step = min(frames, MAX_ENTRY_FRAMES)
            entries.append((actions, step))
            frames -= step
    return entries


def pack_input(document: InputDocument) -> bytes:
    records = []
    for player in sorted(document.players):
        record = document.players[player]
        entries = _split(record.schedule)
        payload = PLAYER_INPUT.pack(
            player,
            FLAG_QUEUE if record.queue else 0,
            record.held & 0xFFFF,
            record.seq & 0xFFFFFFFF,
            len(entries),
        ) + b"".join(ENTRY.pack(actions & 0xFFFF, frames) for actions, frames in entries)
        records.append(RECORD.pack(TAG_PLAYER_INPUT, len(payload)) + payload)
    for player in sorted(document.scheme_overrides):
        payload = SCHEME_OVERRIDE.pack(player, document.scheme_overrides[player])
        records.append(RECORD.pack(TAG_SCHEME_OVERRIDE, len(payload)) + payload)
    header = HEADER.pack(INPUT_MAGIC, VERSION, len(records), document.serial & 0xFFFFFFFF)
    return header + b"".join(records)


def _records(data: bytes, magic: bytes) -> Iterable[tuple[int, bytes]]:
    if len(data) < HEADER.size:
        raise ValueError("document is shorter than its header")
    found, version, count, _ = HEADER.unpack_from(data)
    if found != magic or version != VERSION:
        raise ValueError(f"not a version-{VERSION} {magic!r} document")
    at = HEADER.size
    for _ in range(count):
        tag, length = RECORD.unpack_from(data, at)
        at += RECORD.size
        if at + length > len(data):
            raise ValueError("record runs past the document")
        yield tag, data[at : at + length]
        at += length


def unpack_input(data: bytes) -> InputDocument:
    players: dict[int, PlayerInput] = {}
    overrides: dict[int, int] = {}
    for tag, payload in _records(data, INPUT_MAGIC):
        if tag == TAG_PLAYER_INPUT:
            player, flags, held, seq, count = PLAYER_INPUT.unpack_from(payload)
            schedule = tuple(
                ENTRY.unpack_from(payload, PLAYER_INPUT.size + i * ENTRY.size) for i in range(count)
            )
            players[player] = PlayerInput(held, seq, bool(flags & FLAG_QUEUE), schedule)
        elif tag == TAG_SCHEME_OVERRIDE:
            player, scheme = SCHEME_OVERRIDE.unpack_from(payload)
            overrides[player] = scheme
    serial = HEADER.unpack_from(data)[3]
    return InputDocument(players, overrides, serial)


def unpack_status(data: bytes) -> dict[int, PlayerStatus]:
    """The game's PLAYER_STATUS records; empty before the game has written any."""

    if not data:
        return {}
    status = {}
    for tag, payload in _records(data, STATUS_MAGIC):
        if tag == TAG_PLAYER_STATUS:
            player, scheme, seq, end_frame = PLAYER_STATUS.unpack_from(payload)
            status[player] = PlayerStatus(scheme, seq, end_frame)
    return status


def _scheme_value(scheme: int | str | None) -> int | None:
    if scheme is None:
        return None
    if isinstance(scheme, str):
        return SCHEMES[scheme]
    if scheme not in (SCHEME_ORIGINAL3, SCHEME_ENHANCED6):
        raise ValueError(f"unknown scheme {scheme!r}")
    return int(scheme)


# A measurement default: both players on ORIGINAL 3, as every session played
# before the game bound actions (the labs and fight harnesses rely on it).
# The observer passes its own (``--scheme-p1/-p2``, only for AI players).
MEASUREMENT_SCHEMES: Mapping[int, int] = {1: SCHEME_ORIGINAL3, 2: SCHEME_ORIGINAL3}


class SoRClient(MegaDriveClient):
    """``MegaDriveClient`` whose gamepad commands go through the execution data.

    ``schemes`` maps a player (1, 2) to the scheme the game puts them on for
    this connection (``SCHEME_OVERRIDE``, never saved); a player left out uses
    the game's own (``controls.yaml``), read from ``GET_GAME_DATA`` by
    :meth:`refresh_schemes`.
    """

    def __init__(
        self,
        *args,
        schemes: Mapping[int, int | str | None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        if schemes is None:
            schemes = MEASUREMENT_SCHEMES
        self._input_lock = threading.RLock()
        self._overrides = {
            player: value
            for player, value in ((p, _scheme_value(s)) for p, s in schemes.items())
            if value is not None
        }
        self._enhanced = {
            player: self._overrides.get(player) == SCHEME_ENHANCED6 for player in (1, 2)
        }
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
        """Read each player's scheme from the game (an override wins)."""

        status = unpack_status(self.get_game_data())
        with self._input_lock:
            for player in (1, 2):
                override = self._overrides.get(player)
                if override is not None:
                    self._enhanced[player] = override == SCHEME_ENHANCED6
                elif player in status:
                    self._enhanced[player] = status[player].enhanced
        return status

    def enhanced(self, player: int) -> bool:
        """Whether ``player`` is on ENHANCED 6 (as last read or overridden)."""

        with self._input_lock:
            return self._enhanced[player]

    def set_scheme_override(self, player: int, scheme: int | str | None) -> None:
        value = _scheme_value(scheme)
        with self._input_lock:
            if value is None:
                self._overrides.pop(player, None)
            else:
                self._overrides[player] = value
                self._enhanced[player] = value == SCHEME_ENHANCED6
            self._send()

    def player_status(self) -> dict[int, PlayerStatus]:
        return unpack_status(self.get_game_data())

    # -- the gamepad API, as actions

    def hold_buttons(self, *, player1: int = 0, player2: int = 0) -> None:
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

    def _actions(self, player: int, mask: int) -> int:
        return md_buttons_to_actions(mask, enhanced=self._enhanced[player])

    def _next_seq(self, player: int) -> int:
        self._seq[player] = (self._seq[player] + 1) & 0xFFFFFFFF
        return self._seq[player]

    def _send(self) -> None:
        self._serial = (self._serial + 1) & 0xFFFFFFFF
        document = InputDocument(dict(self._players), dict(self._overrides), self._serial)
        self.set_execution_data(pack_input(document))
