# Project targets

## StreetsOfRageRecompilation

Build from its submodule root:

```bash
./build.sh
```

Run only with a kill grace period, using the local ROM:

```bash
timeout -k 3 60 ./build/sor \
  --runSor --silent --fast --rom rom/SOR.bin
```

Use a longer timeout than the experiment, retain the process/session handle,
and stop it after the Python script finishes. Confirm cleanup with:

```bash
pgrep -lf '[/]sor' || true
```

For a normal paced visual experiment, omit `--fast`. Fast mode is useful for
state bring-up but makes wall-clock timing unsuitable as evidence; synchronize
through VSync or memory instead.

Treat `code-analysis/addresses.csv` as the source of truth for semantic RAM
names, widths, and confidence. Useful current examples include:

| Address | Width | Symbol | Meaning |
|---:|---:|---|---|
| `0xFFFF00` | 2 | `game_state` | Main init/update state pair |
| `0xFFFF08` | 4 | `score_p1` | Player 1 score |
| `0xFFFF20` | 1 | `p1_lives` | Packed-BCD lives |
| `0xFFB832` | 2 | `p1_health` | Health, clamped to `0x00..0x50` |
| `0xFFB840` | 2 | `select_menu_cursor` | Main-menu cursor `0..2` |

These examples are navigation aids, not a substitute for checking the CSV.
Resolve additional fields with:

```bash
rg -n "game_state|p1_health|desired_term" \
  StreetsOfRageRecompilation/code-analysis/addresses.csv
```

Main `game_state` values currently documented in the CSV are even init states
and their `+2` update states: Sega `0x00/02`, story `0x04/06`, title `0x08/0A`,
high scores `0x0C/0E`, main menu `0x10/12`, in-game `0x14/16`, round clear
`0x18/1A`, bad ending `0x1C/1E`, character select `0x20/22`, good ending
`0x24/26`, and level intro `0x28/2A`.

When driving menus, wait for the semantic update state before pressing a
button. Prefer `wait_memory_equals` to guessed wall-clock sleeps.

## MegaDriveEnvironmentSampleGame

Build and run from its submodule root:

```bash
./build_pc.sh
timeout -k 3 60 ./run_pc.sh
```

Do not pass `--frames N` for an interactive remote experiment unless `N` is
large enough: the process exits when the frame limit is reached. The default
`MegaDriveEnvironment` constructor enables the server on port `6969`.

The sample's gameplay model (`SampleGame` and `GameSession`) is stored mainly
in C++ members rather than a documented work-RAM structure. Observe it through:

- framebuffer changes and focused pixel regions;
- decoded SAT positions and attributes for rendered entities;
- Plane A tilemap entries for the HUD and text;
- palettes and bounded VRAM slices;
- inputs with known frame counts, checked against the game source.

Read these files before asserting entity order, positions, or input semantics:

- `include/MegaDriveEnvironmentSampleGame/GameSession.hpp`
- `src/GameSession.cpp`
- `include/MegaDriveEnvironmentSampleGame/SampleGame.hpp`
- `src/SampleGame.cpp`
- `src/main-PC.cpp`

The game initially displays a consent banner. A or Start is edge-triggered for
session reset, and Start also toggles the selected screen on a rising edge.
Release between logical presses by using separate one-frame `press_buttons`
calls with intervening frame waits when the intended edge matters.

## Another MegaDriveEnvironment consumer

Confirm its subclass does not pass `0` as the fourth `MegaDriveEnvironment`
constructor argument. Port `6969` is the default. Derive launch arguments,
memory symbols, and state transitions from that consumer's sources rather than
assuming the Streets of Rage or sample-game layout.
