# CLAUDE.md

Guidance for LLM agents working in the Streets of Rage project workspace.

## Scope

This repository is a public meta-repository. The project code lives in Git
submodules:

- `MegaDriveEnvironment/` - reusable C++23 Sega Mega Drive runtime/development
  environment.
- `RageDecompiler/` - Python reverse-engineering tools for disassembly,
  recompilation, label/map diffing, and speculative scanning.
- `StreetsOfRageRecompilation/` - Streets of Rage-specific C++ recompilation,
  ROM analysis data, generated code, and build/discovery scripts.
- `Genesis-Plus-GX/` - upstream emulator reference dependency. Do not edit this
  repo unless the user explicitly asks; it is not owned by this project.

Each owned submodule has its own `AGENTS.md` and `CLAUDE.md`. Read the
submodule-local `CLAUDE.md` before changing files inside that repository.

## Submodule Workflow

Clone with submodules:

```bash
git clone --recurse-submodules https://github.com/RuiNelson/StreetsOfRageProject.git
```

Initialize submodules after a plain clone:

```bash
git submodule update --init --recursive
```

After committing inside a submodule, commit the updated gitlink in this
meta-repository too:

```bash
git status -sb
git submodule status
git add <submodule-path>
git commit -m "Update <submodule-name> submodule"
```

## Publishing

After completing and validating requested changes, commit and push them
automatically unless the user explicitly asks not to publish. For changes in an
owned submodule, commit and push the submodule first, then commit and push the
updated gitlink in this meta-repository. Preserve unrelated user changes and
include them only when the user explicitly requests publishing the whole
worktree.

## Build

Most build and runtime work happens from `StreetsOfRageRecompilation/`:

```bash
cd StreetsOfRageRecompilation
./build.sh
```

Full regeneration from the local ROM:

```bash
cd StreetsOfRageRecompilation
./build.sh --full
```

The original ROM is not versioned. Put it at:

```bash
StreetsOfRageRecompilation/rom/SOR.bin
```

## Running the Game

Always run the built `sor` executable under `timeout` with a kill grace period.
Boot bugs can spin forever, and the SDL window may survive plain `SIGTERM`.

```bash
cd StreetsOfRageRecompilation
timeout -k 3 20 ./build.sh -r -- --runSor --debug --fast --rom rom/SOR.bin
```

After runs, check that no `sor` process is left behind.

## Tools

Run decompiler tools from `StreetsOfRageRecompilation/` with the sibling
`RageDecompiler` repository on `PYTHONPATH`:

```bash
cd StreetsOfRageRecompilation
PYTHONPATH=../RageDecompiler python3 -m tools --help
```

Common workflows:

```bash
./disassemble.sh
./disassemble_nolabels.sh
./disassemble_iterative.sh
./discover_aux_fast.sh
```

## Project Notes

- The static disassembler follows known code paths; active disassembly data from
  emulator runs supplies extra entry points for indirect jumps/calls.
- `StreetsOfRageRecompilation/code-analysis/aux_addresses.txt` contains known
  extra entry points.
- Generated recompilation output is produced under
  `StreetsOfRageRecompilation/generated/`.
- Do not commit ROM files, build directories, CMake fetch content, or generated
  transient outputs unless the user explicitly requests it.
