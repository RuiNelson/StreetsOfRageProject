"""Record, and check ``ai/twins.py`` against, Onihime and Yasha in lockstep.

The round-5 lockstep lab, in the shape of ``tools/bongo_lab.py``: the real
``AgentLoop`` plays round 5 (street waves swept) until both twins (type
``$58``) are on screen, then the host goes into lockstep and one of four
actors plays on, a frame at a time:

``engage``
    the real pipeline, ticked every two frames as live, its pad recorded and
    applied through ``step_input``;
``edge``
    a scripted version of the plan's shape -- walk to the nearer camera edge,
    face the wall, and press B+C whenever a twin walks into ``--chord-dx``
    behind the actor on its lane band -- for chord and knockdown data;
``wander``
    a seeded walk that never attacks, to take the twins through their whole
    state machine;
``stand``
    nothing at all.

Every frame writes a row with the input, the camera and the **raw bytes** of
the player's object and of both twins' slots (hex), so the model can be
checked against the ROM offline, update by update, as often as it changes
(``--check`` replays a recording through ``twins.boss_update`` and reports
every field that differs). A recording is local analysis output: do not
commit it.

Run (host already up with ``--debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/twins_lab.py --actor edge --out /tmp/twins.jsonl
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/twins_lab.py --check /tmp/twins.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, deque

from sor_autoplay import memory_map as mm

WORK_RAM = 0xFF0000
LEVEL = 5
TWIN_TYPE = 0x58
FRAMES_PER_TICK = 2
SWEEP_EVERY_FRAMES = 30

UP, DOWN, LEFT, RIGHT = 0x0001, 0x0002, 0x0004, 0x0008
PUNCH, JUMP = 0x0020, 0x0040  # physical B and C (A, 0x10, is the police)


def _window(ram: bytes, address: int, length: int) -> bytes:
    offset = address - WORK_RAM
    if offset < 0 or offset + length > len(ram):
        return b""
    return ram[offset : offset + length]


def twin_slots(ram: bytes) -> list[tuple[int, bytes]]:
    """Every live type-``$58`` object: (slot index, its 128 bytes)."""

    found = []
    for index in range(mm.OBJECT_TABLE_SLOTS):
        address = mm.ADDR_OBJECT_TABLE + index * mm.OBJECT_SLOT_SIZE
        slot = _window(ram, address, mm.OBJECT_SLOT_SIZE)
        if slot and slot[0] == TWIN_TYPE:
            found.append((index, slot))
    return found


def _s16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big", signed=True)


class Wander:
    """A seeded walk that never presses B or C."""

    DIRECTIONS = (0, UP, DOWN, LEFT, RIGHT, UP | LEFT, UP | RIGHT, DOWN | LEFT, DOWN | RIGHT)

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.left = 0
        self.mask = 0

    def mask_for(self, ram: bytes) -> int:
        if self.left <= 0:
            self.mask = self.rng.choice(self.DIRECTIONS)
            self.left = self.rng.randint(20, 60)
        self.left -= 1
        return self.mask


class Edge:
    """Walk to the nearer camera edge, face the wall, chord what comes in.

    Deliberately simple -- it is a data source, not the plan: the chord is
    pressed when any grounded twin's origin is ``chord_dx`` or less behind
    the actor, 16 lanes or less off, and the actor is standing free.
    """

    def __init__(self, chord_dx: int, lane_follow: bool) -> None:
        self.chord_dx = chord_dx
        self.lane_follow = lane_follow
        self.side: int | None = None
        self.cooldown = 0

    def mask_for(self, ram: bytes) -> int:
        p1 = _window(ram, mm.ADDR_P1_OBJECT, mm.OBJECT_SLOT_SIZE)
        cam_x = int.from_bytes(_window(ram, mm.ADDR_CAM_X, 2), "big")
        px, py = _s16(p1, 0x10), _s16(p1, 0x14)
        if self.side is None:
            self.side = -1 if px - cam_x < 0xA0 else 1
        wall = LEFT if self.side < 0 else RIGHT
        edge_x = cam_x + 0x20 if self.side < 0 else cam_x + 0x120
        if self.cooldown > 0:
            self.cooldown -= 1
            return 0
        action = p1[0x30] & 0xFE
        if abs(px - edge_x) > 2:
            return LEFT if edge_x < px else RIGHT
        twins = [slot for _, slot in twin_slots(ram) if slot[0x30] in (1, 2)]
        facing_left = bool(p1[0x09] & 0x02)
        facing_wall = facing_left == (self.side < 0)
        if not facing_wall:
            return wall
        best = None
        for slot in twins:
            tx, ty = _s16(slot, 0x10), _s16(slot, 0x14)
            behind = (tx - px) * (-self.side)
            if behind < 0:
                continue
            if best is None or behind < best[0]:
                best = (behind, ty)
        if best is None:
            return 0
        behind, ty = best
        if action in (0x02, 0x30) and behind <= self.chord_dx and abs(ty - py) <= 16:
            self.cooldown = 30
            return PUNCH | JUMP
        if self.lane_follow and abs(ty - py) > 4:
            return UP if ty < py else DOWN
        return 0


def reach_twins(client, loop, rom, scenario, *, seconds: float, settle_seconds: float) -> bool:
    from sor_autoplay.state import read_snapshot

    deadline = time.monotonic() + seconds
    last_report = 0.0
    seen_at: float | None = None
    while time.monotonic() < deadline:
        started = time.monotonic()
        snap = read_snapshot(client, rom=rom)
        playable = any(p.is_playable for p in snap.players)
        if scenario.level_jump_pending:
            if playable:
                scenario.apply_start_level(client)
            time.sleep(0.008)
            continue
        loop.tick(snap, player_index=1)
        if playable and snap.level_index == LEVEL - 1:
            scenario.sweep_other_families(client)
            entities = snap.world_map.entities if snap.world_map else ()
            twins = [e for e in entities if e.type_id == TWIN_TYPE and e.kind == "boss"]
            if len(twins) >= 2:
                seen_at = seen_at if seen_at is not None else started
                if started - seen_at >= settle_seconds:
                    return True
        if started - last_report > 10.0:
            last_report = started
            print(f"walking round {LEVEL}: level={snap.level_index}", flush=True)
        time.sleep(max(0.0, 0.008 - (time.monotonic() - started)))
    return False


class RecordingClient:
    """The two calls ``SharedGamepadState`` makes, captured instead of sent."""

    def __init__(self) -> None:
        self.held = 0
        self.press_mask = 0
        self.press_frames = 0

    def hold_buttons(self, *, player1: int = 0, player2: int = 0) -> None:
        self.held = int(player1)

    def press_buttons(self, *, player1: int = 0, player2: int = 0, frames: int = 1) -> None:
        self.press_mask = int(player1)
        self.press_frames = int(frames)

    def release_buttons(self) -> None:
        self.held = 0

    def next_frame_mask(self) -> int:
        if self.press_frames > 0:
            self.press_frames -= 1
            return self.press_mask
        return self.held


def record(args) -> int:
    from megadrive_remote import MegaDriveClient

    from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
    from sor_autoplay.ai.loop import AgentLoop
    from sor_autoplay.debug_scenario import DebugScenario
    from sor_autoplay.reach_gameplay import reach_gameplay
    from sor_autoplay.rom_data import RomData
    from sor_autoplay.state import snapshot_from_memory_blocks  # noqa: F401 -- engage below

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=LEVEL, kill_street_enemies=True)
    with MegaDriveClient(host=args.host, port=args.port) as client, open(
        args.out, "w", encoding="utf-8"
    ) as sink:
        rom = RomData.read(client)
        live_pad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        if not reach_twins(
            client,
            AgentLoop(live_pad, no_food=True, no_police=True),
            rom,
            scenario,
            seconds=args.reach_seconds,
            settle_seconds=args.settle_seconds,
        ):
            print("never reached the twins", flush=True)
            return 2
        live_pad.release()
        client.release_buttons()

        recorder = RecordingClient()
        loop = AgentLoop(
            VirtualGamepad(SharedGamepadState(recorder), player_index=1),
            no_food=True,
            no_police=True,
        )
        actor = None
        if args.actor == "wander":
            actor = Wander(args.seed)
        elif args.actor == "edge":
            actor = Edge(args.chord_dx, args.lane_follow)
        delayed: deque[int] = deque([0] * args.input_delay)
        client.set_lockstep(True, timeout_ms=10_000)
        frame = 0
        end = "frames"
        hits = 0
        last_hp = None
        try:
            ram = client.step_input(player1=0, held_frames=0, total_frames=1).work_ram
            for frame in range(args.frames):
                if frame % SWEEP_EVERY_FRAMES == 0:
                    scenario.sweep_other_families(client, force=True)
                if args.actor == "engage":
                    if frame % FRAMES_PER_TICK == 0 and recorder.press_frames == 0:
                        snap = _snapshot(ram, rom)
                        loop.tick(snap, player_index=1)
                    delayed.append(recorder.next_frame_mask())
                elif actor is not None:
                    delayed.append(actor.mask_for(ram))
                else:
                    delayed.append(0)
                mask = delayed.popleft()
                new_ram = client.step_input(
                    player1=mask, held_frames=1 if mask else 0, total_frames=1
                ).work_ram
                p1 = _window(new_ram, mm.ADDR_P1_OBJECT, mm.OBJECT_SLOT_SIZE)
                row = {
                    "f": frame,
                    "in": mask,
                    "cam": int.from_bytes(_window(new_ram, mm.ADDR_CAM_X, 2), "big"),
                    "p1": p1.hex(),
                    "tw": [[index, slot.hex()] for index, slot in twin_slots(new_ram)],
                }
                sink.write(json.dumps(row) + "\n")
                hp = _s16(p1, 0x32)
                if last_hp is not None and hp < last_hp:
                    hits += 1
                last_hp = hp
                ram = new_ram
                live = [slot for _, slot in twin_slots(ram) if _s16(slot, 0x32) > 0]
                if not live and frame > 10:
                    end = "both_dead"
                    break
                if new_ram[0xFFFF00 - WORK_RAM + 1] != 0x16 and frame > 10:
                    # game_state left gameplay (a game over, or the stage's end).
                    pass
        finally:
            client.set_lockstep(False)
            try:
                client.hold_buttons(player1=0, player2=0)
            except Exception:  # noqa: BLE001
                pass
        summary = {"end": end, "frames": frame + 1, "actor": args.actor, "hits": hits}
        sink.write(json.dumps({"summary": summary}) + "\n")
        print(json.dumps(summary), flush=True)
    return 0


def _snapshot(ram: bytes, rom):
    """``state.read_snapshot`` from a lockstep frame's work RAM."""

    from bongo_lab import snapshot_from_ram  # tools/ is on sys.path when run from there

    return snapshot_from_ram(ram, rom)


def check(args) -> int:
    from sor_autoplay.ai import twins as model

    rows = []
    with open(args.check, encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if "summary" in row:
                continue
            rows.append(row)
    report = model.check_recording(rows, verbose=args.verbose)
    print(json.dumps(report, indent=1, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--frames", type=int, default=3000, help="lockstep frames to play")
    ap.add_argument("--input-delay", type=int, default=0, help="frames of added input latency")
    ap.add_argument("--actor", choices=("engage", "wander", "edge", "stand"), default="engage")
    ap.add_argument("--chord-dx", type=int, default=56)
    ap.add_argument("--lane-follow", action="store_true")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--settle-seconds", type=float, default=0.5)
    ap.add_argument("--reach-seconds", type=float, default=400.0)
    ap.add_argument("--out")
    ap.add_argument("--check", help="replay a recording through the model instead")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if args.check:
        return check(args)
    if not args.out:
        ap.error("--out is required to record")
    return record(args)


if __name__ == "__main__":
    sys.exit(main())
