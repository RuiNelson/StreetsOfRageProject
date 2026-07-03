"""Instruction → C++ statement generation for data-processing opcodes.

Each handler emits C++ that materializes operands via ``ea_codegen`` and then
splices direct C++ statements for the opcode/CCR semantics. The generated source
is intentionally self-contained; it no longer depends on a shared per-opcode
macro header.

Control-flow instructions (bra/bcc/bsr/jsr/jmp/dbcc/rts/rte/rtr) are emitted by
``generator`` (they need region context); ``emit_dataop`` returns ``None`` for
those. ``movem`` is also expanded by ``generator`` (a memory block transfer, not
a value op). Anything else not implemented raises :class:`Unsupported` so the
generator fails loudly — the recompiler must translate 100% of what it sees.
"""

from tools.disassembler.instruction import EAMode
from tools.recompiler import ea_codegen as ea
from tools.recompiler import cpp_semantics as sem
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
        return 'cpu().status()'
    if e.special == 'ccr':
        return 'cpu().ccr()'
    if e.special == 'usp':
        return 'cpu().usp'
    raise EAGenError(f'read from special register {e.special}')


def _special_write(e, value):
    if e.special == 'sr':
        return [f'cpu().setStatus(WORD({value}));']
    if e.special == 'ccr':
        return [f'cpu().setCCR(WORD({value}));']
    if e.special == 'usp':
        return [f'cpu().usp = LONG({value});']
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
        return stmts + sem.movea(ea.areg(dst.reg), val, size)
    r = tmp.fresh()
    stmts.append(f'{ea._CTYPE[size]} {r} = {val};')
    stmts += ea.write_ea(dst, size, r, tmp)
    return stmts + sem.move(r, size)


def _moveq(instr, tmp):
    src, dst = instr.eas[0], instr.eas[1]
    r = tmp.fresh()
    imm = src.imm & 0xFF
    return [
        f'm_long {r} = LONG(static_cast<int32_t>(static_cast<int8_t>({imm})));',
        ea.write_dn(dst.reg, 'l', r),
    ] + sem.move(r, 'l')


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
            return s_stmts + sem.cmpa(ar, sval, size, tmp)
        return s_stmts + (sem.adda(ar, sval, size) if op == 'ADD'
                          else sem.suba(ar, sval, size))

    s_stmts, sval = ea.read_ea(src, size, tmp)
    if op == 'CMP':
        d_stmts, dval = ea.read_ea(dst, size, tmp)
        return s_stmts + d_stmts + sem.cmp(dval, sval, size, tmp)
    pre, r, post = ea.rmw_ea(dst, size, tmp)
    op_stmts = sem.add(r, sval, size, tmp) if op == 'ADD' else sem.sub(r, sval, size, tmp)
    return s_stmts + pre + op_stmts + post


def _add(instr, tmp): return _arith(instr, tmp, 'ADD')
def _sub(instr, tmp): return _arith(instr, tmp, 'SUB')
def _cmp(instr, tmp): return _arith(instr, tmp, 'CMP')


def _logic(instr, tmp, op):
    size = _sized(instr)
    src, dst = instr.eas[0], instr.eas[1]
    # andi/ori/eori to SR or CCR.
    if _is_special(dst):
        s_stmts, sval = ea.read_ea(src, 'w', tmp)
        cur = _special_src_expr(dst)
        cxx = {'AND': '&', 'OR': '|', 'EOR': '^'}[op]
        return s_stmts + _special_write(dst, f'({cur} {cxx} {sval})')
    s_stmts, sval = ea.read_ea(src, size, tmp)
    pre, r, post = ea.rmw_ea(dst, size, tmp)
    return s_stmts + pre + sem.logic_op(r, sval, size, op) + post


def _and(instr, tmp): return _logic(instr, tmp, 'AND')
def _or(instr, tmp):  return _logic(instr, tmp, 'OR')
def _eor(instr, tmp): return _logic(instr, tmp, 'EOR')


def _tst(instr, tmp):
    size = _sized(instr)
    stmts, val = ea.read_ea(instr.eas[0], size, tmp)
    return stmts + sem.logical(val, size)


def _clr(instr, tmp):
    size = _sized(instr)
    r = tmp.fresh()
    stmts = [f'{ea._CTYPE[size]} {r} = 0;'] + sem.clr(r, size)
    return stmts + ea.write_ea(instr.eas[0], size, r, tmp)


def _lea(instr, tmp):
    src, dst = instr.eas[0], instr.eas[1]
    setup, addr = ea.address_of(src, tmp)
    return setup + [f'{ea.areg(dst.reg)} = LONG({addr});']


def _pea(instr, tmp):
    setup, addr = ea.address_of(instr.eas[0], tmp)
    return setup + [
        'cpu().ssp -= 4;',
        f'memory().writeLong(cpu().ssp, LONG({addr}));',
    ]


def _unary(instr, tmp, macro):
    """neg / not — read-modify-write a single operand via a no-arg macro."""
    size = _sized(instr)
    pre, r, post = ea.rmw_ea(instr.eas[0], size, tmp)
    op = sem.neg(r, size, tmp) if macro == 'NEG' else sem.not_op(r, size)
    return pre + op + post


def _neg(instr, tmp): return _unary(instr, tmp, 'NEG')
def _not(instr, tmp): return _unary(instr, tmp, 'NOT')


def _swap(instr, tmp):
    n = instr.eas[0].reg
    r = tmp.fresh()
    return [f'm_long {r} = {ea.read_dn(n, "l")};',
            *sem.swap(r),
            ea.write_dn(n, 'l', r)]


def _ext(instr, tmp):
    n = instr.eas[0].reg
    return sem.ext(n, instr.size or 'w', tmp)


def _shift(instr, tmp, macro):
    """Shift/rotate. Forms: '<op> #cnt, Dn' / '<op> Dm, Dn' / '<op> <ea>' (×1)."""
    size = _sized(instr)
    if len(instr.eas) == 1:                       # memory shift, count = 1
        pre, r, post = ea.rmw_ea(instr.eas[0], size, tmp)
        return pre + sem.shift(r, '1', size, macro, tmp) + post
    count, dst = instr.eas[0], instr.eas[1]
    if count.mode == EAMode.IMMEDIATE:
        setup, cnt = [], str((count.imm - 1) % 8 + 1)  # immediate count is 1..8
    else:
        # Register count: Dn mod 64; a count of zero shifts nothing.
        setup, cnt = sem.reg_shift_count(count.reg, tmp)
    pre, r, post = ea.rmw_ea(dst, size, tmp)
    return setup + pre + \
        sem.shift(r, cnt, size, macro, tmp,
                  count_may_be_zero=count.mode != EAMode.IMMEDIATE) + post


def _muldiv(instr, tmp, macro):
    """mulu/muls (16×16→Dn long) and divu/divs (Dn 32 ÷ src16 → Dn)."""
    src, dst = instr.eas[0], instr.eas[1]
    s_stmts, sval = ea.read_ea(src, 'w', tmp)
    if macro.startswith('MUL'):
        dexpr = ea.read_dn(dst.reg, 'w')
    else:
        dexpr = ea.read_dn(dst.reg, 'l')
    op_stmts, result = sem.muldiv(dexpr, sval, macro, tmp)
    return s_stmts + op_stmts + [ea.write_dn(dst.reg, 'l', result)]


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
        return stmts + sem.bitop(val, bit, kind, size)
    pre, r, post = ea.rmw_ea(dst, size, tmp)
    return pre + sem.bitop(r, bit, kind, size) + post


def _scc(instr, tmp, cc):
    r = tmp.fresh()
    stmts = [f'm_byte {r} = 0;', *sem.scc(r, cc)]
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
    t = tmp.fresh()
    return [f'm_long {t} = {a};', f'{a} = {b};', f'{b} = {t};']


def _bcd(instr, tmp, macro):
    src, dst = instr.eas[0], instr.eas[1]
    s_stmts, sval = ea.read_ea(src, 'b', tmp)
    pre, r, post = ea.rmw_ea(dst, 'b', tmp)
    return s_stmts + pre + sem.bcd(r, sval, macro, tmp) + post


def _nbcd(instr, tmp):
    pre, r, post = ea.rmw_ea(instr.eas[0], 'b', tmp)
    return pre + sem.nbcd(r, tmp) + post


def _negx(instr, tmp):
    size = _sized(instr)
    pre, r, post = ea.rmw_ea(instr.eas[0], size, tmp)
    return pre + sem.negx(r, size, tmp) + post


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
                         f'BYTE((cpu().d[{dn}] >> {sh}) & 0xFFu));')
        return stmts
    else:                                    # mem → reg
        dn = dst.reg
        setup, base = ea.address_of(src, tmp)
        b = tmp.fresh()
        stmts = setup + [f'm_long {b} = {base};']
        if size == 'l':
            stmts.append(
                f'cpu().d[{dn}] = '
                f'(LONG(memory().readByte({b})) << 24) | '
                f'(LONG(memory().readByte({b} + 2)) << 16) | '
                f'(LONG(memory().readByte({b} + 4)) << 8) | '
                f'LONG(memory().readByte({b} + 6));'
            )
        else:
            stmts.append(
                f'cpu().d[{dn}] = (cpu().d[{dn}] & 0xFFFF0000u) | '
                f'(LONG(memory().readByte({b})) << 8) | '
                f'LONG(memory().readByte({b} + 2));'
            )
        return stmts


def _nop(instr, tmp):
    return ['(void)0;']


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
