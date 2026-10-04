"""Score round 5's twins with two AI players.

P1 reaches gameplay as ``--character``, the host's level cheat jumps to
round 5 with the street families swept (``DebugScenario``, the host's own
debug hotkeys -- no RAM writes), and P2 joins the way a second player does:
Start on pad 2 (``$115CC``, ``update_join_and_continue_hud``; not on round
8). Both seats then run their own ``AgentLoop`` on one shared pad state, as
``--agent-p1 --agent-p2`` does, each other's ``Partner``. Food and the
police are off, as in every scored boss fight.

The summary: both twins killed or not, the fight's wall time, hits and lives
lost per player, and where the two stood -- how many ticks each was the
left or the right one, and the share of ticks they were 160 px or more apart
(the camera is 256 px wide between the clamps), the rule under test being
one player per edge (user, see ``autoplay/CLAUDE.md``, **Two players
against the twins**).

Run against a fresh host per fight (``--turbo 2 --silent --debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/twins_2p_fight.py --out /tmp/twins_2p.jsonl
"""

from __future__ import annotations

import argparse
import json
import time

from megadrive_remote import MegaDriveClient

from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot

START_MASK = 0x0080
TWIN_TYPE = 0x58
ROUND_5_INDEX = 4
# Start on pad 2 is re-sent this often until P2 is playable.
JOIN_RETRY_S = 1.5
APART_PX = 160


def _signed(health: int | None) -> int:
    health = health or 0
    return health - 0x10000 if health >= 0x8000 else health


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--seconds", type=float, default=420.0)
    ap.add_argument("--poll-ms", type=int, default=16)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    poll_s = args.poll_ms / 1000.0

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=5, kill_street_enemies=True)
    with MegaDriveClient(host=args.host, port=args.port) as client:
        rom = RomData.read(client)
        state = SharedGamepadState(client)
        loops = {
            i: AgentLoop(VirtualGamepad(state, player_index=i), no_food=True, no_police=True)
            for i in (1, 2)
        }
        deadline = time.monotonic() + args.seconds
        last_join = last_report = 0.0
        fight_t0: float | None = None
        twin_hp: dict[str, int] = {}
        dead: set[str] = set()
        hits = {1: 0, 2: 0}
        lives_lost = {1: 0, 2: 0}
        prev: dict[int, tuple[int | None, int]] = {}
        sides = {1: {"left": 0, "right": 0}, 2: {"left": 0, "right": 0}}
        ticks = apart = 0
        end = "timeout"
        with open(args.out, "w", encoding="utf-8") as sink:
            while time.monotonic() < deadline:
                started = time.monotonic()
                snap = read_snapshot(client, rom=rom)
                playable = [p.is_playable for p in snap.players]
                if scenario.level_jump_pending:
                    if any(playable):
                        scenario.apply_start_level(client)
                    time.sleep(poll_s)
                    continue
                if (
                    snap.level_index == ROUND_5_INDEX
                    and playable[0]
                    and not playable[1]
                    and fight_t0 is None
                    and started - last_join > JOIN_RETRY_S
                ):
                    client.press_buttons(player2=START_MASK, frames=3)
                    last_join = started
                verbs: dict[int, str | None] = {}
                for i in (1, 2):
                    player = snap.players[i - 1]
                    if player.is_playable or player.is_continue_ui:
                        verb = loops[i].tick(snap, player_index=i)
                        verbs[i] = type(verb).__name__ if verb is not None else None
                scenario.note_snapshot(snap)
                scenario.sweep_other_families(client)
                entities = snap.world_map.entities if snap.world_map else ()
                twins = [e for e in entities if e.type_id == TWIN_TYPE and e.kind in ("boss", "enemy")]
                if started - last_report > 10.0:
                    last_report = started
                    print(
                        f"level={snap.level_index} playable={playable} "
                        f"twins={[(e.slot, _signed(e.health)) for e in twins]}",
                        flush=True,
                    )
                if fight_t0 is None:
                    if twins and all(playable):
                        fight_t0 = started
                        prev = {i: (snap.players[i - 1].health, snap.players[i - 1].lives) for i in (1, 2)}
                        print("twins up", flush=True)
                    else:
                        time.sleep(max(0.0, poll_s - (time.monotonic() - started)))
                        continue
                for twin in twins:
                    twin_hp[twin.slot] = _signed(twin.health)
                    if twin_hp[twin.slot] <= 0:
                        dead.add(twin.slot)
                players = {e.slot: e for e in entities if e.kind == "player"}
                row: dict[str, object] = {
                    "t": round(started - fight_t0, 3),
                    "cam": snap.world_map.camera_x if snap.world_map else None,
                    "twins": [
                        (e.slot, e.world_x, e.world_y, _signed(e.health), e.targets_player) for e in twins
                    ],
                }
                xs: dict[int, int] = {}
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
                    prev[i] = (player.health, player.lives)
                    entity = players.get(f"P{i}")
                    if entity is not None:
                        xs[i] = entity.world_x
                        row[f"P{i}"] = (entity.world_x, entity.world_y, player.health, player.lives, verbs.get(i))
                if len(xs) == 2:
                    ticks += 1
                    if xs[1] != xs[2]:
                        left = 1 if xs[1] < xs[2] else 2
                        sides[left]["left"] += 1
                        sides[3 - left]["right"] += 1
                    if abs(xs[1] - xs[2]) >= APART_PX:
                        apart += 1
                sink.write(json.dumps(row) + "\n")
                if len(twin_hp) >= 2 and twin_hp.keys() <= dead:
                    end = "killed"
                    break
                if not any(playable) and not any(p.is_continue_ui for p in snap.players):
                    end = "lost"
                    break
                time.sleep(max(0.0, poll_s - (time.monotonic() - started)))
        client.hold_buttons(player1=0, player2=0)
        print(
            json.dumps(
                {
                    "end": end,
                    "fight_s": round(time.monotonic() - fight_t0, 1) if fight_t0 else None,
                    "twins_hp": twin_hp,
                    "hits": hits,
                    "lives_lost": lives_lost,
                    "apart_share": round(apart / ticks, 3) if ticks else None,
                    "sides": sides,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
