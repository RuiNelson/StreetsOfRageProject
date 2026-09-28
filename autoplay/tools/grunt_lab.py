"""Record, and check ``ai/grunt.py`` against, the street enemies in lockstep.

``mr_x_lab.py``'s shape for the ordinary families. The real ``AgentLoop``
plays a round in real time with ``DebugScenario(only_enemy=FAMILY)`` keeping
every other family swept, until an enemy of the kept family is fighting on
screen; then the host goes into lockstep and one of three actors plays on, a
frame at a time:

``engage``
    the real pipeline, ticked every two frames as live, its pad recorded and
    applied through ``step_input``;
``wander``
    a seeded walk that never attacks (a hold it walks into is let go by
    holding back), to take the enemies through their whole state machines;
``stand``
    nothing at all.

The other families are swept every 30 frames (lockstep stops the timed
sweep). Every frame writes a row with the input, the camera, the round and
the **raw bytes** of the player's object and of every ordinary enemy and
weapon (hex), so the model can be checked offline update by update
(``--check``). With no kept enemy alive for ``--idle-frames`` the host goes
back to real time and the pipeline walks on to the next wave (``--waves``).
A recording is local analysis output: do not commit it.

Run (host already up with ``--debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/grunt_lab.py --family garcia --level 1 --actor wander --out /tmp/garcia.jsonl
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/grunt_lab.py --check /tmp/garcia.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque

from sor_autoplay import memory_map as mm

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from mr_x_lab import RecordingClient, Wander, _window  # noqa: E402

FAMILY_TYPES = {
    "garcia": frozenset({0x20, 0x21, 0x22, 0x23}),
    "signal": frozenset({0x24}),
    "hakuro": frozenset({0x25, 0x2A}),
    "nora": frozenset({0x26}),
}
ORDINARY = frozenset(range(0x20, 0x2B))
WEAPONS = frozenset({0x08, 0x09, 0x0A, 0x0B, 0x0C})
FRAMES_PER_TICK = 2
STEP_TIMEOUT_MS = 15_000
SWEEP_EVERY = 30


def objects(ram: bytes, types) -> list[tuple[int, bytes]]:
    found = []
    for index in range(mm.OBJECT_TABLE_SLOTS):
        slot = _window(ram, mm.ADDR_OBJECT_TABLE + index * mm.OBJECT_SLOT_SIZE, mm.OBJECT_SLOT_SIZE)
        if slot and (slot[0] & 0x7F) in types:
            found.append((index, slot))
    return found


def fighting(ram: bytes, kept) -> bool:
    for _, slot in objects(ram, kept):
        hp = int.from_bytes(slot[0x32:0x34], "big", signed=True)
        screen_x = int.from_bytes(slot[0x28:0x2A], "big", signed=True)
        if slot[0x30] not in (0x00, 0x06) and hp >= 0 and 0x80 <= screen_x < 0x1C0:
            return True
    return False


def record(args) -> int:
    from megadrive_remote import MegaDriveClient
    from megadrive_remote.exceptions import RemoteTimeoutError

    from bongo_lab import snapshot_from_ram
    from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
    from sor_autoplay.ai.loop import AgentLoop
    from sor_autoplay.debug_scenario import DebugScenario
    from sor_autoplay.reach_gameplay import reach_gameplay
    from sor_autoplay.rom_data import RomData
    from sor_autoplay.state import read_snapshot

    kept = FAMILY_TYPES[args.family]
    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=args.level, only_enemy=args.family)
    total_frames = 0
    hits = 0
    with MegaDriveClient(host=args.host, port=args.port) as client, open(
        args.out, "w", encoding="utf-8"
    ) as sink:
        rom = RomData.read(client)
        live_pad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        live_loop = AgentLoop(live_pad, no_food=True, no_police=True)
        deadline = time.monotonic() + args.seconds
        for wave in range(args.waves):
            # Real time until the kept family fights on screen.
            reached = False
            while time.monotonic() < deadline:
                t0 = time.monotonic()
                snap = read_snapshot(client, rom=rom)
                playable = any(p.is_playable for p in snap.players)
                if scenario.level_jump_pending:
                    if playable:
                        scenario.apply_start_level(client)
                    time.sleep(0.008)
                    continue
                live_loop.tick(snap, player_index=1)
                if playable and snap.level_index == args.level - 1:
                    scenario.sweep_other_families(client)
                    ram = client.read_memory(mm.ADDR_OBJECT_TABLE, mm.OBJECT_TABLE_SLOTS * mm.OBJECT_SLOT_SIZE)
                    padded = bytes(mm.ADDR_OBJECT_TABLE - 0xFF0000) + ram
                    if fighting(padded, kept):
                        reached = True
                        break
                time.sleep(max(0.0, 0.008 - (time.monotonic() - t0)))
            if not reached:
                print("never reached a fight", flush=True)
                break
            live_pad.release()
            client.release_buttons()

            recorder = RecordingClient()
            loop = AgentLoop(VirtualGamepad(SharedGamepadState(recorder), player_index=1), no_food=True, no_police=True)
            actor = Wander(args.seed + wave) if args.actor == "wander" else None
            delayed: deque[int] = deque([0] * args.input_delay)
            client.set_lockstep(True, timeout_ms=10_000)
            idle = 0
            last_hp = None
            end = "frames"
            try:
                ram = client.step_input(player1=0, held_frames=0, total_frames=1, timeout_ms=STEP_TIMEOUT_MS).work_ram
                for frame in range(args.frames):
                    if frame % SWEEP_EVERY == 0:
                        scenario.sweep_other_families(client, force=True)
                    if args.actor == "engage":
                        if frame % FRAMES_PER_TICK == 0 and recorder.press_frames == 0:
                            loop.tick(snapshot_from_ram(ram, rom), player_index=1)
                        delayed.append(recorder.next_frame_mask())
                    elif actor is not None:
                        delayed.append(actor.mask_for(ram))
                    else:
                        delayed.append(0)
                    mask = delayed.popleft()
                    try:
                        new_ram = client.step_input(
                            player1=mask, held_frames=1 if mask else 0, total_frames=1, timeout_ms=STEP_TIMEOUT_MS
                        ).work_ram
                    except RemoteTimeoutError:
                        end = "host_timeout"
                        break
                    p1 = _window(new_ram, mm.ADDR_P1_OBJECT, mm.OBJECT_SLOT_SIZE)
                    level = int.from_bytes(_window(new_ram, mm.ADDR_LEVEL, 2), "big")
                    row = {
                        "f": total_frames,
                        "wave": wave,
                        "in": mask,
                        "cam": int.from_bytes(_window(new_ram, mm.ADDR_CAM_X, 2), "big"),
                        "level": level,
                        "p1": p1.hex(),
                        "en": [[i, s.hex()] for i, s in objects(new_ram, ORDINARY | WEAPONS)],
                    }
                    sink.write(json.dumps(row) + "\n")
                    total_frames += 1
                    hp = int.from_bytes(p1[0x32:0x34], "big", signed=True)
                    if last_hp is not None and hp < last_hp:
                        hits += 1
                    last_hp = hp
                    ram = new_ram
                    if level != args.level - 1:
                        end = "level_change"
                        break
                    if fighting(ram, kept) or any(
                        s[0x30] not in (0x00, 0x06) for _, s in objects(ram, kept)
                    ):
                        idle = 0
                    else:
                        idle += 1
                        if idle >= args.idle_frames:
                            end = "idle"
                            break
            finally:
                try:
                    client.set_lockstep(False)
                    client.hold_buttons(player1=0, player2=0)
                except Exception:  # noqa: BLE001
                    pass
            print(json.dumps({"wave": wave, "end": end, "frames": total_frames, "hits": hits}), flush=True)
            if end not in ("idle", "frames"):
                break
        summary = {"frames": total_frames, "actor": args.actor, "family": args.family, "hits": hits}
        sink.write(json.dumps({"summary": summary}) + "\n")
        print(json.dumps(summary), flush=True)
    return 0


def check(args) -> int:
    from sor_autoplay.ai import grunt

    rows = []
    with open(args.check, encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if "summary" in row:
                continue
            rows.append(row)
    report = grunt.check_recording(rows, verbose=args.verbose)
    print(json.dumps(report, indent=1, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--family", choices=sorted(FAMILY_TYPES), default="garcia")
    ap.add_argument("--level", type=int, default=1)
    ap.add_argument("--frames", type=int, default=3000, help="lockstep frames per wave")
    ap.add_argument("--waves", type=int, default=3)
    ap.add_argument("--idle-frames", type=int, default=240)
    ap.add_argument("--seconds", type=float, default=600.0)
    ap.add_argument("--input-delay", type=int, default=0)
    ap.add_argument("--actor", choices=("engage", "wander", "stand"), default="wander")
    ap.add_argument("--seed", type=int, default=1)
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
