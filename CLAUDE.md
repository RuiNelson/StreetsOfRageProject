# CLAUDE.md

This file provides guidance to LLM agents when working with code in this repository.


Overview
========

This project reverse-engineers the Streets of Rage ROM using a mix of **static recursive-descent disassembly** and **active disassembly** data gathered from a running emulator (Exodus).

The key insight: many 68000 instructions jump/call indirectly (via registers or RAM, e.g. `jmp (a0)`), which is impossible to resolve statically. Active disassembly records every ROM address the CPU actually executes or reads as data during gameplay, providing a ground-truth list of reachable code locations.

**Key files:**
- `etc/sor-exodus.asm` — ground-truth disassembly from the emulator (active disassembly)
- `aux_addresses.txt` — extra entry points for the static disassembler, derived from active disassembly
- `output/sor.map` — binary coverage map (each byte = 'I'=instruction, 'D'=data, 'X'=unknown)

**Unified tool entry point:** use `python3 -m tools <command> ...`.  The old
module entry points still delegate for compatibility, but the cohesive operator
surface is the unified CLI.

**Tools pipeline:**

```
ROM binary
    │
    ▼
tools/disassembler/          # Static recursive-descent disassembler
    │                         # Reads aux_addresses.txt for extra entry points
    │                         # Outputs: .asm + .map
    │
    ▼
tools/remove_data_locations/  # (Optional) Strip data blocks
    │
    ▼
tools/label_diff/            # Compare static output vs sor-exodus.asm
    │
    ▼
tools/iterative_disasm/      # Iteratively close the gap with active disasm
```

---

Disassembler
------------

Converts the ROM binary into readable 68000 assembly.

```bash
python3 -m tools disassemble rom/StreetsOfRage.bin -o output/sor.asm -v
```

**Entry points:** defaults to reset vector (0x000208) and VBlank IRQ (0x019D16). Use `--aux` to add addresses from `aux_addresses.txt` (one hex address per line).

**Optional CSV files** to improve the output:

| Flag | Purpose |
|------|---------|
| `--addresses-csv` | Custom labels + comments (emits EQU directives) |
| `--blocks-csv` | Memory regions for offset resolution |
| `--labels-csv` | Code segment names |
| `--map` | Write ROM coverage map (binary) to this path |
| `--indirect-jumps` | Write unresolved jumps/calls to this path |

**Key concepts:**

- **Flow types** — control how the disassembler continues: SEQUENTIAL (next instr), CALL (follow target + continue), BRANCH (follow target and stop), CONDITIONAL (both paths), RETURN (stop tracing)
- **Indirect jumps** — `jmp (a0)` etc. can't be resolved statically; disassembler flags and continues past them
- **Labels** — `sub_XXXXXXXX` (subroutines), `loc_XXXXXXXX` (branch targets), `$XXXXXXXX` (raw hex). CSVs override these.
- **Gaps** — unreachable regions use `org $XXXXXXXX` to keep output relocatable

---

Active vs Static Disassembly
----------------------------

**Static disassembly** (what this tool does): recursively follows code from known entry points. Misses anything reachable only via indirect jumps.

**Active disassembly** (Exodus emulator): runs the game and records every ROM address the CPU executes or reads as data. Produces `etc/sor-exodus.asm` and `aux_addresses.txt`.

**Why both?** Static disassembly gives clean, commented, labeled code. Active disassembly provides complete coverage. The goal of `iterative-disasm` is to make the static output converge toward the active disassembly by discovering the entry points that the static disassembler missed.

---

remove-data-locations
---------------------

Strips blocks containing data directives (`dc.b`, `dc.w`, `dc.l`) from assembly output. Keeps only code blocks.

```bash
python3 -m tools remove-data output/sor.asm
```

Modifies the file in place. Splits by label, filters out any block with a data directive.

---

label-diff
----------

Two scripts for comparing assembly and finding gaps:

**script.py** — labels in file B but not in file A:
```bash
python3 -m tools label-diff output/sor-new.asm etc/sor-exodus.asm
```

**map_label_gaps.py** — labels that point to 'X' (unmapped) bytes in the ROM map:
```bash
python3 -m tools map-label-gaps output/sor.map etc/sor-exodus.asm
```
Used by `iterative-disasm` to discover which labels land on unmapped regions.

---

iterative-disasm
----------------

Iteratively expands static disassembly coverage toward the active disassembly ground-truth.

```bash
python3 -m tools iterative-disasm output/sor.asm output/sor.map etc/sor-exodus.asm aux_addresses.txt rom/StreetsOfRage.bin
```

**Loop:**
1. Run disassembler with current `aux_addresses.txt`
2. Find labels that point to 'X' (unmapped/data) bytes via `map_label_gaps.py`
3. Append the first missing address to `aux_addresses.txt`
4. Repeat until no gaps remain

**Output:** table of iteration, instruction/subroutine/label counts, and deltas per step.

---

Shell scripts
=============

Top-level scripts for common workflows:

| Script | What it does |
|--------|-------------|
| `./build.sh` | Smart build of the `sor` target: configures only when needed, auto-detects cores, recovers from libpng dependency breakage, and can run the binary (`-r`/`--run`). See `./build.sh --help` |
| `./disassemble.sh` | Run disassembler with all CSV files (`addresses.csv`, `blocks.csv`, `labels.csv`) |
| `./disassemble_nolabels.sh` | Same as above but without `labels.csv` |
| `./disassemble_iterative.sh` | Run disassembler then execute iterative loop to expand coverage |
| `./clang-format.sh` | Run `clang-format` on all C++ sources in `src/` using `.clang-format` |

All disassemble scripts accept an optional ROM path argument (defaults to `rom/SOR.bin`).

---

Pre-commit
==========

Before committing C++ changes, run `clang-format.sh`:

```bash
./clang-format.sh
```


================================================================================
C++ RECOMPILATION
================================================================================

The `src/` directory contains a C++23 recompilation of Streets of Rage that
emulates the Sega Mega Drive hardware and runs the original ROM.

The C++ side is organised around **`MegaDriveEnvironment`** (`src/system/`): a
base class that owns the hardware subsystems. Games/programs **subclass** it
(UIKit-style, like subclassing `UIViewController`) and override `run()` (the
cartridge entry point). The 68K CPU is not emulated — `run()` is native C++.

Entry point: `src/main.cpp` — parses flags `--testFontSDL`, `--testFontPNG`,
`--testVDP`, `--testControllers`, `--configControls`, then constructs the
matching `MegaDriveEnvironment` subclass and calls `boot()`.

Build: CMake with SDL3, yaml-cpp, zlib, libpng (FetchContent). Requires C++23.

```bash
./build.sh           # preferred: smart configure + build (see --help)
# or directly:
cmake -S src -B src/build && cmake --build src/build
```

Executable: `src/build/sor`

> Note: only the static libpng/zlib are linked. `src/CMakeLists.txt` disables
> libpng's shared/framework/tests/tools/example targets, which otherwise break
> on this toolchain. If a build ever fails inside `_deps/libpng-*`, re-fetch it:
> `rm -rf src/build/_deps/libpng-* && ./build.sh` (build.sh does this automatically).

**Always run the game under `timeout`.** Whenever you run `src/build/sor` or
`./build.sh -r` / `./build.sh --run`, wrap the command with `timeout`. Boot bugs
can hang or spin forever, and the SDL window does not exit on plain `SIGTERM` —
a bare `timeout N ...` leaves the process running past the deadline. Always use
the `-k` grace period so `SIGKILL` actually ends it:

```bash
timeout -k 3 20 ./src/build/sor --runSor --debug --fast --rom rom/SOR.bin
```

```bash
timeout -k 3 20 ./build.sh -r -- --runSor --debug --fast --rom rom/SOR.bin
```

- **20** — seconds until the first signal (adjust as needed for the test).
- **3** — grace seconds after `SIGTERM` before `SIGKILL`.

After each run, confirm the process has exited:

```bash
ps aux | grep build/sor
```

---
Architecture
------------

```
main.cpp                       Constructs a MegaDriveEnvironment subclass, calls boot()
    │
    ▼
MegaDriveEnvironment           system/: root object; games subclass it
    │   run()=0                Cartridge entry point (override). Runs on the CPU thread.
    │   vSync()/hSync(line)    Interrupt handlers (override); dispatched by runVDPInterrupts()
    │   boot()                 powerOn() + run() on CPU thread + SDL event pump on main thread
    │   cpu()  [protected]     68000 register file — for mechanically-generated ROM code only
    │
    ├── CPU68K                 system/cpu/: 68000 register file (D0–D7, A0–A6, SSP, USP, PC, SR)
    │
    ├── SystemMemory           system/memory/: 68K address space (ROM/WRAM), SDL_Mutex
    │
    ├── VDP                    system/graphics/: Sega Mega Drive VDP emulator (own render thread)
    │   ├── VDPState           Registers, VRAM(64KB), CRAM(64 entries), VSRAM(40)
    │   ├── VDPPort            Port I/O ($C00000/$C00004), DMA via env->memory()
    │   ├── VDPTile            Tile decoding (8×8×4bpp=32 bytes), CRAM→RGB conversion
    │   ├── VDPRenderer        Scanline render (224 lines), plane/sprite compositing
    │   ├── Framebuffer        320×224×3BPP (9-bit BGR native), PNG export
    │   └── Interrupt queue    Schedules HSync/VSync; drained by runVDPInterrupts()
    │
    ├── Controllers            system/controllers/: Mega Drive joypad protocol
    │   └── Port mapping:
    │       P1: $A10009 (control), $A10003 (data)
    │       P2: $A1000B (control), $A10005 (data)
    │       TH line selects button group:
    │         TH=1 → Up/Down/Left/Right/B/C
    │         TH=0 → Up/Down/Start/A
    │
    ├── Z80                    system/z80/: sub-CPU subsystem (stub; own thread)
    ├── Sound                  system/sound/: YM2612/PSG audio (stub)
    │
    ├── Controls Config UI     config/controls/ — state machine of Screens
    │   ├── MainMenuScreen     Player 1 / Player 2 / Exit
    │   ├── PlayerConfigScreen  Connected toggle, device select (modal), bind/test
    │   └── KeyBindScreen      Binding phase (prompt each button) + Testing phase (grid)
    │
    ├── ControlsConfigStore    config/: YAML persistence (controls.yaml)
    │
    └── Runtime Tests          MegaDriveEnvironment subclasses
        ├── TestFontSDL        3D rotating cube with glyphs on faces + Hello World
        ├── TestFontPNG        PNG export with artistic font effects
        ├── TestControllers    Controller readout via VDP display
        └── VDP tests (18)     Registers, bgcolor, CRAM, VRAM fill, font, planes,
                              H-scroll, V-scroll, sprites, masking, window, 64×64,
                              full scene, animated (girl + duck orbit), collision,
                              raster HSync (wavy per-scanline HScroll via hSync callback)
```

---
Key systems
-----------

**CPU68K (`src/system/cpu/`)**
- 68000 register file: `d[8]` (D0–D7), `a[7]` (A0–A6), `ssp` (supervisor SP),
  `usp` (user SP), `pc`, `sr` (Status Register, 16 bits).
- The SR is stored canonically as `m_word sr`. Inline CCR flag accessors
  (`flagC/V/Z/N/X()`) and setters (`setFlagC/V/Z/N/X()`, `setCVZN()`) make the
  generated code readable. SR system byte accessible via `intLevel()`,
  `supervisorMode()`, `traceMode()`.
- `reset()` sets `sr = 0x2700` (supervisor mode, IPL=7, CCR=0); all other
  registers to 0. Initial SSP/PC come from the reset vector table in ROM and
  are set by the cartridge boot code.
- Owned by `MegaDriveEnvironment` as private `cpu_`; exposed via **`protected`
  `cpu()` accessor** (not public — exclusively for mechanically-generated `run()`
  overrides, not for hand-written test/tool code).

**MegaDriveEnvironment (`src/system/`)**
- Root object that owns the subsystems: `CPU68K`, `SystemMemory`, `VDP`,
  `Controllers`, `Z80`, `Sound`. Each hardware child holds a back-reference
  (`env_`) and reaches the others through it (e.g. the VDP's DMA reads
  `env->memory()`).
- Games subclass it and override `run()` (cartridge entry point), `vSync()` and
  `hSync(int line)`. All mutexes are `SDL_Mutex` for portability.
- `boot()` (called from `main()` on the main thread): `powerOn()` starts each
  subsystem's thread, launches `run()` on a dedicated "CPU" thread, and pumps
  SDL events on the main thread (required so the VDP can present via
  `SDL_RunOnMainThread`) until `run()` returns; then `powerOff()`.
- **Interrupt model (not 1:1 with hardware):** the VDP render thread *schedules*
  interrupts in a queue; the program drains them by calling `runVDPInterrupts()`
  from its `run()` loop, so `vSync()`/`hSync()` run on the **same thread as
  run()** and suspend it while executing. There is no async preemption (that
  would require emulating the 68K) — handlers fire only when the program calls
  `runVDPInterrupts()`.

**VDP (Video Display Processor)**
- Two-thread architecture: program (CPU) thread writes ports under mutex; render
  thread composites scanlines and presents to the SDL window
- Renders scanline by scanline, scheduling an HSync interrupt per line and a
  VSync interrupt per frame (see the interrupt model above)
- H40 mode (320×224), 64×32 plane size default
- Layers (back to front): Plane B → Plane A/Window → Sprite
- Each layer has priority bit; 6-layer compositing per pixel
- H-scroll: full-screen / per-8-scanline / per-scanline
- V-scroll: full-screen / per-2-cell
- Sprite limit: 20 sprites per scanline (H40), SAT link chain for depth ordering
- DMA: copy (68k→VRAM via `env->memory()`), fill (VRAM pattern), VRAM→VRAM copy

**Controllers**
- SDL3 gamepad + keyboard input mapped to Mega Drive 3-button joypad protocol
- Port emulation via readPlayerXDataPort / writePlayerXDataPort (called by game loop)
- Active-low button encoding, TH-line multiplexing
- Hot-plug gamepad support, axis deadzone, auto-direction bindings for gamepad

**Memory (`SystemMemory`, `src/system/memory/`)**
- Instance owned by `MegaDriveEnvironment` (replaces the old global `memory.cpp`);
  subsystems access it via `env->memory()`
- 24-bit address space: ROM (0x000000–0x3FFFFF), Z80 RAM (0xA00000–0xA01FFF, stub),
  Work RAM (0xFF0000–0xFFFFFF)
- Big-endian byte order (Motorola convention)
- Thread-safe via an `SDL_Mutex`

**Controls Config UI**
- State machine: MainMenu → PlayerConfig → KeyBind → PlayerConfig → ...
- UIRenderer: SDL_Renderer wrapper with texture-cached 8×8 font, drawText/
  drawCenteredText/drawButton/fillRect/etc.
- PlayerConfig persisted to `controls.yaml` via ControlsConfigStore + yaml-cpp

**Font system**
- `Font` class converts 8×8 bitmap glyphs (chars 0x20–0x7E from FontData.hpp) into
  three output formats:

| Method | Output | Use case |
|--------|--------|----------|
| `fontCharToPixels()` | RGBA/RGB malloc buffer | PNG export, raw pixel manipulation |
| `fontCharToTexture()` | SDL_Texture (RGBA8888) | UI rendering via UIRenderer |
| `fontCharToVDPTile()` | 4bpp tile in work RAM | VRAM tile data for VDP text rendering |

- `fontCharToVDPTile(SystemMemory&, ...)` writes directly into the given
  `SystemMemory` at a work-RAM address, encoding 2 pixels per byte (high nibble =
  left, low nibble = right) — the bridge between host-side font bitmap and VDP
  tile format
- Flow for VDP text: encode glyphs → DMA from work RAM to VRAM → write
  nametable entries → VDP composites tiles in scanlines
- Same font data (`font8x8_basic[95][8]`) feeds all three methods; changing the
  bitmap in FontData.hpp propagates to every output path

**Image utility**
- `Image` class wraps a raw RGB buffer (3 bytes/pixel) with ownership semantics.
- Constructors: empty image with background fill, or text rendered via `Font::fontCharToPixels`.
- `printToPNG(fileName)` writes the buffer to a PNG file via libpng.
- Static helpers:
  - `joinVertically(top, bottom, gap, bg)` — stacks two images; width = max of both widths.
  - `joinHorizontally(left, right, gap, bg)` — places two images side by side; height = max of both heights.
  - `addLabel(label, img, gap, bg, fg)` — appends a text label below an image.

**Art pipeline**
- `src/art/convert_art.py` — converts PNG to VDP tile format (4bpp, 8×8 pixels,
  32 bytes/tile). Generates C++ constexpr headers. Supports alpha (index 0 =
  transparent). CRAM colour format: `0000_BBB0_GGG0_RRR0` (3 bits/channel).
- Output: GirlTileData.hpp (72 tiles), DuckTileData.hpp (16),
  BackgroundTileData.hpp (1120 tiles split in two), CloudTileData.hpp (18)

---
File map
--------

| Path | Purpose |
|------|---------|
| `src/main.cpp` | Flag parsing; builds a MegaDriveEnvironment subclass and calls `boot()` |
| `src/data_types.hpp` | `m_byte`, `m_word`, `m_long` (8/16/32-bit) |
| `src/system/MegaDriveEnvironment.hpp/cpp` | Root object: owns subsystems, boot/interrupt model |
| `src/system/cpu/CPU68K.hpp/cpp` | 68000 register file (D0–D7, A0–A6, SSP, USP, PC, SR) |
| `src/system/memory/SystemMemory.hpp/cpp` | 68K address space emulation (ROM/WRAM) |
| `src/system/z80/Z80.hpp/cpp` | Z80 sub-CPU subsystem (stub) |
| `src/system/sound/Sound.hpp/cpp` | Sound subsystem (stub) |
| `src/system/graphics/VDP.hpp/cpp` | VDP root + render thread + interrupt queue |
| `src/system/graphics/VDPState.hpp/cpp` | Registers + memory + HV counter |
| `src/system/graphics/VDPPort.hpp/cpp` | Port I/O + DMA (reads system memory via env) |
| `src/system/graphics/VDPTile.hpp/cpp` | Tile decode + colour conversion |
| `src/system/graphics/VDPRenderer.hpp/cpp` | Scanline render + compositing |
| `src/system/graphics/Framebuffer.hpp/cpp` | Pixel buffer + PNG export |
| `src/system/controllers/Controllers.hpp/cpp` | Joypad protocol + SDL input |
| `src/config/ControlsConfigStore.hpp/cpp` | YAML persistence |
| `src/config/controls/Screen.hpp` | Abstract screen base |
| `src/config/controls/UIRenderer.hpp/cpp` | SDL drawing primitives |
| `src/config/controls/MainMenuScreen.hpp/cpp` | Main menu |
| `src/config/controls/PlayerConfigScreen.hpp/cpp` | Player device/config |
| `src/config/controls/KeyBindScreen.hpp/cpp` | Key binding flow |
| `src/config/controls/ControlsConfigUI.hpp/cpp` | UI state machine |
| `src/util/font/Font.hpp/cpp` | Render a string to bitmap (textures, tiles or pixel buffer) |
| `src/util/font/FontData.hpp` | Bitmap source data (95 glyphs × 8 bytes) |
| `src/util/image/Image.hpp/cpp` | RGB image with text rendering and PNG export |
| `src/runtime_tests/TestFontSDL.hpp/cpp` | Font + 3D cube test |
| `src/runtime_tests/TestFontPNG.hpp/cpp` | PNG export test |
| `src/runtime_tests/controllers/TestControllers.hpp/cpp` | Controller display test |
| `src/runtime_tests/vdp_tests/TestVDP.hpp` | VDP test harness |
| `src/runtime_tests/vdp_tests/TestVDPSetup.cpp` | VDP test helpers + tile loading |
| `src/runtime_tests/vdp_tests/TestVDPRunner.cpp` | Test runner |
| `src/runtime_tests/vdp_tests/TestVDPTest01-18.cpp` | Individual test cases |
| `src/art/GirlTileData.hpp` | Girl sprite tiles (6×12) |
| `src/art/DuckTileData.hpp` | Duck sprite tiles (4×4) |
| `src/art/BackgroundTileData.hpp` | Background art (40×28) |
| `src/art/CloudTileData.hpp` | Cloud tiles (6×3) |
| `src/art/convert_art.py` | PNG → VDP tile converter |

---
Genesis-Plus-GX Reference
-------------------------

`Genesis-Plus-GX/` — submodule with high-quality Sega emulator code
(Genesis/Mega Drive, Sega/Mega CD, Master System, Game Gear, SG-1000).

Used for reference and validation of project implementations (VDP, 68K, controllers, etc.).
