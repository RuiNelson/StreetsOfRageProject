"""Check ``ai/antonio.py`` against the ROM, one of Antonio's updates at a time.

A lockstep lab for the round-1 fight, in the shape of
``tools/souther_hold_lab.py``: the real ``AgentLoop`` plays round 1 (street
waves swept) until Antonio is on screen, then the host goes into lockstep and
the same pipeline keeps playing -- ticked every two frames, as live, its pad
output recorded and applied through ``step_input`` -- while every frame on
which his object updates is checked against the model:

    before = the tokens built from the previous frame's work RAM
    predict = antonio.boss_update(BossSim(before), ActorSim(before))
    compare predict with the tokens built from this frame's work RAM

field by field -- position, lane, primary, tactical, both timers, both
velocities, the animation and its countdown, the box ids the renderer
latched, and his screen X -- plus the contact outcome against the player's
own ``+$7C`` (3 = grab, 1 = hit). Every boomerang of his is compared the
same way while it flies: his linked one (his ``+$6E``) and any older one
still out, matched by slot. An object update is recognised by his
animation countdown ``+$0D`` moving, which the renderer does on every one
of his updates.

The fight itself is scored too (hits taken, holds, kicks started, whether he
died), so the same run answers "does the model hold" and "does the plan built
on it work frame for frame". ``--input-delay`` applies the recorded pad that
many frames late, to measure how much latency the plan survives.

Run (host already up with ``--debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/antonio_lab.py --out /tmp/antonio_lab.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, deque

from megadrive_remote import MegaDriveClient

from sor_autoplay import memory_map as mm
from sor_autoplay.ai import antonio as plan
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.ai.observe import generate_direct_observation_tokens
from sor_autoplay.ai.tokens import Antonio, CameraRange, Myself, Projectile, find, find_all
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot, snapshot_from_memory_blocks
from sor_autoplay.world_map import ACTORS_BYTES, CAMERA_BYTES

WORK_RAM = 0xFF0000
ANTONIO_TYPE = 0x56
FRAMES_PER_TICK = 2
SWEEP_EVERY_FRAMES = 30
MAX_EXAMPLES = 25

# (BossSim attribute, Antonio token attribute, tolerance)
FIELDS = (
    ("x", "fine_x", 1e-6),
    ("y", "fine_y", 1e-6),
    ("primary", "primary_state", 0),
    ("tactical", "tactical", 0),
    ("t78", "phase_timer", 0),
    ("t5c", "timer_5c", 0),
    ("t6b", "timer_6b", 0),
    ("vx", "boss_vel_x", 1e-6),
    ("vy", "boss_vel_lane", 1e-6),
    ("anim", "anim", 0),
    ("frame", "anim_frame", 0),
    ("countdown", "anim_countdown", 0),
    ("shown_attack", "attack_box_id", 0),
    ("shown_body", "body_box_id", 0),
    ("screen_x", "screen_x", 0),
)
# His boomerang, while it flies (BoomerangSim attribute, Projectile attribute).
BOOMERANG_FIELDS = (
    ("x", "fine_x", 1e-6),
    ("y", "fine_y", 1e-6),
    ("vx", "vel_x", 1e-6),
    ("vy", "vel_lane", 1e-6),
    ("frame", "anim_frame", 0),
    ("shown", "attack_box_id", 0),
    ("screen_x", "screen_x", 0),
    ("countdown", "countdown", 0),
    ("lane_target", "lane_target", 0),
)


def _window(ram: bytes, address: int, length: int) -> bytes:
    offset = address - WORK_RAM
    if offset < 0 or offset + length > len(ram):
        return b""
    return ram[offset : offset + length]


def snapshot_from_ram(ram: bytes, rom: RomData | None):
    """``state.read_snapshot``, from a lockstep frame's work RAM instead of reads."""

    stride = int.from_bytes(_window(ram, mm.ADDR_PRIMARY_BLOCKMAP_STRIDE, 2) or b"\0\0", "big")
    police = _window(ram, mm.ADDR_POLICE_SPECIAL_ACTIVE, 3) or b"\0\0\0"
    mr_x = _window(ram, mm.ADDR_MR_X_OFFER_FLAG, 6) or bytes(6)
    actors = _window(ram, mm.ADDR_P1_OBJECT, ACTORS_BYTES)
    collision = _window(ram, mm.ADDR_LEVEL_COLLISION_CLASS_MAP, stride * 0x18) if stride else b""
    return snapshot_from_memory_blocks(
        globals_block=_window(ram, 0xFFFF00, 0x40),
        timer_block=_window(ram, mm.ADDR_GAME_TIMER, 4),
        objects_block=actors[:0x100],
        actors_block=actors,
        camera_block=_window(ram, mm.ADDR_PRIMARY_CAMERA, CAMERA_BYTES),
        stop_clock=(_window(ram, mm.ADDR_STOP_CLOCK, 1) or b"\0")[0],
        pause_text_flag=(_window(ram, mm.ADDR_PAUSE_TEXT_FLAG, 1) or b"\0")[0],
        police_special_active_byte=police[0],
        police_special_caller_byte=police[2],
        collision_map=collision,
        blockmap_stride=stride if collision else 0,
        mr_x_offer_flag=mr_x[0],
        mr_x_offer_state=int.from_bytes(mr_x[4:6], "big"),
        connected=True,
        rom=rom,
    )


class RecordingClient:
    """The two calls ``SharedGamepadState`` makes, captured instead of sent.

    A press blocks the live AI thread for its frames and is then followed by
    the re-armed hold; here the press owns the pad for its frames, and the
    lab does not tick the loop while one is running, which is the same thing.
    """

    def __init__(self) -> None:
        self.held = 0
        self.press_mask = 0
        self.press_frames = 0

    def hold_buttons(self, *, player1: int = 0, player2: int = 0) -> None:
        self.held = int(player1)

    def press_buttons(self, *, player1: int = 0, player2: int = 0, frames: int = 1) -> None:
        self.press_mask = int(player1)
        self.press_frames = int(frames)

    def release_buttons(self) -> None:
        self.held = 0

    def next_frame_mask(self) -> int:
        if self.press_frames > 0:
            self.press_frames -= 1
            return self.press_mask
        return self.held


UP, DOWN, LEFT, RIGHT = 0x0001, 0x0002, 0x0004, 0x0008


class Wander:
    """A seeded walk that never presses B or C, for ``--actor wander``.

    Each leg is one of the nine stick positions for 20-60 frames. A hold it
    walks into is let go by holding back, so the fight keeps going and his AI
    keeps deciding -- the point being to run the model through every one of
    his states (the walk back on, the back-off, the dash, the wind-up and the
    throw, the kick), not just the few the engage ever lets him reach.
    """

    DIRECTIONS = (0, UP, DOWN, LEFT, RIGHT, UP | LEFT, UP | RIGHT, DOWN | LEFT, DOWN | RIGHT)

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.left = 0
        self.mask = 0

    def mask_for(self, me, boss) -> int:
        if me is not None and boss is not None and me.is_holding_enemy:
            return LEFT if boss.world_x > me.world_x else RIGHT
        if self.left <= 0:
            self.mask = self.rng.choice(self.DIRECTIONS)
            self.left = self.rng.randint(20, 60)
        self.left -= 1
        return self.mask


def _tokens(snapshot):
    context = generate_direct_observation_tokens(snapshot, player_index=1)
    antonio = next(iter(a for a in find_all(context, Antonio) if not a.is_defeated), None)
    boomerangs = [p for p in find_all(context, Projectile) if p.type_id == plan.BOOMERANG_TYPE]
    return context, find(context, Myself), antonio, boomerangs


def _boss_dead(ram: bytes) -> bool:
    for index in range(mm.OBJECT_TABLE_SLOTS):
        address = mm.ADDR_OBJECT_TABLE + index * mm.OBJECT_SLOT_SIZE
        slot = _window(ram, address, mm.OBJECT_SLOT_SIZE)
        if slot and slot[0] == ANTONIO_TYPE and slot[0x30] != 0:
            health = int.from_bytes(slot[0x32:0x34], "big")
            return health == 0 or health >= 0x8000
    return False


def _compare_boomerang(result: dict, key: str, m, actual) -> None:
    """One boomerang, model against ROM, while either says it flies."""

    flying = (plan.BOOMERANG_OUT, plan.BOOMERANG_BACK)
    if not ((m is not None and m.state in flying) or (actual is not None and actual.state in flying)):
        return
    result["boomerang"] = True
    if m is None or actual is None or m.state != actual.state:
        result["mismatch"].append(f"{key}_state")
        result.setdefault("detail", {})[f"{key}_state"] = [
            None if m is None else m.state,
            None if actual is None else actual.state,
        ]
        return
    for sim_field, token_field, tolerance in BOOMERANG_FIELDS:
        predicted = getattr(m, sim_field)
        observed = getattr(actual, token_field)
        if abs(predicted - observed) > tolerance:
            result["mismatch"].append(f"{key}_{sim_field}")
            result.setdefault("detail", {})[f"{key}_{sim_field}"] = [predicted, observed]


def check_update(
    before_ctx, before_me, before_boss, after_boss, after_ram, before_bms=(), after_bms=()
) -> dict | None:
    """One of his updates: the model's prediction against the ROM's result --
    his object, and every boomerang of his while it flies (his linked one by
    his ``+$6E``, older ones by slot)."""

    camera = find(before_ctx, CameraRange)
    cam_x = before_boss.world_x + plan.SCREEN_BIAS - before_boss.screen_x
    linked, strays = plan.split_boomerangs(before_boss, before_bms)
    sim = plan.BossSim.from_token(
        before_boss, cam_x=cam_x, boomerang=linked, strays=strays, boomerang_known=True
    )
    actor = plan.ActorSim.from_token(
        before_me,
        lane_lo=float(plan.PLAYER_LANE_MIN),
        lane_hi=float(plan.PLAYER_LANE_MAX),
        x_lo=camera.left if camera else -1e9,
        x_hi=camera.right if camera else 1e9,
    )
    outcome = plan.boss_update(sim, actor, margin=False)
    contact = _window(after_ram, mm.ADDR_P1_OBJECT + 0x7C, 1)[0]
    actual_contact = {3: "GRAB", 1: "HIT"}.get(contact & 0x03 if contact in (1, 3) else 0, "NONE")
    result = {
        "state": [before_boss.primary_state, before_boss.tactical],
        "predicted_contact": outcome.name,
        "actual_contact": actual_contact,
        "mismatch": [],
    }
    if outcome is not plan.Outcome.NONE or actual_contact != "NONE":
        # A contact ends the update early in the model; the ROM goes on to
        # run the hold/hit reaction. Only the outcome is comparable.
        if outcome.name != actual_contact:
            result["mismatch"].append("contact")
        return result
    if plan.PRIMARY_HELD in (sim.primary, after_boss.primary_state):
        # The held state is placed by the holder's code ($17DFA), which the
        # model does not replay: only the transition itself compares.
        if sim.primary != after_boss.primary_state:
            result["mismatch"].append("primary")
            result.setdefault("detail", {})["primary"] = [sim.primary, after_boss.primary_state]
        return result
    for sim_field, token_field, tolerance in FIELDS:
        predicted = getattr(sim, sim_field)
        actual = getattr(after_boss, token_field)
        if abs(predicted - actual) > tolerance:
            result["mismatch"].append(sim_field)
            result.setdefault("detail", {})[sim_field] = [predicted, actual]
    after_linked, _ = plan.split_boomerangs(after_boss, after_bms)
    _compare_boomerang(result, "bm", sim.boomerang, after_linked)
    by_slot = {p.slot: p for p in after_bms}
    for stray in sim.strays:
        if stray.slot is not None:
            _compare_boomerang(result, "stray", stray, by_slot.get(stray.slot))
    return result


def enter_lockstep(client: MegaDriveClient, *, attempts: int = 5) -> bool:
    """Stop at a frame boundary, retrying a host that is briefly busy -- the
    same transient ``tools/hold_timing_diag.py`` retries. The first lab run
    asked on the very update he spawned, with the level pipeline loading his
    art, and timed out."""

    for attempt in range(attempts):
        try:
            client.set_lockstep(True, timeout_ms=10_000)
            return True
        except Exception as error:  # noqa: BLE001 -- reported, then retried
            print(f"lockstep attempt {attempt + 1} failed: {error}", flush=True)
            time.sleep(0.5)
    return False


def reach_antonio(
    client, loop, rom, scenario, *, seconds: float, settle_seconds: float = 1.0
) -> bool:
    """Play round 1 in real time until Antonio has been on screen for
    ``settle_seconds`` -- past his spawn, so lockstep is not asked for while
    the level pipeline is still loading him."""

    deadline = time.monotonic() + seconds
    last_report = 0.0
    seen_at: float | None = None
    while time.monotonic() < deadline:
        started = time.monotonic()
        snap = read_snapshot(client, rom=rom)
        playable = any(p.is_playable for p in snap.players)
        if scenario.level_jump_pending:
            if playable:
                scenario.apply_start_level(client)
            time.sleep(0.008)
            continue
        loop.tick(snap, player_index=1)
        if playable and snap.level_index == 0:
            scenario.sweep_other_families(client)
            entities = snap.world_map.entities if snap.world_map else ()
            if any(e.type_id == ANTONIO_TYPE and e.kind == "boss" for e in entities):
                seen_at = seen_at if seen_at is not None else started
                if started - seen_at >= settle_seconds:
                    return True
        if started - last_report > 10.0:
            last_report = started
            print(f"walking round 1: level={snap.level_index}", flush=True)
        time.sleep(max(0.0, 0.008 - (time.monotonic() - started)))
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--frames", type=int, default=2400, help="lockstep frames to play")
    ap.add_argument("--input-delay", type=int, default=0, help="frames of added input latency")
    ap.add_argument(
        "--actor",
        choices=("engage", "wander"),
        default="engage",
        help=(
            "engage: the real pipeline plays (the plan, frame for frame); "
            "wander: a seeded walk that never attacks, to run the model "
            "through all of his states"
        ),
    )
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--reach-seconds", type=float, default=300.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=1, kill_street_enemies=True)
    with MegaDriveClient(host=args.host, port=args.port) as client, open(
        args.out, "w", encoding="utf-8"
    ) as sink:
        rom = RomData.read(client)
        live_pad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        if not reach_antonio(
            client,
            AgentLoop(live_pad, no_food=True, no_police=True),
            rom,
            scenario,
            seconds=args.reach_seconds,
        ):
            print("never reached Antonio", flush=True)
            return 2
        live_pad.release()
        client.release_buttons()

        recorder = RecordingClient()
        loop = AgentLoop(
            VirtualGamepad(SharedGamepadState(recorder), player_index=1),
            no_food=True,
            no_police=True,
        )
        wander = Wander(args.seed) if args.actor == "wander" else None
        delayed: deque[int] = deque([0] * args.input_delay)
        checked: Counter[str] = Counter()
        mismatched: Counter[str] = Counter()
        examples: list[dict] = []
        hp_start = hp_min = None
        hits = holds = kicks = 0
        was_holding = False
        prev_boss_primary = None
        end = "frames"
        if not enter_lockstep(client):
            print("could not enter lockstep", flush=True)
            return 3
        try:
            ram = client.step_input(player1=0, held_frames=0, total_frames=1).work_ram
            last_hp = None
            for frame in range(args.frames):
                snap = snapshot_from_ram(ram, rom)
                context, me, boss, boomerangs = _tokens(snap)
                if frame % SWEEP_EVERY_FRAMES == 0:
                    scenario.sweep_other_families(client, force=True)
                if wander is not None:
                    delayed.append(wander.mask_for(me, boss))
                else:
                    if frame % FRAMES_PER_TICK == 0 and recorder.press_frames == 0:
                        loop.tick(snap, player_index=1)
                    delayed.append(recorder.next_frame_mask())
                mask = delayed.popleft()
                new_ram = client.step_input(
                    player1=mask, held_frames=1 if mask else 0, total_frames=1
                ).work_ram
                after_snap = snapshot_from_ram(new_ram, rom)
                _, after_me, after_boss, after_boomerangs = _tokens(after_snap)

                row: dict = {"f": frame, "in": mask}
                if me is not None and boss is not None and after_boss is not None:
                    row.update(
                        p=[me.world_x, me.world_y, me.action_state],
                        b=[round(boss.fine_x, 3), round(boss.fine_y, 3), boss.primary_state,
                           boss.tactical, boss.phase_timer, boss.anim_frame, boss.attack_box_id],
                        link=boss.child_slot,
                        bm=[[p.slot, p.state, round(p.fine_x, 2), round(p.fine_y, 2), p.attack_box_id]
                            for p in boomerangs],
                    )
                    if boss.anim_countdown != after_boss.anim_countdown and boss.primary_state in (
                        plan.PRIMARY_ACTIVE,
                        plan.PRIMARY_KICK,
                    ):
                        result = check_update(
                            context, me, boss, after_boss, new_ram, boomerangs, after_boomerangs
                        )
                        if result is not None:
                            key = f"p{result['state'][0]}t{result['state'][1]}"
                            checked[key] += 1
                            for name in result["mismatch"]:
                                mismatched[f"{key}:{name}"] += 1
                            if result["mismatch"] and len(examples) < MAX_EXAMPLES:
                                examples.append(
                                    {
                                        "frame": frame,
                                        "boss": {t: getattr(boss, t) for _, t, _ in FIELDS},
                                        "actor": [me.world_x, me.world_y, me.action_state, me.vel_x],
                                        **result,
                                    }
                                )
                            row["check"] = result
                    if after_boss.primary_state == plan.PRIMARY_KICK and prev_boss_primary != plan.PRIMARY_KICK:
                        kicks += 1
                    prev_boss_primary = after_boss.primary_state
                if after_me is not None:
                    hp = after_me.health
                    hp_start = hp if hp_start is None else hp_start
                    hp_min = hp if hp_min is None else min(hp_min, hp)
                    if last_hp is not None and hp is not None and hp < last_hp:
                        hits += 1
                    last_hp = hp
                    holding = after_me.is_holding_enemy
                    if holding and not was_holding:
                        holds += 1
                    was_holding = holding
                sink.write(json.dumps(row) + "\n")
                ram = new_ram
                if _boss_dead(ram):
                    end = "killed"
                    break
                if after_me is None:
                    end = "player_gone"
                    break
        finally:
            client.set_lockstep(False)
            try:
                client.hold_buttons(player1=0, player2=0)
            except Exception:  # noqa: BLE001
                pass

        summary = {
            "end": end,
            "frames": frame + 1,
            "actor": args.actor,
            "input_delay": args.input_delay,
            "hits": hits,
            "hp": [hp_start, hp_min],
            "holds": holds,
            "kicks_started": kicks,
            "updates_checked": sum(checked.values()),
            "checked_by_state": dict(checked),
            "mismatches": dict(mismatched),
            "examples": examples,
        }
        sink.write(json.dumps({"summary": summary}) + "\n")
        print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
