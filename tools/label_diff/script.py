#!/usr/bin/env python3
import re
import sys
from pathlib import Path

PATTERN = re.compile(r'^\s*(?:loc|sub)_([0-9a-fA-F]+):', re.IGNORECASE)

def extract_labels(path: str | Path) -> set[int]:
    labels = set()
    with open(path) as f:
        for line in f:
            m = PATTERN.match(line)
            if m:
                labels.add(int(m.group(1), 16))
    return labels


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or (argv and argv[0] in ('-h', '--help')):
        print("Usage: python3 -m tools label-diff <file1.asm> <file2.asm>")
        return 0 if argv and argv[0] in ('-h', '--help') else 1

    labels1 = extract_labels(argv[0])
    labels2 = extract_labels(argv[1])

    only_in_2 = sorted(labels2 - labels1)

    for n in only_in_2:
        print(f"{n:08x}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
