"""Measure the unarmed jump and jump kick frame by frame, for one character.

The AI's jump-kick model (``ai/jump_kick.py``) is a transcription of the
ROM's own physics -- ``$1FC0`` crouch and launch, ``$1FDC`` free flight
(``$389A`` gravity, ``$38C0`` air steer, ``$3914`` kick edge), ``$2000`` kick
(``$21B4`` hit freeze, ``$38AE`` lighter fall), ``$3E78`` landing. This tool
is how that transcription is checked against the game instead of against the
manuscript: a **lockstep** host stepped one frame at a time from grounded
idle, the jump issued on frame 0, and the player's own action (``+$30``),
animation frame (``+$0A``), position (``+$10``/``+$14``/``+$18``), velocity
(``+$1C``/``+$24``), outgoing damage (``+$34``) and both cached boxes
(``+$64`` attack, ``+$70`` body, written every frame by ``$4140``) sampled
out of the work-RAM copy every frame until the player is standing again.

Variants, all from the same standing start and facing right:

    carry_kick     C + Right, Right held throughout, B on free-flight frame 1
    carry_kick_k   the same, B on free-flight frame ``--late-kick``
    carry_nokick   C + Right, Right held throughout, no B
    release_kick   Right held through the crouch only, B on free-flight frame 1
    vertical_kick  C alone, B on free-flight frame 1

Row ``i`` is the object *after* frame ``i``, whose input is the mask listed in
that row. Every variant starts back at the same X (walked to in lockstep) with
the street swept by the host's own debug hotkeys first, so nothing else is on
screen to collide with.

Run (host already up with ``--debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/jump_kick_lab.py --character blaze --out /tmp/blaze.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from megadrive_remote import Buttons, MegaDriveClient

from sor_autoplay.debug_scenario import ENEMY_FAMILY_HOTKEYS
from sor_autoplay.memory_map import ADDR_P1_OBJECT
from sor_autoplay.reach_gameplay import reach_gameplay

# Work RAM is $FF0000-$FFFFFF and ``step_input`` hands back all 64 KiB of it.
WORK_RAM_BASE = 0xFF0000
OBJECT_BYTES = 0x80

ACTION_IDLE = frozenset({0x02, 0x03})
ACTION_FREE_FLIGHT = frozenset({0x12, 0x13})

# An unbounded loop against a live host is what this repo's rules forbid.
MAX_JUMP_FRAMES = 160
MAX_WALK_FRAMES = 400
SETTLE_FRAMES = 12


def _object(work_ram: bytes) -> bytes:
    start = ADDR_P1_OBJECT - WORK_RAM_BASE
    return work_ram[start : start + OBJECT_BYTES]


def _u16(obj: bytes, offset: int) -> int:
    return int.from_bytes(obj[offset : offset + 2], "big")


def _s16(obj: bytes, offset: int) -> int:
    return int.from_bytes(obj[offset : offset + 2], "big", signed=True)


def _s32(obj: bytes, offset: int) -> int:
    return int.from_bytes(obj[offset : offset + 4], "big", signed=True)


def _u32(obj: bytes, offset: int) -> int:
    return int.from_bytes(obj[offset : offset + 4], "big")


def sample(work_ram: bytes, *, frame: int, mask: int) -> dict:
    obj = _object(work_ram)
    return {
        "frame": frame,
        "input": mask,
        "action": obj[0x30],
        "anim_frame": obj[0x0A],
        "anim_timer": obj[0x0D],
        "box_ids": [obj[0x02], obj[0x03]],
        # 16.16 longs, raw, so a transcription can be compared bit for bit.
        "x_raw": _u32(obj, 0x10),
        "y_raw": _u32(obj, 0x14),
        "z_raw": _u32(obj, 0x18),
        "vx_raw": _s32(obj, 0x1C),
        "vy_raw": _s32(obj, 0x20),
        "vz_raw": _s32(obj, 0x24),
        "x": _u16(obj, 0x10),
        "y": _u16(obj, 0x14),
        "z": _u16(obj, 0x18),
        "damage": obj[0x34],
        "flags58": obj[0x58],
        "flags59": obj[0x59],
        "contact7c": obj[0x7C],
        "attack": [_s16(obj, 0x64 + 2 * i) for i in range(6)],
        "body": [_s16(obj, 0x70 + 2 * i) for i in range(6)],
    }


def step(client: MegaDriveClient, mask: int, frame: int) -> dict:
    result = client.step_input(player1=mask, held_frames=1 if mask else 0, total_frames=1)
    return sample(result.work_ram, frame=frame, mask=mask)


def settle(client: MegaDriveClient) -> dict:
    """Step with no input until the player has stood idle for a while."""

    still = 0
    row = step(client, 0, -1)
    for _ in range(MAX_WALK_FRAMES):
        row = step(client, 0, -1)
        still = still + 1 if row["action"] in ACTION_IDLE else 0
        if still >= SETTLE_FRAMES:
            return row
    raise RuntimeError(f"player never settled idle (action ${row['action']:02X})")


def walk_to(client: MegaDriveClient, target_x: int) -> dict:
    """Walk (in lockstep) until the player stands within 2 px of ``target_x``,
    then settle and face right with a one-frame tap."""

    row = settle(client)
    for _ in range(MAX_WALK_FRAMES):
        dx = target_x - row["x"]
        if abs(dx) <= 2:
            break
        row = step(client, int(Buttons.RIGHT if dx > 0 else Buttons.LEFT), -1)
    row = settle(client)
    if row["action"] & 0x01:
        # Facing left: one Right tap turns without walking far.
        step(client, int(Buttons.RIGHT), -1)
        row = settle(client)
    return row


def sweep(client: MegaDriveClient) -> None:
    for key in ENEMY_FAMILY_HOTKEYS.values():
        client.trigger_option_hotkey(key)


def run_variant(
    client: MegaDriveClient,
    *,
    direction: int,
    kick_on: int | None,
    hold_after_launch: bool,
) -> list[dict]:
    """One jump from standing idle. ``kick_on`` is the free-flight frame (1 =
    the first ``$1FDC`` frame) whose input carries the B edge, or ``None``."""

    rows: list[dict] = []
    launched_at: int | None = None
    landed = False
    for frame in range(MAX_JUMP_FRAMES):
        mask = 0
        if frame == 0:
            mask = int(Buttons.C) | direction
        elif launched_at is None or hold_after_launch:
            mask = direction
        if launched_at is not None and kick_on is not None and frame == launched_at + kick_on:
            mask |= int(Buttons.B)
        row = step(client, mask, frame)
        rows.append(row)
        if launched_at is None and row["action"] in ACTION_FREE_FLIGHT:
            launched_at = frame
        if row["action"] in (0x14, 0x15):
            landed = True
        if landed and row["action"] in ACTION_IDLE:
            break
    return rows


def summarize(rows: list[dict]) -> dict:
    def first(pred) -> int | None:
        return next((r["frame"] for r in rows if pred(r)), None)

    start = rows[0]
    base_x, base_z = start["x_raw"] / 65536.0, start["z_raw"] / 65536.0
    return {
        "launch_frame": first(lambda r: r["action"] in ACTION_FREE_FLIGHT),
        "kick_frame": first(lambda r: r["action"] in (0x16, 0x17)),
        "land_frame": first(lambda r: r["action"] in (0x14, 0x15)),
        "idle_frame": next(
            (r["frame"] for r in rows[1:] if r["action"] in ACTION_IDLE), None
        ),
        "x_travel": round(rows[-1]["x_raw"] / 65536.0 - base_x, 3),
        "apex": round(min(r["z_raw"] / 65536.0 for r in rows) - base_z, 3),
        "damage_frames": [r["frame"] for r in rows if r["damage"]],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="axel")
    ap.add_argument("--late-kick", type=int, default=6)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    right = int(Buttons.RIGHT)
    variants = {
        "carry_kick": dict(direction=right, kick_on=1, hold_after_launch=True),
        f"carry_kick_{args.late_kick}": dict(
            direction=right, kick_on=args.late_kick, hold_after_launch=True
        ),
        "carry_nokick": dict(direction=right, kick_on=None, hold_after_launch=True),
        "release_kick": dict(direction=right, kick_on=1, hold_after_launch=False),
        "vertical_kick": dict(direction=0, kick_on=1, hold_after_launch=False),
    }

    with MegaDriveClient(host=args.host, port=args.port) as client:
        client.release_buttons()
        sweep(client)
        time.sleep(0.3)
        client.set_lockstep(True, timeout_ms=10_000)
        report: dict = {"character": args.character, "variants": {}}
        try:
            home = settle(client)
            report["idle"] = home
            home_x = home["x"]
            for name, spec in variants.items():
                client.set_lockstep(False)
                sweep(client)
                time.sleep(0.2)
                client.release_buttons()
                client.set_lockstep(True, timeout_ms=10_000)
                walk_to(client, home_x)
                rows = run_variant(client, **spec)
                summary = summarize(rows)
                report["variants"][name] = {"summary": summary, "rows": rows}
                print(name, json.dumps(summary), flush=True)
        finally:
            client.set_lockstep(False)
            client.release_buttons()

    if args.out:
        with open(args.out, "w", encoding="utf-8") as sink:
            json.dump(report, sink, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
