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

STATS_RE = re.compile(
    r"(\d+)\s+instructions?\s+decoded?,\s+(\d+)\s+subroutines?,\s+(\d+)\s+labels?",
    re.IGNORECASE,
)


def run_disassembler(sor_asm: Path, sor_map: Path, aux: Path, rom: Path):
    result = subprocess.run(
        [
            sys.executable, "-m", "tools", "disassemble",
            str(rom),
            "-o", str(sor_asm),
            "-a", str(aux),
            "--map", str(sor_map),
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


def get_first_missing_address(sor_map: Path, exodus_asm: Path):
    result = subprocess.run(
        [sys.executable, "-m", "tools", "map-label-gaps",
         str(sor_map), str(exodus_asm)],
        capture_output=True,
        text=True,
    )
    lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    if not lines:
        return None
    return int(lines[0], 16)


def append_address(addr: int, aux: Path):
    with open(aux, "a") as f:
        f.write(f"{addr:08x}\n")


def fmt_delta(new: int, old: int | None) -> str:
    if old is None:
        return "     —"
    d = new - old
    sign = "+" if d > 0 else ""
    return f"{sign}{d}"


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 5 or (argv and argv[0] in ('-h', '--help')):
        print("Usage: python3 -m tools iterative-disasm <sor.asm> <sor.map> <sor-exodus.asm> <aux_addresses.txt> <rom.bin>")
        return 0 if argv and argv[0] in ('-h', '--help') else 1

    sor_asm = Path(argv[0])
    sor_map = Path(argv[1])
    exodus_asm = Path(argv[2])
    aux = Path(argv[3])
    rom = Path(argv[4])

    print(f"{'Addr':<12} {'Instructs':>10} {'Subroutines':>12} {'Labels':>8} {'ΔInstr':>8} {'ΔSub':>6} {'ΔLbl':>6}")
    print("-" * 70)

    prev_instr, prev_sub, prev_lbl = None, None, None
    iteration = 0

    while True:
        iteration += 1
        instr, sub, lbl = run_disassembler(sor_asm, sor_map, aux, rom)

        addr = get_first_missing_address(sor_map, exodus_asm)
        if addr is None:
            print(f"\nNo more missing addresses after {iteration} iteration(s).")
            break

        append_address(addr, aux)
        print(
            f"{addr:08x}   {instr:>10} {sub:>12} {lbl:>8} "
            f"{fmt_delta(instr, prev_instr):>8} {fmt_delta(sub, prev_sub):>6} {fmt_delta(lbl, prev_lbl):>6}"
        )

        prev_instr, prev_sub, prev_lbl = instr, sub, lbl

    print(f"\nFinal aux_addresses.txt has {iteration} extra address(es).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
