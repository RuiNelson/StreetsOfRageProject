#!/usr/bin/env python3
"""Read-only sampling of named Mega Drive memory fields at VSync intervals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT / "MegaDriveEnvironment" / "python" / "src"))

from megadrive_remote import MegaDriveClient  # noqa: E402


@dataclass(frozen=True)
class Field:
    name: str
    address: int
    width: int


@dataclass(frozen=True)
class ExpectedValue:
    address: int
    width: int
    value: int


def integer(text: str) -> int:
    try:
        return int(text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid integer: {text}") from error


def parse_field(text: str) -> Field:
    parts = text.split(":")
    if len(parts) != 3 or not parts[0]:
        raise argparse.ArgumentTypeError("field must be NAME:ADDRESS:WIDTH")
    name, address_text, width_text = parts
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name):
        raise argparse.ArgumentTypeError(f"invalid field name: {name}")
    address = integer(address_text)
    width = integer(width_text)
    validate_location(address, width)
    return Field(name, address, width)


def parse_expected(text: str) -> ExpectedValue:
    parts = text.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("wait condition must be ADDRESS:WIDTH:VALUE")
    address = integer(parts[0])
    width = integer(parts[1])
    value = integer(parts[2])
    validate_location(address, width)
    if not 0 <= value < (1 << (width * 8)):
        raise argparse.ArgumentTypeError("wait value does not fit the selected width")
    return ExpectedValue(address, width, value)


def validate_location(address: int, width: int) -> None:
    if width not in (1, 2, 4):
        raise argparse.ArgumentTypeError("width must be 1, 2, or 4")
    if not 0 <= address <= 0xFFFFFF or address + width - 1 > 0xFFFFFF:
        raise argparse.ArgumentTypeError("address range must fit the 24-bit bus")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6969)
    parser.add_argument("--field", action="append", type=parse_field, required=True)
    parser.add_argument("--wait-for", type=parse_expected)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--interval-frames", type=int, default=60)
    parser.add_argument("--timeout-ms", type=int, default=10_000)
    parser.add_argument("--capture-dir", type=Path)
    parser.add_argument("--capture-every", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.samples <= 0:
        raise SystemExit("--samples must be positive")
    if args.interval_frames <= 0:
        raise SystemExit("--interval-frames must be positive")
    if args.timeout_ms <= 0:
        raise SystemExit("--timeout-ms must be positive")
    if args.capture_every < 0:
        raise SystemExit("--capture-every cannot be negative")
    names = [field.name for field in args.field]
    if len(names) != len(set(names)):
        raise SystemExit("--field names must be unique")
    if args.capture_every and args.capture_dir is None:
        raise SystemExit("--capture-every requires --capture-dir")
    if args.capture_dir is not None:
        args.capture_dir.mkdir(parents=True, exist_ok=True)

    with MegaDriveClient(args.host, args.port, io_timeout=10.0) as client:
        client.ping()
        if args.wait_for is not None:
            client.wait_memory_equals(
                args.wait_for.address,
                args.wait_for.value,
                width=args.wait_for.width,
                timeout_ms=args.timeout_ms,
            )

        samples = []
        captures = []
        for sample_index in range(args.samples):
            values = {
                field.name: client.read_value(field.address, width=field.width)
                for field in args.field
            }
            frame = client.read_framebuffer()
            record = {
                "sample": sample_index,
                "values": values,
                "framebuffer": {
                    "width": frame.width,
                    "height": frame.height,
                    "sha256": hashlib.sha256(frame.bgr).hexdigest(),
                },
            }
            samples.append(record)

            if args.capture_every and sample_index % args.capture_every == 0:
                capture = args.capture_dir / f"sample-{sample_index:04d}.ppm"
                frame.save_ppm(capture)
                captures.append(str(capture))

            if sample_index + 1 < args.samples:
                client.wait_vsync(args.interval_frames, timeout_ms=args.timeout_ms)

    print(json.dumps({
        "success": True,
        "read_only": True,
        "wait_for": None if args.wait_for is None else {
            "address": args.wait_for.address,
            "width": args.wait_for.width,
            "value": args.wait_for.value,
        },
        "interval_frames": args.interval_frames,
        "samples": samples,
        "captures": captures,
    }, indent=2))


if __name__ == "__main__":
    main()
