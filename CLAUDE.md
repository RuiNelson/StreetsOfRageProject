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
| `StreetsOfRageBuilder/` | Tauri + Next.js wizard: dependencies, clone, build, shortcuts; for this computer or the PS5 | this repository |

`Genesis-Plus-GX` is upstream reference only and is not checked out: never edit or patch it. `StreetsOfRageRecompilation/tools/soundtrack` fetches it at a pinned commit and compiles it unmodified, the one sanctioned use of its code.

`README.md` is only the introduction and an index (user decision). The documentation lives in `docs/`: `DeveloperJourney.md`, `BuildingDesktop.md`, `BuildingPS5.md`, `Playing.md`, `Researching.md`.

## Git workflow

```bash
git clone --depth 1 --shallow-submodules --recurse-submodules https://github.com/RuiNelson/StreetsOfRageProject.git
git submodule update --init --recursive --depth 1   # an existing plain clone
```

Submodule commits are part of the reproducible workspace; do not advance them casually. For a change in an owned submodule: validate it there, commit and push it, update the gitlink in the same delivery, and report both repositories. `autoplay/` and `StreetsOfRageBuilder/` are committed directly here.

**Never tag or release with an unpushed gitlink** (0.7.0 shipped with one: the Builder's clone failed with `not our ref`). Before any commit that moves a gitlink, and again before any tag or release, for each submodule run `git -C SUB fetch origin && git -C SUB branch -r --contains $(git ls-tree HEAD SUB | awk '{print $3}')`: it must list `origin/main`. If it prints nothing, push the submodule first. Push submodules before the meta-repository, always, and end a release with a shallow `git clone --depth 1 --shallow-submodules --recurse-submodules` of the tag into a scratch folder.

After validating requested changes, commit and push to `main` automatically unless the user asks not to publish. Never include unrelated dirty files. Do not force-push, rewrite history, or open a pull request unless asked.

Do not commit ROMs, generated C++, build trees, CMake download trees, caches, screenshots, call logs, `call-map.sqlite`, recordings, or transient discovery output.

## Build

`StreetsOfRageRecompilation/` builds the game and consumes the sibling `MegaDriveEnvironment/`. The copyrighted ROM goes at `StreetsOfRageRecompilation/rom/SOR.bin`. `generated/` is ignored, so generate it after a fresh clone and whenever ROM analysis or recompiler inputs change. Requirements and per-platform commands: `docs/BuildingDesktop.md` and `docs/BuildingPS5.md`.

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

**PS5** builds in Docker only (user decision): `./scripts/build_ps5.py` makes the image `sor-ps5-toolchain` from `StreetsOfRageRecompilation/prospero/docker/` (payload SDK, RADV, title converter, all pinned there), checks it, and builds the title into `StreetsOfRageRecompilation/dist-ps5/`; `--shell` opens the image. `./scripts/deploy_ps5.py --host ADDRESS` copies it, the ROM and the soundtrack to a console over FTP. The port is complete (user, 2026-11-01).

**`scripts/ps5_wizzard.sh`** (user request) is the all-in-one PS5 path for a user with only a container engine, on macOS and Linux: a TUI wizard (pure bash 3.2, stock tools, `docker` for Docker, OrbStack and Podman alike) that checks the engine, verifies the ROM (SHA-256, `.bin|.md|.gen`, never `.smd`), builds the image, renders the soundtrack and generates and compiles in the container, then offers two ZIPs in the CWD (`PPSA99872/` for `/data/homebrew`, `sor/` for `/data`) and/or anonymous FTP upload through `curl`, then cleans up. The code is in `scripts/ps5_wizard/`: `tui.sh` (screen), `steps.sh` (work, shared), `macos.sh` and `linux.sh` (only what differs; the hooks are listed atop `steps.sh`). Linux is written and its hooks tried in a container, never run against a real engine (root-owned output is chowned back unless the engine is rootless; `:z` under SELinux). It uses the image and volume names of `build_ps5.py` and calls `generate_cpp.py` and `build.sh` unchanged. Cleanup (user decision) removes the container image, the build volume, `generated/` and `dist-ps5/`; the ROM copy and `rom/soundtrack` stay, since they are reusable. **`scripts/ps5_wizzard.ps1`** is the same wizard for Windows 11 (user request), split into dot-sourced files in `scripts/ps5_wizard/` (`tui.ps1`, `tasks.ps1`, `steps-setup.ps1`, `steps-build.ps1`, `steps-deliver.ps1`), that runs on Windows PowerShell 5.1 (the stock one: keep it ASCII, no `??`/ternary/`&&`) and 7, started by `ps5_wizzard.cmd` (execution policy bypass). It uses `docker` or `podman`, whichever runs; passes the render script on standard input (no PS 5.1 quoting); writes zip entries with `/` itself (`Compress-Archive` 5.1 writes `\`); uploads with `curl.exe`; runs the file dialog in a `-STA` child; and sets the `prospero/` `.sh`, `.site`, `.patch`, `.cmake` and `Dockerfile` files and `cmake/*.cmake` to LF before building (`build-cpython.sh` seds the CPython version out of `cmake/CPythonRuntime.cmake` and fails silently on CRLF), because Git on Windows checks them out with CRLF. Tried only on PowerShell 7 on macOS (menus, ROM check, image and check steps, zips, FTP to a fake server), never on Windows. The script name's spelling ("wizzard") is the user's.

**Windows** uses llvm-mingw with Ninja, not Visual Studio (user decision). `scripts/_common.py` (`cmake_configure_arguments`) adds `-G Ninja` and the compilers; direct CMake calls must pass the same. `MegaDriveEnvironment` is static there. Cleaning goes through `remove_tree` in `scripts/_common.py`, never `shutil.rmtree`, which failed on read-only git objects (user report).

## Player-facing decisions

User decisions. Implementation details are in `StreetsOfRageRecompilation/CLAUDE.md` under the same names.

- **Python AI in `sor`:** **1 PLAYER AI ASSIST** is a 2-player game with the AI on P2, from `autoplay/ai-code/sor_ai` (`sor --ai-path DIR`). `sor` embeds our own CPython through the C API, with no build variant without it (Linux written, untried; static on PS5). The AI's thread keeps its own time, is not woken by the game, and lives from choosing the mode until the mode menu is back. An external `autoplay` may drive P1; P2 stays the internal AI's.
- **Soundtrack:** by default FLAC renders by Genesis Plus GX (`--sound prerendered|emulated`, `--soundtrack DIR`, default `soundtrack/` beside the ROM), because the host's real-time sound is not good enough. Nuked OPN2 **YM3438**, **no low-pass filter**, **48 kHz lossless**; music, effects and voices all pre-rendered; music at normal speed under `--turbo`; effects do not steal a music channel. Each track has two stems (FM, faded by `$E0`; DAC+PSG, cut at once). In `docs/BuildingDesktop.md` the extraction is the last build step of each platform section; `--chip` and `--out` stay out of those steps. `--silent` disables all audio.
- **Command line:** kebab-case, no aliases for old names, `--help` groups them (Game, Video, Audio, AI, Development). `--lang` defaults to `en`; `MegaDriveEnvironment`'s own pin stays Japanese, and `MegaDriveEnvironmentSampleGame` keeps its `--debug`.
- **OPTIONS > VIDEO and `video.yaml`** (beside `controls.yaml`): the command line wins for that run but stays editable on the screen, and SAVE AND APPLY saves what the screen shows, at once. VSYNC names are the technical ones, with Hz and speed in the help line. Ctrl+F changes the session only. `--turbo` without `--frame-sync` runs on the timer. **Measurements must not depend on the player's file:** pass `--default-video` (`play.py --preset` does).
- **OPTIONS > QUALITY-OF-LIFE and `qol.yaml`** (beside `controls.yaml`; the row after VIDEO): changes to the original game, off by default, same save rules as VIDEO. `--qol a,b,c` turns options on for the run. First option: `cam`, ROLL CAMERA EARLIER, the camera rolls from 30% of the screen (the ROM: 55%, and the user finds that claustrophobic, playing alone too). **Measurements:** pass `--default-qol` too (`play.py --preset` does; `play.py --qol` adds options back). The AI's code does not know `cam`; AI scores under it are unmeasured. Second option: `grab`, FRIEND GRAB KEEPS WEAPON (user): only an enemy's grab makes the player drop the weapon; hits still do, a friend's throw included. Third option: `damage`, ENEMY DAMAGE CIRCLES (user, in place of a health bar they found uninspired): over each regular enemy, in the VDP's host layer and never through the VDP's own sprites or VRAM, nothing at full health, then a semi-transparent ring 8 native pixels across with a disc inside, growing with the damage; the disc as wide as the ring means dead, so a living enemy never shows that, and it does not blink with the dying sprite. Colour by family: Garcia blue, Nora red, Signal yellow, Haku-Ro purple, Jack dark grey. It writes no game state, so the AI's games are unaffected. Fourth option: `scores`, SAVE HIGH SCORES (user): the table lives in `highscores.yaml`, and SAVE AND APPLY with it off deletes the file. **Player initials** (user; second page under `scores`, set on an on-screen keyboard, no command line and no switch): a player with initials skips name entry and goes straight to the continue prompt; without them, the ROM's screen. P2 under AI Assist is always `AI `. The menu has pages instead of RESET TO DEFAULTS. `cheat`, CHEAT ENABLED (user; last on the first page; on the menu, turning it on asks for the secret Special+Punch+Jump+Right, or Start, OPTIONS on the console, to give up): OPTIONS always has the ROM's lives and level rows, without its P2 A+B+C+Right chord; the choices last until the game closes.
- **The pause menu** (`SoRPause.cpp`): RESUME, SAVE AND QUIT and FORFEIT, confirm with the cursor on NO. Each human answers for themself; YES loses all continues and dies at once. In AI Assist the one answer forfeits both. The pre-rendered music plays on, FM 9 dB down.
- **Checkpoint saves** (user, `SoRCheckpoint.cpp`): SAVE AND QUIT saves a checkpoint, not a game state: the round, the last wave gate, the mode (1P, 2P, AI Assist), the characters, and each player's score, lives, continues, specials and health at that gate. One save, `checkpoint.yaml` beside `controls.yaml`; CONTINUE on the mode menu (shown only while it exists) loads it and deletes it. Every round, round 7's elevator included (it resumes at the floor). **No saving in Mr. X's room** (user): from the pan into the throne room to the end of round 8, SAVE AND QUIT is dimmed and skipped; the last save there is the gate before the room.
- **Frame sync:** `--frame-sync auto` must work on macOS, Windows and Linux, with or without VRR, with no per-monitor setup and no tearing: the timer is the clock and frames are presented with vsync without the game waiting. Not tested on an external VRR monitor, Windows or Linux. `vsync|vsync-half|vsync-third` tie the speed to the monitor.
- **Controls:** `sor` reads SDL itself (`SoRInput.*`) and binds per-player **actions** in `~/.config/StreetsOfRageProject/controls.yaml`, set in OPTIONS > CONTROLS. Schemes are ORIGINAL 3 and ENHANCED 6; defaults are in `StreetsOfRageRecompilation/CLAUDE.md`, **Controls**. Autoplay sends actions in a binary `struct` format (no PyYAML on the system Python) and **detects** each player's scheme by querying the host, never sets it.
- **Windows console:** `sor` is a GUI-subsystem program; `openConsoleIfWanted` (`main.cpp`) gives it a console only for `--debug-utils`, `--debug-log`, `--call-log`, `--aux-addr-file`, `--help` or `--version`. Without them stdout and stderr go to the null device on every platform. Not tested on Windows.
- **Light bar** (user): each player's pad shows their character while they play, Axel blue, Adam yellow, Blaze red, and white everywhere else (menus, character select, the demo); always on, no option. On the PS5 and on a DualSense or DualShock 4 on the desktop.
- **Mode menu:** a **QUIT** row after OPTIONS ends the game.
- **PS5 menus:** `SoRPlatform::consoleMenus()`, on under `__PROSPERO__` or with `--console-menus` on the desktop for testing, hides BIND KEYBOARD and the DISPLAY row and forces fullscreen. DEVICE stays, to choose between signed-in users' pads.
- **PS5 files:** ROM, pre-rendered soundtrack and Python live in `/data/sor`. The soundtrack and the AI are obligatory there: without them the title says what to copy and closes, with no fallback.

## Hand-written C++ keeps the original memory layout

Reimplemented routines never move game state. Every field stays in 68000 work RAM at its original address, width and encoding, updated on the same frame as the ROM, and tables are read from the ROM, because `autoplay` reads the game by address (`memory_map.py`, `rom_data.py`). A reimplemented routine calls only reimplemented routines (user, 2026-11-01): reimplement the callee instead of calling generated code. See **Manual subroutines** and the `reimplement-subroutine` skill.

## Reverse-engineering tools

```bash
cd StreetsOfRageRecompilation
PYTHONPATH=../RageDecompiler python3 -m tools --help
```

Common entry points: `./scripts/disassemble_to_asm.py`, `./scripts/discover_aux_smart.py`. `code-analysis/aux_addresses.txt` adds entry points for indirect jumps and calls. The cartridge has dead code, which stays out of the recompilation (user decision): add only addresses the game can reach.

For who calls whom at runtime, record with `sor --call-log calls.csv`, collapse with `tools/call_map.py`, and query the SQLite views (`subroutine_activity`, `subroutine_flow`, `callsite_flow`), not the web viewer. Counts are observations, not proof of every path. See the `explore-call-map` skill.

## Launching: `scripts/play.py`

```bash
./scripts/play.py                       # window: configure, Ctrl+R runs both
./scripts/play.py --last                # the saved settings, no window
./scripts/play.py --preset turbo        # turbo | watch | quiet | lockstep | p2 | boss
./scripts/play.py --preset boss --level 2 --dry-run   # print the command lines only
```

`PRESETS` in `play.py` is the source of truth. Agents use the command-line form: it needs no Tk, starts from defaults plus the preset (never the saved `last_play_py_settings.yml`), does not overwrite that file, passes `--default-video` and `--default-qol`, and forwards unknown options to autoplay. Add a setting in `DEFAULTS` and the two argument builders. A copy without the sources saves settings in `~/.config/StreetsOfRageProject/` and disables Build first.

## Testing the symbolic AI live

**No AI behaviour change ships unmeasured** (user's no-regression rule): measure it live before `main`. A change validated only offline goes to a branch and says so. Only start `sor` when necessary, always with `--silent` for debug, and prefer `autoplay` unit tests for logic.

| Preset | Use |
| --- | --- |
| `turbo` | Measurement: `--turbo 6`, `--poll-ms 5.5` (about 2 frames a tick; 10x needs `--poll-ms 3.3` and a fresh measurement) |
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

Everything was tested and confirmed working (user, 2026-11-02); older "untested" or "not run" notes in these files predate that.

- Documentation only: check Markdown, links, paths, commands, and consistency with CMake and scripts.
- C++: configure, compile, and run the narrow relevant tests.
- Python: run the affected tests, then the repository suite when practical.
- Analysis or symbols: follow the synchronization rules in `StreetsOfRageRecompilation/CLAUDE.md`.
- Cross-repository: validate each repository and inspect the final gitlinks.

Finish by summarizing changed files, validation, and anything not tested on the current host.

## Other rules

- Keep the `CLAUDE.md` files updated as you work, and record in them what you learn from the user about the project. Keep them short: rules, decisions and what the code does not say, not run logs or per-function narration.
