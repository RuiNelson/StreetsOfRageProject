#!/usr/bin/env python3
import re
import sys

PATTERN = re.compile(r'^\s*(?:loc|sub)_([0-9a-fA-F]+):', re.IGNORECASE)

def extract_labels(path):
    labels = set()
    with open(path) as f:
        for line in f:
            m = PATTERN.match(line)
            if m:
                labels.add(int(m.group(1), 16))
    return labels

if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} <file1.asm> <file2.asm>")
    sys.exit(1)

labels1 = extract_labels(sys.argv[1])
labels2 = extract_labels(sys.argv[2])

only_in_2 = sorted(labels2 - labels1)

for n in only_in_2:
    print(f"{n:08x}")
