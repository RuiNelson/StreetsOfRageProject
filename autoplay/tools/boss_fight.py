"""Play a level for real under ``--turbo``, then score the boss fight.

Deliberately **no RAM writes** beyond the host's own documented debug
hotkeys (``debug_scenario.DebugScenario``'s level-select and per-family kill
cheats -- the same buttons a human presses with ``--debugUtils``). An
earlier version of this harness poked the player's own X and health every
tick to fast-forward to the boss; that corrupted wave progression and left
the game visibly broken. This one lets the real ``AgentLoop`` walk the
level, through ``ai/gamepad.py`` and nothing else, which ``--turbo 2`` makes
affordable -- the same pairing ``scripts/both_turbo`` uses.

Boss death is read from ``phases.boss_phase``'s own ``DEATH`` decode
(primary ``$05``, or ``>=$0C`` for the ``$55``-``$58`` family) via
``MapEntity.combat_phase``, corroborated by ``MapEntity.is_defeated`` (the
signed health check) -- never "the tracked object disappeared", which is
also what a level reset looks like and produced a false "boss defeated"
report once already.

Run (host already up with ``--debugUtils``, e.g.
``./scripts/run --turbo 2 --lang en --debugUtils --port 7777 --silent``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/boss_fight.py --out /tmp/fight.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter

from megadrive_remote import MegaDriveClient

from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.phases import player_phase
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot
from sor_autoplay.world_map import MapEntity

PLAYER_MAX_HEALTH = 80


def find_boss(snapshot, type_id: int) -> MapEntity | None:
    if not snapshot.world_map:
        return None
    for entity in snapshot.world_map.entities:
        if entity.type_id == type_id and entity.kind == "boss":
            return entity
    return None


def boss_is_dead(entity: MapEntity) -> bool:
    """The raw signed health word, and *only* that -- not the phase decode,
    not ``MapEntity.is_defeated``, and not "the object vanished".

    ``phases.boss_phase`` decodes primary ``$05`` as ``DEATH`` for the
    ``$55``-``$58`` family ("shared lethal gate", ``$164FC``) -- a **false
    positive** confirmed twice live: a trace caught ``boss_state`` step
    ``3 -> 5`` for exactly one poll at 25 of 32 health, then again at 29 of
    32, neither remotely dead, before it would have bounced back on the very
    next tick. ``$164FC`` is visited transiently on *every* hit to test
    lethality, not only a fatal one, and a poll landing on that tick
    misreads it as death.

    The obvious fallback, ``MapEntity.is_defeated``, turned out to inherit
    the identical bug through a different door: its own body is
    ``if self.combat_phase == CombatPhase.DEATH: return True`` *before* the
    signed-health check, so it short-circuits on the exact same false
    positive rather than fixing it -- confirmed by the second live run still
    reporting "killed" at 29/32 after switching to it. The only signal left
    that cannot flicker on a transient state is the raw word this function
    reads directly: ``$8000``-``$FFFF`` has crossed ROM's own signed lethal
    boundary, and a value like 29 or 25 is nowhere near it.

    "The tracked slot is empty" is not checked either: that is what a level
    reset looks like too, and it produced a false "boss defeated" report
    once before any of this existed.

    Both ``phases.boss_phase``'s and ``MapEntity.is_defeated``'s DEATH
    misclassification are real latent bugs worth fixing at the source (needs
    disassembling ``$164FC`` itself to name its real states), but that is
    out of scope here -- this function only has to not be fooled by them.
    """

    return entity.health is not None and entity.health >= 0x8000


def player_bucket(action_state: int, held_type: int) -> str:
    """Classify a tick with no winning verb: hitstun, knockdown, holding,
    attacking, or genuinely idle -- ``phases.player_phase``'s own decode,
    not a new one, so this can never disagree with what the rest of the
    pipeline already believes about the player's state.
    """

    return player_phase(action_byte=action_state, held_type=held_type).name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--level", type=int, default=2, help="1-based, for the host cheat")
    ap.add_argument("--boss-type", type=lambda s: int(s, 0), default=0x55)
    ap.add_argument("--seconds", type=float, default=600.0)
    ap.add_argument("--poll-ms", type=int, default=16)
    ap.add_argument("--character", default="axel")
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
        loop = AgentLoop(gamepad)

        boss_seen = False
        start_hp = start_lives = None
        min_hp = None
        lives_lost = 0
        last_lives = None
        boss_hp_start = boss_hp_min = None
        fight_ticks = 0
        fight_started = None
        no_verb_buckets: Counter[str] = Counter()
        verb_counts: Counter[str] = Counter()
        end_state = "timeout"

        deadline = time.monotonic() + args.seconds
        with open(args.out, "w", encoding="utf-8") as sink:
            while time.monotonic() < deadline:
                started = time.monotonic()
                snap = read_snapshot(client, rom=rom)
                playable = any(p.is_playable for p in snap.players)

                if scenario.level_jump_pending:
                    # Held off exactly as long as app.py._apply_scenario
                    # holds the AI off: a verb decided during the level
                    # intro is aimed at the scene the jump is about to throw
                    # away. loop.tick() is not called here on purpose.
                    if playable:
                        scenario.apply_start_level(client)
                    time.sleep(poll_s)
                    continue

                # Past the jump, loop.tick() runs on *every* remaining tick,
                # never skipped for "not playable" or "wrong level". Gating
                # it the way app.py's own _apply_scenario does post-jump
                # (return False, skip the tick, whenever not playable or off
                # the target level) hung this harness completely the first
                # time it ran: after any death before the boss was reached,
                # the actor sat on the continue/name-entry UI -- is_playable
                # False -- and with the tick skipped, AgentLoop never got the
                # chance to answer it (loop.py's own docstring: the
                # not-playable gate deliberately does *not* fire on that
                # screen, precisely so it can). The run went essentially
                # idle and produced zero rows before its timeout. Only a
                # confirmed level change while the boss was already alive is
                # treated as a real reset below, after the tick.
                verb = loop.tick(snap, player_index=1)
                if not playable or snap.level_index != level_index:
                    if boss_seen:
                        end_state = "level_reset"
                        break
                    time.sleep(max(0.0, poll_s - (time.monotonic() - started)))
                    continue
                scenario.sweep_other_families(client)
                p1 = snap.players[0]
                entities = snap.world_map.entities if snap.world_map else ()
                p1_entity = next(
                    (e for e in entities if e.kind == "player" and e.slot == "P1"),
                    None,
                )
                boss = find_boss(snap, args.boss_type)

                if boss is not None and not boss_seen:
                    boss_seen = True
                    fight_started = started
                    start_hp, start_lives = p1.health, p1.lives
                    last_lives = p1.lives
                    boss_hp_start = boss.health
                    print(f"boss up: hp={start_hp} lives={start_lives}", flush=True)

                if not boss_seen:
                    time.sleep(max(0.0, poll_s - (time.monotonic() - started)))
                    continue

                fight_ticks += 1
                if p1.health is not None:
                    min_hp = p1.health if min_hp is None else min(min_hp, p1.health)
                if boss is not None and boss.health is not None:
                    boss_hp_min = (
                        boss.health if boss_hp_min is None else min(boss_hp_min, boss.health)
                    )
                if p1.lives is not None and last_lives is not None and p1.lives < last_lives:
                    lives_lost += last_lives - p1.lives
                if p1.lives is not None:
                    last_lives = p1.lives

                verb_name = type(verb).__name__ if verb else None
                verb_counts[verb_name or "None"] += 1
                if verb is None and p1_entity is not None:
                    no_verb_buckets[player_bucket(p1_entity.action_state, p1_entity.held_type)] += 1

                sink.write(
                    json.dumps(
                        {
                            "t": round(started - fight_started, 3),
                            "hp": p1.health,
                            "lives": p1.lives,
                            "p1_action_state": p1_entity.action_state if p1_entity else None,
                            "p1_phase_bucket": (
                                player_bucket(p1_entity.action_state, p1_entity.held_type)
                                if p1_entity is not None
                                else None
                            ),
                            "boss_hp": boss.health if boss else None,
                            "boss_phase": (
                                boss.combat_phase.name if boss and boss.combat_phase else None
                            ),
                            "boss_state": boss.action_state if boss else None,
                            "boss_tactical": getattr(boss, "tactical", None) if boss else None,
                            "verb": verb_name,
                        }
                    )
                    + "\n"
                )

                if boss is not None and boss_is_dead(boss):
                    end_state = "killed"
                    break

                remaining = poll_s - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)

        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001
            pass

        damage = None
        if start_hp is not None and min_hp is not None:
            damage = (start_hp - min_hp) + lives_lost * PLAYER_MAX_HEALTH
        summary = {
            "character": args.character,
            "boss_seen": boss_seen,
            "end_state": end_state,
            "player_died": lives_lost > 0,
            "lives_lost_during_fight": lives_lost,
            "start_hp": start_hp,
            "min_hp": min_hp,
            "damage_taken": damage,
            "damage_pct_of_one_bar": (
                round(100.0 * damage / PLAYER_MAX_HEALTH, 1) if damage is not None else None
            ),
            "boss_hp": [boss_hp_start, boss_hp_min],
            "fight_ticks": fight_ticks,
            "fight_seconds": (
                round(time.monotonic() - fight_started, 1) if fight_started else None
            ),
            "verb_counts": dict(verb_counts),
            "no_verb_ticks": sum(no_verb_buckets.values()),
            "no_verb_buckets": dict(no_verb_buckets),
        }
        print(json.dumps(summary), flush=True)
    return 0 if boss_seen else 2


if __name__ == "__main__":
    sys.exit(main())
