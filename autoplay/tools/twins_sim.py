"""Play whole twin fights offline: ``twins_plan.plan`` against ``twins.py``.

Sim-vs-sim, the way ``bongo.py``'s planner was tuned before a live fight:
the fight starts from a ``twins_lab.py`` recording's frame (the entrance, or
any frame with ``--frame``), the actor is moved by the plan one update at a
time, and both twins by the ROM model. ``--starts N`` shifts the actor's
start around the recorded one (seeded), and ``--delay`` hands the plan's
stick to the actor that many updates late, as a slow tick would.

Reports per start: strikes per twin, the first hit taken (the model does not
play a hit reaction, so a start ends there), and how long both twins took.

    cd autoplay
    PYTHONPATH=src python3.11 tools/twins_sim.py --recording /tmp/twins.jsonl --starts 20
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time

from sor_autoplay.ai import twins as model
from sor_autoplay.ai import twins_plan

UPDATES_PER_SECOND = 30.0
SCENARIOS = twins_plan.SCENARIOS
# Events (half updates) between two AI ticks.
TICK_GAPS = (2, 2, 2, 2, 2, 3, 3, 4)


def _load(path: str, frame: int) -> dict:
    with open(path, encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if "summary" in row:
                continue
            if row["f"] >= frame and len(row["tw"]) >= 2:
                return row
    raise SystemExit("no frame with both twins in the recording")


def fight(
    row: dict,
    *,
    dx: float,
    dy: float,
    character: int,
    delay: int,
    limit: int,
    verbose: bool,
    rng: random.Random,
    tick_rate: float,
    trace_at: frozenset = frozenset(),
    verbose_all: bool = False,
    lockstep: bool = False,
) -> dict:
    """One fight, event by event: the player's update and the objects' pass
    alternate (``$AD8E``). Before any event the AI may tick (``tick_rate`` a
    boundary, ~1 a player update at 0.5); its stick latches from the next
    player update, or -- one time in two -- the one after (the lead measured
    live at 2x), plus ``delay`` more. A chord is one press: lost if the actor
    is not free on the update it lands on."""

    cam = row["cam"]
    p1 = bytes.fromhex(row["p1"])
    a = model._actor_from_bytes(p1, cam_x=cam)
    a.x = min(max(a.x + dx, a.x_lo), a.x_hi)
    a.y = min(max(a.y + dy, a.lane_lo), a.lane_hi)
    a.character = character
    a.chord = None
    a.walking = False
    a.damage = 0
    a.unavailable = a.untouchable = a.invulnerable = False
    model.refresh_boxes(a, a.x, a.y)
    twins = [model.TwinSim.from_bytes(bytes.fromhex(h), slot=i, cam_x=cam) for i, h in row["tw"]]
    model.link_pair(twins)
    held = (0, 0)
    presses: list[bool] = []
    memory = twins_plan.PlanMemory()
    pending: list[tuple[int, tuple[int, int], bool]] = []
    strikes = {t.slot: 0 for t in twins}
    started = time.perf_counter()
    plans = 0
    player_updates = 0
    result: dict = {"hit": None, "killed_at": None}
    update = 0
    last_plan = None
    event_index = 0
    next_tick = rng.randint(0, 1)
    for update in range(limit):
        for event in ("player", "objects"):
            event_index += 1
            if lockstep and event == "objects":
                pass  # the lab ticks between the objects' pass and the player's
            elif lockstep or event_index >= next_tick:
                # The loop's cadence at 2x: a tick every player update, now
                # and then half an update or a whole one late.
                next_tick = event_index + rng.choice(TICK_GAPS)
                trace = [] if update in trace_at else None
                p = twins_plan.plan(a, twins, committed=held, trace=trace, memory=memory, scenarios=SCENARIOS)
                if trace:
                    print("TRACE", update, event, "chose", p.label, p.score)
                    for entry in trace:
                        print("   ", entry)
                plans += 1
                last_plan = p
                lead = (0 if lockstep else rng.randint(0, 1)) + delay
                pending.append((player_updates + 1 + lead - (0 if event == "player" else 0), (p.dir_x, p.dir_y), p.chord))
            if event == "player":
                player_updates += 1
                chord = False
                due = [entry for entry in pending if entry[0] <= player_updates]
                if due:
                    pending = [entry for entry in pending if entry[0] > player_updates]
                    _, held, chord = due[-1]
                    chord = any(entry[2] for entry in due)
                pressed = chord and a.chord is None
                model.actor_update(a, held[0], held[1], pressed)
                if pressed:
                    presses.append(False)
                if chord:
                    held = (0, 0)
            else:
                outcomes = model.object_pass(twins, a)
                if verbose and (verbose_all or update % 10 == 0 or any(o is not model.Outcome.NONE for o in outcomes)):
                    print(
                        update,
                        f"A x{a.x:.1f} y{a.y:.1f} f{'L' if a.facing_left else 'R'} chord{a.chord} held{held}",
                        last_plan.label if last_plan else None,
                        " | ".join(
                            f"T{t.slot} p{t.primary} t{t.tac} {t.t78} m{t.mode & 2} x{t.x:.0f} y{t.y:.1f} z{t.z:.0f} vy{t.vy:.2f} hp{t.hp}"
                            for t in twins
                        ),
                        [o.name for o in outcomes if o is not model.Outcome.NONE],
                    )
                for t, outcome in zip(twins, outcomes):
                    if outcome is model.Outcome.STRUCK:
                        strikes[t.slot] += 1
                        if presses:
                            presses[-1] = True
                    if outcome is model.Outcome.HELD:
                        result["hit"] = {"update": update, "by": t.slot, "how": "HELD", "role": t.role, "state": [t.primary, t.tac]}
                    if outcome in (model.Outcome.HIT, model.Outcome.GRABBED):
                        result["hit"] = {
                            "update": update, "by": t.slot, "how": outcome.name,
                            "role": t.role, "state": [t.primary, t.tac],
                        }
        if result["hit"]:
            break
        if all(t.hp <= 0 for t in twins):
            result["killed_at"] = update
            break
    elapsed = time.perf_counter() - started
    result.update(
        strikes=strikes,
        chords=len(presses),
        whiffs=sum(1 for struck in presses[:-1] if not struck) + (0 if not presses or presses[-1] or a.chord is not None else 1),
        hp=[t.hp for t in twins],
        updates=update + 1,
        seconds=round((update + 1) / UPDATES_PER_SECOND, 1),
        ms_per_plan=round(1000 * elapsed / max(1, plans), 2),
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recording", required=True)
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--starts", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--character", type=int, default=model.BLAZE)
    ap.add_argument("--delay", type=int, default=0)
    ap.add_argument("--limit", type=int, default=6000, help="updates per fight")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--every", action="store_true", help="with --verbose: every update")
    ap.add_argument("--only", type=int, action="append", help="play only this start (repeatable)")
    ap.add_argument("--trace", type=int, action="append", help="print every candidate at this update")
    ap.add_argument("--lockstep", action="store_true", help="tick every player update, no lead (the lab's timing)")
    ap.add_argument("--scenarios", type=int, help="use only the first N timing scenarios")
    ap.add_argument("--set", action="append", help="override a twins_plan constant, NAME=VALUE (experiments)")
    ap.add_argument("--tick-rate", type=float, default=0.5, help="AI ticks per event boundary")
    args = ap.parse_args()
    global SCENARIOS
    if args.scenarios:
        SCENARIOS = twins_plan.SCENARIOS[: args.scenarios]
    for override in args.set or []:
        name, value = override.split("=")
        setattr(twins_plan, name, type(getattr(twins_plan, name))(value))
    row = _load(args.recording, args.frame)
    starts = random.Random(args.seed)
    results = []
    only = set(args.only or [])
    for start in range(args.starts):
        dx = 0.0 if start == 0 else starts.uniform(-80, 80)
        dy = 0.0 if start == 0 else starts.uniform(-30, 30)
        if only and start not in only:
            continue
        result = fight(
            row, dx=dx, dy=dy, character=args.character, delay=args.delay,
            limit=args.limit, verbose=args.verbose,
            rng=random.Random(args.seed * 1000 + start), tick_rate=args.tick_rate,
            trace_at=frozenset(args.trace or []), verbose_all=args.every,
            lockstep=args.lockstep,
        )
        result["index"] = start
        result["start"] = [round(dx), round(dy)]
        results.append(result)
        print(json.dumps(result), flush=True)
    killed = [r for r in results if r["killed_at"] is not None]
    hit = [r for r in results if r["hit"]]
    print(
        json.dumps(
            {
                "starts": len(results),
                "killed": len(killed),
                "hit": len(hit),
                "mean_seconds_killed": round(sum(r["seconds"] for r in killed) / len(killed), 1) if killed else None,
                "whiffs": sum(r["whiffs"] for r in results),
                "chords": sum(r["chords"] for r in results),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
