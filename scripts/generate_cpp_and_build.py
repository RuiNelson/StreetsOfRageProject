#!/usr/bin/env python3
"""Generate C++ and then build the host."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _common import script_command


def main() -> int:
    release = False
    rom: str | None = None
    for argument in sys.argv[1:]:
        if argument == "--release":
            release = True
        elif argument in {"-h", "--help"}:
            print(f"Usage: {Path(sys.argv[0]).name} [--release] [ROM]")
            return 0
        elif argument.startswith("-"):
            print(f"Unknown option: {argument}", file=sys.stderr)
            return 2
        elif rom is None:
            rom = argument
        else:
            print("Only one ROM path may be supplied.", file=sys.stderr)
            return 2
    if subprocess.run(script_command("generate_cpp.py", *( [rom] if rom else [] ))).returncode:
        return 1
    return subprocess.run(script_command("build.py", *( ["--release"] if release else [] ))).returncode


if __name__ == "__main__":
    raise SystemExit(main())
