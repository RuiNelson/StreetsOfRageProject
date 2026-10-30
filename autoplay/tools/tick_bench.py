"""Time whole AI ticks on recorded sessions, and prove an optimisation exact.

The tick budget (``autoplay/CLAUDE.md``, **Tick budget**) is 2 ms. This tool
replays ``stage_walk_diag.py --raw`` recordings through the real
``read_snapshot`` and ``AgentLoop.tick`` -- the whole pipeline a live tick
runs, minus the socket -- and

* **times** each tick's two halves, ``read_snapshot`` (parsing the reads) and
  ``AgentLoop.tick`` (observe, infer, decide, rank, execute), as the minimum
  over ``--passes`` passes, reporting median / p95 / p99 / max and the ticks
  over 2 ms, overall and by winning verb;
* **stores** every tick's outcome (``--save FILE``): the winning verb's
  ``repr`` and every pad command the tick sent, and **compares** a later run
  against it (``--compare FILE``), so a speed-up is exact;
* ``--profile`` prints a cProfile of one pass.

The loop is stateful (trackers, the pad's sticky hold), so every pass replays
each recording from its first tick with a fresh ``AgentLoop``. Exit status is
1 on any outcome diff.

    cd autoplay
    PYTHONPATH=src:ai-code:../MegaDriveEnvironment/python/src:tools python3.11 \\
        tools/tick_bench.py --raw r1.raw r3.raw --no-budget --canonical --save before.json
    # ... optimise ...
    PYTHONPATH=src:ai-code:../MegaDriveEnvironment/python/src:tools python3.11 \\
        tools/tick_bench.py --raw r1.raw r3.raw --no-budget --canonical --compare before.json

Two things make a plain replay differ from run to run, and an exactness check
turns both off. ``grunt_plan.plan`` cuts its program list at ``BUDGET_MS`` of
wall clock, so its outcome depends on how fast the machine runs:
``--no-budget`` plays every program. And ties are broken by a set's iteration
order (see ``jack_plan_bench.py``), which differs between processes -- the
street enemies reach ``grunt_plan`` in the context set's order (33-37 of 8,672
round-5 ticks differed between two runs of the same code): ``--canonical``
hands them over in slot order. With both, two runs of the same code agree on
every tick. Timings without ``--no-budget`` are what a live tick costs.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import os
import pstats
import statistics
import sys
import time
from collections import defaultdict

from snapshot_replay import ReplaySource, iter_ticks, load_rom

from sor_ai.ai import decide, grunt_plan
from sor_ai.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_ai.ai.loop import AgentLoop
from sor_ai.state import read_snapshot


class _RecordingPad:
    """A button client that keeps every command sent to it."""

    def __init__(self) -> None:
        self.sent: list = []

    def hold_buttons(self, *, player1: int, player2: int) -> None:
        self.sent.append(("h", player1, player2))

    def press_buttons(self, *, player1: int, player2: int, frames: int = 1) -> None:
        self.sent.append(("p", player1, player2, frames))


def load(path: str):
    rom = load_rom(path)
    return rom, [(t, reads) for t, reads in iter_ticks(path)]


def replay(name, rom, ticks, snap_ms, tick_ms, outcomes, verbs):
    pad = _RecordingPad()
    loop = AgentLoop(VirtualGamepad(SharedGamepadState(pad), player_index=1), no_food=True, no_police=True)
    for i, (t, reads) in enumerate(ticks):
        key = f"{name}@{i}"
        pad.sent.clear()
        t0 = time.perf_counter()
        snap = read_snapshot(ReplaySource(reads), rom=rom)
        t1 = time.perf_counter()
        verb = loop.tick(snap, player_index=1)
        t2 = time.perf_counter()
        snap_ms[key] = min(snap_ms.get(key, 1e9), (t1 - t0) * 1000)
        tick_ms[key] = min(tick_ms.get(key, 1e9), (t2 - t1) * 1000)
        outcomes[key] = [repr(verb), [list(c) for c in pad.sent]]
        verbs[key] = type(verb).__name__ if verb is not None else "-"


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def report(label: str, ms: list[float]) -> None:
    print(
        f"{label:>24}: n={len(ms):6d}  mean {statistics.fmean(ms):6.3f}  median {statistics.median(ms):6.3f}  "
        f"p95 {percentile(ms, 0.95):6.3f}  p99 {percentile(ms, 0.99):6.3f}  max {max(ms):7.3f}  "
        f">2ms {sum(1 for v in ms if v > 2.0)}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", nargs="+", required=True, help="stage_walk_diag.py --raw recordings")
    ap.add_argument("--save", help="write every tick's outcome here (JSON)")
    ap.add_argument("--compare", help="a --save file: every outcome must be identical")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--by-verb", action="store_true", help="also report the tick time by winning verb")
    ap.add_argument(
        "--no-budget", action="store_true",
        help="play every program of grunt_plan.plan (no BUDGET_MS cut), so outcomes do not depend on the clock",
    )
    ap.add_argument(
        "--canonical", action="store_true",
        help="hand grunt_plan its enemies in slot order (not the context set's), so ties break the same in every process",
    )
    args = ap.parse_args()
    if args.no_budget:
        grunt_plan.plan.__kwdefaults__["budget_ms"] = None
    if args.canonical:
        real_sims = decide.grunt_sims

        def canonical_sims(context, actor):
            built = real_sims(context, actor)
            if built is None:
                return None
            a, sims = built
            a.knives = tuple(sorted(a.knives, key=lambda k: (k.x, k.y, k.z, k.vx)))
            return a, sorted(sims, key=lambda g: g.slot)

        decide.grunt_sims = canonical_sims

    sessions = [(os.path.basename(path), *load(path)) for path in args.raw]
    snap_ms: dict[str, float] = {}
    tick_ms: dict[str, float] = {}
    outcomes: dict[str, list] = {}
    verbs: dict[str, str] = {}
    for _ in range(args.passes):
        for name, rom, ticks in sessions:
            replay(name, rom, ticks, snap_ms, tick_ms, outcomes, verbs)

    report("read_snapshot", list(snap_ms.values()))
    report("AgentLoop.tick", list(tick_ms.values()))
    report("total", [snap_ms[k] + tick_ms[k] for k in tick_ms])
    if args.by_verb:
        groups: dict[str, list[float]] = defaultdict(list)
        for key, ms in tick_ms.items():
            groups[verbs[key]].append(ms)
        for verb in sorted(groups, key=lambda v: -sum(groups[v])):
            report(verb, groups[verb])

    if args.save:
        with open(args.save, "w", encoding="utf-8") as sink:
            json.dump(outcomes, sink)
    status = 0
    if args.compare:
        with open(args.compare, encoding="utf-8") as source:
            before = json.load(source)
        diffs = [(k, before.get(k), v) for k, v in outcomes.items() if before.get(k) != v]
        print(f"outcome diffs: {len(diffs)} of {len(outcomes)} ticks")
        for k, old, new in diffs[:10]:
            print(f"  {k}\n    before {old}\n    after  {new}")
        status = 1 if diffs else 0
    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        for name, rom, ticks in sessions:
            replay(name, rom, ticks, {}, {}, {}, {})
        profiler.disable()
        stats = pstats.Stats(profiler)
        stats.sort_stats("tottime").print_stats(30)
        stats.sort_stats("cumulative").print_stats(40)
    return status


if __name__ == "__main__":
    sys.exit(main())
