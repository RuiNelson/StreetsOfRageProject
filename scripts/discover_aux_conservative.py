#!/usr/bin/env python3
"""Iteratively discover confirmed indirect dispatch targets."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from _common import META_ROOT, absolute_path, built_executable, script_command


ADDRESS = re.compile(r"^\s*[0-9a-fA-F]{6}\s*$")


def sort_aux_addresses(path: Path) -> None:
    lines = path.read_text().splitlines()
    non_addresses = [line for line in lines if not ADDRESS.fullmatch(line)]
    addresses = sorted({line.strip().upper() for line in lines if ADDRESS.fullmatch(line)})
    path.write_text("\n".join([*non_addresses, *addresses]) + "\n")


def main() -> int:
    if sys.argv[1:] and sys.argv[1] in {"-h", "--help"}:
        print(f"Usage: {Path(sys.argv[0]).name} [sor options...]")
        return 0
    sor_root = META_ROOT / "StreetsOfRageRecompilation"
    auxiliary = sor_root / "code-analysis" / "aux_addresses.txt"
    rom = absolute_path(os.environ.get("SOR_ROM", sor_root / "rom" / "SOR.bin"))
    maximum = int(os.environ.get("MAX_ITERS", "500"))
    if not rom.is_file():
        print(f"ROM not found: {rom}", file=sys.stderr)
        return 1
    sort_aux_addresses(auxiliary)
    for iteration in range(1, maximum + 1):
        print(f"==> [discover {iteration}] regenerate + build (--full)")
        environment = os.environ.copy()
        environment["SOR_ROM"] = str(rom)
        if subprocess.run(script_command("build.py", "--full"), env=environment).returncode:
            return 1
        executable = built_executable(sor_root / "build", "sor")
        print(f"==> [discover {iteration}] run")
        code = subprocess.run([str(executable), "--auxAddrFile", str(auxiliary), "--rom", str(rom), *sys.argv[1:]]).returncode
        sort_aux_addresses(auxiliary)
        if code == 42:
            print(f"==> [discover {iteration}] recorded a new address; re-seeding")
        elif code == 43:
            print("==> STUCK: a seeded address still has no handler.", file=sys.stderr)
            return 1
        else:
            print(f"==> [discover {iteration}] exited {code} (not an unknown dispatch).", file=sys.stderr)
            return code
    print(f"Reached MAX_ITERS={maximum} without converging.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
