# Agent guide

Instructions for automated contributors working in the Streets of Rage workspace.

## Start here

1. Inspect `git status` in the meta-repository and in every submodule in scope. Preserve unrelated changes.
2. Read the local `CLAUDE.md` before editing an owned submodule.
3. Decide whether the change belongs to the meta-repository or to submodules. Do not place project code in the meta-repository.
4. Use the smallest relevant build or test first, then expand validation in proportion to the change.

## Repository map

| Path | Role | Tracking |
| --- | --- | --- |
| `MegaDriveEnvironment/` | C++23 Mega Drive host runtime and development library | submodule |
| `MegaDriveEnvironmentSampleGame/` | Dual-target sample for PC and real Mega Drive hardware | submodule |
| `RageDecompiler/` | Python disassembly and recompilation tools | submodule |
| `StreetsOfRageRecompilation/` | Analysis, generated C++, native overrides, host executable | submodule |
| `autoplay/` | Python remote observer (`src/sor_autoplay`) + the symbolic AI's core (`ai-code/sor_ai`) | this repository |
| `StreetsOfRageBuilder/` | Tauri + Next.js wizard: dependencies, clone, build, shortcuts | this repository |

`Genesis-Plus-GX` is upstream reference only and is not checked out: never edit or patch it. `StreetsOfRageRecompilation/tools/soundtrack` fetches it at a pinned commit and compiles it unmodified, the one sanctioned use of its code.

## Git workflow

```bash
git clone --recurse-submodules https://github.com/RuiNelson/StreetsOfRageProject.git
git submodule update --init --recursive   # an existing plain clone
```

Submodule commits are part of the reproducible workspace; do not advance them casually. For a change in an owned submodule: validate it there, commit and push it, update the gitlink in the same delivery, and report both repositories. `autoplay/` and `StreetsOfRageBuilder/` are committed directly here.

After validating requested changes, commit and push to `main` automatically unless the user asks not to publish. Never include unrelated dirty files. Do not force-push, rewrite history, or open a pull request unless asked.

Do not commit ROMs, generated C++, build trees, CMake download trees, caches, screenshots, call logs, `call-map.sqlite`, recordings, or transient discovery output.

## Build

`StreetsOfRageRecompilation/` builds the game and consumes the sibling `MegaDriveEnvironment/`. The copyrighted ROM goes at `StreetsOfRageRecompilation/rom/SOR.bin`. `generated/` is ignored, so generate it after a fresh clone and whenever ROM analysis or recompiler inputs change. Requirements and per-platform commands: `README.md`.

```bash
./scripts/generate_cpp.py
./scripts/generate_cpp_and_build.py            # or --release
./scripts/render_soundtrack.py                 # once after cloning, or when the renderer changes
```

Direct CMake runs only after generation:

```bash
cmake -S StreetsOfRageRecompilation -B StreetsOfRageRecompilation/build -DCMAKE_BUILD_TYPE=Debug
cmake --build StreetsOfRageRecompilation/build --parallel
```

**Windows** uses llvm-mingw with Ninja, not Visual Studio (user decision). `scripts/_common.py` (`cmake_configure_arguments`) adds `-G Ninja` and the compilers; direct CMake calls must pass the same. `MegaDriveEnvironment` is static there. Cleaning goes through `remove_tree` in `scripts/_common.py`, never `shutil.rmtree`, which failed on read-only git objects (user report).

## Player-facing decisions

User decisions. Implementation details are in `StreetsOfRageRecompilation/CLAUDE.md` under the same names.

- **Python AI in `sor`:** **1 PLAYER AI ASSIST** is a 2-player game with the AI on P2, from `autoplay/ai-code/sor_ai` (`sor --ai-path DIR`). `sor` embeds our own CPython through the C API, with no build variant without it (Linux written, untried). The AI's thread keeps its own time, is not woken by the game, and lives from choosing the mode until the mode menu is back. An external `autoplay` may drive P1; P2 stays the internal AI's.
- **Soundtrack:** by default FLAC renders by Genesis Plus GX (`--sound prerendered|emulated`, `--soundtrack DIR`, default `soundtrack/` beside the ROM), because the host's real-time sound is not good enough. Nuked OPN2 **YM3438**, **no low-pass filter**, **48 kHz lossless**; music, effects and voices all pre-rendered; music at normal speed under `--turbo`; effects do not steal a music channel. Each track has two stems (FM, faded by `$E0`; DAC+PSG, cut at once). In `README.md` the extraction is the last build step of each platform section; `--chip` and `--out` stay out of those steps. `--silent` disables all audio.
- **Command line:** kebab-case, no aliases for old names, `--help` groups them (Game, Video, Audio, AI, Development). `--lang` defaults to `en`; `MegaDriveEnvironment`'s own pin stays Japanese, and `MegaDriveEnvironmentSampleGame` keeps its `--debug`.
- **OPTIONS > VIDEO and `video.yaml`** (beside `controls.yaml`): the command line wins for that run but stays editable on the screen, and SAVE AND APPLY saves what the screen shows, at once. VSYNC names are the technical ones, with Hz and speed in the help line. Ctrl+F changes the session only. `--turbo` without `--frame-sync` runs on the timer. **Measurements must not depend on the player's file:** pass `--default-video` (`play.py --preset` does).
- **The pause menu** (`SoRPause.cpp`): RESUME and FORFEIT, confirm with the cursor on NO. Each human answers for themself; YES loses all continues and dies at once. In AI Assist the one answer forfeits both. The pre-rendered music plays on, FM 9 dB down.
- **Frame sync:** `--frame-sync auto` must work on macOS, Windows and Linux, with or without VRR, with no per-monitor setup and no tearing: the timer is the clock and frames are presented with vsync without the game waiting. Not tested on an external VRR monitor, Windows or Linux. `vsync|vsync-half|vsync-third` tie the speed to the monitor.
- **Controls:** `sor` reads SDL itself (`SoRInput.*`) and binds per-player **actions** in `~/.config/StreetsOfRageProject/controls.yaml`, set in OPTIONS > CONTROLS. Schemes are ORIGINAL 3 and ENHANCED 6; defaults are in `StreetsOfRageRecompilation/CLAUDE.md`, **Controls**. Autoplay sends actions in a binary `struct` format (no PyYAML on the system Python) and **detects** each player's scheme by querying the host, never sets it.
- **Windows console:** `sor` is a GUI-subsystem program; `openConsoleIfWanted` (`main.cpp`) gives it a console only for `--debug-utils`, `--debug-log`, `--call-log`, `--aux-addr-file`, `--help` or `--version`. Without them stdout and stderr go to the null device on every platform. Not tested on Windows.
- **Mode menu:** a **QUIT** row after OPTIONS ends the game.

## Hand-written C++ keeps the original memory layout

Reimplemented routines never move game state. Every field stays in 68000 work RAM at its original address, width and encoding, updated on the same frame as the ROM, and tables are read from the ROM, because `autoplay` reads the game by address (`memory_map.py`, `rom_data.py`). See **Manual subroutines** and the `reimplement-subroutine` skill.

## Reverse-engineering tools

```bash
cd StreetsOfRageRecompilation
PYTHONPATH=../RageDecompiler python3 -m tools --help
```

Common entry points: `./scripts/disassemble_to_asm.py`, `./scripts/discover_aux_smart.py`. `code-analysis/aux_addresses.txt` adds entry points for indirect jumps and calls.

For who calls whom at runtime, record with `sor --call-log calls.csv`, collapse with `tools/call_map.py`, and query the SQLite views (`subroutine_activity`, `subroutine_flow`, `callsite_flow`), not the web viewer. Counts are observations, not proof of every path. See the `explore-call-map` skill.

## Launching: `scripts/play.py`

```bash
./scripts/play.py                       # window: configure, Ctrl+R runs both
./scripts/play.py --last                # the saved settings, no window
./scripts/play.py --preset turbo        # turbo | watch | quiet | lockstep | p2 | boss
./scripts/play.py --preset boss --level 2 --dry-run   # print the command lines only
```

`PRESETS` in `play.py` is the source of truth. Agents use the command-line form: it needs no Tk, starts from defaults plus the preset (never the saved `last_play_py_settings.yml`), does not overwrite that file, passes `--default-video`, and forwards unknown options to autoplay. Add a setting in `DEFAULTS` and the two argument builders. A copy without the sources saves settings in `~/.config/StreetsOfRageProject/` and disables Build first.

## Testing the symbolic AI live

**No AI behaviour change ships unmeasured** (user's no-regression rule): measure it live before `main`. A change validated only offline goes to a branch and says so. Only start `sor` when necessary, always with `--silent` for debug, and prefer `autoplay` unit tests for logic.

| Preset | Use |
| --- | --- |
| `turbo` | Measurement: `--turbo 2`, `--poll-ms 16` (about 2 frames a tick; 4x needs `--poll-ms 8` and a fresh measurement) |
| `lockstep` | Frame-exact, AI drives the clock, port 6767 |
| `boss --level N` | One round's boss, street enemies swept, `--no-police`, plus `--no-food` on rounds 2-5 and 8; never test bosses without the sweep |
| `watch` / `quiet` | Normal speed, with or without sound; not for measurement |

| Level | Boss |
| --- | --- |
| 1 | Antonio (`$56`) |
| 2 | Souther (`$55`) |
| 3 | Abadede (`$30`) |
| 4 | Bongo (`$57`) |
| 5 | Onihime & Yasha (`$58` pair) |
| 6 | Bongo (`$57`), then a Souther pair (`$55`) |
| 7 | none: the ELC stream has no terminal boss section |
| 8 | rush `$56` → `$55` → `$30` → `$57` → `$58` → Mr. X (`$35`), with `--kill-until-mr-x` |

Scoring tools, ROM models and plans per enemy: `autoplay/CLAUDE.md`.

## Validation and handoff

- Documentation only: check Markdown, links, paths, commands, and consistency with CMake and scripts.
- C++: configure, compile, and run the narrow relevant tests.
- Python: run the affected tests, then the repository suite when practical.
- Analysis or symbols: follow the synchronization rules in `StreetsOfRageRecompilation/CLAUDE.md`.
- Cross-repository: validate each repository and inspect the final gitlinks.

Finish by summarizing changed files, validation, and anything not tested on the current host.

## Other rules

- Do not consult git history.
- Keep the `CLAUDE.md` files updated as you work, and record in them what you learn from the user about the project. Keep them short: rules, decisions and what the code does not say, not run logs or per-function narration.
