"""Unit tests for the 68000 decoder.

These tests use tiny synthetic ROMs (created in-memory) to verify that
each instruction group decodes correctly with the expected FlowType,
operands, and targets.

The synthetic ROM format uses Python struct packing (big-endian, '>H').

To run::

    python3 -m pytest tools/disassembler/tests/ -v

Note: All opcodes are verified against the Exodus emulator opcode definitions.
"""

import struct

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:
    _HAS_PYTEST = False
    # Stub pytest decorators so test file remains importable without pytest
    class _mark:
        @staticmethod
        def parametrize(*_a, **_kw):
            def deco(f): return f
            return deco
    class _PytestStub:
        mark = _mark()
        @staticmethod
        def raises(*_a, **_kw):
            class _ctx:
                def __enter__(s): return s
                def __exit__(s, *a): return False
            return _ctx()
    pytest = _PytestStub()

from ..decoder import DecodeError, InstructionDecoder
from ..instruction import Addr, FlowType
from ..rom import ROM


def _make_rom(*words: int) -> ROM:
    """Pack a sequence of 16-bit words into a big-endian ROM buffer.

    A few trailing zero words are appended so decoding an instruction whose
    extension words the test did not spell out (immediates, displacements)
    reads valid 0x0000 fillers instead of running off the buffer end. The
    padding never changes how the leading instruction decodes.
    """
    data = b''.join(struct.pack('>H', w & 0xFFFF) for w in words)
    data += b'\x00' * 16  # 8 padding words for unspecified extension reads
    return ROM(data)


def _decode(rom: ROM, addr: int = 0) -> 'Instruction':
    """Decode at *addr* (default 0) using a fresh decoder."""
    return InstructionDecoder(rom).decode(addr)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_rom_read_word(self):
        rom = _make_rom(0x1234, 0x5678)
        assert rom.read_word(0) == 0x1234
        assert rom.read_word(2) == 0x5678

    def test_rom_read_word_signed(self):
        rom = _make_rom(0xFF80)   # signed -128
        assert rom.read_word_signed(0) == -128

    def test_rom_out_of_bounds(self):
        rom = ROM(struct.pack('>H', 0x1234))  # exactly one word, no padding
        with pytest.raises(Exception):
            rom.read_word(2)


# ---------------------------------------------------------------------------
# Control flow — RTS / RTE / RTR / ILLEGAL
# ---------------------------------------------------------------------------

class TestControlReturn:
    def test_rts(self):
        instr = _decode(_make_rom(0x4E75))
        assert instr.mnemonic == 'rts'
        assert instr.flow == FlowType.RETURN
        assert instr.byte_length == 2

    def test_rte(self):
        instr = _decode(_make_rom(0x4E73))
        assert instr.mnemonic == 'rte'
        assert instr.flow == FlowType.RETURN

    def test_rtr(self):
        instr = _decode(_make_rom(0x4E77))
        assert instr.mnemonic == 'rtr'
        assert instr.flow == FlowType.RETURN

    def test_illegal(self):
        # ILLEGAL ($4AFC) — fixed opcode, single word
        # Verifies fix: was previously emitted as dc.w, now correctly
        # decoded as 'illegal' with FlowType.RETURN for RomMap 's' marking.
        instr = _decode(_make_rom(0x4AFC))
        assert instr.mnemonic == 'illegal'
        assert instr.flow == FlowType.RETURN
        assert instr.byte_length == 2


# ---------------------------------------------------------------------------
# Branches — BRA / BSR / Bcc / DBcc
# ---------------------------------------------------------------------------

class TestBranches:
    def test_bra_short(self):
        # BRA.s  $12  (PC=0x02 + 0x10 = 0x12)
        instr = _decode(_make_rom(0x6010))
        assert instr.mnemonic == 'bra'
        assert instr.size == 's'
        assert instr.flow == FlowType.BRANCH
        assert instr.targets == [0x12]

    def test_bra_word(self):
        # BRA.w  $+6  (PC=0x02 + 0x0006 = 0x08)
        instr = _decode(_make_rom(0x6000, 0x0006))
        assert instr.mnemonic == 'bra'
        assert instr.size == 'w'
        assert instr.targets == [0x08]

    def test_bsr_short(self):
        instr = _decode(_make_rom(0x6102))
        assert instr.mnemonic == 'bsr'
        assert instr.size == 's'
        assert instr.flow == FlowType.CALL

    def test_bsr_word(self):
        instr = _decode(_make_rom(0x6100, 0x0008))
        assert instr.mnemonic == 'bsr'
        assert instr.size == 'w'
        assert instr.targets == [0x0A]

    @pytest.mark.parametrize('cc,i', [
        ('t', 0), ('f', 1), ('hi', 2), ('ls', 3),
        ('cc', 4), ('cs', 5), ('ne', 6), ('eq', 7),
        ('vc', 8), ('vs', 9), ('pl', 10), ('mi', 11),
        ('ge', 12), ('lt', 13), ('gt', 14), ('le', 15),
    ])
    def test_bcc_all_conditions(self, cc: str, i: int):
        instr = _decode(_make_rom(0x6000 | (i << 8)))
        # cc 0/1 encode BRA / BSR (not "bt"/"bf"); the rest are Bcc.
        expected = {'t': 'bra', 'f': 'bsr'}.get(cc, f'b{cc}')
        assert instr.mnemonic == expected

    def test_dbt(self):
        # DBT  $xxxx (never used in practice)
        instr = _decode(_make_rom(0x50C8, 0x0000))
        assert instr.mnemonic == 'dbt'
        assert instr.flow == FlowType.CONDITIONAL

    def test_dbf(self):
        # DBF  d1,*  ($51C9 = dbf.w d1,*)
        instr = _decode(_make_rom(0x51C9, 0xFFEE))
        assert instr.mnemonic == 'dbf'
        assert instr.flow == FlowType.CONDITIONAL


# ---------------------------------------------------------------------------
# JSR / JMP
# ---------------------------------------------------------------------------

class TestJsrJmp:
    def test_jsr_abs_long(self):
        # 0x4EB9 = JSR <xxx>.L  (mode=7,reg=1 = absolute long)
        instr = _decode(_make_rom(0x4EB9, 0x0000, 0x1234))
        assert instr.mnemonic == 'jsr'
        assert instr.flow == FlowType.CALL
        assert instr.targets == [0x1234]

    def test_jsr_abs_word(self):
        # 0x4EB8 = JSR d16(An)  (mode=7,reg=0 = d16(An) — weird but valid)
        instr = _decode(_make_rom(0x4EB8, 0x1234))
        assert instr.mnemonic == 'jsr'
        assert instr.flow == FlowType.CALL

    def test_jmp_abs_long(self):
        instr = _decode(_make_rom(0x4EF9, 0x0000, 0x5678))
        assert instr.mnemonic == 'jmp'
        assert instr.flow == FlowType.BRANCH

    def test_jmp_pc_rel(self):
        # JMP *+$82  (PC at ext word 0x02 + 0x80 = 0x82)
        instr = _decode(_make_rom(0x4EFA, 0x0080))
        assert instr.mnemonic == 'jmp'
        assert instr.flow == FlowType.BRANCH

    def test_jmp_indirect(self):
        # JMP  (a0) — cannot resolve target statically
        instr = _decode(_make_rom(0x4ED0))
        assert instr.mnemonic == 'jmp'
        assert instr.indirect is True
        assert instr.targets == []

    def test_jsr_indirect(self):
        # JSR  (a0)  — $4E90 (mode 010, reg 000)
        instr = _decode(_make_rom(0x4E90))
        assert instr.mnemonic == 'jsr'
        assert instr.indirect is True


# ---------------------------------------------------------------------------
# Privileged / misc control — RESET / NOP / STOP / TRAP / TRAPV
# ---------------------------------------------------------------------------

class TestPrivileged:
    def test_nop(self):
        instr = _decode(_make_rom(0x4E71))
        assert instr.mnemonic == 'nop'
        assert instr.flow == FlowType.SEQUENTIAL

    def test_reset(self):
        instr = _decode(_make_rom(0x4E70))
        assert instr.mnemonic == 'reset'

    def test_stop(self):
        instr = _decode(_make_rom(0x4E72, 0x2700))
        assert instr.mnemonic == 'stop'

    def test_trap(self):
        # TRAP #9
        instr = _decode(_make_rom(0x4E49))
        assert instr.mnemonic == 'trap'
        assert instr.operands == ['#$9']

    def test_trapv(self):
        instr = _decode(_make_rom(0x4E76))
        assert instr.mnemonic == 'trapv'


# ---------------------------------------------------------------------------
# MOVE variants
# ---------------------------------------------------------------------------

class TestMove:
    def test_move_b(self):
        # move.b d7,(a0)  — from valid.asm
        instr = _decode(_make_rom(0x1C38))
        assert instr.mnemonic == 'move'
        assert instr.size == 'b'

    def test_move_w(self):
        # move.w d7,(a0)  — from valid.asm
        instr = _decode(_make_rom(0x3C38))
        assert instr.mnemonic == 'move'
        assert instr.size == 'w'

    def test_move_l(self):
        # move.l a0,(a1)+  — from valid.asm
        instr = _decode(_make_rom(0x23C8))
        assert instr.mnemonic == 'move'
        assert instr.size == 'l'

    def test_movea_w(self):
        # movea.w d1,a0  — from valid.asm
        instr = _decode(_make_rom(0x3041))
        assert instr.mnemonic == 'movea'
        assert instr.size == 'w'

    def test_movea_l(self):
        # movea.l d0,a0  — from valid.asm
        instr = _decode(_make_rom(0x2040))
        assert instr.mnemonic == 'movea'
        assert instr.size == 'l'

    def test_moveq(self):
        # moveq  #$12,d0
        instr = _decode(_make_rom(0x7012))
        assert instr.mnemonic == 'moveq'


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------

class TestArithmetic:
    def test_add_ea_to_dn(self):
        # add.w d0,d1  — from valid.asm
        instr = _decode(_make_rom(0xD241))
        assert instr.mnemonic == 'add'
        assert instr.size == 'w'

    def test_adda(self):
        # adda.w d0,d1  (destination mode=1 = address register)
        instr = _decode(_make_rom(0xD1C1))
        assert instr.mnemonic == 'adda'

    def test_addq_byte(self):
        # addq.b  #3,d0
        instr = _decode(_make_rom(0x5038))
        assert instr.mnemonic == 'addq'
        assert instr.size == 'b'

    def test_addq_word_to_address(self):
        # addq.w  #1,a0
        instr = _decode(_make_rom(0x5041))
        assert instr.mnemonic == 'addq'

    def test_subq_long(self):
        instr = _decode(_make_rom(0x5982))
        assert instr.mnemonic == 'subq'
        assert instr.size == 'l'

    def test_mulu(self):
        # mulu.w d0,d1  — from valid.asm
        instr = _decode(_make_rom(0xC0C1))
        assert instr.mnemonic == 'mulu'

    def test_muls(self):
        instr = _decode(_make_rom(0xC1C1))
        assert instr.mnemonic == 'muls'

    def test_divu(self):
        # divu.w d0,d1  — from valid.asm
        instr = _decode(_make_rom(0x80C1))
        assert instr.mnemonic == 'divu'

    def test_divs(self):
        instr = _decode(_make_rom(0x81C1))
        assert instr.mnemonic == 'divs'

    def test_cmp(self):
        # cmp.b d0,d1  — from valid.asm
        instr = _decode(_make_rom(0xB401))
        assert instr.mnemonic == 'cmp'

    def test_cmpa(self):
        # cmpa.w a1,a0  — from valid.asm
        instr = _decode(_make_rom(0xB0C1))
        assert instr.mnemonic == 'cmpa'

    def test_cmpm(self):
        # cmpm.b (a0)+,(a1)+  — from valid.asm
        instr = _decode(_make_rom(0xB108))
        assert instr.mnemonic == 'cmpm'

    def test_cmpi_byte(self):
        # cmpi.b  #$42,d0
        instr = _decode(_make_rom(0x0C00, 0x0042))
        assert instr.mnemonic == 'cmpi'
        assert instr.size == 'b'

    def test_cmp_register(self):
        # cmp.w d0,d1
        instr = _decode(_make_rom(0xB241))
        assert instr.mnemonic == 'cmp'


# ---------------------------------------------------------------------------
# Logic / bit ops
# ---------------------------------------------------------------------------

class TestLogic:
    def test_and(self):
        # and.b d5,(a2)  — from valid.asm
        instr = _decode(_make_rom(0xC2AA))
        assert instr.mnemonic == 'and'

    def test_and_byte_reg_to_displacement_not_abcd(self):
        # and.b d7,$58(a0) -- $CF28 is ABCD only for mode 000/001.
        instr = _decode(_make_rom(0xCF28, 0x0058))
        assert instr.mnemonic == 'and'
        assert instr.size == 'b'
        assert instr.operands == ['d7', '$58(a0)']

    def test_or(self):
        # or.b d2,d5
        instr = _decode(_make_rom(0x80AA))
        assert instr.mnemonic == 'or'

    def test_eor(self):
        # eor.b d0,d1  — from valid.asm
        instr = _decode(_make_rom(0xB140))
        assert instr.mnemonic == 'eor'

    def test_not(self):
        # not.w d0
        instr = _decode(_make_rom(0x4640))
        assert instr.mnemonic == 'not'
        assert instr.size == 'w'

    def test_tst_byte(self):
        # tst.b d0
        instr = _decode(_make_rom(0x4A00))
        assert instr.mnemonic == 'tst'
        assert instr.size == 'b'

    def test_tst_long(self):
        # tst.l (a0)
        instr = _decode(_make_rom(0x4A98))
        assert instr.mnemonic == 'tst'
        assert instr.size == 'l'

    def test_btst_static(self):
        # btst  #0,d0  — from valid.asm
        instr = _decode(_make_rom(0x0800, 0x0000))
        assert instr.mnemonic == 'btst'

    def test_btst_dynamic(self):
        # btst.l  d2,d5  — from valid.asm
        instr = _decode(_make_rom(0x0905))
        assert instr.mnemonic == 'btst'

    def test_bchg_dynamic(self):
        # bchg  d0,d1  — from valid.asm
        instr = _decode(_make_rom(0x0141))
        assert instr.mnemonic == 'bchg'

    def test_bclr_static(self):
        # bclr  #3,(a0)  — from valid.asm
        instr = _decode(_make_rom(0x0888, 0x0003))
        assert instr.mnemonic == 'bclr'

    def test_bset_dynamic(self):
        # bset  d0,(a0)  — from valid.asm
        instr = _decode(_make_rom(0x01D0))
        assert instr.mnemonic == 'bset'

    def test_tas(self):
        # tas.b  (a0)  — from valid.asm
        instr = _decode(_make_rom(0x4AC8))
        assert instr.mnemonic == 'tas'


# ---------------------------------------------------------------------------
# Data movement misc
# ---------------------------------------------------------------------------

class TestMoveMisc:
    def test_lea(self):
        # lea.l  (a0),a1  — from valid.asm
        instr = _decode(_make_rom(0x41D0))
        assert instr.mnemonic == 'lea'

    def test_pea(self):
        # pea.l  (a0)  — from valid.asm
        instr = _decode(_make_rom(0x4850))
        assert instr.mnemonic == 'pea'

    def test_link(self):
        # link.w  a0,#-4  — from valid.asm
        instr = _decode(_make_rom(0x4E50, 0xFFFC))
        assert instr.mnemonic == 'link'

    def test_unlk(self):
        # unlk  a0  — from valid.asm
        instr = _decode(_make_rom(0x4E58))
        assert instr.mnemonic == 'unlk'

    def test_movem_reg_to_mem(self):
        # movem.w  d5-a7,(a2)  — from valid.asm
        instr = _decode(_make_rom(0x4889, 0xC140))
        assert instr.mnemonic == 'movem'
        assert instr.size == 'w'

    def test_movem_mem_to_reg(self):
        # movem.l  (a2)+,d5-a7  — $4CDA (mem→reg, long, postinc a2)
        instr = _decode(_make_rom(0x4CDA, 0xFFFF))
        assert instr.mnemonic == 'movem'
        assert instr.size == 'l'

    def test_swap(self):
        # swap.w  d0  — from valid.asm
        instr = _decode(_make_rom(0x4840))
        assert instr.mnemonic == 'swap'

    def test_ext_word(self):
        # ext.w  d0  — from valid.asm
        instr = _decode(_make_rom(0x4880))
        assert instr.mnemonic == 'ext'
        assert instr.size == 'w'

    def test_ext_long(self):
        # ext.l  d0  — from valid.asm
        instr = _decode(_make_rom(0x48C0))
        assert instr.mnemonic == 'ext'
        assert instr.size == 'l'

    def test_exg_dn_dn(self):
        # exg  d0,d1  — from valid.asm
        instr = _decode(_make_rom(0xC141))
        assert instr.mnemonic == 'exg'

    def test_exg_an_an(self):
        # exg  a0,a1  — from valid.asm
        instr = _decode(_make_rom(0xC148))
        assert instr.mnemonic == 'exg'

    def test_movep_w(self):
        # movep.w  $7FFF(a2),d5  — from valid.asm
        instr = _decode(_make_rom(0x030A, 0x7FFF))
        assert instr.mnemonic == 'movep'
        assert instr.size == 'w'

    def test_movep_l(self):
        # movep.l  $7FFF(a2),d5  — from valid.asm
        instr = _decode(_make_rom(0x034A, 0x7FFF))
        assert instr.mnemonic == 'movep'
        assert instr.size == 'l'

    def test_chk(self):
        # chk.w  d0,d1  — from valid.asm
        instr = _decode(_make_rom(0x4181))
        assert instr.mnemonic == 'chk'

    def test_bkpt(self):
        # bkpt  #3  — from valid.asm
        instr = _decode(_make_rom(0x484B))
        assert instr.mnemonic == 'bkpt'
        assert instr.byte_length == 2


# ---------------------------------------------------------------------------
# Scc
# ---------------------------------------------------------------------------

class TestScc:
    def test_st(self):
        # st  d0  — from valid.asm
        instr = _decode(_make_rom(0x50C0))
        assert instr.mnemonic == 'st'

    def test_sf(self):
        # sf  d0  — from valid.asm
        instr = _decode(_make_rom(0x51C0))
        assert instr.mnemonic == 'sf'

    def test_sne(self):
        # sne  d0  — from valid.asm
        instr = _decode(_make_rom(0x56C0))
        assert instr.mnemonic == 'sne'

    def test_sge(self):
        # sge  d0
        instr = _decode(_make_rom(0x5CC0))
        assert instr.mnemonic == 'sge'


# ---------------------------------------------------------------------------
# ABCD / SBCD
# ---------------------------------------------------------------------------

class TestPackedDecimal:
    def test_abcd(self):
        # abcd  d0,d1  — from valid.asm
        instr = _decode(_make_rom(0xC100))
        assert instr.mnemonic == 'abcd'

    def test_sbcd_predec(self):
        # sbcd  -(a0),-(a1)  — from valid.asm
        instr = _decode(_make_rom(0x8109))
        assert instr.mnemonic == 'sbcd'

    def test_nbcd(self):
        # nbcd.b  d0  — from valid.asm
        instr = _decode(_make_rom(0x4800))
        assert instr.mnemonic == 'nbcd'


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------

class TestShifts:
    def test_asr_register_immediate(self):
        # asr.w  #4,d0  — from valid.asm
        instr = _decode(_make_rom(0xE840))
        assert instr.mnemonic == 'asr'

    def test_asr_register_by_zero_means_eight(self):
        # asr.w  #0,d0 means count=8
        instr = _decode(_make_rom(0xE240))
        assert instr.mnemonic == 'asr'

    def test_lsl_register(self):
        # lsl.l  d2,d0  — from valid.asm
        instr = _decode(_make_rom(0xE349))
        assert instr.mnemonic == 'lsl'

    def test_lsr_memory(self):
        # lsr.w  (a0)  — from valid.asm
        instr = _decode(_make_rom(0xE2D0))
        assert instr.mnemonic == 'lsr'
        assert instr.size == 'w'

    def test_rol_memory(self):
        # rol.w  (a0)  — from valid.asm
        instr = _decode(_make_rom(0xE7D0))
        assert instr.mnemonic == 'rol'

    def test_roxr_register(self):
        # roxr.l  #1,d0  — from valid.asm
        instr = _decode(_make_rom(0xE290))
        assert instr.mnemonic == 'roxr'


# ---------------------------------------------------------------------------
# Memory / register operations
# ---------------------------------------------------------------------------

class TestMemoryOps:
    def test_clr_byte(self):
        # clr.b  d5  — from valid.asm
        instr = _decode(_make_rom(0x4201))
        assert instr.mnemonic == 'clr'

    def test_neg_word(self):
        # neg.w  d0
        instr = _decode(_make_rom(0x4440))
        assert instr.mnemonic == 'neg'

    def test_negx_long(self):
        # negx.l  d0
        instr = _decode(_make_rom(0x4080))
        assert instr.mnemonic == 'negx'

    def test_move_to_sr(self):
        # move  d0,sr  — from valid.asm
        instr = _decode(_make_rom(0x46C0))
        assert instr.mnemonic == 'move'

    def test_move_from_sr(self):
        # move  sr,d0  — from valid.asm
        instr = _decode(_make_rom(0x40C0))
        assert instr.mnemonic == 'move'

    def test_move_to_ccr(self):
        # move  d0,ccr  — from valid.asm
        instr = _decode(_make_rom(0x44C0))
        assert instr.mnemonic == 'move'

    def test_move_usp(self):
        # move  usp,a0  — from valid.asm
        instr = _decode(_make_rom(0x4E60))
        assert instr.mnemonic == 'move'

    def test_move_usp_to(self):
        # move  a0,usp  — from valid.asm
        instr = _decode(_make_rom(0x4E68))
        assert instr.mnemonic == 'move'


# ---------------------------------------------------------------------------
# Line-A / Line-F — unimplemented, emitted as dc.w
# ---------------------------------------------------------------------------

class TestLineAF:
    def test_line_a(self):
        instr = _decode(_make_rom(0xA000))
        assert instr.mnemonic == 'dc'
        assert instr.size == 'w'
        assert instr.flow == FlowType.SEQUENTIAL

    def test_line_f(self):
        instr = _decode(_make_rom(0xF000))
        assert instr.mnemonic == 'dc'
        assert instr.size == 'w'


# ---------------------------------------------------------------------------
# Effective addresses
# ---------------------------------------------------------------------------

class TestEffectiveAddresses:
    def test_ea_immediate_byte(self):
        # ori.b  #$FF,d0
        instr = _decode(_make_rom(0x003C, 0x00FF))
        assert '#$ff' in instr.operands[0]

    def test_ea_immediate_long(self):
        # andi.l  #$DEADBEEF,d0
        instr = _decode(_make_rom(0x0280, 0xDEAD, 0xBEEF))
        assert instr.mnemonic == 'andi'
        assert instr.size == 'l'

    def test_ea_absolute_long(self):
        # move.l  $12345678.l,d0
        instr = _decode(_make_rom(0x2039, 0x1234, 0x5678))
        assert instr.mnemonic == 'move'
        addr_op = instr.operands[0]
        assert isinstance(addr_op, Addr)
        assert addr_op.form == 'abs_l'
        assert addr_op.value == 0x12345678

    def test_ea_pc_rel(self):
        # move.w  *(pc),d0
        instr = _decode(_make_rom(0x303A, 0x0000))
        assert instr.operands[0].form == 'pc_rel'

    def test_ea_d8_an_xn(self):
        # move.b  $10(a0,d0.w),d1  — $1230 + brief ext $0010 (d0.w, disp 8)
        instr = _decode(_make_rom(0x1230, 0x0010))
        assert instr.mnemonic == 'move'
        assert 'd0.w' in instr.operands[0]


# ---------------------------------------------------------------------------
# Byte lengths
# ---------------------------------------------------------------------------

class TestByteLengths:
    def test_single_word(self):
        assert _decode(_make_rom(0x4E71)).byte_length == 2

    def test_two_words(self):
        assert _decode(_make_rom(0x6000, 0x0002)).byte_length == 4

    def test_three_words(self):
        assert _decode(_make_rom(0x4EB9, 0x0000, 0x1234)).byte_length == 6

    def test_four_words(self):
        assert _decode(_make_rom(0x4C89, 0xFFFF)).byte_length == 4

    def test_movep_long(self):
        assert _decode(_make_rom(0x034A, 0x7FFF)).byte_length == 4


# ---------------------------------------------------------------------------
# Next address
# ---------------------------------------------------------------------------

class TestNextAddress:
    def test_short_branch(self):
        instr = _decode(_make_rom(0x6010))
        assert instr.next_address == 0x02

    def test_word_branch(self):
        instr = _decode(_make_rom(0x6000, 0x0002))
        assert instr.next_address == 0x04


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:
    def test_odd_address(self):
        with pytest.raises(DecodeError):
            InstructionDecoder(_make_rom(0x4E71)).decode(1)

    def test_out_of_bounds(self):
        with pytest.raises(Exception):
            InstructionDecoder(_make_rom(0x4E71)).decode(0x10000)
