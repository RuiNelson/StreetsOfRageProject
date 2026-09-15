"""Trace a round's stage walk tick by tick, for stalls with nothing on screen.

The real ``AgentLoop`` walks the round (``--level``) with a
``DebugScenario`` sweep, and every tick on the level logs what a stall is
made of: the actor's position, height, action and velocities, the mask the
pad actually holds, the winning verb and whether its route arrived, the
camera and its scroll bounds (``$FFE01A`` max, ``$FFE01E`` min), the
collision class under the actor, the pits the observer built, the round
clock, the time-over byte (``$FFFA49``) and a census of every live object
slot. The level's collision class map -- the lane band's rows only -- is
written as its own row whenever it changes: right after the level jump the
buffer can still hold the previous round's, and after that the ground does
not change, so a stall can be read off it offline.

Written for round 6's stall at X 2557 and the life lost at X 2474
(``autoplay/CLAUDE.md``, **Round 6: the factory floor**).

Run (host already up with ``--debugUtils``, e.g.
``./scripts/run --turbo 4 --lang en --debugUtils --port 7777 --silent``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/stage_walk_diag.py --level 6 --only-enemy jack --out /tmp/walk6.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from megadrive_remote import MegaDriveClient

from sor_autoplay import memory_map as mm
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.hazards import collision_class_at
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot

SLOT_COUNT = mm.OBJECT_TABLE_SLOTS
# Offsets inside the camera block read_snapshot already fetches ($FFE000).
CAMERA_X_MAX = 0x1A
CAMERA_X_MIN = 0x1E
# Rows of the class map worth dumping: row = lane >> 3, and no round's lane
# band reaches past $A0. No more: a round-6 row is 336 bytes, and 24 of them
# from $FFA000 run into the player objects at $FFB800.
COLLISION_ROWS = 0x15
ROUND_BOSS_TYPES = frozenset({0x30, 0x35, 0x55, 0x56, 0x57, 0x58})
# Effects and controllers that are never in anyone's way.
CENSUS_SKIP_TYPES = frozenset({0x00, 0x29, 0x48, 0x49, 0x4A, 0x54})


def _s16(b: bytes, o: int) -> int:
    return int.from_bytes(b[o : o + 2], "big", signed=True)


def _fx(b: bytes, o: int) -> float:
    return round(int.from_bytes(b[o : o + 4], "big", signed=True) / 65536.0, 4)


def census(table: bytes) -> list[list[int]]:
    rows = []
    for i in range(SLOT_COUNT):
        b = table[i * mm.OBJECT_SLOT_SIZE : (i + 1) * mm.OBJECT_SLOT_SIZE]
        type_id = b[0] & 0x7F
        if type_id in CENSUS_SKIP_TYPES:
            continue
        # [slot, type, state, x, lane, z, health, attack box, body box]
        rows.append([i, type_id, b[0x30], _s16(b, 0x10), _s16(b, 0x14), _s16(b, 0x18), _s16(b, 0x32), b[2], b[3]])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--level", type=int, default=6, help="1-based, for the host cheat")
    ap.add_argument("--seconds", type=float, default=240.0)
    ap.add_argument("--poll-ms", type=int, default=8)
    ap.add_argument("--character", default="blaze")
    sweep = ap.add_mutually_exclusive_group()
    sweep.add_argument("--only-enemy", help="keep this family, sweep the rest (jack_fight.py: jack)")
    sweep.add_argument("--kill-street-enemies", action="store_true", help="sweep every family")
    ap.add_argument("--until-x", type=int, help="stop once the actor's X passes this")
    ap.add_argument(
        "--stop-at-boss",
        action="store_true",
        help="stop when a round boss appears (round 6 meets Bongo mid-round, so off by default)",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    poll_s = args.poll_ms / 1000.0
    level_index = args.level - 1

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(
        start_level=args.level,
        only_enemy=args.only_enemy,
        kill_street_enemies=args.kill_street_enemies,
    )

    with MegaDriveClient(host=args.host, port=args.port) as client:
        rom = RomData.read(client)
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        loop = AgentLoop(gamepad, no_food=True, no_police=True)

        on_level = False
        started_at = None
        end_state = "timeout"
        prev_lives = prev_hp = None
        dumped_map = b""
        last_report = 0.0
        deadline = time.monotonic() + args.seconds

        with open(args.out, "w", encoding="utf-8") as sink:
            while time.monotonic() < deadline:
                t0 = time.monotonic()
                snap = read_snapshot(client, rom=rom)
                playable = any(p.is_playable for p in snap.players)
                if scenario.level_jump_pending:
                    if playable:
                        scenario.apply_start_level(client)
                    time.sleep(poll_s)
                    continue

                verb = loop.tick(snap, player_index=1)
                if not playable or snap.level_index != level_index:
                    if on_level and snap.level_index != level_index:
                        end_state = "level_change"
                        break
                    if on_level and not playable and snap.players[0].lives == 0:
                        end_state = "game_over"
                        break
                    time.sleep(max(0.0, poll_s - (time.monotonic() - t0)))
                    continue
                if not on_level:
                    on_level = True
                    started_at = t0
                    print(f"on level {args.level}", flush=True)
                scenario.sweep_other_families(client)
                elapsed = t0 - started_at

                p1raw = client.read_memory(mm.ADDR_P1_OBJECT, mm.OBJECT_SLOT_SIZE)
                table = client.read_memory(mm.ADDR_OBJECT_TABLE, SLOT_COUNT * mm.OBJECT_SLOT_SIZE)
                camera = client.read_memory(mm.ADDR_PRIMARY_CAMERA, 0x20)
                clock_bcd = client.read_memory(mm.ADDR_GAME_TIMER, 2)[1]
                time_over = client.read_memory(mm.ADDR_TIME_OVER_SEQUENCE, 1)[0]
                stride = int.from_bytes(client.read_memory(mm.ADDR_PRIMARY_BLOCKMAP_STRIDE, 2), "big")
                cmap = client.read_memory(mm.ADDR_LEVEL_COLLISION_CLASS_MAP, stride * COLLISION_ROWS) if stride else b""
                if cmap and cmap != dumped_map:
                    dumped_map = cmap
                    sink.write(
                        json.dumps({"t": None, "at": round(elapsed, 3), "collision_map": cmap.hex(), "stride": stride})
                        + "\n"
                    )

                x, y, z = _s16(p1raw, 0x10), _s16(p1raw, 0x14), _s16(p1raw, 0x18)
                p1 = snap.players[0]
                state = loop.verb_state()
                route = state.route
                row = {
                    "t": round(elapsed, 3),
                    "clock": (clock_bcd >> 4) * 10 + (clock_bcd & 0x0F),
                    "time_over": time_over,
                    "hp": p1.health,
                    "lives": p1.lives,
                    "p1": [x, y, z, p1raw[0x30], bool(p1raw[0x09] & 0x02)],
                    "v": [_fx(p1raw, 0x1C), _fx(p1raw, 0x20), _fx(p1raw, 0x24)],
                    "attacker": _s16(p1raw, 0x7E) & 0xFFFF,
                    "held": gamepad.held,
                    "verb": type(verb).__name__ if verb else None,
                    "pending": sorted({type(v).__name__ for v in state.pending}),
                    "route": None
                    if route is None
                    else [route.reached, route.steps[0].direction.name if route.steps else None],
                    "cam": [snap.world_map.camera_x, _s16(camera, CAMERA_X_MIN), _s16(camera, CAMERA_X_MAX)],
                    "class": collision_class_at(cmap, stride=stride, world_x=x, lane_y=y),
                    "pits": [
                        [h.world_x, h.lane_y, h.width, h.height]
                        for h in snap.floor_holes
                        if abs(h.world_x - x) < 400
                    ],
                    "walls": [
                        [w.world_x, w.lane_y, w.width, w.height]
                        for w in snap.floor_barriers
                        if abs(w.world_x - x) < 400
                    ],
                    "objs": census(table),
                }
                if prev_lives is not None and p1.lives is not None and p1.lives < prev_lives:
                    row["life_lost"] = True
                if prev_hp is not None and p1.health is not None and p1.health < prev_hp:
                    row["hurt"] = prev_hp - p1.health
                sink.write(json.dumps(row) + "\n")
                if row.get("life_lost") or row.get("hurt"):
                    print(f"t={elapsed:.1f} x={x} y={y} hurt={row.get('hurt')} life_lost={row.get('life_lost', False)} "
                          f"attacker={row['attacker']:#06x} time_over={time_over} verb={row['verb']}", flush=True)
                prev_lives, prev_hp = p1.lives, p1.health

                if args.until_x is not None and x >= args.until_x:
                    end_state = "until_x"
                    break
                boss = next(
                    (e for e in snap.world_map.entities if e.kind == "boss" and e.type_id in ROUND_BOSS_TYPES),
                    None,
                )
                if boss is not None and args.stop_at_boss:
                    end_state = f"boss_{boss.type_id:02X}"
                    break
                if t0 - last_report > 5.0:
                    last_report = t0
                    print(f"t={elapsed:.1f} x={x} y={y} z={z} hp={p1.health} lives={p1.lives} "
                          f"cam={row['cam']} class={row['class']} held={gamepad.held:#x} verb={row['verb']}",
                          flush=True)
                time.sleep(max(0.0, poll_s - (time.monotonic() - t0)))

        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001
            pass

    print(json.dumps({"end_state": end_state, "seconds": round(time.monotonic() - started_at, 1) if started_at else None}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
