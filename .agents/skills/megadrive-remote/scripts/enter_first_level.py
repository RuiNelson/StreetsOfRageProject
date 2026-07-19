#!/usr/bin/env python3
"""Enter Streets of Rage level 1 through the natural P1 controller path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT / "MegaDriveEnvironment" / "python" / "src"))

from megadrive_remote import Buttons, MegaDriveClient  # noqa: E402


GAME_STATE = 0xFFFF00
LEVEL = 0xFFFF02
CHARACTER_SELECT_SUBSTATE = 0xFFF904
MAIN_MENU_SUBSTATE = 0xFFFB0E
MAIN_MENU_CURSOR = 0xFFB840
CHARACTER_CURSOR = 0xFFB858

CHARACTER_SLOTS = {"adam": 0, "axel": 1, "blaze": 2}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6969)
    parser.add_argument("--character", choices=CHARACTER_SLOTS, default="axel")
    parser.add_argument("--scene-frames", type=int, default=75)
    parser.add_argument("--settle-frames", type=int, default=180)
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    return parser.parse_args()


def tap(client: MegaDriveClient, buttons: Buttons) -> None:
    client.press_buttons(player1=buttons, frames=1)
    client.wait_vsync(4, timeout_ms=2_000)


def wait_value(
    client: MegaDriveClient,
    address: int,
    expected: int,
    *,
    width: int,
    timeout_ms: int,
    label: str,
) -> None:
    client.wait_memory_equals(
        address,
        expected,
        width=width,
        timeout_ms=timeout_ms,
    )
    print(f"OK: {label}", flush=True)


def main() -> None:
    args = parse_args()
    if args.scene_frames <= 0 or args.settle_frames <= 0:
        raise SystemExit("frame counts must be positive")

    target_slot = CHARACTER_SLOTS[args.character]
    with MegaDriveClient(args.host, args.port, io_timeout=10.0) as client:
        client.ping()
        print("Connected; sending no input during the SEGA logo.", flush=True)

        wait_value(
            client,
            GAME_STATE,
            0x0006,
            width=2,
            timeout_ms=args.timeout_ms,
            label="story mode",
        )
        client.wait_vsync(args.scene_frames, timeout_ms=args.timeout_ms)
        tap(client, Buttons.START)

        wait_value(
            client,
            GAME_STATE,
            0x000A,
            width=2,
            timeout_ms=args.timeout_ms,
            label="title screen",
        )
        client.wait_vsync(args.scene_frames, timeout_ms=args.timeout_ms)
        tap(client, Buttons.START)

        wait_value(
            client,
            GAME_STATE,
            0x0012,
            width=2,
            timeout_ms=args.timeout_ms,
            label="main menu",
        )
        wait_value(
            client,
            MAIN_MENU_SUBSTATE,
            0x0002,
            width=2,
            timeout_ms=args.timeout_ms,
            label="interactive main menu",
        )
        menu_cursor = client.read_value(MAIN_MENU_CURSOR, width=2)
        if menu_cursor != 0:
            raise RuntimeError(f"main-menu cursor is {menu_cursor}, not 1 PLAYER")
        client.wait_vsync(args.scene_frames, timeout_ms=args.timeout_ms)
        tap(client, Buttons.START)

        wait_value(
            client,
            GAME_STATE,
            0x0022,
            width=2,
            timeout_ms=args.timeout_ms,
            label="character select",
        )
        wait_value(
            client,
            CHARACTER_SELECT_SUBSTATE,
            0x0004,
            width=2,
            timeout_ms=args.timeout_ms,
            label="interactive character select",
        )
        current_slot = client.read_value(CHARACTER_CURSOR, width=2)
        if current_slot not in CHARACTER_SLOTS.values():
            raise RuntimeError(f"unexpected character slot {current_slot}")
        while current_slot != target_slot:
            expected_slot = (current_slot + 1) % len(CHARACTER_SLOTS)
            tap(client, Buttons.RIGHT)
            wait_value(
                client,
                CHARACTER_CURSOR,
                expected_slot,
                width=2,
                timeout_ms=5_000,
                label=f"character slot {expected_slot}",
            )
            current_slot = expected_slot
        client.wait_vsync(args.scene_frames, timeout_ms=args.timeout_ms)
        tap(client, Buttons.A)

        wait_value(
            client,
            GAME_STATE,
            0x002A,
            width=2,
            timeout_ms=args.timeout_ms,
            label="level intro",
        )
        wait_value(
            client,
            GAME_STATE,
            0x0016,
            width=2,
            timeout_ms=args.timeout_ms,
            label="active gameplay",
        )
        if client.read_value(LEVEL, width=2) != 0:
            raise RuntimeError("active gameplay is not level 1")

        client.wait_vsync(args.settle_frames, timeout_ms=args.timeout_ms)
        state = client.read_value(GAME_STATE, width=2)
        level = client.read_value(LEVEL, width=2)
        if state != 0x0016 or level != 0:
            raise RuntimeError(f"game moved unexpectedly: state=0x{state:04X}, level={level}")

        print(json.dumps({
            "success": True,
            "character": args.character,
            "state": f"0x{state:04X}",
            "level": level,
            "settled_frames": args.settle_frames,
            "reset_used": False,
            "memory_writes_used": False,
        }, indent=2))


if __name__ == "__main__":
    main()
