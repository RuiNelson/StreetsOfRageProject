"""Record the reads ``read_snapshot`` makes, and serve them back offline.

A live stall is a tick the pipeline got wrong, and the pipeline is pure over
the snapshot: record every ``read_memory`` (and the uptime) a tick's
``read_snapshot`` makes, and the same tick can be rebuilt later and run
through ``AgentLoop`` -- or any single ``decide``/``priority``/``execute``
function -- as often as the question needs, with no host.

The recording is JSONL. The first row holds ``RomData``'s own reads
(``{"rom": {...}}``); every later row is one tick, ``{"t": ..., "reads":
{...}}``, holding only the reads whose bytes changed since the previous row
(the class map and the ROM-static blocks are written once). ``iter_ticks``
folds them back into each tick's full read set.

Used by ``stage_walk_diag.py --raw FILE``; replay with::

    from snapshot_replay import load_rom, iter_ticks, ReplaySource
    rom = load_rom(path)
    for t, reads in iter_ticks(path):
        snap = read_snapshot(ReplaySource(reads), rom=rom)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from sor_autoplay.rom_data import RomData


def _key(address: int, length: int) -> str:
    return f"{address:x}:{length}"


class RecordingSource:
    """Wraps a client; while recording, keeps every read it serves."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._reads: dict[str, str] | None = None

    def start(self) -> None:
        self._reads = {}

    def stop(self) -> dict[str, str]:
        reads, self._reads = self._reads or {}, None
        return reads

    def read_memory(self, address: int, length: int) -> bytes:
        data = self._client.read_memory(address, length)
        if self._reads is not None:
            self._reads[_key(address, length)] = bytes(data).hex()
        return data

    def get_game_uptime_frames(self) -> int:
        frames = self._client.get_game_uptime_frames()
        if self._reads is not None:
            self._reads["uptime"] = str(frames)
        return frames

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class ReplaySource:
    """Serves one tick's recorded reads back to ``read_snapshot``."""

    def __init__(self, reads: dict[str, str]) -> None:
        self._reads = reads

    def read_memory(self, address: int, length: int) -> bytes:
        return bytes.fromhex(self._reads[_key(address, length)])

    def get_game_uptime_frames(self) -> int:
        return int(self._reads.get("uptime", "0"))


class SnapshotRecorder:
    """Writes ``RecordingSource`` reads as delta rows."""

    def __init__(self, path: str) -> None:
        self._sink = open(path, "w", encoding="utf-8")
        self._last: dict[str, str] = {}

    def write_rom(self, reads: dict[str, str]) -> None:
        self._sink.write(json.dumps({"rom": reads}) + "\n")

    def write_tick(self, t: float, reads: dict[str, str]) -> None:
        delta = {k: v for k, v in reads.items() if self._last.get(k) != v}
        self._last.update(reads)
        self._sink.write(json.dumps({"t": t, "reads": delta}) + "\n")

    def close(self) -> None:
        self._sink.close()


def load_rom(path: str) -> RomData:
    with open(path, encoding="utf-8") as source:
        first = json.loads(source.readline())
    return RomData.read(ReplaySource(first["rom"]))


def iter_ticks(path: str) -> Iterator[tuple[float, dict[str, str]]]:
    state: dict[str, str] = {}
    with open(path, encoding="utf-8") as source:
        source.readline()
        for line in source:
            row = json.loads(line)
            state.update(row["reads"])
            yield row["t"], dict(state)
