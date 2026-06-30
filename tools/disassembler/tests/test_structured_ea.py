"""Unit tests for the structured effective-address (EA) representation.

These verify the additive ``Instruction.eas`` field and the
``ea_from_operand`` converter introduced for the C++ recompiler.  They follow
the style of ``test_decoder.py``: tiny synthetic big-endian ROMs decoded with a
fresh decoder, asserting structured-EA fields (mode, register, displacement,
index register/size, immediate, resolved absolute address).

The legacy ``Instruction.operands`` (strings / :class:`Addr`) is unchanged and
covered by ``test_decoder.py``; here we only assert the parallel ``eas`` list.

To run::

    python3 -m pytest tools/disassembler/tests/ -v
"""

import struct

try:
    import pytest  # noqa: F401
except ImportError:
    class _PytestStub:
        @staticmethod
        def raises(*_a, **_kw):
            class _ctx:
                def __enter__(s): return s
                def __exit__(s, *a): return False
            return _ctx()
    pytest = _PytestStub()

from ..decoder import InstructionDecoder
from ..instruction import EA, EAMode, ea_from_operand
from ..rom import ROM


def _make_rom(*words: int) -> ROM:
    """Pack words big-endian, padding with zero words so extension-word
    reads never run off the end of the synthetic buffer."""
    data = b''.join(struct.pack('>H', w & 0xFFFF) for w in words)
    return ROM(data + b'\x00' * 16)


def _decode(*words: int):
    return InstructionDecoder(_make_rom(*words)).decode(0)


# ---------------------------------------------------------------------------
# Parallelism: eas mirrors operands one-for-one
# ---------------------------------------------------------------------------

class TestEasParallel:
    def test_eas_length_matches_operands(self):
        i = _decode(0x2200)            # move.l d0,d1
        assert len(i.eas) == len(i.operands) == 2

    def test_operandless_has_empty_eas(self):
        i = _decode(0x4E71)            # nop
        assert i.eas == []

    def test_eas_are_EA_instances(self):
        i = _decode(0x2200)
        assert all(isinstance(e, EA) for e in i.eas)


# ---------------------------------------------------------------------------
# Register-direct modes
# ---------------------------------------------------------------------------

class TestRegisterDirect:
    def test_data_register(self):
        i = _decode(0x2200)            # move.l d0,d1
        assert i.eas[0].mode == EAMode.DATA_REG
        assert i.eas[0].reg == 0
        assert i.eas[1].mode == EAMode.DATA_REG
        assert i.eas[1].reg == 1

    def test_size_stamped_on_register(self):
        i = _decode(0x2200)            # move.l → both EAs get size 'l'
        assert i.eas[0].size == 'l'
        assert i.eas[1].size == 'l'

    def test_address_register(self):
        # lea $4(a0),a1 — destination is An
        i = _decode(0x43E8, 0x0004)
        assert i.eas[1].mode == EAMode.ADDR_REG
        assert i.eas[1].reg == 1

    def test_sp_is_register_seven(self):
        assert ea_from_operand('sp').mode == EAMode.ADDR_REG
        assert ea_from_operand('sp').reg == 7


# ---------------------------------------------------------------------------
# Indirect / increment / decrement
# ---------------------------------------------------------------------------

class TestIndirectModes:
    def test_address_indirect(self):
        # move.w d0,(a1)
        i = _decode(0x3280)
        assert i.eas[1].mode == EAMode.ADDR_IND
        assert i.eas[1].reg == 1

    def test_postincrement(self):
        # move.l (a0)+,d0
        i = _decode(0x2018)
        assert i.eas[0].mode == EAMode.ADDR_POSTINC
        assert i.eas[0].reg == 0

    def test_predecrement(self):
        # move.l a0,-(a1)
        i = _decode(0x2308)
        assert i.eas[1].mode == EAMode.ADDR_PREDEC
        assert i.eas[1].reg == 1

    def test_predecrement_sp(self):
        assert ea_from_operand('-(sp)').mode == EAMode.ADDR_PREDEC
        assert ea_from_operand('-(sp)').reg == 7


# ---------------------------------------------------------------------------
# Displacement and indexed
# ---------------------------------------------------------------------------

class TestDisplacementIndexed:
    def test_disp(self):
        # lea $4(a0),a1
        i = _decode(0x43E8, 0x0004)
        ea = i.eas[0]
        assert ea.mode == EAMode.ADDR_DISP
        assert ea.reg == 0
        assert ea.disp == 4

    def test_disp_negative(self):
        # move.w -$4(a0),d0
        i = _decode(0x3028, 0xFFFC)
        ea = i.eas[0]
        assert ea.mode == EAMode.ADDR_DISP
        assert ea.disp == -4

    def test_indexed_data_word(self):
        # move.b $10(a0,d0.w),d1
        i = _decode(0x1230, 0x0010)
        ea = i.eas[0]
        assert ea.mode == EAMode.ADDR_INDEX
        assert ea.reg == 0
        assert ea.disp == 0x10
        assert ea.index_reg == 0
        assert ea.index_is_addr is False
        assert ea.index_size == 'w'

    def test_indexed_addr_long(self):
        # move.b $8(a0,a5.l),d1
        i = _decode(0x1230, 0xD808)
        ea = i.eas[0]
        assert ea.mode == EAMode.ADDR_INDEX
        assert ea.index_reg == 5
        assert ea.index_is_addr is True
        assert ea.index_size == 'l'


# ---------------------------------------------------------------------------
# Absolute and PC-relative — resolved absolute address carried
# ---------------------------------------------------------------------------

class TestAbsoluteAndPC:
    def test_absolute_long(self):
        # move.l $00001234.l,d0
        i = _decode(0x2039, 0x0000, 0x1234)
        ea = i.eas[0]
        assert ea.mode == EAMode.ABS_L
        assert ea.abs_value == 0x1234
        assert ea.size == 'l'

    def test_absolute_short(self):
        # move.w ($1000).w,d0
        i = _decode(0x3038, 0x1000)
        ea = i.eas[0]
        assert ea.mode == EAMode.ABS_W
        assert ea.abs_value == 0x1000
        assert ea.size == 'w'

    def test_pc_displacement_resolved(self):
        # jmp *+$80 (PC at ext word = 0x02, +0x80 = 0x82)
        i = _decode(0x4EFA, 0x0080)
        ea = i.eas[0]
        assert ea.mode == EAMode.PC_DISP
        assert ea.abs_value == 0x82

    def test_pc_indexed_resolved(self):
        # jmp $xx(pc,d0.w) — PC 0x02 + d8(0x10) = 0x12, index d0.w
        i = _decode(0x4EFB, 0x0010)
        ea = i.eas[0]
        assert ea.mode == EAMode.PC_INDEX
        assert ea.abs_value == 0x12
        assert ea.index_reg == 0
        assert ea.index_is_addr is False
        assert ea.index_size == 'w'


# ---------------------------------------------------------------------------
# Branch targets — resolved absolute, like Addr
# ---------------------------------------------------------------------------

class TestBranchTargets:
    def test_bra_short_target(self):
        # bra.s $12
        i = _decode(0x6010)
        ea = i.eas[0]
        assert ea.mode == EAMode.BRANCH_TARGET
        assert ea.abs_value == 0x12

    def test_bsr_word_target(self):
        # bsr.w *+8 → PC at ext word (0x02) + 0x08 = 0x0A
        i = _decode(0x6100, 0x0008)
        ea = i.eas[0]
        assert ea.mode == EAMode.BRANCH_TARGET
        assert ea.abs_value == 0x0A

    def test_dbf_target(self):
        # dbf d1,* with disp -0x12
        i = _decode(0x51C9, 0xFFEE)
        # operands: [d1, Addr(branch)]
        assert i.eas[0].mode == EAMode.DATA_REG
        assert i.eas[0].reg == 1
        assert i.eas[1].mode == EAMode.BRANCH_TARGET


# ---------------------------------------------------------------------------
# Immediate
# ---------------------------------------------------------------------------

class TestImmediate:
    def test_moveq_immediate(self):
        # moveq #$12,d0
        i = _decode(0x7012)
        assert i.eas[0].mode == EAMode.IMMEDIATE
        assert i.eas[0].imm == 0x12

    def test_immediate_long(self):
        # andi.l #$DEADBEEF,d0
        i = _decode(0x0280, 0xDEAD, 0xBEEF)
        assert i.eas[0].mode == EAMode.IMMEDIATE
        assert i.eas[0].imm == 0xDEADBEEF

    def test_moveq_negative_immediate(self):
        # moveq #-1,d0 → operand string '-$1'
        i = _decode(0x70FF)
        assert i.eas[0].mode == EAMode.IMMEDIATE
        assert i.eas[0].imm == -1


# ---------------------------------------------------------------------------
# Register lists (movem) and special registers
# ---------------------------------------------------------------------------

class TestSpecialOperands:
    def test_movem_reglist(self):
        # movem.l (a2)+,d0-sp  (mode=3 postinc, reg=2)
        i = _decode(0x4CDA, 0xFFFF)
        # operands: [(a2)+, 'd0-sp']
        assert i.eas[0].mode == EAMode.ADDR_POSTINC
        assert i.eas[0].reg == 2
        assert i.eas[1].mode == EAMode.REG_LIST
        assert i.eas[1].reglist == 'd0-sp'

    def test_move_to_sr(self):
        # move d0,sr
        i = _decode(0x46C0)
        assert i.eas[0].mode == EAMode.DATA_REG
        assert i.eas[1].mode == EAMode.SPECIAL_REG
        assert i.eas[1].special == 'sr'

    def test_move_from_sr(self):
        # move sr,d0
        i = _decode(0x40C0)
        assert i.eas[0].mode == EAMode.SPECIAL_REG
        assert i.eas[0].special == 'sr'

    def test_move_usp(self):
        # move usp,a0
        i = _decode(0x4E68)   # move a0,usp
        assert any(e.mode == EAMode.SPECIAL_REG and e.special == 'usp'
                   for e in i.eas)


# ---------------------------------------------------------------------------
# Converter unit tests (direct, independent of the decoder)
# ---------------------------------------------------------------------------

class TestConverterDirect:
    def test_raw_fallback(self):
        ea = ea_from_operand('something(weird)')
        assert ea.mode == EAMode.RAW
        assert ea.raw == 'something(weird)'

    def test_ccr(self):
        assert ea_from_operand('ccr').special == 'ccr'

    def test_data_reg_seven(self):
        ea = ea_from_operand('d7')
        assert ea.mode == EAMode.DATA_REG
        assert ea.reg == 7

    def test_helpers(self):
        assert ea_from_operand('(a3)').mode == EAMode.ADDR_IND
        assert ea_from_operand('(a3)').reg == 3
        assert ea_from_operand('$11(a3)').mode == EAMode.ADDR_DISP
        assert ea_from_operand('$11(a3)').disp == 0x11
        assert ea_from_operand('#$ff').mode == EAMode.IMMEDIATE
        assert ea_from_operand('#$ff').imm == 0xFF


# ---------------------------------------------------------------------------
# EA convenience predicates
# ---------------------------------------------------------------------------

class TestEAPredicates:
    def test_is_register_direct(self):
        assert ea_from_operand('d0').is_register_direct
        assert ea_from_operand('a0').is_register_direct
        assert not ea_from_operand('(a0)').is_register_direct

    def test_is_memory(self):
        assert ea_from_operand('(a0)').is_memory
        assert ea_from_operand('(a0)+').is_memory
        assert not ea_from_operand('d0').is_memory
