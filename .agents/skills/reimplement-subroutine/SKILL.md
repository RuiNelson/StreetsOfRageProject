---
name: reimplement-subroutine
description: >
  Manually reimplement a Streets of Rage recompiled 68000 subroutine as
  hand-written C++ (manual function): replace the generated body with native
  logic while keeping declarations, dispatch, and call sites. Use when asked to
  reimplement a subroutine, manual function, native port of a ROM routine,
  rewrite a generated Sor method by hand, replace busy-wait with host wait,
  or runs /reimplement-subroutine. Triggers: "reimplement", "manual function",
  "manual_functions.txt", "reimplementa", "subrotina", "native body".
---

# /reimplement-subroutine — Manual 68000 body

Replace a **generated** `Sor::…` body with hand-written C++ in
`StreetsOfRageRecompilation/`, without breaking call sites or `dispatch()`.

Work from **`StreetsOfRageRecompilation/`** (sibling: `../RageDecompiler`,
`../MegaDriveEnvironment`). Read that submodule’s `CLAUDE.md` before editing.

## When to reimplement

Good candidates:

- Tight spins / busy waits (`bra.s *`, poll loops) that should use
  `waitForInterrupt` / `waitForByteValue`
- Hot paths that do not need `BEFORE_INSTRUCTION` on every opcode
- Small helpers with clear semantics (lookups, queues, simple math)
- Cheat / host hooks that inject behavior the ROM never had

Avoid (or keep generated until proven):

- Full sound engine / channel sequencers
- Large, poorly labeled state machines
- Anything whose side effects on D/A/SR/memory are not understood

## Inputs

Identify the target from the user (name, address, or both), e.g.:

- `game_infinite_loop` / `$0003A2`
- label in `code-analysis/labels.csv`
- existing method in `generated/Sor.hpp`

If ambiguous, start with `output/sor.asm`, then use `labels.csv` and the exact
generated declaration/call sites to resolve the target before writing code.

## Workflow

### 1. Define the exact scope

For multi-routine requests, turn the user's document/table into an explicit
address + symbol inventory before coding. Treat an authoritative “related
code” table as the scope unless the user says that every mentioned callee must
also become manual. Record any scope interpretation in a progress update.

Check every target against `labels.csv`, ASM, the generated header, and the
dispatch table. A label alone does not prove that the disassembler/recompiler
currently recognizes the address.

### 2. Understand the ROM routine — ASM first

Use **`output/sor.asm` as the primary reasoning source**. It has much less
translation noise than generated C++ and exposes control flow, operand widths,
fall-through, flags, stack operations, and `org` gaps directly.

Read sources in this order:

| Source | What to extract |
|--------|-----------------|
| `output/sor.asm` | Real opcodes, labels, fall-through, nearby `org`, widths and flag-producing instructions |
| `code-analysis/labels.csv` + `addresses.csv` | Names, RAM symbols, confidence |
| ROM dump | Jump tables, data, and code hidden by an `org` gap (`xxd`) |
| `generated/Sor.hpp` / dispatch | Method name, default entry, recognized roots |
| `generated/Sor.cpp` | Folded entries, call sites, synthetic return PCs, and generator flag behavior when needed |

Do not begin by reading a large generated C++ body. After understanding the
ASM, inspect only the exact generated function/call-site ranges needed to
confirm the C++ ABI and recompiler partition.

Note:

- **Primary entry** (function address, e.g. `$3A2`)
- **Mid-entries** (`switch (entry_)` / `game_infinite_loop(0x0412u)`)
- **Return style**: normal `RTS` (`ssp += 4`) vs never-returns / tail-call only
- **Fall-through**: adjacent labels may share one 68k stack frame; an init
  wrapper can flow directly into its update handler without an `RTS`
- **Callees**: `jsr` → `CALL` / `CALL_DISPATCH` / other manuals
- **Condition-code contract**: callers may branch on Z/N/C/V left by a helper
- **Temporary stack data**: preserve word/long saves around nested calls
- **IRQ needs**: does a hang or poll require host interrupt wait?

If a documented jump-table target is absent from both `output/sor.asm` and the
generated dispatch/header:

1. Decode the jump-table entry and inspect the ROM bytes at the target.
2. Add the real subroutine root to `code-analysis/aux_addresses.txt`.
3. Regenerate and confirm that its declaration and dispatch case now exist.
4. Then register and implement it as manual.

### 3. Register the manual function

Add the **primary entry address** (hex, no `$`) to
`code-analysis/manual_functions.txt`:

```text
0003A2 # game_infinite_loop
```

One address per function entry the recompiler treats as a subroutine root.
Comments after `#` are fine.

Do **not** list mid-entry addresses separately unless they are their own
subroutine in the partition (rare). Mid-entries stay on the same method via
`entry_`.

### 4. Implement the body

Pick the file:

| Kind | File |
|------|------|
| General game logic | `SorManualFunctions.cpp` |
| Sound helpers only | `SoRSound.cpp` |
| Cohesive multi-routine feature | Dedicated file such as `SoRMainMenus.cpp` |

When adding a dedicated manual file, CMake's recursive source glob picks it up;
also update comments/docs that enumerate the manual source files.

Signature (must match generated header — do not edit `generated/Sor.hpp` by hand):

```cpp
void Sor::<name>(m_long entry_ = 0x….u);  // declaration stays generated
void Sor::<name>(m_long entry_) { … }     // body only in manual .cpp
```

#### Patterns

**A. Normal subroutine (called via soft stack, returns with RTS)**

```cpp
void Sor::example(m_long /*entry_*/) {
    traceEnter(0x……u);
    // … native logic using cpu(), memory() …
    cpu().ssp += 4;  // RETURN_68K equivalent
}
```

**B. Mid-entry**

```cpp
void Sor::example(m_long entry_) {
    if (entry_ == 0x……u) {
        traceEnter(0x……u);
        // alternate prologue
    } else {
        traceEnter(0xPRIMARY);
    }
    // …
    cpu().ssp += 4;
}
```

**C. Call another recompiled / manual method (soft `jsr`)**

Mirror generated `CALL` / `CALL_DISPATCH` (macros live only in `generated/Sor.cpp`):

```cpp
const auto call68k = [this](auto &&fn, m_long retPc) -> bool {
    const m_long spBefore = cpu().ssp;
    cpu().ssp -= 4;
    memory().writeLong(cpu().ssp, retPc);
    fn();
    // Callee did ssp += 4 on normal RTS. Abort if stack unwound past us.
    return (cpu().ssp & 0x00FFFFFFu) <= (spBefore & 0x00FFFFFFu);
};

if (!call68k([this] { other_fn(); }, 0xRET_PCu))
    return;
if (!call68k([this, addr] { dispatch(addr); }, 0xRET_PCu))
    return;
```

**D. Host-friendly wait (instead of busy spin)**

```cpp
memory().writeByte(mailbox, cmd);
cpu().setStatus(0x2500u);  // allow VBlank (IPL 6) if that is what the ROM did
memory().waitForByteValue(mailbox, 0, [this] {
    waitForInterrupt();
    if (irqLevel() > cpu().interruptMask())
        serviceIRQ();
    return !shouldQuit();
});
```

Infinite hang (`bra.s *`):

```cpp
while (!shouldQuit()) {
    waitForInterrupt();
    if (irqLevel() > cpu().interruptMask())
        serviceIRQ();
}
// No ssp += 4 if this path never RTS'd in the ROM / is tail-entered only
```

**E. IRQ policy (important)**

- Generated code runs `BEFORE_INSTRUCTION` before **every** opcode:
  `if (irqLevel() > mask) serviceIRQ(); pace();`
- Manual bodies may **batch** work without per-opcode IRQ checks when:
  - the routine is short setup, then calls something that waits/serves IRQs, or
  - callees still use generated `BEFORE_INSTRUCTION`
- **Never** leave a tight host loop that neither calls `waitForInterrupt` /
  `serviceIRQ` / a waiter nor returns — the VDP/IRQ thread will starve and
  quit may force `_Exit`.
- Prefer `shouldQuit()` on long loops so the window can close cleanly.

**F. Register and memory fidelity**

- Update `cpu().d[]` / `cpu().a[]` / SR when later code or IRQs can observe them
- Preserve flags when a caller branches immediately after the routine. A
  helper may communicate success through Z rather than a C++ return value
- Use `memory().read/writeByte|Word|Long` for cart/RAM/IO
- Sign-extend word offsets like the recompiler:  
  `static_cast<m_long>(static_cast<std::int16_t>(word))` (SEX_W)
- Preserve partial-register semantics. `move.w` keeps the high half of `Dn`;
  code may set a high-word bank bit before replacing the low word
- Prefer named `constexpr m_long` for well-known addresses (see existing manuals)

### 5. Regenerate and build

`generated/` is gitignored; bodies are stripped only after a full recompile:

```bash
cd StreetsOfRageRecompilation
./build.sh --full
```

Confirm:

- `[recompile] N function(s) supplied by hand-written C++` includes the new one
- The reported count increased by the number of newly registered roots
- `void Sor::<name>(` **body** is **not** in `generated/Sor.cpp`
- Declaration remains in `generated/Sor.hpp`
- `dispatch` / call sites still reference the method
- Newly added auxiliary jump-table targets have declarations and dispatch cases

Then fix compile errors in the manual `.cpp` only.

### 6. Smoke-test

Always wrap runs (boot hangs / SDL survival):

```bash
cd StreetsOfRageRecompilation
timeout -k 3 20 ./build.sh -r -- --runSor --debug --fast --rom rom/SOR.bin
# after:
pgrep -lf '[/]sor' || true   # must be empty
```

Watch debug lines: `mode($FF00)=…` (game_state), frame counter, `fn=$……`, sound.
If the reimplemented path is not on the boot path, exercise it (cheats, later
states) or add a focused check the user agrees on. Do not claim that a menu or
state was runtime-tested when the smoke run only reached an earlier boot mode;
report the last observed `game_state` and what remains unexercised.

### 7. Docs and publish

- Update the “currently manual” blurb in `StreetsOfRageRecompilation/README.md`
  if the set of manuals changed
- Commit **only** related files in the submodule (typical):
  - `code-analysis/manual_functions.txt`
  - the relevant manual `.cpp` file
  - `code-analysis/aux_addresses.txt` when a missing indirect target was added
  - `README.md` when needed
- Do **not** commit `generated/`, `rom/`, `build/`, `output/`
- Push submodule, then update + push the meta-repo gitlink
  (`StreetsOfRageProject`), per root `CLAUDE.md` publishing rules
- Obey the active confirmation policy for pushes to a default branch. If push
  is not authorized, leave clean local commits and report both hashes
- Leave unrelated dirty files alone

## Checklist (copy mentally)

- [ ] Exact address/symbol scope inventoried
- [ ] ASM understood first; generated C++ used only for ABI/partition checks
- [ ] Missing jump-table roots added to `aux_addresses.txt` when necessary
- [ ] Address in `manual_functions.txt`
- [ ] Body in the appropriate manual `.cpp`
- [ ] `traceEnter` at real entries
- [ ] `ssp += 4` on RTS paths; soft `call68k` when calling other 68k routines
- [ ] Fall-through/tail entries and caller-visible flags preserved
- [ ] Partial registers and temporary stack saves preserved
- [ ] No IRQ-starving busy loops
- [ ] `./build.sh --full` succeeds; count, declarations, dispatch, and body omission checked
- [ ] `timeout -k` smoke run; actual reached state reported; no leftover `sor` process
- [ ] README + submodule commit/push + meta gitlink

## References

- `references/patterns.md` — CALL/IRQ/return cheat sheet and file map
- Live examples: `SorManualFunctions.cpp`, `SoRSound.cpp`,
  `code-analysis/manual_functions.txt`
- Recompiler behavior: `RageDecompiler/tools/recompiler/generator.py`
  (`manual_functions` skips body emit, keeps decl/dispatch/calls)
