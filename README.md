# Streets of Rage Project

Meta-repository for a Streets of Rage reverse-engineering and recompilation
workspace. The project is split into separate public repositories and tracked
here as Git submodules.

## Repositories

| Submodule | Purpose |
| --- | --- |
| `MegaDriveEnvironment/` | Reusable Sega Mega Drive development environment and PC runtime. |
| `RageDecompiler/` | Python reverse-engineering tools: disassembler, recompiler, label/map diffing, and speculative scanning. |
| `StreetsOfRageRecompilation/` | Streets of Rage recompilation project, including `code-analysis/`, generated C++, ROM-local scripts, and build entry points. |
| `Genesis-Plus-GX/` | Emulator reference dependency. |

`StreetsOfRageRecompilation` expects the other two repositories to live beside it:

```bash
./MegaDriveEnvironment
./RageDecompiler
./StreetsOfRageRecompilation
```

## Clone

Clone this repository with submodules:

```bash
git clone --recurse-submodules https://github.com/RuiNelson/StreetsOfRageProject.git
cd StreetsOfRageProject
```

If you already cloned without submodules:

```bash
git submodule update --init --recursive
```

Update all submodules to the commits recorded by this meta-repository:

```bash
./update_submodules.sh
```

## Build

Build the recompilation from its repository:

```bash
cd StreetsOfRageRecompilation
./build.sh
```

The original game ROM is not committed. Put your local ROM at:

```bash
StreetsOfRageRecompilation/rom/SOR.bin
```

## Tools

Run RageDecompiler commands from `StreetsOfRageRecompilation` by putting the tools repository on `PYTHONPATH`:

```bash
cd StreetsOfRageRecompilation
PYTHONPATH=../RageDecompiler python3 -m tools --help
```
