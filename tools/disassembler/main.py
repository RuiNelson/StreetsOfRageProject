#!/usr/bin/env python3
"""CLI entry point for the Streets of Rage disassembler.

Usage
-----
    python3 tools/disassembler/main.py rom/StreetsOfRage.bin -o output/sor.asm
    python3 tools/disassembler/main.py rom/StreetsOfRage.bin -o output/sor.asm \\
        -a aux_addresses.txt --map output/sor.map
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.common.addresses import parse_address_lines


@dataclass
class AuxAddress:
    label: str
    comment: str


@dataclass
class Block:
    start: int
    end: int   # exclusive
    name: str


def _load_csv_addresses(path: str) -> dict[int, AuxAddress]:
    """Load addresses.csv: address(hex), label, comment

    Lines starting with '#' or ';' are ignored.
    """
    result: dict[int, AuxAddress] = {}
    with open(path, newline='', encoding='utf-8') as f:
        for lineno, row in enumerate(csv.reader(f), 1):
            if not row:
                continue
            raw = row[0].strip()
            if raw.startswith('#') or raw.startswith(';'):
                continue
            if len(row) < 2:
                continue
            try:
                addr = int(row[0].strip(), 16)
            except ValueError:
                print(f'Warning: bad address on line {lineno} of {path!r}',
                      file=sys.stderr)
                continue
            label = row[1].strip()
            # Handle improperly-quoted CSV fields (space before quote splits the field)
            raw_comment = ','.join(row[2:]).strip() if len(row) > 2 else ''
            comment = raw_comment.strip().strip('"')
            result[addr] = AuxAddress(label=label, comment=comment)
    return result


def _load_csv_blocks(path: str) -> list[Block]:
    """Load blocks.csv: start(hex), end(hex), name

    Lines starting with '#' or ';' are ignored.
    """
    result: list[Block] = []
    with open(path, newline='', encoding='utf-8') as f:
        for lineno, row in enumerate(csv.reader(f), 1):
            if not row:
                continue
            raw = row[0].strip()
            if raw.startswith('#') or raw.startswith(';'):
                continue
            if len(row) < 3:
                continue
            try:
                start = int(row[0].strip(), 16)
                end = int(row[1].strip(), 16)
                name = row[2].strip()
            except ValueError:
                print(f'Warning: bad block on line {lineno} of {path!r}',
                      file=sys.stderr)
                continue
            result.append(Block(start=start, end=end, name=name))
    return result


def _load_labels_csv(path: str) -> tuple[dict[int, str], dict[int, str]]:
    """Load labels.csv: address(hex), label, comment

    Lines starting with '#' or ';' are ignored.
    Returns ({address: label_name}, {address: comment}).
    """
    labels: dict[int, str] = {}
    comments: dict[int, str] = {}
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.reader(f):
            if not row:
                continue
            raw = row[0].strip()
            if raw.startswith('#') or raw.startswith(';'):
                continue
            try:
                addr = int(row[0].strip(), 16)
                label = row[1].strip()
                # Handle improperly-quoted CSV fields (space before quote splits the field)
                raw_comment = ','.join(row[2:]).strip() if len(row) > 2 else ''
                comment = raw_comment.strip().strip('"')
            except (ValueError, IndexError):
                continue
            labels[addr] = label
            if comment:
                comments[addr] = comment
    return labels, comments


def _load_aux(path: str) -> list[int]:
    """Load a plain-text auxiliary address file.

    Each line is a 6-digit hex address.  Lines starting with ``;`` and blank
    lines are ignored.  Inline comments (after the address) are also stripped.
    """
    return parse_address_lines(path, warn_prefix='Warning:')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Recursive-descent 68000 disassembler for Streets of Rage.')
    parser.add_argument('rom',
                        help='Path to the ROM binary (e.g. rom/StreetsOfRage.bin)')
    parser.add_argument('-o', '--output', required=True,
                        help='Output .asm file path')
    parser.add_argument('-a', '--aux',
                        help='Auxiliary address file (extra subroutine entry points)')
    parser.add_argument('--addresses-csv',
                        help='CSV with address,label,comment (see docs)')
    parser.add_argument('--blocks-csv',
                        help='CSV with start,end,name for memory blocks (see docs)')
    parser.add_argument('--labels-csv',
                        help='CSV with code segment addresses (see docs)')
    parser.add_argument('--map',
                        help='Write a ROM coverage map to this path')
    parser.add_argument('--indirect-jumps',
                        help='Write addresses of unresolved indirect jumps/calls to this path')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Print progress to stderr')
    args = parser.parse_args(argv)

    # --- Lazy imports so the module is importable without side-effects ---
    from .rom          import ROM
    from .disassembler import Disassembler
    from .formatter    import AsmFormatter
    from .rom_map      import RomMap

    # Load ROM
    if args.verbose:
        print(f'[disasm] Loading ROM: {args.rom}', file=sys.stderr)
    rom = ROM.from_file(args.rom)

    # Load optional auxiliary addresses
    aux: list[int] = []
    if args.aux:
        aux = _load_aux(args.aux)
        if args.verbose:
            print(f'[disasm] {len(aux)} auxiliary address(es) loaded', file=sys.stderr)

    # Load optional CSV files
    csv_addresses: dict[int, AuxAddress] = {}
    csv_blocks: list[Block] = []
    csv_labels: dict[int, str] = {}
    csv_label_comments: dict[int, str] = {}

    if args.addresses_csv:
        csv_addresses = _load_csv_addresses(args.addresses_csv)
        if args.verbose:
            print(f'[disasm] {len(csv_addresses)} addresses loaded from {args.addresses_csv}',
                  file=sys.stderr)

        # Auto-generate 32-bit mirror addresses for work RAM (FF0000-FFFFFF)
        # e.g. FFFF00 → FFFFFF00 (label becomes game_state_)
        work_ram_start = 0xFF0000
        work_ram_end = 0xFFFFFF
        mirrors_added = 0
        for addr in list(csv_addresses.keys()):
            if work_ram_start <= addr <= work_ram_end:
                mirror_addr = addr | 0xFF000000  # Prepend FF to make 32-bit address
                src_aux = csv_addresses[addr]
                if mirror_addr not in csv_addresses:
                    csv_addresses[mirror_addr] = AuxAddress(
                        label=src_aux.label + '_',
                        comment=src_aux.comment
                    )
                    mirrors_added += 1
                elif not csv_addresses[mirror_addr].comment and src_aux.comment:
                    # Mirror exists but without comment - fill it in from source
                    csv_addresses[mirror_addr].comment = src_aux.comment
        if args.verbose and mirrors_added:
            print(f'[disasm] {mirrors_added} work RAM mirror addresses auto-generated',
                  file=sys.stderr)

    if args.blocks_csv:
        csv_blocks = _load_csv_blocks(args.blocks_csv)
        if args.verbose:
            print(f'[disasm] {len(csv_blocks)} blocks loaded from {args.blocks_csv}',
                  file=sys.stderr)

    if args.labels_csv:
        csv_labels, csv_label_comments = _load_labels_csv(args.labels_csv)
        if args.verbose:
            print(f'[disasm] {len(csv_labels)} code labels loaded from {args.labels_csv}',
                  file=sys.stderr)

    # Disassemble
    disasm = Disassembler(rom, aux_addresses=aux, verbose=args.verbose)
    disasm.disassemble()

    # Format assembly output
    formatter = AsmFormatter(
        disasm.instructions,
        disasm.subroutines,
        disasm.labels,
        rom_name='Streets of Rage',
        csv_addresses=csv_addresses,
        csv_blocks=csv_blocks,
        csv_labels=csv_labels,
        csv_label_comments=csv_label_comments,
    )
    asm_text = formatter.format()

    # Write .asm
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(asm_text, encoding='utf-8')
    if args.verbose:
        print(f'[disasm] Wrote assembly: {out_path}', file=sys.stderr)

    # Write indirect jumps (optional)
    if args.indirect_jumps:
        lines = []
        for addr in disasm.indirect_warnings:
            lines.append(f'${addr:08X}')
        ij_path = Path(args.indirect_jumps)
        ij_path.parent.mkdir(parents=True, exist_ok=True)
        ij_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        if args.verbose:
            print(f'[disasm] Wrote indirect jumps: {ij_path}', file=sys.stderr)

    # Write ROM map (optional)
    if args.map:
        rmap = RomMap(
            rom.size,
            disasm.instructions,
            disasm.subroutines,
            disasm.labels,
        )
        map_path = Path(args.map)
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_bytes(rmap.format())
        if args.verbose:
            print(f'[disasm] Wrote ROM map:  {map_path}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
