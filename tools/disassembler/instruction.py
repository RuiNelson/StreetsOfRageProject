"""Data types for decoded 68000 instructions.

Structured effective addresses (EA)
===================================
In addition to the human-readable ``Instruction.operands`` list (a mix of
formatted strings and :class:`Addr` objects, consumed byte-for-byte by
:class:`AsmFormatter`), every instruction also carries a parallel
``Instruction.eas`` list of :class:`EA` objects.  An :class:`EA` is the
*structured* form of one operand — addressing mode, register number(s),
displacement, index register/size, immediate value and any decode-time
resolved absolute address.  This is what the C++ recompiler consumes; it
never has to reparse the symbolized operand strings.

The two representations are kept strictly in sync: ``eas[i]`` is the
structured form of ``operands[i]``.

Coverage
--------
**Fully structured** (mode + all relevant fields populated):

* data register direct ``Dn``                 → :attr:`EAMode.DATA_REG`
* address register direct ``An`` / ``sp``     → :attr:`EAMode.ADDR_REG`
* address register indirect ``(An)``          → :attr:`EAMode.ADDR_IND`
* postincrement ``(An)+``                      → :attr:`EAMode.ADDR_POSTINC`
* predecrement ``-(An)``                       → :attr:`EAMode.ADDR_PREDEC`
* displacement ``d16(An)``                     → :attr:`EAMode.ADDR_DISP`
* indexed ``d8(An,Xn.sz)``                     → :attr:`EAMode.ADDR_INDEX`
* absolute short ``(xxx).w``                   → :attr:`EAMode.ABS_W`
* absolute long ``(xxx).l``                    → :attr:`EAMode.ABS_L`
* PC-relative ``d16(PC)`` (resolved abs)       → :attr:`EAMode.PC_DISP`
* PC-indexed ``d8(PC,Xn.sz)`` (resolved abs)   → :attr:`EAMode.PC_INDEX`
* immediate ``#imm``                           → :attr:`EAMode.IMMEDIATE`
* branch/jump target (resolved abs)            → :attr:`EAMode.BRANCH_TARGET`
* register list (movem)                        → :attr:`EAMode.REG_LIST`
* special registers ``sr`` / ``ccr`` / ``usp`` → :attr:`EAMode.SPECIAL_REG`

**Fallback** (mode :attr:`EAMode.RAW`, with the original text in
:attr:`EA.raw`): any operand string the structured converter does not
recognize.  In practice this should not occur for the Streets of Rage ROM;
it exists so the conversion is total and never crashes the decoder.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Union


class FlowType(Enum):
    """How the disassembler should continue after this instruction.

    Used by :class:`Disassembler` to decide whether to follow a target,
    continue sequentially, or stop tracing this path.
    """
    SEQUENTIAL   = auto()   # Execution continues to next instruction
    CALL         = auto()   # Subroutine call — follow target, then continue sequentially
    BRANCH       = auto()   # Unconditional jump — follow target, stop this path
    CONDITIONAL  = auto()   # Conditional branch — follow both target and fall-through
    RETURN       = auto()   # RTS/RTE/RTR/ILLEGAL — stop this path


@dataclass
class Addr:
    """An address operand whose value is known at decode time.

    The :class:`Disassembler` stores the concrete 32-bit target address so
    it can recursively follow JSR/JMP/Bcc paths.  The :class:`AsmFormatter`
    converts this to a label name when a corresponding ``sub_`` or ``loc_``
    marker exists, otherwise to a raw ``$XXXXXX`` hex string.

    Attributes
    ----------
    value:
        Absolute 32-bit target address resolved from the instruction.
    form:
        How the address is encoded in the instruction word:

        :``branch``:     Plain label — BRA/BSR/Bcc/DBcc PC-relative displacement.
                         The displacement has already been applied to produce
                         the absolute ``value``.
        :``abs_w``:      ``(xxx).w`` — 16-bit absolute short, sign-extended.
        :``abs_l``:      ``(xxx).l`` — 32-bit absolute long.
        :``pc_rel``:     ``d16(PC)`` — PC-relative with 16-bit displacement.
        :``pc_rel_idx``: ``d8(PC,Xn.sz)`` — PC-relative with index and 8-bit
                         displacement.  The index register is carried in
                         ``suffix`` (e.g. ``d0.w``).
    suffix:
        For ``pc_rel_idx`` only — the index register and size,
        e.g. ``d0.w`` or ``a5.l``.  Empty for all other forms.
    """
    value:  int
    form:   str
    suffix: str = ''


class EAMode(Enum):
    """The 68000 effective-address taxonomy, plus a few non-EA operand kinds.

    The first eleven members are the eleven canonical 68000 addressing modes.
    The remaining members cover operand shapes that are not classic EAs but
    still appear in the operand list (branch targets, register lists, special
    registers) plus a total-conversion fallback.
    """

    # --- the eleven 68000 addressing modes ---
    DATA_REG      = auto()   # Dn
    ADDR_REG      = auto()   # An  (a0..a6, sp==a7)
    ADDR_IND      = auto()   # (An)
    ADDR_POSTINC  = auto()   # (An)+
    ADDR_PREDEC   = auto()   # -(An)
    ADDR_DISP     = auto()   # d16(An)
    ADDR_INDEX    = auto()   # d8(An,Xn.sz)
    ABS_W         = auto()   # (xxx).w   — absolute short
    ABS_L         = auto()   # (xxx).l   — absolute long
    PC_DISP       = auto()   # d16(PC)   — resolved abs in `abs_value`
    PC_INDEX      = auto()   # d8(PC,Xn.sz) — resolved abs in `abs_value`
    IMMEDIATE     = auto()   # #imm

    # --- non-EA operand kinds carried alongside the classic modes ---
    BRANCH_TARGET = auto()   # Bcc/BSR/BRA/DBcc PC-relative target (resolved abs)
    REG_LIST      = auto()   # movem register list, e.g. 'd0-d7/a0-a5'
    SPECIAL_REG   = auto()   # sr / ccr / usp

    # --- fallback ---
    RAW           = auto()   # unrecognized — original text preserved in `raw`


@dataclass
class EA:
    """A structured 68000 effective-address (or operand) for the recompiler.

    Exactly one of the address-related fields is meaningful for any given
    :attr:`mode`; the rest stay at their defaults.

    Attributes
    ----------
    mode:
        The addressing-mode tag (:class:`EAMode`).
    reg:
        Primary register number.  For ``Dn`` / ``An`` / all ``(An)`` forms
        this is the register index 0–7 (``sp`` → 7).  ``None`` when the mode
        has no base register (absolute, immediate, branch target, …).
    size:
        Operand size ``'b'`` / ``'w'`` / ``'l'`` when known, else ``None``.
        (For most EAs this mirrors the instruction's size; for branch targets
        it is the branch-displacement size ``'s'`` / ``'w'`` when relevant.)
    disp:
        Signed displacement for ``d16(An)`` / ``d8(An,Xn)`` / PC-relative
        forms.  ``None`` when the mode has no displacement.
    index_reg:
        Index register number for indexed modes, else ``None``.
    index_is_addr:
        ``True`` if the index register is an address register (``An``),
        ``False`` if a data register (``Dn``).  Only meaningful for indexed
        modes.
    index_size:
        Index register size, ``'w'`` (sign-extended word) or ``'l'``.  Only
        meaningful for indexed modes.
    imm:
        Immediate value for :attr:`EAMode.IMMEDIATE` (unsigned, already
        masked to the operand size by the decoder), else ``None``.
    abs_value:
        Decode-time resolved absolute address.  Populated for ABS_W / ABS_L
        (the absolute address itself), PC_DISP / PC_INDEX (PC already added,
        mirroring :class:`Addr`) and BRANCH_TARGET.  ``None`` otherwise.
    reglist:
        For :attr:`EAMode.REG_LIST` only — the rendered register-list string
        (e.g. ``'d0-d7/a0-a5'``), matching the assembler text.
    special:
        For :attr:`EAMode.SPECIAL_REG` only — one of ``'sr'`` / ``'ccr'`` /
        ``'usp'``.
    raw:
        For :attr:`EAMode.RAW` only — the original unparsed operand text.
    """

    mode:          EAMode
    reg:           Optional[int] = None
    size:          Optional[str] = None
    disp:          Optional[int] = None
    index_reg:     Optional[int] = None
    index_is_addr: bool          = False
    index_size:    Optional[str] = None
    imm:           Optional[int] = None
    abs_value:     Optional[int] = None
    reglist:       Optional[str] = None
    special:       Optional[str] = None
    raw:           Optional[str] = None

    @property
    def is_register_direct(self) -> bool:
        """True for ``Dn`` / ``An`` (no memory access)."""
        return self.mode in (EAMode.DATA_REG, EAMode.ADDR_REG)

    @property
    def is_memory(self) -> bool:
        """True for modes that read/write memory (indirect/abs/PC-rel)."""
        return self.mode in (
            EAMode.ADDR_IND, EAMode.ADDR_POSTINC, EAMode.ADDR_PREDEC,
            EAMode.ADDR_DISP, EAMode.ADDR_INDEX,
            EAMode.ABS_W, EAMode.ABS_L, EAMode.PC_DISP, EAMode.PC_INDEX,
        )


# ---------------------------------------------------------------------------
# String/Addr  →  structured EA conversion
# ---------------------------------------------------------------------------
#
# The decoder produces operands in a fixed, canonical grammar (see
# ``InstructionDecoder._ea`` and the inline ``f'd{n}'`` / ``f'-(a{n})'``
# builders).  ``ea_from_operand`` converts one such operand — a string or an
# :class:`Addr` — into the structured :class:`EA`.  This is the *decoder*
# canonicalizing its own output, not the C++ generator reparsing ``.asm``:
# the grammar here is closed and exercised by unit tests.

import re as _re

# Address registers accept a0–a7 (the decoder renders A7 as either 'a7' or
# 'sp'); both map to register index 7 via _reg_of / the 'sp' alternative.
_RE_DREG       = _re.compile(r'^d([0-7])$')
_RE_AREG       = _re.compile(r'^(?:a([0-7])|sp)$')
_RE_IND        = _re.compile(r'^\((?:a([0-7])|sp)\)$')
_RE_POSTINC    = _re.compile(r'^\((?:a([0-7])|sp)\)\+$')
_RE_PREDEC     = _re.compile(r'^-\((?:a([0-7])|sp)\)$')
_RE_HEX        = r'-?\$[0-9a-fA-F]+'
_RE_DISP       = _re.compile(r'^(' + _RE_HEX + r')\((?:a([0-7])|sp)\)$')
_RE_INDEX      = _re.compile(
    r'^(' + _RE_HEX + r')\((?:a([0-7])|sp),'
    r'(?:(d)([0-7])|(a)([0-7])|(sp))\.([wl])\)$')
_RE_IMM        = _re.compile(r'^#(' + _RE_HEX + r')$')
# moveq emits negative immediates as bare '-$h' (no leading '#'); accept it.
_RE_IMM_BARE   = _re.compile(r'^(-\$[0-9a-fA-F]+)$')
_RE_REGLIST    = _re.compile(r'^(?:d[0-7]|a[0-7]|sp)(?:[-/](?:d[0-7]|a[0-7]|sp))*$')


def _reg_of(an_group: Optional[str]) -> int:
    """Return the register index for an ``a([0-6])|sp`` regex group (sp→7)."""
    return 7 if an_group is None else int(an_group)


def _hex_signed(s: str) -> int:
    """Parse the decoder's ``$hh`` / ``-$hh`` displacement notation."""
    neg = s.startswith('-')
    if neg:
        s = s[1:]
    val = int(s.lstrip('$'), 16)
    return -val if neg else val


def ea_from_operand(op) -> 'EA':
    """Convert one decoder operand (``str`` or :class:`Addr`) to an :class:`EA`.

    Unrecognized strings become :attr:`EAMode.RAW` with the text preserved,
    so the conversion is total.
    """
    # --- Addr operands already carry structured fields ---
    if isinstance(op, Addr):
        if op.form == 'branch':
            return EA(EAMode.BRANCH_TARGET, abs_value=op.value)
        if op.form == 'abs_w':
            return EA(EAMode.ABS_W, abs_value=op.value, size='w')
        if op.form == 'abs_l':
            return EA(EAMode.ABS_L, abs_value=op.value, size='l')
        if op.form == 'pc_rel':
            return EA(EAMode.PC_DISP, abs_value=op.value)
        if op.form == 'pc_rel_idx':
            ix = _parse_index_suffix(op.suffix)
            return EA(EAMode.PC_INDEX, abs_value=op.value,
                      index_reg=ix[0], index_is_addr=ix[1], index_size=ix[2])
        return EA(EAMode.RAW, raw=str(op))

    s = str(op)

    if s in ('sr', 'ccr', 'usp'):
        return EA(EAMode.SPECIAL_REG, special=s)

    m = _RE_DREG.match(s)
    if m:
        return EA(EAMode.DATA_REG, reg=int(m.group(1)))

    m = _RE_AREG.match(s)
    if m:
        return EA(EAMode.ADDR_REG, reg=_reg_of(m.group(1)))

    m = _RE_IND.match(s)
    if m:
        return EA(EAMode.ADDR_IND, reg=_reg_of(m.group(1)))

    m = _RE_POSTINC.match(s)
    if m:
        return EA(EAMode.ADDR_POSTINC, reg=_reg_of(m.group(1)))

    m = _RE_PREDEC.match(s)
    if m:
        return EA(EAMode.ADDR_PREDEC, reg=_reg_of(m.group(1)))

    m = _RE_DISP.match(s)
    if m:
        return EA(EAMode.ADDR_DISP, reg=_reg_of(m.group(2)),
                  disp=_hex_signed(m.group(1)))

    m = _RE_INDEX.match(s)
    if m:
        # groups: 1=disp 2=base 3='d' 4=dnum 5='a' 6=anum 7='sp' 8=size
        if m.group(3):            # data index
            ireg, iaddr = int(m.group(4)), False
        elif m.group(5):          # addr index
            ireg, iaddr = int(m.group(6)), True
        else:                     # sp index
            ireg, iaddr = 7, True
        return EA(EAMode.ADDR_INDEX, reg=_reg_of(m.group(2)),
                  disp=_hex_signed(m.group(1)),
                  index_reg=ireg, index_is_addr=iaddr, index_size=m.group(8))

    m = _RE_IMM.match(s)
    if m:
        return EA(EAMode.IMMEDIATE, imm=_hex_signed(m.group(1)))

    m = _RE_IMM_BARE.match(s)
    if m:
        return EA(EAMode.IMMEDIATE, imm=_hex_signed(m.group(1)))

    if _RE_REGLIST.match(s):
        return EA(EAMode.REG_LIST, reglist=s)

    return EA(EAMode.RAW, raw=s)


def _parse_index_suffix(suffix: str) -> tuple:
    """Parse a 'd0.w' / 'a5.l' / 'sp.l' index suffix → (reg, is_addr, size)."""
    m = _re.match(r'^(?:(d)([0-7])|(a)([0-7])|(sp))\.([wl])$', suffix)
    if not m:
        return (None, False, None)
    if m.group(1):
        return (int(m.group(2)), False, m.group(6))
    if m.group(3):
        return (int(m.group(4)), True, m.group(6))
    return (7, True, m.group(6))


@dataclass
class Instruction:
    """A fully decoded Motorola 68000 instruction."""

    address:     int                              # ROM address of the first byte
    mnemonic:    str                              # Mnemonic, lowercase (e.g. 'move', 'bra')
    size:        Optional[str]                    # Size suffix: 'b', 'w', 'l', or None
    operands:    list                             # list[str | Addr] — formatted operands
    byte_length: int                              # Total size in bytes (always even)
    flow:        FlowType                         # Control-flow classification
    targets:     list[int] = field(default_factory=list)
    # Statically-resolved branch/call targets (empty when indirect)
    indirect:    bool = False
    # True when a jump/call target cannot be determined statically
    eas:         list = field(default_factory=list)
    # list[EA] — structured form of each operand (eas[i] mirrors operands[i]);
    # consumed by the C++ recompiler. Empty only for operand-less instructions.

    @property
    def next_address(self) -> int:
        """Address of the instruction that follows this one."""
        return self.address + self.byte_length

    def __str__(self) -> str:
        mnem = f'{self.mnemonic}.{self.size}' if self.size else self.mnemonic
        if self.operands:
            ops = ', '.join(
                (f'${o.value:06X}' if isinstance(o, Addr) else o)
                for o in self.operands
            )
            return f'{mnem} {ops}'
        return mnem
