"""Trace round 8's thrown tables (object type ``$45``) from a live host.

**Reverse-engineering aid, not part of the AI.** Reproduces the user's report
(autoplay/CLAUDE.md, "Round 8's thrown tables"): "No nivel 8, de vez em
quando o jogo atira umas mesas contra o jogador ... as mesas do nivel 8
tambem sao um 'breakable'" -- the office occasionally throws a table
(furniture) at the player, right at the start of the level. Static
disassembly of the object-type-$45 dispatcher (``sor.asm`` $7534, state table
at $7540) found: a 3-state machine (state 0 $7546 camera-gated arm/idle,
state 1 $75E6 flight + hit check via ``sub_00007392``, state 2 $75EE
gravity/bounce after a punch knocks it away), a per-variant (+$40) launch
velocity table at $75DC (only ~5-6 px/frame, entries 1-4: +5, +6, -5, -6),
and a hit-response in ``sub_00007392`` that explicitly special-cases type
$45 (``cmpi.b #$0045, $0(a0)``) for a stronger vertical recoil when punched
while its variant is nonzero. That reading left the actual spawn trigger and
real flight speed unconfirmed from static analysis alone (state 0 never
visibly advances +$30 in the disassembly, so whether the object is spawned
already airborne or arms itself over several ticks needed live confirmation)
-- this script gets the real numbers by polling the raw object table through
round 8's opening.

Runs the real ``AgentLoop`` pipeline against a live host, the same shape as
``tools/hakuro_emerge_diag.py``, jumping straight to round 8
(``DebugScenario(start_level=8)``, no family sweep -- the user says the
tables are thrown right at the start, so the boss-rush sweep tooling
(``--kill-until-mr-x``, ``scripts/go_to_boss_8``) is not needed here). Every
tick with a live type-$45 object on the table logs its full raw geometry --
world X/Y/Z, the velocity fields (+$1C/+$20/+$24, all signed 16.16 fixed),
primary state (+$30), fine flags (+$31/+$3A), health, and the spawn/variant
byte (+$40) -- plus the player's own position and the AI's current verb, so
a hit taken from an unrecognised table shows up directly in the log.

**Mandatory stop conditions** (autoplay/CLAUDE.md, "do not run it, or any
tool that drives a live host, without a real stop condition"): stops the
instant ``level_index`` changes away from round 8 (checked every tick), a
hard wall-clock backstop (``--seconds``, default 75) regardless of what is
observed, and an independent shorter backstop (``--after-seen-seconds``,
default 30) once at least one type-$45 object has been seen, so this does
not idle indefinitely once the opening throw has been captured.

Run (host already up with ``--debugUtils``, ``--turbo 2 --silent``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/table_throw_diag.py --port 7777 --out /tmp/table_throw.jsonl
"""

from __future__ import annotations

import argparse
import json
import time

from megadrive_remote import MegaDriveClient

from sor_autoplay import memory_map as mm
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot

TABLE_TYPE = 0x45
LEVEL = 8  # round 8 (1-based, for the host cheat)
LEVEL_INDEX = LEVEL - 1
SLOT_COUNT = 66


def _s16(b: bytes, o: int) -> int:
    return int.from_bytes(b[o : o + 2], "big", signed=True)


def _u16(b: bytes, o: int) -> int:
    return int.from_bytes(b[o : o + 2], "big")


def _u8(b: bytes, o: int) -> int:
    return b[o]


def _fx(b: bytes, o: int) -> float:
    raw = int.from_bytes(b[o : o + 4], "big")
    if raw >= 0x8000_0000:
        raw -= 0x1_0000_0000
    return round(raw / 65536.0, 4)


def table_row(slot: str, b: bytes) -> dict:
    return {
        "slot": slot,
        "type": f"{b[0]:#04x}",
        "x": _s16(b, 0x10),
        "y": _s16(b, 0x14),
        "z": _s16(b, 0x18),
        "vel_x": _fx(b, 0x1C),
        "vel_lane": _fx(b, 0x20),
        "vel_z": _fx(b, 0x24),
        "state": _u8(b, 0x30),
        "flags31": _u8(b, 0x31),
        "hp": _s16(b, 0x32),
        "variant40": _u8(b, 0x40),
        "byte41": _u8(b, 0x41),
        "flags01": _u8(b, 0x01),
        "flags3a": _u8(b, 0x3A),
        "facing_left": bool(_u8(b, 0x09) & 0x02),
        "anim": _u16(b, 0x08),
        "anim_frame": _u8(b, 0x0A),
        "hidden": bool(_u8(b, 0x01) & 0x01),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--poll-ms", type=int, default=16)
    ap.add_argument(
        "--seconds", type=float, default=75.0, help="Hard wall-clock backstop, regardless of sightings."
    )
    ap.add_argument(
        "--after-seen-seconds",
        type=float,
        default=30.0,
        help="Stop this long after the first type-$45 sighting.",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    poll_s = args.poll_ms / 1000.0

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=LEVEL)

    end_state = "timeout"
    first_seen_at: float | None = None
    rows_written = 0
    max_seen_slots = 0

    with MegaDriveClient(host=args.host, port=args.port) as client:
        rom = RomData.read(client)
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        loop = AgentLoop(gamepad, no_food=True, no_police=True)

        start_t = time.monotonic()
        deadline = start_t + args.seconds
        on_level = False
        last_report = 0.0

        with open(args.out, "w", encoding="utf-8") as sink:
            while True:
                t0 = time.monotonic()
                if t0 >= deadline:
                    end_state = "timeout"
                    print("STOP: wall-clock backstop reached", flush=True)
                    break

                snap = read_snapshot(client, rom=rom)
                playable = any(p.is_playable for p in snap.players)

                if scenario.level_jump_pending:
                    if playable:
                        scenario.apply_start_level(client)
                    time.sleep(poll_s)
                    continue

                # Mandatory: stop the instant we are off round 8, checked
                # every tick, not only once at the end.
                if on_level and (not playable or snap.level_index != LEVEL_INDEX):
                    end_state = "level_changed"
                    print(
                        f"STOP: level_index={snap.level_index} (wanted {LEVEL_INDEX}), "
                        f"playable={playable}",
                        flush=True,
                    )
                    break
                if not playable:
                    time.sleep(max(0.0, poll_s - (time.monotonic() - t0)))
                    continue
                if not on_level:
                    on_level = True
                    print(f"on level {LEVEL}", flush=True)

                verb = loop.tick(snap, player_index=1)
                verb_name = type(verb).__name__ if verb else None
                target_slot = getattr(verb, "target_slot", None) if verb else None

                table = client.read_memory(mm.ADDR_OBJECT_TABLE, SLOT_COUNT * mm.OBJECT_SLOT_SIZE)
                slots = {
                    f"obj{i:02d}": table[i * mm.OBJECT_SLOT_SIZE : (i + 1) * mm.OBJECT_SLOT_SIZE]
                    for i in range(SLOT_COUNT)
                }
                table_rows = [
                    table_row(name, b) for name, b in slots.items() if b[0] == TABLE_TYPE
                ]

                if table_rows and first_seen_at is None:
                    first_seen_at = t0
                    print(f"t={t0 - start_t:.1f} first type-$45 sighting", flush=True)
                max_seen_slots = max(max_seen_slots, len(table_rows))

                if first_seen_at is not None and t0 - first_seen_at > args.after_seen_seconds:
                    end_state = "captured_enough"
                    print("STOP: captured enough after first sighting", flush=True)
                    break

                if table_rows:
                    p1 = snap.players[0]
                    p1e = next(
                        (e for e in snap.world_map.entities if e.slot == "P1"), None
                    ) if snap.world_map else None
                    sink.write(
                        json.dumps(
                            {
                                "t": round(t0 - start_t, 3),
                                "p1_hp": p1.health,
                                "p1": [p1e.world_x, p1e.world_y, p1e.world_z] if p1e else None,
                                "cam_x": snap.world_map.camera_left if snap.world_map else None,
                                "verb": verb_name,
                                "verb_target": target_slot,
                                "tables": table_rows,
                            }
                        )
                        + "\n"
                    )
                    rows_written += 1

                if t0 - last_report > 10.0:
                    last_report = t0
                    print(
                        f"t={t0 - start_t:.1f} tables={len(table_rows)} "
                        f"verb={verb_name}->{target_slot}",
                        flush=True,
                    )
                time.sleep(max(0.0, poll_s - (time.monotonic() - t0)))

        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001
            pass

    print(
        f"end_state={end_state} rows_written={rows_written} max_seen_slots={max_seen_slots} "
        f"out={args.out}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
