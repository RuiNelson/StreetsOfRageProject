"""Compare P2's AI inside the ``sor`` host with the same AI over the socket.

Each run starts its own host (``--turbo 2 --silent --debug-utils``), reaches
round 1 as P1 with an external ``AgentLoop`` on P1, and has P2 join:

- ``--p2 embedded``: the host runs with ``--ai-assist``, so P2 is the AI in its
  process (``sor_ai.embedded``). A client's Start on pad 2 is ignored there, so
  the join pokes ``p2_button_held`` until ``$115CC`` sees it.
- ``--p2 socket``: a second ``AgentLoop`` on the same link, as ``--agent-p2``.

The summary is one JSON line per run: frames from the join to the end of round
1, or to the deadline; and both players' scores and lives lost.

    cd autoplay
    PYTHONPATH=src:ai-code:../MegaDriveEnvironment/python/src python3 tools/ai_assist_fight.py \\
        --sor ../StreetsOfRageRecompilation/build/sor --rom ../StreetsOfRageRecompilation/rom/SOR.bin \\
        --ai-path ai-code --p2 embedded --out /tmp/ai_assist.jsonl
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import tempfile
import time

from sor_ai.ai.gamepad import SharedGamepadState, VirtualGamepad
from sor_ai.ai.loop import AgentLoop
from sor_ai.rom_data import RomData
from sor_ai.state import read_snapshot
from sor_autoplay.reach_gameplay import reach_gameplay
from sor_autoplay.sor_remote import SoRClient

START_MASK = 0x0080
P2_BUTTON_HELD = 0xFFFC08
JOIN_RETRY_S = 1.0
HOST_START_TIMEOUT_S = 20.0


def _connect(port: int) -> None:
    deadline = time.monotonic() + HOST_START_TIMEOUT_S
    while True:
        try:
            with SoRClient(host="127.0.0.1", port=port) as client:
                client.ping()
            return
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)


def fight(args: argparse.Namespace, log_path: str) -> dict[str, object]:
    embedded = args.p2 == "embedded"
    _connect(args.port)
    with SoRClient(host="127.0.0.1", port=args.port) as menu:
        reach_gameplay(menu, args.character, timeout_ms=90_000)

    poll_s = args.poll_ms / 1000.0
    with SoRClient(host="127.0.0.1", port=args.port) as client:
        assist = client.ai_assist()
        rom = RomData.read(client)
        state = SharedGamepadState(client)
        loops = {1: AgentLoop(VirtualGamepad(state, player_index=1))}
        if not embedded:
            loops[2] = AgentLoop(VirtualGamepad(state, player_index=2))
        deadline = time.monotonic() + args.seconds
        last_join = 0.0
        joined_frame: int | None = None
        cleared_frame: int | None = None
        lives_lost = {1: 0, 2: 0}
        previous_lives: dict[int, int] = {}
        snap = None
        while time.monotonic() < deadline:
            started = time.monotonic()
            snap = read_snapshot(client, rom=rom)
            frame = (snap.raw or {}).get("uptime_frames") or 0
            p1, p2 = snap.players
            if snap.level_index >= 1:
                cleared_frame = frame
                break
            if p1.is_playable and not p2.is_playable and joined_frame is None:
                if embedded:
                    client.write_memory(P2_BUTTON_HELD, b"\x80")
                elif started - last_join > JOIN_RETRY_S:
                    client.press_buttons(player2=START_MASK, frames=3)
                    last_join = started
            if p2.is_playable and joined_frame is None:
                joined_frame = frame
                previous_lives = {1: p1.lives, 2: p2.lives}
                print(f"P2 joined at frame {frame}", flush=True)
            for index, loop in loops.items():
                player = snap.players[index - 1]
                if player.is_playable or player.is_continue_ui:
                    loop.tick(snap, player_index=index)
            if joined_frame is not None:
                for index, player in enumerate(snap.players, start=1):
                    lost = previous_lives[index] - player.lives
                    if lost > 0:
                        lives_lost[index] += lost
                    previous_lives[index] = player.lives
            time.sleep(max(0.0, poll_s - (time.monotonic() - started)))
        final = snap
        client.release_buttons()
    return {
        "p2": args.p2,
        "host_ai_assist": assist,
        "joined_frame": joined_frame,
        "round_frames": cleared_frame - joined_frame if cleared_frame and joined_frame else None,
        "scores": [p.score for p in final.players] if final else None,
        "lives_lost": lives_lost,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sor", required=True)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--ai-path", required=True)
    ap.add_argument("--p2", choices=("embedded", "socket"), required=True)
    ap.add_argument("--port", type=int, default=7791)
    ap.add_argument("--poll-ms", type=int, default=16)
    ap.add_argument("--seconds", type=float, default=240.0)
    ap.add_argument("--character", default="blaze")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    command = [args.sor, "--rom", args.rom, "--default-video", "--turbo", "2", "--lang", "en", "--silent", "--debug-utils",
               "--port", str(args.port), "--ai-path", args.ai_path]
    if args.p2 == "embedded":
        command.append("--ai-assist")
    with tempfile.NamedTemporaryFile("w+", suffix=".log") as log:
        host = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            result = fight(args, log.name)
        finally:
            host.send_signal(signal.SIGINT)
            try:
                host.wait(timeout=10)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait()
        log.seek(0)
        result["host_exit"] = host.returncode
        result["ai_log"] = [line.strip() for line in log if "[ai]" in line or "Traceback" in line or "Error" in line]
    print(json.dumps(result), flush=True)
    with open(args.out, "a", encoding="utf-8") as sink:
        sink.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
