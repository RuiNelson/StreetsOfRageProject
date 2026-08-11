# SoR Autoplay

Python app that attaches to a running
[`StreetsOfRageRecompilation`](../StreetsOfRageRecompilation/) host through the
[`MegaDriveEnvironment`](../MegaDriveEnvironment/) remote-access library
(`megadrive_remote`).


## Features

### Observer

- game mode, level, wave, timer
- P1/P2 character, health %, lives, specials, scores
- pause / police-special flags, floor holes
- **2D world map** (wide view + exact camera box):
  - letter-only markers with a square **outline** for state
  - players `1`/`2`, enemies `G/S/H/N/J`, bosses `B`, weapons/pickups
  - dashed camera rect = player walk band (32..288 × lane); off-camera actors still drawn
  - hunt counts when enemies target P1 / P2

### AI

- Token/Information/Verb pipeline per [`AI.md`](AI.md): observes the same
  snapshot the HUD already reads, infers danger/incoming-projectile tokens,
  proposes walk/attack/police verbs, ranks them by emergency, and issues
  the winner through a virtual gamepad (`hold_buttons`/`press_buttons` only —
  never writes RAM).
- Per-enemy-type/boss subclassing (`Garcia`/`Signal`/`HakuRo`/`Nora`/`Jack`;
  bosses split into a bespoke family — `Abadede`/`Mr. X` — and a later-boss
  family — `Souther`/`Antonio`/`Bongo`/`Onihime`-`Yasha` — matching which RAM
  fields the ROM actually populates for each).
- Combat: punching, jump-kicking, suplexing a grabbed enemy (front-hold →
  back-hold → suplex, all one physical control sequence), and throwing a
  held knife at range. No separate "combo"/"grab" moves — the ROM has no
  distinct input for either, so repeated `Punch` already produces both.
- Movement: approaching the nearest enemy, walking to a weapon upgrade on
  the floor, and advancing the stage when no enemy is on screen.
- Reacts to incoming projectiles (not just melee enemies) by predicting
  their flight path and picking a dodge direction in time.
- Threat-filtered `IncomingProjectile` inference only — no separate danger
  zone or sidestep machinery.
- Calls police automatically when health drops below a critical threshold
  (and never while holding an enemy or with zero specials).
- The HUD shows the AI's current winning `Verb` plus a pending-verb
  label of every candidate it was choosing between.
- Automatically stands down (releases input) when the game is paused or
  outside active gameplay (menus, character select, round-clear, continues).
- Original A/B/C control scheme only; `--altControls` is not yet supported.
  Two-player AI coordination and bespoke per-boss tactics are also future
  work (see `autoplay/CLAUDE.md`'s AI surface table).

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

## Run the observer

From the meta-repository (preferred):

```bash
./scripts/autoplay
./scripts/autoplay --host 127.0.0.1 --port 6969
./scripts/autoplay --once
./scripts/autoplay --poll-ms 33
```

Or directly:

```bash
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay
```

Options:

| Flag | Meaning |
| --- | --- |
| `--host 127.0.0.1` | Remote host |
| `--port 6969` | Remote TCP port |
| `--poll-ms 33` | Wall-clock remote poll period |
| `--hud-ms 33` | GUI paint period only |
| `--once` | Print one snapshot to stdout (no GUI) |
| `--agent-p1` | Start with the AI controlling P1 (off by default) |
| `--agent-p2` | Start with the AI controlling P2 (off by default) |

Sampling is wall-clock only (no VSync wait). Keys: **Esc** / **Q** quit.

The window starts maximized (title bar kept; not exclusive fullscreen). Layout:

1. **Top status row** — three equal columns: **State / P1 / P2**
2. **Map** — fills all remaining window space

## Tests

```bash
cd autoplay
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m unittest discover -s tests -q
```

## Layout

```text
autoplay/
  pyproject.toml
  README.md
  CLAUDE.md
  src/sor_autoplay/
    app.py              # CLI + poll loop
    hud.py              # maximized Tk: status + map
    state.py            # RAM → snapshot
    world_map.py        # camera + actors → map entities
    object_catalog.py   # type → symbol/color/family
    memory_map.py       # addresses / names
    hazards.py          # pause, police, floor holes
    bcd.py              # packed-BCD helpers
    phases.py           # ordinary/boss/player combat phase decode
    ai/                 # symbolic AI (Token/Information/Verb pipeline)
  tests/
```
