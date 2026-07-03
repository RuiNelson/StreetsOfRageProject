"""C++ statement snippets for 68000 opcode semantics.

The recompiler emits these semantics directly into ``Sor.cpp``. The only
generated macros are the one-line cast shorthands below, kept as a small visual
aid for otherwise noisy ``static_cast`` expressions.
"""

from tools.recompiler import ea_codegen as ea

CAST_MACROS = r'''
#define BYTE(v) static_cast<m_byte>(v)
#define WORD(v) static_cast<m_word>(v)
#define LONG(v) static_cast<m_long>(v)
#define BEFORE_INSTRUCTION if (irqLevel() > cpu().interruptMask()) serviceIRQ(); pace();
'''

_SIGN = {'b': '0x80u', 'w': '0x8000u', 'l': '0x80000000u'}
_CARRY = {'b': '0x100u', 'w': '0x10000u', 'l': '0x100000000ull'}
_CTYPE = ea._CTYPE
_FULL = {'b': 'm_word', 'w': 'm_long', 'l': 'uint64_t'}
_CAST = {'b': 'BYTE', 'w': 'WORD', 'l': 'LONG'}
_WIDEN = {'b': 'WORD', 'w': 'LONG'}
_MASK = {'b': '0xFFu', 'w': '0xFFFFu', 'l': '0xFFFFFFFFu'}
_NBITS = {'b': 8, 'w': 16, 'l': 32}


def _wide(size: str, expr: str) -> str:
    if size == 'l':
        return f'static_cast<uint64_t>({expr})'
    return f'{_WIDEN[size]}({expr})'


_FLAG = {
    'c': 'cpu().flagC()', 'v': 'cpu().flagV()', 'z': 'cpu().flagZ()',
    'n': 'cpu().flagN()', 'x': 'cpu().flagX()',
}
_FLAG_BIT = {
    'c': 'CPU68K::FlagC', 'v': 'CPU68K::FlagV', 'z': 'CPU68K::FlagZ',
    'n': 'CPU68K::FlagN', 'x': 'CPU68K::FlagX',
}


def flag(name: str) -> str:
    return _FLAG[name.lower()]


def set_flag(name: str, value: str) -> str:
    bit = _FLAG_BIT[name.lower()]
    return f'cpu().setFlag({bit}, {value});'


def int_level() -> str:
    return 'cpu().interruptMask()'


def cc_expr(cc: int) -> str:
    return f'cpu().condition({cc})'


def set_nzvc(value: str, size: str, v: str = 'false', c: str = 'false',
             x: str | None = None) -> list[str]:
    """Update N/Z/V/C and optionally X through compact CPU68K helpers."""
    sign = _SIGN[size]
    if v == 'false' and c == 'false' and x in (None, 'false'):
        return [f'cpu().setNZClearVC({value}, {sign});']
    if x is None:
        return [f'cpu().setNZVC({value}, {sign}, {v}, {c});']
    return [f'cpu().setNZVCX({value}, {sign}, {v}, {c}, {x});']


def logical(value: str, size: str) -> list[str]:
    return set_nzvc(value, size)


def move(value: str, size: str) -> list[str]:
    return logical(value, size)


def add(dst: str, src: str, size: str, tmp) -> list[str]:
    old, sval, full, cy, ov = (tmp.fresh() for _ in range(5))
    return [
        f'{_CTYPE[size]} {old} = {dst};',
        f'{_CTYPE[size]} {sval} = {src};',
        f'{_FULL[size]} {full} = {_wide(size, old)} + {_wide(size, sval)};',
        f'{dst} = {_CAST[size]}({full});',
        f'bool {cy} = ({full} & {_CARRY[size]}) != 0;',
        f'bool {ov} = ((~({old} ^ {sval}) & ({old} ^ {dst})) & {_SIGN[size]}) != 0;',
        *set_nzvc(dst, size, ov, cy, x=cy),
    ]


def sub(dst: str, src: str, size: str, tmp) -> list[str]:
    old, sval, full, cy, ov = (tmp.fresh() for _ in range(5))
    return [
        f'{_CTYPE[size]} {old} = {dst};',
        f'{_CTYPE[size]} {sval} = {src};',
        f'{_FULL[size]} {full} = {_wide(size, old)} - {_wide(size, sval)};',
        f'{dst} = {_CAST[size]}({full});',
        f'bool {cy} = ({full} & {_CARRY[size]}) != 0;',
        f'bool {ov} = ((({old} ^ {sval}) & ({old} ^ {dst})) & {_SIGN[size]}) != 0;',
        *set_nzvc(dst, size, ov, cy, x=cy),
    ]


def cmp(dst: str, src: str, size: str, tmp) -> list[str]:
    dval, sval, full, result, cy, ov = (tmp.fresh() for _ in range(6))
    return [
        f'{_CTYPE[size]} {dval} = {dst};',
        f'{_CTYPE[size]} {sval} = {src};',
        f'{_FULL[size]} {full} = {_wide(size, dval)} - {_wide(size, sval)};',
        f'{_CTYPE[size]} {result} = {_CAST[size]}({full});',
        f'bool {cy} = ({full} & {_CARRY[size]}) != 0;',
        f'bool {ov} = ((({dval} ^ {sval}) & ({dval} ^ {result})) & {_SIGN[size]}) != 0;',
        *set_nzvc(result, size, ov, cy),
    ]


def signext_to_long(value: str, size: str) -> str:
    return ea.signext_to_long(value, size)


def _addr_operand(src: str, size: str) -> str:
    """Source operand of an An-destination op: word forms sign-extend to 32 bits."""
    return signext_to_long(src, size) if size == 'w' else f'LONG({src})'


def movea(dst: str, src: str, size: str) -> list[str]:
    return [f'{dst} = {_addr_operand(src, size)};']


def adda(dst: str, src: str, size: str) -> list[str]:
    return [f'{dst} = LONG({dst} + {_addr_operand(src, size)});']


def suba(dst: str, src: str, size: str) -> list[str]:
    return [f'{dst} = LONG({dst} - {_addr_operand(src, size)});']


def cmpa(dst: str, src: str, size: str, tmp) -> list[str]:
    return cmp(dst, _addr_operand(src, size), 'l', tmp)


def logic_op(dst: str, src: str, size: str, op: str) -> list[str]:
    c_op = {'AND': '&', 'OR': '|', 'EOR': '^'}[op]
    return [
        f'{dst} = {_CAST[size]}({dst} {c_op} {_CAST[size]}({src}));',
        *logical(dst, size),
    ]


def clr(dst: str, size: str) -> list[str]:
    return [f'{dst} = 0;', *logical(dst, size)]


def neg(dst: str, size: str, tmp) -> list[str]:
    old, full, cy, ov = (tmp.fresh() for _ in range(4))
    return [
        f'{_CTYPE[size]} {old} = {dst};',
        f'{_FULL[size]} {full} = {_wide(size, "0")} - {_wide(size, old)};',
        f'{dst} = {_CAST[size]}({full});',
        f'bool {cy} = ({full} & {_CARRY[size]}) != 0;',
        f'bool {ov} = (({old} & {dst}) & {_SIGN[size]}) != 0;',
        *set_nzvc(dst, size, ov, cy, x=cy),
    ]


def not_op(dst: str, size: str) -> list[str]:
    return [f'{dst} = {_CAST[size]}(~{dst});', *logical(dst, size)]


def swap(dst: str) -> list[str]:
    return [
        f'{dst} = LONG(({dst} >> 16) | ({dst} << 16));',
        *logical(dst, 'l'),
    ]


def ext(reg: int, size: str, tmp) -> list[str]:
    v = tmp.fresh()
    if size == 'l':
        return [
            f'm_long {v} = LONG(static_cast<int32_t>(static_cast<int16_t>(cpu().d[{reg}] & 0xFFFFu)));',
            f'cpu().d[{reg}] = {v};',
            *logical(v, 'l'),
        ]
    return [
        f'm_word {v} = WORD(static_cast<int16_t>(static_cast<int8_t>(cpu().d[{reg}] & 0xFFu)));',
        f'cpu().d[{reg}] = LONG((cpu().d[{reg}] & 0xFFFF0000u) | LONG({v}));',
        *logical(v, 'w'),
    ]


def bitop(dst: str, bit: str, kind: str, size: str) -> list[str]:
    cast = _CAST[size]
    out = [set_flag('z', f'((LONG({dst}) >> ({bit})) & 1u) == 0')]
    if kind == 'BSET':
        out.append(f'{dst} = {cast}({dst} | (1u << ({bit})));')
    elif kind == 'BCLR':
        out.append(f'{dst} = {cast}({dst} & ~(1u << ({bit})));')
    elif kind == 'BCHG':
        out.append(f'{dst} = {cast}({dst} ^ (1u << ({bit})));')
    return out


def reg_shift_count(reg: int, tmp) -> tuple[list[str], str]:
    """Register shift count: Dn mod 64; a count of zero shifts nothing."""
    name = tmp.fresh()
    return [f'int {name} = static_cast<int>(cpu().d[{reg}] & 63);'], name


def shift(dst: str, count: str, size: str, kind: str, tmp,
          count_may_be_zero: bool = False) -> list[str]:
    v, c, ov = tmp.fresh(), tmp.fresh(), tmp.fresh()
    cast = _CAST[size]
    mask = _MASK[size]
    sign = _SIGN[size]
    top = _NBITS[size] - 1
    out = [
        f'm_long {v} = LONG({cast}({dst}));',
        f'bool {c} = false;',
        f'bool {ov} = false;',
    ]
    if kind in ('ROXL', 'ROXR'):
        x = tmp.fresh()
        out.append(f'bool {x} = {flag("x")};')
        if kind == 'ROXL':
            body = (f'm_long ms_ = ({v} >> {top}) & 1u; '
                    f'{v} = (({v} << 1) | ({x} ? 1u : 0u)) & {mask}; '
                    f'{x} = ms_ != 0;')
        else:
            body = (f'm_long ls_ = {v} & 1u; '
                    f'{v} = (({v} >> 1) | (({x} ? 1u : 0u) << {top})) & {mask}; '
                    f'{x} = ls_ != 0;')
        out += [
            f'for (int i_ = 0; i_ < static_cast<int>({count}); ++i_) {{ {body} }}',
            f'cpu().setVCX(false, {x}, {x});',
        ]
    else:
        bodies = {
            'LSL': f'{c} = ({v} & {sign}) != 0; {v} = ({v} << 1) & {mask};',
            'LSR': f'{c} = ({v} & 1u) != 0; {v} >>= 1;',
            'ASL': (f'm_long sg_ = {v} & {sign}; {c} = sg_ != 0; '
                    f'{v} = ({v} << 1) & {mask}; '
                    f'if (({v} & {sign}) != sg_) {ov} = true;'),
            'ASR': (f'm_long sg_ = {v} & {sign}; {c} = ({v} & 1u) != 0; '
                    f'{v} = (({v} >> 1) | sg_) & {mask};'),
            'ROL': (f'm_long ms_ = ({v} >> {top}) & 1u; '
                    f'{v} = (({v} << 1) | ms_) & {mask}; {c} = ms_ != 0;'),
            'ROR': (f'm_long ls_ = {v} & 1u; '
                    f'{v} = (({v} >> 1) | (ls_ << {top})) & {mask}; {c} = ls_ != 0;'),
        }
        out.append(
            f'for (int i_ = 0; i_ < static_cast<int>({count}); ++i_) {{ {bodies[kind]} }}')
        if kind in ('LSL', 'LSR', 'ASL', 'ASR'):
            if count_may_be_zero:
                # Count 0: C and V are cleared but X is unchanged.
                out.append(f'cpu().setVC({ov}, {c});')
                out.append(f'if ({count} != 0) cpu().setFlagX({c});')
            else:
                out.append(f'cpu().setVCX({ov}, {c}, {c});')
        else:
            out.append(f'cpu().setVC(false, {c});')
    out += [
        f'cpu().setNZ({v}, {sign});',
        f'{dst} = {cast}({v});',
    ]
    return out


def muldiv(dst_expr: str, src_expr: str, macro: str, tmp) -> tuple[list[str], str]:
    r = tmp.fresh()
    if macro == 'MULU':
        out = [f'm_long {r} = LONG(WORD({dst_expr})) * LONG(WORD({src_expr}));']
    elif macro == 'MULS':
        out = [
            f'int32_t {r}_p = static_cast<int32_t>(static_cast<int16_t>(WORD({dst_expr}))) * '
            f'static_cast<int32_t>(static_cast<int16_t>(WORD({src_expr})));',
            f'm_long {r} = LONG({r}_p);',
        ]
    elif macro == 'DIVU':
        s, q, rem = tmp.fresh(), tmp.fresh(), tmp.fresh()
        out = [
            f'm_word {s} = WORD({src_expr});',
            f'm_long {r} = LONG({dst_expr});',
            f'if ({s} != 0) {{',
            f'    m_long {q} = LONG({dst_expr}) / {s};',
            f'    m_long {rem} = LONG({dst_expr}) % {s};',
            f'    if ({q} > 0xFFFFu) {{',
            f'        {set_flag("v", "true")}',
            f'        {set_flag("c", "false")}',
            f'    }} else {{',
            f'        {r} = LONG(({rem} << 16) | ({q} & 0xFFFFu));',
            f'        {set_flag("v", "false")}',
            f'        {set_flag("c", "false")}',
            f'        {set_flag("n", f"(WORD({q}) & 0x8000u) != 0")}',
            f'        {set_flag("z", f"WORD({q}) == 0")}',
            f'    }}',
            f'}}',
        ]
        return out, r
    else:
        s, d, q, rem = tmp.fresh(), tmp.fresh(), tmp.fresh(), tmp.fresh()
        out = [
            f'int16_t {s} = static_cast<int16_t>(WORD({src_expr}));',
            f'm_long {r} = LONG({dst_expr});',
            f'if ({s} != 0) {{',
            f'    int32_t {d} = static_cast<int32_t>(LONG({dst_expr}));',
            # INT32_MIN / -1 overflows before the quotient check (UB in C++).
            f'    if ({d} == INT32_MIN && {s} == -1) {{',
            f'        {set_flag("v", "true")}',
            f'        {set_flag("c", "false")}',
            f'    }} else {{',
            f'        int32_t {q} = {d} / {s};',
            f'        int32_t {rem} = {d} % {s};',
            f'        if ({q} > 32767 || {q} < -32768) {{',
            f'            {set_flag("v", "true")}',
            f'            {set_flag("c", "false")}',
            f'        }} else {{',
            f'            {r} = LONG((LONG({rem} & 0xFFFF) << 16) | (LONG({q}) & 0xFFFFu));',
            f'            {set_flag("v", "false")}',
            f'            {set_flag("c", "false")}',
            f'            {set_flag("n", f"(WORD({q}) & 0x8000u) != 0")}',
            f'            {set_flag("z", f"WORD({q}) == 0")}',
            f'        }}',
            f'    }}',
            f'}}',
        ]
        return out, r
    out += [*logical(r, 'l')]
    return out, r


def scc(dst: str, cc: int) -> list[str]:
    return [f'{dst} = {cc_expr(cc)} ? BYTE(0xFF) : BYTE(0);']


def bcd(dst: str, src: str, kind: str, tmp) -> list[str]:
    x, lo, hi, carry, outv = (tmp.fresh() for _ in range(5))
    if kind == 'ABCD':
        calc = [
            f'int {lo} = ({dst} & 0x0F) + ({src} & 0x0F) + {x};',
            f'int {hi} = ({dst} >> 4) + ({src} >> 4);',
            f'int {carry} = 0;',
            f'if ({lo} > 9) {{ {lo} -= 10; ++{hi}; }}',
            f'if ({hi} > 9) {{ {hi} -= 10; {carry} = 1; }}',
        ]
    else:
        calc = [
            f'int {lo} = ({dst} & 0x0F) - ({src} & 0x0F) - {x};',
            f'int {hi} = ({dst} >> 4) - ({src} >> 4);',
            f'int {carry} = 0;',
            f'if ({lo} < 0) {{ {lo} += 10; --{hi}; }}',
            f'if ({hi} < 0) {{ {hi} += 10; {carry} = 1; }}',
        ]
    return [
        f'int {x} = {flag("x")} ? 1 : 0;',
        *calc,
        f'm_byte {outv} = BYTE((({hi} & 0x0F) << 4) | ({lo} & 0x0F));',
        set_flag('c', f'{carry} != 0'),
        set_flag('x', f'{carry} != 0'),
        f'if ({outv} != 0) {set_flag("z", "false")}',
        set_flag('n', f'({outv} & 0x80u) != 0'),
        f'{dst} = {outv};',
    ]


def nbcd(dst: str, tmp) -> list[str]:
    x, lo, hi, carry, outv, src = (tmp.fresh() for _ in range(6))
    return [
        f'int {x} = {flag("x")} ? 1 : 0;',
        f'm_byte {src} = BYTE({dst});',
        f'int {lo} = -({src} & 0x0F) - {x};',
        f'int {hi} = -({src} >> 4);',
        f'int {carry} = 0;',
        f'if ({lo} < 0) {{ {lo} += 10; --{hi}; }}',
        f'if ({hi} < 0) {{ {hi} += 10; {carry} = 1; }}',
        f'm_byte {outv} = BYTE((({hi} & 0x0F) << 4) | ({lo} & 0x0F));',
        set_flag('c', f'{carry} != 0'),
        set_flag('x', f'{carry} != 0'),
        f'if ({outv} != 0) {set_flag("z", "false")}',
        set_flag('n', f'({outv} & 0x80u) != 0'),
        f'{dst} = {outv};',
    ]


def negx(dst: str, size: str, tmp) -> list[str]:
    x, full, outv, borrow, old = (tmp.fresh() for _ in range(5))
    return [
        f'int {x} = {flag("x")} ? 1 : 0;',
        f'{_CTYPE[size]} {old} = {dst};',
        f'{_FULL[size]} {full} = {_wide(size, "0")} - {_wide(size, old)} - {x};',
        f'{_CTYPE[size]} {outv} = {_CAST[size]}({full});',
        f'bool {borrow} = ({full} & {_CARRY[size]}) != 0;',
        f'if ({outv} != 0) {set_flag("z", "false")}',
        set_flag('n', f'({outv} & {_SIGN[size]}) != 0'),
        set_flag('v', f'(({old} & {outv}) & {_SIGN[size]}) != 0'),
        set_flag('c', borrow),
        set_flag('x', borrow),
        f'{dst} = {outv};',
    ]
