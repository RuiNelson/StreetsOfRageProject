#!/usr/bin/env python3
"""Generate the local C++ recompilation from a compatible ROM."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from _common import META_ROOT, absolute_path, prepend_pythonpath


def scan_speculative(rom: Path, auxiliary: Path, speculative: Path, environment: dict[str, str]) -> int:
    """Write speculative_addresses.txt (ignored by Git) from the ROM's current coverage."""
    with tempfile.TemporaryDirectory(prefix="sor_spec_") as temporary:
        assembly, coverage = Path(temporary) / "sor.asm", Path(temporary) / "sor.map"
        code = subprocess.run([sys.executable, "-m", "tools", "disassemble", str(rom), "-o", str(assembly), "-a", str(auxiliary), "--map", str(coverage)], env=environment).returncode
        if code:
            return code
        return subprocess.run([sys.executable, "-m", "tools", "speculative-scan", str(coverage), str(rom), str(auxiliary), "-o", str(speculative)], env=environment).returncode


def main() -> int:
    arguments = sys.argv[1:]
    usage = f"Usage: {Path(sys.argv[0]).name} [--speculative] [ROM]"
    if arguments and arguments[0] in {"-h", "--help"}:
        print(usage)
        print("  --speculative   Also compile the speculative entry points (the PS5 build; the ones reached are logged to confirmed.txt).")
        return 0
    speculative_flag = "--speculative" in arguments
    arguments = [argument for argument in arguments if argument != "--speculative"]
    if len(arguments) > 1:
        print(usage, file=sys.stderr)
        return 2
    sor_root = META_ROOT / "StreetsOfRageRecompilation"
    rom = absolute_path(arguments[0] if arguments else os.environ.get("SOR_ROM", sor_root / "rom" / "SOR.bin"))
    if not rom.is_file():
        print(f"ROM not found: {rom}", file=sys.stderr)
        return 1
    environment = os.environ.copy()
    prepend_pythonpath(environment, META_ROOT / "RageDecompiler")
    auxiliary = sor_root / "code-analysis" / "aux_addresses.txt"
    speculative = sor_root / "code-analysis" / "speculative_addresses.txt"
    extra: list[str] = []
    if speculative_flag:
        print("==> Scanning for speculative entry points...")
        if scan_speculative(rom, auxiliary, speculative, environment):
            return 1
        extra = ["--speculative", str(speculative)]
    return subprocess.run([
        sys.executable, "-m", "tools", "recompile", str(rom), "-o", str(sor_root / "generated"),
        *extra,
        "--aux", str(auxiliary),
        "--labels-csv", str(sor_root / "code-analysis" / "labels.csv"),
        "--addresses-csv", str(sor_root / "code-analysis" / "addresses.csv"),
        "--manual-functions", str(sor_root / "code-analysis" / "manual_functions.txt"),
    ], env=environment).returncode


if __name__ == "__main__":
    raise SystemExit(main())
