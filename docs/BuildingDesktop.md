# Building for Windows, macOS and Linux

[Back to the README](../README.md)

![VDP Dump](vdp_dump.webp)

- [Using the Builder (recommended)](#using-the-builder-recommended)
- [Building by hand](#building-by-hand)
  - [Common prerequisites](#common-prerequisites)
  - [Clone the repository and submodules](#clone-the-repository-and-submodules)
  - [Obtain a compatible ROM](#obtain-a-compatible-rom)
  - [Build on Windows](#build-on-windows)
  - [Build on macOS](#build-on-macos)
  - [Build on Linux](#build-on-linux)

For the console, see [Building for PlayStation 5](BuildingPS5.md).

## Using the Builder (recommended)

![Streets of Rage Builder](builder.webp)

The easiest way to get the game running is **Streets of Rage Builder**, a guided
installer for Windows, macOS and Debian-based Linux (Ubuntu and similar). It
does for you the steps of [building by hand](#building-by-hand); you only need a ROM you
are legally entitled to use (see [Obtain a compatible ROM](#obtain-a-compatible-rom)).
The ROM must be the **Rev. A** dump (CRC32 `4052E845`).

### Download and open the Builder

Get the file for your system from the
[latest release](https://github.com/RuiNelson/StreetsOfRageProject/releases/latest):

| System                          | File                                             |
| ------------------------------- | ------------------------------------------------ |
| macOS (Apple silicon and Intel) | `StreetsOfRageBuilder-X.Y.Z-macos-universal.dmg` |
| Windows (64-bit Intel/AMD)      | `StreetsOfRageBuilder-X.Y.Z-windows-x64.exe`     |
| Windows on ARM                  | `StreetsOfRageBuilder-X.Y.Z-windows-arm64.exe`   |
| Linux x64                       | `StreetsOfRageBuilder-X.Y.Z-x86_64.AppImage`     |
| Linux ARM64                     | `StreetsOfRageBuilder-X.Y.Z-aarch64.AppImage`    |

The apps are not signed yet, so macOS, Windows and your browser will warn you the
first time; the release page explains how to open them.

### Follow the steps

The window lists the steps on the left; **Back** and **Next** are at the bottom.
**Next** is enabled when a step is done.

1. **Choose Target**: this computer. (For the other choice, see
   [Building for PlayStation 5](BuildingPS5.md#using-the-builder).)
2. **Install Tools**: checks Git, CMake, Ninja, Python (with Tk) and a C++
   compiler, and installs what is missing with WinGet, Homebrew or apt. The
   installers open in a terminal window and may ask for your password or
   administrator approval. When they finish, the Builder checks again by itself
   (or press **Re-check**).
3. **Download Source**: choose an empty or new folder for the project. The version
   that matches this Builder is downloaded from GitHub with its submodules and a
   single commit of history. To update later, choose the same folder in a newer
   Builder.
4. **Copy ROM**: drag your ROM onto the window or browse for it (`.bin`, `.md`,
   `.gen`). Its CRC32 is checked, and it is copied into the project only if it
   is the right dump. A Super Magic Drive (`.smd`) dump must first be converted
   to a raw dump; any other version of the cartridge is not supported.
5. **Pre-render Soundtrack**: renders the music and sound effects from your ROM
   (about 4 minutes or more, ~265 MB). You can pick the sound chip: YM3438
   (default) or YM2612. Keep the window open.
6. **Build Executable**: generates the C++ from the ROM and compiles the game
   and its dependencies; it takes several minutes, longer on slow computers.
7. **Create Shortcut**: adds **StreetsOfRageRecompilation**, which starts the game,
   and **StreetsOfRageRecompilation Launcher**, which opens the launcher window. On
   Windows and Linux they are shortcuts on your desktop. On macOS they are two apps
   in a `StreetsOfRageProject` folder, in Applications or your home folder as you
   choose; the game app holds a copy of everything it needs, including your ROM.
   Click **Finish** to close the Builder.

Then double-click **StreetsOfRageRecompilation** to play, and see
[Playing](Playing.md) for the controls.

If a step fails, the last lines of its output are shown; fix the cause (for
example, a missing tool) and run the step again.

## Building by hand

The steps below do by hand what the Builder does. Follow them if you prefer, or if
your system is not supported by the Builder.

### Common prerequisites

All three desktop platforms require:

- Git, including submodule support;
- CMake 3.24 or newer;
- a compiler with C++23 support;
- network access during the first configuration, because CMake downloads CLI11,
  yaml-cpp, zlib, libpng, SDL3_mixer, and SDL3 itself unless it is already
  installed (and, for the soundtrack renderer, Genesis Plus GX and libFLAC), and
  the CPython that runs the AI in the **1 PLAYER AI ASSIST** mode: Windows downloads
  the official build, macOS and Linux build it once, about two minutes with `make`.
  It is independent of any Python installed on the machine;
- Python 3 for the first C++ generation and the analysis tools, with Tk for the
  `play.py` window;
- a compatible local ROM for the mandatory first C++ generation.

Check the main tools before configuring:

```bash
git --version
cmake --version
python3 --version
```

The repository's `scripts/*.py` launchers generate, build, and run the port on
all three desktop platforms, and use only the Python standard library. On
Windows invoke them with `py scripts\NAME.py`; on macOS and Linux they are
executable directly as `./scripts/NAME.py`. Run them from the meta-repository
root.

### Clone the repository and submodules

A build needs one commit of history and the commits of the submodules, not the
whole history, so clone shallow: `--depth 1` fetches a single commit of the
meta-repository and `--shallow-submodules` one commit of each submodule.

```bash
git clone --depth 1 --shallow-submodules --recurse-submodules https://github.com/RuiNelson/StreetsOfRageProject.git
cd StreetsOfRageProject
```

If the repository was cloned without submodules:

```bash
git submodule update --init --recursive --depth 1
```

To restore all submodules to the commits recorded by the meta-repository:

```bash
git submodule update --init --recursive --checkout --depth 1
```

### Obtain a compatible ROM

The generated C++ under `StreetsOfRageRecompilation/generated/` is ignored by
Git and is not included in a fresh clone. Before the first build, generate it
from a compatible 512 KiB Streets of Rage / Bare Knuckle ROM image at:

```text
StreetsOfRageRecompilation/rom/SOR.bin
```

#### Legal and preservation considerations

The preferred way to obtain this image is to make a private dump of a physical
cartridge that you own, or that you are otherwise explicitly authorized to
access, using a compatible Mega Drive cartridge dumper. Follow the dumper's
documentation and verify the resulting file against the reference hashes
below. This approach also contributes to responsible preservation: it keeps the
source of the image clear and avoids relying on unverified downloads.

Copyright, archival-copy, reverse-engineering, and anti-circumvention rules
differ substantially between jurisdictions. Owning a cartridge does not
necessarily grant permission to redistribute its ROM, upload it, include it in
this repository, or bypass technical protection measures. Check the law that
applies to you before making or using a dump; this project provides technical
documentation, not legal advice. Keep the ROM private, use it only as permitted
by the applicable law, and do not share it with the project or its community.

The project is developed against the `JUE` Rev. A cartridge, with these hashes:

| Property | Value                                                              |
| -------- | ------------------------------------------------------------------ |
| Size     | `524288` bytes                                                     |
| CRC32    | `4052E845`                                                         |
| MD5      | `59a3b22a1899461dceba50d1ade88d3a`                                 |
| SHA-256  | `95d7efb98e97f4ffffe68257aef9a855034a36a41b86cf9d332d129f30cb2d4b` |

ROM images are ignored by Git. Do not commit or redistribute them.

### Build on Windows

#### Prerequisites

Open PowerShell as Administrator and install the command-line tools with
[WinGet](https://learn.microsoft.com/windows/package-manager/winget/):

```powershell
winget source update

winget install --exact --id Git.Git

winget install --exact --id Kitware.CMake

winget install --exact --id Ninja-build.Ninja

winget install --exact --id Python.Python.3.14

winget install --exact --id MartinStorsjo.LLVM-MinGW.UCRT
```

The compiler is [llvm-mingw](https://github.com/mstorsjo/llvm-mingw): Clang,
LLD and libc++ for Windows, about a gigabyte, with no Visual Studio and no
Windows SDK. The game is built for the UCRT, so it runs on any current Windows.

> Important: close the terminal and open a new PowerShell (so that the new
> programs are on `PATH`)

Confirm that the tools are available:

```powershell
x86_64-w64-mingw32-clang --version   # aarch64-w64-mingw32-clang on Windows on ARM
git --version
cmake --version
ninja --version
py --version
```

#### Configure, compile, and run

Run the following from the meta-repository root in PowerShell.

After a fresh clone, generate the C++ port and create an optimized build:

```powershell
py .\scripts\generate_cpp_and_build.py --release
```

Generation is mandatory after a fresh clone.

Extract the soundtrack from your ROM (about 4 minutes, ~265 MB). Without it the
game still runs, but the sound is emulated in real time and is noticeably worse:

```powershell
py .\scripts\render_soundtrack.py
```

Run the game. There is a handy `play.py` launcher that is easy to use (**this might take a while on the first run**):

```powershell
py .\scripts\play.py
```

### Build on macOS

#### Prerequisites

Install the Xcode command-line tools and [Homebrew](https://brew.sh) dependencies:

```bash
xcode-select --install
```

```bash
brew install cmake ninja python python-tk
```

Both Apple Silicon and Intel Macs are supported. Keep CMake, the compiler, and
SDL3 on the same architecture.

#### Configure, compile, and run

After a fresh clone, generate the C++ port and create an optimized build:

```bash
./scripts/generate_cpp_and_build.py --release
```

Extract the soundtrack from your ROM (about 4 minutes, ~265 MB). Without it the
game still runs, but the sound is emulated in real time and is noticeably worse:

```bash
./scripts/render_soundtrack.py
```

Run the port:

```bash
./scripts/play.py
```

### Build on Linux

These are the commands for Ubuntu and other Debian-based systems; elsewhere,
install the same packages under your distribution's names.

#### Prerequisites

Install the compiler and build tools:

```bash
sudo apt update
```

```bash
sudo apt install build-essential cmake git ninja-build python3 python3-tk pkg-config
```

Confirm that `cmake --version` reports 3.24 or newer. SDL3 is downloaded and
built by CMake, which needs SDL's usual system development packages:

```bash
sudo apt install libasound2-dev libpulse-dev libx11-dev libxext-dev \
  libxrandr-dev libxcursor-dev libxfixes-dev libxi-dev libxss-dev \
  libxkbcommon-dev libdrm-dev libgbm-dev libgl1-mesa-dev libegl1-mesa-dev \
  libdbus-1-dev libudev-dev libwayland-dev libdecor-0-dev
```

#### Configure, compile, and run

Generate the C++ port and create the first optimized build:

```bash
./scripts/generate_cpp_and_build.py --release
```

Extract the soundtrack from your ROM (about 4 minutes, ~265 MB). Without it the
game still runs, but the sound is emulated in real time and is noticeably worse:

```bash
./scripts/render_soundtrack.py
```

Run the port:

```bash
./scripts/play.py
```
