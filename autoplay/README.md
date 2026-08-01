# SoR Autoplay

Python app that attaches to a running
[`StreetsOfRageRecompilation`](../StreetsOfRageRecompilation/) host through the
[`MegaDriveEnvironment`](../MegaDriveEnvironment/) remote-access library
(`megadrive_remote`).

Long-term goal: an agent that plays *Streets of Rage* well automatically.

**Current milestone:** a compact maximized-window observer that keeps a clear
replica of the live campaign/HUD state:

- game mode
- character(s) (1P or 2P)
- life bar %
- lives
- police specials
- time left before timeout
- level (and wave)
- scores
- **2D world map** (camera band + lane depth):
  - players `1`/`2` — blue Axel, yellow Adam, red Blaze
  - enemies by family symbol (`G` Garcia, `S` Signal, `H` Haku-Ro, `N` Nora, `J` Jack) with per-type colours
  - bosses as `B` with distinct colours per boss family
  - weapons (`k`/`b`/`/`/`|`/`p`), pickups (`+`/`$`/`♥`/`★`), breakables (`#`/`□`)

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
| `--poll-ms 33` | Wall-clock remote poll period (default ~2 frames at 60 Hz) |
| `--hud-ms 33` | GUI paint period only (does not pace remote reads) |
| `--once` | Print one snapshot to stdout (no GUI) |

Sampling is **wall-clock**: the poller reads RAM on a fixed timer and does
**not** call `wait_vsync`. Default `33` ms is approximately two frames at 60 Hz.

Keys in the HUD: **Esc** or **Q** quit.

The window starts maximized (title bar kept; not exclusive fullscreen). Layout:

1. **Top status row** — three equal columns: **State / P1 / P2**
2. **Map** — fills all remaining window space and resizes with the window

## One-shot CLI check

```bash
PYTHONPATH=src:../MegaDriveEnvironment/python/src python3.11 -m sor_autoplay --once
```

## Tests

```bash
cd autoplay
PYTHONPATH=src python3.11 -m pytest -q
```

## Memory sources

Observer addresses come from:

- `StreetsOfRageRecompilation/code-analysis/addresses.csv`
- `StreetsOfRageRecompilation/ai-analysis/` (especially
  `player-health-lives-and-combat.md` and `story-mode-and-campaign-flow.md`)
- `StreetsOfRageRecompilation/output/sor.asm` for timer/score BCD behaviour

Important symbols:

| Symbol | Address | Notes |
| --- | --- | --- |
| `game_state` | `$FFFF00` | Global mode dispatcher |
| `level` | `$FFFF02` | 0-based campaign index |
| `wave` | `$FFFF04` | In-level phase |
| `score_p1` / `score_p2` | `$FFFF08` / `$FFFF10` | Packed-BCD longwords |
| `player_mode` | `$FFFF18` | Bit0=P1, bit1=P2 |
| `p1_lives` / `p1_special_attacks` | `$FFFF20` / `$FFFF21` | Packed-BCD bytes |
| `p2_lives` / `p2_special_attacks` | `$FFFF23` / `$FFFF24` | Packed-BCD bytes |
| `p1_character_id` / `p2_character_id` | `$FFFF1E` / `$FFFF1F` | 0 Axel, 1 Adam, 2 Blaze |
| `game_timer` | `$FFFB00` | Countdown seconds (BCD-like word) |
| `p1_object` / `p2_object` | `$FFB800` / `$FFB880` | Health at `+$32`, char at `+$50` |
| Full health | `$50` (80) | Binary, not BCD |

## Layout

```text
autoplay/
  pyproject.toml
  README.md
  CLAUDE.md
  src/sor_autoplay/
    app.py              # CLI + wall-clock poll loop
    hud.py              # maximized Tk window: status + 2D map
    state.py            # RAM → snapshot
    world_map.py        # camera + actors → map entities
    object_catalog.py   # type → symbol/color/family
    memory_map.py       # addresses / names
    bcd.py              # packed-BCD helpers
  tests/
```
