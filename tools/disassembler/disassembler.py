"""Recursive-descent disassembler for the Streets of Rage ROM."""

import sys
import warnings
from collections import deque

from .decoder import DecodeError, InstructionDecoder
from .instruction import FlowType, Instruction
from .rom import ROM


class Disassembler:
    """Recursive-descent 68000 disassembler for Streets of Rage.

    The algorithm starts from a set of seed addresses (reset vector,
    VBlank IRQ handler, and any addresses in the auxiliary file) and
    walks all reachable code, recursively following control-flow edges
    until every path terminates (RTS/RTE/RTR/ILLEGAL) or merges into
    already-decoded territory.

    Control-flow classification (:class:`FlowType`)
    ===============================================
    Each decoded instruction carries a ``flow`` attribute that determines
    how the disassembler continues after it:

    :SEQUENTIAL:  Continue to the next address (``.next_address``).
    :CALL:        Follow the target as a new subroutine, then continue
                  sequentially (used for JSR/BSR).
    :BRANCH:      Follow the target as a label, then stop this path
                  (used for JMP, BRA).
    :CONDITIONAL: Follow both the target and the fall-through path
                  (used for Bcc).
    :RETURN:      Stop this path — no further instructions follow
                  (used for RTS, RTE, RTR, ILLEGAL, TRAP).

    Indirect control flow
    =====================
    When a JSR or JMP uses an addressing mode whose target cannot be
    resolved statically (e.g. ``jmp (a0)`` or ``jsr $1234(a5,d0.w)``),
    the instruction is flagged with ``indirect=True`` and its address
    is appended to :attr:`indirect_warnings`.  The disassembler continues
    past the instruction but cannot follow that path.

    Seed addresses
    ==============
    :attr:`ENTRY_POINT`  — Reset vector, ROM offset 0x004–0x007.
                            In the Streets of Rage ROM this points to 0x000208.
    :attr:`VBLANK_ENTRY` — Level-6 IRQ vector, ROM offset 0x078–0x07B.
                            In the Streets of Rage ROM this points to 0x019D16.

    The auxiliary address file (optional) lists additional subroutine entry
    points that cannot be discovered statically (e.g. functions called
    through function-pointer tables).

    After calling :meth:`disassemble`, the following are available:

    * :attr:`instructions` — ``{addr: Instruction}`` for every decoded word
    * :attr:`subroutines`  — set of addresses identified as subroutine entries
    * :attr:`labels`       — set of branch/jump target addresses
    * :attr:`indirect_warnings` — addresses of unresolvable indirect jumps/calls
    """

    # Hard-coded seed addresses extracted from the Streets of Rage ROM header
    ROM_HEADER   = 0x000200   # ROM header / reset bootstrap (always seed)
    ENTRY_POINT  = 0x000208   # Reset vector  (ROM offset 0x004–0x007)
    VBLANK_ENTRY = 0x019D16   # Level-6 IRQ   (ROM offset 0x078–0x07B)

    def __init__(self, rom: ROM,
                 aux_addresses: list[int] | None = None,
                 verbose: bool = False) -> None:
        self.rom      = rom
        self.verbose  = verbose
        self._decoder = InstructionDecoder(rom)

        self.instructions:       dict[int, Instruction] = {}
        self.subroutines:        set[int]               = set()
        self.labels:             set[int]               = set()
        self.indirect_warnings:  list[int]              = []

        self._queue: deque[int] = deque()

        # Seed — also trace the ROM header bootstrap (NOP/NOP/BRA to entry)
        for addr in (self.ROM_HEADER, self.ENTRY_POINT, self.VBLANK_ENTRY):
            self._enqueue_sub(addr)

        for addr in (aux_addresses or []):
            self._enqueue_sub(addr)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def disassemble(self) -> None:
        """Run the recursive-descent algorithm until the queue is empty."""
        while self._queue:
            addr = self._queue.popleft()
            self._trace(addr)

        if self.verbose:
            n = len(self.instructions)
            print(f'[disasm] {n} instructions decoded, '
                  f'{len(self.subroutines)} subroutines, '
                  f'{len(self.labels)} labels',
                  file=sys.stderr)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enqueue_sub(self, addr: int) -> None:
        self.subroutines.add(addr)
        if addr not in self.instructions:
            self._queue.append(addr)

    def _enqueue_label(self, addr: int) -> None:
        self.labels.add(addr)
        if addr not in self.instructions:
            self._queue.append(addr)

    def _trace(self, start: int) -> None:
        """Decode sequentially from *start* until a terminal instruction."""
        addr = start
        while True:
            if not self.rom.in_bounds(addr, 2):
                warnings.warn(f'Trace left ROM bounds at ${addr:06X}')
                break

            if addr & 1:
                warnings.warn(f'Odd address ${addr:06X} — alignment error')
                break

            if addr in self.instructions:
                # Already decoded — this path merges into known code
                break

            try:
                instr = self._decoder.decode(addr)
            except (DecodeError, Exception) as exc:
                warnings.warn(f'Decode error at ${addr:06X}: {exc}')
                break

            self.instructions[addr] = instr

            # ---- Process control-flow targets ----
            if instr.indirect:
                self.indirect_warnings.append(addr)

            for tgt in instr.targets:
                if not self.rom.in_bounds(tgt, 2) or (tgt & 1):
                    continue
                if instr.flow == FlowType.CALL:
                    self._enqueue_sub(tgt)
                else:
                    self._enqueue_label(tgt)

            # ---- Decide whether to continue sequentially ----
            if instr.flow in (FlowType.SEQUENTIAL,
                              FlowType.CALL,
                              FlowType.CONDITIONAL):
                addr = instr.next_address
            else:
                # BRANCH or RETURN — this path ends here
                break
