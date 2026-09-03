"""Catch the round-2 wipe that keeps destroying boss measurements.

Four of sixteen scored Souther runs never reached the boss at all. With
``boss_fight.py``'s off-target heartbeat they all read the same way: the
actor is walking round 2, last verb ``OpenBreakable``, somewhere around
x=1960-1982 with three lives and full health -- and ten seconds later the
game is on the attract screen with ``lives=0``. Three lives, in ten seconds,
at full health, with ``--kill-street-enemies`` sweeping every ordinary
family: that is not enemy damage. Falling costs a whole life regardless of
health (``player-health-lives-and-combat.md``'s ``$01C0`` fall boundary),
and three of them in ten seconds is a death loop.

Reading the code did not explain it: pits are already ``solid_obstacles``,
so a routed approach plans around them, and ``execute_tick`` carries a pit
escape for an actor already standing in one. So this records what actually
happens instead.

It plays the same scenario the fight harness does -- same level jump, same
sweep, same turbo cadence -- keeps a ring buffer of the last ticks, and dumps
that buffer the moment a life disappears: position, lane, health, the
winning verb, the action state, every ``Pit`` in the context with its
rectangle, and whether ``reach.pit_endangers`` called the actor's own
position dangerous. Stops on the second death or its own deadline, so it
cannot spin the way the run it is diagnosing did.

Run (host already up with ``--debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/round2_death_diag.py --out /tmp/r2.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque

from megadrive_remote import MegaDriveClient

from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.ai.observe import (
    GrabStallTracker,
    HoldTracker,
    NoraAttackTracker,
    generate_direct_observation_tokens,
)
from sor_autoplay.ai.reach import pit_endangers
from sor_autoplay.ai.tokens import Myself, Pit, find, find_all
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.phases import player_phase
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot

# Ticks of context to keep for each death. At ~2 frames a tick under turbo
# this is about a second and a half -- long enough to show the approach that
# walked in, not just the frame that fell.
HISTORY_TICKS = 60


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--level", type=int, default=2)
    ap.add_argument("--seconds", type=float, default=180.0)
    ap.add_argument("--poll-ms", type=int, default=8)
    ap.add_argument("--deaths", type=int, default=2, help="stop after this many")
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--trace",
        help=(
            "Write every tick here as JSONL. The ring buffer only dumps on a "
            "life *loss*, and the failure being chased never shows one: the "
            "game is simply gone from the level on the next poll. A "
            "continuous trace is the only thing that can show the last "
            "seconds before that."
        ),
    )
    args = ap.parse_args()
    poll_s = args.poll_ms / 1000.0
    level_index = args.level - 1

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=args.level, kill_street_enemies=True)

    with MegaDriveClient(host=args.host, port=args.port) as client:
        rom = RomData.read(client)
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        loop = AgentLoop(gamepad)
        nora, holds, stalls = NoraAttackTracker(), HoldTracker(), GrabStallTracker()

        trace = open(args.trace, "w", encoding="utf-8") if args.trace else None
        history: deque = deque(maxlen=HISTORY_TICKS)
        deaths: list[dict] = []
        prev_lives = None
        deadline = time.monotonic() + args.seconds
        last_report = 0.0

        while time.monotonic() < deadline and len(deaths) < args.deaths:
            started = time.monotonic()
            snap = read_snapshot(client, rom=rom)
            playable = any(p.is_playable for p in snap.players)

            if scenario.level_jump_pending:
                if playable:
                    scenario.apply_start_level(client)
                time.sleep(poll_s)
                continue

            verb = loop.tick(snap, player_index=1)
            if not playable or snap.level_index != level_index:
                if trace is not None:
                    trace.write(
                        json.dumps(
                            {
                                "t": round(started, 2),
                                "off_target": True,
                                "level": snap.level_index,
                                "wave": snap.wave,
                                "state": snap.game_mode,
                                "lives": snap.players[0].lives,
                                "timer": snap.time_left,
                            }
                        )
                        + "\n"
                    )
                    trace.flush()
                if snap.level_index == 0 and not playable:
                    print("reset detected; stopping", flush=True)
                    break
                if started - last_report > 10.0:
                    last_report = started
                    print(
                        f"off-target: level={snap.level_index} playable={playable} "
                        f"lives={snap.players[0].lives} state={snap.game_mode!r}",
                        flush=True,
                    )
                time.sleep(max(0.0, poll_s - (time.monotonic() - started)))
                continue
            scenario.sweep_other_families(client)

            p1 = snap.players[0]
            context = generate_direct_observation_tokens(
                snap,
                player_index=1,
                nora_tracker=nora,
                hold_tracker=holds,
                grab_stall_tracker=stalls,
            )
            actor = find(context, Myself)
            pits = [
                {
                    "x": pit.world_x,
                    "lane_y": pit.lane_y,
                    "w": pit.width,
                    "h": pit.height,
                    "endangers_actor": bool(
                        actor is not None
                        and pit_endangers(pit, actor.world_x, actor.world_y)
                    ),
                }
                for pit in find_all(context, Pit)
            ]
            row = {
                "t": round(started, 2),
                "x": actor.world_x if actor else None,
                "y": actor.world_y if actor else None,
                "hp": p1.health,
                "lives": p1.lives,
                "verb": type(verb).__name__ if verb else None,
                "action": f"${actor.action_state:02X}" if actor else None,
                "phase": (
                    player_phase(
                        action_byte=actor.action_state,
                        held_type=actor.held_weapon_type,
                    ).name
                    if actor
                    else None
                ),
                "airborne": bool(actor.is_airborne) if actor else None,
                "pits": pits,
            }
            row["wave"] = snap.wave
            row["timer"] = snap.time_left
            row["clock_stopped"] = snap.clock_stopped
            row["level"] = snap.level_index
            history.append(row)
            if trace is not None:
                trace.write(json.dumps(row) + "\n")

            if (
                p1.lives is not None
                and prev_lives is not None
                and p1.lives < prev_lives
            ):
                deaths.append({"at": row, "history": list(history)})
                print(
                    f"death {len(deaths)}: x={row['x']} y={row['y']} hp={row['hp']} "
                    f"verb={row['verb']} action={row['action']} pits={len(pits)} "
                    f"endangered={[p for p in pits if p['endangers_actor']]}",
                    flush=True,
                )
            if p1.lives is not None:
                prev_lives = p1.lives

            if started - last_report > 10.0:
                last_report = started
                print(
                    f"walking: x={row['x']} y={row['y']} hp={row['hp']} "
                    f"lives={row['lives']} verb={row['verb']} pits={len(pits)}",
                    flush=True,
                )
            time.sleep(max(0.0, poll_s - (time.monotonic() - started)))

        if trace is not None:
            trace.close()
        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001
            pass

        with open(args.out, "w", encoding="utf-8") as sink:
            json.dump({"deaths": deaths}, sink, indent=1)
        print(json.dumps({"deaths_caught": len(deaths), "out": args.out}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
