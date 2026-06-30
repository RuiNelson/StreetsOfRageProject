"""Instruction → C++ statement generation for data-processing opcodes.

Each handler emits C++ that materializes the operands (via ``ea_codegen``) and
then invokes a per-opcode macro from ``tools/recompiler/M68KMacros.hpp`` — e.g.
``M68K_ADD_W``, ``M68K_LSR_L``, ``M68K_MOVE_TO_SR``. The macros carry the
operation + CCR semantics; the generator supplies side-effect-free temporaries
so a macro never re-evaluates an operand.

Control-flow instructions (bra/bcc/bsr/jsr/jmp/dbcc/rts/rte/rtr) are emitted by
``generator`` (they need region context); ``emit_dataop`` returns ``None`` for
those. ``movem`` is also expanded by ``generator`` (a memory block transfer, not
a value op). Anything else not implemented raises :class:`Unsupported` so the
generator fails loudly — the recompiler must translate 100% of what it sees.
"""

from tools.disassembler.instruction import EAMode
from tools.recompiler import ea_codegen as ea
from tools.recompiler.ea_codegen import EAGenError, TempPool

_SUF = {'b': 'B', 'w': 'W', 'l': 'L'}
_NBITS = {'b': 8, 'w': 16, 'l': 32}

FLOW_MNEMONICS = {
    'bra', 'bsr', 'jmp', 'jsr', 'rts', 'rte', 'rtr',
    'bhi', 'bls', 'bcc', 'bcs', 'bne', 'beq', 'bvc', 'bvs',
    'bpl', 'bmi', 'bge', 'blt', 'bgt', 'ble',
    'dbt', 'dbf', 'dbra', 'dbhi', 'dbls', 'dbcc', 'dbcs', 'dbne', 'dbeq',
    'dbvc', 'dbvs', 'dbpl', 'dbmi', 'dbge', 'dblt', 'dbgt', 'dble',
}

# Emitted by generator (memory block transfer, not a value macro).
GENERATOR_MNEMONICS = {'movem'}

# Scc — set a byte to 0xFF/0x00 per the condition. Mapped to condition numbers.
SCC = {'st': 0, 'sf': 1, 'shi': 2, 'sls': 3, 'scc': 4, 'scs': 5, 'sne': 6,
       'seq': 7, 'svc': 8, 'svs': 9, 'spl': 10, 'smi': 11, 'sge': 12,
       'slt': 13, 'sgt': 14, 'sle': 15}


class Unsupported(Exception):
    """An opcode this generator does not yet implement."""


def _sized(instr) -> str:
    return instr.size or 'w'


def _signext_to_long(expr: str, size: str) -> str:
    return ea.signext_to_long(expr, size)


def emit_dataop(instr):
    m = instr.mnemonic
    if m in FLOW_MNEMONICS or m in GENERATOR_MNEMONICS:
        return None
    if m in SCC:
        return _scc(instr, TempPool(instr.address), SCC[m])
    handler = _HANDLERS.get(m)
    if handler is None:
        raise Unsupported(m)
    return handler(instr, TempPool(instr.address))


# ---------------------------------------------------------------------------
# Special-register helpers (move/andi/ori/eori to sr or ccr)
# ---------------------------------------------------------------------------

def _is_special(e):
    return e.mode == EAMode.SPECIAL_REG


def _special_size(e):
    """move to/from usp is long; sr/ccr are word."""
    return 'l' if e.special == 'usp' else 'w'


def _special_src_expr(e):
    if e.special == 'sr':
        return 'M68K_MOVE_FROM_SR()'
    if e.special == 'ccr':
        return 'static_cast<m_word>(M68K_SR & 0x00FFu)'
    if e.special == 'usp':
        return 'cpu().usp'
    raise EAGenError(f'read from special register {e.special}')


def _special_write(e, value):
    if e.special == 'sr':
        return [f'M68K_MOVE_TO_SR({value});']
    if e.special == 'ccr':
        return [f'M68K_MOVE_TO_CCR({value});']
    if e.special == 'usp':
        return [f'M68K_MOVE_TO_USP({value});']
    raise EAGenError(f'write to special register {e.special}')


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _move(instr, tmp):
    size = _sized(instr)
    src, dst = instr.eas[0], instr.eas[1]

    # move to/from a special register (SR / CCR / USP).
    if _is_special(dst):
        ssz = _special_size(dst)
        s_stmts, sval = (([], _special_src_expr(src)) if _is_special(src)
                         else ea.read_ea(src, ssz, tmp))
        return s_stmts + _special_write(dst, sval)
    if _is_special(src):
        ssz = _special_size(src)
        v = tmp.fresh()
        stmts = [f'{ea._CTYPE[ssz]} {v} = {_special_src_expr(src)};']
        stmts += ea.write_ea(dst, ssz, v, tmp)
        return stmts

    stmts, val = ea.read_ea(src, size, tmp)
    if dst.mode == EAMode.ADDR_REG:                # movea — sign-extend, no flags
        if size == 'b':
            raise Unsupported('movea.b')           # invalid on 68000
        return stmts + [f'M68K_MOVEA_{_SUF[size]}({ea.areg(dst.reg)}, {val});']
    r = tmp.fresh()
    stmts.append(f'{ea._CTYPE[size]} {r} = {val};')
    if size == 'w' and dst.mode == EAMode.DATA_REG:
        # Word move to Dn: merge low 16 bits only (68000 MOVE.W to Dn).
        stmts.append(ea.write_dn_word_preserve_high(dst.reg, r))
        stmts.append(f'M68K_MOVE_W({r});')
        return stmts
    stmts += ea.write_ea(dst, size, r, tmp)
    stmts.append(f'M68K_MOVE_{_SUF[size]}({r});')
    return stmts


def _moveq(instr, tmp):
    src, dst = instr.eas[0], instr.eas[1]
    r = tmp.fresh()
    return [
        f'm_long {r} = {_signext_to_long(f"static_cast<m_byte>({ea._hex(src.imm)})", "b")};',
        ea.write_dn(dst.reg, 'l', r),
        f'M68K_MOVE_L({r});',
    ]


def _arith(instr, tmp, op):
    """add / sub / cmp families (op in {'ADD','SUB','CMP'})."""
    size = _sized(instr)
    suf = _SUF[size]
    src, dst = instr.eas[0], instr.eas[1]

    if dst.mode == EAMode.ADDR_REG:               # adda / suba / cmpa
        if size == 'b':
            raise Unsupported(f'{op.lower()}a.b') # invalid on 68000
        s_stmts, sval = ea.read_ea(src, size, tmp)
        ar = ea.areg(dst.reg)
        if op == 'CMP':
            return s_stmts + [f'M68K_CMPA_{_SUF[size]}({ar}, {sval});']
        macro = 'ADDA' if op == 'ADD' else 'SUBA'
        return s_stmts + [f'M68K_{macro}_{_SUF[size]}({ar}, {sval});']

    s_stmts, sval = ea.read_ea(src, size, tmp)
    if op == 'CMP':
        d_stmts, dval = ea.read_ea(dst, size, tmp)
        return s_stmts + d_stmts + [f'M68K_CMP_{suf}({dval}, {sval});']
    pre, r, post = ea.rmw_ea(dst, size, tmp)
    return s_stmts + pre + [f'M68K_{op}_{suf}({r}, {sval});'] + post


def _add(instr, tmp): return _arith(instr, tmp, 'ADD')
def _sub(instr, tmp): return _arith(instr, tmp, 'SUB')
def _cmp(instr, tmp): return _arith(instr, tmp, 'CMP')


def _logic(instr, tmp, op):
    size = _sized(instr)
    src, dst = instr.eas[0], instr.eas[1]
    # andi/ori/eori to SR or CCR.
    if _is_special(dst):
        sval = ea.read_ea(src, 'w', tmp)[1]
        cur = _special_src_expr(dst)
        cxx = {'AND': '&', 'OR': '|', 'EOR': '^'}[op]
        return _special_write(dst, f'({cur} {cxx} {sval})')
    s_stmts, sval = ea.read_ea(src, size, tmp)
    pre, r, post = ea.rmw_ea(dst, size, tmp)
    return s_stmts + pre + [f'M68K_{op}_{_SUF[size]}({r}, {sval});'] + post


def _and(instr, tmp): return _logic(instr, tmp, 'AND')
def _or(instr, tmp):  return _logic(instr, tmp, 'OR')
def _eor(instr, tmp): return _logic(instr, tmp, 'EOR')


def _tst(instr, tmp):
    size = _sized(instr)
    stmts, val = ea.read_ea(instr.eas[0], size, tmp)
    return stmts + [f'M68K_TST_{_SUF[size]}({val});']


def _clr(instr, tmp):
    size = _sized(instr)
    r = tmp.fresh()
    stmts = [f'{ea._CTYPE[size]} {r} = 0;', f'M68K_CLR_{_SUF[size]}({r});']
    return stmts + ea.write_ea(instr.eas[0], size, r, tmp)


def _lea(instr, tmp):
    src, dst = instr.eas[0], instr.eas[1]
    setup, addr = ea.address_of(src, tmp)
    return setup + [f'{ea.areg(dst.reg)} = static_cast<m_long>({addr});']


def _pea(instr, tmp):
    setup, addr = ea.address_of(instr.eas[0], tmp)
    return setup + [
        'cpu().ssp -= 4;',
        f'memory().writeLong(cpu().ssp, static_cast<m_long>({addr}));',
    ]


def _unary(instr, tmp, macro):
    """neg / not — read-modify-write a single operand via a no-arg macro."""
    size = _sized(instr)
    pre, r, post = ea.rmw_ea(instr.eas[0], size, tmp)
    return pre + [f'M68K_{macro}_{_SUF[size]}({r});'] + post


def _neg(instr, tmp): return _unary(instr, tmp, 'NEG')
def _not(instr, tmp): return _unary(instr, tmp, 'NOT')


def _swap(instr, tmp):
    n = instr.eas[0].reg
    r = tmp.fresh()
    return [f'm_long {r} = {ea.read_dn(n, "l")};',
            f'M68K_SWAP({r});',
            ea.write_dn(n, 'l', r)]


def _ext(instr, tmp):
    n = instr.eas[0].reg
    return [f'M68K_EXT_{"L" if instr.size == "l" else "W"}({n});']


def _shift(instr, tmp, macro):
    """Shift/rotate. Forms: '<op> #cnt, Dn' / '<op> Dm, Dn' / '<op> <ea>' (×1)."""
    size = _sized(instr)
    suf = _SUF[size]
    if len(instr.eas) == 1:                       # memory shift, count = 1
        pre, r, post = ea.rmw_ea(instr.eas[0], size, tmp)
        return pre + [f'M68K_{macro}_{suf}({r}, 1);'] + post
    count, dst = instr.eas[0], instr.eas[1]
    if count.mode == EAMode.IMMEDIATE:
        cnt = str((count.imm - 1) % 8 + 1)        # immediate count is 1..8
    else:
        # Register count: low six bits of Dn; zero → 8/16/32 by operand size.
        zero = {'b': 8, 'w': 16, 'l': 32}[size]
        cnt = f'M68K_REG_SHIFT_COUNT({count.reg}, {zero})'
    pre, r, post = ea.rmw_ea(dst, size, tmp)
    return pre + [f'M68K_{macro}_{suf}({r}, {cnt});'] + post


def _muldiv(instr, tmp, macro):
    """mulu/muls (16×16→Dn long) and divu/divs (Dn 32 ÷ src16 → Dn)."""
    src, dst = instr.eas[0], instr.eas[1]
    s_stmts, sval = ea.read_ea(src, 'w', tmp)
    if macro.startswith('MUL'):
        dexpr = ea.read_dn(dst.reg, 'w')
    else:
        dexpr = ea.read_dn(dst.reg, 'l')
    return s_stmts + [ea.write_dn(dst.reg, 'l', f'M68K_{macro}({dexpr}, {sval})')]


def _bitop(instr, tmp, kind):
    bit_ea, dst = instr.eas[0], instr.eas[1]
    data_reg = dst.mode == EAMode.DATA_REG
    size = 'l' if data_reg else 'b'
    modulo = 32 if data_reg else 8
    if bit_ea.mode == EAMode.IMMEDIATE:
        bit = str(bit_ea.imm % modulo)
    else:
        bit = f'(cpu().d[{bit_ea.reg}] % {modulo})'
    if kind == 'BTST':
        stmts, val = ea.read_ea(dst, size, tmp)
        return stmts + [f'M68K_BTST({val}, {bit});']
    pre, r, post = ea.rmw_ea(dst, size, tmp)
    return pre + [f'M68K_{kind}({r}, {bit});'] + post


def _scc(instr, tmp, cc):
    r = tmp.fresh()
    stmts = [f'm_byte {r} = 0;', f'M68K_SCC({r}, {cc});']
    return stmts + ea.write_ea(instr.eas[0], 'b', r, tmp)


def _reg_lvalue(e):
    if e.mode == EAMode.DATA_REG:
        return f'cpu().d[{e.reg}]'
    if e.mode == EAMode.ADDR_REG:
        return ea.areg(e.reg)
    raise EAGenError(f'exg operand is not a register: {e.mode}')


def _exg(instr, tmp):
    a = _reg_lvalue(instr.eas[0])
    b = _reg_lvalue(instr.eas[1])
    return [f'M68K_EXG({a}, {b});']


def _bcd(instr, tmp, macro):
    src, dst = instr.eas[0], instr.eas[1]
    s_stmts, sval = ea.read_ea(src, 'b', tmp)
    pre, r, post = ea.rmw_ea(dst, 'b', tmp)
    return s_stmts + pre + [f'M68K_{macro}({r}, {sval});'] + post


def _nbcd(instr, tmp):
    pre, r, post = ea.rmw_ea(instr.eas[0], 'b', tmp)
    return pre + [f'M68K_NBCD({r});'] + post


def _negx(instr, tmp):
    size = _sized(instr)
    pre, r, post = ea.rmw_ea(instr.eas[0], size, tmp)
    return pre + [f'M68K_NEGX_{_SUF[size]}({r});'] + post


def _movep(instr, tmp):
    """Transfer bytes between Dn and alternating memory addresses. No CCR effect."""
    size = _sized(instr)  # 'w' or 'l'
    src, dst = instr.eas[0], instr.eas[1]
    if src.mode == EAMode.DATA_REG:          # reg → mem
        dn = src.reg
        setup, base = ea.address_of(dst, tmp)
        b = tmp.fresh()
        stmts = setup + [f'm_long {b} = {base};']
        shifts = [24, 16, 8, 0] if size == 'l' else [8, 0]
        for i, sh in enumerate(shifts):
            stmts.append(f'memory().writeByte({b} + {i * 2}, '
                         f'static_cast<m_byte>((cpu().d[{dn}] >> {sh}) & 0xFFu));')
        return stmts
    else:                                    # mem → reg
        dn = dst.reg
        setup, base = ea.address_of(src, tmp)
        b = tmp.fresh()
        stmts = setup + [f'm_long {b} = {base};']
        if size == 'l':
            stmts.append(
                f'cpu().d[{dn}] = '
                f'(static_cast<m_long>(memory().readByte({b})) << 24) | '
                f'(static_cast<m_long>(memory().readByte({b} + 2)) << 16) | '
                f'(static_cast<m_long>(memory().readByte({b} + 4)) << 8) | '
                f'static_cast<m_long>(memory().readByte({b} + 6));'
            )
        else:
            stmts.append(
                f'cpu().d[{dn}] = (cpu().d[{dn}] & 0xFFFF0000u) | '
                f'(static_cast<m_long>(memory().readByte({b})) << 8) | '
                f'static_cast<m_long>(memory().readByte({b} + 2));'
            )
        return stmts


def _nop(instr, tmp):
    return ['M68K_NOP();']


_HANDLERS = {
    'move': _move, 'movea': _move,
    'moveq': _moveq,
    'movep': _movep,
    'add': _add, 'adda': _add, 'addi': _add, 'addq': _add,
    'sub': _sub, 'suba': _sub, 'subi': _sub, 'subq': _sub,
    'cmp': _cmp, 'cmpa': _cmp, 'cmpi': _cmp, 'cmpm': _cmp,
    'and': _and, 'andi': _and,
    'or': _or, 'ori': _or,
    'eor': _eor, 'eori': _eor,
    'tst': _tst, 'clr': _clr, 'lea': _lea, 'pea': _pea,
    'swap': _swap, 'ext': _ext,
    'neg': _neg, 'not': _not,
    'btst': lambda i, t: _bitop(i, t, 'BTST'),
    'bset': lambda i, t: _bitop(i, t, 'BSET'),
    'bclr': lambda i, t: _bitop(i, t, 'BCLR'),
    'bchg': lambda i, t: _bitop(i, t, 'BCHG'),
    'lsl': lambda i, t: _shift(i, t, 'LSL'),
    'lsr': lambda i, t: _shift(i, t, 'LSR'),
    'asl': lambda i, t: _shift(i, t, 'ASL'),
    'asr': lambda i, t: _shift(i, t, 'ASR'),
    'rol': lambda i, t: _shift(i, t, 'ROL'),
    'ror': lambda i, t: _shift(i, t, 'ROR'),
    'roxl': lambda i, t: _shift(i, t, 'ROXL'),
    'roxr': lambda i, t: _shift(i, t, 'ROXR'),
    'mulu': lambda i, t: _muldiv(i, t, 'MULU'),
    'muls': lambda i, t: _muldiv(i, t, 'MULS'),
    'divu': lambda i, t: _muldiv(i, t, 'DIVU'),
    'divs': lambda i, t: _muldiv(i, t, 'DIVS'),
    'exg': _exg,
    'abcd': lambda i, t: _bcd(i, t, 'ABCD'),
    'sbcd': lambda i, t: _bcd(i, t, 'SBCD'),
    'nbcd': _nbcd,
    'negx': _negx,
    'nop': _nop,
}
