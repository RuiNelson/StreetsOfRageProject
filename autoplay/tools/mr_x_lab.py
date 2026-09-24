"""Record, and check ``ai/mr_x.py`` against, Mr. X in lockstep.

The round-8 lockstep lab, in the shape of ``tools/twins_lab.py``. The real
``AgentLoop`` plays round 8 in real time with ``--kill-until-mr-x``'s sweep --
every enemy and every boss of the rush dies, until his scene (types
``$33``-``$35``) is up, and then nothing -- until Mr. X (type ``$35``) is
fighting (out of his entrance, primary 3 or later). On the way it writes a
``census`` row whenever the set of object types in the table changes, so a
recording shows when his Garcia helpers arrive against his office controller
and his own spawn. Then the host goes into lockstep and one of four actors
plays on, a frame at a time:

``engage``
    the real pipeline, ticked every two frames as live, its pad recorded and
    applied through ``step_input``;
``hold``
    a scripted hold loop -- walk into him on his lane, knee twice, release by
    holding back, walk straight back in -- for the hold's reads and whether
    his release can be re-grabbed;
``wander``
    a seeded walk that never attacks, to take him through his whole state
    machine (the walk-in, the lunge, the retreat, the machine gun);
``stand``
    nothing at all.

Every frame writes a row with the input, the camera and the **raw bytes** of
the player's object, of Mr. X's slot, of every bullet (``$36``) and of every
ordinary enemy (hex), so the model can be checked offline update by update
(``--check``). A recording is local analysis output: do not commit it.

Run (host already up with ``--debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/mr_x_lab.py --actor wander --out /tmp/mr_x.jsonl
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/mr_x_lab.py --check /tmp/mr_x.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import deque

from sor_autoplay import memory_map as mm

WORK_RAM = 0xFF0000
LEVEL = 8
MR_X_TYPE = 0x35
BULLET_TYPE = 0x36
SCENE_TYPES = frozenset({0x33, 0x34, 0x35})
FRAMES_PER_TICK = 2
# His entrance ($13E4C/$13E9E) ends in primary 3; from there he fights.
FIGHTING_FROM = 0x03
STEP_TIMEOUT_MS = 15_000

UP, DOWN, LEFT, RIGHT = 0x0001, 0x0002, 0x0004, 0x0008
PUNCH, JUMP = 0x0020, 0x0040  # physical B and C (A, 0x10, is the police)


def _window(ram: bytes, address: int, length: int) -> bytes:
    offset = address - WORK_RAM
    if offset < 0 or offset + length > len(ram):
        return b""
    return ram[offset : offset + length]


def _s16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big", signed=True)


def slots(ram: bytes, types) -> list[tuple[int, bytes]]:
    """Every object of one of ``types``: (slot index, its 128 bytes)."""

    found = []
    for index in range(mm.OBJECT_TABLE_SLOTS):
        address = mm.ADDR_OBJECT_TABLE + index * mm.OBJECT_SLOT_SIZE
        slot = _window(ram, address, mm.OBJECT_SLOT_SIZE)
        if slot and slot[0] in types:
            found.append((index, slot))
    return found


ORDINARY = frozenset(range(0x20, 0x2B))


def census(client) -> list[list[int]]:
    """(slot, type, primary) of every occupied slot, read live."""

    table = client.read_memory(mm.ADDR_OBJECT_TABLE, mm.OBJECT_TABLE_SLOTS * mm.OBJECT_SLOT_SIZE)
    out = []
    for index in range(mm.OBJECT_TABLE_SLOTS):
        slot = table[index * mm.OBJECT_SLOT_SIZE : (index + 1) * mm.OBJECT_SLOT_SIZE]
        if slot[0]:
            out.append([index, slot[0], slot[0x30]])
    return out


class Wander:
    """A seeded walk that never presses B or C; a hold it walks into is let go
    by holding back, so the fight keeps going and his AI keeps deciding."""

    DIRECTIONS = (0, UP, DOWN, LEFT, RIGHT, UP | LEFT, UP | RIGHT, DOWN | LEFT, DOWN | RIGHT)

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.left = 0
        self.mask = 0

    def mask_for(self, ram: bytes) -> int:
        p1 = _window(ram, mm.ADDR_P1_OBJECT, mm.OBJECT_SLOT_SIZE)
        if 0x60 <= (p1[0x30] & 0xFE) <= 0x6F:
            return RIGHT if p1[0x09] & 0x02 else LEFT
        if self.left <= 0:
            self.mask = self.rng.choice(self.DIRECTIONS)
            self.left = self.rng.randint(20, 60)
        self.left -= 1
        return self.mask


class HoldLoop:
    """Walk into him on his lane; in a front hold, B twice (each after the
    last knee has played out), then back until the hold drops, then straight
    back toward him -- the re-grab the plan would like to make."""

    def __init__(self, knees: int = 2) -> None:
        self.knees = knees
        self.done = 0
        self.wait = 0
        self.releasing = False

    def mask_for(self, ram: bytes) -> int:
        p1 = _window(ram, mm.ADDR_P1_OBJECT, mm.OBJECT_SLOT_SIZE)
        found = slots(ram, {MR_X_TYPE})
        if not found:
            return 0
        boss = found[0][1]
        px, py = _s16(p1, 0x10), _s16(p1, 0x14)
        bx, by = _s16(boss, 0x10), _s16(boss, 0x14)
        toward = RIGHT if bx > px else LEFT
        action = p1[0x30] & 0xFE
        reading = boss[0x30] == 0x0A and boss[0x5B] == 1  # $13598 reads +$7D
        if action == 0x60:  # the front hold, free to take a move
            if self.wait > 0:
                self.wait -= 1
                return 0
            if not reading and not self.releasing:
                return 0
            if self.done < self.knees and not self.releasing:
                self.done += 1
                self.wait = 4
                return PUNCH
            self.releasing = True
            return RIGHT if p1[0x09] & 0x02 else LEFT  # back: the release
        if 0x60 <= action <= 0x6F:
            return 0  # a knee or a crossover on its frames
        self.done = 0
        self.releasing = False
        lane = 0
        if by > py + 2:
            lane = DOWN
        elif by < py - 2:
            lane = UP
        return toward | lane


def reach_mr_x(client, loop, rom, scenario, sink, *, seconds: float, settle_seconds: float) -> bool:
    from sor_autoplay.state import read_snapshot

    deadline = time.monotonic() + seconds
    last_report = 0.0
    last_types: tuple | None = None
    seen_at: float | None = None
    started_at = time.monotonic()
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
        if snap.level_index == LEVEL - 1:
            scenario.note_snapshot(snap)
            if playable:
                scenario.sweep_other_families(client)
            table = census(client)
            types = tuple(sorted({t for _, t, _ in table}))
            if types != last_types:
                last_types = types
                sink.write(
                    json.dumps(
                        {
                            "census": round(started - started_at, 3),
                            "cam": snap.world_map.camera_x if snap.world_map else None,
                            "offer": snap.mr_x_offer_flag,
                            "objects": table,
                        }
                    )
                    + "\n"
                )
            mr_x = [s for s in table if s[1] == MR_X_TYPE]
            if mr_x and mr_x[0][2] >= FIGHTING_FROM:
                seen_at = seen_at if seen_at is not None else started
                if started - seen_at >= settle_seconds:
                    return True
        if started - last_report > 10.0:
            last_report = started
            p1 = snap.p1 if snap.players else None
            print(
                f"walking round {LEVEL}: level={snap.level_index} "
                f"x={getattr(p1, 'world_x', None)} hp={getattr(p1, 'health', None)} "
                f"lives={getattr(p1, 'lives', None)}",
                flush=True,
            )
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
    from megadrive_remote.exceptions import RemoteTimeoutError

    from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
    from sor_autoplay.ai.loop import AgentLoop
    from sor_autoplay.debug_scenario import DebugScenario
    from sor_autoplay.reach_gameplay import reach_gameplay
    from sor_autoplay.rom_data import RomData

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=LEVEL, kill_until_mr_x=True)
    with MegaDriveClient(host=args.host, port=args.port) as client, open(
        args.out, "w", encoding="utf-8"
    ) as sink:
        rom = RomData.read(client)
        live_pad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        if not reach_mr_x(
            client,
            AgentLoop(live_pad, no_food=True, no_police=True),
            rom,
            scenario,
            sink,
            seconds=args.reach_seconds,
            settle_seconds=args.settle_seconds,
        ):
            print("never reached Mr. X", flush=True)
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
        elif args.actor == "hold":
            actor = HoldLoop(args.knees)
        delayed: deque[int] = deque([0] * args.input_delay)
        client.set_lockstep(True, timeout_ms=10_000)
        frame = 0
        end = "frames"
        hits = 0
        last_hp = None
        try:
            ram = client.step_input(
                player1=0, held_frames=0, total_frames=1, timeout_ms=STEP_TIMEOUT_MS
            ).work_ram
            for frame in range(args.frames):
                if args.actor == "engage":
                    if frame % FRAMES_PER_TICK == 0 and recorder.press_frames == 0:
                        loop.tick(_snapshot(ram, rom), player_index=1)
                    delayed.append(recorder.next_frame_mask())
                elif actor is not None:
                    delayed.append(actor.mask_for(ram))
                else:
                    delayed.append(0)
                mask = delayed.popleft()
                try:
                    new_ram = client.step_input(
                        player1=mask,
                        held_frames=1 if mask else 0,
                        total_frames=1,
                        timeout_ms=STEP_TIMEOUT_MS,
                    ).work_ram
                except RemoteTimeoutError:
                    end = "host_timeout"
                    break
                p1 = _window(new_ram, mm.ADDR_P1_OBJECT, mm.OBJECT_SLOT_SIZE)
                row = {
                    "f": frame,
                    "in": mask,
                    "cam": int.from_bytes(_window(new_ram, mm.ADDR_CAM_X, 2), "big"),
                    "p1": p1.hex(),
                    "mx": [[i, s.hex()] for i, s in slots(new_ram, {MR_X_TYPE})],
                    "bu": [[i, s.hex()] for i, s in slots(new_ram, {BULLET_TYPE})],
                    "en": [[i, s.hex()] for i, s in slots(new_ram, ORDINARY)],
                }
                sink.write(json.dumps(row) + "\n")
                hp = _s16(p1, 0x32)
                if last_hp is not None and hp < last_hp:
                    hits += 1
                last_hp = hp
                ram = new_ram
                boss = slots(ram, {MR_X_TYPE})
                if not boss and frame > 10:
                    end = "gone"
                    break
                if boss and boss[0][1][0x30] == 0x0E:
                    end = "dying"
                    break
        finally:
            try:
                client.set_lockstep(False)
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
    from sor_autoplay.ai import mr_x as model

    rows = []
    with open(args.check, encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if "summary" in row or "census" in row:
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
    ap.add_argument("--actor", choices=("engage", "hold", "wander", "stand"), default="engage")
    ap.add_argument("--knees", type=int, default=2, help="with --actor hold: knees before the release")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--settle-seconds", type=float, default=0.5)
    ap.add_argument("--reach-seconds", type=float, default=1500.0)
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
