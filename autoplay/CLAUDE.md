# SoR Autoplay — agent notes

## Role

`autoplay/` is a Python project that attaches to a running
`StreetsOfRageRecompilation` (`sor`) process via
`MegaDriveEnvironment`'s `megadrive_remote` client.

Intended end state: an automatic play agent. **Current scope:** a read-only
maximized-window observer that mirrors mode, characters, health, lives, specials,
timer, level, scores, and a 2D world map (players / enemies / bosses / items).

## Ownership

- Project-owned directory in the StreetsOfRageProject workspace.
- Prefer keeping implementation here; do not fork the remote protocol.
- Consume `MegaDriveEnvironment/python` (`megadrive_remote`) as a library
  (`PYTHONPATH` or install). Do not copy wire-protocol code.

## Commands

```bash
# Host (meta-repo root)
./scripts/run StreetsOfRageRecompilation/rom/SOR.bin --debugUtils --port 6969

# Observer (meta-repo wrapper; defaults host 127.0.0.1 port 6969)
./scripts/autoplay
./scripts/autoplay --once
./scripts/autoplay --poll-ms 33

# Or direct module invoke
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay
PYTHONPATH=src python3.11 -m unittest discover -s tests -q
```

Use Python 3.11+ with Tk (`_tkinter`). System/Homebrew 3.13/3.14 builds on this
machine may lack Tk.

## Design constraints

- Read-only observation for now (no injected buttons unless explicitly requested).
- Prefer small multi-byte `read_memory` windows over many single-byte reads.
- **Snapshot cadence is wall-clock polling, not VSync waits.** Default
  `--poll-ms 33` (~2 frames at 60 Hz): `read_snapshot()` on the remote poll
  thread, then sleep the remainder of the period. Do not call `wait_vsync` for
  ordinary observation.
- HUD must stay visually small (corner card), even if the window is maximized.
  Prefer maximized normal window over exclusive fullscreen.
- Do not commit ROMs, captures, or build artifacts.
- Never leave a background `sor` process running after local experiments; use
  `timeout -k` when scripting launches.

## Key RAM (verified from analysis)

See `src/sor_autoplay/memory_map.py` and
`StreetsOfRageRecompilation/code-analysis/addresses.csv`.

- Health: binary word `0..0x50` at player object `+$32`
- Lives / specials: packed-BCD bytes at `$FFFF20+`
- Scores: packed-BCD longwords at `$FFFF08` / `$FFFF10` (mask dirty high bits)
- Timer: `$FFFB00` BCD-like word; wave seeds `$40`/`$50`/`$60`
- Character IDs: 0=Axel, 1=Adam, 2=Blaze
- `player_mode`: bit mask, not a 1/2 enum alone
- Map actors: P1/P2 at `$FFB800`/`$FFB880`; **66**×`$80` table at `$FFB900`
- Map plot (top-down visualization):  
  `map_x = world_x - cam_x`, `map_y = lane_y` (`+$10` / `+$14`)  
  Elevation `world_z` (`+$18`) is stored for agents but **not** used on the map.
- Sprite CRT formula (`lane/2 + z`) lives in `project_to_screen()` for later use.
- Playable lane from `clamp_players_to_gameplay_bounds`: Y ∈ `[$02,$70]`  
  (or `[$02,$A0]` on level index 6). Camera box height uses that max.
- Dormant off-screen enemy spawns (flags bit0 held) stay on the map; the
  **view** expands to include them while the **camera** rect stays the
  visible 320×lane band.
- apple = type `$4B`
- Pause: `$FFFA46 (pause_text_flag)` **nonzero** (written as 3, then often 1
  after `bclr #1` on the first paused frame)
- Police special: `$FFFA1A` nonzero (+ caller `$FFFA1C`)
- Floor holes: `$FFA000` collision-class map, class 0 = open/pit
  (query matches `sub_0000AD30`: x>>4, lane>>3, stride `$FFE02E`)
- Styles live in `object_catalog.py`; extraction in `world_map.py`

## Next milestones (not done)

- Agent policy / scripted input via `press_buttons` or lockstep `step_input`
- Stronger attract-vs-real-play discrimination if needed
- Optional transparent overlay instead of black fullscreen stage
