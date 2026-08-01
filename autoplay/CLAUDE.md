# SoR Autoplay — agent notes

## Role

`autoplay/` is a Python project that attaches to a running
`StreetsOfRageRecompilation` (`sor`) process via
`MegaDriveEnvironment`'s `megadrive_remote` client.

**Current scope:** maximized-window observer (mode, characters, health, lives,
specials, timer, level, scores, 2D world map) **plus** optional scripted agents
that inject standard-control input through `press_buttons`.

## Ownership

- Project-owned directory in the StreetsOfRageProject workspace.
- Prefer keeping implementation here; do not fork the remote protocol.
- Consume `MegaDriveEnvironment/python` (`megadrive_remote`) as a library
  (`PYTHONPATH` or install). Do not copy wire-protocol code.

## Commands

```bash
# Host (meta-repo root) — do NOT use --altControls with the agents yet
./scripts/run StreetsOfRageRecompilation/rom/SOR.bin --debugUtils --port 6969

# Observer + AI (meta-repo wrapper; defaults host 127.0.0.1 port 6969)
./scripts/autoplay
./scripts/autoplay --agent-p1
./scripts/autoplay --agent-p1 --agent-p2
./scripts/autoplay --once
./scripts/autoplay --poll-ms 33

# Or direct module invoke
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay
PYTHONPATH=src python3.11 -m unittest discover -s tests -q
```

Use Python 3.11+ with Tk (`_tkinter`). System/Homebrew 3.13/3.14 builds on this
machine may lack Tk.

## Agent design (standard controls only)

Specs live in `AgentSpecs.md`. Implementation under `src/sor_autoplay/agent/`.

**Controls assumption:** OPTIONS scheme 0 and **no** host `--altControls`.

| Physical | Role | `Buttons` |
|---|---|---|
| B | Attack / pickup | `Buttons.B` |
| C | Jump | `Buttons.C` |
| A | Police special | `Buttons.A` |
| D-pad | Move | UP/DOWN/LEFT/RIGHT |

`--altControls` remaps A/X/Y and splits pickup from attack; agents do not support
that layout yet.

### Behaviour (priority)

1. Steady (no input) while paused or police special is active
2. Mr. X offer: always select **NO** (refuse) then confirm
3. Police special when pressure score ≥ threshold and specials remain (not round 8)
4. **Grab / weapon hold tree** (`agent/grabs.py`): knee → throw; bat/pipe swing;
   knife/bottle/pepper throw at mid-range
5. 2P mid-air assist when both agents and partner is airborne nearby
6. Pick up weapons freely; health/life/special only if co-op fairness allows
7. Engage threats with **family-specific counters** (`agent/enemies.py`):
   Signal face/rear, Haku jump intercept, Nora no-rush feint, Jack projectile
   lane-dodge, Abadede/Bongo sidestep charges, Souther grounded only, Antonio
   outside boomerang band, twins mobile, Mr. X pressure
8. Grab setup (walk-in without attack) on grab-friendly foes
9. Avoid floor holes (stage 4) and elevator edges (stage 7)
10. Progress right (stage 8: left) when the screen is clear

Map entities now carry `action_state`, `held_type`, `held_ptr`, `outgoing_damage`,
`combo_state` for the agent (plot still ignores them).

### UI

- Per-player **AI ON/OFF** buttons in the P1/P2 columns
- Keys **1** / **2** toggle P1 / P2 agents
- CLI: `--agent-p1`, `--agent-p2`, `--agent-hold-frames N`

Input is applied on the same remote poll thread as RAM reads (one client
connection). When an agent is active, `press_buttons(..., frames=hold)` paces
the loop; when off, wall-clock `--poll-ms` is used.

## Design constraints

- Prefer small multi-byte `read_memory` windows over many single-byte reads.
- **Snapshot cadence is wall-clock polling, not VSync waits** (when agents off).
  Default `--poll-ms 33` (~2 frames at 60 Hz).
- HUD must stay visually clear (corner status + map). Prefer maximized normal
  window over exclusive fullscreen.
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
- Mr. X offer: `$FFDE00` flag, `$FFDE04` state; player object `+$59` bit3=side,
  bit4=choice UI active (initial refuse path wants bit3=1 = NO)
- Styles live in `object_catalog.py`; extraction in `world_map.py`
- Agent modules: `agent/policy.py`, `combat.py`, `pressure.py`, `stage.py`,
  `coop.py`, `characters.py`, `controls.py`

## Next milestones

- Optional `--altControls` mapping (deferred)
- Frame-tighter boss phase reads from object `+$30`/`+$67` tactical substates
- Attract-vs-real-play discrimination if needed
- Optional transparent overlay instead of black stage
