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
launch and a just-finished install are both seen. Installs are verified by
re-running the check, never by exit code. Keep the tables in step with the
project README prerequisites. Only the macOS code path was compiled and run so
far; the Windows and Linux tables are untested on those systems.
