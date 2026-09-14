"""Check ``ai/abadede.py`` against the ROM, one of Abadede's updates at a time.

The round-3 lockstep lab, in the shape of ``tools/bongo_lab.py``: the real
``AgentLoop`` plays round 3 (street waves swept) until Abadede is on screen,
then the host goes into lockstep and the same pipeline keeps playing --
ticked every two frames, as live, its pad output recorded and applied
through ``step_input`` -- while every frame on which his object updates is
checked against the model:

    before = the tokens built from the previous frame's work RAM
    predict = abadede.boss_update(AbadedeSim(before), ActorSim(before))
    compare predict with the tokens built from this frame's work RAM

field by field -- position, lane, primary ``+$30``, substate ``+$5B``, the
``+$54`` timer, both velocities, the animation, the latched boxes, his screen
X -- in the states the model replays (1, 2, 3, 4, 5, 7, ``$A``). The contact
outcome is compared against the player's own ``+$7C`` after his update (3 =
the grab his update hands out, 1 = his hit, 2 = the actor's strike on him);
not while the actor's own strike is live, which the check does not model.

His updates are found by his own fields: every update of every state he
fights in moves him or counts ``+$54`` down, so a frame on which none of them
changed is a frame his object did not update. Neither of the cheaper tests
holds: his animation countdown, which ``bongo_lab`` keys on, stands still
while he pauses, and the object pass keeps no fixed frame parity -- a first
version locked one and a third of its checks landed on frames he had not
updated on (a lag frame shifts the phase).

``--actor wander`` swaps the pipeline for a seeded walk that never attacks,
so the model runs through every state he has -- the approach, the pause, the
retreat, the run, the brake, the punch -- not only the few the engage lets
him reach. Every row also carries the player's action, ``+$7D`` and ``+$34``
and his health, which is how the hold's reads were timed. The fight is scored
too (hits, holds, runs started, whether he died).

Run (host already up with ``--debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/abadede_lab.py --out /tmp/abadede_lab.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, deque

from megadrive_remote import MegaDriveClient
from megadrive_remote.exceptions import RemoteTimeoutError

from sor_autoplay import memory_map as mm
from sor_autoplay.ai import abadede as plan
from sor_autoplay.ai.antonio import ActorSim
from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.ai.observe import generate_direct_observation_tokens
from sor_autoplay.ai.tokens import Abadede, CameraRange, Myself, find, find_all
from sor_autoplay.debug_scenario import DebugScenario
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot, snapshot_from_memory_blocks
from sor_autoplay.world_map import ACTORS_BYTES, CAMERA_BYTES

WORK_RAM = 0xFF0000
LEVEL = 3
FRAMES_PER_TICK = 2
SWEEP_EVERY_FRAMES = 30
MAX_EXAMPLES = 40
# The client's own default for one frame is 1.05 s, and a frame on which his
# run lands was measured going past it (twice, both times the step after the
# model first predicted the hit).
STEP_TIMEOUT_MS = 15_000

# (AbadedeSim attribute, Abadede token attribute, tolerance)
FIELDS = (
    ("x", "fine_x", 1e-6),
    ("y", "fine_y", 1e-6),
    ("primary", "primary_state", 0),
    ("sub", "substate", 0),
    ("t54", "timer_54", 0),
    ("vx", "boss_vel_x", 1e-6),
    ("vy", "boss_vel_lane", 1e-6),
    ("anim", "anim", 0),
    ("screen_x", "screen_x", 0),
)
MODELLED = frozenset(
    {
        plan.PRIMARY_APPROACH,
        plan.PRIMARY_PAUSE,
        plan.PRIMARY_RETREAT,
        plan.PRIMARY_STRUCK,
        plan.PRIMARY_SHAKE,
        plan.PRIMARY_CHARGE,
        plan.PRIMARY_GET_UP,
    }
)
P1_ACTION = mm.ADDR_P1_OBJECT + 0x30
P1_DAMAGE = mm.ADDR_P1_OBJECT + 0x34
P1_CONTACT = mm.ADDR_P1_OBJECT + 0x7C
P1_REACTION = mm.ADDR_P1_OBJECT + 0x7D
P1_FLAGS_59 = mm.ADDR_P1_OBJECT + 0x59
P1_BODY_BOX = mm.ADDR_P1_OBJECT + 0x70


def _window(ram: bytes, address: int, length: int) -> bytes:
    offset = address - WORK_RAM
    if offset < 0 or offset + length > len(ram):
        return b""
    return ram[offset : offset + length]


def _byte(ram: bytes, address: int) -> int:
    chunk = _window(ram, address, 1)
    return chunk[0] if chunk else 0


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
    """The two calls ``SharedGamepadState`` makes, captured instead of sent."""

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
    keeps deciding.
    """

    DIRECTIONS = (0, UP, DOWN, LEFT, RIGHT, UP | LEFT, UP | RIGHT, DOWN | LEFT, DOWN | RIGHT)

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.left = 0
        self.mask = 0

    def mask_for(self, me, boss) -> int:
        if me is not None and boss is not None and me.is_holding_enemy:
            return RIGHT if me.facing_left else LEFT
        if self.left <= 0:
            self.mask = self.rng.choice(self.DIRECTIONS)
            self.left = self.rng.randint(20, 60)
        self.left -= 1
        return self.mask


def _tokens(snapshot):
    context = generate_direct_observation_tokens(snapshot, player_index=1)
    boss = next(iter(b for b in find_all(context, Abadede) if not b.is_defeated), None)
    return context, find(context, Myself), boss


def _signature(boss: Abadede | None):
    if boss is None:
        return None
    return (
        boss.fine_x, boss.fine_y, boss.primary_state, boss.substate, boss.timer_54,
        boss.boss_vel_x, boss.boss_vel_lane, boss.anim, boss.screen_x,
    )


def _boss_dead(ram: bytes) -> bool:
    for index in range(mm.OBJECT_TABLE_SLOTS):
        address = mm.ADDR_OBJECT_TABLE + index * mm.OBJECT_SLOT_SIZE
        slot = _window(ram, address, mm.OBJECT_SLOT_SIZE)
        if slot and slot[0] == plan.ABADEDE_TYPE and slot[0x30] != 0:
            health = int.from_bytes(slot[0x32:0x34], "big")
            return health == 0 or health >= 0x8000 or slot[0x30] == plan.PRIMARY_DYING
    return False


def check_update(before_ctx, before_me, before_boss, after_boss, before_ram, after_ram) -> dict:
    """One of his updates: the model's prediction against the ROM's result."""

    camera = find(before_ctx, CameraRange)
    cam_x = before_boss.world_x + plan.SCREEN_BIAS - before_boss.screen_x
    sim = plan.AbadedeSim.from_token(before_boss, cam_x=cam_x)
    actor = ActorSim.from_token(
        before_me,
        lane_lo=float(plan.PLAYER_LANE_MIN),
        lane_hi=float(plan.PLAYER_LANE_MAX),
        x_lo=camera.left if camera else -1e9,
        x_hi=camera.right if camera else 1e9,
    )
    outcome = plan.boss_update(sim, actor, margin=False)
    predicted = outcome.name
    if sim.primary == plan.PRIMARY_HELD and before_boss.primary_state != plan.PRIMARY_HELD:
        predicted = "GRAB"  # a refused grab: code 3 lands, the actor takes nothing
    contact = _byte(after_ram, P1_CONTACT)
    actual_contact = {3: "GRAB", 2: "STRUCK", 1: "HIT"}.get(contact, "NONE")
    result = {
        "state": [before_boss.primary_state, before_boss.substate],
        "predicted_contact": predicted,
        "actual_contact": actual_contact,
        "mismatch": [],
    }
    striking = _byte(before_ram, P1_DAMAGE) != 0
    if plan.PRIMARY_THROWS_PLAYER in (before_boss.primary_state, after_boss.primary_state):
        # State 8 writes the held player's +$7C itself ($14D40, $14DB0): not a
        # contact test, and not a state the model replays.
        if sim.primary != after_boss.primary_state:
            result["mismatch"].append("primary")
        return result
    if predicted != "NONE" or actual_contact != "NONE":
        if striking:
            result["striking"] = True
        elif predicted != actual_contact:
            result["mismatch"].append("contact")
        return result
    if before_boss.primary_state not in MODELLED or after_boss.primary_state not in MODELLED:
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
    boxes = (after_boss.attack_box_id, after_boss.body_box_id)
    if sim.boxes != boxes:
        result["mismatch"].append("boxes")
        result.setdefault("detail", {})["boxes"] = [list(sim.boxes), list(boxes)]
    return result


def enter_lockstep(client: MegaDriveClient, *, attempts: int = 5) -> bool:
    for attempt in range(attempts):
        try:
            client.set_lockstep(True, timeout_ms=10_000)
            return True
        except Exception as error:  # noqa: BLE001 -- reported, then retried
            print(f"lockstep attempt {attempt + 1} failed: {error}", flush=True)
            time.sleep(0.5)
    return False


def reach_abadede(client, loop, rom, scenario, *, seconds: float, settle_seconds: float = 1.0) -> bool:
    """Play round 3 in real time until Abadede has been on screen for
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
        if playable and snap.level_index == LEVEL - 1:
            scenario.sweep_other_families(client)
            entities = snap.world_map.entities if snap.world_map else ()
            if any(e.type_id == plan.ABADEDE_TYPE and e.kind == "boss" for e in entities):
                seen_at = seen_at if seen_at is not None else started
                if started - seen_at >= settle_seconds:
                    return True
        if started - last_report > 10.0:
            last_report = started
            print(f"walking round {LEVEL}: level={snap.level_index}", flush=True)
        time.sleep(max(0.0, 0.008 - (time.monotonic() - started)))
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--frames", type=int, default=2400, help="lockstep frames to play")
    ap.add_argument("--input-delay", type=int, default=0, help="frames of added input latency")
    ap.add_argument("--actor", choices=("engage", "wander"), default="engage")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--settle-seconds", type=float, default=1.0)
    ap.add_argument("--reach-seconds", type=float, default=400.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    scenario = DebugScenario(start_level=LEVEL, kill_street_enemies=True)
    with MegaDriveClient(host=args.host, port=args.port) as client, open(
        args.out, "w", encoding="utf-8"
    ) as sink:
        rom = RomData.read(client)
        live_pad = VirtualGamepad(SharedGamepadState(client), player_index=1)
        if not reach_abadede(
            client,
            AgentLoop(live_pad, no_food=True, no_police=True),
            rom,
            scenario,
            seconds=args.reach_seconds,
            settle_seconds=args.settle_seconds,
        ):
            print("never reached Abadede", flush=True)
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
        boss_hp_start = boss_hp_min = None
        hits = holds = runs = struck = 0
        was_holding = False
        prev_state = None
        end = "frames"
        if not enter_lockstep(client):
            print("could not enter lockstep", flush=True)
            return 3
        frame = 0
        try:
            ram = client.step_input(
                player1=0, held_frames=0, total_frames=1, timeout_ms=STEP_TIMEOUT_MS
            ).work_ram
            last_hp = None
            for frame in range(args.frames):
                snap = snapshot_from_ram(ram, rom)
                context, me, boss = _tokens(snap)
                if frame % SWEEP_EVERY_FRAMES == 0:
                    scenario.sweep_other_families(client, force=True)
                if wander is not None:
                    delayed.append(wander.mask_for(me, boss))
                else:
                    if frame % FRAMES_PER_TICK == 0 and recorder.press_frames == 0:
                        loop.tick(snap, player_index=1)
                    delayed.append(recorder.next_frame_mask())
                mask = delayed.popleft()
                try:
                    new_ram = client.step_input(
                        player1=mask,
                        held_frames=1 if mask else 0,
                        total_frames=1,
                        timeout_ms=STEP_TIMEOUT_MS,
                    ).work_ram
                except RemoteTimeoutError:
                    # The host itself stops completing lockstep frames now and
                    # then (seen three times in round 3, never at a fixed
                    # frame); what was checked up to here still stands.
                    end = "host_timeout"
                    break
                after_snap = snapshot_from_ram(new_ram, rom)
                _, after_me, after_boss = _tokens(after_snap)

                body = _window(ram, P1_BODY_BOX, 12)
                row: dict = {
                    "f": frame,
                    "in": mask,
                    "pa": [_byte(new_ram, P1_ACTION), _byte(new_ram, P1_REACTION),
                           _byte(new_ram, P1_DAMAGE), _byte(new_ram, P1_CONTACT)],
                    # What his hit test reads on the player before his update:
                    # +$59 (bit 1 skips it) and the +$70 body box $4140 cached.
                    "pb": [_byte(ram, P1_FLAGS_59)]
                    + [int.from_bytes(body[i : i + 2], "big", signed=True) for i in range(0, len(body), 2)],
                }
                if me is not None and boss is not None and after_boss is not None:
                    row.update(
                        p=[me.world_x, me.world_y, me.action_state],
                        b=[round(after_boss.fine_x, 3), round(after_boss.fine_y, 3),
                           after_boss.primary_state, after_boss.substate, after_boss.timer_54,
                           after_boss.health, after_boss.anim, after_boss.attack_box_id,
                           after_boss.body_box_id],
                        en=[
                            [e.slot, e.type_id, e.world_x, e.world_y, e.action_state]
                            for e in (snap.world_map.entities if snap.world_map else ())
                            if e.kind == "enemy" and not e.is_defeated
                        ],
                    )
                    if _signature(boss) != _signature(after_boss):
                        result = check_update(context, me, boss, after_boss, ram, new_ram)
                        key = f"p{result['state'][0]}s{result['state'][1]}"
                        checked[key] += 1
                        for name in result["mismatch"]:
                            mismatched[f"{key}:{name}"] += 1
                        if result.get("predicted_contact") == "STRUCK" or result.get("actual_contact") == "STRUCK":
                            struck += 1
                        if result["mismatch"] and len(examples) < MAX_EXAMPLES:
                            examples.append(
                                {
                                    "frame": frame,
                                    "boss": {t: getattr(boss, t) for _, t, _ in FIELDS},
                                    "actor": [me.world_x, me.world_y, me.action_state, me.vel_x, me.facing_left],
                                    **result,
                                }
                            )
                        row["check"] = result
                    state = (after_boss.primary_state, after_boss.substate)
                    if state == (plan.PRIMARY_CHARGE, plan.SUB_RUN) and prev_state != state:
                        runs += 1
                    prev_state = state
                    if after_boss.health is not None:
                        boss_hp_start = after_boss.health if boss_hp_start is None else boss_hp_start
                        boss_hp_min = (
                            after_boss.health if boss_hp_min is None else min(boss_hp_min, after_boss.health)
                        )
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
        finally:
            try:
                client.set_lockstep(False)
                client.hold_buttons(player1=0, player2=0)
            except Exception:  # noqa: BLE001 -- a hung host is reported above
                pass

        summary = {
            "end": end,
            "frames": frame + 1,
            "actor": args.actor,
            "input_delay": args.input_delay,
            "hits": hits,
            "hp": [hp_start, hp_min],
            "boss_hp": [boss_hp_start, boss_hp_min],
            "holds": holds,
            "runs_started": runs,
            "struck_checks": struck,
            "updates_checked": sum(checked.values()),
            "checked_by_state": dict(checked),
            "mismatches": dict(mismatched),
            "examples": examples,
        }
        sink.write(json.dumps({"summary": summary}) + "\n")
        print(json.dumps({k: v for k, v in summary.items() if k != "examples"}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
