#!/usr/bin/env python3
"""Run the built Streets of Rage host with a local ROM."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from _common import META_ROOT, absolute_path, executable_path


def main() -> int:
    sor_root = META_ROOT / "StreetsOfRageRecompilation"
    executable = executable_path(sor_root / "build", "sor")
    arguments = sys.argv[1:]
    rom = Path(os.environ.get("SOR_ROM", sor_root / "rom" / "SOR.bin"))
    if arguments and not arguments[0].startswith("-"):
        rom = Path(arguments.pop(0))
    rom = absolute_path(rom)

    if not executable.is_file():
        print(f"Executable not found: {executable}", file=sys.stderr)
        print("Run scripts/build.py or scripts/generate_cpp_and_build.py first.", file=sys.stderr)
        return 1
    if not rom.is_file():
        print(f"ROM not found: {rom}", file=sys.stderr)
        return 1
    # Replacing this wrapper means session launchers can reliably terminate the
    # host they started instead of leaving an orphaned sor child process.
    os.execv(str(executable), [str(executable), "--rom", str(rom), *arguments])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
