# Agent guide

Tauri 2 + Next.js static-export wizard that builds Streets of Rage from a ROM
(see `README.md`). Tracked directly in the meta-repository (not a submodule).
The frontend (`Frontend/`) must stay statically exportable: no runtime server,
no API routes. All system work (installing dependencies, git clone, CRC check,
running the project's scripts) belongs in Rust commands under `Backend/src/`,
called through `Frontend/src/lib/tauri.ts`. Steps and order: `Frontend/src/lib/steps.ts`.
Run npm scripts from `Frontend/` (`npm run tauri dev` does `cd ../Backend`).
Validate with `npm run lint`, `npm run build` (Frontend) and `cargo check` (Backend).

## Step 1: dependencies

`Backend/src/dependencies.rs` holds one `Spec` table per platform (check + install
recipe: winget id, brew formulas or apt packages). `system.rs` resolves programs on
a refreshed search path (Homebrew dirs on macOS, registry PATH on Windows) so a GUI
launch and a just-finished install are both seen. Installs open the system terminal (Terminal.app, cmd, or the first terminal emulator
found on Linux) with a generated script, so the user sees the installers' own output and
prompts; the app does not wait, and re-checks when its window regains focus or on Re-check. Keep the tables in step with the
project README prerequisites. Only the macOS code path was compiled and run so
far; the Windows and Linux tables are untested on those systems.

## Step 2: download the project

`Backend/src/project.rs` puts the project in the exact folder the user chooses (user
decision, so the same folder is chosen again to update it); branch `main`; a player, not a
developer, so `git clone --depth 1 --recurse-submodules --shallow-submodules`, one commit
of history everywhere. A folder that is a copy (a `.git` whose origin names
StreetsOfRageProject) is updated: `fetch --depth 1`, `checkout --force -B main FETCH_HEAD`
and a submodule update, replacing local changes (ROM and soundtrack are gitignored, so they
survive). A missing or empty folder is cloned into; anything else is refused. git's
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
(`dependencies::python_candidates`), streaming stdout and stderr line by line to the UI
(`system::read_lines`). The first run builds the renderer, so it takes minutes: while it runs
the step sets `busy` (`StepProps.setBusy`) and the wizard disables Back/Next. The result is
`rom/soundtrack/` with `manifest.tsv` written last; `soundtrack_status` recognises a finished
render when the user comes back. Failure shows the last lines of output. The end-to-end test
is `#[ignore]`d (`SOR_TEST_FOLDER`, `SOR_TEST_ROM`; it works in a scratch clone, never in the
user's `rom/soundtrack`).
