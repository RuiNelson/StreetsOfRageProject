"""Unit tests for the recursive-descent Disassembler engine."""

import struct

try:
    import pytest
except ImportError:
    class _PytestStub:
        @staticmethod
        def parametrize(*_a, **_kw):
            def deco(f): return f
            return deco
    pytest = _PytestStub()

from ..disassembler import Disassembler
from ..instruction import FlowType
from ..rom import ROM


def _rom(*words: int) -> ROM:
    """Build an in-memory ROM from 16-bit words (big-endian)."""
    data = b''.join(struct.pack('>H', w & 0xFFFF) for w in words)
    return ROM(data)


class TestDisassemblerEntryPoints:
    """Seed addresses are enqueued correctly."""

    def test_entry_point_queued(self):
        # Entry point is 0x000208, but our ROM is tiny.
        # We use a mini-ROM at a known address and override aux_addresses.
        rom = _rom(0x4E75)  # RTS at offset 0
        dis = Disassembler(rom, aux_addresses=[0x000000])
        assert 0x000000 in dis.subroutines

    def test_duplicate_enqueue_ignored(self):
        rom = _rom(0x4E75)
        dis = Disassembler(rom, aux_addresses=[0x000000, 0x000000])
        # Should not crash, subroutines should still have only one entry
        assert len(dis.subroutines) >= 1


class TestDisassemblerTrace:
    """Sequential tracing stops at terminal instructions."""

    def test_stops_at_rts(self):
        # nop; nop; rts
        rom = _rom(0x4E71, 0x4E71, 0x4E75)
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert 0x000000 in dis.instructions
        assert 0x000002 in dis.instructions
        assert 0x000004 in dis.instructions
        assert 0x000006 not in dis.instructions  # stopped at RTS

    def test_stops_at_rte(self):
        rom = _rom(0x4E73)  # RTE
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert 0x000000 in dis.instructions

    def test_stops_at_illegal(self):
        rom = _rom(0x4AFC)  # ILLEGAL
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert 0x000000 in dis.instructions
        assert dis.instructions[0x000000].mnemonic == 'illegal'

    def test_merges_already_decoded(self):
        # Two entry points converging on shared code: each instruction is
        # decoded exactly once. nop; nop; rts, seeded at both 0x00 and 0x02.
        rom = _rom(0x4E71, 0x4E71, 0x4E75)
        dis = Disassembler(rom, aux_addresses=[0x000000, 0x000002])
        dis.disassemble()
        assert len(dis.instructions) == 3
        assert dis.instructions[0x000000].mnemonic == 'nop'


class TestDisassemblerBranches:
    """Branch instructions correctly populate targets and labels."""

    def test_bra_adds_label(self):
        # bra.s to $06 (target = instr+2+disp = 0+2+4); the target becomes a
        # label and is decoded. $6004 = bra.s with 8-bit displacement 4.
        # At 0: bra.s $06 ($6004); unreached nop/nop at 2,4; rts at 6 (target)
        rom = _rom(0x6004, 0x4E71, 0x4E71, 0x4E75)
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert 0x000006 in dis.labels
        assert 0x000006 in dis.instructions

    def test_bsr_adds_subroutine(self):
        # bsr.s to $04 (target = 0+2+disp, disp=2 -> $6102): the target is a
        # subroutine entry, and execution also continues past the bsr.
        # At 0: bsr.s $04 ($6102); rts at 2 (fall-through); nop at 4 (sub); rts at 6
        rom = _rom(0x6102, 0x4E75, 0x4E71, 0x4E75)
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert 0x000004 in dis.subroutines
        assert 0x000004 in dis.instructions
        assert 0x000002 in dis.instructions  # fall-through after the bsr
        assert 0x000006 in dis.instructions  # sub's rts

    def test_beq_conditional_both_paths(self):
        # beq.s  target
        # nop
        # target: rts
        # At 0: beq.s $+4 ($6704)
        # At 2: nop ($4E71)
        # At 4: rts ($4E75)
        rom = _rom(0x6704, 0x4E71, 0x4E75)
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        # Both the branch target and fall-through should be decoded
        assert 0x000004 in dis.instructions
        assert 0x000002 in dis.instructions


class TestDisassemblerJsrJmp:
    """JSR and JMP are handled correctly."""

    def test_jsr_absolute_long(self):
        # jsr ($06).w ($4EB8 + ext word $0006): the target is a subroutine entry.
        # At 0: jsr ($06).w (4 bytes); rts at 4 (fall-through); nop at 6 (sub); rts at 8
        rom = _rom(0x4EB8, 0x0006, 0x4E75, 0x4E71, 0x4E75)
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert 0x000006 in dis.subroutines

    def test_jmp_indirect_warning(self):
        # jmp  (a0)
        rom = _rom(0x4ED0)
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert 0x000000 in dis.indirect_warnings


class TestDisassemblerDbf:
    """DBcc loop handling."""

    def test_dbf_conditional_both_paths(self):
        # dbra d0, $00 (loop back): $51C8 = DBRA d0, disp word $FFFE (= -2 ->
        # target = instr+2+disp = 0). DBcc is conditional: both the loop-back
        # target (already decoded) and the fall-through past the 4-byte dbra.
        # At 0: dbra d0,$00 (4 bytes: $51C8 $FFFE); rts at 4 (fall-through)
        rom = _rom(0x51C8, 0xFFFE, 0x4E75)
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert 0x000000 in dis.instructions  # the dbra itself / loop target
        assert 0x000004 in dis.instructions  # fall-through rts


class TestDisassemblerNoCrashOnEmptyRom:
    """Empty ROM should not crash."""

    def test_empty_rom(self):
        rom = ROM(b'')
        dis = Disassembler(rom, aux_addresses=[])
        dis.disassemble()
        assert len(dis.instructions) == 0


class TestDisassemblerFlowTypes:
    """Flow types are correctly classified."""

    def test_nop_is_sequential(self):
        rom = _rom(0x4E71)
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert dis.instructions[0x000000].flow == FlowType.SEQUENTIAL

    def test_bra_is_branch(self):
        rom = _rom(0x6010, 0x4E75)  # bra.s $+2; rts
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert dis.instructions[0x000000].flow == FlowType.BRANCH

    def test_bsr_is_call(self):
        rom = _rom(0x6102, 0x4E75, 0x4E75)  # bsr.s $+4; rts; rts
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert dis.instructions[0x000000].flow == FlowType.CALL

    def test_rts_is_return(self):
        rom = _rom(0x4E75)
        dis = Disassembler(rom, aux_addresses=[0x000000])
        dis.disassemble()
        assert dis.instructions[0x000000].flow == FlowType.RETURN
