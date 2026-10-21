#!/usr/bin/env python3
"""Open the host's controller configuration UI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _common import META_ROOT, built_executable


def main() -> int:
    if sys.argv[1:] and sys.argv[1] in {"-h", "--help"}:
        print(f"Usage: {Path(sys.argv[0]).name}")
        return 0
    executable = built_executable(META_ROOT / "StreetsOfRageRecompilation" / "build", "sor")
    if not executable.is_file():
        print(f"Executable not found: {executable}", file=sys.stderr)
        print("Run scripts/build.py first.", file=sys.stderr)
        return 1
    return subprocess.run([str(executable), "--configControls", *sys.argv[1:]]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
