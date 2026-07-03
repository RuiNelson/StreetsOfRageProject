"""Motorola 68000 instruction decoder.

Covers the complete 68000 instruction set as implemented by the Exodus emulator
(``Exodus/Devices/M68000/M68000Opcodes.pkg``), covering 56 distinct instruction
types across 16 primary opcode groups.

Opcode groups (bits 15-12 of the first word)
==============================================
:``0000`` — ORI / ANDI / SUBI / ADDI / EORI / CMPI / BTST / BCHG / BCLR /
            BSET (static + dynamic) / MOVEP
:``0001`` — MOVE.B
:``0010`` — MOVE.L
:``0011`` — MOVE.W / MOVEA.W
:``0100`` — Miscellaneous: NEG / NEGX / CLR / EXT / NBCD / SWAP / PEA /
            LINK / UNLK / MOVEM / MOVEA / LEA / CHK / TAS / TST /
            MOVE from/to SR / MOVE from/to CCR / ILLEGAL / TRAP / TRAPV /
            RESET / NOP / STOP / RTE / RTS / RTR / JSR / JMP /
            MOVE USP / BKPT
:``0101`` — ADDQ / SUBQ / Scc / DBcc
:``0110`` — BRA / BSR / Bcc (all 16 condition codes)
:``0111`` — MOVEQ
:``1000`` — OR / DIVU / SBCD / DIVS
:``1001`` — SUB / SUBX / SUBA
:``1010`` — Line-A  (unimplemented, emitted as ``dc.w``)
:``1011`` — CMP / CMPA / CMPM / EOR
:``1100`` — AND / MULU / ABCD / EXG / MULS
:``1101`` — ADD / ADDX / ADDA
:``1110`` — ASL / ASR / LSL / LSR / ROXL / ROXR / ROL / ROR
            (register and memory variants, immediate and register count)
:``1111`` — Line-F  (unimplemented, emitted as ``dc.w``)

Condition codes (alphabetical)
===============================
:``t``  — true (always)
:``f``  — false (never, used for padding)
:``hi`` — high (C∧Z=0)
:``ls`` — low or same (C∨Z=1)
:``cc`` — carry clear (C=0)
:``cs`` — carry set (C=1)
:``ne`` — not equal (Z=0)
:``eq`` — equal (Z=1)
:``vc`` — overflow clear (V=0)
:``vs`` — overflow set (V=1)
:``pl`` — plus (N=0)
:``mi`` — minus (N=1)
:``ge`` — greater or equal (N⊕V=0)
:``lt`` — less than (N⊕V=1)
:``gt`` — greater than (Z∨(N⊕V)=0)
:``le`` — less or equal (Z∨(N⊕V)=1)

Fallback for unknown opcodes
============================
If the decoder encounters a word in groups 0–E that it cannot interpret
(it should never happen for the Streets of Rage ROM), it emits a
``dc.w $XXXX`` data word with ``FlowType.SEQUENTIAL`` so the disassembler
can continue past it rather than aborting.  Line-A and Line-F opcodes
are explicitly emitted as ``dc.w`` since they are not real 68000 instructions.

Macro strategy
==============
All documented 68000 opcodes plus ``illegal`` are supported.
Any unsupported opcode is emitted as ``dc.w`` so the output is still
byte-exact and re-assemblable.
"""

from .instruction import Addr, EAMode, FlowType, Instruction, ea_from_operand
from .rom import ROM, ROMError


class DecodeError(Exception):
    """Raised when a word cannot be decoded as a valid 68000 instruction."""


# ---------------------------------------------------------------------------
# Internal decode context — tracks sequential extension-word consumption
# ---------------------------------------------------------------------------

class _Ctx:
    """Stateful cursor that walks extension words of one instruction.

    Call ``next_word()`` / ``next_long()`` in the same order the CPU would
    fetch them; ``byte_length`` reflects the total bytes consumed so far.
    """

    def __init__(self, rom: ROM, addr: int) -> None:
        self.rom       = rom
        self.base_addr = addr
        self._exts     = 0          # extension words read so far

    # -- reads -----------------------------------------------------------

    @property
    def _ext_addr(self) -> int:
        """Address of the *next* extension word to be read."""
        return self.base_addr + 2 + self._exts * 2

    def next_word(self) -> int:
        v = self.rom.read_word(self._ext_addr)
        self._exts += 1
        return v

    def next_word_signed(self) -> int:
        v = self.rom.read_word_signed(self._ext_addr)
        self._exts += 1
        return v

    def next_long(self) -> int:
        v = self.rom.read_long(self._ext_addr)
        self._exts += 2
        return v

    def peek_ext_addr(self) -> int:
        """Address of the next extension word, without advancing."""
        return self._ext_addr

    # -- totals ----------------------------------------------------------

    @property
    def byte_length(self) -> int:
        return 2 + self._exts * 2


# ---------------------------------------------------------------------------
# Main decoder
# ---------------------------------------------------------------------------

class InstructionDecoder:
    """Decodes one 68000 instruction from the ROM at a given address.

    Usage::

        decoder = InstructionDecoder(rom)
        instr   = decoder.decode(0x000208)
    """

    # Condition-code names indexed by 4-bit condition field
    CC = ['t', 'f', 'hi', 'ls', 'cc', 'cs', 'ne', 'eq',
          'vc', 'vs', 'pl', 'mi', 'ge', 'lt', 'gt', 'le']

    # Size suffix indexed by the standard 2-bit size field  (00=b 01=w 10=l)
    SZ = {0: 'b', 1: 'w', 2: 'l'}

    def __init__(self, rom: ROM) -> None:
        self.rom = rom

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decode(self, addr: int) -> Instruction:
        """Decode the instruction at *addr* and return an :class:`Instruction`."""
        if addr & 1:
            raise DecodeError(f'Odd address ${addr:06X}')
        if not self.rom.in_bounds(addr, 2):
            raise DecodeError(f'Address out of bounds: ${addr:06X}')

        word = self.rom.read_word(addr)
        ctx  = _Ctx(self.rom, addr)
        grp  = (word >> 12) & 0xF

        dispatch = {
            0x0: self._grp0,
            0x1: lambda c, w: self._move(c, w, 'b'),
            0x2: lambda c, w: self._move(c, w, 'l'),
            0x3: lambda c, w: self._move(c, w, 'w'),
            0x4: self._grp4,
            0x5: self._grp5,
            0x6: self._grp6,
            0x7: self._moveq,
            0x8: self._grp8,
            0x9: self._grp9,
            0xA: self._line_a,
            0xB: self._grpB,
            0xC: self._grpC,
            0xD: self._grpD,
            0xE: self._grpE,
            0xF: self._line_f,
        }
        return dispatch[grp](ctx, word)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make(self, ctx: _Ctx, mnem: str, size, operands,
              flow=FlowType.SEQUENTIAL,
              targets=None, indirect=False) -> Instruction:
        ops = list(operands)
        return Instruction(
            address     = ctx.base_addr,
            mnemonic    = mnem,
            size        = size,
            operands    = ops,
            eas         = [self._build_ea(o, size) for o in ops],
            byte_length = ctx.byte_length,
            flow        = flow,
            targets     = targets or [],
            indirect    = indirect,
        )

    @staticmethod
    def _build_ea(op, size):
        """Structured EA for one operand, with the instruction size attached.

        ``ea_from_operand`` resolves the addressing mode and all EA fields from
        the decoder's canonical operand grammar.  The instruction's operand
        size is then stamped onto register/indirect modes (which do not encode
        their own size in the operand text) so the recompiler knows the access
        width.  Modes that carry an intrinsic size ('.w'/'.l' absolute, branch
        displacement, immediate, special regs, reglists) keep their own.
        """
        ea = ea_from_operand(op)
        if size in ('b', 'w', 'l') and ea.size is None and ea.mode not in (
            EAMode.IMMEDIATE, EAMode.BRANCH_TARGET, EAMode.REG_LIST,
            EAMode.SPECIAL_REG, EAMode.RAW,
        ):
            ea.size = size
        return ea

    # -- Effective-address helpers ---------------------------------------

    def _ea(self, ctx: _Ctx, mode: int, reg: int, size: str) -> object:
        """Decode one effective-address field; return a string or :class:`Addr`.

        *size* is needed only for immediate mode (to know whether it is 1 or 2
        extension words).
        """
        an = 'sp' if reg == 7 else f'a{reg}'

        if mode == 0b000:
            return f'd{reg}'
        if mode == 0b001:
            return an
        if mode == 0b010:
            return f'({an})'
        if mode == 0b011:
            return f'({an})+'
        if mode == 0b100:
            return f'-({an})'

        if mode == 0b101:           # d16(An)
            d16 = ctx.next_word_signed()
            ds  = f'-${-d16:x}' if d16 < 0 else f'${d16:x}'
            return f'{ds}({an})'

        if mode == 0b110:           # d8(An,Xn)
            ext     = ctx.next_word()
            d8      = ext & 0xFF
            if d8 >= 0x80:
                d8 -= 0x100
            xtype   = 'a' if (ext >> 15) & 1 else 'd'
            xnum    = (ext >> 12) & 7
            xsz     = 'l' if (ext >> 11) & 1 else 'w'
            xn      = 'sp' if xtype == 'a' and xnum == 7 else f'{xtype}{xnum}'
            ds      = f'-${-d8:x}' if d8 < 0 else f'${d8:x}'
            return f'{ds}({an},{xn}.{xsz})'

        if mode == 0b111:
            if reg == 0b000:        # (xxx).w  — sign-extended short absolute
                val = ctx.next_word()
                # Store raw 16-bit value; formatter handles sign-extension
                return Addr(val, 'abs_w')

            if reg == 0b001:        # (xxx).l  — absolute long
                return Addr(ctx.next_long(), 'abs_l')

            if reg == 0b010:        # d16(PC)
                pc   = ctx.peek_ext_addr()   # PC = address of this ext word
                d16  = ctx.next_word_signed()
                return Addr(pc + d16, 'pc_rel')

            if reg == 0b011:        # d8(PC,Xn)
                pc   = ctx.peek_ext_addr()
                ext  = ctx.next_word()
                d8   = ext & 0xFF
                if d8 >= 0x80:
                    d8 -= 0x100
                xtype = 'a' if (ext >> 15) & 1 else 'd'
                xnum  = (ext >> 12) & 7
                xsz   = 'l' if (ext >> 11) & 1 else 'w'
                xn    = 'sp' if xtype == 'a' and xnum == 7 else f'{xtype}{xnum}'
                ds    = f'-${-d8:x}' if d8 < 0 else f'${d8:x}'
                return Addr(pc + d8, 'pc_rel_idx', suffix=f'{xn}.{xsz}')

            if reg == 0b100:        # #<data>  immediate
                if size == 'l':
                    return f'#${ctx.next_long():08x}'
                else:
                    val = ctx.next_word()
                    if size == 'b':
                        val &= 0xFF
                    return f'#${val:04x}'

        raise DecodeError(f'Invalid EA mode={mode} reg={reg}')

    def _ea_target(self, ea_op) -> tuple:
        """Return (target_addr, indirect) for a JSR/JMP effective address."""
        if isinstance(ea_op, Addr) and ea_op.form in ('abs_l', 'abs_w', 'pc_rel'):
            return ea_op.value, False
        return 0, True

    @staticmethod
    def _reglist(mask: int, predecrement: bool) -> str:
        """Format a MOVEM register-list mask as 'd0-d7/a0-a5' style string.

        For predecrement mode the bit-to-register mapping is reversed per the
        M68000 PRM (bit 15 = D0, …, bit 8 = D7, bit 7 = A0, …, bit 0 = A7).
        """
        if predecrement:
            # natural register index i  →  bit position (15 - i)
            active = [i for i in range(16) if (mask >> (15 - i)) & 1]
        else:
            # natural register index i  →  bit position i
            active = [i for i in range(16) if (mask >> i) & 1]

        if not active:
            return ''

        # Build compact range strings
        def reg_name(i: int) -> str:
            if i < 8:
                return f'd{i}'
            n = i - 8
            return 'sp' if n == 7 else f'a{n}'

        parts = []
        i = 0
        while i < len(active):
            start = active[i]
            j = i + 1
            while j < len(active) and active[j] == active[j - 1] + 1:
                j += 1
            end = active[j - 1]
            parts.append(reg_name(start) if start == end
                         else f'{reg_name(start)}-{reg_name(end)}')
            i = j
        return '/'.join(parts)

    # ------------------------------------------------------------------
    # Group 0  —  ORI / ANDI / SUBI / ADDI / EORI / CMPI
    #             BTST / BCHG / BCLR / BSET  (static and dynamic)
    #             MOVEP
    # ------------------------------------------------------------------

    def _grp0(self, ctx: _Ctx, word: int) -> Instruction:
        bit8 = (word >> 8) & 1

        if bit8:
            # ---- Dynamic bit ops  OR  MOVEP ----
            dn    = (word >> 9) & 7
            bop   = (word >> 6) & 3          # 00=btst 01=bchg 10=bclr 11=bset
            mode  = (word >> 3) & 7
            reg   = word & 7

            if mode == 0b001:
                # MOVEP  — address-register indirect with displacement
                # bit 7 = direction, bit 6 = size
                direction = (word >> 7) & 1   # 0 = mem→reg, 1 = reg→mem
                sz        = 'l' if (word >> 6) & 1 else 'w'
                d16       = ctx.next_word_signed()
                an        = 'sp' if reg == 7 else f'a{reg}'
                ds        = f'-${-d16:x}' if d16 < 0 else f'${d16:x}'
                mem_op    = f'{ds}({an})'
                if direction:
                    ops = [f'd{dn}', mem_op]
                else:
                    ops = [mem_op, f'd{dn}']
                return self._make(ctx, 'movep', sz, ops)

            # Dynamic bit operation
            ea   = self._ea(ctx, mode, reg, 'b')
            mnems = ['btst', 'bchg', 'bclr', 'bset']
            return self._make(ctx, mnems[bop], None, [f'd{dn}', ea])

        # ---- Immediate group ----
        sub   = (word >> 9) & 7              # sub-opcode
        sz_id = (word >> 6) & 3             # 00=b 01=w 10=l
        mode  = (word >> 3) & 7
        reg   = word & 7
        ea_id = (mode << 3) | reg           # 0x3C = immediate (CCR/SR special)

        if sub == 0b100:
            # Static bit operation: BTST/BCHG/BCLR/BSET  #n,ea
            bop   = (word >> 6) & 3
            imm_w = ctx.next_word()
            bit_n = f'#${imm_w & 0xFF:02x}'
            ea    = self._ea(ctx, mode, reg, 'b')
            mnems = ['btst', 'bchg', 'bclr', 'bset']
            return self._make(ctx, mnems[bop], None, [bit_n, ea])

        op_map = {
            0b000: 'ori',
            0b001: 'andi',
            0b010: 'subi',
            0b011: 'addi',
            0b101: 'eori',
            0b110: 'cmpi',
        }
        if sub not in op_map:
            raise DecodeError(f'Unknown group-0 sub={sub:#05b} at ${ctx.base_addr:06X}')
        mnem = op_map[sub]

        # Immediate ops never take An as destination on the 68000.
        if mode == 0b001:
            raise DecodeError(
                f'{mnem} with address-register destination at ${ctx.base_addr:06X}')

        # Special forms: ORI/ANDI/EORI to CCR or SR
        if ea_id == 0x3C:
            if sz_id == 0:    # …  to CCR
                imm = ctx.next_word() & 0xFF
                return self._make(ctx, mnem, None, [f'#${imm:02x}', 'ccr'])
            if sz_id == 1:    # … to SR  (privileged)
                imm = ctx.next_word()
                return self._make(ctx, mnem, None, [f'#${imm:04x}', 'sr'])

        sz   = self.SZ[sz_id]
        imm  = self._ea(ctx, 0b111, 0b100, sz)    # #<data>
        ea   = self._ea(ctx, mode, reg, sz)
        return self._make(ctx, mnem, sz, [imm, ea])

    # ------------------------------------------------------------------
    # Groups 1 / 2 / 3  —  MOVE.b / MOVE.l / MOVE.w  (and MOVEA)
    # ------------------------------------------------------------------

    def _move(self, ctx: _Ctx, word: int, sz: str) -> Instruction:
        # Source EA: bits 5-0
        src_mode = (word >> 3) & 7
        src_reg  = word & 7
        # Destination EA: bits 11-6  (mode and reg are *swapped* vs normal)
        dst_mode = (word >> 6) & 7
        dst_reg  = (word >> 9) & 7

        src = self._ea(ctx, src_mode, src_reg, sz)
        dst = self._ea(ctx, dst_mode, dst_reg, sz)

        if dst_mode == 0b001:
            # MOVEA — destination is address register
            # Byte size is not valid for MOVEA; treat as w/l
            return self._make(ctx, 'movea', sz, [src, dst])

        return self._make(ctx, 'move', sz, [src, dst])

    # ------------------------------------------------------------------
    # Group 4  —  Miscellaneous
    # ------------------------------------------------------------------

    def _grp4(self, ctx: _Ctx, word: int) -> Instruction:  # noqa: C901 — complex by necessity
        b11_8 = (word >> 8) & 0xF
        b7_6  = (word >> 6) & 3
        b5_3  = (word >> 3) & 7
        mode  = b5_3
        reg   = word & 7

        # --- ILLEGAL (fixed opcode $4AFC) ---
        if word == 0x4AFC:
            return self._make(ctx, 'illegal', None, [],
                              flow=FlowType.RETURN)

        # --- MOVE from SR / from CCR / to CCR / to SR ---
        if b11_8 == 0x0 and b7_6 == 3:
            ea = self._ea(ctx, mode, reg, 'w')
            return self._make(ctx, 'move', 'w', ['sr', ea])

        if b11_8 == 0x2 and b7_6 == 3:
            # MOVE from CCR  (68010; Exodus includes it)
            ea = self._ea(ctx, mode, reg, 'w')
            return self._make(ctx, 'move', 'w', ['ccr', ea])

        if b11_8 == 0x4 and b7_6 == 3:
            ea = self._ea(ctx, mode, reg, 'w')
            return self._make(ctx, 'move', 'w', [ea, 'ccr'])

        if b11_8 == 0x6 and b7_6 == 3:
            ea = self._ea(ctx, mode, reg, 'w')
            return self._make(ctx, 'move', 'w', [ea, 'sr'])

        # --- NEGX / CLR / NEG / NOT ---
        if b11_8 in (0x0, 0x2, 0x4, 0x6) and b7_6 != 3:
            mnem_map = {0x0: 'negx', 0x2: 'clr', 0x4: 'neg', 0x6: 'not'}
            sz = self.SZ[b7_6]
            ea = self._ea(ctx, mode, reg, sz)
            return self._make(ctx, mnem_map[b11_8], sz, [ea])

        # --- Group 0x8xxx: NBCD / SWAP / BKPT / PEA / EXT / MOVEM reg→mem ---
        if b11_8 == 0x8:
            if b7_6 == 0b00:
                # NBCD  (byte, alterable EA)
                ea = self._ea(ctx, mode, reg, 'b')
                return self._make(ctx, 'nbcd', None, [ea])

            if b7_6 == 0b01:
                if mode == 0b000:
                    return self._make(ctx, 'swap', 'w', [f'd{reg}'])
                if mode == 0b001:
                    # BKPT  #n  (Exodus implements it)
                    return self._make(ctx, 'bkpt', None, [f'#${reg:x}'])
                # PEA
                ea = self._ea(ctx, mode, reg, 'l')
                return self._make(ctx, 'pea', 'l', [ea])

            if (word >> 7) & 1:
                # bit 7 = 1: EXT (when EA=Dn) or MOVEM reg→mem
                sz = 'l' if (word >> 6) & 1 else 'w'   # size is bit 6 alone
                if mode == 0b000:
                    # EXT.w Dn  or  EXT.l Dn
                    return self._make(ctx, 'ext', sz, [f'd{reg}'])
                # MOVEM register list → memory
                mask = ctx.next_word()
                predec = (mode == 0b100)
                reglist = self._reglist(mask, predec)
                ea = self._ea(ctx, mode, reg, sz)
                return self._make(ctx, 'movem', sz, [reglist, ea])

        # --- TST / TAS ---
        if b11_8 == 0xA:
            if b7_6 == 0b11:
                ea = self._ea(ctx, mode, reg, 'b')
                return self._make(ctx, 'tas', 'b', [ea])
            sz = self.SZ[b7_6]
            ea = self._ea(ctx, mode, reg, sz)
            return self._make(ctx, 'tst', sz, [ea])

        # --- MOVEM memory → register ---
        if b11_8 == 0xC and (word >> 7) & 1:
            sz = 'l' if (word >> 6) & 1 else 'w'
            mask    = ctx.next_word()
            reglist = self._reglist(mask, False)
            ea      = self._ea(ctx, mode, reg, sz)
            return self._make(ctx, 'movem', sz, [ea, reglist])

        # --- CHK  Dn,<ea> ---
        if (word >> 8) & 1 and b7_6 == 0b10:
            dn = (word >> 9) & 7
            ea = self._ea(ctx, mode, reg, 'w')
            return self._make(ctx, 'chk', 'w', [ea, f'd{dn}'])

        # --- LEA  <ea>,An ---
        if (word >> 8) & 1 and b7_6 == 0b11:
            an_n = (word >> 9) & 7
            ea   = self._ea(ctx, mode, reg, 'l')
            an   = 'sp' if an_n == 7 else f'a{an_n}'
            return self._make(ctx, 'lea', 'l', [ea, an])

        # --- 0x4Exx area: TRAP / LINK / UNLK / MOVE USP / specials / JSR / JMP ---
        if b11_8 == 0xE:
            lo = word & 0xFF

            if 0x40 <= lo <= 0x4F:
                return self._make(ctx, 'trap', None, [f'#${lo & 0xF:x}'])

            if 0x50 <= lo <= 0x57:
                an_n = lo & 7
                an   = 'sp' if an_n == 7 else f'a{an_n}'
                d16  = ctx.next_word_signed()
                ds   = f'-${-d16:x}' if d16 < 0 else f'${d16:x}'
                return self._make(ctx, 'link', 'w', [an, f'#${d16 & 0xFFFF:04x}'])

            if 0x58 <= lo <= 0x5F:
                an_n = lo & 7
                an   = 'sp' if an_n == 7 else f'a{an_n}'
                return self._make(ctx, 'unlk', None, [an])

            if 0x60 <= lo <= 0x6F:
                direction = (lo >> 3) & 1    # 0 = USP→An, 1 = An→USP
                an_n = lo & 7
                an   = 'sp' if an_n == 7 else f'a{an_n}'
                if direction:
                    return self._make(ctx, 'move', None, [an, 'usp'])
                else:
                    return self._make(ctx, 'move', None, ['usp', an])

            if lo == 0x70:
                return self._make(ctx, 'reset', None, [])
            if lo == 0x71:
                return self._make(ctx, 'nop', None, [])
            if lo == 0x72:
                imm = ctx.next_word()
                return self._make(ctx, 'stop', None, [f'#${imm:04x}'])
            if lo == 0x73:
                return self._make(ctx, 'rte', None, [], flow=FlowType.RETURN)
            if lo == 0x75:
                return self._make(ctx, 'rts', None, [], flow=FlowType.RETURN)
            if lo == 0x76:
                return self._make(ctx, 'trapv', None, [])
            if lo == 0x77:
                return self._make(ctx, 'rtr', None, [], flow=FlowType.RETURN)

            if 0x80 <= lo <= 0xBF:
                # JSR  <ea>
                ea = self._ea(ctx, mode, reg, 'l')
                tgt, ind = self._ea_target(ea)
                flow = FlowType.CALL
                targets = [tgt] if not ind and self.rom.in_bounds(tgt, 2) else []
                return self._make(ctx, 'jsr', None, [ea],
                                  flow=flow, targets=targets, indirect=ind)

            if 0xC0 <= lo <= 0xFF:
                # JMP  <ea>
                ea = self._ea(ctx, mode, reg, 'l')
                tgt, ind = self._ea_target(ea)
                flow = FlowType.BRANCH
                targets = [tgt] if not ind and self.rom.in_bounds(tgt, 2) else []
                return self._make(ctx, 'jmp', None, [ea],
                                  flow=flow, targets=targets, indirect=ind)

        raise DecodeError(
            f'Unhandled group-4 word=${word:04X} at ${ctx.base_addr:06X}')

    # ------------------------------------------------------------------
    # Group 5  —  ADDQ / SUBQ / Scc / DBcc
    # ------------------------------------------------------------------

    def _grp5(self, ctx: _Ctx, word: int) -> Instruction:
        bit8  = (word >> 8) & 1
        b7_6  = (word >> 6) & 3
        mode  = (word >> 3) & 7
        reg   = word & 7
        data  = (word >> 9) & 7   # 3-bit immediate (0 means 8)
        cc    = (word >> 8) & 0xF  # condition code

        if b7_6 == 0b11:
            # Scc or DBcc
            cc4 = (word >> 8) & 0xF
            if mode == 0b001:
                # DBcc  Dn, <label>
                dn    = f'd{reg}'
                d16   = ctx.next_word_signed()
                tgt   = ctx.base_addr + 2 + d16   # PC at ext word = base+2
                label = Addr(tgt, 'branch')
                instr = self._make(ctx, f'db{self.CC[cc4]}', 'w',
                                   [dn, label],
                                   flow=FlowType.CONDITIONAL,
                                   targets=[tgt] if self.rom.in_bounds(tgt, 2) else [])
                return instr
            # Scc
            ea = self._ea(ctx, mode, reg, 'b')
            return self._make(ctx, f's{self.CC[cc4]}', None, [ea])

        sz   = self.SZ[b7_6]
        imm  = data if data else 8
        ea   = self._ea(ctx, mode, reg, sz)

        if bit8 == 0:
            return self._make(ctx, 'addq', sz, [f'#${imm:x}', ea])
        else:
            return self._make(ctx, 'subq', sz, [f'#${imm:x}', ea])

    # ------------------------------------------------------------------
    # Group 6  —  BRA / BSR / Bcc
    # ------------------------------------------------------------------

    def _grp6(self, ctx: _Ctx, word: int) -> Instruction:
        cc4  = (word >> 8) & 0xF
        d8   = word & 0xFF

        if d8 != 0x00:
            # 8-bit (short) displacement
            disp = d8 if d8 < 0x80 else d8 - 0x100
            tgt  = ctx.base_addr + 2 + disp
            sz   = 's'
        else:
            # 16-bit displacement in extension word
            # PC at extension word = base_addr + 2
            disp = ctx.next_word_signed()
            tgt  = ctx.base_addr + 2 + disp
            sz   = 'w'

        label   = Addr(tgt, 'branch')
        in_rom  = self.rom.in_bounds(tgt, 2) and not (tgt & 1)
        targets = [tgt] if in_rom else []

        if cc4 == 0:          # BRA
            return self._make(ctx, 'bra', sz, [label],
                              flow=FlowType.BRANCH, targets=targets)
        if cc4 == 1:          # BSR
            return self._make(ctx, 'bsr', sz, [label],
                              flow=FlowType.CALL, targets=targets)
        # Bcc
        return self._make(ctx, f'b{self.CC[cc4]}', sz, [label],
                          flow=FlowType.CONDITIONAL, targets=targets)

    # ------------------------------------------------------------------
    # Group 7  —  MOVEQ
    # ------------------------------------------------------------------

    def _moveq(self, ctx: _Ctx, word: int) -> Instruction:
        if (word >> 8) & 1:
            raise DecodeError(f'Invalid MOVEQ (bit 8 set) at ${ctx.base_addr:06X}')
        dn   = (word >> 9) & 7
        data = word & 0xFF
        imm  = data if data < 0x80 else data - 0x100
        imm_s = f'-${-imm:x}' if imm < 0 else f'#${imm:02x}'
        return self._make(ctx, 'moveq', None, [imm_s, f'd{dn}'])

    # ------------------------------------------------------------------
    # Group 8  —  OR / DIVU / SBCD / DIVS
    # ------------------------------------------------------------------

    def _grp8(self, ctx: _Ctx, word: int) -> Instruction:
        dn   = (word >> 9) & 7
        bit8 = (word >> 8) & 1
        b7_6 = (word >> 6) & 3
        mode = (word >> 3) & 7
        reg  = word & 7

        if b7_6 == 0b11:
            # DIVU / DIVS
            ea   = self._ea(ctx, mode, reg, 'w')
            mnem = 'divs' if bit8 else 'divu'
            return self._make(ctx, mnem, 'w', [ea, f'd{dn}'])

        if bit8 and b7_6 == 0b00:
            # SBCD — only valid for data-reg (mode=000) or addr-reg (mode=001)
            if mode not in (0b000, 0b001):
                sz = self.SZ[b7_6]
                ea = self._ea(ctx, mode, reg, sz)
                return self._make(ctx, 'or', sz, [f'd{dn}', ea])   # reg → mem
            rm = reg
            rn = dn
            if mode == 0b000:
                return self._make(ctx, 'sbcd', None, [f'd{rm}', f'd{rn}'])
            return self._make(ctx, 'sbcd', None, [f'-(a{rm})', f'-(a{rn})'])

        sz = self.SZ[b7_6]
        ea = self._ea(ctx, mode, reg, sz)
        if bit8:
            return self._make(ctx, 'or', sz, [f'd{dn}', ea])   # reg → mem
        return self._make(ctx, 'or', sz, [ea, f'd{dn}'])        # mem → reg

    # ------------------------------------------------------------------
    # Group 9  —  SUB / SUBX / SUBA
    # ------------------------------------------------------------------

    def _grp9(self, ctx: _Ctx, word: int) -> Instruction:
        dn   = (word >> 9) & 7
        bit8 = (word >> 8) & 1
        b7_6 = (word >> 6) & 3
        mode = (word >> 3) & 7
        reg  = word & 7

        if b7_6 == 0b11:
            # SUBA
            ea  = self._ea(ctx, mode, reg, 'l' if bit8 else 'w')
            an  = 'sp' if dn == 7 else f'a{dn}'
            return self._make(ctx, 'suba', 'l' if bit8 else 'w', [ea, an])

        if bit8 and mode in (0b000, 0b001):
            # SUBX
            sz   = self.SZ[b7_6]
            if mode == 0b000:
                return self._make(ctx, 'subx', sz, [f'd{reg}', f'd{dn}'])
            return self._make(ctx, 'subx', sz, [f'-(a{reg})', f'-(a{dn})'])

        sz = self.SZ[b7_6]
        ea = self._ea(ctx, mode, reg, sz)
        if bit8:
            return self._make(ctx, 'sub', sz, [f'd{dn}', ea])   # reg → mem
        return self._make(ctx, 'sub', sz, [ea, f'd{dn}'])        # mem → reg

    # ------------------------------------------------------------------
    # Line-A  (0xAxxx)  and Line-F  (0xFxxx)  — unimplemented instructions
    # ------------------------------------------------------------------

    def _line_a(self, ctx: _Ctx, word: int) -> Instruction:
        return self._make(ctx, 'dc', 'w', [f'${word:04x}'])  # emit as data word

    def _line_f(self, ctx: _Ctx, word: int) -> Instruction:
        return self._make(ctx, 'dc', 'w', [f'${word:04x}'])

    # ------------------------------------------------------------------
    # Group B  —  CMP / CMPA / CMPM / EOR
    # ------------------------------------------------------------------

    def _grpB(self, ctx: _Ctx, word: int) -> Instruction:
        dn   = (word >> 9) & 7
        bit8 = (word >> 8) & 1
        b7_6 = (word >> 6) & 3
        mode = (word >> 3) & 7
        reg  = word & 7

        if b7_6 == 0b11:
            # CMPA
            sz  = 'l' if bit8 else 'w'
            ea  = self._ea(ctx, mode, reg, sz)
            an  = 'sp' if dn == 7 else f'a{dn}'
            return self._make(ctx, 'cmpa', sz, [ea, an])

        if bit8:
            if mode == 0b001:
                # CMPM  (An)+,(An)+
                sz = self.SZ[b7_6]
                src_an = 'sp' if reg == 7 else f'a{reg}'
                dst_an = 'sp' if dn  == 7 else f'a{dn}'
                return self._make(ctx, 'cmpm', sz,
                                  [f'({src_an})+', f'({dst_an})+'])
            # EOR  Dn,<ea>
            sz = self.SZ[b7_6]
            ea = self._ea(ctx, mode, reg, sz)
            return self._make(ctx, 'eor', sz, [f'd{dn}', ea])

        # CMP  <ea>,Dn
        sz = self.SZ[b7_6]
        ea = self._ea(ctx, mode, reg, sz)
        return self._make(ctx, 'cmp', sz, [ea, f'd{dn}'])

    # ------------------------------------------------------------------
    # Group C  —  AND / MULU / ABCD / EXG / MULS
    # ------------------------------------------------------------------

    def _grpC(self, ctx: _Ctx, word: int) -> Instruction:
        dn   = (word >> 9) & 7
        bit8 = (word >> 8) & 1
        b7_6 = (word >> 6) & 3
        mode = (word >> 3) & 7
        reg  = word & 7

        if b7_6 == 0b11:
            mnem = 'muls' if bit8 else 'mulu'
            ea   = self._ea(ctx, mode, reg, 'w')
            return self._make(ctx, mnem, 'w', [ea, f'd{dn}'])

        if bit8:
            # ABCD, EXG, or AND reg→mem
            if b7_6 == 0b00:
                # ABCD is only valid for register-direct and predecrement
                # forms; other EAs in this slot are AND.b Dn,<ea>.
                if mode == 0b000:
                    return self._make(ctx, 'abcd', None, [f'd{reg}', f'd{dn}'])
                if mode == 0b001:
                    return self._make(ctx, 'abcd', None,
                                      [f'-(a{reg})', f'-(a{dn})'])

            b7_3 = (word >> 3) & 0b11111
            if b7_3 == 0b01000:    # EXG Dn,Dn
                return self._make(ctx, 'exg', None, [f'd{dn}', f'd{reg}'])
            if b7_3 == 0b01001:    # EXG An,An
                an1 = 'sp' if dn  == 7 else f'a{dn}'
                an2 = 'sp' if reg == 7 else f'a{reg}'
                return self._make(ctx, 'exg', None, [an1, an2])
            if b7_3 == 0b10001:    # EXG Dn,An
                an  = 'sp' if reg == 7 else f'a{reg}'
                return self._make(ctx, 'exg', None, [f'd{dn}', an])

            # AND  Dn,<ea>  (reg → mem)
            sz = self.SZ[b7_6]
            ea = self._ea(ctx, mode, reg, sz)
            return self._make(ctx, 'and', sz, [f'd{dn}', ea])

        # AND  <ea>,Dn  (mem → reg)
        sz = self.SZ[b7_6]
        ea = self._ea(ctx, mode, reg, sz)
        return self._make(ctx, 'and', sz, [ea, f'd{dn}'])

    # ------------------------------------------------------------------
    # Group D  —  ADD / ADDX / ADDA
    # ------------------------------------------------------------------

    def _grpD(self, ctx: _Ctx, word: int) -> Instruction:
        dn   = (word >> 9) & 7
        bit8 = (word >> 8) & 1
        b7_6 = (word >> 6) & 3
        mode = (word >> 3) & 7
        reg  = word & 7

        if b7_6 == 0b11:
            sz  = 'l' if bit8 else 'w'
            ea  = self._ea(ctx, mode, reg, sz)
            an  = 'sp' if dn == 7 else f'a{dn}'
            return self._make(ctx, 'adda', sz, [ea, an])

        if bit8 and mode in (0b000, 0b001):
            # ADDX
            sz = self.SZ[b7_6]
            if mode == 0b000:
                return self._make(ctx, 'addx', sz, [f'd{reg}', f'd{dn}'])
            return self._make(ctx, 'addx', sz, [f'-(a{reg})', f'-(a{dn})'])

        sz = self.SZ[b7_6]
        ea = self._ea(ctx, mode, reg, sz)
        if bit8:
            return self._make(ctx, 'add', sz, [f'd{dn}', ea])   # reg → mem
        return self._make(ctx, 'add', sz, [ea, f'd{dn}'])        # mem → reg

    # ------------------------------------------------------------------
    # Group E  —  ASL / ASR / LSL / LSR / ROXL / ROXR / ROL / ROR
    # ------------------------------------------------------------------

    def _grpE(self, ctx: _Ctx, word: int) -> Instruction:
        b11_9 = (word >> 9) & 7
        dr    = (word >> 8) & 1    # direction: 0=right, 1=left
        b7_6  = (word >> 6) & 3
        mode  = (word >> 3) & 7
        reg   = word & 7

        if b7_6 == 0b11:
            # Memory shift / rotate (always by 1, always word).
            # Verified against Exodus opcode table:
            #   $E0D0=asr  $E1D0=asl  $E2D0=lsr  $E3D0=lsl
            #   $E4D0=roxr  $E5D0=roxl $E6D0=ror  $E7D0=rol
            # Bits 10-8 encode the full op, not (op_type, direction) separately.
            _MEM_SHIFT = {
                0b000: 'asr', 0b001: 'asl',
                0b010: 'lsr', 0b011: 'lsl',
                0b100: 'roxr', 0b101: 'roxl',
                0b110: 'ror',  0b111: 'rol',
            }
            # Only memory-alterable EAs are legal: (An)…d8(An,Xn) and abs.w/l.
            if mode < 0b010 or (mode == 0b111 and reg > 1):
                raise DecodeError(
                    f'Memory shift with non-alterable EA mode={mode} reg={reg} '
                    f'at ${ctx.base_addr:06X}')
            mnem = _MEM_SHIFT[(word >> 8) & 7]
            ea   = self._ea(ctx, mode, reg, 'w')
            return self._make(ctx, mnem, 'w', [ea])

        # Register shift / rotate
        # Op type (bits 4-3): 00=AS, 01=LS, 10=ROX, 11=RO
        SHIFT_MNEMS = {0b00: 'as', 0b01: 'ls', 0b10: 'rox', 0b11: 'ro'}
        sz    = self.SZ[b7_6]
        ir    = (word >> 5) & 1            # 0 = immediate count, 1 = register count
        op_t  = (word >> 3) & 3           # shift type
        base  = SHIFT_MNEMS[op_t]
        mnem  = f'{base}{"l" if dr else "r"}'
        dn    = f'd{reg}'

        if ir:
            cnt_reg = f'd{b11_9}'
            return self._make(ctx, mnem, sz, [cnt_reg, dn])
        else:
            cnt = b11_9 if b11_9 else 8
            return self._make(ctx, mnem, sz, [f'#${cnt:x}', dn])
