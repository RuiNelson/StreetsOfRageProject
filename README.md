# Streets of Rage Project

This repository assembles the complete Streets of Rage reverse-engineering and
native recompilation workspace. The playable host port is C++23; its runtime,
analysis tools, sample game, and emulator reference are pinned as Git
submodules so the full workspace can be reproduced from one clone.

> The project does not include the original Streets of Rage ROM. You must
> provide a compatible dump that you are legally entitled to use.

## Repository layout

| Submodule | Purpose |
| --- | --- |
| [`MegaDriveEnvironment/`](MegaDriveEnvironment/) | SDL3-based Mega Drive host runtime and reusable C++ library |
| [`StreetsOfRageRecompilation/`](StreetsOfRageRecompilation/) | Streets of Rage generated/native C++, analysis data, build scripts, and `sor` executable |
| [`RageDecompiler/`](RageDecompiler/) | Python disassembler, recompiler, label tools, and discovery workflows |
| [`MegaDriveEnvironmentSampleGame/`](MegaDriveEnvironmentSampleGame/) | Small game that targets both the PC runtime and real Mega Drive hardware |
| [`Genesis-Plus-GX/`](Genesis-Plus-GX/) | Read-only upstream emulator reference; it is not modified by this project |

The playable port expects `MegaDriveEnvironment`, `RageDecompiler`, and
`StreetsOfRageRecompilation` to remain sibling directories. This is the layout
created by the meta-repository.

## Clone the complete workspace

```bash
git clone --recurse-submodules https://github.com/RuiNelson/StreetsOfRageProject.git
cd StreetsOfRageProject
```

If the repository was cloned without submodules:

```bash
git submodule update --init --recursive
```

To restore every submodule to the commit recorded by this repository:

```bash
git submodule update --init --recursive --checkout
```

## ROM requirement

A normal build compiles the checked-in generated C++ and does not read the ROM.
Running the game or regenerating the C++ requires a compatible 512 KiB
Streets of Rage / Bare Knuckle dump at:

```text
StreetsOfRageRecompilation/rom/SOR.bin
```

The project is developed against the `JUE` cartridge with these hashes:

| Property | Value |
| --- | --- |
| Size | `524288` bytes |
| MD5 | `59a3b22a1899461dceba50d1ade88d3a` |
| SHA-256 | `95d7efb98e97f4ffffe68257aef9a855034a36a41b86cf9d332d129f30cb2d4b` |

ROM images are ignored by Git. Do not commit or redistribute them.

## Common prerequisites

All three desktop platforms need:

- Git, including Git submodule support;
- CMake 3.24 or newer;
- a compiler with C++23 support;
- SDL3 development headers and libraries;
- network access during the first configuration, because CMake downloads
  CLI11, yaml-cpp, zlib, and libpng;
- Python 3 only for full ROM regeneration and analysis tools.

Check the main tools before configuring:

```bash
git --version
cmake --version
python3 --version
```

## Build on Windows

### Prerequisites

Install:

1. Visual Studio 2022 Build Tools or Visual Studio 2022 with **Desktop
   development with C++**;
2. Git for Windows;
3. CMake and Ninja;
4. Python 3;
5. [vcpkg](https://github.com/microsoft/vcpkg), used here to provide SDL3.

Open **Developer PowerShell for VS 2022**. Bootstrap vcpkg once and install the
64-bit SDL3 package:

```powershell
git clone https://github.com/microsoft/vcpkg.git C:\src\vcpkg
C:\src\vcpkg\bootstrap-vcpkg.bat
C:\src\vcpkg\vcpkg.exe install sdl3:x64-windows
```

### Configure and compile

From the meta-repository root:

```powershell
$VcpkgRoot = "C:\src\vcpkg"
$BuildDir = "$PWD\StreetsOfRageRecompilation\build\windows"
$BinDir = "$BuildDir\bin"

cmake -S StreetsOfRageRecompilation -B $BuildDir -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DCMAKE_TOOLCHAIN_FILE="$VcpkgRoot\scripts\buildsystems\vcpkg.cmake" `
  -DCMAKE_RUNTIME_OUTPUT_DIRECTORY="$BinDir"

cmake --build $BuildDir --parallel
```

`CMAKE_RUNTIME_OUTPUT_DIRECTORY` puts `sor.exe` and the shared libraries built
by the project in one directory, avoiding Windows DLL search-path problems.

Run the port:

```powershell
& "$BinDir\sor.exe" --runSor --rom StreetsOfRageRecompilation\rom\SOR.bin
```

If CMake cannot find SDL3, confirm that the toolchain path and vcpkg triplet
used during configuration match the installed `sdl3:x64-windows` package.

## Build on macOS

### Prerequisites

Install the Xcode command-line tools and Homebrew dependencies:

```bash
xcode-select --install
brew install cmake ninja sdl3 python
```

Both Apple Silicon and Intel Macs are supported by the native Homebrew
toolchain. Keep CMake, the compiler, and SDL3 on the same architecture.

### Configure and compile

The project wrapper builds a Debug configuration by default:

```bash
cd StreetsOfRageRecompilation
./build.sh
```

For an optimized build:

```bash
./build.sh --clean --type Release
```

Run the port:

```bash
./build.sh --run -- --runSor --rom rom/SOR.bin
```

The equivalent direct CMake workflow is:

```bash
cmake -S StreetsOfRageRecompilation \
  -B StreetsOfRageRecompilation/build/macos \
  -G Ninja \
  -DCMAKE_BUILD_TYPE=Release
cmake --build StreetsOfRageRecompilation/build/macos --parallel
```

## Build on Ubuntu

### Prerequisites

Install the compiler and build tools:

```bash
sudo apt update
sudo apt install build-essential cmake git ninja-build python3 pkg-config
```

Verify that `cmake --version` reports 3.24 or newer. On an Ubuntu release whose
package repository provides SDL3:

```bash
sudo apt install libsdl3-dev
```

If `libsdl3-dev` is unavailable, build SDL's maintained SDL3 release branch:

```bash
sudo apt install libasound2-dev libpulse-dev libx11-dev libxext-dev \
  libxrandr-dev libxcursor-dev libxfixes-dev libxi-dev libxss-dev \
  libwayland-dev libxkbcommon-dev libgl1-mesa-dev libegl1-mesa-dev

git clone --depth 1 --branch release-3.2.x \
  https://github.com/libsdl-org/SDL.git /tmp/SDL3
cmake -S /tmp/SDL3 -B /tmp/SDL3/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DSDL_TEST_LIBRARY=OFF
cmake --build /tmp/SDL3/build --parallel
sudo cmake --install /tmp/SDL3/build
sudo ldconfig
```

### Configure and compile

```bash
cd StreetsOfRageRecompilation
./build.sh --clean --type Release
```

Run the port:

```bash
./build.sh --run -- --runSor --rom rom/SOR.bin
```

The equivalent direct CMake workflow is:

```bash
cmake -S StreetsOfRageRecompilation \
  -B StreetsOfRageRecompilation/build/ubuntu \
  -G Ninja \
  -DCMAKE_BUILD_TYPE=Release
cmake --build StreetsOfRageRecompilation/build/ubuntu --parallel
```

If SDL3 was installed to a custom prefix, add
`-DCMAKE_PREFIX_PATH=/path/to/prefix` during configuration.

## Regenerate the port from the ROM

Normal builds use `StreetsOfRageRecompilation/generated/Sor.cpp`. Regeneration
is needed only when changing disassembly/recompilation data or generated code.

On macOS, Ubuntu, Git Bash, or another Bash environment:

```bash
cd StreetsOfRageRecompilation
./build.sh --full
```

On native Windows PowerShell, run the equivalent Python command before the
CMake build:

```powershell
$env:PYTHONPATH = (Resolve-Path RageDecompiler)
python -m tools recompile StreetsOfRageRecompilation\rom\SOR.bin `
  -o StreetsOfRageRecompilation\generated `
  --manual-functions StreetsOfRageRecompilation\code-analysis\manual_functions.txt
```

Regeneration intentionally changes checked-in files under `generated/`.

## Tests and developer tools

Build and run the reusable environment's tests:

```bash
cmake -S MegaDriveEnvironment -B MegaDriveEnvironment/build \
  -DCMAKE_BUILD_TYPE=Debug
cmake --build MegaDriveEnvironment/build --parallel
ctest --test-dir MegaDriveEnvironment/build --output-on-failure
```

Run the Python decompiler tests:

```bash
cd RageDecompiler
python3 -m pytest
```

Inspect the reverse-engineering CLI:

```bash
cd StreetsOfRageRecompilation
PYTHONPATH=../RageDecompiler python3 -m tools --help
```

The sample game's separate PC and real-hardware workflows are documented in
[`MegaDriveEnvironmentSampleGame/docs/BUILDING.md`](MegaDriveEnvironmentSampleGame/docs/BUILDING.md).

## Updating the workspace

`update_submodules.sh` follows the configured branches and may advance several
gitlinks. Use it only when intentionally updating dependencies:

```bash
./update_submodules.sh
```

For a reproducible checkout, prefer `git submodule update --init --recursive`
and keep the commits recorded by this meta-repository.
