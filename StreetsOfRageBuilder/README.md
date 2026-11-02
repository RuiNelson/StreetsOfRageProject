# Streets of Rage Builder

Tauri 2 (Rust) + Next.js (static export) desktop wizard that builds this project from a ROM.
Windows (winget), macOS (Homebrew) and Debian-based Linux (apt).

Steps: 1 Choose Target (this computer, or PlayStation 5) · 2 Install Tools · 3 Download Source · 4 Copy ROM (CRC check) · 5 Pre-render Soundtrack · 6 Build Executable · 7 Create Shortcut (the game, and a Launcher with `scripts/play.py`).

For the **PlayStation 5** the build runs in a container, so only git and a container engine (Docker, OrbStack or Podman) are needed; steps 7 and 8 then make the ZIP files or send the files to the console over FTP, and offer to clean up (the container, the generated C++ and the built title; the ROM and the soundtrack stay).

```bash
cd StreetsOfRageBuilder/Frontend
npm install
npm run tauri dev      # window + hot reload
npm run tauri build    # installers
```

Requires Node 20.9+, Rust, and Tauri's [platform prerequisites](https://tauri.app/start/prerequisites/).

Release builds for every platform come from the **Builder** GitHub Action (Actions > Builder > Run workflow, pick the platforms): a macOS universal `.dmg`, Windows x64 and ARM64 `.exe`, Linux x64 and ARM64 AppImage, as downloadable artifacts. They are not signed yet.

## Layout

- `Frontend/` Next.js app (`output: "export"` → `Frontend/out`); `src/lib/steps.ts` defines the wizard steps.
- `Backend/` Tauri/Rust app (`tauri.conf.json`, `src/*.rs`, commands registered in `lib.rs`); cargo output goes to `Intermediaries/cargo`.
- `Intermediaries/`, `Products/` ignored build output.
