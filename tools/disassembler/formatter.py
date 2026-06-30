"""Formats decoded 68000 instructions as standard 68000 assembly text.

Assembly syntax:
  * Comments      ``;``  — to end of line
  * Labels       ``label_name:``  — at column 0, no indentation
  * Instructions TAB-indented
  * Hex literals ``$`` prefix (e.g. ``$FF``, ``$FFFF0000``)
  * Registers    lowercase  (d0–d7, a0–a7, sp, sr, ccr, pc)
  * Sizes        ``.b``  (byte), ``.w`` (word/short), ``.l`` (long),
                 ``.s``  (branch short)

Label naming convention
=======================
The formatter applies consistent label prefixes based on how the
:class:`Disassembler` classified each address:

:``sub_XXXXXX``:  Subroutine entry point (discovered via JSR/BSR)
:``loc_XXXXXX``:  Branch/jump target (plain label)
:``$XXXXXX``:     Raw hex — used for absolute addresses that are neither
                  a known subroutine entry nor a known branch target

Output structure
================
The formatter emits a single continuous ``org $000200`` block (the
standard ROM load address).  Gaps between non-adjacent instruction
blocks are bridged with ``org $XXXXXX`` directives so the assembly
remains relocatable.
"""

from dataclasses import dataclass

from .instruction import Addr, Instruction


@dataclass
class AuxAddress:
    label: str
    comment: str


@dataclass
class Block:
    start: int
    end: int
    name: str


class AsmFormatter:
    """Converts a Disassembler result into a .asm source string.

    Parameters
    ----------
    instructions:
        Decoded instruction map ``{addr: Instruction}``.
    subroutines:
        Set of addresses that are subroutine entry points (label prefix
        ``sub_``).
    labels:
        Set of addresses that are branch/jump targets (label prefix
        ``loc_``).
    rom_name:
        Displayed in the file header comment.
    csv_addresses:
        Optional dict of {addr: AuxAddress} from addresses.csv.
    csv_blocks:
        Optional list of Block from blocks.csv.
    csv_labels:
        Optional dict of {addr: label_name} from labels.csv.
    csv_label_comments:
        Optional dict of {addr: comment} from labels.csv.
    """

    def __init__(self, instructions: dict,
                 subroutines: set[int],
                 labels: set[int],
                 rom_name: str = 'Streets of Rage',
                 csv_addresses: dict[int, AuxAddress] | None = None,
                 csv_blocks: list[Block] | None = None,
                 csv_labels: dict[int, str] | None = None,
                 csv_label_comments: dict[int, str] | None = None) -> None:
        self.instructions = instructions
        self.subroutines  = subroutines
        self.labels       = labels
        self.rom_name     = rom_name
        self.csv_addresses = csv_addresses or {}
        self.csv_blocks   = csv_blocks or []
        self.csv_labels   = csv_labels or {}
        self.csv_label_comments = csv_label_comments or {}

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def format(self) -> str:
        """Return the full .asm text."""
        lines: list[str] = []
        self._header(lines)
        self._equ_section(lines)

        sorted_addrs = sorted(self.instructions)
        if not sorted_addrs:
            return '\n'.join(lines)

        # org directive before first instruction block
        lines.append(f'\torg ${sorted_addrs[0]:08X}')
        lines.append('')

        prev_end = None   # expected address of the next instruction
        prev_addr = None  # previous address processed

        for addr in sorted_addrs:
            instr = self.instructions[addr]

            # Insert org directive when there is a gap (data region skipped)
            if prev_end is not None and addr != prev_end:
                lines.append('')
                lines.append(f'\torg ${addr:08X}')
                lines.append('')

            # Label (if any) — blank line before subroutines when jumped to
            for lbl, comment in self._labels_at(addr):
                is_sub = (
                    addr in self.csv_labels
                    or (addr in self.csv_addresses and addr not in self.labels)
                    or addr in self.subroutines
                )
                # Add blank line if we jumped here (not the next sequential address)
                if is_sub and lines and prev_addr is not None and addr != prev_end:
                    lines.append('')
                if comment:
                    lines.append(f'{lbl}:{" " * max(0, 58 - len(lbl))}; ${addr:08X} | {comment}')
                else:
                    lines.append(f'{lbl}:')

            # Instruction line
            lines.append(self._fmt_instr(instr))

            # Blank line after RTS for readability
            if instr.mnemonic == 'rts':
                lines.append('')

            prev_end = instr.next_address
            prev_addr = addr

        return '\n'.join(lines) + '\n'

    # ------------------------------------------------------------------
    # SR bit descriptions (68000 Status Register)
    # ------------------------------------------------------------------

    _SR_BITS = [
        (15, 'T',  'Trace mode'),
        (12, 'I2', 'Interrupt priority mask bit 2'),
        (11, 'I1', 'Interrupt priority mask bit 1'),
        (10, 'I0', 'Interrupt priority mask bit 0'),
        ( 8, 'F',  'Function code mask bit 2'),
        ( 7, 'F',  'Function code mask bit 1'),
        ( 6, 'F',  'Function code mask bit 0'),
        ( 3, 'M',  'Master/interrupt stack'),
        ( 2, 'S',  'Supervisor mode'),
        ( 1, 'X',  'Extend'),
        ( 0, 'C',  'Carry'),
    ]

    def _sr_binary_comment(self, val: int) -> str:
        """Return a binary comment string for a 16-bit SR value."""
        parts = []
        for bit, abbr, name in self._SR_BITS:
            if val & (1 << bit):
                parts.append(f'{abbr}')
            else:
                parts.append(f'{abbr}:0')
        return ' '.join(parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _header(self, lines: list[str]) -> None:
        lines += [
            f'; {self.rom_name} — Disassembly',
            f'; Generated by tools/disassembler',
            '',
        ]

    def _equ_section(self, lines: list[str]) -> None:
        """Emit EQU definitions from addresses.csv and blocks.csv."""
        # Calculate longest label width for alignment
        max_label_len = max(
            len(blk.name) for blk in self.csv_blocks
        ) if self.csv_blocks else 0
        max_label_len = max(
            max_label_len,
            max(len(aux.label) for aux in self.csv_addresses.values())
        ) if self.csv_addresses else max_label_len

        # Block EQUs first
        for blk in self.csv_blocks:
            lines.append(f'{blk.name:<{max_label_len}} equ ${blk.start:08X}')

        # Per-address EQUs (custom labels) - comments at column 60
        # Layout: label (col 0), space, "equ" (col N+1), space, $XXXXXXXX (col N+5), spaces to col 60
        for addr, aux in sorted(self.csv_addresses.items()):
            if aux.comment:
                spaces = 60 - (max_label_len + 15)  # 60 = comment column, 15 = " equ $XXXXXXXX "
                lines.append(f'{aux.label:<{max_label_len}} equ ${addr:08X}{" " * spaces}; {aux.comment}')
            else:
                lines.append(f'{aux.label:<{max_label_len}} equ ${addr:08X}')

        if self.csv_blocks or self.csv_addresses:
            lines.append('')

    def _labels_at(self, addr: int) -> list[tuple[str, str]]:
        """Return zero or one (label, comment) tuple for *addr*."""
        # CSV addresses take priority
        if addr in self.csv_addresses:
            aux = self.csv_addresses[addr]
            return [(aux.label, aux.comment)]
        # CSV labels (code segments)
        if addr in self.csv_labels:
            label = self.csv_labels[addr]
            comment = self.csv_label_comments.get(addr, '')
            return [(label, comment)]
        if addr in self.subroutines:
            return [(f'sub_{addr:08X}', '')]
        if addr in self.labels:
            return [(f'loc_{addr:08X}', '')]
        return []

    def _block_for(self, addr: int) -> Block | None:
        """Return the block that contains addr, or None."""
        for blk in self.csv_blocks:
            if blk.start <= addr < blk.end:
                return blk
        return None

    def _get_label(self, addr: int) -> str:
        """Return a label name for *addr*, or a raw ``$XXXXXXXX`` string."""
        # CSV addresses take priority
        if addr in self.csv_addresses:
            return self.csv_addresses[addr].label
        if addr in self.csv_labels:
            return self.csv_labels[addr]
        if addr in self.subroutines:
            return f'sub_{addr:08X}'
        if addr in self.labels:
            return f'loc_{addr:08X}'
        # Check if addr falls in a block
        blk = self._block_for(addr)
        if blk is not None:
            offset = addr - blk.start
            return f'{blk.name}+${offset:04X}'
        # Unknown — use raw hex
        return f'${addr:08X}'

    def _fmt_operand(self, op) -> str:
        if not isinstance(op, Addr):
            return str(op)

        label = self._get_label(op.value)

        form = op.form
        if form == 'branch':
            return label

        if form == 'abs_w':
            # Raw 16-bit value; sign-extend for display
            val16 = op.value & 0xFFFF
            if val16 >= 0x8000:
                # Negative address - sign-extend to 32-bit before label lookup
                eff_addr = (val16 - 0x10000) & 0xFFFFFFFF
                label = self._get_label(eff_addr)
                addr_s = label if not label.startswith('$') else f'${eff_addr:08X}'
            else:
                # Positive address
                addr_s = label if not label.startswith('$') else f'${val16:04X}'
            return f'({addr_s}).w'

        if form == 'abs_l':
            addr_s = label if not label.startswith('$') else f'${op.value:06X}'
            return f'({addr_s}).l'

        if form == 'pc_rel':
            addr_s = label if not label.startswith('$') else f'${op.value:06X}'
            return f'{addr_s}(pc)'

        if form == 'pc_rel_idx':
            # Cannot substitute a clean label here (runtime index added)
            return f'${op.value:06X}(pc,{op.suffix})'

        return f'${op.value:06X}'

    def _fmt_instr(self, instr: Instruction) -> str:
        mnem = instr.mnemonic
        if instr.size:
            mnem = f'{mnem}.{instr.size}'
        if instr.operands:
            ops = ', '.join(self._fmt_operand(o) for o in instr.operands)
            base = f'\t{mnem} {ops}'

            # Detect move to SR with immediate value: move #$,sr
            if (mnem.startswith('move') and
                    len(instr.operands) == 2 and
                    str(instr.operands[1]) == 'sr'):
                src = str(instr.operands[0])
                if src.startswith('#$'):
                    try:
                        val = int(src[2:], 16)
                        bin_s = format(val, '016b')
                        comment = self._sr_binary_comment(val)
                        pad = 60 - _visual_width(base)
                        return base + ' ' * max(1, pad) + f'; {bin_s}  ({comment})'
                    except ValueError:
                        pass

            return base
        return f'\t{mnem}'


def _visual_width(s: str) -> int:
    """Return the display width of *s*, treating tab as 8 characters."""
    return sum(8 if c == '\t' else 1 for c in s)
