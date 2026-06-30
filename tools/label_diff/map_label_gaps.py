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


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <rom.map> <reference.asm>")
        sys.exit(1)

    map_path = Path(sys.argv[1])
    asm_path = Path(sys.argv[2])

    rom_map = map_path.read_bytes()

    for addr in extract_labels(asm_path):
        if addr < len(rom_map) and rom_map[addr:addr+1] == b'X':
            print(f"{addr:08X}")


if __name__ == '__main__':
    main()
