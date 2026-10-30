"""Streets of Rage input documents: actions, the binary layout, no transport.

The game reads the keyboard and gamepads itself and binds them to actions
(``StreetsOfRageRecompilation/SoRInput``). A client's input is a binary document
the game reads once a frame (``SoRRemoteInput``), and the game answers with
another. Both are packed with ``struct``, big-endian, and built to grow -- a
container, then tagged records, an unknown tag skipped. The layout is
``SoRRemoteInput.hpp``'s; change both together:

- container ``magic:4s, version:H, record count:H, serial:I``;
- record ``tag:H, length:H`` and the payload;
- client -> game, magic ``SORX``: ``PLAYER_INPUT`` (``player:B, flags:B,
  held:H, seq:I, count:H`` then ``count`` x ``actions:H, frames:H``);
- game -> client, magic ``SORG``: ``PLAYER_STATUS`` (``player:B, scheme:B,
  seq:I, end frame:Q``).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterable, Sequence

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

INPUT_MAGIC = b"SORX"
STATUS_MAGIC = b"SORG"
VERSION = 1

HEADER = struct.Struct(">4sHHI")
RECORD = struct.Struct(">HH")
PLAYER_INPUT = struct.Struct(">BBHIH")
ENTRY = struct.Struct(">HH")
PLAYER_STATUS = struct.Struct(">BBIQ")

TAG_PLAYER_INPUT = 0x0001
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
    for tag, payload in _records(data, INPUT_MAGIC):
        if tag == TAG_PLAYER_INPUT:
            player, flags, held, seq, count = PLAYER_INPUT.unpack_from(payload)
            schedule = tuple(
                ENTRY.unpack_from(payload, PLAYER_INPUT.size + i * ENTRY.size) for i in range(count)
            )
            players[player] = PlayerInput(held, seq, bool(flags & FLAG_QUEUE), schedule)
    serial = HEADER.unpack_from(data)[3]
    return InputDocument(players, serial)


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
