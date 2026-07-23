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
| `Genesis-Plus-GX/` | Upstream emulator used only as a behavioral reference | Upstream; never edit |

`Genesis-Plus-GX` is reference material only. Do not modify files, create
patches, reformat code, commit inside it, or update its gitlink. If comparison
with it is useful, perform read-only inspection and keep the implementation in
an owned repository.

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

After `generated/Sor.cpp` and `generated/Sor.hpp` exist locally, subsequent
builds may omit `--full`. The portable CMake path, including Windows, must be
run only after that generation step:

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

## Running safely

Game boot defects can spin indefinitely. On platforms with GNU `timeout`, use
a kill grace period:

```bash
timeout -k 3 20 ./scripts/run StreetsOfRageRecompilation/rom/SOR.bin --debug
```

After automated runs, verify that no `sor` process remains. On Windows, use a
bounded process runner or stop the process explicitly after the observation.

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

> Keep this file and the other `CLAUDE.md` files updated as you work
