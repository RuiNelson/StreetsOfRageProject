"""Play the approach to Mr. X offline: ``mr_x_plan.plan`` against ``mr_x.py``.

``tools/twins_sim.py``'s shape. A start is a frame of a ``tools/mr_x_lab.py``
recording on which he is free (not held, not down, not dying) -- his bytes,
his bullets in flight and the player's, the actor then shifted around it
(seeded) -- and the plan drives the actor one update at a time until the
first hold, the first hit (his lunge or a bullet; the model plays no hit
reaction, so a start ends there) or the limit. Events alternate as ``$AD8E``
runs them: a tick about every player update (sometimes half an update or a
whole one late), its stick landing on the next player update or the one
after. His RNG draws are seeded per start.

The hold loop itself is not played here: once held he is in the states the
lockstep lab measured (``--actor hold``), and what this scores is getting
there -- a grab a Garcia's blow reaches before a knee is spent is marked
``burnt``. His Garcias play from the start frame's bytes (``garcia.py``); a
hold taken on one ends the start (``held a Garcia``).

    cd autoplay
    PYTHONPATH=src python3.11 tools/mr_x_sim.py --recording /tmp/mr_x.jsonl --starts 30
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time

from sor_autoplay.ai import garcia as garcia_model
from sor_autoplay.ai import mr_x as model
from sor_autoplay.ai import mr_x_plan

UPDATES_PER_SECOND = 30.0
TICK_GAPS = (2, 2, 2, 2, 2, 3, 3, 4)
FREE = frozenset(
    {
        model.PRIMARY_DECIDE, model.PRIMARY_RESUME, model.PRIMARY_WALK_IN, model.PRIMARY_LUNGE,
        model.PRIMARY_RETREAT, model.PRIMARY_GUN, model.PRIMARY_REPOSITION,
    }
)


def load_starts(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if "f" not in row or not row.get("mx"):
                continue
            data = bytes.fromhex(row["mx"][0][1])
            if data[0x30] in FREE and int.from_bytes(bytes.fromhex(row["p1"])[0x32:0x34], "big", signed=True) > 0:
                rows.append(row)
    return rows


def fight(row: dict, *, dx: float, dy: float, character: int, limit: int, rng: random.Random,
          verbose: bool = False, lockstep: bool = False, trace_at=frozenset(),
          trace_labels=frozenset(), with_garcias: bool = True) -> dict:
    cam = row["cam"]
    m = model.MrXSim.from_bytes(bytes.fromhex(row["mx"][0][1]), slot=row["mx"][0][0], cam_x=cam)
    bullets = [model.BulletSim.from_bytes(bytes.fromhex(h), slot=i, cam_x=cam) for i, h in row.get("bu", ())]
    bullets = [b for b in bullets if b.state == 1]
    garcias = [
        garcia_model.GarciaSim.from_bytes(bytes.fromhex(h), slot=i, cam_x=cam)
        for i, h in row.get("en", ())
        if bytes.fromhex(h)[0] == garcia_model.OFFICE_TYPE
    ] if with_garcias else []
    garcias = [g for g in garcias if g.alive]
    a = model.actor_from_bytes(bytes.fromhex(row["p1"]), cam_x=cam)
    a.character = character
    a.x = min(max(a.x + dx, a.x_lo), a.x_hi)
    a.y = min(max(a.y + dy, a.lane_lo), a.lane_hi)
    a.unavailable = a.invulnerable = a.holding = False
    a.z = int(m.floor)  # a start frame can catch the player mid-air
    a.punch = None
    a.latch = 0
    a.walking = False
    a.damage = 0
    model.refresh_boxes(a, a.x, a.y)
    memory = mr_x_plan.PlanMemory()
    held = (0, 0)
    pending: list[tuple[int, tuple[int, int], bool, bool]] = []
    player_updates = 0
    event_index = 0
    next_tick = rng.randint(0, 1)
    started = time.perf_counter()
    plans = 0
    result: dict = {"hit": None, "grab": None}
    update = 0
    for update in range(limit):
        for event in ("player", "objects"):
            event_index += 1
            if lockstep and event == "objects":
                pass
            elif lockstep or event_index >= next_tick:
                next_tick = event_index + rng.choice(TICK_GAPS)
                trace = [] if update in trace_at else None
                p = mr_x_plan.plan(a, m, bullets, garcias=garcias, committed=held, memory=memory, trace=trace)
                if trace:
                    print("TRACE", update, event, "chose", p.label, p.score)
                    for entry in trace:
                        if entry[0] in trace_labels or not trace_labels:
                            print("   ", entry)
                plans += 1
                lead = 0 if lockstep else rng.randint(0, 1)
                pending.append((player_updates + 1 + lead, (p.dir_x, p.dir_y), p.punch, p.chord))
                if verbose:
                    print(update, event, p.label, p.mode, p.outcome, p.at_update, (p.dir_x, p.dir_y),
                          f"A {a.x:.1f},{a.y:.1f} M p{m.primary}s{m.sub} t{m.t54} {m.x:.1f},{m.y:.1f}")
            if event == "player":
                player_updates += 1
                a.latch = 0
                due = [e for e in pending if e[0] <= player_updates]
                punch = chord = False
                if due:
                    pending = [e for e in pending if e[0] > player_updates]
                    held = due[-1][1]
                    punch = any(e[2] for e in due)
                    chord = any(e[3] for e in due)
                ready = a.punch is None and a.chord is None
                if punch and ready:
                    result["punches"] = result.get("punches", 0) + 1
                if chord and ready:
                    result["chords"] = result.get("chords", 0) + 1
                model.actor_step(a, *held, punch=punch and ready, chord=chord and ready)
            else:
                events = mr_x_plan._object_pass(m, garcias, bullets, a)
                hits = [who for who, what in events if what == "HIT"]
                if hits:
                    result["hit"] = {"update": update, "by": hits[0], "state": [m.primary, m.sub]}
                elif any(who == "m" and what == "GRAB" for who, what in events):
                    result["grab"] = {"update": update, "state": [m.primary, m.sub]}
                    # A Garcia's blow (or a bullet) on the holder before a
                    # knee can be spent: the hold is let go, or it is the blow.
                    blow = mr_x_plan._hold_burn(garcias, bullets, a)
                    if blow is not None:
                        result["grab"]["burnt"] = blow
                elif any(who == "g" and what == "GRAB" for who, what in events):
                    result["held_garcia"] = result.get("held_garcia", 0) + 1
                    result["hit"] = {"update": update, "by": "held a Garcia", "state": [m.primary, m.sub]}
                for who, what in events:
                    if what == "STRUCK":
                        result["struck_" + who] = result.get("struck_" + who, 0) + 1
        if m.primary == model.PRIMARY_DYING and not result["grab"]:
            result["grab"] = {"update": update, "state": [m.primary, m.sub], "killed": True}
        if result["hit"] or result["grab"]:
            break
    result.update(
        updates=update + 1,
        seconds=round((update + 1) / UPDATES_PER_SECOND, 2),
        ms_per_plan=round(1000 * (time.perf_counter() - started) / max(1, plans), 1),
        start_state=[row["mx"] and bytes.fromhex(row["mx"][0][1])[0x30]],
    )
    return result


def replay(path: str, at: float, *, top: int = 12) -> None:
    """``--replay FILE --at T``: the plan on one row of a ``boss_fight.py``
    recording (its raw slots), every program's worst and mean over the
    timings, best first -- why the live pipeline did what it did."""

    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    rows = [r for r in rows if not r.get("pre") and r.get("p1")]
    row = min(rows, key=lambda r: abs(r["t"] - at))
    cam = row["cam"]
    m = model.MrXSim.from_bytes(bytes.fromhex(row["mx"][0][1]), slot=row["mx"][0][0], cam_x=cam) if row.get("mx") else None
    bullets = [model.BulletSim.from_bytes(bytes.fromhex(h), slot=i, cam_x=cam) for i, h in row.get("bu", ())]
    garcias = [
        garcia_model.GarciaSim.from_bytes(bytes.fromhex(h), slot=i, cam_x=cam)
        for i, h in row.get("en", ())
        if bytes.fromhex(h)[0] == garcia_model.OFFICE_TYPE
    ]
    a = model.actor_from_bytes(bytes.fromhex(row["p1"]), cam_x=cam)
    a.punch = None
    print("row", row["t"], "verb", row.get("verb"), "A", round(a.x, 1), round(a.y, 1), "L" if a.facing_left else "R",
          "unavailable", a.unavailable)
    if m is not None:
        print("  X", round(m.x, 1), round(m.y, 1), f"p{m.primary}s{m.sub} t{m.t54}")
    for g in garcias:
        print("  G", g.slot, round(g.x, 1), round(g.y, 1), f"s{g.state:x}.{g.flags:x} fr{g.frame} cd{g.countdown}", "alive", g.alive)
    trace: list = []
    p = mr_x_plan.plan(a, m, [b for b in bullets if b.state == 1], garcias=[g for g in garcias if g.alive], trace=trace)
    print("chose", p.label, p.outcome, p.at_update, round(p.score), (p.dir_x, p.dir_y), "punch" if p.punch else "")
    by: dict[str, list] = {}
    for label, player_first, lead, overrun, score, hit_at, grab_at in trace:
        by.setdefault(label, []).append((score, hit_at, grab_at))
    ranked = sorted(by.items(), key=lambda kv: -min(s for s, _, _ in kv[1]))
    for label, outs in ranked[:top]:
        worst = min(outs)
        print(f"  {label:24s} worst {worst[0]:>10} hit@{worst[1]} grab@{worst[2]}  mean {sum(s for s, _, _ in outs) / len(outs):>12.0f}")


def main() -> int:
    if "--replay" in sys.argv:
        ap = argparse.ArgumentParser()
        ap.add_argument("--replay", required=True)
        ap.add_argument("--at", type=float, action="append", required=True)
        ap.add_argument("--top", type=int, default=12)
        args = ap.parse_args()
        for at in args.at:
            replay(args.replay, at, top=args.top)
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("--recording", action="append", required=True)
    ap.add_argument("--starts", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--character", type=int, default=model.BLAZE)
    ap.add_argument("--limit", type=int, default=600, help="updates per start")
    ap.add_argument("--only", type=int, action="append")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--lockstep", action="store_true")
    ap.add_argument("--trace", type=int, action="append", help="print every program's score at update U")
    ap.add_argument("--trace-label", action="append", help="only these programs in the trace")
    ap.add_argument("--no-garcias", action="store_true", help="leave his Garcias out")
    args = ap.parse_args()
    rows = [r for path in args.recording for r in load_starts(path)]
    pick = random.Random(args.seed)
    results = []
    for start in range(args.starts):
        row = pick.choice(rows)
        dx = pick.uniform(-100, 100)
        dy = pick.uniform(-40, 40)
        if args.only and start not in args.only:
            continue
        r = fight(row, dx=dx, dy=dy, character=args.character, limit=args.limit,
                  rng=random.Random(args.seed * 1000 + start), verbose=args.verbose, lockstep=args.lockstep,
                  trace_at=frozenset(args.trace or []), trace_labels=frozenset(args.trace_label or []),
                  with_garcias=not args.no_garcias)
        r["index"] = start
        r["frame"] = row["f"]
        r["offset"] = [round(dx), round(dy)]
        results.append(r)
        print(json.dumps(r), flush=True)
    grabbed = [r for r in results if r["grab"]]
    hit = [r for r in results if r["hit"]]
    print(json.dumps({
        "starts": len(results), "grabbed": len(grabbed), "hit": len(hit),
        "burnt": sum(1 for r in grabbed if r["grab"].get("burnt")),
        "held_garcia": sum(1 for r in hit if r["hit"]["by"] == "held a Garcia"),
        "neither": len(results) - len(grabbed) - len(hit),
        "mean_seconds_to_grab": round(sum(r["seconds"] for r in grabbed) / len(grabbed), 2) if grabbed else None,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
