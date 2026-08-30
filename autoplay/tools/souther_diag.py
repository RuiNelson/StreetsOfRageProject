"""Diagnose the round-2 Souther fight tick by tick.

Same shape as ``tools/antonio_diag.py``: runs the **real** pipeline against a
live host and logs one JSON row per tick while the boss is up, so a stall in
the grab chain (``GrabEnemy`` at or near zero ticks) can be traced to the
actual dx/dy/verb sequence rather than guessed at from a summary.

Run (host already up with ``--debugUtils``, e.g.
``./scripts/run --turbo 4 --lang en --debugUtils --port 7777 --silent``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/souther_diag.py --out /tmp/souther.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from megadrive_remote import MegaDriveClient

from sor_autoplay.ai import reach
from sor_autoplay.ai.decide import _blocked, _is_holding_enemy, generate_verb_tokens
from sor_autoplay.ai.execute import _lane_offset_while_closing, _souther_pocket_stop_dx, execute_tick
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.inference import generate_inference_tokens
from sor_autoplay.ai.observe import (
    HoldTracker,
    NoraAttackTracker,
    generate_direct_observation_tokens,
)

# Private on purpose: the per-verb score is exactly what this tool exists to
# show, and re-deriving it here would risk disagreeing with the pipeline.
from sor_autoplay.ai.priority import _emergency, determine_priority_verb
from sor_autoplay.ai.tokens import Boss, DebugNoFood, Enemy, Myself, Verb, find, find_all
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot

SOUTHER_TYPE = 0x55


def boss_is_dead(entity) -> bool:
    """The raw signed health word, and *only* that.

    Identical to ``tools/boss_fight.py``'s own ``boss_is_dead`` -- see that
    function's docstring for why the phase decode and ``is_defeated`` both
    false-positive on the transient ``$164FC`` lethality test. Duplicated
    rather than imported because ``boss_fight.py`` is a ``__main__`` script,
    not a module this tool should import from.
    """

    return entity.health is not None and entity.health >= 0x8000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--level", type=int, default=2)
    ap.add_argument("--boss-type", type=lambda s: int(s, 0), default=SOUTHER_TYPE)
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--poll-ms", type=int, default=8)
    ap.add_argument(
        "--fight-seconds",
        type=float,
        default=60.0,
        help=(
            "Hard cap after the boss first appears (default 60): stops even "
            "if the boss is neither dead nor reset by then. The real stop "
            "conditions are the boss's death and a level reset, both checked "
            "every tick -- this is only the backstop."
        ),
    )
    ap.add_argument("--no-food", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    poll_s = args.poll_ms / 1000.0
    level_index = args.level - 1

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=args.level, kill_street_enemies=True)

    with MegaDriveClient(host=args.host, port=args.port) as client:
        rom = RomData.read(client)
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        nora_tracker = NoraAttackTracker()
        hold_tracker = HoldTracker()

        rows = 0
        boss_seen = False
        boss_deadline: float | None = None
        deadline = time.monotonic() + args.seconds
        end_state = "timeout"

        with open(args.out, "w", encoding="utf-8") as sink:
            while time.monotonic() < deadline:
                started = time.monotonic()
                snap = read_snapshot(client, rom=rom)
                player = snap.players[0]

                # A real reset (game over -> continue -> restart, or a level
                # change), not the brief continue *prompt* itself -- that is
                # answered in place (bde71b6) and must not stop this loop.
                # Mirrors tools/boss_fight.py's own level_reset check.
                if (
                    boss_seen
                    and not player.is_playable
                    and not player.is_continue_ui
                    and snap.level_index != level_index
                ):
                    end_state = "level_reset"
                    print("level reset after the boss was seen - stopping", flush=True)
                    break

                if scenario.level_jump_pending:
                    if player.is_playable:
                        scenario.apply_start_level(client)
                    time.sleep(poll_s)
                    continue

                in_continue_ui = player.is_continue_ui
                if snap.paused or (
                    not in_continue_ui and (not snap.timer_valid or not player.is_playable)
                ):
                    gamepad.release()
                    time.sleep(poll_s)
                    continue
                if snap.level_index == level_index:
                    scenario.sweep_other_families(client)

                context = generate_direct_observation_tokens(
                    snap, player_index=1, nora_tracker=nora_tracker, hold_tracker=hold_tracker
                )
                if args.no_food:
                    context = context | {DebugNoFood()}
                context |= generate_inference_tokens(context)
                context |= generate_verb_tokens(context)
                pending = tuple(find_all(context, Verb))
                scored = sorted(
                    ((_emergency(v, context), v.priority, type(v).__name__) for v in pending),
                    reverse=True,
                )
                context = determine_priority_verb(context)
                verbs = find_all(context, Verb)
                verb = verbs[0] if verbs else None
                execute_tick(verb, context, gamepad, route_trace={})

                boss = next(
                    (b for b in find_all(context, Boss) if b.type_id == args.boss_type),
                    None,
                )
                if boss is None:
                    time.sleep(max(0.0, poll_s - (time.monotonic() - started)))
                    continue
                if not boss_seen:
                    boss_seen = True
                    boss_deadline = started + args.fight_seconds
                    print("boss up", flush=True)

                me = find(context, Myself)
                enemies = reach.live_enemies(context)
                dx = (boss.world_x - me.world_x) if me else None
                dy = (boss.world_y - me.world_y) if me else None
                row = {
                    "t": round(started - (boss_deadline - args.fight_seconds), 3),
                    "hp": player.health,
                    "lives": player.lives,
                    "p1_x": me.world_x if me else None,
                    "p1_y": me.world_y if me else None,
                    "p1_facing_left": me.facing_left if me else None,
                    "p1_action": hex(me.action_state) if me else None,
                    "p1_held": hex(me.held_weapon_type) if me else None,
                    "p1_phase": me.combat_phase.name if me else None,
                    "is_holding_enemy": _is_holding_enemy(me) if me else None,
                    "blocked": _blocked(context, me) if me else None,
                    "held_mask": hex(gamepad.held),
                    "boss_x": boss.world_x,
                    "boss_y": boss.world_y,
                    "boss_hp": boss.health,
                    "boss_primary": boss.primary_state,
                    "boss_tactical": boss.tactical,
                    "boss_grabbable": boss.primary_state in reach.SOUTHER_GRABBABLE_PRIMARIES,
                    "boss_committed": boss.strike_is_committed() if hasattr(boss, "strike_is_committed") else None,
                    "boss_phase": boss.combat_phase.name if boss.combat_phase else None,
                    "dx": dx,
                    "dy": dy,
                    "lane_offset_gate": (
                        _lane_offset_while_closing(me, boss) if me is not None else None
                    ),
                    "pocket_stop_dx": (
                        _souther_pocket_stop_dx(me, boss, 999) if me is not None else None
                    ),
                    "grab_reasons": (
                        sorted(r.name for r in reach.grab_reasons(context, me, boss, enemies))
                        if me is not None
                        else None
                    ),
                    "grab_would_connect": (
                        reach.grab_would_connect(me, boss) if me is not None else None
                    ),
                    "verb": type(verb).__name__ if verb else None,
                    "pending": [[s, p, n] for s, p, n in scored],
                    "enemy_slots": sorted(e.slot for e in find_all(context, Enemy)),
                }
                sink.write(json.dumps(row) + "\n")
                rows += 1

                if boss_is_dead(boss):
                    end_state = "killed"
                    print("boss defeated - stopping", flush=True)
                    break
                if boss_deadline is not None and started > boss_deadline:
                    end_state = "fight_seconds_elapsed"
                    print("fight window elapsed (backstop)", flush=True)
                    break

                remaining = poll_s - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)

        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001
            pass

    print(f"done ({end_state}): {rows} rows -> {args.out}", flush=True)
    return 0 if rows else 2


if __name__ == "__main__":
    sys.exit(main())
