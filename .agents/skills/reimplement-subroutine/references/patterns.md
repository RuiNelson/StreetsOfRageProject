# Manual subroutine patterns (StreetsOfRageRecompilation)

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

## Finding the generated body

```bash
cd StreetsOfRageRecompilation
rg -n "void Sor::NAME|case 0xADDR" generated/Sor.cpp generated/Sor.hpp
rg -n "LABEL|0xADDR" output/sor.asm
rg -n "ADDR|name" code-analysis/labels.csv
```

After `./build.sh --full`, the body definition must disappear; declaration and
calls remain.

## Existing manuals (examples)

| Address | Name | File | Notes |
|---------|------|------|-------|
| `$0003A2` | `game_infinite_loop` | `SorManualFunctions.cpp` | Frame loop + `$412` hang; soft CALL; IRQ via `sync_z80_1` |
| `$0041EA` | `sub_0041ea` | `SorManualFunctions.cpp` | Attack strength + cheat hook; RTS |
| `$010502` | `sync_z80_1` | `SorManualFunctions.cpp` | Mailbox wait 1 |
| `$010514` | `sync_z80_2` | `SorManualFunctions.cpp` | Mailbox wait 2 |
| `$01069E` | `queue_sound_id` | `SoRSound.cpp` | Mid-entry `$106CA` |
| `$011B12` | `play_level_music` | `SoRSound.cpp` | Level BGM queue |

## Build / run

```bash
cd StreetsOfRageRecompilation
./build.sh --full
timeout -k 3 20 ./build.sh -r -- --runSor --debug --fast --rom rom/SOR.bin
pgrep -lf '[/]sor' || echo 'clean'
```

## Commit boundaries

Commit in the **submodule** first, then the **meta-repo** gitlink. Leave
unrelated worktree dirt out of the commit unless the user asks to publish
everything.
