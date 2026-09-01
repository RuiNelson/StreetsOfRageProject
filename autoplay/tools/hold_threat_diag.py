"""Does the hold actually end when something else is about to hit us?

``tools/hold_timing_diag.py`` measured what each hold move *costs*;
``decide.could_hold_actions`` spends those numbers. This checks the spending,
live, in the one situation the scored boss fights cannot produce: a hold with
**other enemies alive and swinging**. Round 2 is 1v1 -- the only enemy is the
body already in the actor's hands, which is excluded from its own clock -- so
every boss run exercises the unthreatened path and nothing else.

So this one plays an ordinary level with the waves **left alive** (no
``DebugScenario`` sweep, deliberately) and logs one row per tick in which the
actor is holding a body:

    action base, the winning verb, how many live enemies are on screen, and
    ``reach.frames_until_any_melee_lands`` -- the clock the decision is made
    against, in 60 Hz frames, with the held body excluded.

The summary answers three questions the unit tests cannot:

* did a threatened hold ever actually happen (``threatened_decisions``)?
* what did the AI do on those ticks (``verbs_while_threatened``)?
* did it ever start a knee with something inbound (``knees_while_threatened``,
  which must be 0 -- a knee is 17-18 frames of ignoring every fresh edge, and
  the whole rule is not to start one inside a shorter window than that)?

Only *decision* ticks are counted for those three: the ROM's animation locks
($62/$64/$68/$6A/$6C/$6E) ignore fresh edges, and ``could_hold_actions``
deliberately produces nothing there, so counting them would dilute the
question with ticks where no choice was on offer.

Run (host already up with ``--debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/hold_threat_diag.py --out /tmp/holds.jsonl --seconds 150
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter

from megadrive_remote import MegaDriveClient

from sor_autoplay.ai import reach
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.ai.observe import GrabStallTracker, HoldTracker, NoraAttackTracker
from sor_autoplay.ai.observe import generate_direct_observation_tokens
from sor_autoplay.ai.tokens import Myself, find
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot

# The two stable holds, facing bit cleared: the only bases at which
# could_hold_actions offers anything at all. Everything else in $60-$6F is an
# animation lock the ROM ignores fresh edges during.
DECISION_BASES = frozenset({0x60, 0x66})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="axel")
    ap.add_argument("--seconds", type=float, default=150.0)
    ap.add_argument("--poll-ms", type=int, default=8)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    poll_s = args.poll_ms / 1000.0

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    with MegaDriveClient(host=args.host, port=args.port) as client:
        rom = RomData.read(client)
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        loop = AgentLoop(gamepad)
        # The trackers the loop owns are private to it; this tool rebuilds the
        # observation only to *read* the same tokens the loop just decided on,
        # so it keeps its own and never feeds them back.
        nora = NoraAttackTracker()
        holds = HoldTracker()
        stalls = GrabStallTracker()

        hold_ticks = 0
        decisions = 0
        threatened_decisions = 0
        knees_while_threatened = 0
        verbs_while_threatened: Counter[str] = Counter()
        verbs_while_clear: Counter[str] = Counter()
        grace_seen: Counter[int] = Counter()
        deadline = time.monotonic() + args.seconds
        last_report = 0.0

        with open(args.out, "w", encoding="utf-8") as sink:
            while time.monotonic() < deadline:
                started = time.monotonic()
                snapshot = read_snapshot(client, rom=rom)
                verb = loop.tick(snapshot, player_index=1)

                context = generate_direct_observation_tokens(
                    snapshot,
                    player_index=1,
                    nora_tracker=nora,
                    hold_tracker=holds,
                    grab_stall_tracker=stalls,
                )
                actor = find(context, Myself)
                if actor is None or not actor.is_holding_enemy:
                    if started - last_report > 15.0:
                        last_report = started
                        print(
                            f"playing: holds so far {hold_ticks}, "
                            f"decisions {decisions}, threatened {threatened_decisions}",
                            flush=True,
                        )
                    time.sleep(max(0.0, poll_s - (time.monotonic() - started)))
                    continue

                enemies = reach.live_enemies(context)
                held = reach.held_enemy(actor, enemies)
                held_slot = held.slot if held is not None else None
                grace = reach.frames_until_any_melee_lands(
                    actor,
                    enemies,
                    ignore_slots=frozenset({held_slot}) if held_slot else frozenset(),
                )
                verb_name = type(verb).__name__ if verb is not None else None
                base = actor.action_base
                is_decision = base in DECISION_BASES

                hold_ticks += 1
                if is_decision:
                    decisions += 1
                    if grace is not None:
                        threatened_decisions += 1
                        grace_seen[grace] += 1
                        verbs_while_threatened[verb_name or "None"] += 1
                        if verb_name == "AttackHeldEnemy":
                            knees_while_threatened += 1
                    else:
                        verbs_while_clear[verb_name or "None"] += 1

                sink.write(
                    json.dumps(
                        {
                            "t": round(started, 3),
                            "action_base": f"${base:02X}",
                            "decision": is_decision,
                            "verb": verb_name,
                            "grace_frames": grace,
                            "live_enemies": len(enemies),
                            "held": held_slot,
                            "hp": snapshot.players[0].health,
                        }
                    )
                    + "\n"
                )
                time.sleep(max(0.0, poll_s - (time.monotonic() - started)))

        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001
            pass

        summary = {
            "character": args.character,
            "hold_ticks": hold_ticks,
            "decisions": decisions,
            "threatened_decisions": threatened_decisions,
            "knees_while_threatened": knees_while_threatened,
            "verbs_while_threatened": dict(verbs_while_threatened),
            "verbs_while_clear": dict(verbs_while_clear),
            "grace_frames_seen": dict(sorted(grace_seen.items())),
        }
        print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
