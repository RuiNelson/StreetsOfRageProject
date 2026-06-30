"""Validator self-checks for tools.speculative_scan.

The interesting case is overlapping decodes: a word that decodes *standalone* as
a clean branch, but is really the extension word of a longer instruction whose
true fall-through hits invalid data. An earlier optimistic-cycle memoisation
wrongly accepted such an address; reachability must reject it.
"""

from pathlib import Path

from tools.disassembler.rom import ROM
from tools.speculative_scan import Validator, scan
from tools.speculative_scan.main import static_recompiler_map, write_output

_MAP = b'X' * (ROM.END + 1)  # everything unmapped, so nothing short-circuits


def _rom(at: dict[int, bytes]) -> ROM:
    data = bytearray(ROM.END + 1)
    for addr, b in at.items():
        data[addr:addr + len(b)] = b
    return ROM(bytes(data))


def test_clean_function_validates():
    # move.w d0,d1 ; rts
    rom = _rom({0x1000: b'\x32\x00\x4E\x75'})
    assert Validator(rom, _MAP).terminates(0x1000) is True


def test_line_a_data_word_rejected():
    rom = _rom({0x1000: b'\xA0\x00'})  # Line-A → dc.w, not a real opcode
    assert Validator(rom, _MAP).terminates(0x1000) is False


def test_branch_off_rom_rejected():
    # bra.s with a displacement that lands outside ROM → no resolved target,
    # which the recompiler cannot lower (targets[0] would throw).
    rom = _rom({ROM.END - 1: b'\x60\x7E'})
    assert Validator(rom, _MAP).terminates(ROM.END - 1) is False


def test_overlapping_decode_trap_rejected():
    # 0x1000: move.l ($60FC).w, d0   (4 bytes) — its extension word is 0x60FC
    # 0x1002: 60 FC decodes *standalone* as bra.s back to 0x1000 (a cycle)
    # 0x1004: A000  Line-A data word
    # The real fall-through 0x1000 -> 0x1004 hits invalid data, so neither
    # 0x1000 nor the misaligned 0x1002 is a valid function.
    rom = _rom({0x1000: b'\x20\x38\x60\xFC\xA0\x00'})
    v = Validator(rom, _MAP)
    assert v.terminates(0x1000) is False
    assert v.terminates(0x1002) is False


def test_run_end_skips_past_rts():
    # move.w d0,d1 ; move.w d2,d3 ; rts   — run ends just after the rts.
    rom = _rom({0x1000: b'\x32\x00\x34\x02\x4E\x75'})
    assert Validator(rom, _MAP).run_end(0x1000) == 0x1006


def test_scan_emits_one_address_per_function():
    # Two back-to-back functions, each `move.w d0,d1 ; rts` (4 bytes).
    # Only the two entry addresses must be emitted — not every opcode offset.
    rom = _rom({0x2000: b'\x32\x00\x4E\x75\x32\x00\x4E\x75'})
    mp = bytearray(b'C' * (ROM.END + 1))  # only the window is unmapped ('X')
    mp[0x2000:0x2008] = b'X' * 8
    assert scan(bytes(mp), rom, known=set()) == [0x2000, 0x2004]


def test_write_output_uses_canonical_uppercase_6_digit_addresses(tmp_path):
    out = tmp_path / 'spec.txt'

    write_output([0x16D0A, 0x72E9C], out)

    lines = out.read_text().splitlines()
    assert lines[1:] == ['016D0A', '072E9C']


def test_static_filter_prevents_known_recompiler_targets_from_being_speculative(tmp_path):
    root = Path(__file__).resolve().parents[3]
    aux = tmp_path / 'aux_without_016d0a.txt'
    lines = []
    for line in (root / 'code-analysis/aux_addresses.txt').read_text().splitlines():
        s = line.split(';')[0].split('#')[0].strip()
        if s and int(s, 16) == 0x016D0A:
            continue
        lines.append(line)
    aux.write_text('\n'.join(lines) + '\n')

    rom = ROM.from_file(str(root / 'rom/SOR.bin'))
    rom_map, known = static_recompiler_map(rom, aux)
    results = scan(rom_map, rom, known)

    assert 0x016D0A in known
    assert 0x016D0A not in results


if __name__ == '__main__':
    test_clean_function_validates()
    test_line_a_data_word_rejected()
    test_branch_off_rom_rejected()
    test_overlapping_decode_trap_rejected()
    test_run_end_skips_past_rts()
    test_scan_emits_one_address_per_function()
    print('ok')
