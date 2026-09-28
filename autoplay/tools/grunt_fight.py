"""Play a round with one ordinary family kept, and score every encounter.

``jack_fight.py``'s shape for the street families: the real ``AgentLoop``
walks the round through ``ai/gamepad.py`` and nothing else, while
``DebugScenario(only_enemy=FAMILY)`` keeps every other ordinary family swept
-- so each wave leaves the kept family alone on screen with the actor, which
is the question: how does the AI fight *them*. ``--family all`` sweeps
nothing and scores every ordinary enemy (the mixed waves as the round plays
them).

A hit is attributed through the player's own ``+$7E`` -- the object
``$AA22`` names as the attacker -- to the enemy (its type, primary state,
animation, frame and latched boxes, and the weapon it carries) or to a
weapon object (its type, ``+$51`` and its holder, ``+$52``). The previous
tick's slots stand in when the attacker has already removed itself.

A loss with no attacker within 15 s of a time-over (``$FFFA49``) is filed as
``round_clock`` (``jack_fight.py``). The run ends when a round's boss appears
(``--through-bosses`` plays on), the level changes, the game is over, or
``--seconds`` runs out.

Run (host already up with ``--debugUtils``, e.g.
``./scripts/run --turbo 2 --lang en --debugUtils --port 7777 --silent``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/grunt_fight.py --family garcia --level 1 --out /tmp/garcia.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, deque

from megadrive_remote import MegaDriveClient

from sor_autoplay import memory_map as mm
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot

FAMILY_TYPES: dict[str, frozenset[int]] = {
    "garcia": frozenset({0x20, 0x21, 0x22, 0x23}),
    "signal": frozenset({0x24}),
    "hakuro": frozenset({0x25, 0x2A}),
    "nora": frozenset({0x26}),
    "jack": frozenset({0x27}),
}
ORDINARY_TYPES = frozenset().union(*FAMILY_TYPES.values())
WEAPON_TYPES = frozenset({0x08, 0x09, 0x0A, 0x0B, 0x0C})
WEAPON_NAMES = {0x08: "knife", 0x09: "bottle", 0x0A: "bat", 0x0B: "pipe", 0x0C: "pepper"}
ROUND_BOSS_TYPES = frozenset({0x30, 0x35, 0x55, 0x56, 0x57, 0x58})
SLOT_COUNT = 66
HIT_HISTORY_TICKS = 30
TIME_OVER_WINDOW_S = 15.0


def _u8(b: bytes, o: int) -> int:
    return b[o]


def _u16(b: bytes, o: int) -> int:
    return int.from_bytes(b[o : o + 2], "big")


def _s16(b: bytes, o: int) -> int:
    return int.from_bytes(b[o : o + 2], "big", signed=True)


def _fx(b: bytes, o: int) -> float:
    return round(int.from_bytes(b[o : o + 4], "big", signed=True) / 65536.0, 4)


def family_of(type_id: int) -> str | None:
    for name, types in FAMILY_TYPES.items():
        if type_id in types:
            return name
    return None


def slot_for_ptr(ptr: int) -> str | None:
    low = ptr & 0xFFFF
    if 0xB800 <= low < 0xB880:
        return "P1"
    if 0xB880 <= low < 0xB900:
        return "P2"
    if low >= 0xB900:
        index = (low - 0xB900) // mm.OBJECT_SLOT_SIZE
        if index < SLOT_COUNT:
            return f"obj{index:02d}"
    return None


def enemy_row(slot: str, b: bytes, weapons: dict[str, dict]) -> dict:
    held = weapons.get(slot)
    return {
        "slot": slot,
        "type": _u8(b, 0x00),
        "x": _s16(b, 0x10),
        "y": _s16(b, 0x14),
        "z": _s16(b, 0x18),
        "state": _u8(b, 0x30),
        "sub": _u8(b, 0x31),
        "hp": _s16(b, 0x32),
        "dmg": _u8(b, 0x34),
        "left": bool(_u8(b, 0x09) & 0x02),
        "vx": _fx(b, 0x1C),
        "vy": _fx(b, 0x20),
        "vz": _fx(b, 0x24),
        "p40": _u8(b, 0x40),
        "p41": _u8(b, 0x41),
        "target": slot_for_ptr(_u16(b, 0x42)),
        "aim": [_s16(b, 0x60), _s16(b, 0x62), _u16(b, 0x64)],
        "anim": _u16(b, 0x08),
        "frame": _u8(b, 0x0A),
        "cd": _u8(b, 0x0D),
        "t50": _u8(b, 0x50),
        "t51": _u8(b, 0x51),
        "f4a": [_u8(b, 0x48), _u8(b, 0x49), _u8(b, 0x4A), _u8(b, 0x4B)],
        "f6a": _u16(b, 0x6A),
        "f6e": _u8(b, 0x6E),
        "boxes": [_u8(b, 0x02), _u8(b, 0x03)],
        "flags01": _u8(b, 0x01),
        "c7c": [_u8(b, 0x7C), _u8(b, 0x7D)],
        "sx": _s16(b, 0x28),
        "weapon": held["type"] if held else 0,
        "raw": b.hex(),
    }


def weapon_row(slot: str, b: bytes) -> dict:
    return {
        "slot": slot,
        "type": _u8(b, 0x00) & 0x7F,
        "x": _s16(b, 0x10),
        "y": _s16(b, 0x14),
        "z": _s16(b, 0x18),
        "state": _u8(b, 0x30),
        "cmd": _u8(b, 0x51),
        "wear": _u8(b, 0x50),
        "holder": slot_for_ptr(_u16(b, 0x52)) if _u16(b, 0x52) else None,
        "dmg": _u8(b, 0x34),
        "anim": _u16(b, 0x08),
        "boxes": [_u8(b, 0x02), _u8(b, 0x03)],
        "flags01": _u8(b, 0x01),
        "vx": _fx(b, 0x1C),
    }


def compress(names: list[str | None]) -> list[str]:
    runs: list[list] = []
    for name in names:
        label = name or "None"
        if runs and runs[-1][0] == label:
            runs[-1][1] += 1
        else:
            runs.append([label, 1])
    return [f"{label} x{count}" for label, count in runs]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--family", default="garcia", choices=sorted(FAMILY_TYPES) + ["all"])
    ap.add_argument("--level", type=int, default=1, help="1-based, for the host cheat")
    ap.add_argument("--seconds", type=float, default=300.0)
    ap.add_argument("--poll-ms", type=int, default=16)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--through-bosses", action="store_true", help="Play on past a round's boss.")
    ap.add_argument("--food", action="store_true", help="Let the AI eat (off: a heal hides the hits after it).")
    ap.add_argument("--no-reach", action="store_true", help="Already in gameplay: skip the menus.")
    ap.add_argument("--profile-ms", type=float, default=0.0,
                    help="Profile every tick; print the stats of any tick slower than this.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    poll_s = args.poll_ms / 1000.0
    level_index = args.level - 1
    kept = ORDINARY_TYPES if args.family == "all" else FAMILY_TYPES[args.family]

    if not args.no_reach:
        with MegaDriveClient(host=args.host, port=args.port) as menu:
            reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(
        start_level=args.level, only_enemy=None if args.family == "all" else args.family
    )

    with MegaDriveClient(host=args.host, port=args.port) as client:
        rom = RomData.read(client)
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        loop = AgentLoop(gamepad, no_food=not args.food, no_police=True)

        on_level = False
        started_at = None
        end_state = "timeout"
        last_hp = prev_lives = None
        prev_clock = prev_pos = last_time_over_t = None
        hits: list[dict] = []
        recent_verbs: deque = deque(maxlen=HIT_HISTORY_TICKS)
        verbs_with_enemy: Counter[str] = Counter()
        enemies: dict[str, dict] = {}
        prev_slots: dict[str, bytes] = {}
        enemy_ticks = 0
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

                if args.profile_ms > 0:
                    import cProfile
                    import io
                    import pstats

                    prof = cProfile.Profile()
                    tick_t0 = time.perf_counter()
                    prof.enable()
                    verb = loop.tick(snap, player_index=1)
                    prof.disable()
                    tick_ms = (time.perf_counter() - tick_t0) * 1000.0
                    if tick_ms > args.profile_ms:
                        buf = io.StringIO()
                        pstats.Stats(prof, stream=buf).sort_stats("cumulative").print_stats(25)
                        print(f"SLOW TICK {tick_ms:.0f} ms verb={type(verb).__name__ if verb else None}", flush=True)
                        print(buf.getvalue(), flush=True)
                else:
                    tick_t0 = time.perf_counter()
                    verb = loop.tick(snap, player_index=1)
                    tick_ms = (time.perf_counter() - tick_t0) * 1000.0
                verb_name = type(verb).__name__ if verb else None
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

                table = client.read_memory(mm.ADDR_OBJECT_TABLE, SLOT_COUNT * mm.OBJECT_SLOT_SIZE)
                p1raw = client.read_memory(mm.ADDR_P1_OBJECT, mm.OBJECT_SLOT_SIZE)
                clock_raw = client.read_memory(mm.ADDR_GAME_TIMER, 4)
                clock_bcd = clock_raw[1]
                clock = (clock_bcd >> 4) * 10 + (clock_bcd & 0x0F)
                if client.read_memory(mm.ADDR_TIME_OVER_SEQUENCE, 1)[0]:
                    last_time_over_t = t0
                slots = {f"obj{i:02d}": table[i * 0x80 : (i + 1) * 0x80] for i in range(SLOT_COUNT)}
                weapons = {
                    name: weapon_row(name, b) for name, b in slots.items() if b[0] & 0x7F in WEAPON_TYPES
                }
                held_by = {w["holder"]: w for w in weapons.values() if w["holder"] and w["cmd"] == 1}
                rows = [
                    enemy_row(name, b, held_by)
                    for name, b in slots.items()
                    if b[0] in kept and b[0x31] != 0xFF
                ]
                live = [r for r in rows if r["hp"] >= 0 and r["state"] not in (0x00, 0x06)]
                elapsed = t0 - started_at

                seen = set()
                for r in rows:
                    key = r["slot"]
                    seen.add(key)
                    rec = enemies.get(key)
                    fresh = rec is None or (
                        rec["dead_t"] is not None and r["hp"] >= 0 and r["state"] not in (0x00, 0x06)
                    )
                    if fresh:
                        if rec is not None:
                            enemies[f"{key}@{rec['first_t']}"] = rec
                        rec = enemies[key] = {
                            "slot": key,
                            "type": r["type"],
                            "first_t": round(elapsed, 2),
                            "p40": r["p40"],
                            "p41": r["p41"],
                            "hp0": r["hp"],
                            "hits": 0,
                            "damage": 0,
                            "dead_t": None,
                            "armed": set(),
                            "states": [],
                        }
                    if r["weapon"]:
                        rec["armed"].add(WEAPON_NAMES.get(r["weapon"], hex(r["weapon"])))
                    if r["hp"] < 0 or r["state"] == 0x06:
                        if rec["dead_t"] is None:
                            rec["dead_t"] = round(elapsed, 2)
                    if not rec["states"] or rec["states"][-1] != r["state"]:
                        if len(rec["states"]) < 200:
                            rec["states"].append(r["state"])
                for key, rec in list(enemies.items()):
                    if "@" in key or rec["dead_t"] is not None:
                        continue
                    if key not in seen:
                        rec["dead_t"] = round(elapsed, 2)

                p1 = snap.players[0]
                p1e = next((e for e in snap.world_map.entities if e.slot == "P1"), None) if snap.world_map else None
                p1_pos = [p1e.world_x, p1e.world_y] if p1e else None
                attacker = slot_for_ptr(_u16(p1raw, 0x7E))
                lost_life = p1.lives is not None and prev_lives is not None and p1.lives < prev_lives
                took = p1.health is not None and last_hp is not None and p1.health < last_hp
                if took or lost_life:
                    src = slots.get(attacker) if attacker and attacker.startswith("obj") else None
                    if src is not None and src[0] == 0 and attacker in prev_slots:
                        src = prev_slots[attacker]
                    source = "unknown"
                    detail: dict = {}
                    owner_slot = None
                    if src is not None:
                        t = src[0] & 0x7F
                        if t in WEAPON_TYPES:
                            w = weapon_row(attacker, src)
                            owner_slot = w["holder"]
                            owner = slots.get(owner_slot) if owner_slot else None
                            fam = family_of(owner[0]) if owner is not None else None
                            source = f"{WEAPON_NAMES[t]}_cmd{w['cmd']}" + (f"_{fam}" if fam else "")
                            detail = {"weapon": w}
                            if owner is not None and owner[0] in ORDINARY_TYPES:
                                detail["holder"] = enemy_row(owner_slot, owner, held_by)
                        elif src[0] in ORDINARY_TYPES:
                            e = enemy_row(attacker, src, held_by)
                            owner_slot = attacker
                            source = f"{family_of(src[0])}_s{e['state']:02x}"
                            if e["weapon"]:
                                source += f"_{WEAPON_NAMES.get(e['weapon'], 'w')}"
                            detail = {"enemy": e}
                        else:
                            source = f"type_{src[0]:02X}"
                    time_over_s_ago = round(t0 - last_time_over_t, 2) if last_time_over_t is not None else None
                    if time_over_s_ago is not None and time_over_s_ago <= TIME_OVER_WINDOW_S:
                        source = "round_clock"
                    damage = (last_hp - p1.health) if took else last_hp
                    if owner_slot in enemies:
                        enemies[owner_slot]["hits"] += 1
                        enemies[owner_slot]["damage"] += damage or 0
                    hit = {
                        "t": round(elapsed, 2),
                        "damage": damage,
                        "life_lost": bool(lost_life),
                        "clock": clock,
                        "time_over_s_ago": time_over_s_ago,
                        "source": source,
                        "attacker": attacker,
                        "owner": owner_slot,
                        "verb": verb_name,
                        "recent_verbs": compress(list(recent_verbs)),
                        "p1": [p1e.world_x, p1e.world_y, p1e.world_z, p1e.action_state, p1e.facing_left]
                        if p1e
                        else None,
                        "p1_before": prev_pos,
                        "p1_boxes": [
                            int.from_bytes(p1raw[o : o + 2], "big", signed=True) for o in range(0x64, 0x7C, 2)
                        ],
                        "detail": detail,
                        "enemies": live,
                    }
                    hits.append(hit)
                    rel = ""
                    ref = detail.get("enemy") or detail.get("holder")
                    if ref is not None and p1e is not None:
                        rel = f" dx={ref['x'] - p1e.world_x} dy={ref['y'] - p1e.world_y} anim={ref['anim']:#x} fr={ref['frame']} box={ref['boxes']}"
                    print(
                        f"HIT t={hit['t']} dmg={damage} src={source} by={attacker}{rel} verb={verb_name} "
                        f"recent={hit['recent_verbs'][-4:]}",
                        flush=True,
                    )
                recent_verbs.append(verb_name)
                prev_slots = slots
                prev_clock, prev_pos = clock, p1_pos
                if p1.health is not None:
                    last_hp = p1.health
                if p1.lives is not None:
                    prev_lives = p1.lives

                if live:
                    enemy_ticks += 1
                    verbs_with_enemy[verb_name or "None"] += 1
                if live or weapons:
                    pending = [type(v).__name__ for v in loop.verb_state().pending]
                    sink.write(
                        json.dumps(
                            {
                                "t": round(elapsed, 3),
                                "hp": p1.health,
                                "lives": p1.lives,
                                "clock": clock,
                                "cam": snap.world_map.camera_x if snap.world_map else None,
                                "p1_boxes": [
                                    int.from_bytes(p1raw[o : o + 2], "big", signed=True)
                                    for o in range(0x64, 0x7C, 2)
                                ],
                                "p1": [p1e.world_x, p1e.world_y, p1e.world_z, p1e.action_state, p1e.facing_left]
                                if p1e
                                else None,
                                "p1_raw": p1raw.hex(),
                                "verb": verb_name,
                                "tick_ms": round(tick_ms, 1),
                                "target": getattr(verb, "target_slot", None),
                                "pending": sorted(set(pending)),
                                "enemies": rows,
                                "level_index": snap.level_index,
                                "weapons": list(weapons.values()),
                            }
                        )
                        + "\n"
                    )

                boss = next(
                    (
                        e
                        for e in (snap.world_map.entities if snap.world_map else ())
                        if e.kind == "boss" and e.type_id in ROUND_BOSS_TYPES
                    ),
                    None,
                )
                if boss is not None and not args.through_bosses and not live:
                    end_state = f"boss_reached_{boss.type_id:02X}"
                    print(f"boss {boss.type_id:#04x} in {boss.slot} at x={boss.world_x}", flush=True)
                    break
                if t0 - last_report > 10.0:
                    last_report = t0
                    print(
                        f"t={elapsed:.1f} x={p1e.world_x if p1e else None} hp={p1.health} "
                        f"lives={p1.lives} enemies={len(live)} verb={verb_name}",
                        flush=True,
                    )
                time.sleep(max(0.0, poll_s - (time.monotonic() - t0)))

        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001
            pass

    for rec in enemies.values():
        rec["armed"] = sorted(rec["armed"])
        rec["life_s"] = round(rec["dead_t"] - rec["first_t"], 2) if rec["dead_t"] is not None else None
    killed = [r for r in enemies.values() if r["dead_t"] is not None]
    family_hits = [h for h in hits if h["owner"] in enemies or any(
        h["source"].startswith(f) for f in FAMILY_TYPES)]
    summary = {
        "family": args.family,
        "level": args.level,
        "character": args.character,
        "end_state": end_state,
        "seconds": round(time.monotonic() - started_at, 1) if started_at else None,
        "enemies_seen": len(enemies),
        "enemies_killed": len(killed),
        "mean_life_s": round(sum(r["life_s"] for r in killed if r["life_s"] is not None) / len(killed), 2)
        if killed
        else None,
        "hits_total": len(hits),
        "damage_total": sum(h["damage"] or 0 for h in hits),
        "family_hits": len(family_hits),
        "family_damage": sum(h["damage"] or 0 for h in family_hits),
        "lives_lost": sum(1 for h in hits if h["life_lost"]),
        "hits_by_source": dict(Counter(h["source"] for h in hits)),
        "hits_by_verb": dict(Counter(str(h["verb"]) for h in hits)),
        "enemy_ticks": enemy_ticks,
        "verbs_with_enemy": dict(verbs_with_enemy.most_common()),
        "enemies": list(enemies.values()),
        "hits": [{k: v for k, v in h.items() if k not in ("enemies",)} for h in hits],
    }
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
