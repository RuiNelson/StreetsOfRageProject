#!/usr/bin/env python3
"""Smoke probe for a running MegaDriveEnvironment server."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT / "MegaDriveEnvironment" / "python" / "src"))

from megadrive_remote import MegaDriveClient, TilemapPlane  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6969)
    parser.add_argument("--wait-frames", type=int, default=1)
    parser.add_argument("--timeout-ms", type=int, default=5_000)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--restart", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with MegaDriveClient(args.host, args.port) as client:
        client.ping()
        if args.restart:
            client.restart_game(timeout_ms=args.timeout_ms)
        client.wait_vsync(args.wait_frames, timeout_ms=args.timeout_ms)

        frame = client.read_framebuffer()
        state = client.read_vdp_state()
        palettes = client.read_palettes()
        sprites = client.read_sat()
        plane_a = client.read_tilemap(TilemapPlane.A)
        if args.capture is not None:
            frame.save_ppm(args.capture)

        print(json.dumps({
            "connected": True,
            "framebuffer": {
                "width": frame.width,
                "height": frame.height,
                "sha256": hashlib.sha256(frame.bgr).hexdigest(),
                "capture": str(args.capture) if args.capture else None,
            },
            "vdp": {
                "status": state.status,
                "active_width": state.active_width,
                "active_height": state.active_height,
                "palette_entries": len(palettes),
                "sprites": len(sprites),
                "plane_a": [plane_a.width, plane_a.height],
            },
            "restarted": args.restart,
        }, indent=2))


if __name__ == "__main__":
    main()
