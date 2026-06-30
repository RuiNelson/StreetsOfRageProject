"""Unit tests for the recompiler codegen (EA expressions + opcode lowering)."""

from pathlib import Path
import subprocess
import sys

from tools.disassembler.instruction import EA, EAMode, FlowType, Instruction
from tools.disassembler.rom import ROM
from tools.recompiler import ea_codegen as ea
from tools.recompiler import main as recompiler_main
from tools.recompiler import opcodes
from tools.recompiler.ea_codegen import TempPool
from tools.recompiler.generator import Generator
from tools.recompiler.main import _install_macros, _load_aux
from tools.recompiler.opcodes import Unsupported
from tools.recompiler.regions import partition

_ROOT = Path(__file__).resolve().parents[3]


def _tp():
    return TempPool(0x1000)


def _run_recompiler(out_dir, *args):
    return subprocess.run(
        [sys.executable, '-m', 'tools.recompiler',
         'rom/SOR.bin', '-o', str(out_dir), *args],
        cwd=_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _function_source(source, name):
    start = source.index(f'void Sor::{name}(')
    end = source.find('\n}\n\n', start)
    if end < 0:
        end = source.rindex('\n}', start)
    return source[start:end]


# --- effective-address codegen -------------------------------------------

def test_areg_a7_is_ssp():
    assert ea.areg(7) == 'cpu().ssp'
    assert ea.areg(3) == 'cpu().a[3]'


def test_read_data_reg_sizes():
    assert ea.read_ea(EA(EAMode.DATA_REG, reg=3), 'l', _tp())[1] == 'cpu().d[3]'
    assert ea.read_ea(EA(EAMode.DATA_REG, reg=0), 'b', _tp())[1] == \
        'static_cast<m_byte>(cpu().d[0] & 0xFFu)'


def test_read_postinc_has_side_effect_after_read():
    stmts, expr = ea.read_ea(EA(EAMode.ADDR_POSTINC, reg=0), 'w', _tp())
    joined = '\n'.join(stmts)
    assert 'readWord(cpu().a[0])' in joined
    assert 'cpu().a[0] += 2;' in joined
    # the read must precede the increment
    assert joined.index('readWord') < joined.index('+= 2')
    assert expr in joined  # value materialized into a temp


def test_a7_byte_postinc_and_predec_step_by_word():
    post, _ = ea.read_ea(EA(EAMode.ADDR_POSTINC, reg=7), 'b', _tp())
    pre, _ = ea.read_ea(EA(EAMode.ADDR_PREDEC, reg=7), 'b', _tp())

    assert 'cpu().ssp += 2;' in '\n'.join(post)
    assert 'cpu().ssp -= 2;' in '\n'.join(pre)


def test_non_a7_byte_postinc_still_steps_by_byte():
    stmts, _ = ea.read_ea(EA(EAMode.ADDR_POSTINC, reg=4), 'b', _tp())

    assert 'cpu().a[4] += 1;' in '\n'.join(stmts)


def test_read_predec_decrements_before_read():
    stmts, _ = ea.read_ea(EA(EAMode.ADDR_PREDEC, reg=1), 'l', _tp())
    joined = '\n'.join(stmts)
    assert joined.index('-= 4') < joined.index('readLong')


def test_write_subregister_uses_merge_helpers():
    assert ea.write_ea(EA(EAMode.DATA_REG, reg=2), 'b', 'v', _tp()) == \
        ['cpu().d[2] = static_cast<m_long>((cpu().d[2] & 0xFFFFFF00u) '
         '| static_cast<m_long>(static_cast<m_byte>(v)));']
    assert ea.write_ea(EA(EAMode.DATA_REG, reg=2), 'w', 'v', _tp()) == \
        ['cpu().d[2] = static_cast<m_long>((cpu().d[2] & 0xFFFF0000u) '
         '| static_cast<m_long>(static_cast<m_word>(v)));']


def test_write_addr_reg_word_sign_extends():
    out = ea.write_ea(EA(EAMode.ADDR_REG, reg=4), 'w', 'v', _tp())[0]
    assert 'static_cast<int32_t>' in out
    assert 'cpu().a[4]' in out


def test_address_of_disp_and_abs():
    assert ea.address_of(EA(EAMode.ADDR_DISP, reg=2, disp=4), _tp())[1] == \
        '(cpu().a[2] + 4)'
    assert ea.address_of(EA(EAMode.ABS_L, abs_value=0xFF0000), _tp())[1] == \
        '0x00FF0000u'


# --- opcode lowering -----------------------------------------------------

def _instr(mnem, size, eas, flow=FlowType.SEQUENTIAL):
    return Instruction(address=0x1000, mnemonic=mnem, size=size, operands=[],
                       byte_length=2, flow=flow, eas=eas)


def test_move_sets_logical_flags():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'move', 'l', [EA(EAMode.DATA_REG, reg=0), EA(EAMode.DATA_REG, reg=1)])))
    assert 'cpu().d[1]' in out and 'M68K_MOVE_L(' in out


def test_movea_no_flags_sign_extends():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'move', 'w', [EA(EAMode.DATA_REG, reg=0), EA(EAMode.ADDR_REG, reg=1)])))
    assert 'setLogicalFlags' not in out          # movea never touches CCR
    assert 'M68K_MOVEA_W(cpu().a[1]' in out       # word source sign-extended


def test_move_word_to_data_reg_sign_extends():
    """68000 MOVE.W to Dn sign-extends; must not use setDataWord (preserves high half)."""
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'move', 'w', [EA(EAMode.DATA_REG, reg=0), EA(EAMode.DATA_REG, reg=7)])))
    assert 'cpu().d[7]' in out and '0xFFFF0000u' in out
    assert 'M68K_WRITE_DN_W(7' not in out
    assert 'M68K_MOVE_W(' in out


def test_move_word_to_memory_uses_ea_writer_not_data_reg_macro():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'move', 'w', [EA(EAMode.DATA_REG, reg=0), EA(EAMode.ADDR_IND, reg=1)])))
    assert '0xFFFF0000u' not in out
    assert 'memory().writeWord(cpu().a[1]' in out
    assert 'M68K_MOVE_W(' in out


def test_moveq_long_signext_and_flags():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'moveq', None, [EA(EAMode.IMMEDIATE, imm=-1), EA(EAMode.DATA_REG, reg=0)])))
    assert 'cpu().d[0]' in out and 'M68K_MOVE_L(' in out


def test_add_uses_macro_and_writes_back():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'add', 'w', [EA(EAMode.DATA_REG, reg=0), EA(EAMode.DATA_REG, reg=1)])))
    assert 'M68K_ADD_W(' in out
    assert 'cpu().d[1]' in out


def test_cmp_sets_flags_without_writing():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'cmp', 'l', [EA(EAMode.DATA_REG, reg=0), EA(EAMode.DATA_REG, reg=1)])))
    assert 'M68K_CMP_L(' in out
    assert 'setData' not in out                   # compare writes nothing


def test_adda_is_address_arith_no_flags():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'adda', 'l', [EA(EAMode.DATA_REG, reg=0), EA(EAMode.ADDR_REG, reg=1)])))
    assert 'M68K_ADDA_L(cpu().a[1]' in out
    assert 'M68K_ADD_' not in out and 'setLogicalFlags' not in out


def test_shift_immediate_count():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'lsr', 'w', [EA(EAMode.IMMEDIATE, imm=3), EA(EAMode.DATA_REG, reg=2)])))
    assert 'M68K_LSR_W(' in out and ', 3)' in out


def test_shift_register_count_uses_reg_shift_count():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'lsl', 'w', [EA(EAMode.DATA_REG, reg=1), EA(EAMode.DATA_REG, reg=0)])))
    assert 'M68K_LSL_W(' in out
    assert 'M68K_REG_SHIFT_COUNT(1, 16)' in out


def test_movem_unsupported_via_generator():
    # movem is handled by the generator, not emit_dataop.
    assert opcodes.emit_dataop(_instr('movem', 'l', [], FlowType.SEQUENTIAL)) is None


def test_movem_reglist_crosses_data_to_addr():
    """d5-a4 spans D5..D7 then A0..A4 — common in SoR boot (movem.l (a5)+, d5-a4)."""
    regs = Generator._parse_reglist('d5-a4')
    assert regs == [(False, 5), (False, 6), (False, 7),
                    (True, 0), (True, 1), (True, 2), (True, 3), (True, 4)]


def test_scc_sets_byte_by_condition():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'sne', 'b', [EA(EAMode.DATA_REG, reg=6)])))
    assert 'M68K_SCC(' in out and ', 6)' in out      # 6 == NE
    assert 'cpu().d[6]' in out


def test_exg_swaps_registers():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'exg', 'l', [EA(EAMode.DATA_REG, reg=0), EA(EAMode.ADDR_REG, reg=1)])))
    assert 'M68K_EXG(cpu().d[0], cpu().a[1])' in out


def test_abcd_uses_macro():
    out = '\n'.join(opcodes.emit_dataop(_instr(
        'abcd', 'b', [EA(EAMode.DATA_REG, reg=0), EA(EAMode.DATA_REG, reg=1)])))
    assert 'M68K_ABCD(' in out


def test_flow_opcodes_return_none():
    assert opcodes.emit_dataop(_instr('bra', None, [], FlowType.BRANCH)) is None
    assert opcodes.emit_dataop(_instr('rts', None, [], FlowType.RETURN)) is None


def test_unsupported_opcode_raises():
    # tas is not reached by the SoR ROM and is intentionally not implemented;
    # the generator must reject it (hard error) rather than silently degrade.
    try:
        opcodes.emit_dataop(_instr('tas', 'b', [EA(EAMode.DATA_REG, reg=0)]))
    except Unsupported:
        return
    assert False, 'expected Unsupported for tas'


# --- region partitioning -------------------------------------------------

def test_irq_check_emitted_before_each_instruction():
    from tools.recompiler.generator import Generator
    ins = {0x100: _instr('nop', None, []),
           0x102: _instr('rts', None, [], FlowType.RETURN)}
    for a in ins:
        ins[a].address = a
    src = Generator(ins, {0x100}).emit_source()
    assert src.count('M68K_STEP();') == 2
    assert 'M68K_NOP();' in src
    assert 'M68K_RTS();' in src
    assert 'void Sor::serviceIRQ()' in src


def test_jsr_emits_nonlocal_return_guard():
    ins = {
        0x100: _instr('jsr', None, [], FlowType.CALL),
        0x106: _instr('rts', None, [], FlowType.RETURN),
        0x200: _instr('rts', None, [], FlowType.RETURN),
    }
    ins[0x100].byte_length = 6
    ins[0x100].targets = [0x200]
    for a in ins:
        ins[a].address = a

    src = Generator(ins, {0x100, 0x200}).emit_source()

    assert 'm_long __sp_000100 = cpu().ssp;' in src
    assert 'M68K_PUSH_RET(0x00000106u);' in src
    assert 'if ((cpu().ssp & 0x00FFFFFFu) > (__sp_000100 & 0x00FFFFFFu)) return;' in src


def test_partition_assigns_to_nearest_entry():
    ins = {
        0x100: _instr('nop', None, []),
        0x102: _instr('rts', None, [], FlowType.RETURN),
        0x200: _instr('nop', None, []),
        0x202: _instr('rts', None, [], FlowType.RETURN),
    }
    for a in ins:
        ins[a].address = a
    part = partition(ins, {0x100, 0x200})
    assert part.entries == [0x100, 0x200]
    assert part.func_of(0x102) == 0x100
    assert part.func_of(0x202) == 0x200
    assert part.functions[0x100].addrs == [0x100, 0x102]


def test_load_aux_ignores_vector_table_and_odd_addresses(tmp_path):
    aux = tmp_path / 'aux.txt'
    aux.write_text('0000001e\n00000200\n00000201\n00000436 ; valid\n')

    assert _load_aux(aux) == [0x200, 0x436]


def test_load_aux_empty_path_disables_optional_inputs():
    assert _load_aux('') == []


def test_recompiler_default_emits_no_speculative_hooks(tmp_path):
    out = tmp_path / 'normal'

    _run_recompiler(out)

    source = (out / 'Sor.cpp').read_text()
    assert 'confirmSpeculative(' not in source


def test_recompiler_speculative_option_emits_speculative_hooks(tmp_path):
    out = tmp_path / 'discover'

    _run_recompiler(out, '--speculative', 'code-analysis/speculative_addresses.txt')

    source = (out / 'Sor.cpp').read_text()
    assert 'confirmSpeculative(' in source


def test_install_macros_creates_output_directory(tmp_path):
    out = tmp_path / 'new-generated-dir'

    copied = _install_macros(str(out))

    assert copied == out / 'M68KMacros.hpp'
    assert copied.exists()


def test_disassemble_to_fixpoint_repeats_after_new_table_targets(monkeypatch):
    calls = []

    class FakeDisassembler:
        def __init__(self, rom, aux_addresses, verbose=False):
            self.rom = rom
            self.aux_addresses = set(aux_addresses)
            self.verbose = verbose
            self.subroutines = set()
            self.instructions = {}
            calls.append(self.aux_addresses)

        def disassemble(self):
            pass

    def fake_discover(disasm, rom):
        return {0x200} if 0x200 not in disasm.aux_addresses else set()

    monkeypatch.setattr(recompiler_main, 'Disassembler', FakeDisassembler)
    monkeypatch.setattr(recompiler_main, '_discover_table_targets', fake_discover)

    disasm, seeds = recompiler_main._disassemble_to_fixpoint('rom', {0x100})

    assert calls == [{0x100}, {0x100, 0x200}]
    assert disasm.aux_addresses == {0x100, 0x200}
    assert seeds == {0x100, 0x200}


def test_banked_word_dispatch_table_discovers_016d0a_without_runtime_aux():
    rom = ROM.from_file(str(_ROOT / 'rom/SOR.bin'))
    seeds = set(_load_aux(str(_ROOT / 'code-analysis/aux_addresses.txt')))
    seeds.discard(0x016D0A)

    _, fixed = recompiler_main._disassemble_to_fixpoint(rom, seeds)

    assert 0x016D0A in fixed


def test_shared_dispatcher_backward_table_discovers_00d62a_without_runtime_aux():
    rom = ROM.from_file(str(_ROOT / 'rom/SOR.bin'))
    seeds = set(_load_aux(str(_ROOT / 'code-analysis/aux_addresses.txt')))
    seeds.discard(0x00D62A)

    _, fixed = recompiler_main._disassemble_to_fixpoint(rom, seeds)

    assert 0x00D62A in fixed


def test_speculative_scope_does_not_confirm_derived_entries():
    ins = {
        0x100: _instr('rts', None, [], FlowType.RETURN),
        0x200: _instr('rts', None, [], FlowType.RETURN),
        0x300: _instr('rts', None, [], FlowType.RETURN),
    }
    for a in ins:
        ins[a].address = a

    src = Generator(ins, {0x100, 0x200, 0x300},
                    speculative_addrs={0x200},
                    speculative_scope={0x200, 0x300},
                    baseline_instrs={0x100}).emit_source()

    assert ('case 0x00000200u: confirmSpeculative(0x00000200u); '
            'sub_000200(); return;') in src
    assert 'confirmSpeculative(0x00000200u);' not in _function_source(src, 'sub_000200')
    assert 'confirmSpeculative(0x00000300u);' not in src


def test_invalid_speculative_derived_entry_is_rejected_not_fatal():
    ins = {
        0x100: _instr('rts', None, [], FlowType.RETURN),
        0x200: _instr('rts', None, [], FlowType.RETURN),
        0x300: _instr('tas', 'b', [EA(EAMode.DATA_REG, reg=0)]),
    }
    for a in ins:
        ins[a].address = a

    src = Generator(ins, {0x100, 0x200, 0x300},
                    speculative_addrs={0x200},
                    speculative_scope={0x200, 0x300},
                    baseline_instrs={0x100}).emit_source()

    assert 'void Sor::sub_000300' not in src
    assert ('case 0x00000200u: confirmSpeculative(0x00000200u); '
            'sub_000200(); return;') in src
    assert 'confirmSpeculative(0x00000200u);' not in _function_source(src, 'sub_000200')


def test_csv_names_applied_to_goto_labels():
    ins = {
        0x100: _instr('bra', None, [], FlowType.BRANCH),
        0x106: _instr('nop', None, []),
        0x108: _instr('rts', None, [], FlowType.RETURN),
    }
    ins[0x100].byte_length = 6
    ins[0x100].targets = [0x106]
    for a in ins:
        ins[a].address = a

    src = Generator(ins, {0x100}, names={0x106: 'my_loop'}).emit_source()

    assert 'my_loop:' in src
    assert 'goto my_loop;' in src
    assert 'L000106:' not in src
