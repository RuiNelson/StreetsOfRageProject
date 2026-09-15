"""Play a round with only Jack kept, and score every Jack encounter.

``boss_fight.py``'s shape for an ordinary enemy: the real ``AgentLoop``
walks the round through ``ai/gamepad.py`` and nothing else, while
``DebugScenario(only_enemy="jack")`` keeps every other ordinary family
swept -- so each wave leaves Jack alone on screen with the actor, which is
the question: how does the AI fight *him*.

Jack's own body never carries an attack box (``ai-analysis/enemy-ai.md``,
"Jack"): every hit he lands is one of his type-``$28`` axes, juggled in
front of him or thrown. So a hit is attributed through the player's own
``+$7E`` -- the object ``$AA22`` names as the attacker -- to the axe, its
``+$30`` state (1 juggled, 4 thrown) and the Jack that owns it (``+$42``),
with that Jack's primary state and spawn personality (``+$40`` low
nibble).

Rounds with Jack (the ELC census in ``autoplay/CLAUDE.md``): 2 and 4
(personality 0), 5 (2 and 3), 6 and 8 (0 and 1). The run ends when a boss
appears, the level changes, or ``--seconds`` runs out.

Run (host already up with ``--debugUtils``, e.g.
``./scripts/run --turbo 4 --lang en --debugUtils --port 7777 --silent``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/jack_fight.py --level 2 --out /tmp/jack.jsonl
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

JACK_TYPE = 0x27
AXE_TYPE = 0x28
# The rounds' own bosses (enemy-ai.md): the run ends on the first of these,
# not on any object the catalog files as a boss.
ROUND_BOSS_TYPES = frozenset({0x30, 0x35, 0x55, 0x56, 0x57, 0x58})
PLAYER_MAX_HEALTH = 80
SLOT_COUNT = 66
HIT_HISTORY_TICKS = 30


def _u8(b: bytes, o: int) -> int:
    return b[o]


def _u16(b: bytes, o: int) -> int:
    return int.from_bytes(b[o : o + 2], "big")


def _s16(b: bytes, o: int) -> int:
    return int.from_bytes(b[o : o + 2], "big", signed=True)


def _fx(b: bytes, o: int) -> float:
    return round(int.from_bytes(b[o : o + 4], "big", signed=True) / 65536.0, 4)


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


def jack_row(slot: str, b: bytes) -> dict:
    return {
        "slot": slot,
        "x": _s16(b, 0x10),
        "y": _s16(b, 0x14),
        "z": _s16(b, 0x18),
        "state": _u8(b, 0x30),
        "sub": _u8(b, 0x31),
        "hp": _s16(b, 0x32),
        "left": bool(_u8(b, 0x09) & 0x02),
        "vx": _fx(b, 0x1C),
        "vy": _fx(b, 0x20),
        "p40": _u8(b, 0x40),
        "p41": _u8(b, 0x41),
        "f52": _u8(b, 0x52),
        "aim": [_s16(b, 0x60), _s16(b, 0x62), _u16(b, 0x64)],
        "anim": _u16(b, 0x08),
        "frame": _u8(b, 0x0A),
        "t50": _u8(b, 0x50),
        "t51": _u8(b, 0x51),
        "t54": _u8(b, 0x54),
        "boxes": [_u8(b, 0x02), _u8(b, 0x03)],
        "sx": _s16(b, 0x28),
    }


def axe_row(slot: str, b: bytes) -> dict:
    return {
        "slot": slot,
        "x": _s16(b, 0x10),
        "y": _s16(b, 0x14),
        "z": _s16(b, 0x18),
        "state": _u8(b, 0x30),
        "sub": _u8(b, 0x31),
        "vx": _fx(b, 0x1C),
        "vy": _fx(b, 0x20),
        "vz": _fx(b, 0x24),
        "off": _fx(b, 0x54),
        "t50": _u8(b, 0x50),
        "owner": slot_for_ptr(_u16(b, 0x42)),
        "p40": _u8(b, 0x40),
        "anim": _u16(b, 0x08),
        "frame": _u8(b, 0x0A),
        "boxes": [_u8(b, 0x02), _u8(b, 0x03)],
        "dmg": _u8(b, 0x34),
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
    ap.add_argument("--level", type=int, default=2, help="1-based, for the host cheat")
    ap.add_argument("--seconds", type=float, default=300.0)
    ap.add_argument("--poll-ms", type=int, default=8)
    ap.add_argument("--character", default="blaze")
    ap.add_argument(
        "--food",
        action="store_true",
        help="Let the AI eat. Off by default: a heal hides the hits after it.",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    poll_s = args.poll_ms / 1000.0
    level_index = args.level - 1

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=args.level, only_enemy="jack")

    with MegaDriveClient(host=args.host, port=args.port) as client:
        rom = RomData.read(client)
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        loop = AgentLoop(gamepad, no_food=not args.food, no_police=True)

        on_level = False
        started_at = None
        end_state = "timeout"
        last_hp = prev_lives = None
        hits: list[dict] = []
        recent_verbs: deque = deque(maxlen=HIT_HISTORY_TICKS)
        verbs_with_jack: Counter[str] = Counter()
        # Keyed by (slot, first-seen tick): a slot is reused once he dies.
        jacks: dict[str, dict] = {}
        # The previous tick's slots: a thrown axe removes itself on the hit
        # ($FFA2 -> clear_object_128), so by the time the harness reads the
        # player's +$7E the attacker's slot is already empty.
        prev_slots: dict[str, bytes] = {}
        jack_ticks = 0
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
                # $FFFB00: the live countdown word; its low byte holds the two
                # BCD digits (read live: 30, 29 ... then 49 for the next section).
                clock_raw = client.read_memory(mm.ADDR_GAME_TIMER, 4)
                clock_bcd = clock_raw[1]
                clock = (clock_bcd >> 4) * 10 + (clock_bcd & 0x0F)
                slots = {
                    f"obj{i:02d}": table[i * 0x80 : (i + 1) * 0x80] for i in range(SLOT_COUNT)
                }
                jack_rows = [
                    jack_row(name, b) for name, b in slots.items() if b[0] == JACK_TYPE and b[0x31] != 0xFF
                ]
                axe_rows = [axe_row(name, b) for name, b in slots.items() if b[0] & 0x7F == AXE_TYPE]
                live_jacks = [j for j in jack_rows if j["hp"] >= 0 and j["state"] not in (0x00, 0x06)]
                elapsed = t0 - started_at

                # Per-Jack bookkeeping.
                seen = set()
                for j in jack_rows:
                    key = j["slot"]
                    seen.add(key)
                    rec = jacks.get(key)
                    if rec is None or rec.get("dead_t") is not None and j["hp"] >= 0 and j["state"] == 0x01 and rec["dead_t"] is not None:
                        if rec is not None and rec.get("dead_t") is not None:
                            jacks[f"{key}@{rec['first_t']}"] = rec
                        rec = jacks[key] = {
                            "slot": key,
                            "first_t": round(elapsed, 2),
                            "p40": j["p40"],
                            "p41": j["p41"],
                            "hp0": j["hp"],
                            "hits": 0,
                            "damage": 0,
                            "dead_t": None,
                            "states": [],
                        }
                    if j["hp"] < 0 or j["state"] == 0x06:
                        if rec["dead_t"] is None:
                            rec["dead_t"] = round(elapsed, 2)
                    if not rec["states"] or rec["states"][-1] != j["state"]:
                        rec["states"].append(j["state"])
                for key, rec in list(jacks.items()):
                    if "@" in key or rec["dead_t"] is not None:
                        continue
                    if key not in seen:
                        rec["dead_t"] = round(elapsed, 2)

                p1 = snap.players[0]
                attacker = slot_for_ptr(_u16(p1raw, 0x7E))
                lost_life = p1.lives is not None and prev_lives is not None and p1.lives < prev_lives
                took = p1.health is not None and last_hp is not None and p1.health < last_hp
                if took or lost_life:
                    src = slots.get(attacker) if attacker and attacker.startswith("obj") else None
                    if src is not None and src[0] == 0 and attacker in prev_slots:
                        src = prev_slots[attacker]
                    source = "unknown"
                    owner_state = None
                    owner_slot = None
                    if src is not None:
                        if src[0] & 0x7F == AXE_TYPE:
                            a = axe_row(attacker, src)
                            source = {1: "juggled_axe", 4: "thrown_axe", 2: "tossed_axe", 3: "falling_axe"}.get(
                                a["state"], f"axe_state_{a['state']}"
                            )
                            owner_slot = a["owner"]
                            if owner_slot in slots and slots[owner_slot][0] == JACK_TYPE:
                                owner_state = slots[owner_slot][0x30]
                        elif src[0] == JACK_TYPE:
                            source = "jack_body"
                            owner_slot = attacker
                            owner_state = src[0x30]
                        else:
                            source = f"type_{src[0]:02X}"
                    if owner_slot in jacks:
                        jacks[owner_slot]["hits"] += 1
                        jacks[owner_slot]["damage"] += (last_hp - p1.health) if took else last_hp
                    hit = {
                        "t": round(elapsed, 2),
                        "damage": (last_hp - p1.health) if took else last_hp,
                        "life_lost": bool(lost_life),
                        "clock": clock,
                        "source": source,
                        "attacker": attacker,
                        "owner": owner_slot,
                        "owner_state": owner_state,
                        "verb": verb_name,
                        "recent_verbs": compress(list(recent_verbs)),
                        "p1": [snap.world_map and next((e.world_x for e in snap.world_map.entities if e.slot == "P1"), None),
                               next((e.world_y for e in snap.world_map.entities if e.slot == "P1"), None) if snap.world_map else None],
                        "jacks": live_jacks,
                        "axes": axe_rows,
                    }
                    hits.append(hit)
                    print(
                        f"HIT t={hit['t']} dmg={hit['damage']} src={source} owner={owner_slot} "
                        f"owner_state={owner_state} verb={verb_name}",
                        flush=True,
                    )
                recent_verbs.append(verb_name)
                prev_slots = slots
                if p1.health is not None:
                    last_hp = p1.health
                if p1.lives is not None:
                    prev_lives = p1.lives

                if live_jacks:
                    jack_ticks += 1
                    verbs_with_jack[verb_name or "None"] += 1
                if live_jacks or axe_rows:
                    p1e = next((e for e in snap.world_map.entities if e.slot == "P1"), None) if snap.world_map else None
                    sink.write(
                        json.dumps(
                            {
                                "t": round(elapsed, 3),
                                "hp": p1.health,
                                "lives": p1.lives,
                                "clock": clock,
                                "clock_raw": clock_raw.hex(),
                                # $4140's cached player boxes: attack (+$64) then
                                # body (+$70), six absolute words each.
                                "p1_boxes": [
                                    int.from_bytes(p1raw[o : o + 2], "big", signed=True)
                                    for o in range(0x64, 0x7C, 2)
                                ],
                                "p1": [p1e.world_x, p1e.world_y, p1e.world_z, p1e.action_state, p1e.facing_left]
                                if p1e
                                else None,
                                "verb": verb_name,
                                "jacks": jack_rows,
                                "axes": axe_rows,
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
                # A round can meet a boss before its Jacks (round 5 has an
                # Abadede early on): only stop once a Jack has been seen and
                # none is left alive; the AI fights anything else meanwhile.
                if boss is not None and jacks and not live_jacks:
                    end_state = f"boss_reached_{boss.type_id:02X}"
                    print(f"boss {boss.type_id:#04x} in {boss.slot} at x={boss.world_x}", flush=True)
                    break
                if t0 - last_report > 10.0:
                    last_report = t0
                    p1e = next((e for e in snap.world_map.entities if e.slot == "P1"), None) if snap.world_map else None
                    print(
                        f"t={elapsed:.1f} x={p1e.world_x if p1e else None} hp={p1.health} "
                        f"lives={p1.lives} jacks={len(live_jacks)} axes={len(axe_rows)} verb={verb_name}",
                        flush=True,
                    )
                time.sleep(max(0.0, poll_s - (time.monotonic() - t0)))

        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001
            pass

    summary = {
        "level": args.level,
        "character": args.character,
        "end_state": end_state,
        "seconds": round(time.monotonic() - started_at, 1) if started_at else None,
        "hits_total": len(hits),
        "damage_total": sum(h["damage"] or 0 for h in hits),
        "lives_lost": sum(1 for h in hits if h["life_lost"]),
        "hits_by_source": dict(Counter(h["source"] for h in hits)),
        "hits_by_owner_state": dict(Counter(str(h["owner_state"]) for h in hits)),
        "jacks": list(jacks.values()),
        "jack_ticks": jack_ticks,
        "verbs_with_jack": dict(verbs_with_jack.most_common()),
        "hits": [{k: v for k, v in h.items() if k not in ("jacks", "axes")} for h in hits],
    }
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
