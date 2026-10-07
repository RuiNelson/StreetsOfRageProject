"""Play the Jack engage offline, ``jack.plan_world`` against ``jack.py``'s own model.

``twins_sim.py``'s idea for Jack: every tick of a ``stage_walk_diag.py --raw``
recording that has a Jack on screen (between ``--from`` and ``--to``, one in
``--every``) seeds a world -- him, his axes, the actor, the camera, the holes --
and the plan then plays it out update by update against the model until he is
held, the actor is hit, or ``--updates`` run out (a stalemate). ``--timing``
picks how the tick meets the game: ``ideal`` (a plan every two updates, the
stick on the same update), ``fixed`` (one update late) or ``jitter`` (a tick
every 1-3 updates, the stick 0-2 late, ``--seeds`` times).

Written for round 4's stalemate (``autoplay/CLAUDE.md``, **Round 4: the bridge,
its props and its Jack**): the sim showed the loop -- ``$07`` resetting off
screen, ``$0A`` backing off it -- that the live traces only hinted at.

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/jack_sim.py --raw /tmp/r4.raw --from 56 --to 82 --every 60
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

from snapshot_replay import ReplaySource, iter_ticks, load_rom

from sor_autoplay.ai import jack as J
from sor_autoplay.ai.abadede import punch_spec
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.ai.reach import PIT_AVOID_MARGIN
from sor_autoplay.ai.tokens import CameraRange, Jack, Myself, Pit, Projectile, Stage, find, find_all
from sor_autoplay.state import read_snapshot
from sor_autoplay.world_map import LANE_Y_MAX_DEFAULT, LANE_Y_MIN
import sor_autoplay.ai.loop as loop_module


class _NoPad:
    def hold_buttons(self, **_):
        pass

    def press_buttons(self, **_):
        pass


def seeds(path: str, t0: float, t1: float) -> list[tuple[float, set]]:
    """Every recorded tick in [t0, t1] with a Jack, as the pipeline's context."""

    rom = load_rom(path)
    loop = AgentLoop(VirtualGamepad(SharedGamepadState(_NoPad()), player_index=1), no_food=True, no_police=True)
    captured: dict = {}
    real = loop_module.execute_tick

    def capture(verb, context, gamepad, **kwargs):
        captured["context"] = context
        return real(verb, context, gamepad, **kwargs)

    loop_module.execute_tick = capture
    out = []
    try:
        for t, reads in iter_ticks(path):
            if t < t0 - 3:
                continue
            if t > t1:
                break
            captured.clear()
            loop.tick(read_snapshot(ReplaySource(reads), rom=rom), player_index=1)
            context = captured.get("context")
            if t >= t0 and context and find_all(context, Jack) and find(context, Myself):
                out.append((t, context))
    finally:
        loop_module.execute_tick = real
    return out


def simulate(context, *, updates: int, timing: str, rng: random.Random | None):
    me = find(context, Myself)
    jacks = find_all(context, Jack)
    camera = find(context, CameraRange)
    stage = find(context, Stage)
    a = J.ActorSim.from_token(
        me, lane_lo=float(LANE_Y_MIN), lane_hi=float(LANE_Y_MAX_DEFAULT), x_lo=camera.left, x_hi=camera.right
    )
    a.untouchable = False
    holes = [
        (p.world_x - PIT_AVOID_MARGIN, p.world_x + p.width + PIT_AVOID_MARGIN,
         p.lane_y - PIT_AVOID_MARGIN, p.lane_y + p.height + PIT_AVOID_MARGIN)
        for p in find_all(context, Pit)
    ]
    world = J.build_world(
        me, jacks, find_all(context, Projectile), camera=camera,
        level=stage.level_index if stage else None, holes=holes,
    )
    spec = punch_spec(me.character_id)
    pending: list = []
    stick = (0, 0)
    punched_on = None
    next_tick = 0
    states: Counter = Counter()
    for u in range(updates):
        if u >= next_tick and punched_on is None:
            next_tick = u + (2 if timing != "jitter" else rng.choice((1, 2, 2, 3)))
            plan = J.plan_world(
                world.copy(), a.copy(), spec=spec, moving_x=1 if a.vx > 0.5 else -1 if a.vx < -0.5 else 0
            )
            lag = {"ideal": 0, "fixed": 1}.get(timing) if timing != "jitter" else rng.choice((0, 1, 1, 2))
            pending.append((u + lag, plan))
        while pending and pending[0][0] <= u:
            _, plan = pending.pop(0)
            if plan.punch and punched_on is None:
                punched_on = u
            elif not plan.punch:
                stick = (plan.dir_x, plan.dir_y)
        world.punch = None
        if punched_on is not None:
            age = u - punched_on
            if spec.live[0] <= age <= spec.live[1]:
                world.punch = spec.box
            a.walking = False
            a.vx = 0.0
            a.box_x, a.box_y = a.x, a.y
            if age >= spec.lock - 1:
                punched_on = None
        else:
            J._step_clear_of_holes(a, world, *stick)
        outcome, _ = J.world_update(world, a)
        states[world.jacks[0].state] += 1
        if outcome is J.Outcome.HIT:
            return "hit", u, states
        if outcome is J.Outcome.GRAB:
            return "hold", u, states
    return "stalemate", updates, states


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True, help="a stage_walk_diag.py --raw recording")
    ap.add_argument("--from", dest="t0", type=float, required=True)
    ap.add_argument("--to", dest="t1", type=float, required=True)
    ap.add_argument("--every", type=int, default=60, help="seed from one tick in this many")
    ap.add_argument("--updates", type=int, default=1500)
    ap.add_argument("--timing", choices=("ideal", "fixed", "jitter"), default="ideal")
    ap.add_argument("--seeds", type=int, default=3, help="rng seeds under --timing jitter")
    args = ap.parse_args()

    ticks = seeds(args.raw, args.t0, args.t1)[:: args.every]
    totals: Counter = Counter()
    hold_updates = []
    for seed in range(args.seeds if args.timing == "jitter" else 1):
        rng = random.Random(seed)
        for t, context in ticks:
            result, u, states = simulate(context, updates=args.updates, timing=args.timing, rng=rng)
            totals[result] += 1
            if result == "hold":
                hold_updates.append(u)
            print(f"t={t:.2f} {result} after {u} updates, states {dict(sorted(states.items()))}")
    mean = sum(hold_updates) / len(hold_updates) if hold_updates else None
    print(dict(totals), "mean updates to the hold:", None if mean is None else round(mean))
    return 0


if __name__ == "__main__":
    sys.exit(main())
