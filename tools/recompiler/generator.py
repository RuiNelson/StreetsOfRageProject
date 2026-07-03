"""Emit a MegaDriveEnvironment subclass from the decoded ROM.

Ties together region partitioning (``regions``), data-op codegen (``opcodes``)
and EA codegen (``ea_codegen``), adding the control-flow lowering that needs
region context: intra-function ``goto``, cross-function calls, the indirect
``dispatch`` table, and the JSR/RTS emulated-stack handling.

Output: a ``Sor.hpp`` / ``Sor.cpp`` pair. Generation is total — an opcode that
cannot be translated is a hard error, never a silent stub; coverage statistics
are reported by ``main``. Function names and intra-function ``goto`` labels
come from the labels CSV when present (falling back to ``sub_XXXXXX`` /
``L{addr}``).
"""

import re

from tools.disassembler.instruction import FlowType, EAMode
from tools.recompiler import cpp_semantics as sem
from tools.recompiler import ea_codegen as ea
from tools.recompiler import opcodes
from tools.recompiler.opcodes import Unsupported
from tools.recompiler.ea_codegen import EAGenError, TempPool
from tools.recompiler.regions import partition

# Condition-code numbers.
_CC = {
    't': 0, 'f': 1, 'hi': 2, 'ls': 3, 'cc': 4, 'cs': 5, 'ne': 6, 'eq': 7,
    'vc': 8, 'vs': 9, 'pl': 10, 'mi': 11, 'ge': 12, 'lt': 13, 'gt': 14, 'le': 15,
}


def _fn(addr: int) -> str:
    return f'sub_{addr:06x}'


def _default_label(addr: int) -> str:
    return f'L{addr:06x}'


# Identifiers a generated function must not take (Sor / MegaDriveEnvironment
# members and a few obvious C++ keywords); such a label falls back to sub_….
_RESERVED = {
    'run', 'dispatch', 'unhandledDispatch', 'boot', 'powerOn', 'powerOff',
    'vSync', 'hSync', 'cpu', 'memory', 'vdp', 'controllers', 'z80', 'sound',
    'loadROM', 'runVDPInterrupts', 'shouldQuit', 'main',
    'int', 'char', 'void', 'for', 'do', 'if', 'else', 'while', 'switch',
    'case', 'default', 'return', 'class', 'struct', 'new', 'delete', 'this',
    'and', 'or', 'not', 'xor', 'auto', 'const', 'static', 'goto',
}


def _sanitize(name: str) -> str | None:
    """Turn a CSV label into a valid C++ identifier, or None if unusable."""
    ident = re.sub(r'[^0-9A-Za-z_]', '_', name.strip())
    if not ident or ident[0].isdigit():
        return None
    return ident


class Stats:
    def __init__(self):
        self.handled = 0
        self.stubbed = 0
        self.stub_mnemonics = {}

    def stub(self, mnem):
        self.stubbed += 1
        self.stub_mnemonics[mnem] = self.stub_mnemonics.get(mnem, 0) + 1


class Generator:
    def __init__(self, instructions, subroutines, rom_path='rom/StreetsOfRage.bin',
                 names=None, speculative_addrs=None, speculative_scope=None,
                 baseline_instrs=None):
        self.ins = instructions
        self.part = partition(instructions, subroutines)
        self.rom_path = rom_path
        self.stats = Stats()
        self._names = names or {}
        # _speculative: raw seeds promoted only when an indirect dispatch lands
        # on them. Direct calls within generated code must not confirm aux hits.
        self._speculative = set(speculative_addrs or [])
        # _speculative_scope: all Phase-2-derived functions (seeds + derivatives)
        # — these get their full address list instead of the baseline-filtered one.
        self._speculative_scope = set(speculative_scope or self._speculative)
        # Effective instruction addresses per function.
        # Baseline functions are restricted to Phase-1 addresses so that phantom
        # instructions injected by overlapping speculative decodes are excluded.
        bl = set(baseline_instrs) if baseline_instrs is not None else None
        self._eff_addrs = {
            e: (f.addrs if (bl is None or e in self._speculative_scope)
                else [a for a in f.addrs if a in bl])
            for e, f in self.part.functions.items()
        }
        # Set version of _eff_addrs for O(1) membership in _transfer.
        self._addrs_sets = {e: set(addrs) for e, addrs in self._eff_addrs.items()}
        # Rejected entries (speculative-scope with invalid opcodes): populated in
        # emit_source before the second pass; _transfer skips direct calls to
        # rejected functions.
        self._rejected: set = set()
        self._build_fn_names(self._names)
        self._build_label_names(self._names)

    def _build_fn_names(self, names):
        """Map each function entry to a C++ identifier — the labels-CSV name
        when it sanitizes to a free identifier, otherwise ``sub_XXXXXX``."""
        self._fnname = {}
        used = set()
        for e in self.part.entries:
            ident = _sanitize(names.get(e, '')) if names.get(e) else None
            if not ident or ident in _RESERVED or ident in used:
                ident = _fn(e)
            if ident in used:                  # extremely unlikely collision
                ident = f'{ident}_{e:06x}'
            used.add(ident)
            self._fnname[e] = ident

    def _build_label_names(self, names):
        """Map goto / mid-entry targets to C++ label identifiers."""
        self._labelname = {}
        used = set(self._fnname.values()) | _RESERVED
        label_addrs = set(self.part.goto_labels)
        for func in self.part.functions.values():
            label_addrs |= func.extra_entries
        for addr in sorted(label_addrs):
            ident = _sanitize(names.get(addr, '')) if names.get(addr) else None
            if not ident or ident in used:
                ident = _default_label(addr)
            if ident in used:
                ident = f'{ident}_{addr:06x}'
            used.add(ident)
            self._labelname[addr] = ident

    def fn(self, entry):
        """C++ function name for a function entry address."""
        return self._fnname.get(entry, _fn(entry))

    def label(self, addr):
        """C++ label for an intra-function branch target."""
        return self._labelname.get(addr, _default_label(addr))

    # -- control-flow lowering ------------------------------------------------

    def _transfer(self, src_addr, tgt):
        """Unconditional transfer to absolute ``tgt`` (goto or cross-fn call)."""
        if tgt not in self.ins:
            return [f'traceEnter({ea._hex(src_addr)});',
                    f'dispatch({ea._hex(tgt)}); return;']
        src_fn = self.part.func_of(src_addr)
        tgt_fn = self.part.func_of(tgt)
        if tgt_fn == src_fn and tgt in self._addrs_sets[src_fn]:
            # tgt is actually decoded as part of this function — safe goto.
            return [f'goto {self.label(tgt)};']
        # If the owning function was rejected (invalid speculative code), fall
        # through to dispatch so the runtime can handle it at run time.
        if tgt_fn in self._rejected:
            return [f'traceEnter({ea._hex(src_addr)});',
                    f'dispatch({ea._hex(tgt)}); return;']
        owner = tgt_fn
        return [f'{self.fn(owner)}({ea._hex(tgt)}); return;']

    def _cc_of(self, mnem, prefix):
        return _CC[mnem[len(prefix):]]

    def _emit_flow(self, instr):
        m = instr.mnemonic
        a = instr.address
        nxt = instr.next_address

        if m == 'nop':
            return ['(void)0;']

        if m == 'bra':
            return self._transfer(a, instr.targets[0])

        if m.startswith('b') and m[1:] in _CC and m not in ('bra',):
            cc = _CC[m[1:]]
            body = self._transfer(a, instr.targets[0])
            return [f'if ({sem.cc_expr(cc)}) {{'] + \
                   [f'    {s}' for s in body] + ['}']

        if m in ('jmp',):
            if instr.indirect or not instr.targets:
                setup, addr = self._jump_address(instr)
                return setup + [f'traceEnter({ea._hex(a)});',
                                f'dispatch({addr}); return;']
            return self._transfer(a, instr.targets[0])

        if m in ('bsr', 'jsr'):
            call_sp = f'sp_{a:06x}'
            push = [f'm_long {call_sp} = cpu().ssp;',
                    f'cpu().ssp -= 4;',
                    f'memory().writeLong(cpu().ssp, LONG({ea._hex(nxt)}));']
            check_nonlocal_return = [
                f'if ((cpu().ssp & 0x00FFFFFFu) > ({call_sp} & 0x00FFFFFFu)) return;'
            ]
            if m == 'jsr' and (instr.indirect or not instr.targets):
                setup, addr = self._jump_address(instr)
                return push + setup + [f'traceEnter({ea._hex(a)});',
                                       f'dispatch({addr});'] + check_nonlocal_return
            tgt = instr.targets[0]
            if tgt in self.ins:
                owner = self.part.func_of(tgt)
                if owner not in self._rejected:
                    if owner == tgt:
                        return push + [f'{self.fn(owner)}();'] + check_nonlocal_return
                    return push + [f'{self.fn(owner)}({ea._hex(tgt)});'] + check_nonlocal_return
            return push + [f'traceEnter({ea._hex(a)});',
                           f'dispatch({ea._hex(tgt)});'] + check_nonlocal_return

        if m == 'rts':
            return [
                'cpu().ssp += 4;',
                'if ((cpu().ssp & 0x00FFFFFFu) > 0x00FFFF00u) {',
                '    std::fprintf(stderr, "[RTS] ssp=$%06X fn=$%06X\\n",',
                '                 static_cast<unsigned>(cpu().ssp & 0x00FFFFFFu),',
                '                 static_cast<unsigned>(lastFunction() & 0x00FFFFFFu));',
                '}',
                'return;',
            ]

        if m == 'rte':
            return ['cpu().setStatus(memory().readWord(cpu().ssp));',
                    'cpu().ssp += 6;',
                    'return;']

        if m == 'rtr':
            return ['cpu().setCCR(memory().readWord(cpu().ssp));',
                    'cpu().ssp += 6;',
                    'return;']

        if m.startswith('db'):
            suffix = m[2:]
            cc = 1 if suffix in ('f', 'ra') else _CC[suffix]
            reg = instr.eas[0].reg
            body = self._transfer(a, instr.targets[0])
            ctr = f'dbcc_{a:06x}'
            return [f'if (!({sem.cc_expr(cc)})) {{',
                    f'    m_word {ctr} = WORD((WORD(cpu().d[{reg}] & 0xFFFFu) - 1) & 0xFFFFu);',
                    f'    cpu().d[{reg}] = LONG((cpu().d[{reg}] & 0xFFFF0000u) | LONG({ctr}));',
                    f'    if ({ctr} != 0xFFFFu) {{'] + \
                   [f'        {s}' for s in body] + ['    }', '}']

        raise Unsupported(m)

    def _jump_address(self, instr):
        """(setup, expr) for the effective target address of an indirect jmp/jsr."""
        if not instr.eas:
            return [], 'cpu().pc'
        e = instr.eas[0]
        if e.mode == EAMode.ADDR_IND:
            return [], ea.areg(e.reg)
        try:
            return ea.address_of(e, TempPool(instr.address))
        except EAGenError:
            return [], ea._hex(e.abs_value or 0)

    # -- per-instruction emission --------------------------------------------

    def _emit_instr(self, instr):
        try:
            if instr.mnemonic in opcodes.FLOW_MNEMONICS:
                body = self._emit_flow(instr)
            elif instr.mnemonic == 'movem':
                body = self._emit_movem(instr)
            else:
                body = opcodes.emit_dataop(instr)
                if body is None:
                    raise Unsupported(instr.mnemonic)
        except (Unsupported, EAGenError) as exc:
            raise RuntimeError(
                f'cannot translate {instr} at ${instr.address:06X}: '
                f'{type(exc).__name__}: {exc}') from exc
        self.stats.handled += 1
        lines = []
        if self.part.needs_label(instr.address):
            lines.append(f'{self.label(instr.address)}:')
        lines.append(f'// ${instr.address:06X} {instr}')
        lines.append('{')
        lines.append('    BEFORE_INSTRUCTION')
        for stmt in body:
            lines.append(f'    {stmt}')
        lines.append('}')
        return lines

    # -- movem (register-list memory block transfer) --------------------------

    @staticmethod
    def _reg_index(tok: str) -> int:
        """Map ``dN`` / ``aN`` / ``sp`` to a unified 0..15 index (d0..d7, a0..a7)."""
        tok = tok.strip()
        if tok == 'sp':
            return 15
        if tok[0] == 'd':
            return int(tok[1])
        return 8 + int(tok[1])

    @staticmethod
    def _index_to_reg(i: int) -> tuple[bool, int]:
        if i < 8:
            return (False, i)
        n = i - 8
        return (True, 7 if n == 7 else n)

    @staticmethod
    def _parse_reglist(text):
        """'d0-d7/a0-a5' or 'd5-a4' → [(is_addr, n), …] in canonical order."""
        regs = []
        for group in text.split('/'):
            if '-' in group:
                lo, hi = group.split('-', 1)
                i0 = Generator._reg_index(lo)
                i1 = Generator._reg_index(hi)
                if i0 > i1:
                    i0, i1 = i1, i0
                for i in range(i0, i1 + 1):
                    regs.append(Generator._index_to_reg(i))
            else:
                regs.append(Generator._index_to_reg(Generator._reg_index(group)))
        return sorted(set(regs), key=lambda r: (r[0], r[1]))

    @staticmethod
    def _movem_regs(reg_ea):
        """Register list for a movem operand (REG_LIST, or a single Dn / An)."""
        if reg_ea.mode == EAMode.REG_LIST:
            return Generator._parse_reglist(reg_ea.reglist)
        if reg_ea.mode == EAMode.DATA_REG:
            return [(False, reg_ea.reg)]
        if reg_ea.mode == EAMode.ADDR_REG:
            return [(True, reg_ea.reg)]
        raise ValueError(f'movem register operand has mode {reg_ea.mode}')

    def _movem_reg_read(self, is_addr, n, size):
        if is_addr:
            ar = ea.areg(n)
            if size == 'w':
                return f'WORD({ar} & 0xFFFFu)'
            return ar
        return ea.read_dn(n, size)

    def _movem_reg_write(self, is_addr, n, size, value):
        if is_addr:
            ar = ea.areg(n)
            if size == 'l':
                return ea.write_areg_long(ar, value)
            return ea.write_areg_word(ar, value)
        if size == 'l':
            return ea.write_dn(n, 'l', value)
        # MOVEM memory→register sign-extends each word to 32 bits — Dn too.
        return ea.write_dn(n, 'l', ea.signext_to_long(value, 'w'))

    def _emit_movem(self, instr):
        size = instr.size or 'w'
        loads = {'b': 'memory().readByte', 'w': 'memory().readWord',
                 'l': 'memory().readLong'}[size]
        storem = {'b': 'memory().writeByte', 'w': 'memory().writeWord',
                  'l': 'memory().writeLong'}[size]
        nbytes = 4 if size == 'l' else 2
        tmp = TempPool(instr.address)

        # The memory side is the operand with a memory addressing mode; the
        # other operand is the register list (possibly a single register, which
        # the decoder classifies as DATA_REG/ADDR_REG rather than REG_LIST).
        mem_modes = {EAMode.ADDR_IND, EAMode.ADDR_POSTINC, EAMode.ADDR_PREDEC,
                     EAMode.ADDR_DISP, EAMode.ADDR_INDEX, EAMode.ABS_W,
                     EAMode.ABS_L, EAMode.PC_DISP, EAMode.PC_INDEX}
        if instr.eas[0].mode in mem_modes:
            mem, reg_ea, store = instr.eas[0], instr.eas[1], False
        else:
            mem, reg_ea, store = instr.eas[1], instr.eas[0], True
        regs = self._movem_regs(reg_ea)

        out = []
        if store and mem.mode == EAMode.ADDR_PREDEC:
            ar = ea.areg(mem.reg)
            init = None
            if (True, mem.reg) in regs:
                # 68000: when the base An is in the list, its *initial* value
                # is stored, not the partially-decremented one.
                init = tmp.fresh()
                out.append(f'm_long {init} = {ar};')
            for is_addr, n in reversed(regs):       # predec stores high→low
                out.append(f'{ar} -= {nbytes};')
                if init is not None and is_addr and n == mem.reg:
                    val = f'WORD({init} & 0xFFFFu)' if size == 'w' else init
                else:
                    val = self._movem_reg_read(is_addr, n, size)
                out.append(f'{storem}({ar}, {val});')
            return out
        if not store and mem.mode == EAMode.ADDR_POSTINC:
            ar = ea.areg(mem.reg)
            for is_addr, n in regs:
                v = tmp.fresh()
                out.append(f'm_{"long" if size == "l" else "word"} {v} '
                           f'= {loads}({ar});')
                out.append(f'{ar} += {nbytes};')
                out.append(self._movem_reg_write(is_addr, n, size, v))
            return out

        # Control addressing modes: sequential offsets from a fixed base.
        setup, addr = ea.address_of(mem, tmp)
        base = tmp.fresh()
        out += setup + [f'm_long {base} = {addr};']
        for off, (is_addr, n) in enumerate(regs):
            ea_expr = f'{base} + {off * nbytes}'
            if store:
                out.append(f'{storem}({ea_expr}, {self._movem_reg_read(is_addr, n, size)});')
            else:
                v = tmp.fresh()
                out.append(f'm_{"long" if size == "l" else "word"} {v} '
                           f'= {loads}({ea_expr});')
                out.append(self._movem_reg_write(is_addr, n, size, v))
        return out

    # -- function emission ----------------------------------------------------

    def _emit_function(self, func):
        out = [f'void Sor::{self.fn(func.entry)}(m_long entry_) {{']
        out.append(f'    traceEnter({ea._hex(func.entry)}); // diagnostic')
        return self._emit_function_body(func, out)

    def _emit_function_body(self, func, out):
        addrs = self._eff_addrs[func.entry]
        eff_set = self._addrs_sets[func.entry]
        # Only emit extra-entry goto cases for addresses that will actually be
        # emitted — phantom entries from speculative contamination are excluded.
        eff_extras = [t for t in sorted(func.extra_entries) if t in eff_set]
        if eff_extras:
            out.append('    switch (entry_) {')
            for t in eff_extras:
                out.append(f'        case {ea._hex(t)}: goto {self.label(t)};')
            out.append('        default: break;')
            out.append('    }')
        else:
            out.append('    (void)entry_;')
        for addr in addrs:
            out += [f'    {ln}' for ln in self._emit_instr(self.ins[addr])]
        # A function whose last instruction falls through (no RTS/RTE/BRA/JMP)
        # is hand-optimized 68000 code sharing a tail with whatever comes next
        # in ROM order — real hardware just keeps executing into it. Tail-call
        # the owning function instead of returning, so the original caller's
        # pushed return address gets popped by *that* function's eventual
        # rts/rte rather than leaking 4 bytes off the emulated 68k stack.
        last = self.ins[addrs[-1]]
        if last.flow in (FlowType.SEQUENTIAL, FlowType.CONDITIONAL, FlowType.CALL) \
                and last.next_address in self.ins:
            out += [f'    {ln}' for ln in self._transfer(func.addrs[-1], last.next_address)]
        else:
            out.append('    return;')
        out.append('}')
        return out


    # -- whole-program emission ----------------------------------------------

    def emit_header(self):
        decls = [f'    void {self.fn(e)}(m_long entry_ = {ea._hex(e)});'
                 for e in self.part.entries if e not in self._rejected]
        return _HEADER_TEMPLATE.format(decls='\n'.join(decls))

    def emit_source(self):
        boot = self.fn(self.part.func_of(0x000200))
        parts = [_SOURCE_PREAMBLE.format(cast_macros=sem.CAST_MACROS.strip(),
                                         rom_path=self.rom_path,
                                         boot_fn=boot)]

        # Pre-translate all functions; speculative-scope entries that fail are
        # excluded entirely — they decoded data as code and are not valid entry
        # points.
        # Non-speculative failures are real recompiler bugs and re-raise.
        bodies = {}
        rejected = set()
        for e in self.part.entries:
            try:
                bodies[e] = '\n'.join(self._emit_function(self.part.functions[e]))
            except Exception:
                if e in self._speculative_scope:
                    rejected.add(e)
                else:
                    raise

        if rejected:
            import sys
            print(f'[recompile] {len(rejected)} speculative entry(ies) rejected '
                  f'(invalid opcodes — treated as data, not code)', file=sys.stderr)

        # Expose rejected set so _transfer can route calls through dispatch instead
        # of generating direct C++ function calls to non-existent bodies.
        self._rejected = rejected
        # Re-translate: _transfer now knows which targets are rejected and emits
        # dispatch() for them so their callers still link correctly.
        bodies = {e: '\n'.join(self._emit_function(self.part.functions[e]))
                  for e in self.part.entries if e not in rejected}

        disp = ['void Sor::dispatch(m_long addr) {', '    switch (addr) {']
        for e in self.part.entries:
            if e not in rejected:
                if e in self._speculative:
                    disp.append(
                        f'        case {ea._hex(e)}: '
                        f'confirmSpeculative({ea._hex(e)}); {self.fn(e)}(); return;')
                else:
                    disp.append(f'        case {ea._hex(e)}: {self.fn(e)}(); return;')
        disp += ['        default: unhandledDispatch(addr); return;', '    }', '}']
        parts.append('\n'.join(disp))

        for e in self.part.entries:
            if e not in rejected:
                parts.append(bodies[e])

        return '\n\n'.join(parts) + '\n'


_HEADER_TEMPLATE = '''\
#pragma once

// Generated by tools/recompiler — do not edit by hand.
// Recompiled Streets of Rage cartridge as a MegaDriveEnvironment subclass.

#include "MegaDriveEnvironment.hpp"
#include <string>

class Sor : public MegaDriveEnvironment {{
    public:
    explicit Sor(const std::string &romPath,
                 VDP::Synchronization sync    = VDP::VSync,
                 VDP::Scaling         scaling = VDP::Integer);

    protected:
    void run() override;

    private:
    // Indirect-jump dispatch (jmp (an), computed jumps).
    void dispatch(m_long addr);
    void unhandledDispatch(m_long addr);

    // Cooperative interrupt delivery: 68000 exception entry + handler dispatch,
    // invoked before an instruction when an unmasked IRQ is pending.
    void serviceIRQ();

    // One method per recompiled subroutine entry.
{decls}
}};
'''

_SOURCE_PREAMBLE = '''\
// Generated by tools/recompiler — do not edit by hand.

#include "Sor.hpp"

#include <cstdint>
#include <cstdio>
#include <cstdlib>

{cast_macros}

Sor::Sor(const std::string &romPath, VDP::Synchronization sync,
         VDP::Scaling scaling)
    : MegaDriveEnvironment(sync, scaling) {{
    loadROM(romPath);
}}

void Sor::unhandledDispatch(m_long addr) {{
    // Delegated to the base class so the behaviour (abort, or record-and-exit
    // when --auxAddrFile is set) lives in hand-written, non-generated code.
    reportUnhandledDispatch(addr);
}}

void Sor::serviceIRQ() {{
    // Slow path: an unmasked interrupt is pending. Perform the 68000 autovector
    // exception entry, then dispatch the recompiled handler; its `rte` restores
    // the saved SR (and the previous IPL) and balances the stack.
    int level = irqLevel();
    if (level <= cpu().interruptMask())
        return; // raced with another service / masked
    clearInterrupt(level);
    m_word oldSR = cpu().status();
    cpu().ssp -= 4;
    memory().writeLong(cpu().ssp, 0); // return PC slot (native return drives flow)
    cpu().ssp -= 2;
    memory().writeWord(cpu().ssp, oldSR);
    // Stay in supervisor mode and raise the interrupt mask to this level.
    cpu().enterInterrupt(level);
    dispatch(memory().readLong(0x60 + LONG(level) * 4));
    if (level == 6) {{
        sound().endFrame();
    }}
}}

void Sor::run() {{
    // Reset: load the supervisor stack pointer from the reset vector, then
    // enter the ROM bootstrap. (The boot code itself reloads SR/registers.)
    cpu().ssp = memory().readLong(0x000000);
    {boot_fn}();
}}'''
