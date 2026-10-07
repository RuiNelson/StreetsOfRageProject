"""Time ``jack.plan_engage`` on recorded EngageJack ticks, and prove an optimisation exact.

The tick budget (``autoplay/CLAUDE.md``, **Tick budget**) is 2 ms; the Jack
lookahead (``execute.engage_jack_plan`` -> ``jack.plan_engage``) is the biggest
single cost of a tick with a Jack on screen. This tool replays
``stage_walk_diag.py --raw`` recordings through the real ``AgentLoop``, captures
the ``(verb, context)`` of every tick whose winning verb is ``EngageJack``, and

* **times** ``engage_jack_plan`` on each (``--passes`` passes, the per-tick
  minimum of them, so a stray scheduler hiccup is not a slow tick), reporting
  median / p95 / max overall and by the number of Jacks in the context;
* **stores** the full ``EngagePlan`` of every tick (``--save FILE``) and
  **compares** a later run against it (``--compare FILE``): every field
  (``dir_x``, ``dir_y``, ``punch``, ``mode``, ``outcome``, ``at_update``,
  ``score``) must be identical on every tick, so a speed-up is exact.

Capture once, then iterate on the code against the cached contexts
(``--cache FILE``, a pickle of the captured contexts; rebuilt from the raw
recordings when missing):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/jack_plan_bench.py --raw /tmp/j/r4.raw /tmp/j/r5.raw \\
        --cache /tmp/j/ctx.pkl --save /tmp/j/plans_before.json
    # ... optimise ...
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/jack_plan_bench.py --cache /tmp/j/ctx.pkl --compare /tmp/j/plans_before.json

``--profile`` prints a cProfile of one pass. Exit status is 1 on any plan diff.

A context is a set, and ``find_all`` walks it: the order of the Jacks'
``others`` and of the axes -- and with it a tie between two equally good sticks
-- depends on the set's hash order, which varies from process to process (string
hash seeds, and ``hash(None)`` is an address on Python 3.11: even
``PYTHONHASHSEED=0`` is not enough; the pre-optimisation code gave different
plans on 2 of 13,953 round-2 ticks between runs). The tool therefore replays
every context as a list sorted by ``repr``, which ``find``/``find_all`` iterate
the same way: a before/after comparison is then exact.
"""

from __future__ import annotations

import argparse
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

import sor_autoplay.ai.loop as loop_module
from sor_autoplay.ai import execute
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.ai.tokens import EngageJack, Jack, find_all
from sor_autoplay.state import read_snapshot


class _NoPad:
    def hold_buttons(self, **_):
        pass

    def press_buttons(self, **_):
        pass


def capture(path: str) -> list[tuple[str, float, object, object]]:
    """Every EngageJack tick of one recording: ``(file, t, verb, context)``."""

    rom = load_rom(path)
    loop = AgentLoop(VirtualGamepad(SharedGamepadState(_NoPad()), player_index=1), no_food=True, no_police=True)
    seen: dict = {}
    real = loop_module.execute_tick

    def spy(verb, context, gamepad, **kwargs):
        seen["tick"] = (verb, context)
        return real(verb, context, gamepad, **kwargs)

    loop_module.execute_tick = spy
    out = []
    try:
        for t, reads in iter_ticks(path):
            seen.clear()
            loop.tick(read_snapshot(ReplaySource(reads), rom=rom), player_index=1)
            tick = seen.get("tick")
            if tick is not None and isinstance(tick[0], EngageJack):
                out.append((os.path.basename(path), t, tick[0], tick[1]))
    finally:
        loop_module.execute_tick = real
    return out


def plan_row(plan) -> list | None:
    if plan is None:
        return None
    return [
        plan.dir_x, plan.dir_y, plan.punch, plan.mode.name, plan.outcome, plan.at_update, repr(plan.score),
    ]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", nargs="*", default=[], help="stage_walk_diag.py --raw recordings")
    ap.add_argument("--cache", help="pickle of the captured contexts (written when missing)")
    ap.add_argument("--save", help="write every tick's plan here (JSON)")
    ap.add_argument("--compare", help="a --save file: every plan must be identical")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only the first N ticks (0: all)")
    args = ap.parse_args()

    if args.cache and os.path.exists(args.cache):
        with open(args.cache, "rb") as source:
            ticks = pickle.load(source)
    else:
        ticks = []
        for path in args.raw:
            ticks += capture(path)
        if args.cache:
            with open(args.cache, "wb") as sink:
                pickle.dump(ticks, sink)
    # A canonical order for the set's tokens (see the module docstring).
    ticks = [(name, t, verb, sorted(context, key=repr)) for name, t, verb, context in ticks]
    if args.limit:
        ticks = ticks[: args.limit]
    print(f"{len(ticks)} EngageJack ticks")

    plans: dict[str, list | None] = {}
    best = [float("inf")] * len(ticks)
    for _ in range(args.passes):
        for i, (name, t, verb, context) in enumerate(ticks):
            start = time.perf_counter()
            plan = execute.engage_jack_plan(verb, context)
            best[i] = min(best[i], time.perf_counter() - start)
            plans[f"{name}@{t}"] = plan_row(plan)

    groups: dict[str, list[float]] = defaultdict(list)
    for (name, t, verb, context), seconds in zip(ticks, best):
        groups["all"].append(seconds * 1000)
        groups[f"{len(find_all(context, Jack))} Jack(s)"].append(seconds * 1000)
    for label in sorted(groups):
        ms = groups[label]
        print(
            f"{label:>10}: n={len(ms):5d}  median {statistics.median(ms):6.3f} ms  "
            f"p95 {percentile(ms, 0.95):6.3f}  p99 {percentile(ms, 0.99):6.3f}  max {max(ms):6.3f}  "
            f"over 2 ms: {sum(1 for v in ms if v > 2.0)}"
        )

    if args.save:
        with open(args.save, "w", encoding="utf-8") as sink:
            json.dump(plans, sink)
    status = 0
    if args.compare:
        with open(args.compare, encoding="utf-8") as source:
            before = json.load(source)
        diffs = [(k, before.get(k), v) for k, v in plans.items() if before.get(k) != v]
        missing = [k for k in plans if k not in before]
        print(f"plan diffs: {len(diffs)} of {len(plans)} ticks ({len(missing)} not in the saved file)")
        for k, old, new in diffs[:10]:
            print(f"  {k}\n    before {old}\n    after  {new}")
        status = 1 if diffs else 0
    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        for name, t, verb, context in ticks:
            execute.engage_jack_plan(verb, context)
        profiler.disable()
        pstats.Stats(profiler).sort_stats("tottime").print_stats(18)
    return status


if __name__ == "__main__":
    sys.exit(main())
