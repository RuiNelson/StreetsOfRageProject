# Building for PlayStation 5

[Back to the README](../README.md)

This builds an installed homebrew title with its own home-screen tile, drawn through
[Mesa's RADV on the console](https://github.com/mihawk-99/PS5_Vulkan). It runs only on a
jailbroken PS5 that you own, and it needs the same
[ROM as the desktop builds](BuildingDesktop.md#obtain-a-compatible-rom): nothing
copyrighted is in the title.

There are three routes to the same result. The first two need only Git and a container engine
([OrbStack](https://orbstack.dev/),
[Docker](https://www.docker.com/products/docker-desktop/) or
[Podman](https://podman-desktop.io/)), and all need about 12 GB of free disk.

## On the console

Whichever route you take, the console needs:

- [ShadowMountPlus](https://github.com/drakmor/ShadowMountPlus) 1.7beta4 or newer
- an FTP server, such as [my ftpsrv](https://github.com/RuiNelson/ftpsrv-streamextract), [drakmor's ftpsrv](https://github.com/drakmor/ftpsrv), [John Törnblom's ftpsrv](https://github.com/ps5-payload-dev/ftpsrv), etc., if you send the files over the network

## Using the Builder

[Streets of Rage Builder](BuildingDesktop.md#download-and-open-the-builder) runs on Windows,
macOS and Debian-based Linux. Choose **PlayStation 5 (Prospero)** in its first step, and it
guides you through checking Git and the container engine, downloading the source, copying the
ROM, rendering the soundtrack and building the title. **Send to PS5** then makes the ZIP files
or sends the files over FTP, and **Clean Up** offers to remove the container image and the built
title.

## The wizard (macOS, Linux and Windows)

One script does everything in a container. It checks your ROM, renders the soundtrack, builds
the title, then makes two ZIP files in the current folder or sends the files to the console over
FTP:

```bash
git clone --depth 1 --shallow-submodules --recurse-submodules https://github.com/RuiNelson/StreetsOfRageProject.git
cd StreetsOfRageProject
./scripts/ps5_wizzard.sh
```

On Windows 11, run it from a terminal, for the same result with
[Docker Desktop](https://www.docker.com/products/docker-desktop/) or
[Podman Desktop](https://podman-desktop.io/) and nothing else installed:

```powershell
git clone --depth 1 --shallow-submodules --recurse-submodules https://github.com/RuiNelson/StreetsOfRageProject.git
cd StreetsOfRageProject
.\scripts\ps5_wizzard.cmd
```

The ZIP files go on the console as follows:

| File                             | Contains     | Unpack into       |
| -------------------------------- | ------------ | ----------------- |
| `StreetsOfRage-PS5-homebrew.zip` | `PPSA99872/` | `/data/homebrew/` |
| `StreetsOfRage-PS5-data.zip`     | `sor/`       | `/data/`          |

## By hand (macOS and Linux)

On your computer: [Docker](https://www.docker.com) or any Docker-compatible software, plus the
[desktop prerequisites](BuildingDesktop.md#common-prerequisites), because the C++ generation and
the soundtrack run there. The toolchain itself is built inside Docker, and the first build takes
a while. On Windows, use one of the routes above: they correct the line endings that Git gives
the build files there, and `build_ps5.py` does not.

[Clone the repository](BuildingDesktop.md#clone-the-repository-and-submodules) and put your ROM at
`StreetsOfRageRecompilation/rom/SOR.bin`.

Generate the C++ port:

```bash
./scripts/generate_cpp.py
```

Build the title into `StreetsOfRageRecompilation/dist-ps5/`:

```bash
./scripts/build_ps5.py
```

Extract the soundtrack from your ROM (about 4 minutes, ~265 MB). On the PS5 it is required:

```bash
./scripts/render_soundtrack.py
```

Close the title if it is running, then copy everything to the console, using its address (the
FTP port is 2121 unless you pass `--port`):

```bash
./scripts/deploy_ps5.py --host your.ps5.address
```

## On the console, afterwards

The tile appears on the home screen after a few seconds. The console then holds:

| Folder                      | What is in it                                                                                                             |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `/data/homebrew/PPSA99872/` | The app                                                                                                                   |
| `/data/sor/`                | The ROM, `soundtrack/`, the AI in `ai-code/`, Python in `python/`, `controls.yaml`, `video.yaml`, `qol.yaml` and `ai.log` |

If the ROM, the soundtrack, the AI or Python is missing, the title says what to copy in a
notification and closes.

Good to know:

- The console pairs each controller with a signed-in user, so a second player needs a second
  user signed in. **1 PLAYER AI ASSIST** needs only one.
- The game always runs fullscreen, and the menus have no BIND KEYBOARD or DISPLAY row. See
  [Playing](Playing.md) for the rest of the controls and options.
- The title has no command line. If you need run-time arguments, write one per line in `/data/sor/args.txt`.
- If the AI does not play, `/data/sor/ai.log` says why.
- A built title links GPL-3.0 parts of the PS5 stack; see
  [`prospero/LICENSING.md`](../StreetsOfRageRecompilation/prospero/LICENSING.md).
