#!/usr/bin/env python3
"""
Find labels in an asm file that point to addresses marked as data/unknown ('X')
in the ROM coverage map.

Usage
-----
    python3 tools/label_diff/map_label_gaps.py <rom.map> <reference.asm>

Output
------
One hex address (8 digits, uppercase) per line for each label that lands on
an 'X' byte in the map.
"""

import re
import sys
from pathlib import Path

LABEL_RE = re.compile(r'^\s*(?:loc|sub)_([0-9a-fA-F]+):', re.IGNORECASE)


def extract_labels(path: Path) -> list[int]:
    labels = []
    with path.open() as f:
        for line in f:
            m = LABEL_RE.match(line)
            if m:
                labels.append(int(m.group(1), 16))
    return sorted(labels)


def find_gaps(map_path: Path, asm_path: Path) -> list[int]:
    rom_map = map_path.read_bytes()
    return [
        addr for addr in extract_labels(asm_path)
        if addr < len(rom_map) and rom_map[addr:addr+1] == b'X'
    ]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or (argv and argv[0] in ('-h', '--help')):
        print("Usage: python3 -m tools map-label-gaps <rom.map> <reference.asm>")
        return 0 if argv and argv[0] in ('-h', '--help') else 1

    map_path = Path(argv[0])
    asm_path = Path(argv[1])

    for addr in find_gaps(map_path, asm_path):
        print(f"{addr:08X}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
