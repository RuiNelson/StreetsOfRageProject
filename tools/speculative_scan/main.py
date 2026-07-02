#!/usr/bin/env python3
"""
Scan unmapped ('X') ROM regions for 68000 function entry point candidates.

Usage:
    python3 -m tools.speculative_scan output/sor.map rom/SOR.bin code-analysis/aux_addresses.txt

Output:
    code-analysis/speculative_addresses.txt

Map byte key (from tools/disassembler/rom_map.py):
    X = data/unknown   S = subroutine  s = return  L = label  C = code  c = continuation

One candidate is emitted per *function*, not per opcode: the scan walks the
unmapped regions and, at the first address that is a valid function (decodes from
there with every reachable instruction a real, translatable opcode and every path
ending cleanly at an RTS/RTE/RTR, an unconditional jump, or a merge into mapped
baseline code), it records that address and then skips past the whole run — up to
and including the terminating RTS (or unconditional jump) — before looking for the
next one. This is the "first valid opcode, ending after the RTS or similar"
guarantee, and because the whole reachable closure is validated the recompiler
never emits an "invalid opcode" / "decode error" warning for what is written.
"""

import argparse
from pathlib import Path

from tools.common.addresses import parse_address_lines, write_address_file
from tools.disassembler.decoder import InstructionDecoder
from tools.disassembler.instruction import FlowType
from tools.disassembler.rom import ROM
from tools.disassembler.rom_map import RomMap
from tools.recompiler.main import _disassemble_to_fixpoint, _load_aux
from tools.recompiler.opcodes import emit_dataop, FLOW_MNEMONICS, GENERATOR_MNEMONICS

# SoR cartridge code starts at $200 (below it is the vector table / header). The
# recompiler refuses to seed anything lower, so never offer such an address.
_CODE_START = 0x000200

# Mnemonics that are not real translatable opcodes: 'dc' is a Line-A/Line-F data
# word, 'illegal' is the ILLEGAL trap. Either one in a candidate's reachable code
# makes it data, not a function.
_INVALID_MNEMS = frozenset(['dc', 'illegal'])

# Baseline map bytes that mark an instruction boundary (safe to merge into).
_CODE_BOUNDARY = frozenset(ord(c) for c in 'SsLC')


class Validator:
    """Decides whether a ROM address is a valid 68000 function entry.

    ``terminates(addr)`` is True iff *no invalid instruction is reachable* from
    *addr* by following flow edges (the same edges the recursive-descent
    disassembler follows: fall-through, branch/jump targets, and call targets).
    If any reachable byte fails to decode, is a Line-A/Line-F data word, an
    ILLEGAL, or runs off the ROM, the candidate would make the disassembler warn
    and the recompiler reject it — so it is not a valid function.

    Cycles (loops, overlapping decodes) are handled by the visited set rather
    than an optimistic assumption: a node is only memoised once its *entire*
    forward closure is confirmed clean, which is sound because every node in a
    clean closure has a clean closure of its own.
    """

    def __init__(self, rom: ROM, rom_map: bytes):
        self.rom = rom
        self.map = rom_map
        self.dec = InstructionDecoder(rom)
        self._good: set[int] = set()  # confirmed: clean forward closure

    def _is_code(self, addr: int) -> bool:
        """True if *addr* is a baseline *instruction boundary* (S/s/L/C).

        Such an address was decoded during the (clean) baseline pass, so its
        closure is known good and need not be re-traversed. Continuation bytes
        ('c', inside a multi-word baseline instruction) and unknown bytes ('X')
        are NOT safe: decoding there is misaligned and must be validated.
        """
        return 0 <= addr < len(self.map) and self.map[addr] in _CODE_BOUNDARY

    @staticmethod
    def _translatable(ins) -> bool:
        """True if the recompiler can emit C++ for *ins* — same check the
        generator uses, so a candidate that passes never triggers a rejection.

        movem and the indirect/terminal flow ops are always lowered. A relative
        branch (bra/bsr/Bcc/DBcc), though, makes the generator do ``targets[0]``
        unconditionally, so a misaligned decode whose displacement runs off the
        ROM (empty ``targets``) is *not* translatable. Everything else must
        translate through ``emit_dataop`` without error."""
        m = ins.mnemonic
        if m in FLOW_MNEMONICS:
            if m in ('jmp', 'jsr', 'rts', 'rte', 'rtr'):
                return True  # generator resolves indirect / has no target operand
            return bool(ins.targets)  # relative branch — needs a resolved target
        if m in GENERATOR_MNEMONICS:
            return True
        try:
            return emit_dataop(ins) is not None
        except Exception:
            return False

    def _successors(self, ins) -> list[int]:
        """Flow successors the disassembler would follow from *ins*."""
        flow = ins.flow
        if flow is FlowType.RETURN:
            return []
        if flow is FlowType.BRANCH:
            return list(ins.targets)
        if flow in (FlowType.CALL, FlowType.CONDITIONAL):
            return list(ins.targets) + [ins.next_address]
        return [ins.next_address]  # SEQUENTIAL

    def terminates(self, start: int) -> bool:
        seen: set[int] = set()
        stack = [start]
        while stack:
            pc = stack.pop()
            if pc in seen or pc in self._good or self._is_code(pc):
                continue
            if (pc & 1) or not self.rom.in_bounds(pc, 2):
                return False
            try:
                ins = self.dec.decode(pc)
            except Exception:
                # DecodeError, or any malformed-word failure (e.g. KeyError on an
                # invalid size field) — the disassembler treats these the same.
                return False
            if ins.mnemonic in _INVALID_MNEMS or not self._translatable(ins):
                return False
            seen.add(pc)
            stack.extend(self._successors(ins))
        # Whole closure clean: every node in it is a valid entry too.
        self._good |= seen
        return True

    def run_end(self, start: int) -> int:
        """Address just past the function that begins at *start*.

        Walks the straight-line / fall-through chain (only ever advancing) until
        the terminating RTS/RTE/RTR or unconditional jump — the run ends *after*
        that instruction — or until it merges into mapped baseline code. Used to
        skip the whole function so it is recorded once, by its first opcode."""
        pc = start
        while True:
            if (pc & 1) or not self.rom.in_bounds(pc, 2):
                return pc
            if pc != start and self._is_code(pc):
                return pc
            try:
                ins = self.dec.decode(pc)
            except Exception:
                return pc
            if ins.flow in (FlowType.RETURN, FlowType.BRANCH):
                return ins.next_address  # past the rts / unconditional jump
            pc = ins.next_address


def load_known(aux_path: Path) -> set[int]:
    return set(parse_address_lines(aux_path, code_only=True))


def static_recompiler_map(rom: ROM, aux_path: Path) -> tuple[bytes, set[int]]:
    """Return coverage after the recompiler's static table-discovery fixpoint."""
    seeds = set(_load_aux(aux_path))
    disasm, seeds = _disassemble_to_fixpoint(rom, seeds)
    rom_map = RomMap(rom.size, disasm.instructions, disasm.subroutines,
                     disasm.labels).format()
    return rom_map, seeds


def scan(rom_map: bytes, rom: ROM, known: set[int]) -> list[int]:
    validator = Validator(rom, rom_map)
    results = []
    pos = _CODE_START
    end = len(rom_map) - 1
    while pos < end:
        if rom_map[pos] != ord('X') or pos in known or not rom.in_bounds(pos, 2):
            pos += 2
            continue
        w = rom.read_word(pos)
        # Cheap reject before the (memoised) full walk.
        if (w & 0xF000) in (0xA000, 0xF000) or w == 0x4AFC:
            pos += 2
            continue
        if not validator.terminates(pos):
            pos += 2
            continue
        # Valid function: record its first opcode, then skip past its RTS.
        results.append(pos)
        nxt = validator.run_end(pos)
        pos = nxt if nxt > pos else pos + 2
    return results


def write_output(results: list[int], out_path: Path) -> None:
    write_address_file(
        results,
        out_path,
        header="# speculative_addresses.txt — auto-generated by speculative_scan.py",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scan unmapped ROM for 68k function entry candidates")
    ap.add_argument('map_file', help="ROM coverage map (output/sor.map)")
    ap.add_argument('rom_file', help="ROM binary (rom/SOR.bin)")
    ap.add_argument('aux_file', help="Known aux addresses to skip (code-analysis/aux_addresses.txt)")
    ap.add_argument('--dry-run', action='store_true', help="Print count only, don't write output")
    ap.add_argument('--no-static-filter', action='store_true',
                    help="Scan the supplied map directly instead of first applying "
                         "the recompiler's static table-discovery fixpoint")
    ap.add_argument('-o', '--output', default='code-analysis/speculative_addresses.txt')
    args = ap.parse_args(argv)

    rom_map = Path(args.map_file).read_bytes()
    rom = ROM.from_file(args.rom_file)
    known = load_known(Path(args.aux_file))
    if not args.no_static_filter:
        rom_map, known = static_recompiler_map(rom, Path(args.aux_file))

    results = scan(rom_map, rom, known)
    print(f"Candidates: {len(results)} functions")

    if args.dry_run:
        return 0

    out = Path(args.output)
    write_output(results, out)
    print(f"Written → {out}")
    return 0
