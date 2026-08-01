# SoR Autoplay

Python app that attaches to a running
[`StreetsOfRageRecompilation`](../StreetsOfRageRecompilation/) host through the
[`MegaDriveEnvironment`](../MegaDriveEnvironment/) remote-access library
(`megadrive_remote`).

**Current milestone:** live observer HUD **and** optional scripted agents that
play with **standard controls only** (no host `--altControls`).

Agent goals and rules: [`AgentSpecs.md`](AgentSpecs.md).

## Features

### Observer

- game mode, level, wave, timer
- P1/P2 character, health %, lives, specials, scores
- pause / police-special flags, floor holes
- **2D world map** (camera band + lane depth):
  - players `1`/`2` — blue Axel, yellow Adam, red Blaze
  - enemies by family (`G` Garcia, `S` Signal, `H` Haku-Ro, `N` Nora, `J` Jack)
  - bosses `B`, weapons, pickups, breakables

### Agents

Per-player toggle (HUD button or keys **1** / **2**):

- **Face-then-hit combat**: punch only when same lane (±12 Y), in strike range,
  and facing the foe (player action-state bit 0). Turn one tick if wrong-way.
- No air punches: match lane before closing X; no B while mid-attack animation;
  no RNG jump spam from out of range
- Phase-aware targeting: knockdown punish, charge sidestep, ignore dead/scripted,
  prefer hunters (`+$42` / boss target)
- Family-specific counters (Signal, Haku-Ro, Nora, Jack, all bosses, Mr. X)
- **Grab/throw trees**: always throw; weapon swing/throw facing the foe
- Character-tuned ranges (Axel / Adam / Blaze)
- Police special under pressure; pickups with co-op fairness
- Stage rules (holes / elevator / stage 8 left); Mr. X always **NO**

**Standard control mapping** (OPTIONS scheme 0):

| Physical | Role |
|---|---|
| **B** | Attack / pickup |
| **C** | Jump |
| **A** | Police special |
| D-pad | Move |

Do **not** launch the host with `--altControls` when using the agents.

## Requirements

- Python 3.11+ with Tk (macOS Homebrew: `python@3.11` includes `_tkinter`)
- A running `sor` binary with remote access enabled
- Sibling checkout of `MegaDriveEnvironment` (for `megadrive_remote`), or the
  package installed into the active environment

## Launch the game host

From the meta-repository, with a legal ROM at
`StreetsOfRageRecompilation/rom/SOR.bin`:

```bash
./scripts/run StreetsOfRageRecompilation/rom/SOR.bin --debugUtils --port 6969
```

`--debugUtils` enables the remote server. Default port is `6969`.

## Run the observer / agents

From the meta-repository (preferred):

```bash
./scripts/autoplay
./scripts/autoplay --agent-p1
./scripts/autoplay --agent-p1 --agent-p2
./scripts/autoplay --host 127.0.0.1 --port 6969
./scripts/autoplay --once
```

Or directly:

```bash
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay --agent-p1
```

Options:

| Flag | Meaning |
| --- | --- |
| `--host 127.0.0.1` | Remote host |
| `--port 6969` | Remote TCP port |
| `--poll-ms 33` | Wall-clock remote poll period when agents are off |
| `--hud-ms 33` | GUI paint period only |
| `--agent-p1` / `--agent-p2` | Start with that seat's AI enabled |
| `--agent-hold-frames 2` | Frames each AI mask is held via `press_buttons` |
| `--once` | Print one snapshot to stdout (no GUI) |

When an agent is on, the poller applies `press_buttons` for `--agent-hold-frames`
each decision (blocking ~N VSyncs). When off, sampling is wall-clock only.

Keys: **Esc** / **Q** quit · **1** / **2** toggle P1 / P2 AI.

The window starts maximized (title bar kept; not exclusive fullscreen). Layout:

1. **Top status row** — three equal columns: **State / P1 / P2** (AI buttons here)
2. **Map** — fills all remaining window space

## Tests

```bash
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m unittest discover -s tests -q
```

## Layout

```text
autoplay/
  AgentSpecs.md
  pyproject.toml
  README.md
  CLAUDE.md
  src/sor_autoplay/
    app.py              # CLI + poll loop + agent I/O
    hud.py              # maximized Tk: status + map + AI toggles
    state.py            # RAM → snapshot
    world_map.py        # camera + actors → map entities
    object_catalog.py   # type → symbol/color/family
    memory_map.py       # addresses / names
    hazards.py          # pause, police, floor holes
    bcd.py              # packed-BCD helpers
    phases.py           # ordinary/boss/player combat phase decode
    agent/
      controls.py       # standard button mapping
      policy.py         # decide_actions()
      combat.py         # phase-aware targeting / approach
      enemies.py        # family/boss counter plans
      grabs.py          # hold / knee / throw / weapon trees
      pressure.py       # police special score
      stage.py          # holes, elevator, stage 8, Mr. X
      coop.py           # item fairness + 2P assist
      characters.py     # Axel / Adam / Blaze profiles
  tests/
```
