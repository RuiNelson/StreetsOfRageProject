#!/usr/bin/env python3
"""
Iterative disassembler loop.

1. Run the disassembler with the current aux_addresses.txt.
2. Compare output/sor.asm against etc/sor-exodus.asm via map_label_gaps.
3. Extract the first missing address and append it to aux_addresses.txt.
4. Repeat until no more addresses are missing.
"""

import subprocess
import re
import sys
from pathlib import Path

ROOT = Path.cwd()
SOR_ASM = Path(sys.argv[1])
SOR_MAP = Path(sys.argv[2])
EXODUS_ASM = Path(sys.argv[3])
AUX = Path(sys.argv[4])
ROM = Path(sys.argv[5])
MAP_LABEL_GAPS = ROOT / "tools" / "label_diff" / "map_label_gaps.py"

STATS_RE = re.compile(
    r"(\d+)\s+instructions?\s+decoded?,\s+(\d+)\s+subroutines?,\s+(\d+)\s+labels?",
    re.IGNORECASE,
)


def run_disassembler():
    result = subprocess.run(
        [
            sys.executable, "-m", "tools.disassembler",
            str(ROM),
            "-o", str(SOR_ASM),
            "-a", str(AUX),
            "--map", str(SOR_MAP),
            "-v",
        ],
        capture_output=True,
        text=True,
    )
    output = result.stderr  # verbose output goes to stderr
    m = STATS_RE.search(output)
    if not m:
        raise RuntimeError(f"Could not parse disassembler stats:\n{output}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def get_first_missing_address():
    result = subprocess.run(
        [sys.executable, str(MAP_LABEL_GAPS), str(SOR_MAP), str(EXODUS_ASM)],
        capture_output=True,
        text=True,
    )
    lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    if not lines:
        return None
    return int(lines[0], 16)


def append_address(addr: int):
    with open(AUX, "a") as f:
        f.write(f"{addr:08x}\n")


def fmt_delta(new: int, old: int | None) -> str:
    if old is None:
        return "     —"
    d = new - old
    sign = "+" if d > 0 else ""
    return f"{sign}{d}"


def main():
    print(f"{'Addr':<12} {'Instructs':>10} {'Subroutines':>12} {'Labels':>8} {'ΔInstr':>8} {'ΔSub':>6} {'ΔLbl':>6}")
    print("-" * 70)

    prev_instr, prev_sub, prev_lbl = None, None, None
    iteration = 0

    while True:
        iteration += 1
        instr, sub, lbl = run_disassembler()

        addr = get_first_missing_address()
        if addr is None:
            print(f"\nNo more missing addresses after {iteration} iteration(s).")
            break

        append_address(addr)
        print(
            f"{addr:08x}   {instr:>10} {sub:>12} {lbl:>8} "
            f"{fmt_delta(instr, prev_instr):>8} {fmt_delta(sub, prev_sub):>6} {fmt_delta(lbl, prev_lbl):>6}"
        )

        prev_instr, prev_sub, prev_lbl = instr, sub, lbl

    print(f"\nFinal aux_addresses.txt has {iteration} extra address(es).")


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print(f"Usage: {sys.argv[0]} <sor.asm> <sor.map> <sor-exodus.asm> <aux_addresses.txt> <rom.bin>")
        sys.exit(1)
    main()
