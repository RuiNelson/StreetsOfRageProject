#!/usr/bin/env python3
"""Run the built Streets of Rage host with a local ROM."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from _common import META_ROOT, absolute_path, built_executable


def main() -> int:
    sor_root = META_ROOT / "StreetsOfRageRecompilation"
    executable = built_executable(sor_root / "build", "sor")
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
    # The Python AI of the 1 PLAYER AI ASSIST mode: the checkout's, unless told otherwise.
    if not any(argument == "--ai-path" or argument.startswith("--ai-path=") for argument in arguments):
        arguments[0:0] = ["--ai-path", str(META_ROOT / "autoplay" / "ai-code")]
    command = [str(executable), "--rom", str(rom), *arguments]
    if os.name == "nt":
        # Windows has no exec: os.execv would start sor as a separate process,
        # without quoting paths that contain spaces, and exit at once, so
        # session launchers would see the host die before it listened.
        return subprocess.run(command).returncode
    # Replacing this wrapper means session launchers can reliably terminate the
    # host they started instead of leaving an orphaned sor child process.
    os.execv(str(executable), command)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
