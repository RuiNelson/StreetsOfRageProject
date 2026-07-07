# Streets of Rage Project Workspace

This workspace is split into three local repositories:

| Repository | Purpose |
| --- | --- |
| `MegaDriveEnvironment/` | Reusable Sega Mega Drive development environment and PC runtime. |
| `RageDecompiler/` | Python reverse-engineering tools: disassembler, recompiler, label/map diffing, and speculative scanning. |
| `StreetsOfRageRecompilation/` | Streets of Rage recompilation project, including `code-analysis/`, generated C++, ROM-local scripts, and build entry points. |

`StreetsOfRageRecompilation` expects the other two repositories to live beside it:

```bash
./MegaDriveEnvironment
./RageDecompiler
./StreetsOfRageRecompilation
```

Build the recompilation from its repository:

```bash
cd StreetsOfRageRecompilation
./build.sh
```

Run RageDecompiler commands from `StreetsOfRageRecompilation` by putting the tools repository on `PYTHONPATH`:

```bash
cd StreetsOfRageRecompilation
PYTHONPATH=../RageDecompiler python3 -m tools --help
```
