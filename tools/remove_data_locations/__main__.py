#!/usr/bin/env python3
"""Remove locations containing data (dc.b/dc.w) from sor-exodus.asm"""

import re
import sys

BLOCK_START = re.compile(r'^loc_[0-9A-F]+:')

def is_data_line(line):
    """Check if a line is a data directive (dc.b, dc.w)"""
    stripped = line.strip()
    return stripped.startswith('dc.b') or stripped.startswith('dc.w') or stripped.startswith('dc.l')

def process_file(filename):
    with open(filename, 'r') as f:
        lines = f.readlines()

    # Step 1: Split into blocks (each block starts with a label)
    blocks = []
    current_block = []

    for line in lines:
        if BLOCK_START.match(line.strip()):
            if current_block:
                blocks.append(current_block)
            current_block = [line]
        else:
            current_block.append(line)

    if current_block:
        blocks.append(current_block)

    # Step 2: Filter blocks that contain data (dc.b, dc.w)
    filtered_blocks = []
    for block in blocks:
        has_data = any(is_data_line(l) for l in block)
        if not has_data:
            filtered_blocks.append(block)

    # Step 3: Reconstruct the file
    result = []
    for block in filtered_blocks:
        result.extend(block)

    return result

def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ('-h', '--help'):
        print("Usage: python3 -m tools remove-data [asm-file]")
        return 0
    filename = argv[0] if argv else 'etc/sor-exodus.asm'
    result = process_file(filename)
    with open(filename, 'w') as f:
        f.writelines(result)
    print(f"Processed {filename}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
