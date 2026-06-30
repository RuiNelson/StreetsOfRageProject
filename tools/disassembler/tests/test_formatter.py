"""Unit tests for the AsmFormatter."""

try:
    import pytest
except ImportError:
    class _PytestStub:
        @staticmethod
        def parametrize(*_a, **_kw):
            def deco(f): return f
            return deco
    pytest = _PytestStub()

from ..instruction import Addr, FlowType, Instruction
from ..formatter import AsmFormatter


def _instr(address: int, mnemonic: str,
           size: str | None = None,
           operands: list | None = None,
           flow: FlowType = FlowType.SEQUENTIAL,
           targets: list | None = None,
           byte_length: int = 2) -> Instruction:
    """Create a minimal Instruction for testing."""
    return Instruction(
        address=address,
        mnemonic=mnemonic,
        size=size,
        operands=operands or [],
        byte_length=byte_length,
        flow=flow,
        targets=targets or [],
    )


class TestAsmFormatterBasic:
    """Basic label and instruction output."""

    def test_nop_no_label(self):
        instrs = {0x100: _instr(0x100, 'nop')}
        fmt = AsmFormatter(instrs, subroutines=set(), labels=set())
        lines = fmt.format().splitlines()
        assert any('nop' in l for l in lines)

    def test_subroutine_label(self):
        instrs = {0x100: _instr(0x100, 'nop')}
        fmt = AsmFormatter(instrs, subroutines={0x100}, labels=set())
        output = fmt.format()
        assert 'sub_00000100:' in output

    def test_label_not_subroutine(self):
        instrs = {0x100: _instr(0x100, 'nop')}
        fmt = AsmFormatter(instrs, subroutines=set(), labels={0x100})
        output = fmt.format()
        assert 'loc_00000100:' in output

    def test_subroutine_takes_precedence_over_label(self):
        # If an address is both a subroutine entry and a label, subroutine wins
        instrs = {0x100: _instr(0x100, 'nop')}
        fmt = AsmFormatter(instrs, subroutines={0x100}, labels={0x100})
        output = fmt.format()
        assert 'sub_00000100:' in output
        assert 'loc_00000100:' not in output

    def test_instruction_indented_with_tab(self):
        instrs = {0x100: _instr(0x100, 'nop')}
        fmt = AsmFormatter(instrs, subroutines=set(), labels=set())
        output = fmt.format()
        lines = [l for l in output.splitlines() if l.strip()]
        nop_lines = [l for l in lines if 'nop' in l]
        assert any(l.startswith('\t') for l in nop_lines)

    def test_org_directive_before_gap(self):
        # Gap between instructions should insert org
        i1 = _instr(0x100, 'nop')
        i2 = _instr(0x200, 'rts')
        instrs = {0x100: i1, 0x200: i2}
        fmt = AsmFormatter(instrs, subroutines={0x200}, labels=set())
        output = fmt.format()
        assert 'org $00000200' in output

    def test_header_comment(self):
        instrs = {0x100: _instr(0x100, 'nop')}
        fmt = AsmFormatter(instrs, subroutines=set(), labels=set())
        output = fmt.format()
        assert 'Disassembly' in output
        assert 'org $00000100' in output


class TestAsmFormatterMnemonics:
    """Mnemonic formatting (with/without size suffix)."""

    def test_mnemonic_without_size(self):
        instrs = {0x100: _instr(0x100, 'nop')}
        fmt = AsmFormatter(instrs, set(), set())
        assert 'nop' in fmt.format()

    def test_mnemonic_with_size(self):
        instrs = {0x100: _instr(0x100, 'move', 'w')}
        fmt = AsmFormatter(instrs, set(), set())
        output = fmt.format()
        assert 'move.w' in output


class TestAsmFormatterOperands:
    """Operand formatting."""

    def test_immediate_byte(self):
        instrs = {0x100: _instr(0x100, 'nop', operands=['#$42'])}
        fmt = AsmFormatter(instrs, set(), set())
        output = fmt.format()
        assert '#$42' in output

    def test_data_register(self):
        instrs = {0x100: _instr(0x100, 'nop', operands=['d0'])}
        fmt = AsmFormatter(instrs, set(), set())
        output = fmt.format()
        assert 'd0' in output

    def test_address_register(self):
        instrs = {0x100: _instr(0x100, 'nop', operands=['a7'])}
        fmt = AsmFormatter(instrs, set(), set())
        output = fmt.format()
        assert 'a7' in output

    def test_addr_operand_sub_label(self):
        # When an Addr operand points to a known subroutine, use sub_ label
        addr_op = Addr(0x000300, 'abs_l')
        instrs = {0x100: _instr(0x100, 'jsr', operands=[addr_op])}
        fmt = AsmFormatter(instrs, subroutines={0x000300}, labels=set())
        output = fmt.format()
        assert '(sub_00000300).l' in output

    def test_addr_operand_loc_label(self):
        addr_op = Addr(0x000400, 'abs_w')
        instrs = {0x100: _instr(0x100, 'bra', operands=[addr_op])}
        fmt = AsmFormatter(instrs, subroutines=set(), labels={0x000400})
        output = fmt.format()
        assert 'loc_00000400' in output

    def test_addr_operand_unknown(self):
        addr_op = Addr(0x123456, 'abs_l')
        instrs = {0x100: _instr(0x100, 'jmp', operands=[addr_op])}
        fmt = AsmFormatter(instrs, subroutines=set(), labels=set())
        output = fmt.format()
        assert '($123456).l' in output

    def test_pc_rel_label(self):
        addr_op = Addr(0x000400, 'pc_rel')
        instrs = {0x100: _instr(0x100, 'bra', operands=[addr_op])}
        fmt = AsmFormatter(instrs, subroutines=set(), labels={0x000400})
        output = fmt.format()
        assert 'loc_00000400' in output

    def test_pc_rel_unknown(self):
        addr_op = Addr(0x000500, 'pc_rel')
        instrs = {0x100: _instr(0x100, 'bra', operands=[addr_op])}
        fmt = AsmFormatter(instrs, subroutines=set(), labels=set())
        output = fmt.format()
        assert '$000500(pc)' in output

    def test_pc_rel_indexed(self):
        addr_op = Addr(0x000300, 'pc_rel_idx', suffix='d0.w')
        instrs = {0x100: _instr(0x100, 'jmp', operands=[addr_op])}
        fmt = AsmFormatter(instrs, subroutines=set(), labels=set())
        output = fmt.format()
        assert '$000300(pc,d0.w)' in output

    def test_abs_w_sign_extended_display(self):
        # $FF80 as a signed 16-bit is -128
        addr_op = Addr(0xFFFFFF80, 'abs_w')
        instrs = {0x100: _instr(0x100, 'jmp', operands=[addr_op])}
        fmt = AsmFormatter(instrs, subroutines=set(), labels=set())
        output = fmt.format()
        # Should display as signed hex: ($FF80).w
        assert '($FFFFFF80).w' in output


class TestAsmFormatterSorted:
    """Instructions are output in ascending address order."""

    def test_sorted_address_order(self):
        instrs = {
            0x200: _instr(0x200, 'rts'),
            0x100: _instr(0x100, 'nop'),
        }
        fmt = AsmFormatter(instrs, subroutines={0x200}, labels=set())
        output = fmt.format()
        lines = output.splitlines()
        nop_line = next(i for i, l in enumerate(lines) if 'nop' in l)
        rts_line = next(i for i, l in enumerate(lines) if 'rts' in l)
        assert nop_line < rts_line
