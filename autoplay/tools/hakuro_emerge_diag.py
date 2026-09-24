"""Trace HakuRo's rise from below the deck at round 5, wave 3.

**Reverse-engineering aid, not part of the AI.** Reproduces the user's
report (autoplay/CLAUDE.md, HakuRo section to follow): "No nível 5 há um bug
que a AI fica presa num inimigo que é detetado (e bem), mas está por debaixo
do chão do estágio (o estágio é num barco e o inimigo sai a saltar), a IA
fica presa a tentar dar murros no inimigo, mas este ainda não está
disponível" -- HakuRo (types ``$25``/``$2A``, ``ai/tokens/enemy.py``'s
``HakuRo(Grunt)``) jumps up from below the boat's deck at round 5's wave 3
(0-indexed, the 4th wave), and the AI's observation already sees the object
(it is in the table, targetable) before it is actually reachable.

Runs the **real** ``AgentLoop`` pipeline against a live host, the same shape
as ``tools/jack_fight.py``, while jumping to round 5 and keeping only the
HakuRo family alive (``DebugScenario(start_level=5, only_enemy="hakuro")``)
so wave 3 is reached quickly with nothing else confusing the trace. Every
tick with a live HakuRo on the object table logs its full raw geometry --
world X/Y and the **signed** high word of +$18 (world_z; the object table
stores the low word as fractional 16.16 below it, but only the high word is
an integer pixel offset and it can read negative while emerging, unlike
``world_map.fixed16_lane_y``'s unsigned read, which would wrap it to a large
positive number and hide exactly the signal this trace exists to find),
primary state/flags, health, animation and the winning ``Verb`` each tick --
so a punch or a walk aimed at a HakuRo that is not yet at floor level shows
up directly in the log.

**Mandatory stop conditions** (autoplay/CLAUDE.md, "do not run it, or any
tool that drives a live host, without a real stop condition"): stops the
instant ``level_index`` changes away from round 5 (checked every tick, not
only at the end), and a hard wall-clock backstop
(``--seconds``, default 90) regardless of what wave is reached. Once wave 3
has been seen, an independent shorter backstop (``--after-wave-seconds``,
default 40) ends the run once enough of it has been captured, so this does
not idle indefinitely on wave 3 either.

Run (host already up with ``--debugUtils``, ``--turbo 2 --silent``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/hakuro_emerge_diag.py --port 7777 --out /tmp/hakuro.jsonl
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

HAKURO_TYPES = (0x25, 0x2A)
LEVEL = 5  # round 5, the boat stage (1-based, for the host cheat)
LEVEL_INDEX = LEVEL - 1
TARGET_WAVE = 3  # 0-indexed, per the user's report
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


def hakuro_row(slot: str, b: bytes) -> dict:
    return {
        "slot": slot,
        "type": f"{b[0]:#04x}",
        "x": _s16(b, 0x10),
        "y": _s16(b, 0x14),
        # The signed high word at +$18: the integer pixel elevation. A
        # positive value here (z grows downward, hazards.py's convention) is
        # below the visible floor; 0 is on it.
        "z": _s16(b, 0x18),
        "z_fixed": _fx(b, 0x18),
        "state": _u8(b, 0x30),
        "flags31": _u8(b, 0x31),
        "hp": _s16(b, 0x32),
        "facing_left": bool(_u8(b, 0x09) & 0x02),
        "vx": _fx(b, 0x1C),
        "vlane": _fx(b, 0x20),
        "anim": _u16(b, 0x08),
        "anim_frame": _u8(b, 0x0A),
        "hidden": bool(_u8(b, 0x01) & 0x01),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--target-wave", type=int, default=TARGET_WAVE)
    ap.add_argument("--poll-ms", type=int, default=16)
    ap.add_argument(
        "--seconds", type=float, default=90.0, help="Hard wall-clock backstop, regardless of wave."
    )
    ap.add_argument(
        "--after-wave-seconds",
        type=float,
        default=40.0,
        help="Stop this long after the target wave is first seen.",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    poll_s = args.poll_ms / 1000.0

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=LEVEL, only_enemy="hakuro")

    end_state = "timeout"
    wave_reached_at: float | None = None
    rows_written = 0

    with MegaDriveClient(host=args.host, port=args.port) as client:
        rom = RomData.read(client)
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        loop = AgentLoop(gamepad, no_food=True, no_police=True)

        start_t = time.monotonic()
        deadline = start_t + args.seconds
        on_level = False
        last_wave = None
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

                # Mandatory: stop the instant we are off round 5, checked
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

                scenario.sweep_other_families(client)
                verb = loop.tick(snap, player_index=1)
                verb_name = type(verb).__name__ if verb else None
                target_slot = getattr(verb, "target_slot", None) if verb else None

                if snap.wave != last_wave:
                    print(f"t={t0 - start_t:.1f} wave -> {snap.wave}", flush=True)
                    last_wave = snap.wave
                if snap.wave == args.target_wave and wave_reached_at is None:
                    wave_reached_at = t0
                    print(f"t={t0 - start_t:.1f} reached target wave {args.target_wave}", flush=True)
                if snap.wave > args.target_wave:
                    end_state = "wave_advanced"
                    print(f"STOP: wave advanced past {args.target_wave} to {snap.wave}", flush=True)
                    break
                if wave_reached_at is not None and t0 - wave_reached_at > args.after_wave_seconds:
                    end_state = "captured_target_wave"
                    print("STOP: captured enough of the target wave", flush=True)
                    break

                table = client.read_memory(mm.ADDR_OBJECT_TABLE, SLOT_COUNT * mm.OBJECT_SLOT_SIZE)
                slots = {
                    f"obj{i:02d}": table[i * mm.OBJECT_SLOT_SIZE : (i + 1) * mm.OBJECT_SLOT_SIZE]
                    for i in range(SLOT_COUNT)
                }
                hakuro_rows = [
                    hakuro_row(name, b) for name, b in slots.items() if b[0] in HAKURO_TYPES
                ]

                if hakuro_rows or snap.wave == args.target_wave:
                    p1 = snap.players[0]
                    p1e = next(
                        (e for e in snap.world_map.entities if e.slot == "P1"), None
                    ) if snap.world_map else None
                    sink.write(
                        json.dumps(
                            {
                                "t": round(t0 - start_t, 3),
                                "wave": snap.wave,
                                "p1_hp": p1.health,
                                "p1": [p1e.world_x, p1e.world_y, p1e.world_z] if p1e else None,
                                "verb": verb_name,
                                "verb_target": target_slot,
                                "hakuro": hakuro_rows,
                            }
                        )
                        + "\n"
                    )
                    rows_written += 1

                if t0 - last_report > 10.0:
                    last_report = t0
                    print(
                        f"t={t0 - start_t:.1f} wave={snap.wave} hakuro={len(hakuro_rows)} "
                        f"verb={verb_name}->{target_slot}",
                        flush=True,
                    )
                time.sleep(max(0.0, poll_s - (time.monotonic() - t0)))

        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001
            pass

    print(f"end_state={end_state} rows_written={rows_written} out={args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
