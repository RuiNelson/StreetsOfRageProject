"""Score Mr. X's betrayal duel with two AI players.

P1 reaches gameplay as ``--character`` and P2 joins on round 1 with Start on
pad 2 (``$115CC`` refuses a join on round 8); then the host's level cheat
jumps to round 8 and ``--kill-until-mr-x`` sweeps it up to the office
(``DebugScenario``, the host's own hotkeys -- no RAM writes). Both seats run
their own ``AgentLoop``; the ``--accept`` seat carries the harness's
``DebugMrXAccept`` and answers YES, the other NO, so ``$11F74
(mr_x_offer_compare_2p_choices)`` starts the duel (``$11FA8``, ``$FFFA43``
set). Food and the police are off.

``--blind P`` hides the duel from seat P (its snapshots read ``$FFFA43`` as
0), which is the AI before ``PlayerDuel``: the baseline. ``--cold P`` (repeatable)
turns seat P's duel style off (``AgentLoop(duel_style=False)``): the generic
pipeline's efficient fight, the AI before ``duel.DuelStyle``. Each row also
carries the seat's style tactic.

The summary: whether the duel started, its wall time, the damage each seat
dealt and took (hits and lives), who was out when ``$11E72
(mr_x_offer_wait_duel_end)`` cleared the byte, and the survivor's answer --
``$FFDE10 (bad_ending_selected)`` set is the post-duel NO, round 6 the YES.

Run against a fresh host per fight (``--turbo 2 --silent --debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/mr_x_duel_fight.py --out /tmp/duel.jsonl
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time

from sor_autoplay.sor_remote import SoRClient

from sor_autoplay import memory_map as mm
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot

START_MASK = 0x0080
ROUND_8_INDEX = 7
ROUND_6_INDEX = 5
# Start on pad 2 is re-sent this often until P2 is playable.
JOIN_RETRY_S = 1.5
# After the duel, how long to wait for the survivor's answer to land.
AFTER_DUEL_S = 60.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--seconds", type=float, default=600.0)
    ap.add_argument("--poll-ms", type=int, default=16)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--accept", type=int, choices=(1, 2), default=2)
    ap.add_argument("--blind", type=int, choices=(1, 2), default=None)
    ap.add_argument("--cold", type=int, choices=(1, 2), action="append", default=[])
    ap.add_argument(
        "--duel-seconds",
        type=float,
        default=None,
        help="End the run this long into the duel (an AI continues at game over, so a duel between two can run on for many minutes)",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    poll_s = args.poll_ms / 1000.0

    with SoRClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=8, kill_until_mr_x=True)
    with SoRClient(host=args.host, port=args.port) as client:
        rom = RomData.read(client)
        state = SharedGamepadState(client)
        loops = {
            i: AgentLoop(
                VirtualGamepad(state, player_index=i),
                no_food=True,
                no_police=True,
                mr_x_accept=args.accept == i,
                duel_style=i not in args.cold,
            )
            for i in (1, 2)
        }
        deadline = time.monotonic() + args.seconds
        last_join = last_report = 0.0
        duel_t0: float | None = None
        duel_t1: float | None = None
        hits = {1: 0, 2: 0}
        lives_lost = {1: 0, 2: 0}
        damage_taken = {1: 0, 2: 0}
        prev: dict[int, tuple[int | None, int]] = {}
        verb_counts: dict[int, dict[str, int]] = {1: {}, 2: {}}
        out_at_end: dict[int, bool] = {}
        end = "timeout"
        with open(args.out, "w", encoding="utf-8") as sink:
            while time.monotonic() < deadline:
                started = time.monotonic()
                snap = read_snapshot(client, rom=rom)
                playable = [p.is_playable for p in snap.players]
                if not all(playable) and duel_t0 is None and snap.level_index != ROUND_8_INDEX:
                    if playable[0] and started - last_join > JOIN_RETRY_S:
                        client.press_buttons(player2=START_MASK, frames=3)
                        last_join = started
                elif scenario.level_jump_pending:
                    scenario.apply_start_level(client)
                    time.sleep(poll_s)
                    continue
                duel = bool(snap.mr_x_offer_flag and snap.duel_damage_modifier)
                verbs: dict[int, str | None] = {}
                for i in (1, 2):
                    player = snap.players[i - 1]
                    if player.is_playable or player.is_continue_ui:
                        seen = snap
                        if args.blind == i:
                            seen = dataclasses.replace(snap, duel_damage_modifier=0)
                        verb = loops[i].tick(seen, player_index=i)
                        verbs[i] = type(verb).__name__ if verb is not None else None
                scenario.note_snapshot(snap)
                scenario.sweep_other_families(client)
                if started - last_report > 10.0:
                    last_report = started
                    print(
                        f"level={snap.level_index} playable={playable} offer={snap.mr_x_offer_flag} "
                        f"state=${snap.mr_x_offer_state:02X} duel={int(duel)} verbs={verbs}",
                        flush=True,
                    )
                if duel and duel_t0 is None:
                    duel_t0 = started
                    prev = {i: (snap.players[i - 1].health, snap.players[i - 1].lives) for i in (1, 2)}
                    print("duel started", flush=True)
                if duel_t0 is None:
                    time.sleep(max(0.0, poll_s - (time.monotonic() - started)))
                    continue
                if duel:
                    for i in (1, 2):
                        player = snap.players[i - 1]
                        last_health, last_lives = prev[i]
                        if player.lives < last_lives:
                            lives_lost[i] += last_lives - player.lives
                        elif (
                            player.health is not None
                            and last_health is not None
                            and player.health < last_health
                        ):
                            hits[i] += 1
                            damage_taken[i] += last_health - player.health
                        prev[i] = (player.health, player.lives)
                        if verbs.get(i):
                            verb_counts[i][verbs[i]] = verb_counts[i].get(verbs[i], 0) + 1
                elif duel_t1 is None:
                    duel_t1 = started
                    out_at_end = {i: not snap.players[i - 1].is_playable for i in (1, 2)}
                    print(f"duel over, out={out_at_end}", flush=True)
                entities = snap.world_map.entities if snap.world_map else ()
                players = {e.slot: e for e in entities if e.kind == "player"}
                row: dict[str, object] = {
                    "t": round(started - duel_t0, 3),
                    "state": snap.mr_x_offer_state,
                    "duel": int(duel),
                }
                for i in (1, 2):
                    player = snap.players[i - 1]
                    entity = players.get(f"P{i}")
                    row[f"P{i}"] = (
                        entity.world_x if entity else None,
                        entity.world_y if entity else None,
                        player.health,
                        player.lives,
                        verbs.get(i),
                        entity.facing_left if entity else None,
                        entity.action_state if entity else None,
                        loops[i].duel_tactic,
                    )
                sink.write(json.dumps(row) + "\n")
                if duel and args.duel_seconds is not None and started - duel_t0 > args.duel_seconds:
                    end = "duel_timeout"
                    break
                if duel_t1 is not None:
                    if snap.level_index == ROUND_6_INDEX:
                        end = "round6_restart"
                        break
                    if client.read_memory(mm.ADDR_BAD_ENDING_SELECTED, 1)[0]:
                        end = "bad_ending_selected"
                        break
                    if started - duel_t1 > AFTER_DUEL_S:
                        end = "no_answer"
                        break
                time.sleep(max(0.0, poll_s - (time.monotonic() - started)))
        client.hold_buttons(player1=0, player2=0)
        print(
            json.dumps(
                {
                    "end": end,
                    "accept": args.accept,
                    "blind": args.blind,
                    "cold": args.cold,
                    "duel_s": round((duel_t1 or time.monotonic()) - duel_t0, 1) if duel_t0 else None,
                    "hits_taken": hits,
                    "damage_taken": damage_taken,
                    "lives_lost": lives_lost,
                    "out": out_at_end,
                    "verbs": {i: dict(sorted(v.items(), key=lambda kv: -kv[1])[:6]) for i, v in verb_counts.items()},
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
