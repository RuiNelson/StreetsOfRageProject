# Streets of Rage Project

This is the public meta-repository for a Streets of Rage reverse-engineering and
recompilation workspace. The actual work lives in separate repositories,
tracked here as Git submodules so the whole tree can be checked out together.

## Repositories

| Submodule | Purpose |
| --- | --- |
| `MegaDriveEnvironment/` | Reusable Sega Mega Drive development environment and PC runtime. |
| `MegaDriveEnvironmentSampleGame/` | Small playable example of a new game built on `MegaDriveEnvironment`. |
| `RageDecompiler/` | Python tools: disassembler, recompiler, label/map diffing, and speculative scanning. |
| `StreetsOfRageRecompilation/` | Streets of Rage recompilation — analysis data, generated C++, scripts, and build entry points. |
| `Genesis-Plus-GX/` | Emulator reference dependency. |

The recompilation project expects its two main dependencies as siblings:

```text
./MegaDriveEnvironment
./RageDecompiler
./StreetsOfRageRecompilation
```

That layout is what you get from a full clone of this meta-repository.

## Clone

```bash
git clone --recurse-submodules https://github.com/RuiNelson/StreetsOfRageProject.git
cd StreetsOfRageProject
```

If the repo was cloned without submodules:

```bash
git submodule update --init --recursive
```

To refresh every submodule to the commits recorded here:

```bash
./update_submodules.sh
```

## Build

The sample game is a plain CMake project:

```bash
cd MegaDriveEnvironmentSampleGame
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
./build/mega_drive_environment_sample_game
```

Streets of Rage uses its own wrapper. Drop a local copy of the original ROM at
`StreetsOfRageRecompilation/rom/SOR.bin` (it is not versioned), then:

```bash
cd StreetsOfRageRecompilation
./build.sh
```

See that repository’s README for run flags, full ROM recompilation, and
disassembly workflows.

## Tools

From `StreetsOfRageRecompilation`, put the sibling tools repo on `PYTHONPATH`
and call the CLI:

```bash
cd StreetsOfRageRecompilation
PYTHONPATH=../RageDecompiler python3 -m tools --help
```
