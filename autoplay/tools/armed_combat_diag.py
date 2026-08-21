"""Measure armed-weapon swing behaviour against real enemies.

Companion to ``breakable_diag.py``: that one isolates the round-1 booth
stall, this one checks the *other* half of the reverted "Fix round-1 phone
booth" commit -- the ``phases.py`` reclassification of held-weapon
``$44-$4F`` states as ``ATTACKING`` -- for a regression in ordinary armed
combat, since that change's blast radius is every armed encounter, not
just breakables. Logs one row per tick while the actor holds a weapon
(``held_weapon_type`` in ``$08-$0C``): action_state, combat_phase, verb,
and the nearest on-screen enemy's health (to eyeball whether swings land).

Run (host already up with ``--debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/armed_combat_diag.py --out /tmp/armed.jsonl --seconds 90
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from megadrive_remote import MegaDriveClient

from sor_autoplay.ai.execute import execute_tick
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.decide import generate_verb_tokens
from sor_autoplay.ai.observe import HoldTracker, NoraAttackTracker, generate_direct_observation_tokens
from sor_autoplay.ai.priority import determine_priority_verb
from sor_autoplay.ai.tokens import Myself, Verb, find, find_all
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--poll-ms", type=int, default=8)
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
                context = determine_priority_verb(context)
                verbs = find_all(context, Verb)
                verb = verbs[0] if verbs else None
                execute_tick(verb, context, gamepad, route_trace={})

                myself = find(context, Myself)
                if myself is not None and 0x08 <= myself.held_weapon_type <= 0x0C:
                    entities = snap.world_map.entities if snap.world_map else ()
                    nearest = None
                    nearest_d = None
                    for e in entities:
                        if e.kind not in ("enemy", "boss") or e.health is None:
                            continue
                        d = abs(e.world_x - myself.world_x) + abs(e.world_y - myself.world_y)
                        if nearest_d is None or d < nearest_d:
                            nearest, nearest_d = e, d
                    sink.write(
                        json.dumps(
                            {
                                "t": round(started - deadline + args.seconds, 3),
                                "p1_x": myself.world_x,
                                "p1_y": myself.world_y,
                                "action_state": myself.action_state,
                                "combat_phase": myself.combat_phase.name,
                                "held_weapon_type": myself.held_weapon_type,
                                "verb": type(verb).__name__ if verb else None,
                                "nearest_enemy_dist": nearest_d,
                                "nearest_enemy_hp": nearest.health if nearest else None,
                            }
                        )
                        + "\n"
                    )
                    rows += 1

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
