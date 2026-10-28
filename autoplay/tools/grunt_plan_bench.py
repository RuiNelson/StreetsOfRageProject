"""Time ``grunt_plan.plan`` on recorded EngageGrunts ticks, and prove an optimisation exact.

``tick_bench.py`` times whole ticks; this one isolates the street lookahead
(``EngageGrunts`` -> ``execute.engage_grunts_plan`` -> ``grunt_plan.plan``),
the biggest single cost of a tick in a street fight. It replays
``stage_walk_diag.py --raw`` recordings through the real ``AgentLoop`` with
the budget off (every program played), captures every ``plan`` call's inputs
-- the actor, the enemies, the knives, ``committed``, the flags and a copy of
the ``PlanMemory`` as it was -- and then

* **times** ``plan`` on each, unbudgeted (``--passes`` passes, the per-call
  minimum), reporting median / p95 / max overall and by enemies relevant;
* **stores** every call's ``GruntPlan`` and the program it kept
  (``--save FILE``) and **compares** a later run against it (``--compare``).

Capture once, then iterate against the cached inputs (``--cache FILE``)::

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src:tools python3.11 \\
        tools/grunt_plan_bench.py --raw r1.raw r3.raw --cache calls.pkl --save before.json
    # ... optimise ...
    PYTHONPATH=src:../MegaDriveEnvironment/python/src:tools python3.11 \\
        tools/grunt_plan_bench.py --cache calls.pkl --compare before.json

The cache pickles the model objects, so it is only good while their fields
stay the same. ``--profile`` prints a cProfile of one pass. Exit status is 1
on any diff.
"""

from __future__ import annotations

import argparse
import copy
import cProfile
import json
import os
import pickle
import pstats
import statistics
import sys
import time
from collections import defaultdict

from snapshot_replay import ReplaySource, iter_ticks, load_rom

from sor_autoplay.ai import grunt_plan
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.state import read_snapshot


class _NoPad:
    def hold_buttons(self, **_):
        pass

    def press_buttons(self, **_):
        pass


def capture(path: str) -> list[tuple[str, tuple, dict]]:
    """Every ``plan`` call of one recording: ``(key, args, kwargs)``."""

    rom = load_rom(path)
    loop = AgentLoop(VirtualGamepad(SharedGamepadState(_NoPad()), player_index=1), no_food=True, no_police=True)
    real = grunt_plan.plan
    calls = []

    def spy(*args, **kwargs):
        kwargs["budget_ms"] = None
        calls.append((f"{os.path.basename(path)}#{len(calls)}", copy.deepcopy(args), copy.deepcopy(kwargs)))
        return real(*args, **kwargs)

    grunt_plan.plan = spy
    try:
        for t, reads in iter_ticks(path):
            loop.tick(read_snapshot(ReplaySource(reads), rom=rom), player_index=1)
    finally:
        grunt_plan.plan = real
    return calls


def row(plan, memory) -> list:
    kept = memory.program if memory is not None else None
    plan_row = None if plan is None else [
        plan.dir_x, plan.dir_y, plan.outcome, plan.at_update, repr(plan.score), plan.label,
        plan.target_slot, plan.punch, plan.chord,
    ]
    return [plan_row, repr(kept)]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", nargs="*", default=[], help="stage_walk_diag.py --raw recordings")
    ap.add_argument("--cache", help="pickle of the captured calls (written when missing)")
    ap.add_argument("--save", help="write every call's plan here (JSON)")
    ap.add_argument("--compare", help="a --save file: every plan must be identical")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only the first N calls (0: all)")
    args = ap.parse_args()

    if args.cache and os.path.exists(args.cache):
        with open(args.cache, "rb") as source:
            calls = pickle.load(source)
    else:
        calls = []
        for path in args.raw:
            calls += capture(path)
        if args.cache:
            with open(args.cache, "wb") as sink:
                pickle.dump(calls, sink)
    if args.limit:
        calls = calls[: args.limit]
    print(f"{len(calls)} plan calls")

    rows: dict[str, list] = {}
    best = [float("inf")] * len(calls)
    for _ in range(args.passes):
        for i, (key, call_args, call_kwargs) in enumerate(calls):
            a, sims = copy.deepcopy(call_args)
            kwargs = copy.deepcopy(call_kwargs)
            start = time.perf_counter()
            plan = grunt_plan.plan(a, sims, **kwargs)
            best[i] = min(best[i], time.perf_counter() - start)
            rows[key] = row(plan, kwargs.get("memory"))

    groups: dict[str, list[float]] = defaultdict(list)
    for (key, call_args, _), seconds in zip(calls, best):
        a, sims = call_args
        groups["all"].append(seconds * 1000)
        groups[f"{len(grunt_plan.relevant(a, sims))} relevant"].append(seconds * 1000)
    for label in sorted(groups):
        ms = groups[label]
        print(
            f"{label:>12}: n={len(ms):5d}  mean {statistics.fmean(ms):6.3f}  median {statistics.median(ms):6.3f} ms  "
            f"p95 {percentile(ms, 0.95):6.3f}  max {max(ms):6.3f}  over 2 ms: {sum(1 for v in ms if v > 2.0)}"
        )

    if args.save:
        with open(args.save, "w", encoding="utf-8") as sink:
            json.dump(rows, sink)
    status = 0
    if args.compare:
        with open(args.compare, encoding="utf-8") as source:
            before = json.load(source)
        diffs = [(k, before.get(k), v) for k, v in rows.items() if before.get(k) != v]
        print(f"plan diffs: {len(diffs)} of {len(rows)} calls")
        for k, old, new in diffs[:10]:
            print(f"  {k}\n    before {old}\n    after  {new}")
        status = 1 if diffs else 0
    if args.profile:
        prepared = [(copy.deepcopy(c[1]), copy.deepcopy(c[2])) for c in calls]
        profiler = cProfile.Profile()
        profiler.enable()
        for (a, sims), kwargs in prepared:
            grunt_plan.plan(a, sims, **kwargs)
        profiler.disable()
        stats = pstats.Stats(profiler)
        stats.sort_stats("tottime").print_stats(35)
    return status


if __name__ == "__main__":
    sys.exit(main())
