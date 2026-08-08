# SoR Autoplay — agent notes

## Role

`autoplay/` is a Python project that attaches to a running
`StreetsOfRageRecompilation` (`sor`) process via
`MegaDriveEnvironment`'s `megadrive_remote` client.

**Current scope:** maximized-window **observer** only (mode, characters, health,
lives, specials, timer, level, scores, 2D world map, floor holes, police-special
flags). It does **not** inject controller input or run a scripted / symbolic AI.

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
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m unittest discover -s tests -q
```

Use Python 3.11+ with Tk (`_tkinter`). System/Homebrew 3.13/3.14 builds on this
machine may lack Tk.

## Observer surface

| Piece | Role |
| --- | --- |
| `app.py` | CLI (`--host`, `--port`, `--poll-ms`, `--hud-ms`, `--once`), poll loop |
| `state.py` | Work-RAM / remote reads → `GameSnapshot` |
| `world_map.py` | Camera + actors → map entities (incl. hunt targets) |
| `object_catalog.py` | Type → symbol / color / family |
| `memory_map.py` | Known addresses |
| `hazards.py` | Pause, police special active, floor holes |
| `phases.py` | Combat-phase decode for map outlines |
| `hud.py` | Maximized Tk: State / P1 / P2 + world map |
| `bcd.py` | Packed-BCD helpers |

### CLI (observer only)

- `--host` / `--port` — remote endpoint
- `--poll-ms` — wall-clock remote sample period (default 33 ms)
- `--hud-ms` — GUI paint period only
- `--once` — one snapshot to stdout, no GUI

There are **no** agent enable flags, hold-frame knobs, police-special suppress
flags, or evaluation entry points in this tree.

### HUD

- Keys: **Esc** / **Q** quit
- Columns: State · P1 · P2 (health, lives, specials, score, hunt count)
- Map outlines use `phases.py` combat-phase colours

## Snapshot cadence

- **Snapshot cadence is wall-clock polling**, not VSync waits.
- The poller reconnects with backoff on link failure and surfaces errors in the
  HUD / offline snapshot.

## Observation notes (keep these)

- Lives / specials: packed-BCD bytes at `$FFFF20+`
- Pause / police special: `$FFFA1A` nonzero (+ caller `$FFFA1C`)
- Elevation `world_z` (`+$18`) is stored on map entities but **not** used on the
  map plot
- Dormant ordinary enemies and police-special sweep controllers are filtered by
  `object_catalog` / map build rules as documented in those modules
- Combat phase decode lives in `phases.py` for HUD outline colours

## Validation

```bash
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m unittest discover -s tests -q
```

Unit tests cover snapshot decoding, BCD, hazards, phases, world map, and
`ObserverApp.stop()` client handoff. There is no live host requirement for the
unit suite.

## What was removed

The previous symbolic / scripted AI stack is gone from this branch:

- `src/sor_autoplay/agent/` (policy, inference, expert, skills, combat, …)
- `evaluation.py`, `scenarios.py`, and the `sor-autoplay-eval` entry point
- CLI: `--agent-p1`, `--agent-p2`, `--agent-hold-frames`, and evaluator flags
  such as `--no-police-special`
- HUD AI toggles (keys 1/2) and agent decision notes
- Agent-focused unit tests

Observation (RAM → snapshot → HUD/map) is intentionally unchanged in capability.
