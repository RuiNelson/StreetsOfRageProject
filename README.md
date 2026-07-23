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

The generated C++ under `StreetsOfRageRecompilation/generated/` is ignored by
Git and is not included in a fresh clone. Before the first build, generate it
from a compatible 512 KiB Streets of Rage / Bare Knuckle dump at:

```text
StreetsOfRageRecompilation/rom/SOR.bin
```

The project is developed against the `JUE` cartridge with these hashes:

| Property | Value |
| --- | --- |
| Size | `524288` bytes |
| CRC32 | `4052E845` (WinRAR checked) |
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
- Python 3 for the mandatory first C++ generation and analysis tools;
- a compatible local ROM for the mandatory first C++ generation.

Check the main tools before configuring:

```bash
git --version
cmake --version
python3 --version
```

## Build on Windows

### Prerequisites

Open PowerShell as Administrator and install the command-line tools with
[WinGet](https://learn.microsoft.com/windows/package-manager/winget/):

```powershell
winget source update

winget install --exact --id Git.Git --source winget `
  --accept-package-agreements --accept-source-agreements

winget install --exact --id Kitware.CMake --source winget `
  --accept-package-agreements --accept-source-agreements

winget install --exact --id Ninja-build.Ninja --source winget `
  --accept-package-agreements --accept-source-agreements

winget install --exact --id Python.Python.3.14 --source winget `
  --accept-package-agreements --accept-source-agreements

winget install --exact --id Microsoft.VisualStudio.2022.BuildTools `
  --source winget `
  --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools;includeRecommended" `
  --accept-package-agreements --accept-source-agreements
```

The `Microsoft.VisualStudio.Workload.VCTools` workload supplies MSVC, the
Windows SDK, and the native x64/x86 build environment. The
`;includeRecommended` suffix also installs the workload's recommended CMake
and vcpkg integration components. See Microsoft's
[Build Tools component list](https://learn.microsoft.com/visualstudio/install/workload-component-id-vs-build-tools?view=visualstudio)
and
[command-line installation reference](https://learn.microsoft.com/visualstudio/install/use-command-line-parameters-to-install-visual-studio?view=visualstudio).

Close the administrator terminal after installation and open **Developer
PowerShell for VS 2022** from the Start menu. Confirm that the tools are
available:

```powershell
where.exe cl
cl
git --version
cmake --version
ninja --version
python --version
```

Python is required to generate the ignored C++ files after a fresh clone.
After `generated/Sor.cpp` and `generated/Sor.hpp` exist locally, subsequent
incremental builds do not need to run Python again unless the analysis inputs
change.

Use Microsoft's official [vcpkg](https://github.com/microsoft/vcpkg) bootstrap
flow to install the SDL3 development package in a predictable location:

```powershell
$VcpkgRoot = "C:\src\vcpkg"

git clone https://github.com/microsoft/vcpkg.git $VcpkgRoot
& "$VcpkgRoot\bootstrap-vcpkg.bat" -disableMetrics
& "$VcpkgRoot\vcpkg.exe" install sdl3:x64-windows
```

The `sdl3:x64-windows` port provides the headers, import library, and runtime
DLL for a 64-bit build. The vcpkg toolchain makes it available to the
project's `find_package(SDL3 REQUIRED)` call.

### Generate the C++ port

This step is mandatory after a fresh clone because `generated/` is ignored by
Git. Run it from the meta-repository root before invoking CMake:

```powershell
$env:PYTHONPATH = (Resolve-Path RageDecompiler)

python -m tools recompile StreetsOfRageRecompilation\rom\SOR.bin `
  -o StreetsOfRageRecompilation\generated `
  --aux StreetsOfRageRecompilation\code-analysis\aux_addresses.txt `
  --labels-csv StreetsOfRageRecompilation\code-analysis\labels.csv `
  --addresses-csv StreetsOfRageRecompilation\code-analysis\addresses.csv `
  --manual-functions StreetsOfRageRecompilation\code-analysis\manual_functions.txt
```

This requires the compatible ROM at
`StreetsOfRageRecompilation\rom\SOR.bin`. The command creates the local
`StreetsOfRageRecompilation\generated\Sor.cpp` and `Sor.hpp`. Regenerate them
whenever ROM analysis, labels, auxiliary addresses, manual-function inputs, or
the recompiler changes. These outputs remain ignored and must not be committed.
See [Regenerate the port from the ROM](#regenerate-the-port-from-the-rom) for
the equivalent Bash workflow.

### Configure and compile

From the meta-repository root in the same **Developer PowerShell for VS 2022**
session:

```powershell
$VcpkgRoot = "C:\src\vcpkg"
$BuildDir = "build/windows"
$BinDir = (Join-Path (Resolve-Path ".") "$BuildDir/bin")

cmake -S StreetsOfRageRecompilation -B $BuildDir -G "Visual Studio 17 2022" -A x64 `
  -DCMAKE_TOOLCHAIN_FILE="$VcpkgRoot\scripts\buildsystems\vcpkg.cmake" `
  -DCMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE="$BinDir"

cmake --build $BuildDir --config Release --parallel
```

The Visual Studio generator is multi-configuration, so `--config Release`
selects the optimized build. `CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE` puts
`sor.exe` in `$BinDir`, and the project copies all required runtime DLLs beside
it after linking.

Run the port:

```powershell
.\build\windows\bin\sor.exe --rom ".\StreetsOfRageRecompilation\rom\SOR.bin" --lang en
```

If CMake cannot find SDL3, confirm that the toolchain path and vcpkg triplet
used during configuration match the installed `sdl3:x64-windows` package.

**For information about configuring the controls and other settings, read the `StreetsOfRageRecompilation` README [here](https://github.com/RuiNelson/StreetsOfRageProject).**

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

Generate the ignored C++ and build a Debug configuration after a fresh clone:

```bash
cd StreetsOfRageRecompilation
./build.sh --full
```

For the first optimized build:

```bash
./build.sh --full --clean --type Release
```

Once `generated/Sor.cpp` and `generated/Sor.hpp` exist locally, subsequent
builds may use `./build.sh` without `--full`.

Run the port:

```bash
./build.sh --run -- --rom rom/SOR.bin
```

The equivalent direct CMake workflow is:

```bash
cmake -S StreetsOfRageRecompilation \
  -B StreetsOfRageRecompilation/build/macos \
  -G Ninja \
  -DCMAKE_BUILD_TYPE=Release
cmake --build StreetsOfRageRecompilation/build/macos --parallel
```

**For information about configuring the controls and other settings, read the `StreetsOfRageRecompilation` README [here](https://github.com/RuiNelson/StreetsOfRageProject).**

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

Generate the ignored C++ and create the first optimized build:

```bash
cd StreetsOfRageRecompilation
./build.sh --full --clean --type Release
```

Once `generated/Sor.cpp` and `generated/Sor.hpp` exist locally, subsequent
builds may omit `--full`.

Run the port:

```bash
./build.sh --run -- --rom rom/SOR.bin
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

**For information about configuring the controls and other settings, read the `StreetsOfRageRecompilation` README [here](https://github.com/RuiNelson/StreetsOfRageProject).**

## Regenerate the port from the ROM

`StreetsOfRageRecompilation/generated/` is ignored by Git. Generation is
mandatory after a fresh clone and must be repeated whenever the ROM analysis,
labels, auxiliary addresses, manual-function inputs, or RageDecompiler changes.
Once the local generated files exist and their inputs are unchanged,
incremental builds can skip this step.

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
  --aux StreetsOfRageRecompilation\code-analysis\aux_addresses.txt `
  --labels-csv StreetsOfRageRecompilation\code-analysis\labels.csv `
  --addresses-csv StreetsOfRageRecompilation\code-analysis\addresses.csv `
  --manual-functions StreetsOfRageRecompilation\code-analysis\manual_functions.txt
```

Regeneration creates or replaces ignored local files under `generated/`.
Do not add them to Git.

## Tests and developer tools

Build and run the reusable environment's tests:

```powershell
$VcpkgRoot = "C:\src\vcpkg"

cmake -S MegaDriveEnvironment -B MegaDriveEnvironment/build/windows `
  -G "Visual Studio 17 2022" -A x64 `
  -DCMAKE_TOOLCHAIN_FILE="$VcpkgRoot\scripts\buildsystems\vcpkg.cmake"
cmake --build MegaDriveEnvironment/build/windows --config Debug --parallel
ctest --test-dir MegaDriveEnvironment/build/windows -C Debug `
  --output-on-failure
```

Run the Python decompiler tests:

```powershell
cd RageDecompiler
python -m pytest
```

Inspect the reverse-engineering CLI:

```powershell
$env:PYTHONPATH = (Resolve-Path RageDecompiler)
python -m tools --help
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
