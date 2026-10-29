# Agent guide

Tauri 2 + Next.js static-export wizard that builds Streets of Rage from a ROM
(see `README.md`). Tracked directly in the meta-repository (not a submodule).
The frontend (`Frontend/`) must stay statically exportable: no runtime server,
no API routes. All system work (installing dependencies, git clone, CRC check,
running the project's scripts) belongs in Rust commands under `Backend/src/`,
called through `Frontend/src/lib/tauri.ts`. Steps and order: `Frontend/src/lib/steps.ts`.
Run npm scripts from `Frontend/` (`npm run tauri dev` does `cd ../Backend`).
Validate with `npm run lint`, `npm run build` (Frontend) and `cargo check` (Backend).
