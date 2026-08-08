# SoR Autoplay — agent notes

## Role

`autoplay/` is a Python project that attaches to a running
`StreetsOfRageRecompilation` (`sor`) process via
`MegaDriveEnvironment`'s `megadrive_remote` client.

**Current scope:** maximized-window **observer** (mode, characters, health,
lives, specials, timer, level, scores, 2D world map, floor holes, police-special
flags), plus an opt-in **symbolic AI** (`ai/` — Phase A of the design in
`/AI.md`) that can control P1 and/or P2 through controller input only (never
RAM writes). The AI is off by default and enabled per player via
`--agent-p1`/`--agent-p2` or the HUD's click-to-toggle label. See `ai/`'s
module docstrings for the Token/Information/Decision pipeline; per-enemy-type
subclassing, danger-zone clustering, two-player coordination, and the
six-button `--altControls` scheme remain future work.

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
| `app.py` | CLI (`--host`, `--port`, `--poll-ms`, `--hud-ms`, `--once`, `--agent-p1`, `--agent-p2`), poll loop, AI dispatch |
| `state.py` | Work-RAM / remote reads → `GameSnapshot` |
| `world_map.py` | Camera + actors → map entities (incl. hunt targets) |
| `object_catalog.py` | Type → symbol / color / family |
| `memory_map.py` | Known addresses |
| `hazards.py` | Pause, police special active, floor holes |
| `phases.py` | Combat-phase decode for map outlines and AI danger checks |
| `hud.py` | Maximized Tk: State / P1 / P2 + world map + AI toggle labels |
| `bcd.py` | Packed-BCD helpers |
| `ai/` | Symbolic AI — see "AI surface" below |

### CLI

- `--host` / `--port` — remote endpoint
- `--poll-ms` — wall-clock remote sample period (default 33 ms)
- `--hud-ms` — GUI paint period only
- `--once` — one snapshot to stdout, no GUI
- `--agent-p1` / `--agent-p2` — start with the AI controlling that player
  (off by default; also toggleable at runtime from the HUD)

There are no hold-frame knobs, police-special suppress flags, or evaluation
entry points in this tree.

### HUD

- Keys: **Esc** / **Q** quit
- Columns: State · P1 · P2 (health, lives, specials, score, hunt count, AI
  toggle label)
- Map outlines use `phases.py` combat-phase colours
- Click a player's "AI: OFF/ON" label to toggle that player's AI at runtime

### AI surface (`ai/`, Phase A — see `/AI.md`)

| Piece | Role |
| --- | --- |
| `tokens.py` | `Token`/`Information`/`Decision` base classes, `Context`, `find`/`find_all` |
| `character.py`, `enemy.py`, `essential.py`, `hazard_tokens.py` | Information tokens (`Myself`/`Partner`, `Enemy`, `Stage`/`CameraRange`/`AnimationInProgress`, `Projectile`/`IncomingProjectile`/`DangerZone`) |
| `observe.py` | Direct observation from an already-fetched `GameSnapshot` (never re-polls RAM) |
| `inference.py` | `check_for_incoming_projectiles`, `check_for_danger_zone` |
| `walk_decisions.py`, `attack_decisions.py`, `police_decision.py` | `Decision` tokens (`WalkToNearEnemy`, `WalkToAdvanceStage`, `Sidestep`, `Punch`, `CallPolice`) |
| `decide.py` | `should_*` candidate generators |
| `priority.py` | `determine_priority_decision` — emergency ranking + priority tie-break + logged random fallback |
| `gamepad.py` | `VirtualGamepad`/`SharedGamepadState` — the only code allowed to call `hold_buttons`/`press_buttons`/`release_buttons`; never `write_memory`/`write_value` |
| `execute.py` | `execute_decision` dispatch to controller input |
| `loop.py` | `AgentLoop.tick` — gates on pause/non-gameplay/not-playable first, then runs the full pipeline |

Verified button mapping for the original (non-altControls) scheme (see
`execute.py`'s module docstring): **Attack/Punch is physical B**, **Police
special is physical A** — the reverse of the naive "A=attack" assumption.

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

Unit tests cover snapshot decoding, BCD, hazards, phases, world map,
`ObserverApp.stop()` client handoff, and the full `ai/` pipeline (tokens,
observation, inference, decisions, priority ranking, execution, the
pause/non-gameplay gate). There is no live host requirement for the unit
suite.

## History: the old agent stack, and the new one in `ai/`

An earlier, ad-hoc scripted AI stack (`src/sor_autoplay/agent/`, `evaluation.py`,
`scenarios.py`, the `sor-autoplay-eval` entry point, HUD key-1/2 toggles,
`--agent-hold-frames`/`--no-police-special` flags) was deliberately removed
from this branch because it predated and did not follow the Token/Information/
Decision architecture in `/AI.md`. Observation (RAM → snapshot → HUD/map) was
unchanged by that removal.

`ai/` (see "AI surface" above) is a **fresh implementation** against that
architecture, not a revival of the removed stack — the CLI flag names
(`--agent-p1`/`--agent-p2`) are reused because they're the obvious names, not
because any removed code came back. Do not look to the old stack (it no
longer exists) for how the new one should work; follow `/AI.md` and the
module docstrings under `ai/` instead.
