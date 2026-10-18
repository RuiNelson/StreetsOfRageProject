#!/usr/bin/env python3
"""Generate C++, build it, and run the host."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from _common import META_ROOT, absolute_path, script_command


def main() -> int:
    arguments = sys.argv[1:]
    if "-h" in arguments or "--help" in arguments:
        print(f"Usage: {Path(sys.argv[0]).name} [--release] [ROM] [sor options...]")
        return 0
    release = False
    rom: str | None = None
    program_arguments: list[str] = []
    option_expects_value = False
    for argument in arguments:
        if argument == "--release":
            release = True
        elif argument.startswith("-"):
            program_arguments.append(argument)
            option_expects_value = True
        elif rom is None and not option_expects_value:
            rom = argument
        else:
            program_arguments.append(argument)
            option_expects_value = False
    sor_root = META_ROOT / "StreetsOfRageRecompilation"
    rom = str(absolute_path(rom or os.environ.get("SOR_ROM", sor_root / "rom" / "SOR.bin")))
    if subprocess.run(script_command("generate_cpp.py", rom)).returncode:
        return 1
    if subprocess.run(script_command("build.py", *( ["--release"] if release else [] ))).returncode:
        return 1
    return subprocess.run(script_command("run.py", rom, *program_arguments)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
