# Agent guide

Instructions for automated contributors working in the Streets of Rage
workspace.

## Start here

1. Inspect `git status` in the meta-repository and in every submodule that is
   in scope. Preserve unrelated changes.
2. Read the local `CLAUDE.md` before editing an owned submodule.
3. Identify whether the requested change belongs to the meta-repository or to
   one or more submodules. Do not place project code in the meta-repository.
4. Use the smallest relevant build or test first, then expand validation in
   proportion to the change.

## Repository map and ownership

This public meta-repository pins the repositories that make up the workspace:

| Path | Role | Ownership |
| --- | --- | --- |
| `MegaDriveEnvironment/` | C++23 Mega Drive host runtime and development library | Project-owned; editable |
| `MegaDriveEnvironmentSampleGame/` | Dual-target sample for PC and real Mega Drive hardware | Project-owned; editable |
| `RageDecompiler/` | Python disassembly and recompilation tools | Project-owned; editable |
| `StreetsOfRageRecompilation/` | Streets of Rage analysis, generated C++, native overrides, and host executable | Project-owned; editable |
| `autoplay/` | Python remote SoR observer + symbolic AI (`megadrive_remote`) | Project-owned; editable; **not a submodule** |
| `Genesis-Plus-GX/` | Upstream emulator used only as a behavioral reference | Upstream; never edit |

`Genesis-Plus-GX` is reference material only. Do not modify files, create
patches, reformat code, commit inside it, or update its gitlink. If comparison
with it is useful, perform read-only inspection and keep the implementation in
an owned repository.

Unlike the other rows above, `autoplay/` is tracked directly in this
meta-repository (no entry in `.gitmodules`, no separate remote) despite this
table's wording — commit and push its changes as part of a normal
meta-repository commit, not through the submodule workflow below, and do not
attempt to update a gitlink for it.

## Submodule workflow

Clone the complete workspace with:

```bash
git clone --recurse-submodules https://github.com/RuiNelson/StreetsOfRageProject.git
cd StreetsOfRageProject
```

Initialize an existing plain clone with:

```bash
git submodule update --init --recursive
```

The checked-out submodule commits are part of the reproducible workspace.
Do not advance them casually. When a requested change spans an owned
submodule:

1. make and validate the change inside that submodule;
2. commit and push the submodule after validation unless the user explicitly
   asks not to publish;
3. update the meta-repository gitlink in the same delivery;
4. report both repositories and their validation.

After completing and validating requested changes, commit and push them to
`main` automatically unless the user explicitly asks not to publish. Never
include unrelated dirty files in a commit. Do not force-push, rewrite history,
or open a pull request unless the user explicitly requests that action.

## Build model

The playable port is built from `StreetsOfRageRecompilation/`, which consumes
the sibling `MegaDriveEnvironment/` checkout. Its `generated/` directory is
ignored by Git, so a fresh checkout must run the decompiler before CMake.

Requirements:

- CMake 3.24 or newer;
- a C++23 compiler;
- SDL3 development files;
- Git and network access for first-time CMake `FetchContent` dependencies;
- Python 3 and a compatible local ROM for the mandatory first C++ generation,
  analysis scripts, and Python tests.

On macOS and Linux, the preferred wrappers are:

```bash
./scripts/generate_cpp_and_build
./scripts/generate_cpp_and_build --release
```

After `generated/SoR.hpp`, `generated/SoR-common.hpp`, and the split
`generated/SoR-XXX.cpp` files exist locally, subsequent builds may omit
`--full`. Each source group uses the first three hexadecimal digits of its
first subroutine entry address. The portable CMake path, including Windows,
must be run only after that generation step:

```bash
cmake -S StreetsOfRageRecompilation \
  -B StreetsOfRageRecompilation/build \
  -DCMAKE_BUILD_TYPE=Debug
cmake --build StreetsOfRageRecompilation/build --parallel
```

With the Visual Studio generator, select the configuration on both build and
test commands (`--config Release` and `ctest -C Release`); `CMAKE_BUILD_TYPE`
is for single-configuration generators. See `README.md` for platform-specific
prerequisites and exact Windows, macOS, and Ubuntu commands.

## ROM and generated code

The original ROM is copyrighted and is never versioned. A legally obtained
compatible dump may be placed at:

```text
StreetsOfRageRecompilation/rom/SOR.bin
```

`generated/` is ignored by Git. Generate it after a fresh clone and regenerate
it whenever ROM analysis or recompiler inputs change:

```bash
./scripts/generate_cpp
```

Do not commit ROMs, ignored generated C++, build trees, CMake download trees,
caches, screenshots, or transient discovery output.



## Reverse-engineering tools

Run tools from the recompilation repository with the sibling decompiler on
`PYTHONPATH`:

```bash
cd StreetsOfRageRecompilation
PYTHONPATH=../RageDecompiler python3 -m tools --help
```

Prefer the repository entry points for common workflows:

```bash
./scripts/disassemble_to_asm
./scripts/discover_aux_smart
```

The static disassembler follows known control flow. Active runtime discovery
and `code-analysis/aux_addresses.txt` provide additional entry points for
indirect jumps and calls.

### Runtime call recording and call map

For **game analysis** (who calls whom at runtime, which labelled routines
actually run, callsites for a given flow), use the recompilation binary's
optional call log and `tools/call_map.py`. Full schema, flags, and agent
rules live in `StreetsOfRageRecompilation/CLAUDE.md` and the
`explore-call-map` skill; this is the workspace overview.

1. **Record** while playing or automating a bounded session of `sor`. Every
   emulated 68000 subroutine **entry** and `bsr`/`jsr` **call** is written as
   typed CSV (`event,source,callsite,target`). Addresses are six-digit hex
   ROM addresses. The file is truncated at startup.

```bash
StreetsOfRageRecompilation/build/sor \
  --rom StreetsOfRageRecompilation/rom/SOR.bin \
  --callLog calls.csv
```

2. **Collapse** one or more logs into a deduplicated SQLite call map. The
   tool always includes every routine from
   `StreetsOfRageRecompilation/code-analysis/labels.csv` (including zero
   activity), so labelled-only routines stay visible next to observed ones.

```bash
python3 StreetsOfRageRecompilation/tools/call_map.py calls.csv \
  --database StreetsOfRageRecompilation/call-map.sqlite \
  --labels StreetsOfRageRecompilation/code-analysis/labels.csv
```

3. **Analyse** by querying SQLite (agents must not rely on the web viewer).
   Prefer the views `subroutine_activity`, `subroutine_flow`, and
   `callsite_flow`. Counts are runtime observations from the captured runs,
   not proof of every static path. Optional `--port` starts a localhost
   read-only viewer for humans only.

Call logs, `call-map.sqlite`, and similar artefacts are local analysis
output: do not commit them unless the user explicitly asks to version that
exact file. Use this map together with `ai-analysis/*.md` manuscripts and
`labels.csv` when mapping control flow for reverse engineering or AI work.

## Testing the symbolic AI live

When a change needs a live session of the symbolic AI (not unit tests),
run the host in turbo and raise autoplay's poll cadence so the agent
still samples about two game frames per tick. Prefer the wrapper:

```bash
./scripts/both_turbo
```

That is equivalent to:

```bash
./scripts/run --turbo 4 --lang en --debugUtils --port 7777 --silent &
./scripts/autoplay --poll-ms 8 --port 7777 --agent-p1 --reach-gameplay blaze
```

- `--turbo 4` (with the default `--vsync 0`) runs the internal VDP at
  `60 × 4` Hz.
- `--poll-ms 8` replaces the default 33 ms wall-clock poll (~2 frames
  at 60 Hz) with ~2 frames at 240 Hz. Do not leave `--poll-ms` at 33
  under turbo: the AI would see every eighth frame and miss holds,
  jumps, and incoming attacks.
- `--silent` is required whenever the game is launched for debug.
- Only start a live `sor` session when necessary; prefer `autoplay`
  unit tests for logic changes.

Keep `scripts/both_turbo` as the source of truth for these flags. If the
wrapper's turbo factor or `--poll-ms` changes, update this section to
match.

### Going straight to a boss

`scripts/go_to_boss_1` … `scripts/go_to_boss_8` put the AI in front of one
round's boss with nothing else on screen: same turbo host and poll cadence as
`both_turbo`, plus `--start-level N` and `--kill-street-enemies`, so autoplay
navigates the menus, jumps to the round, and keeps every ordinary family
swept for the rest of the session.

```bash
./scripts/go_to_boss_1            # round 1, Antonio
./scripts/go_to_boss_2 --agent-p2 # extra args pass through to autoplay
./scripts/go_to_boss 5            # the shared implementation, by level
```

| Script | Round | Boss |
| --- | --- | --- |
| `go_to_boss_1` | 1 | Antonio (`$56`) |
| `go_to_boss_2` | 2 | Souther (`$55`) |
| `go_to_boss_3` | 3 | Abadede (`$30`) |
| `go_to_boss_4` | 4 | Bongo (`$57`) |
| `go_to_boss_5` | 5 | Onihime & Yasha (`$58` pair) |
| `go_to_boss_6` | 6 | Bongo (`$57`), then a Souther pair (`$55`) |
| `go_to_boss_7` | 7 | none — the ELC stream has no terminal boss section |
| `go_to_boss_8` | 8 | boss rush, `$56` → `$55` → `$30` → `$57` → `$58` → Mr. X (`$35`) |

The numbered scripts are one line each; the turbo/poll/port flags live only
in `scripts/go_to_boss`, so eight copies cannot drift apart. Sweeping is not
optional for boss work — see `autoplay/CLAUDE.md`. Quitting the HUD (Esc/Q)
also shuts the host down, so the port is free for the next run.

## Validation and handoff

- Documentation-only changes: check Markdown structure, links, paths, command
  syntax, and consistency with CMake/scripts.
- C++ runtime changes: configure, compile, and run the narrow relevant tests.
- Python tooling changes: run the affected tests, then the repository suite
  when practical.
- Analysis/symbol changes: follow the synchronization and regeneration rules
  in `StreetsOfRageRecompilation/CLAUDE.md`.
- Cross-repository changes: validate each changed repository and inspect the
  final meta-repository gitlinks.

Finish by summarizing changed files, validation performed, and anything not
tested on the current host.

## Other rules

- do not consult git history
- Keep this file and the other `CLAUDE.md` files updated as you work
- Save in the `CLAUDE.md` all the information that charactizes the project that you obtain from the user.
- If running the game for debug, only run if **necessary**, remember to use `--silent` to silence the sound
- When testing the symbolic AI live, use turbo and a matching autoplay cadence (`./scripts/both_turbo`); see **Testing the symbolic AI live** above

 