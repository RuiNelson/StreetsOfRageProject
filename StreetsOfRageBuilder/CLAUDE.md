# Agent guide

Tauri 2 + Next.js static-export wizard that builds Streets of Rage from a ROM
(see `README.md`). Tracked directly in the meta-repository (not a submodule).
The frontend (`Frontend/`) must stay statically exportable: no runtime server,
no API routes. All system work (installing dependencies, git clone, CRC check,
running the project's scripts) belongs in Rust commands under `Backend/src/`,
called through `Frontend/src/lib/tauri.ts`. Steps and order: `Frontend/src/lib/steps.ts`.
Run npm scripts from `Frontend/` (`npm run tauri dev` does `cd ../Backend`).
Validate with `npm run lint`, `npm run build` (Frontend) and `cargo check` (Backend).

## The Python AI inside `sor`

The game builds its own CPython (`StreetsOfRageRecompilation/cmake/CPythonRuntime.cmake`) during
step 5's configure: about 2 minutes more the first time, no new entry in the tables below (`make`
comes with the Xcode tools and `build-essential`; Windows downloads a prebuilt one). The game's
shortcut passes `--ai-path`, and the Launcher's `play.py` gets it from `run.py`. The build and
the mode were run on Windows by hand, not through the Builder; Linux is untested.

## Step 1: dependencies

`Backend/src/dependencies.rs` holds one `Spec` table per platform (check + install
recipe: winget id, brew formulas or apt packages). `system.rs` resolves programs on
a refreshed search path (Homebrew dirs on macOS, registry PATH on Windows) so a GUI
launch and a just-finished install are both seen. Installs open the system terminal (Terminal.app, cmd, or the first terminal emulator
found on Linux) with a generated script, so the user sees the installers' own output and
prompts; the app does not wait, and re-checks when its window regains focus or on Re-check. Keep the tables in step with the
project README prerequisites. The macOS code path was compiled and run; on Windows (x64,
real machine over SSH) the app compiles, the unit tests pass and the dependency report and the
`.lnk` creation were checked; the GUI flows on Windows, and everything on Linux, are untested.

## Step 2: download the project

`Backend/src/project.rs` puts the project in the exact folder the user chooses (user
decision, so the same folder is chosen again to update it). It downloads the commit tagged with
the Builder's own version (`CARGO_PKG_VERSION`: Builder 0.3.1, tag `0.3.1`), neither older nor newer
(user decision, 2026-10-31), so a version of the Builder only works once its tag exists: a draft or
artifacts-only build reports that the version has not been released. A player, not a
developer, so `git clone --depth 1 --branch TAG --recurse-submodules --shallow-submodules`, one commit
of history everywhere. A folder that is a copy (a `.git` whose origin names
StreetsOfRageProject) is moved to the tag, forwards or backwards: `fetch --depth 1` of the tag,
`checkout --force --detach` and a submodule update, replacing local changes (ROM and soundtrack are
gitignored, so they survive). A missing or empty folder is cloned into; anything else is refused. git's
`\r`-redrawn progress reaches the UI as lines through a Tauri `Channel`;
`GIT_TERMINAL_PROMPT=0` keeps git from waiting on a hidden prompt. The chosen path lives in
`Wizard` (`projectPath`) for the later steps.
Unit tests clone a local repo through `file://` (a plain path ignores `--depth`); the
network test against the real repository is `#[ignore]`d (`SOR_TEST_FOLDER=dir cargo test
real_project -- --ignored`).

## Step 3: the ROM

`Backend/src/rom.rs` verifies the user's ROM by CRC32 (the `crc` crate, `CRC_32_ISO_HDLC`)
against the project's `SOR.bin` (`4052E845`, 512 KiB raw dump, the "Rev. A" version of the game, which the step tells the user to obtain) and, only when it matches,
copies it to `StreetsOfRageRecompilation/rom/SOR.bin` inside the chosen project folder.
The ROM comes from the file dialog (extensions `.md` `.gen` `.bin` `.smd` plus all files) or
by dragging it on the window (`getCurrentWebview().onDragDropEvent`). Three outcomes:
`ok`; `smd` (Super Magic Drive: 512-byte header with `AA BB`, 16 KiB blocks; not supported
directly, the user is asked to convert it to a raw dump); `mismatch` (not the game, or a
cartridge version the project does not support: the user is told to get a copy of the
original). The UI warns to use only a legally obtained ROM. `installed_rom` lets the step
recognise a ROM already in the project when the user comes back to it.

## Step 4: extract the sound

`Backend/src/sound.rs` runs the project's own `scripts/render_soundtrack.py` with the chip the
user picked in the step (`--chip ym3438`, the default, or `ym2612`; user request; no `--out`)
in the project folder with the first working Python
(`script::run`, shared with step 5: first working Python from `dependencies::python_candidates`,
`PYTHONUNBUFFERED`), streaming stdout and stderr line by line to the UI (`system::read_lines`). The first run builds the renderer, so it takes minutes: while it runs
the step sets `busy` (`StepProps.setBusy`) and the wizard disables Back/Next. The result is
`rom/soundtrack/` with `manifest.tsv` written last; `soundtrack_status` recognises a finished
render when the user comes back. Failure shows the last lines of output. The end-to-end test
is `#[ignore]`d (`SOR_TEST_FOLDER`, `SOR_TEST_ROM`; it works in a scratch clone, never in the
user's `rom/soundtrack`).

## Step 5: build

`Backend/src/compile.rs` runs `scripts/generate_cpp_and_build.py --release` through
`script::run` (a player wants the optimized build; `--release` also cleans the build folder, so
"Build again" is a full rebuild). The script does the platform work itself (Ninja and llvm-mingw
on Windows). Success means `sor[.exe]` exists in `StreetsOfRageRecompilation/build/` or, for a
multi-configuration generator (a clone made before the Ninja change builds with Visual Studio),
in its `Release`/`Debug`/… subfolder, the newest one winning; `game_status`
recognises an earlier build when the user comes back. Long scripts show their last lines and a
bar parsed from `[ 45%]` (Makefiles) or `[12/340]` (Ninja) lines (`components/Progress.tsx`).
The end-to-end test is `#[ignore]`d (`SOR_TEST_FOLDER`, `SOR_TEST_ROM`; scratch clone).

## "Ready" means built from this version of the project

`build/` and `rom/soundtrack/` are gitignored, so updating the project (step 2) leaves the old output
behind. `Backend/src/stamp.rs` writes `.builder-version` next to the output after a successful run and
`game_status` / `soundtrack_status` compare it with git's current version, returning `outdated: true`
when it differs or is missing (so builds made before the stamps existed are rebuilt once). The game's
version is the project's `HEAD` (it names every submodule); the soundtrack's is the object ids of
`scripts/render_soundtrack.py` and `StreetsOfRageRecompilation/tools/soundtrack`, so an update that does
not touch the renderer keeps the render (a choice of mine, not a user decision: widen it if the
renders turn out to depend on more). Without git or a repository the output is accepted. The steps
treat an outdated output as not done and say so.

## Step 6: the shortcut

`Backend/src/shortcut.rs` holds what is common, and `shortcut/windows.rs`, `macos.rs` and `linux.rs` one file per system (user request). It makes two entries (user request, 2026-10-31; icon `punch-icon.png`):
**StreetsOfRageRecompilation** starts the game, **StreetsOfRageRecompilation Launcher** opens the
`play.py` window (not `--last`). The step needs the ROM, soundtrack and build, and says which step to finish.
A **Streets of Rage** shortcut made by an older Builder is left where it is, and still works.

- **Windows**: two `.lnk` on the desktop (PowerShell `WScript.Shell`), pointing into the project: `sor.exe` with
  `--rom`, `--soundtrack` and `--ai-path`, and `pyw -3 play.py`, so no console window.
- **Linux** (user: like Windows, no copy): two `.desktop` files on the desktop, pointing into the project
  (`Exec` quoted, `Path` the project, `gio` trusted flag).
- **macOS**: a `StreetsOfRageProject` folder with two bundles, in `/Applications` or `~/Desktop` (a radio button
  in the step, user decision). The game's bundle is self-contained (about 330 MB, `APFS` clones it), including a copy of the
  ROM (user decision), and is made aside (`StreetsOfRageRecompilation.staging`), so a failure leaves the old one. That name must not start with a dot: under `.StreetsOfRageRecompilation.staging`, on a desktop synced with iCloud, the bundle came out with the `hidden` flag on everything and only the Launcher showed in Finder (user report, 2026-10-31, in the Builder 0.3.0; a short test did not reproduce the flag, and the iCloud case of the fix was not run):
  - `Contents/MacOS`: `launcher` (the `sh` script Finder starts, which passes the three options) and `sor`.
  - `Contents/Frameworks`: every non-system library `sor` loads, walked with `otool` (MegaDriveEnvironment, SDL3 from
    Homebrew, SDL3_mixer, yaml-cpp, libpng, zlib, libpython). `install_name_tool` makes them `@rpath/...`, removes the
    build tree's rpaths and leaves `@executable_path/../Frameworks`; `codesign --sign -` then re-signs each, which
    Apple Silicon requires. The bundle itself is not signed, and so can write `__pycache__`.
  - `Contents/Resources`: the checkout's layout, so the scripts work unchanged: `scripts`, `autoplay`,
    `MegaDriveEnvironment/python/src`, `StreetsOfRageRecompilation/rom` (ROM, soundtrack) and `python/`, which
    is where SoRPython looks, since `SDL_GetBasePath` is `Resources` in a bundle. `StreetsOfRageRecompilation/build/sor`,
    where `run.py` looks, is a script that `exec`s `Contents/MacOS/sor`, not a symlink: through a link `sor`
    does not find `python/` (`[ai] cannot start Python`).
  - The Launcher's bundle holds only a script that `exec`s the Tk-capable Python (absolute path, since a Finder launch has no
    Homebrew on `PATH`) on the other bundle's `play.py`, by relative path. Without sources `play.py` keeps its settings in
    `~/.config/StreetsOfRageProject/`, so they survive the bundle being made again, and disables **Build first**.
  - A project update does not reach the bundle until the step is run again.

The icons are `include_bytes!`ed from `Backend/icons`, so the shortcuts never depend on files in the
project; Windows and Linux copy theirs to the app's local data folder. `punch-icon.png` is the
source of those icons: regenerate with `npm run tauri -- icon ../punch-icon.png -o icons` from
`Frontend/`, then delete the `android/` and `ios/` folders it makes.

Tested on macOS by the `#[ignore]`d `creates_the_real_shortcut` and by running the bundles from a scratch folder: `open` on both,
`launcher`, and `run.py` through `build/sor`, with the AI on P2, the soundtrack playing (`SDL_AUDIO_DRIVER=dummy`) and no library
loaded from outside the bundle. Not checked: the Dock icons, the step's window, a machine without Homebrew's SDL3.
Windows: only `cargo check --target x86_64-pc-windows-gnu`, and the shortcuts were not created. Linux: never run; `cargo test` on macOS compiles `linux.rs` and runs its tests, and the same the other way round.

On the last step Next becomes **Finish** (always enabled: the shortcut is optional); it calls the
`finish` command (`platform.rs`), which exits the app.

## Release builds (GitHub Actions)

`.github/workflows/builder.yml` (meta-repository root) builds the Builder on demand
(`workflow_dispatch` only, never on push; user decision) with a checkbox per platform: macOS
universal `.dmg`, Windows x64 and ARM64 as a **bare `.exe`** (no installer: `tauri build
--no-bundle`; the user does not want one), Linux x64 and ARM64 as an **AppImage** only. Nothing is
signed yet (macOS needs right-click > Open, Windows shows SmartScreen). Each platform uploads
one artifact, `StreetsOfRageBuilder-<platform>`, kept 14 days, holding the file already named for a release (`StreetsOfRageBuilder-<version>-<platform>.<ext>`, version from `tauri.conf.json`; Linux: `-<x86_64|aarch64>.AppImage`, because the AppImage catalogue (appimage.github.io, PR 11023) rejects "linux" in the name, plus a `.AppImage.zsync`). The AppImage embeds update information (`LDAI_UPDATE_INFORMATION`, `gh-releases-zsync` on the latest release) and the workflow regenerates the `.zsync` with `zsyncmake` after renaming; untested on a runner. Linux builds on Ubuntu 22.04 (older
glibc, so the AppImage runs on more systems). A `workflow_dispatch` workflow only appears in the
Actions tab once its file is on the default branch (`main`). Only the macOS command
(`tauri build --target aarch64-apple-darwin --bundles dmg`, with `CI=true`, 45 s) was run
locally; the Windows, Linux and universal runs are untested.

Publishing a release (version bump, Action run, release notes format, `gh release create`):
the `release-builder` skill, `.agents/skills/release-builder/SKILL.md`.
