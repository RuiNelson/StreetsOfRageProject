#!/usr/bin/env python3
"""Disassemble a compatible ROM into the local analysis outputs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from _common import META_ROOT, absolute_path, prepend_pythonpath


def main() -> int:
    arguments = sys.argv[1:]
    if arguments and arguments[0] in {"-h", "--help"}:
        print(f"Usage: {Path(sys.argv[0]).name} [ROM]")
        return 0
    if len(arguments) > 1 or (arguments and arguments[0].startswith("-")):
        print(f"Usage: {Path(sys.argv[0]).name} [ROM]", file=sys.stderr)
        return 2
    sor_root = META_ROOT / "StreetsOfRageRecompilation"
    rom = absolute_path(arguments[0] if arguments else os.environ.get("SOR_ROM", sor_root / "rom" / "SOR.bin"))
    if not rom.is_file():
        print(f"ROM not found: {rom}", file=sys.stderr)
        return 1
    (sor_root / "output").mkdir(exist_ok=True)
    environment = os.environ.copy()
    prepend_pythonpath(environment, META_ROOT / "RageDecompiler")
    return subprocess.run([
        sys.executable, "-m", "tools", "disassemble", str(rom), "-o", str(sor_root / "output" / "sor.asm"),
        "-a", str(sor_root / "code-analysis" / "aux_addresses.txt"),
        "--addresses-csv", str(sor_root / "code-analysis" / "addresses.csv"),
        "--blocks-csv", str(sor_root / "code-analysis" / "blocks.csv"),
        "--labels-csv", str(sor_root / "code-analysis" / "labels.csv"),
        "--map", str(sor_root / "output" / "sor.map"), "-v",
    ], env=environment).returncode


if __name__ == "__main__":
    raise SystemExit(main())
