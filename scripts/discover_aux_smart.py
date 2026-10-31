#!/usr/bin/env python3
"""Discover indirect dispatch targets with speculative pre-generation."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from _common import META_ROOT, absolute_path, built_executable, prepend_pythonpath, script_command


ADDRESS = re.compile(r"^\s*[0-9a-fA-F]{6}\s*$")


def sort_aux_addresses(path: Path) -> None:
    lines = path.read_text().splitlines()
    path.write_text("\n".join([
        *(line for line in lines if not ADDRESS.fullmatch(line)),
        *sorted({line.strip().upper() for line in lines if ADDRESS.fullmatch(line)}),
    ]) + "\n")


def main() -> int:
    if sys.argv[1:] and sys.argv[1] in {"-h", "--help"}:
        print(f"Usage: {Path(sys.argv[0]).name} [sor options...]")
        return 0
    sor_root = META_ROOT / "StreetsOfRageRecompilation"
    auxiliary = sor_root / "code-analysis" / "aux_addresses.txt"
    speculative = sor_root / "code-analysis" / "speculative_addresses.txt"
    rom = absolute_path(os.environ.get("SOR_ROM", sor_root / "rom" / "SOR.bin"))
    maximum = int(os.environ.get("MAX_ITERS", "500"))
    if not rom.is_file():
        print(f"ROM not found: {rom}", file=sys.stderr)
        return 1
    sort_aux_addresses(auxiliary)
    original_count = sum(1 for line in auxiliary.read_text().splitlines() if ADDRESS.fullmatch(line))
    environment = os.environ.copy()
    prepend_pythonpath(environment, META_ROOT / "RageDecompiler")
    with tempfile.TemporaryDirectory(prefix="sor_smart_") as temporary:
        assembly, coverage = Path(temporary) / "sor.asm", Path(temporary) / "sor.map"
        print("==> [smart] Refreshing coverage map from current aux addresses...")
        if subprocess.run([sys.executable, "-m", "tools", "disassemble", str(rom), "-o", str(assembly), "-a", str(auxiliary), "--map", str(coverage)], env=environment).returncode:
            return 1
        print("==> [smart] Scanning for speculative entry points...")
        if subprocess.run([sys.executable, "-m", "tools", "speculative-scan", str(coverage), str(rom), str(auxiliary), "-o", str(speculative)], env=environment).returncode:
            return 1
    def build() -> int:
        build_environment = os.environ.copy()
        build_environment["SOR_ROM"] = str(rom)
        return subprocess.run(script_command("build.py", "--full", "--discover"), env=build_environment).returncode
    if build():
        return 1
    for iteration in range(1, maximum + 1):
        executable = built_executable(sor_root / "build", "sor")
        print(f"==> [smart {iteration}] run")
        code = subprocess.run([str(executable), "--rom", str(rom), "--aux-addr-file", str(auxiliary), *sys.argv[1:], "--debug-utils", "--lang", "en", "--turbo", "4"]).returncode
        sort_aux_addresses(auxiliary)
        if code == 42:
            print(f"==> [smart {iteration}] new unknown address recorded; rebuilding")
            if build():
                return 1
        elif code == 43:
            print("==> STUCK: a seeded address still has no handler.", file=sys.stderr)
            return 1
        else:
            current = sum(1 for line in auxiliary.read_text().splitlines() if ADDRESS.fullmatch(line))
            print(f"==> [smart {iteration}] exited {code}. Added {current - original_count} address(es).")
            return 0
    print(f"Reached MAX_ITERS={maximum} without converging.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
