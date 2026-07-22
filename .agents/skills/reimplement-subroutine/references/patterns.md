# Manual subroutine patterns (StreetsOfRageRecompilation)

## Contents

- File map
- Generated call/return macros
- Entry, tail-call, and mid-entry handling
- Host wait helpers
- ASM-first extraction and missing indirect targets
- Cross-routine contracts learned
- Existing manuals, build/run, and commit boundaries

## File map

| Path | Role |
|------|------|
| `code-analysis/manual_functions.txt` | Addresses whose bodies are hand-written |
| `code-analysis/labels.csv` | Code names / confidence comments |
| `code-analysis/addresses.csv` | RAM/IO symbols |
| `code-analysis/aux_addresses.txt` | Extra disassembly entry points |
| `generated/Sor.hpp` | Declarations (regenerated; do not hand-edit) |
| `generated/Sor.cpp` | Generated bodies + CALL macros (regenerated; gitignored) |
| `SorManualFunctions.cpp` | Manual game/runtime bodies |
| `SoRMainMenus.cpp` | Manual mode-select, OPTIONS, and character-select bodies |
| `SoRSound.cpp` | Manual sound helpers |
| `output/sor.asm` | Local disassembly (gitignored) |
| `rom/SOR.bin` | Local ROM (not versioned) |

## Generated call/return macros (`generated/Sor.cpp`)

```cpp
#define BEFORE_INSTRUCTION \
    if (irqLevel() > cpu().interruptMask()) serviceIRQ(); pace();

#define CALL(fn, ret_pc) do { \
    m_long _call_sp = cpu().ssp; \
    cpu().ssp -= 4; \
    memory().writeLong(cpu().ssp, LONG(ret_pc)); \
    (fn)(); \
    if ((cpu().ssp & 0x00FFFFFFu) > (_call_sp & 0x00FFFFFFu)) return; \
} while (0)

#define CALL_DISPATCH(addr, ret_pc) do { \
    m_long _call_sp = cpu().ssp; \
    cpu().ssp -= 4; \
    memory().writeLong(cpu().ssp, LONG(ret_pc)); \
    dispatch(addr); \
    if ((cpu().ssp & 0x00FFFFFFu) > (_call_sp & 0x00FFFFFFu)) return; \
} while (0)

#define RETURN_68K() do { cpu().ssp += 4; return; } while (0)
```

Manual files **do not** include these macros. Replicate with a local lambda or
`cpu().ssp += 4` only.

## Entry / tail-call vs CALL

Inspect call sites in `generated/Sor.cpp` before assuming RTS:

| Pattern | Manual must |
|---------|-------------|
| `CALL(fn, ret);` | End with `cpu().ssp += 4` (pop return PC) |
| `CALL_ENTRY(fn, entry, ret);` | Same; honor `entry_` |
| `fn(); return;` / `fn(entry); return;` | Tail entry — **no** mandatory `ssp += 4` unless this path also RTS'd |
| `case 0x…: fn(); return;` in `dispatch` | Same as tail entry |

## Mid-entries

The recompiler may fold nearby code into one function and pass `entry_`:

```cpp
// Generated (before manual):
void Sor::game_infinite_loop(m_long entry_) {
    switch (entry_) {
        case 0x0412u: goto L000412;
        default: break;
    }
    // primary at 0x03A2
}
```

After manual: handle with `if (entry_ == 0x0412u)` (or a switch). Grep for
`function_name(0x` and `case 0x…u: function_name` to find every entry.

## Host wait helpers

| API | Use |
|-----|-----|
| `waitForInterrupt()` | Block until pending IRQ above CPU IPL mask (or quit) |
| `irqLevel()` / `cpu().interruptMask()` | Decide whether to `serviceIRQ()` |
| `serviceIRQ()` | Enter 68000 exception path + handler (private on `Sor`) |
| `memory().waitForByteValue(addr, want, pollFn)` | Spin/poll with cooperative wait (mailbox style) |
| `shouldQuit()` | Window closed / host quit |
| `pace()` | Yield / cycle accounting (optional in manuals) |
| `cpu().setStatus(0x2500u)` | Supervisor, IPL 2 — common while waiting for VBlank |

Typical VBlank mailbox (see `sync_z80_1` / `sync_z80_2`):

- Write command byte to `$FFFFFA00`
- Enable IRQs in SR
- Wait until mailbox cleared by `vblank_handler`

## ASM-first extraction

Start from compact ASM ranges, not generated bodies:

```bash
cd StreetsOfRageRecompilation
rg -n "target_label:|nearby_label:" output/sor.asm
sed -n 'START,ENDp' output/sor.asm
rg -n "ADDR|name" code-analysis/labels.csv code-analysis/addresses.csv
```

From ASM, record:

- entry and every reachable mid-entry;
- `jsr` versus `jmp`, explicit `rts`, and label fall-through;
- byte/word/long widths and partial-register writes;
- the last flag-producing instruction before each conditional branch;
- temporary `movem`/`move …,-(sp)` saves around calls;
- PC-relative jump-table bases and signed word offsets.

Only then query generated code for the recompiler contract:

```bash
rg -n "void Sor::NAME|case 0xADDR" generated/Sor.cpp generated/Sor.hpp
rg -n "NAME\(0x|CALL\(NAME|CALL_ENTRY\(NAME" generated/Sor.cpp
```

Generated C++ is useful for names, folded entries, soft-call return PCs, and
dispatch coverage. It is not the preferred behavioral source.

After `./build.sh --full`, the body definition must disappear; declaration and
calls remain.

## Missing indirect targets

Jump-table targets can have high-confidence labels yet be absent from ASM,
`Sor.hpp`, and dispatch because they were never supplied as auxiliary roots. An
`org` gap around the address is a strong signal.

```bash
xxd -g 2 -s 0xTARGET -l 0x80 rom/SOR.bin
rg -n "TARGET" code-analysis/aux_addresses.txt generated/Sor.hpp generated/Sor.cpp
```

Decode enough ROM to confirm code, add the six-digit root to
`aux_addresses.txt`, regenerate, and verify declaration + dispatch before
writing the manual body. This was required for OPTIONS handlers `$1404` and
`$1476`.

## Cross-routine contracts learned

- **Fall-through wrappers:** `$9170` and `$927C` initialize a mode and flow
  directly into the adjacent update wrapper. Their manual init bodies must
  tail-call the update path, not pop an extra return address.
- **Flags as return values:** `$14F2` communicates whether OPTIONS navigation
  occurred through Z; callers immediately execute `bne`.
- **High-half preservation:** object dispatch near `$AE20` sets bit 16 in `D0`
  and then executes `move.w …,d0`; the word write preserves the bank bit used
  by the absolute handler address.
- **Nested temporary saves:** `$AD8E` pushes a word loop counter before a soft
  `jsr`. Restore it only on the normal path; if a call unwinds past the frame,
  return exactly as generated code does.
- **Scope discipline:** for a document-driven batch, inventory its explicit
  related-code table first. Do not manualize every helper mentioned in prose.

## Existing manuals (examples)

| Address | Name | File | Notes |
|---------|------|------|-------|
| `$0003A2` | `game_infinite_loop` | `SorManualFunctions.cpp` | Frame loop + `$412` hang; soft CALL; IRQ via `sync_z80_1` |
| `$0041EA` | `sub_0041ea` | `SorManualFunctions.cpp` | Attack strength + cheat hook; RTS |
| `$010502` | `sync_z80_1` | `SorManualFunctions.cpp` | Mailbox wait 1 |
| `$010514` | `sync_z80_2` | `SorManualFunctions.cpp` | Mailbox wait 2 |
| `$01069E` | `queue_sound_id` | `SoRSound.cpp` | Mid-entry `$106CA` |
| `$011B12` | `play_level_music` | `SoRSound.cpp` | Level BGM queue |
| `$000FE8`–`$00AD8E` | select/OPTIONS/character-select set | `SoRMainMenus.cpp` | 27 roots; includes mid-entry `$AE10` |

## Build / run

```bash
cd StreetsOfRageRecompilation
./build.sh --full
timeout -k 3 20 ./build.sh -r -- --runSor --debug --rom rom/SOR.bin
pgrep -lf '[/]sor' || echo 'clean'
```

## Commit boundaries

Commit in the **submodule** first, then the **meta-repo** gitlink. Leave
unrelated worktree dirt out of the commit unless the user asks to publish
everything.
