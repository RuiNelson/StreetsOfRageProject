# Static 68K → C++ recompiler — design

> **Status:** implemented. The generator (`tools/recompiler/`) translates 100%
> of the active-disassembly-reachable ROM into `src/generated/Sor.{hpp,cpp}`,
> which builds in-tree. See the "Current status" note in §8 for what remains
> (an entry point + behavioural validation). This document is both the design
> and the record of what was built.

## Context

The repo can already disassemble the SoR ROM into structured 68000 instructions
(`tools/disassembler/`) and run Mega Drive hardware natively via
`MegaDriveEnvironment` subclasses whose `run()` is hand-written C++
(`src/system/`). The next goal is to **mechanically translate the disassembled
ROM into a C++ `run()`** so the actual game logic executes natively against the
existing VDP / memory / controllers / etc.

This is a **static binary recompiler** (same genre as the N64 static-recomp
projects). The naive framing — "a macro per opcode, one method per label, parse
`output/sor.asm` as text" — does not survive contact with how 68K code actually
behaves. This document records the corrected architecture and an incremental,
verifiable roadmap so the risky parts are proven on a small slice before scaling
to ~21k lines of assembly.

## Key decisions at a glance

- **Input:** consume the disassembler's structured `Instruction` objects, not the
  text `.asm` (§1).
- **Control flow:** **small functions** (roughly per-region / per-label), not one
  giant function. Fall-through and forward branches become native calls;
  **back-edges (loops) stay as `goto`/`while` inside a single function and are
  never function calls** — this is the fix for infinite loops (§3).
- **Indirect transfers:** runtime **68K-address → label dispatch table** (§4).
- **Interrupts:** the handler is the game's own recompiled code; entry simulates
  the 68K exception (push SR+PC, mask IPL) and `rte` undoes it; checked before
  each instruction via a cheap atomic flag gated by the IPL (§5b).
- **Helpers:** opcode semantics are emitted as direct C++ statements. The only
  generated macros are one-line cast shorthands (`BYTE`, `WORD`, `LONG`) used to
  reduce visual noise around `static_cast` (§2d).
- **Verification:** primary = **run the game**; safety net = **unit tests of the
  EA + flag/CCR core** (§7).
- **Memory:** `SystemMemory` owns mirroring/masking; `convertAddress` masks all
  addresses to 24 bits (§6).

---

## 1. Input: reuse the decoder, do NOT parse text `.asm`

The disassembler already yields structured `Instruction` objects
(`tools/disassembler/instruction.py`): `mnemonic`, `size`, `operands`
(`str | Addr`), `flow` (`FlowType`), resolved `targets`, and an `indirect` flag.

- Add a **`CppFormatter`** alongside `AsmFormatter` (`tools/disassembler/
  formatter.py`) that consumes the same `Instruction` stream and emits C++.
- **Problem to solve:** current operands are *already symbolized strings*
  (`(mem_ram_+$FF40).w`, `boot_vdp_copy_loop`). For codegen we need **structured
  operands** (addressing mode + register + displacement + resolved absolute
  value), not pre-rendered text. → The decoder must expose structured EAs
  (effective addresses) to the C++ formatter. Plan: enrich the operand model (or
  have the decoder retain the raw EA fields) so the C++ path never reparses text.
  The existing `Addr` dataclass already carries `value`/`form`/`suffix`; extend
  the same idea to *all* operands.
- **Completeness depends on active disassembly.** Static following misses
  anything reached only via indirect jumps. The generator must seed its
  reachable-target set from `etc/sor-exodus.asm` / `aux_addresses.txt`, not just
  the static `output/sor.asm`. (327 indirect `jmp/jsr` sites exist; see §4.)

---

## 2. The two code generators that matter (not "a macro per opcode")

The opcode is the easy axis. The hard axes are **addressing modes** and **flags**.

### 2a. Effective-address (EA) read/write codegen

One mnemonic has ~12 source × ~9 destination operand forms. A uniform
`MOVE(src,dst)` form cannot express that `(a0)+` has a post-increment side effect
while `d0` does not. Instead the generator emits, per EA, the correct C++:

| 68K EA | Read expr | Write target | Side effect |
|---|---|---|---|
| `Dn` / `An` | `cpu().d[n]` / `cpu().a[n]` | same | — |
| `(An)` | `memory().readX(cpu().a[n])` | `memory().writeX(cpu().a[n], …)` | — |
| `(An)+` | read then `cpu().a[n]+=sz` | write then `+=sz` | post-inc |
| `-(An)` | `cpu().a[n]-=sz` then read | pre-dec then write | pre-dec |
| `d16(An)`, `d8(An,Xn)` | `memory().readX(addr_expr)` | write to addr_expr | — |
| `(xxx).w/.l` | absolute, baked at gen time | — | — |
| `d16(PC)`, `d8(PC,Xn)` | **PC resolved to absolute at gen time** | (read-only) | see §6 |
| `#imm` | literal | n/a | — |

Reads/writes are **size-aware** (`b`/`w`/`l`) — `move.b` touches only the low
byte of `Dn`; `(An)` reads use `readByte/readWord/readLong`.

**Sub-register writes are read-modify-merge, not assignment.** `move.w d0,d1`
changes only the low 16 bits of `d1`; `addq.b` only the low 8. EA writes to a
register go through size-specific helpers (`setDn_w`, `setDn_b`, …) that merge,
never a full `=`.

**Sequencing is solved by the generator, not by macros.** `move.l (a0)+,(a0)+`
touches `a0` twice; the 68K evaluates the source EA fully (incl. its
post-increment) before the destination. The generator emits **explicit sequenced
statements with temporaries** — `auto src = <read+incr>; <write dst using updated
a0>;` — never a single expression (which would be UB, and which a
double-evaluating preprocessor macro would get wrong). This is the concrete
reason the EA layer is a code generator, and why the operation/flag helpers
(§2b/§2c) act on already-materialized temporaries.

### 2b. CCR flag codegen (where the bugs live)

Most ALU ops set N/Z/V/C/X in **size-dependent** ways on the truncated result.
`CPU68K` already has `setCVZN`, `setFlagX`, etc. The generator emits the correct
flag computation per (mnemonic, size). This is the highest-risk surface and gets
its own unit tests (§7). Helper methods may be added to `CPU68K` to keep emitted
code compact, e.g. `setNZ_b/w/l(result)`, add/sub carry+overflow helpers.

### 2c. Special-case instruction helpers (tested individually)

A handful of instructions are not "simple EA + op" and get **dedicated,
unit-tested inline helpers** rather than generic codegen:

- **`dbcc`/`dbf`** — decrements only the **word** of `Dn` and terminates at
  **−1** (not 0). Classic off-by-one; pervasive in loops.
- **`movem`** — pushes/restores a register list in a fixed order, and that order
  **differs** between pre-decrement and post-increment; updates the address reg.
- **`abcd`/`sbcd`/`nbcd`** (BCD) and **`divu`/`divs`/`mulu`/`muls`** — SoR does
  **not** use BCD or div/mul, so these are low-priority; a helper with correct
  flags (and the div-by-zero exception, vector 5) is written only if coverage
  ever reaches them.

### 2d. Direct opcode semantics

`cpp_semantics.py` emits the arithmetic, logical, shift/rotate, BCD, multiply /
divide, special-register, and CCR-update statements directly into `Sor.cpp`.
Effective-address expansion (read, write, read-modify-write, `(An)+` side
effects) is emitted by `opcodes.py` + `ea_codegen.py`; the generated cartridge
therefore reads an operand, runs the C++ semantics on an already-materialized
temporary, then writes the result back when needed.

The generated source still defines exactly three macros from a raw string:
`BYTE(v)`, `WORD(v)`, and `LONG(v)`. They are one-line `static_cast` shorthands
for readability only; they do not carry instruction semantics or side effects.

The classic macro hazard — re-evaluating an argument that has a side effect — is
removed structurally: opcode behaviour is plain C++, and the generator
**materializes every effective address into a plain temporary first** (§2a).
Read-modify-write operands (`(An)+`, `-(An)`) go through `rmw_ea`, which computes
the address once and auto-increments once.

---

## 3. Control-flow model: small functions, loops stay as loops

Goal: **small, readable functions** rather than one giant function — but correct
under the two things SoR does pervasively that break naive schemes:

- **Fall-through** (a label is both a branch target *and* fallen into from above).
- **Infinite / counted loops** (`game_infinite_loop: … bra game_infinite_loop`,
  and every `dbf`).

### The decisive rule: a back-edge is never a function call

If a backward `bra`/`bcc` (a loop) became a function call, an infinite loop would
become **infinite recursion → stack overflow**, and C++ gives **no portable
tail-call guarantee** (`[[clang::musttail]]` is non-standard and conditional).
Therefore:

- **Back-edges (loops) stay as `goto`/`while` inside one function.** Function
  boundaries are chosen so that every loop (every cycle / SCC of the control-flow
  graph) is **entirely contained** in a single function. The game's top-level
  infinite loop becomes the **outer `while` of `run()`**.
- **Forward fall-through to another block** → a native call to that block's
  function, then `return` (the chain unwinds naturally).
- **Forward `bra`/`bcc` to another region** → native call (conditional: inside
  `if (cond) { f(); return; }`).
- **Intra-function branches** (including all back-edges) → `goto Llabel;` /
  `if (cond) goto Llabel;`, CCR read via `cpu().flagZ()` etc.

### Consequences that must hold

- **Registers/flags live in `cpu()`** (the `CPU68K` member), never in locals —
  they must survive across the function-call boundaries above.
- **Synthetic continuation calls push *nothing* on the emulated SSP** — only real
  `jsr`/`bsr` do (§5a). So code that inspects the 68K stack sees exactly the
  hardware picture; native stack depth ≠ emulated stack depth, which is fine.
- A block that is *both* a fall-through target and a `jsr` target is still one
  function; the distinction is only whether the *caller* pushed the SSP.

---

## 4. Indirect dispatch (327 sites — unavoidable)

`jmp (a0)`, `jsr (a5)`, and computed tables (`jmp $00044C(pc,d0.w)`) cannot be
resolved statically.

- Build a **dispatch table**: `68K address → {function ptr or label token}`,
  populated from the reachable-target set (static + active disasm).
- `jmp (an)` → `dispatch(cpu().a[n])` (tail-transfer); `jsr (an)` →
  `call_dispatch(cpu().a[n])`.
- Computed `jmp d(pc,Dn)` → the table base is known at gen time; emit a read of
  the table entry from ROM/`memory()` then `dispatch(entry)`.
- Targets that are mid-region need a secondary entry mechanism (a per-region
  `switch` on entry address, or split the region). Default: address-keyed
  `switch` trampoline.

---

## 5a. JSR / RTS / stack model

`jsr → native C++ call` is the default and works **only if every matching `rts`
just returns**. Two facts complicate this:

- **`rts`-based dispatch:** code may push a computed address and `rts` to "jump",
  or pop/modify the return address. The native call/return model breaks there.
- **A7/SSP is a real RAM pointer:** `movem` register saves, `-(a6)` stacks, etc.
  read/write through it. So the **emulated 68K stack must live in SystemMemory**
  regardless of the native call stack.

Adopted model:

- `jsr/bsr` pushes the return PC onto the **emulated** SSP (`cpu().ssp -= 4;
  memory().writeLong(cpu().ssp, retAddr)`) **and** makes the native call.
- Plain `rts` pops the emulated stack and `return`s natively (the two stay in
  sync as long as the routine is balanced).
- **`rts`-dispatch routines** (detected: a routine whose `rts` consumes a value it
  computed/modified, not the one `jsr` pushed) are flagged by the generator and
  lowered to the **dispatch path** (§4) instead of native return. These are
  enumerated as a known special-case list, seeded from active-disasm analysis.

---

## 5b. Interrupt model

The interrupt handler **is the game's own recompiled code** (VBlank entry
`0x019D16`); it uses the same `cpu()` registers and the same emulated stack, and
ends in `rte`. To make that work under this project's *cooperative* interrupt
model (handlers run on the `run()` thread, never async — see CLAUDE.md):

- **Where interrupts fire:** the generator inserts an interrupt check **before
  each instruction**. This is semantically *more* faithful than real hardware
  (which fires between instructions), so it is correct; the only concern is cost.
- **Cheap check, not a mutex drain per instruction:** the VDP render thread sets
  an **atomic `irqPending` flag** (plus the pending level). The per-instruction
  check is `if (irqPending && cpu().intLevel() < level) deliverInterrupt();` — one
  atomic load in the common (no-IRQ) case. Only then is the queue drained.
- **IPL gate is mandatory, not optional:** boot runs at IPL 7 (`sr = 0x2700`);
  delivering VBlank there would corrupt start-up. Delivery honours
  `cpu().intLevel()` vs the interrupt's level (VBlank = 6, HBlank = 4).
- **Exception entry simulates the 68K:** on delivery, push SR then PC onto the
  **emulated SSP**, set S, raise the IPL mask to the interrupt level, then call
  the handler function (via §4 dispatch on the vector address).
- **`rte`** → pop SR (restores the previous IPL/CCR) and PC from the emulated SSP,
  then `return`. This is why the handler's stack manipulation and any `movem`
  save/restore inside it "just work".

---

## 6. PC-relative, data-vs-code, ROM loading

- **PC-relative *data* reads** (`move.l $0003BA(pc,d0.w), d0`): the disassembler
  already resolves PC to an absolute address (`Addr.value`). Emit an **absolute
  `memory().readX(base + index)`** — "PC" is not a live register in recompiled
  code. This is why the **whole ROM must be resident** in SystemMemory.
- **PC-relative *jump tables*** → dispatch (§4), not data reads.
- **ROM-loading constructor:** `MegaDriveEnvironment` (or the SoR subclass) gains
  a constructor taking the ROM path; it loads the entire image into
  `SystemMemory` ROM region (`0x000000–0x3FFFFF`) via the existing
  `writeFromBuffer`. Reset vector (`0x000000` SSP, `0x000004` PC) is read from the
  loaded image by the generated boot code, exactly as the asm does.
- **Data interleaved with code:** `output/sor.asm` uses 362 `org` gaps where data
  was stripped. The generator emits code only for instruction regions; data is
  reached purely as memory reads against the resident ROM — never translated.
- **24-bit address normalization (in `SystemMemory`):** registers (`a[n]`) are
  32-bit but the 68K bus is 24-bit. Today `convertAddress` masks only the high
  mirror (`>= 0xFF000000`). Extend it to mask **every** address to 24 bits
  (`& 0xFFFFFF`) so register-derived addresses with stray high bits normalize, and
  the work-RAM mirror (`0xFFFF0000 → 0xFF0000`) keeps working. This keeps masking
  out of the generated code — it is the memory layer's job.

---

## 7. Verification strategy (lightweight)

Primary verification is **running the game** and watching behaviour — no
per-region Genesis-Plus-GX state-diffing harness.

But playtesting alone is weak for the highest-frequency bug class: a wrong CCR bit
at one of hundreds of flag sites usually does **not** fail visibly — it diverges
the RNG / a specific enemy's AI / a counter, surfacing rarely and far from the
cause. So the safety net is:

1. **Unit-test the EA + flag/CCR core (§2) in isolation.** Small, deterministic,
   covers the instruction types × 3 sizes plus the special-case helpers (§2c).
   This is cheap and catches the bugs that playtesting cannot localize.
2. **Run the game** as the integration test, region by region as coverage grows.
3. `etc/sor-exodus.asm` remains the **reachable-address ground truth** (which code
   runs) — it seeds the dispatch table and coverage, not behaviour.

(Genesis-Plus-GX stays available as an *ad-hoc* reference if a specific divergence
needs pinning down, but is not part of the routine workflow.)

**Note (2026-07-02):** the old `M68KMacros.hpp` source of truth was removed.
`tests/test_codegen.py` now checks direct C++ lowering and generated-source
shape, and semantic regressions should be covered by generator tests or runtime
behaviour tests against the generated `Sor.cpp`.

---

## 8. Proposed component layout

```
tools/recompiler/
  DESIGN.md            ← this document
  cpp_semantics.py     ← direct opcode/CCR C++ snippets + cast macro raw string
  ea_codegen.py        ← per-addressing-mode read/write/address/RMW emitters (temps)
  opcodes.py           ← data-op lowering; composes EA code with direct semantics
  regions.py           ← partition into small functions; each loop fully contained
  generator.py         ← control-flow lowering, movem, dispatch table, Sor emit
  main.py / __main__.py← CLI; consumes decoder + active-disasm seeds
  tests/test_codegen.py
src/generated/
  Sor.hpp/.cpp         ← MegaDriveEnvironment subclass; generated run() + regions
```

The decoder is **extended** to expose structured operands; `AsmFormatter` is
untouched. Run the generator with:

```
python3 -m tools.recompiler rom/SOR.bin -o src/generated
```

It consumes the same `code-analysis/` inputs as `disassemble.sh`:
`aux_addresses.txt` seeds the indirect-jump targets (so the **full call graph**
is reached, not just the statically-reachable code), and `labels.csv` /
`addresses.csv` give the generated functions their **real names** (`init`,
`level_flow_handler`, …) instead of `sub_XXXXXX`.

**Current status.** The pipeline is implemented end-to-end and translates
**100%** of the reachable code seeded from the active disassembly — **15647
instructions / 950 functions** — every opcode, including shifts, rotates,
`movem`, `mulu/muls/divu/divs`, `exg`, BCD (`abcd/sbcd/nbcd`), `negx`, `Scc`,
bit ops, and `move` to/from SR/CCR/USP. There are **no stubs**: an opcode the
generator cannot translate is a hard error (it never silently degrades). The
generated `Sor.cpp` compiles cleanly (`-Wall -Wextra`) and is built as part of
the project.

Interrupt delivery (§5b) is wired: every instruction is preceded by a direct IPL
compare, and when an unmasked IRQ is pending `serviceIRQ()` performs the 68000
autovector exception entry and dispatches the recompiled handler.

It **runs without crashing**: `./build.sh && src/build/sor --runSor` boots
through the cartridge hardware init (TMSS, VDP register setup, CRAM/VRAM clear,
RAM clear, Z80 init — via the memory-mapped hardware routing in `SystemMemory`,
§6) and runs the game loop continuously, presenting frames through the VDP.

Reaching that required **PC-relative `bra.s` jump-table discovery** (in
`main.py`): a `jmp d(pc,Dn)` lands on a table of 2-byte `bra.s` entries that
static following never decodes; the recompiler scans each such table, seeds the
entries, and re-disassembles to a fixpoint (entries become dispatchable). That
closed the last reachability gap that stopped execution.

Remaining work is the §7 validation phase: confirm the rendered output is
correct, then chase behavioural divergences (flag/RNG/timing) as they surface.
Known not-yet-handled idioms that may need attention later: register-indexed
jump tables (`jmp d(An,Xn)` — base unknown statically) and word-offset tables
whose entries were never exercised in the capture.

---

## 9. Staged roadmap (build order)

1. **ROM-loading constructor** (small, independently useful, low risk).
2. **EA + CCR core** as hand-written, unit-tested `CPU68K` helpers + Python
   emitters; verified against 68K semantics.
3. **Enrich decoder operands** (structured EAs) without disturbing `AsmFormatter`.
4. **Proof-of-concept:** generate the boot region only; validate the loop/goto +
   small-function + stack + dispatch + interrupt model end-to-end by running it
   (boots, reaches the main loop).
5. **Scale** region by region (run the game as integration test); build out the
   dispatch table, the interrupt delivery, and the `rts`-dispatch special-case
   list as they're discovered.

---

## 10. Open risks / things to watch

- **`rts`-dispatch detection** (§5a) may need manual annotation for tricky cases.
- **Self-modifying code**, if any, would break static translation — must be ruled
  out or special-cased (audit during PoC).
- **Per-instruction interrupt check cost** (§5b): the atomic-flag + IPL gate keeps
  the common case to one atomic load, but measure it on the PoC.
- **Structured-operand refactor of the decoder** is a prerequisite and
  non-trivial; scope it carefully so `AsmFormatter` / tests stay green.
