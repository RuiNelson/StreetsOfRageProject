"""Diagnose the round-1 "AI stuck on a breakable, throwing punches" report.

Runs the real ``ai/`` pipeline (same functions ``AgentLoop.tick`` calls, in
the same order) against a live host with **real enemies** -- deliberately
no ``--kill-street-enemies``, since a live sweep with that scenario did not
reproduce the stall (see ``autoplay/CLAUDE.md``'s history around the
reverted "Fix round-1 phone booth" commit). Logs one JSON row per tick
while any ``Breakable`` is in context, with enough of the actor/target
geometry to tell a facing miss, a positional miss, and a genuine repeat
punch apart.

Run (host already up with ``--debugUtils``, e.g.
``./scripts/run --turbo 4 --lang en --debugUtils --port 7777 --silent``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/breakable_diag.py --out /tmp/breakable.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from megadrive_remote import MegaDriveClient

from sor_autoplay.ai.decide import in_smash_range
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.decide import generate_verb_tokens
from sor_autoplay.ai.execute import execute_tick
from sor_autoplay.ai.observe import HoldTracker, NoraAttackTracker, generate_direct_observation_tokens
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import Breakable, Myself, Verb, find, find_all
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--seconds", type=float, default=180.0)
    ap.add_argument("--poll-ms", type=int, default=8)
    ap.add_argument(
        "--gap-seconds",
        type=float,
        default=40.0,
        help="Stop early after this many seconds with no Breakable in context, "
        "once at least one has been seen (default 40, wide enough to cross a "
        "wave gap between prop clusters without cutting the run short)",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    poll_s = args.poll_ms / 1000.0

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    with MegaDriveClient(host=args.host, port=args.port) as client:
        rom = RomData.read(client)
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        nora_tracker = NoraAttackTracker()
        hold_tracker = HoldTracker()

        rows = 0
        seen_breakable = False
        gap_ticks = 0
        deadline = time.monotonic() + args.seconds

        with open(args.out, "w", encoding="utf-8") as sink:
            while time.monotonic() < deadline:
                started = time.monotonic()
                snap = read_snapshot(client, rom=rom)
                player = snap.players[0]
                in_continue_ui = player.is_continue_ui
                if snap.paused or (
                    not in_continue_ui and (not snap.timer_valid or not player.is_playable)
                ):
                    gamepad.release()
                    time.sleep(poll_s)
                    continue

                context = generate_direct_observation_tokens(
                    snap, player_index=1, nora_tracker=nora_tracker, hold_tracker=hold_tracker
                )
                context |= generate_inference_tokens(context)
                context |= generate_verb_tokens(context)
                pending = tuple(find_all(context, Verb))
                context = determine_priority_verb(context)
                verbs = find_all(context, Verb)
                verb = verbs[0] if verbs else None
                execute_tick(verb, context, gamepad, route_trace={})

                breakables = find_all(context, Breakable)
                if breakables:
                    seen_breakable = True
                    gap_ticks = 0
                elif seen_breakable:
                    gap_ticks += 1

                if breakables:
                    myself = find(context, Myself)
                    row = {
                        "t": round(started - deadline + args.seconds, 3),
                        "p1_x": myself.world_x if myself else None,
                        "p1_y": myself.world_y if myself else None,
                        "p1_facing_left": myself.facing_left if myself else None,
                        "p1_action_state": myself.action_state if myself else None,
                        "p1_held_weapon_type": myself.held_weapon_type if myself else None,
                        "p1_combat_phase": myself.combat_phase.name if myself else None,
                        "verb": type(verb).__name__ if verb else None,
                        "pending": sorted({type(v).__name__ for v in pending}),
                        "breakables": [
                            {
                                "slot": b.slot,
                                "type_id": hex(b.type_id),
                                "x": b.world_x,
                                "y": b.world_y,
                                "dx": (b.world_x - myself.world_x) if myself else None,
                                "hitbox": (
                                    [b.hitbox.x0, b.hitbox.x1, b.hitbox.y0, b.hitbox.y1]
                                    if b.hitbox is not None
                                    else None
                                ),
                                "in_smash_range": (
                                    in_smash_range(myself, b) if myself else None
                                ),
                            }
                            for b in breakables
                        ],
                    }
                    sink.write(json.dumps(row) + "\n")
                    rows += 1

                if seen_breakable and gap_ticks * poll_s > args.gap_seconds:
                    print(f"breakable(s) resolved or left scene; {rows} rows logged", flush=True)
                    break

                remaining = poll_s - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)

        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001
            pass

    print(f"done: {rows} rows -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
