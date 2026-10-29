# Streets of Rage Builder

Tauri 2 (Rust) + Next.js (static export) desktop wizard that builds this project from a ROM.
Windows (winget), macOS (Homebrew) and Debian-based Linux (apt).

Steps: 1 Install Tools · 2 Download Source · 3 Copy ROM (CRC check) · 4 Pre-render Soundtrack · 5 Build Executable · 6 Create Shortcut (`scripts/play.py`).

```bash
cd StreetsOfRageBuilder/Frontend
npm install
npm run tauri dev      # window + hot reload
npm run tauri build    # installers
```

Requires Node 20.9+, Rust, and Tauri's [platform prerequisites](https://tauri.app/start/prerequisites/).

## Layout

- `Frontend/` Next.js app (`output: "export"` → `Frontend/out`); `src/lib/steps.ts` defines the wizard steps.
- `Backend/` Tauri/Rust app (`tauri.conf.json`, `src/*.rs`, commands registered in `lib.rs`); cargo output goes to `Intermediaries/cargo`.
- `Intermediaries/`, `Products/` ignored build output.
