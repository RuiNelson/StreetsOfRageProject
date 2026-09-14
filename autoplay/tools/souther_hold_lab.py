"""Measure, frame by frame, what each way of ending a Souther hold costs.

A lockstep lab for the round-2 fight, in the shape of
``tools/hold_timing_diag.py``: the real ``AgentLoop`` plays round 2 (street
waves swept) until it is holding Souther, then the host goes into lockstep and
one scripted experiment runs from that hold with every frame logged. Between
experiments lockstep is released and the AI takes the next hold itself.

The experiments answer the questions the disassembly raises but cannot settle
on its own (see ``autoplay/CLAUDE.md``, "Souther: the ROM model"):

``second_crossover``
    knee, knee, C, C. ``$26E2`` sets the player's ``+$4B`` bit 7 on a
    crossover's frame 6 and branches to its failure path when that bit is
    already set; only a fresh grab (``$3266``) clears it. So the second
    crossover of one hold should drop the body.
``release_regrab``
    knee, knee, then hold *back* until ``loc_235A``'s ``+$63`` countdown
    releases the hold, then walk *toward* him at once (``--regrab-delay``
    frames of nothing in between). Does the walk-in re-take the hold before
    ``$15EDA`` commits, and does the grab contact pre-empt his claw box?
``release_loop``
    ``release_regrab`` repeated from one hold until he dies or a re-grab is
    lost -- the whole candidate strategy, with the same ``--regrab-delay``.
``throw``
    knee, knee, B+back. Blaze's throw is ``$64`` -> Souther primary ``$08``
    for 50 frames, then ``$05`` for 8 -- against 46 frames of her own throw.
``suplex``
    knee, knee, C, B. The suplex is primary ``$07`` for 45 frames, then ``$05``
    for 8 -- against the player's own 78.

Every experiment first tops the knee chain up to exactly two knees
(``+$58`` bit 6 and ``+$61``, see ``chain_stage``), so a hold the AI had
already kneed from is not mistaken for a fresh one -- a third B there is the
``$6E`` knockback, which ends the hold.

Every row carries both objects' raw fields (action/primary, timers, the
``+$66`` hold word, health, position, box ids and the player's cached boxes),
so the numbers in the summary can be re-derived from the log.

Run (host already up with ``--debugUtils``, e.g.
``./scripts/run --turbo 4 --lang en --debugUtils --port 7777 --silent``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/souther_hold_lab.py --out /tmp/lab.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from megadrive_remote import Buttons, MegaDriveClient

from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.memory_map import (
    ACTION_HOLDING,
    ADDR_OBJECT_TABLE,
    ADDR_P1_OBJECT,
    OBJECT_SLOT_SIZE,
    OBJECT_TABLE_SLOTS,
)
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot

WORK_RAM_BASE = 0xFF0000
SOUTHER_TYPE = 0x55
STABLE_FRONT = frozenset({0x60, 0x61})
STABLE_BACK = frozenset({0x66, 0x67})
STABLE_HOLDS = STABLE_FRONT | STABLE_BACK
# Player hurt/knockdown family (player-health-lives-and-combat.md).
PLAYER_HURT_LOW, PLAYER_HURT_HIGH = 0x50, 0x5F
MAX_STEP_FRAMES = 240
KNEE_CHAIN_BIT = 0x40  # player +$58 bit 6, set by $2BA8 on a hold's first knee


def _u8(ram: bytes, address: int, offset: int) -> int:
    return ram[(address - WORK_RAM_BASE) + offset]


def _s16(ram: bytes, address: int, offset: int) -> int:
    i = (address - WORK_RAM_BASE) + offset
    return int.from_bytes(ram[i : i + 2], "big", signed=True)


def _u16(ram: bytes, address: int, offset: int) -> int:
    i = (address - WORK_RAM_BASE) + offset
    return int.from_bytes(ram[i : i + 2], "big")


def _box(ram: bytes, address: int, offset: int) -> list[int]:
    return [_s16(ram, address, offset + 2 * k) for k in range(6)]


def souther_address(ram: bytes) -> int | None:
    for index in range(OBJECT_TABLE_SLOTS):
        address = ADDR_OBJECT_TABLE + index * OBJECT_SLOT_SIZE
        if _u8(ram, address, 0x00) == SOUTHER_TYPE and _u8(ram, address, 0x30) != 0:
            return address
    return None


def chain_stage(flags_58: int, last_knee_61: int) -> int:
    """Knees already landed in the current chain: 0, 1 or 2.

    ``$2BA8``: the first knee of a chain sets ``+$58`` bit 6 and writes
    ``$6A`` to ``+$61``; each later knee steps ``+$61`` by 2 while it stays in
    ``[$6A, $6E)``. Bit 6 survives only ``$60``/``$6A``/``$6C`` (the ``$394E``
    mask table), so any other action -- the walk before a grab, a crossover
    -- restarts the chain at knee 1.
    """

    if not flags_58 & KNEE_CHAIN_BIT:
        return 0
    if last_knee_61 == 0x6A:
        return 1
    if last_knee_61 == 0x6C:
        return 2
    return 0


def sample(ram: bytes) -> dict:
    p = ADDR_P1_OBJECT
    row = {
        "p_act": _u8(ram, p, 0x30),
        "p_frame": _u8(ram, p, 0x0A),
        "p_x": _s16(ram, p, 0x10),
        "p_y": _s16(ram, p, 0x14),
        "p_z": _s16(ram, p, 0x18),
        "p_vx": _s16(ram, p, 0x1C),
        "p_vy": _s16(ram, p, 0x20),
        "p_hp": _s16(ram, p, 0x32),
        "p_dmg": _u8(ram, p, 0x34),
        "p_4b": _u8(ram, p, 0x4B),
        "p_hold": _u16(ram, p, 0x4C),
        "p_58": _u8(ram, p, 0x58),
        "p_61": _u8(ram, p, 0x61),
        "p_63": _u8(ram, p, 0x63),
        "p_7c": _u8(ram, p, 0x7C),
        "p_7d": _u8(ram, p, 0x7D),
        "p_att": _box(ram, p, 0x64),
        "p_body": _box(ram, p, 0x70),
    }
    # Every other live combatant: the experiments run in lockstep, and a
    # street enemy walking in mid-loop is not the loop's own failure.
    others = []
    for index in range(OBJECT_TABLE_SLOTS):
        address = ADDR_OBJECT_TABLE + index * OBJECT_SLOT_SIZE
        kind = _u8(ram, address, 0x00)
        if 0x20 <= kind <= 0x2A and _u8(ram, address, 0x30) != 0:
            others.append([kind, _s16(ram, address, 0x10), _s16(ram, address, 0x14)])
    row["others"] = others
    s = souther_address(ram)
    if s is not None:
        row.update(
            {
                "s_slot": s & 0xFFFF,
                "s_pri": _u8(ram, s, 0x30),
                "s_tac": _u8(ram, s, 0x67),
                "s_62": _u8(ram, s, 0x62),
                "s_63": _u8(ram, s, 0x63),
                "s_66": _u8(ram, s, 0x66),
                "s_6d": _u8(ram, s, 0x6D),
                "s_77": _u8(ram, s, 0x77),
                "s_hp": _s16(ram, s, 0x32),
                "s_x": _s16(ram, s, 0x10),
                "s_y": _s16(ram, s, 0x14),
                "s_z": _s16(ram, s, 0x18),
                "s_anim": _u16(ram, s, 0x08),
                "s_frame": _u8(ram, s, 0x0A),
                "s_att_id": _u8(ram, s, 0x02),
                "s_body_id": _u8(ram, s, 0x03),
                "s_face_left": bool(_u8(ram, s, 0x09) & 0x02),
                "s_50": _u16(ram, s, 0x50),
                "s_52": _u16(ram, s, 0x52),
                "s_61": _u8(ram, s, 0x61),
            }
        )
    return row


class Lab:
    # Lockstep does not stop the round's own spawns, and the family sweep the
    # live loop runs twice a second is wall-clock paced -- so it is re-sent
    # here every this many emulated frames instead.
    SWEEP_EVERY_FRAMES = 30

    def __init__(
        self,
        client: MegaDriveClient,
        sink,
        *,
        experiment: str,
        scenario: DebugScenario | None = None,
    ) -> None:
        self.client = client
        self.sink = sink
        self.experiment = experiment
        self.scenario = scenario
        self.frame = 0
        self.last: dict = {}

    def step(self, buttons: int = 0) -> dict:
        if self.scenario is not None and self.frame % self.SWEEP_EVERY_FRAMES == 0:
            self.scenario.sweep_other_families(self.client, force=True)
        result = self.client.step_input(
            player1=buttons, held_frames=1 if buttons else 0, total_frames=1
        )
        self.frame += 1
        row = sample(result.work_ram)
        row["exp"] = self.experiment
        row["f"] = self.frame
        row["in"] = buttons
        self.sink.write(json.dumps(row) + "\n")
        self.last = row
        return row

    def facing_left(self) -> bool:
        return bool(self.last.get("p_act", 0) & 0x01)

    def back(self) -> int:
        return int(Buttons.RIGHT if self.facing_left() else Buttons.LEFT)

    def toward_souther(self) -> int:
        if "s_x" not in self.last:
            return self.back() ^ int(Buttons.LEFT | Buttons.RIGHT)
        return int(Buttons.RIGHT if self.last["s_x"] > self.last["p_x"] else Buttons.LEFT)

    def wait_until(self, predicate, *, buttons: int = 0, limit: int = MAX_STEP_FRAMES) -> bool:
        for _ in range(limit):
            row = self.step(buttons)
            if predicate(row):
                return True
        return False

    def press(self, buttons: int, frames: int = 2) -> None:
        for _ in range(frames):
            self.step(buttons)

    def settle_front(self) -> bool:
        return self.wait_until(lambda r: r["p_act"] in STABLE_FRONT, limit=120)

    def chain(self) -> int:
        return chain_stage(self.last.get("p_58", 0), self.last.get("p_61", 0))

    def knees_to_two(self) -> bool:
        """Knee until the chain holds exactly two knees -- never a third."""

        for _ in range(3):
            if not self.settle_front():
                return False
            if self.chain() >= 2:
                return True
            self.press(int(Buttons.B))
        return self.settle_front() and self.chain() == 2


def _holding_souther(row: dict) -> bool:
    return (
        (row["p_act"] & 0xFE) in ACTION_HOLDING
        and row["p_hold"] != 0
        and row.get("s_slot") == row["p_hold"]
    )


def _free(row: dict) -> bool:
    act = row["p_act"] & 0xFE
    return act in (0x00, 0x02) and row["p_hold"] == 0


def run_second_crossover(lab: Lab) -> dict:
    ok = lab.knees_to_two()
    lab.press(int(Buttons.C))
    reached = lab.wait_until(lambda r: r["p_act"] in STABLE_HOLDS or not _holding_souther(r))
    first = lab.last["p_act"]
    lab.press(int(Buttons.C))
    lab.wait_until(
        lambda r: r["p_act"] in STABLE_HOLDS or _free(r) or r["p_act"] in (0x14, 0x15),
        limit=120,
    )
    lab.wait_until(lambda r: False, limit=30)
    return {
        "knees_ok": ok,
        "after_first_c": f"${first:02X}" if reached else None,
        "after_second_c": f"${lab.last['p_act']:02X}",
        "still_holding": _holding_souther(lab.last),
        "souther_primary": lab.last.get("s_pri"),
    }


def _release_and_regrab(lab: Lab, *, delay: int) -> dict:
    back = lab.back()
    released = None
    for _ in range(16):
        row = lab.step(back)
        if row["p_hold"] == 0:
            released = lab.frame
            break
    if released is None:
        return {"result": "no_release"}
    dx_at_release = lab.last.get("s_x", 0) - lab.last["p_x"]
    for _ in range(delay):
        lab.step(0)
    toward = lab.toward_souther()
    regrab = committed = None
    hp0 = lab.last["p_hp"]
    for _ in range(60):
        row = lab.step(toward)
        if committed is None and row.get("s_pri") == 0x02:
            committed = lab.frame - released
        if _holding_souther(row) and row["p_act"] in STABLE_HOLDS:
            regrab = lab.frame - released
            break
        if PLAYER_HURT_LOW <= (row["p_act"] & 0xFE) <= PLAYER_HURT_HIGH:
            break
        if row.get("s_hp", 1) <= 0:
            break
    return {
        "result": "regrabbed" if regrab is not None else "lost",
        "regrab_frames": regrab,
        "committed_after": committed,
        "dx_at_release": dx_at_release,
        "player_hp_lost": hp0 - lab.last["p_hp"],
        "souther_hp": lab.last.get("s_hp"),
        "final_player_action": f"${lab.last['p_act']:02X}",
        "final_souther_primary": lab.last.get("s_pri"),
    }


def run_release_regrab(lab: Lab, *, delay: int) -> dict:
    ok = lab.knees_to_two()
    result = _release_and_regrab(lab, delay=delay)
    result["knees_ok"] = ok
    return result


def run_release_loop(lab: Lab, *, delay: int, max_cycles: int = 20) -> dict:
    """knee, knee, release, re-grab -- repeated from one hold until he dies.

    The whole of the candidate strategy in one experiment: every cycle is two
    knees (4 damage) and a hand-over that leaves him at the front hold's own
    32px, on the actor's lane, in primary 1. ``delay`` frames of no input
    are inserted between the release and the walk back in, to measure how
    much input latency the re-grab survives.
    """

    cycles = []
    hp_player0 = lab.last["p_hp"]
    for _ in range(max_cycles):
        if not lab.knees_to_two():
            cycles.append({"result": "knees_failed", "souther_hp": lab.last.get("s_hp")})
            break
        if lab.last.get("s_hp", 1) <= 0:
            cycles.append({"result": "killed"})
            break
        cycle = _release_and_regrab(lab, delay=delay)
        cycles.append(cycle)
        if cycle["result"] != "regrabbed":
            break
    return {
        "delay": delay,
        "cycles": cycles,
        "regrabs": sum(1 for c in cycles if c.get("result") == "regrabbed"),
        "player_hp_lost": hp_player0 - lab.last["p_hp"],
        "souther_hp_end": lab.last.get("s_hp"),
    }


def _watch_until_both_act(lab: Lab, *, limit: int = 200) -> dict:
    player_free = souther_active = None
    for _ in range(limit):
        row = lab.step(0)
        if player_free is None and _free(row):
            player_free = lab.frame
        if souther_active is None and row.get("s_pri") == 0x01:
            souther_active = lab.frame
        if player_free is not None and souther_active is not None:
            break
    return {
        "player_free_at": player_free,
        "souther_active_at": souther_active,
        "dx_at_active": (lab.last.get("s_x", 0) - lab.last["p_x"]),
        "dy_at_active": (lab.last.get("s_y", 0) - lab.last["p_y"]),
    }


def run_throw(lab: Lab) -> dict:
    ok = lab.knees_to_two()
    hp0 = lab.last.get("s_hp")
    start = lab.frame
    lab.press(int(Buttons.B) | lab.back())
    watched = _watch_until_both_act(lab)
    watched.update(
        {
            "knees_ok": ok,
            "start_frame": start,
            "souther_hp_lost": (hp0 or 0) - lab.last.get("s_hp", 0),
        }
    )
    return watched


def run_suplex(lab: Lab) -> dict:
    ok = lab.knees_to_two()
    lab.press(int(Buttons.C))
    lab.wait_until(lambda r: r["p_act"] in STABLE_BACK, limit=120)
    hp0 = lab.last.get("s_hp")
    start = lab.frame
    lab.press(int(Buttons.B))
    watched = _watch_until_both_act(lab)
    watched.update(
        {
            "knees_ok": ok,
            "start_frame": start,
            "souther_hp_lost": (hp0 or 0) - lab.last.get("s_hp", 0),
        }
    )
    return watched


def _holding_souther_now(client: MegaDriveClient) -> bool:
    ram_p = client.read_memory(ADDR_P1_OBJECT, OBJECT_SLOT_SIZE)
    action, hold = ram_p[0x30], int.from_bytes(ram_p[0x4C:0x4E], "big")
    if action not in STABLE_FRONT or not hold:
        return False
    return client.read_value(0xFF0000 | hold, width=1) == SOUTHER_TYPE


def reach_souther_hold(
    client: MegaDriveClient,
    loop: AgentLoop,
    rom: RomData,
    scenario: DebugScenario,
    *,
    seconds: float,
) -> bool:
    deadline = time.monotonic() + seconds
    last_report = 0.0
    while time.monotonic() < deadline:
        started = time.monotonic()
        # Checked *before* the AI's tick: the pipeline knees the instant it
        # holds anything, and the experiments want the hold before it does.
        if _holding_souther_now(client):
            return True
        snap = read_snapshot(client, rom=rom)
        playable = any(p.is_playable for p in snap.players)
        if scenario.level_jump_pending:
            if playable:
                scenario.apply_start_level(client)
            time.sleep(0.008)
            continue
        loop.tick(snap, player_index=1)
        if playable and snap.level_index == 1:
            scenario.sweep_other_families(client)
        if started - last_report > 5.0:
            last_report = started
            action = snap.players[0]
            print(f"waiting for a Souther hold: level={snap.level_index}", flush=True)
        time.sleep(max(0.0, 0.008 - (time.monotonic() - started)))
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="blaze")
    ap.add_argument(
        "--experiments",
        default="second_crossover,release_regrab,throw,suplex",
        help="comma-separated, run in order, one fresh hold each",
    )
    ap.add_argument("--regrab-delay", type=int, default=0)
    ap.add_argument("--grab-seconds", type=float, default=240.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=2, kill_street_enemies=True)
    summaries = []
    with MegaDriveClient(host=args.host, port=args.port) as client, open(
        args.out, "w", encoding="utf-8"
    ) as sink:
        rom = RomData.read(client)
        gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        loop = AgentLoop(gamepad, no_food=True, no_police=True)
        for name in [e.strip() for e in args.experiments.split(",") if e.strip()]:
            if not reach_souther_hold(client, loop, rom, scenario, seconds=args.grab_seconds):
                print(f"{name}: never reached a Souther hold", flush=True)
                break
            gamepad.release()
            client.release_buttons()
            client.set_lockstep(True, timeout_ms=10_000)
            lab = Lab(client, sink, experiment=name, scenario=scenario)
            try:
                lab.step(0)
                if name == "second_crossover":
                    summary = run_second_crossover(lab)
                elif name == "release_regrab":
                    summary = run_release_regrab(lab, delay=args.regrab_delay)
                elif name == "release_loop":
                    summary = run_release_loop(lab, delay=args.regrab_delay)
                elif name == "throw":
                    summary = run_throw(lab)
                elif name == "suplex":
                    summary = run_suplex(lab)
                else:
                    summary = {"error": "unknown experiment"}
            finally:
                client.set_lockstep(False)
            summary["experiment"] = name
            summaries.append(summary)
            print(json.dumps(summary), flush=True)
            sink.write(json.dumps({"summary": summary}) + "\n")
        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001
            pass
    return 0 if summaries else 2


if __name__ == "__main__":
    sys.exit(main())
