"""Check ``ai/souther_pair.py``'s replay of Souther's state 1 against a fight.

``tools/boss_fight.py --level 6 --boss-type 0x55`` logs, for the round-6 pair,
every Souther's raw slot, P1's and the game frame each row was read on. For
every two rows one object update apart (two frames), this rebuilds each Souther
in primary 1 from the first row, runs ``souther_pair.update`` once against P1,
and compares what he wrote -- primary, tactical, ``+$1C``, ``+$20`` -- with the
second row. P1 is taken from either row (the update reads the player after the
player's own update, and a poll can land on either side of it), and both are
reported.

Expect a few percent of misses, nearly all timing: the actor turning or
stopping between the two polls flips the rush and the band-restore, or the
lane mirror. A body the actor walks back into commits on paper and is re-held
in the ROM (``$17B52``'s contact test runs before the gate); that is the held
one, not the one the plan asks about.

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/souther_pair_check.py /tmp/fight.jsonl [...]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

from sor_autoplay.ai import souther_pair as pair

SOUTHER_TYPE = 0x55


def _s32(b: bytes, offset: int) -> float:
    return int.from_bytes(b[offset : offset + 4], "big", signed=True) / 65536


def _s16(b: bytes, offset: int) -> int:
    return int.from_bytes(b[offset : offset + 2], "big", signed=True)


def souther_sim(b: bytes, cam_x: int) -> pair.SoutherSim:
    return pair.SoutherSim(
        x=_s32(b, 0x10),
        y=_s32(b, 0x14),
        vx=_s32(b, 0x1C),
        vy=_s32(b, 0x20),
        primary=b[0x30],
        tactical=b[0x67] & 0x7F,
        t7b=b[0x7B],
        t5c=b[0x5C],
        role_two=b[0x5D] == pair.ROLE_TWO,
        screen_x=_s16(b, 0x28),
        cam_x=cam_x,
        held=bool(b[0x66] & 0x01),
        inert=0,
    )


def target_state(b: bytes) -> pair.TargetState:
    action = b[0x30]
    return pair.TargetState(
        x=_s32(b, 0x10),
        y=_s32(b, 0x14),
        vx=_s32(b, 0x1C),
        vy=_s32(b, 0x20),
        facing_left=bool(b[0x09] & 0x02),
        unavailable=bool(b[0x59] & 0x02) or bool(b[0x4B] & 0x02) or 0x5A <= action <= 0x5F,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--examples", type=int, default=5)
    args = ap.parse_args()

    total: Counter = Counter()
    missed: Counter = Counter()
    examples: dict = {}
    for path in args.logs:
        rows = [json.loads(line) for line in open(path, encoding="utf-8")]
        rows = [r for r in rows if "frame" in r and r.get("en") and r.get("p1")]
        for r0, r1 in zip(rows, rows[1:]):
            if r1["frame"] - r0["frame"] != 2:
                continue
            after = {slot: bytes.fromhex(h) for slot, h in r1["en"]}
            for slot, h in r0["en"]:
                b0 = bytes.fromhex(h)
                if b0[0] != SOUTHER_TYPE or b0[0x30] != pair.PRIMARY_ACTIVE or slot not in after:
                    continue
                b1 = after[slot]
                observed = (b1[0x30], b1[0x67] & 0x7F, round(_s32(b1, 0x1C), 3), round(_s32(b1, 0x20), 3))
                for label, player in (("P1 before", r0["p1"]), ("P1 after", r1["p1"])):
                    sim = souther_sim(b0, r0["cam"])
                    pair.update(sim, target_state(bytes.fromhex(player)))
                    predicted = (sim.primary, sim.tactical, round(sim.vx, 3), round(sim.vy, 3))
                    key = (label, f"tactical {b0[0x67] & 0x7F}")
                    total[key] += 1
                    if predicted != observed:
                        missed[key] += 1
                        examples.setdefault(key, []).append((path, r0["t"], slot, predicted, observed))
    for key in sorted(total):
        share = 100.0 * missed[key] / total[key]
        print(f"{key[0]:9}  {key[1]:11}  {total[key]:5} updates  {missed[key]:4} missed ({share:.1f}%)")
    for key, rows in sorted(examples.items()):
        if args.examples <= 0:
            break
        print(key)
        for row in rows[: args.examples]:
            print("   ", row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
