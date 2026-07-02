"""Partition decoded instructions into C++ functions.

A *function* spans from a subroutine/call entry up to the next entry, so that
sequential code and intra-function branches (including back-edges) stay inside
one function — loops therefore stay as ``goto``/``while``, never recursion
through native calls.

Transfers are classified:

* **intra-function** (target in the same function)  → ``goto`` to a local label;
* **cross-function to another entry**                → native call to that fn;
* **cross-function into the middle** of a function   → native call carrying the
  target address; the callee routes it via an entry ``switch`` trampoline.
  Such mid-function targets are recorded as extra entry points of the owning
  function.
"""

import bisect
from dataclasses import dataclass, field

from tools.disassembler.instruction import FlowType


@dataclass
class Function:
    entry:    int                       # base entry address (lowest)
    addrs:    list = field(default_factory=list)   # sorted instruction addresses
    extra_entries: set = field(default_factory=set)  # cross-function mid-entries


@dataclass
class Partition:
    functions:   dict          # entry addr -> Function
    entries:     list          # sorted entry addresses
    goto_labels: set           # addresses reached by an intra-function goto
    instructions: dict         # {addr: Instruction}

    def func_of(self, addr: int) -> int:
        """Entry address of the function that owns ``addr`` (or None)."""
        i = bisect.bisect_right(self.entries, addr) - 1
        return self.entries[i] if i >= 0 else None

    def needs_label(self, addr: int) -> bool:
        """True if ``addr`` must carry a C label (goto target or mid-entry)."""
        if addr in self.goto_labels:
            return True
        f = self.functions.get(self.func_of(addr))
        return f is not None and addr in f.extra_entries


def partition(instructions: dict, subroutines: set) -> Partition:
    """Build the function partition from decoded instructions.

    ``subroutines`` are the disassembler's identified entries (reset/IRQ seeds,
    aux addresses, and JSR/BSR targets). Any decoded instruction is also a
    fall-back entry boundary only through those; everything else is owned by the
    nearest preceding entry.
    """
    # Entries: known subroutines that actually decoded, always including the
    # lowest decoded address so every instruction is owned.
    entries = sorted(a for a in subroutines if a in instructions)
    if not entries or entries[0] != min(instructions):
        entries = sorted(set(entries) | {min(instructions)})

    functions = {e: Function(entry=e) for e in entries}
    for addr in sorted(instructions):
        i = bisect.bisect_right(entries, addr) - 1
        functions[entries[i]].addrs.append(addr)

    part = Partition(functions=functions, entries=entries,
                     goto_labels=set(), instructions=instructions)

    # Classify every static transfer to populate goto labels and mid-entries.
    for addr, instr in instructions.items():
        if instr.flow not in (FlowType.BRANCH, FlowType.CONDITIONAL):
            continue
        fsrc = part.func_of(addr)
        for tgt in instr.targets:
            if tgt not in instructions:
                continue
            ftgt = part.func_of(tgt)
            if ftgt == fsrc:
                part.goto_labels.add(tgt)            # intra-function goto
            elif tgt != ftgt:
                functions[ftgt].extra_entries.add(tgt)  # mid-function entry

    return part
