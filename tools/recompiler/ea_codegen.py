"""Effective-address → C++ expression generation.

Translates one structured :class:`EA` (from the disassembler) into C++ that
reads it, writes it, or computes its address — emitting **temporaries** so that
addressing-mode side effects (``(An)+`` post-increment, ``-(An)`` pre-decrement)
are sequenced correctly even when the same register appears in both operands
(``move.l (a0)+,(a0)+``).

Conventions of the emitted code
-------------------------------
* Data registers are reached through ``cpu().d[n]`` with explicit sub-field
  masking on read and merge-on-write for byte/word.
* Address registers use ``cpu().a[n]`` / ``cpu().ssp`` (A7); word writes sign-
  extend to 32 bits (movea / lea rule).
* Memory is reached through ``memory()`` (``SystemMemory``):
  ``readByte/Word/Long`` and ``writeByte/Word/Long``. ``SystemMemory`` masks
  every address to 24 bits, so the generator never masks.
"""

from tools.disassembler.instruction import EA, EAMode

SIZE_BYTES = {'b': 1, 'w': 2, 'l': 4}
_READ_FN   = {'b': 'readByte',  'w': 'readWord',  'l': 'readLong'}
_WRITE_FN  = {'b': 'writeByte', 'w': 'writeWord', 'l': 'writeLong'}
_CTYPE     = {'b': 'm_byte', 'w': 'm_word', 'l': 'm_long'}
_CAST      = {'b': 'BYTE', 'w': 'WORD', 'l': 'LONG'}


class EAGenError(Exception):
    """An EA that this generator cannot translate (e.g. RAW fallback)."""


class TempPool:
    """Hands out unique temporary names within one instruction's emission."""

    def __init__(self, addr: int) -> None:
        self._prefix = f't{addr:06x}_'
        self._n = 0

    def fresh(self) -> str:
        name = f'{self._prefix}{self._n}'
        self._n += 1
        return name


def _hex(value: int) -> str:
    """Format an unsigned 32-bit constant as a compact C++ hex literal."""
    v = value & 0xFFFFFFFF
    if v <= 0xFF:
        return f'0x{v:02X}u'
    if v <= 0xFFFF:
        return f'0x{v:04X}u'
    return f'0x{v:08X}u'


def areg(n: int) -> str:
    """Lvalue for address register An. A7 is the supervisor stack pointer."""
    return 'cpu().ssp' if n == 7 else f'cpu().a[{n}]'


def addr_step(reg: int, size: str) -> int:
    """Predecrement/postincrement step; byte accesses on A7 move by two."""
    if reg == 7 and size == 'b':
        return 2
    return SIZE_BYTES[size]


def read_dn(n: int, size: str) -> str:
    """Expression reading Dn at byte / word / long width."""
    if size == 'b':
        return f'BYTE(cpu().d[{n}] & 0xFFu)'
    if size == 'w':
        return f'WORD(cpu().d[{n}] & 0xFFFFu)'
    return f'cpu().d[{n}]'


def write_dn(n: int, size: str, value: str) -> str:
    """Statement writing ``value`` into Dn, preserving untouched high bits."""
    if size == 'b':
        return (f'cpu().d[{n}] = LONG((cpu().d[{n}] & 0xFFFFFF00u) '
                f'| LONG(BYTE({value})));')
    if size == 'w':
        return (f'cpu().d[{n}] = LONG((cpu().d[{n}] & 0xFFFF0000u) '
                f'| LONG(WORD({value})));')
    return f'cpu().d[{n}] = LONG({value});'


def write_areg_word(ar: str, value: str) -> str:
    """Word write to An — sign-extend bit 15 (movea / lea)."""
    return (f'{ar} = LONG(static_cast<int32_t>('
            f'static_cast<int16_t>(WORD({value}))));')


def write_areg_long(ar: str, value: str) -> str:
    return f'{ar} = LONG({value});'


def signext_to_long(expr: str, size: str) -> str:
    if size == 'l':
        return expr
    if size == 'w':
        return (f'LONG(static_cast<int32_t>('
                f'static_cast<int16_t>(WORD({expr}))))')
    return (f'LONG(static_cast<int32_t>('
            f'static_cast<int8_t>(BYTE({expr}))))')


def _index_expr(ea: EA) -> str:
    """C++ expression for the (sign-extended) index register of an indexed EA."""
    reg = areg(ea.index_reg) if ea.index_is_addr else f'cpu().d[{ea.index_reg}]'
    if ea.index_size == 'w':
        return (f'LONG(static_cast<int32_t>('
                f'static_cast<int16_t>(WORD({reg} & 0xFFFFu))))')
    return reg


def address_of(ea: EA, tmp: TempPool) -> tuple[list[str], str]:
    """Return (setup statements, address expression) for a memory EA."""
    if ea.mode == EAMode.ADDR_IND:
        return [], areg(ea.reg)
    if ea.mode == EAMode.ADDR_DISP:
        return [], f'({areg(ea.reg)} + {ea.disp})'
    if ea.mode == EAMode.ADDR_INDEX:
        return [], f'({areg(ea.reg)} + {ea.disp} + {_index_expr(ea)})'
    if ea.mode == EAMode.ABS_W:
        v = ea.abs_value & 0xFFFF
        return [], _hex(v | 0xFFFF0000 if (v & 0x8000) else v)
    if ea.mode == EAMode.ABS_L:
        return [], _hex(ea.abs_value)
    if ea.mode == EAMode.PC_DISP:
        return [], _hex(ea.abs_value)
    if ea.mode == EAMode.PC_INDEX:
        return [], f'({_hex(ea.abs_value)} + {_index_expr(ea)})'
    raise EAGenError(f'address_of: mode {ea.mode} has no address')


def read_ea(ea: EA, size: str, tmp: TempPool) -> tuple[list[str], str]:
    """Return (setup statements, value expression) reading ``ea`` at ``size``."""
    if ea.mode == EAMode.DATA_REG:
        return [], read_dn(ea.reg, size)

    if ea.mode == EAMode.ADDR_REG:
        if size == 'l':
            return [], areg(ea.reg)
        if size == 'w':
            return [], f'WORD({areg(ea.reg)} & 0xFFFFu)'
        return [], f'BYTE({areg(ea.reg)} & 0xFFu)'

    if ea.mode == EAMode.IMMEDIATE:
        return [], f'{_CAST[size]}({_hex(ea.imm)})'

    if ea.mode == EAMode.ADDR_POSTINC:
        v = tmp.fresh()
        step = addr_step(ea.reg, size)
        stmts = [
            f'{_CTYPE[size]} {v} = memory().{_READ_FN[size]}({areg(ea.reg)});',
            f'{areg(ea.reg)} += {step};',
        ]
        return stmts, v

    if ea.mode == EAMode.ADDR_PREDEC:
        v = tmp.fresh()
        step = addr_step(ea.reg, size)
        stmts = [
            f'{areg(ea.reg)} -= {step};',
            f'{_CTYPE[size]} {v} = memory().{_READ_FN[size]}({areg(ea.reg)});',
        ]
        return stmts, v

    setup, addr = address_of(ea, tmp)
    v = tmp.fresh()
    setup = list(setup)
    setup.append(f'{_CTYPE[size]} {v} = memory().{_READ_FN[size]}({addr});')
    return setup, v


def rmw_ea(ea: EA, size: str, tmp: TempPool) -> tuple[list[str], str, list[str]]:
    """Read-modify-write access: (pre, value_temp, post)."""
    if ea.mode == EAMode.DATA_REG:
        v = tmp.fresh()
        return ([f'{_CTYPE[size]} {v} = {read_dn(ea.reg, size)};'],
                v, [write_dn(ea.reg, size, v)])

    if ea.mode == EAMode.ADDR_REG:
        # No 68000 opcode does a byte/word read-modify-write on An.
        if size != 'l':
            raise EAGenError(f'{size}-size read-modify-write on an address register')
        v = tmp.fresh()
        return ([f'm_long {v} = {areg(ea.reg)};'],
                v, [write_areg_long(areg(ea.reg), v)])

    bytes_ = (
        addr_step(ea.reg, size)
        if ea.mode in (EAMode.ADDR_POSTINC, EAMode.ADDR_PREDEC)
        else SIZE_BYTES[size]
    )
    addr = tmp.fresh()
    v = tmp.fresh()
    if ea.mode == EAMode.ADDR_POSTINC:
        pre = [f'm_long {addr} = {areg(ea.reg)};',
               f'{_CTYPE[size]} {v} = memory().{_READ_FN[size]}({addr});']
        post = [f'memory().{_WRITE_FN[size]}({addr}, {v});',
                f'{areg(ea.reg)} += {bytes_};']
        return pre, v, post
    if ea.mode == EAMode.ADDR_PREDEC:
        pre = [f'{areg(ea.reg)} -= {bytes_};',
               f'm_long {addr} = {areg(ea.reg)};',
               f'{_CTYPE[size]} {v} = memory().{_READ_FN[size]}({addr});']
        post = [f'memory().{_WRITE_FN[size]}({addr}, {v});']
        return pre, v, post

    setup, aexpr = address_of(ea, tmp)
    pre = setup + [f'm_long {addr} = {aexpr};',
                   f'{_CTYPE[size]} {v} = memory().{_READ_FN[size]}({addr});']
    post = [f'memory().{_WRITE_FN[size]}({addr}, {v});']
    return pre, v, post


def write_ea(ea: EA, size: str, value: str, tmp: TempPool) -> list[str]:
    """Return statements writing ``value`` into ``ea`` at ``size``."""
    if ea.mode == EAMode.DATA_REG:
        return [write_dn(ea.reg, size, value)]

    if ea.mode == EAMode.ADDR_REG:
        # No 68000 opcode writes a byte to An; word writes sign-extend (movea).
        if size == 'b':
            raise EAGenError('byte write to an address register')
        if size == 'l':
            return [write_areg_long(areg(ea.reg), value)]
        return [write_areg_word(areg(ea.reg), value)]

    if ea.mode == EAMode.ADDR_POSTINC:
        step = addr_step(ea.reg, size)
        return [
            f'memory().{_WRITE_FN[size]}({areg(ea.reg)}, {value});',
            f'{areg(ea.reg)} += {step};',
        ]

    if ea.mode == EAMode.ADDR_PREDEC:
        step = addr_step(ea.reg, size)
        return [
            f'{areg(ea.reg)} -= {step};',
            f'memory().{_WRITE_FN[size]}({areg(ea.reg)}, {value});',
        ]

    if ea.mode in (EAMode.IMMEDIATE, EAMode.PC_DISP, EAMode.PC_INDEX):
        raise EAGenError(f'{ea.mode} is not a writable destination')

    setup, addr = address_of(ea, tmp)
    return setup + [f'memory().{_WRITE_FN[size]}({addr}, {value});']
