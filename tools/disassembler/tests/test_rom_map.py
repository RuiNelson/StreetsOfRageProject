"""Unit tests for the ROM coverage map (RomMap).

RomMap stores one byte per ROM byte (full resolution); ``_map[addr]`` is the
ASCII code of the classification character and ``format()`` returns the raw
bytes. See ``rom_map.py`` for the legend (X/S/s/L/C/c).
"""

try:
    import pytest
except ImportError:
    class _PytestStub:
        @staticmethod
        def parametrize(*_a, **_kw):
            def deco(f): return f
            return deco
    pytest = _PytestStub()

from ..instruction import FlowType, Instruction
from ..rom_map import RomMap


def _instr(address: int, mnemonic: str,
           flow: FlowType = FlowType.SEQUENTIAL,
           byte_length: int = 2) -> Instruction:
    """Create a minimal Instruction for testing."""
    return Instruction(
        address=address,
        mnemonic=mnemonic,
        size=None,
        operands=[],
        byte_length=byte_length,
        flow=flow,
    )


def _ch(rmap: RomMap, addr: int) -> str:
    """Classification character at a ROM byte (the map stores ASCII codes)."""
    return chr(rmap._map[addr])


class TestRomMapLegend:
    """ROM map uses the correct character for each instruction type."""

    def test_rts_is_subroutine_end(self):
        rmap = RomMap(0x200, {0x100: _instr(0x100, 'rts')}, set(), set())
        assert _ch(rmap, 0x100) == 's'

    def test_rte_is_subroutine_end(self):
        rmap = RomMap(0x200, {0x100: _instr(0x100, 'rte')}, set(), set())
        assert _ch(rmap, 0x100) == 's'

    def test_rtr_is_subroutine_end(self):
        rmap = RomMap(0x200, {0x100: _instr(0x100, 'rtr')}, set(), set())
        assert _ch(rmap, 0x100) == 's'

    def test_illegal_is_subroutine_end(self):
        rmap = RomMap(0x200, {0x100: _instr(0x100, 'illegal')}, set(), set())
        assert _ch(rmap, 0x100) == 's'

    def test_subroutine_entry_is_S(self):
        rmap = RomMap(0x200, {0x100: _instr(0x100, 'nop')}, {0x100}, set())
        assert _ch(rmap, 0x100) == 'S'

    def test_branch_target_is_L(self):
        instrs = {0x100: _instr(0x100, 'bra', flow=FlowType.BRANCH),
                  0x102: _instr(0x102, 'nop')}
        rmap = RomMap(0x200, instrs, set(), {0x102})
        assert _ch(rmap, 0x102) == 'L'

    def test_plain_code_is_C(self):
        rmap = RomMap(0x200, {0x100: _instr(0x100, 'add')}, set(), set())
        assert _ch(rmap, 0x100) == 'C'

    def test_unknown_is_X(self):
        rmap = RomMap(0x200, {}, set(), set())
        assert _ch(rmap, 0) == 'X'


class TestRomMapMultiWord:
    """Extension bytes of multi-word instructions are marked 'c'."""

    def test_bra_word_extension(self):
        # BRA.w at $100 occupies 4 bytes (first + 3 continuation).
        rmap = RomMap(0x200, {0x100: _instr(0x100, 'bra', byte_length=4)},
                      set(), {0x104})
        assert _ch(rmap, 0x100) == 'C'
        assert _ch(rmap, 0x101) == 'c'
        assert _ch(rmap, 0x102) == 'c'
        assert _ch(rmap, 0x103) == 'c'

    def test_jsr_long(self):
        # JSR $123456.l at $100 occupies 6 bytes.
        rmap = RomMap(0x200, {0x100: _instr(0x100, 'jsr', byte_length=6)},
                      {0x100}, set())
        assert _ch(rmap, 0x100) == 'S'
        assert _ch(rmap, 0x101) == 'c'
        assert _ch(rmap, 0x105) == 'c'


class TestRomMapFormat:
    """format() returns the raw one-byte-per-ROM-byte map."""

    def test_format_is_raw_bytes_of_rom_size(self):
        rmap = RomMap(0x100, {}, set(), set())
        data = rmap.format()
        assert isinstance(data, (bytes, bytearray))
        assert len(data) == 0x100
        assert data == b'X' * 0x100  # nothing decoded → all unknown

    def test_classification_counts(self):
        instrs = {
            0x100: _instr(0x100, 'nop'),                       # C
            0x102: _instr(0x102, 'rts'),                       # s
            0x104: _instr(0x104, 'bra', flow=FlowType.BRANCH),  # L (branch target)
            0x200: _instr(0x200, 'jsr'),                       # S
        }
        data = RomMap(0x400, instrs, {0x200}, {0x104}).format()
        assert data.count(ord('C')) == 1
        assert data.count(ord('s')) == 1
        assert data.count(ord('L')) == 1
        assert data.count(ord('S')) == 1
