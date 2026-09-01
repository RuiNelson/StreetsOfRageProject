"""Measure, frame by frame, how long each hold move actually takes.

The hold family's timings were the last thing in this AI decided by feel:
``priority.HOLD_KNEE_TICKS`` was a tick budget, chosen so "a few knees land
before the flip", and a tick is not a unit the game knows. Deciding *whether
there is time for another knee before that enemy hits me* needs the moves in
the game's own unit -- 60 Hz frames -- and needs them measured, because an
action's length is not its animation's length: the ROM's action handlers
advance on specific animation frames (``$23D6``'s ``cmpi.b #$0004,$a(a0)`` is
the shape of it), so ``frames x per-frame delay`` from the animation record
over-states every move, by 2x for Axel's chord and 3.5x for Blaze's.

So this measures instead, the same way ``ai-analysis/controls-and-input.md``'s
"Measured chord timing" table was produced: a **lockstep** host stepped one
frame at a time, the move's input issued on frame 0, and the player's own
``+$30`` (action) and ``+$0A`` (animation frame) sampled out of the work-RAM
copy every frame until the action settles again.

The AI drives itself into a real hold first (no RAM writes, no teleporting --
it plays round 1 and grabs someone), and only then does the host go into
lockstep. What comes out is one row per move:

    move      from  to    frames  path
    knee      $60   $60   17      $60 -> $6a -> $6c -> $60
    ...

Run (host already up with ``--debugUtils``):

    cd autoplay
    PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 \\
        tools/hold_timing_diag.py --character axel

``--character`` matters: the three characters do **not** share these numbers
(Blaze's throw animation is 4 frames at 27 against Axel's 3 at 15), so a
number measured for one of them is not a number for the others.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from megadrive_remote import Buttons, MegaDriveClient

from sor_autoplay.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_autoplay.ai.loop import AgentLoop
from sor_autoplay.memory_map import ACTION_HOLDING, ADDR_P1_OBJECT
from sor_autoplay.phases import CombatPhase, player_phase
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.rom_data import RomData
from sor_autoplay.state import read_snapshot

# Work RAM is $FF0000-$FFFFFF and ``step_input`` hands back all 64 KiB of it,
# so an absolute address is read at its low 16 bits.
WORK_RAM_BASE = 0xFF0000

OBJ_ACTION = 0x30
OBJ_ANIM_FRAME = 0x0A
OBJ_HELD_LINK = 0x4C
OBJ_OUT_DAMAGE = 0x34
OBJ_HELD_TYPE = 0x60

# Free to issue a new input: the same pair observe.py treats as free, minus
# the enemy-grab counter (which is not a state a finisher can end in).
FREE_TO_ACT = frozenset({CombatPhase.NORMAL, CombatPhase.HOLDING})

ACTION_HOLD_FRONT = 0x60
ACTION_HOLD_BACK = 0x66
# The two stable holds, facing bit included: these are where a move starts and
# where it is over.
STABLE_HOLDS = frozenset({0x60, 0x61, 0x66, 0x67})

# How long to let a move run before giving up on it settling. Generous: the
# longest thing measured here is a suplex, and an unbounded loop against a
# live host is what this repo's own rules forbid.
MAX_MOVE_FRAMES = 400


def byte_at(work_ram: bytes, address: int, offset: int) -> int:
    return work_ram[(address - WORK_RAM_BASE) + offset]


def word_at(work_ram: bytes, address: int, offset: int) -> int:
    index = (address - WORK_RAM_BASE) + offset
    return int.from_bytes(work_ram[index : index + 2], "big")


def reach_a_hold(client: MegaDriveClient, *, character: str, seconds: float) -> bool:
    """Let the AI play until it is actually holding a body.

    Deliberately the real ``AgentLoop`` rather than a scripted walk-in: the
    hold this measures has to be the same hold the AI takes in a fight, and
    the grab is a contact result rather than an input (see
    ``execute.state_machine_grab_enemy``).
    """

    rom = RomData.read(client)
    gamepad = VirtualGamepad(SharedGamepadState(client), player_index=1)
    loop = AgentLoop(gamepad, no_food=True)
    deadline = time.monotonic() + seconds
    last_report = 0.0
    while time.monotonic() < deadline:
        started = time.monotonic()
        snapshot = read_snapshot(client, rom=rom)
        loop.tick(snapshot, player_index=1)
        action = client.read_value(ADDR_P1_OBJECT + OBJ_ACTION, width=1)
        if (action & 0xFE) in ACTION_HOLDING and client.read_value(
            ADDR_P1_OBJECT + OBJ_HELD_LINK, width=2
        ):
            gamepad.release()
            return True
        if started - last_report > 5.0:
            last_report = started
            print(f"waiting for a hold: action ${action:02X}", flush=True)
        time.sleep(max(0.0, 0.016 - (time.monotonic() - started)))
    return False


def settle_to_stable_hold(client: MegaDriveClient, *, limit: int = 120) -> int | None:
    """Step with no input until the actor is in a stable hold, or give up."""

    for _ in range(limit):
        step = client.step_input(held_frames=0, total_frames=1)
        action = byte_at(step.work_ram, ADDR_P1_OBJECT, OBJ_ACTION)
        if action in STABLE_HOLDS:
            return action
        if word_at(step.work_ram, ADDR_P1_OBJECT, OBJ_HELD_LINK) == 0:
            return None
    return None


def time_move(
    client: MegaDriveClient, *, buttons: int, press_frames: int, label: str
) -> dict | None:
    """Issue one hold move and count the frames until the action settles.

    "Settles" is the actor back in a stable hold ($60/$66) -- the state that
    accepts the *next* move -- or out of the hold family entirely, which is
    what a throw and a suplex both end in. Either way the number is what the
    caller wanted: how long the AI is committed for once it presses this.
    """

    start = settle_to_stable_hold(client)
    if start is None:
        return None

    path: list[int] = [start]
    frames = 0
    damage_frames: list[int] = []
    for frame in range(MAX_MOVE_FRAMES):
        held = 1 if frame < press_frames else 0
        step = client.step_input(
            player1=buttons if frame < press_frames else Buttons.NONE,
            held_frames=held,
            total_frames=1,
        )
        frames = frame + 1
        action = byte_at(step.work_ram, ADDR_P1_OBJECT, OBJ_ACTION)
        if byte_at(step.work_ram, ADDR_P1_OBJECT, OBJ_OUT_DAMAGE):
            damage_frames.append(frames)
        if action != path[-1]:
            path.append(action)
        # The first frame is the press itself; the action has not changed yet.
        #
        # "Settled" is the ROM's own answer to "can this actor act again",
        # not a list of action bytes: Blaze's suplex puts *her* on the floor
        # too and comes back through a landing state ($30/$31), so a fixed
        # set of idle/hold bytes reported her finisher as never ending. That
        # floor time is part of what the move costs and has to be counted.
        settled = action in STABLE_HOLDS or (
            (action & 0xFE) not in ACTION_HOLDING
            and player_phase(
                action_byte=action,
                held_type=byte_at(step.work_ram, ADDR_P1_OBJECT, OBJ_HELD_TYPE),
            )
            in FREE_TO_ACT
        )
        if frames > 1 and settled:
            return {
                "move": label,
                "frames": frames,
                "from": f"${start:02X}",
                "to": f"${action:02X}",
                "path": [f"${a:02X}" for a in path],
                "damage_frames": damage_frames,
            }
        if word_at(step.work_ram, ADDR_P1_OBJECT, OBJ_HELD_LINK) == 0 and frames > 1:
            # Body gone: a throw or a suplex has released it. The move is
            # still running (the actor is mid-animation), so keep stepping
            # until the actor itself is free -- that is what "committed for"
            # means to a caller deciding whether it has time.
            continue
    return {
        "move": label,
        "frames": frames,
        "from": f"${start:02X}",
        "to": "unsettled",
        "path": [f"${a:02X}" for a in path],
        "damage_frames": damage_frames,
    }


def enter_lockstep(client: MegaDriveClient, *, attempts: int = 3) -> bool:
    """Stop at a frame boundary, retrying a host that is briefly busy."""

    for attempt in range(attempts):
        try:
            client.set_lockstep(True, timeout_ms=10_000)
            return True
        except Exception as error:  # noqa: BLE001 -- reported, then retried
            print(f"lockstep attempt {attempt + 1} failed: {error}", flush=True)
            time.sleep(0.5)
    return False


def facing_left(client: MegaDriveClient) -> bool:
    return bool(client.read_value(ADDR_P1_OBJECT + OBJ_ACTION, width=1) & 0x01)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--character", default="axel")
    ap.add_argument("--grab-seconds", type=float, default=180.0)
    ap.add_argument("--press-frames", type=int, default=2)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with MegaDriveClient(host=args.host, port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    with MegaDriveClient(host=args.host, port=args.port) as client:
        rows = []
        # One fresh hold per *session*, not per run: a throw and a suplex both
        # end the hold, so anything after one of them has nothing to measure
        # from -- and re-entering lockstep on a hold that is already ending
        # measures the ending rather than the move (seen live: two frames from
        # $61 straight to idle $03). The crossover and the suplex share a
        # session because the suplex is only reachable from the back hold the
        # crossover produces.
        sessions = [
            [("knee", lambda back: Buttons.B)],
            [("crossover", lambda back: Buttons.C), ("suplex", lambda back: Buttons.B)],
            [("throw", lambda back: Buttons.B | back)],
        ]
        for session in sessions:
            action = client.read_value(ADDR_P1_OBJECT + OBJ_ACTION, width=1)
            if action not in STABLE_HOLDS:
                if not reach_a_hold(
                    client, character=args.character, seconds=args.grab_seconds
                ):
                    print("never reached another hold", flush=True)
                    break
            print(f"holding -- lockstep for {[m for m, _ in session]}", flush=True)
            # Release first: the host refuses to stop at a frame boundary
            # ("timed out entering lockstep") while a hold_buttons state is
            # still latched from the agent loop that just drove us here.
            client.release_buttons()
            if not enter_lockstep(client):
                print("could not enter lockstep", flush=True)
                break
            try:
                back = Buttons.LEFT if not facing_left(client) else Buttons.RIGHT
                for label, buttons_for in session:
                    row = time_move(
                        client,
                        buttons=int(buttons_for(back)),
                        press_frames=args.press_frames,
                        label=label,
                    )
                    if row is None:
                        print(f"{label}: no hold left to measure from", flush=True)
                        break
                    rows.append(row)
                    print(json.dumps(row), flush=True)
            finally:
                client.set_lockstep(False)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as sink:
                json.dump({"character": args.character, "rows": rows}, sink, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
