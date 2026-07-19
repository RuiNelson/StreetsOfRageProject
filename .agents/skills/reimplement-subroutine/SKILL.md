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

If ambiguous, search `labels.csv`, `output/sor.asm`, and `generated/Sor.cpp`
before writing code.

## Workflow

### 1. Understand the ROM routine

Gather **all** of:

| Source | What to extract |
|--------|-----------------|
| `output/sor.asm` | Real opcodes, labels, nearby `org` |
| `generated/Sor.cpp` body | Current C++ translation, mid-entries, CALL targets |
| `code-analysis/labels.csv` + `addresses.csv` | Names, RAM symbols, confidence |
| ROM dump if needed | Jump tables / data (`xxd` / Python `struct`) |

Note:

- **Primary entry** (function address, e.g. `$3A2`)
- **Mid-entries** (`switch (entry_)` / `game_infinite_loop(0x0412u)`)
- **Return style**: normal `RTS` (`ssp += 4`) vs never-returns / tail-call only
- **Callees**: `jsr` → `CALL` / `CALL_DISPATCH` / other manuals
- **IRQ needs**: does a hang or poll require host interrupt wait?

### 2. Register the manual function

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

### 3. Implement the body

Pick the file:

| Kind | File |
|------|------|
| General game logic | `SorManualFunctions.cpp` |
| Sound helpers only | `SoRSound.cpp` |

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
- Use `memory().read/writeByte|Word|Long` for cart/RAM/IO
- Sign-extend word offsets like the recompiler:  
  `static_cast<m_long>(static_cast<std::int16_t>(word))` (SEX_W)
- Prefer named `constexpr m_long` for well-known addresses (see existing manuals)

### 4. Regenerate and build

`generated/` is gitignored; bodies are stripped only after a full recompile:

```bash
cd StreetsOfRageRecompilation
./build.sh --full
```

Confirm:

- `[recompile] N function(s) supplied by hand-written C++` includes the new one
- `void Sor::<name>(` **body** is **not** in `generated/Sor.cpp`
- Declaration remains in `generated/Sor.hpp`
- `dispatch` / call sites still reference the method

Then fix compile errors in the manual `.cpp` only.

### 5. Smoke-test

Always wrap runs (boot hangs / SDL survival):

```bash
cd StreetsOfRageRecompilation
timeout -k 3 20 ./build.sh -r -- --runSor --debug --fast --rom rom/SOR.bin
# after:
pgrep -lf '[/]sor' || true   # must be empty
```

Watch debug lines: `mode($FF00)=…` (game_state), frame counter, `fn=$……`, sound.
If the reimplemented path is not on the boot path, exercise it (cheats, later
states) or add a focused check the user agrees on.

### 6. Docs and publish

- Update the “currently manual” blurb in `StreetsOfRageRecompilation/README.md`
  if the set of manuals changed
- Commit **only** related files in the submodule (typical):
  - `code-analysis/manual_functions.txt`
  - `SorManualFunctions.cpp` and/or `SoRSound.cpp`
  - `README.md` when needed
- Do **not** commit `generated/`, `rom/`, `build/`, `output/`
- Push submodule, then update + push the meta-repo gitlink
  (`StreetsOfRageProject`), per root `CLAUDE.md` publishing rules
- Leave unrelated dirty files alone

## Checklist (copy mentally)

- [ ] ASM + generated body + mid-entries understood
- [ ] Address in `manual_functions.txt`
- [ ] Body in `SorManualFunctions.cpp` or `SoRSound.cpp`
- [ ] `traceEnter` at real entries
- [ ] `ssp += 4` on RTS paths; soft `call68k` when calling other 68k routines
- [ ] No IRQ-starving busy loops
- [ ] `./build.sh --full` succeeds; body omitted from generated
- [ ] `timeout -k` smoke run; no leftover `sor` process
- [ ] README + submodule commit/push + meta gitlink

## References

- `references/patterns.md` — CALL/IRQ/return cheat sheet and file map
- Live examples: `SorManualFunctions.cpp`, `SoRSound.cpp`,
  `code-analysis/manual_functions.txt`
- Recompiler behavior: `RageDecompiler/tools/recompiler/generator.py`
  (`manual_functions` skips body emit, keeps decl/dispatch/calls)
