---
name: control-megadrive-game
description: >
  Write and run small Python automation scripts that control and observe a live
  game built on MegaDriveEnvironment through the local megadrive_remote client.
  Use for scripted controller input, deterministic frame waits, memory reads or
  patches, framebuffer captures, VDP/VRAM/palette/sprite/tilemap inspection,
  runtime probes, gameplay reproduction, and automated experiments against
  StreetsOfRageRecompilation, MegaDriveEnvironmentSampleGame, or another
  MegaDriveEnvironment consumer. Triggers include "control the game", "observe
  the game", "remote client", "MegaDriveClient", "automation script",
  "scripted input", "read game memory", "capture frames", "controla o jogo",
  "observa a execucao", "script Python para o jogo", "remote cheats",
  "cheats remotos", and "ativar cheats remotamente".
---

# Control a MegaDriveEnvironment game

First: prefer static game assembly files analysis/game ROM file inspection/call stack analysis than running the game and controlling it remotely. Only use this skill if you have no other option.

Create focused Python scripts around the in-repository `megadrive_remote`
client. Prefer a short, explicit experiment over a generic automation framework.

Work from the `StreetsOfRageProject/` meta-repository. Read the root
`CLAUDE.md` and the target submodule's `CLAUDE.md` before changing project files.

## Workflow

1. Define the observation or intervention precisely: target game, initial
   state, inputs, number of frames or condition, and evidence to collect.
2. Read `MegaDriveEnvironment/python/README.md` and the relevant public client
   methods before writing code. For exact signatures and patterns, read
   [references/python-client.md](references/python-client.md).
3. Inspect the target game's current sources for launch commands and semantic
   addresses. Read [references/project-targets.md](references/project-targets.md)
   for the two sibling projects.
4. Put an ephemeral diagnostic script in a temporary directory. Add a script to
   a repository only when the user requests a reusable tool or test; then follow
   that submodule's conventions and keep generated captures out of Git.
5. Use `PYTHONPATH=MegaDriveEnvironment/python/src` from the meta-repository, or
   install the package from `MegaDriveEnvironment/python` when isolation is
   useful. Do not copy or reimplement the wire protocol.
6. Connect with a context manager, call `ping()`, establish a deterministic
   baseline with `restart_game()` when appropriate, perform the smallest input
   or mutation, and record structured observations.
7. Validate syntax with `python3 -m py_compile`. If a runnable game and required
   ROM/assets are present, execute the script against it and report the exact
   state reached and evidence captured. Otherwise report what was statically
   validated and the missing runtime prerequisite.

## Minimal pattern

```python
from megadrive_remote import Buttons, MegaDriveClient

with MegaDriveClient() as game:
    game.ping()
    game.restart_game()
    game.wait_vsync(2)
    before = game.read_framebuffer()
    game.press_buttons(player1=Buttons.START, frames=1)
    game.wait_vsync(2)
    after = game.read_framebuffer()
    print({
        "before": [before.width, before.height],
        "after": [after.width, after.height],
        "changed": before.bgr != after.bgr,
    })
```

Treat `press_buttons(..., frames=N)` as a blocking hold for exactly `N` complete
frame intervals starting at the next VSync. Use a fresh call for each input
phase; the server releases the remote buttons before replying.

## Host debug actions and cheats

`trigger_option_hotkey(key)` sends one printable ASCII key to the same
game-defined host callback as an Alt/Option keyboard chord. It is appropriate
for host debugging actions such as Streets of Rage cheats, not emulated joypad
input. The target must have debug utilities enabled; for Streets of Rage, start
`sor` with `--debugUtils` and a non-zero `--port`.

```python
with MegaDriveClient() as game:
    game.trigger_option_hotkey("l")  # Streets of Rage: add one P1 life
    game.trigger_option_hotkey("p")  # toggle P1 punch power
    game.trigger_option_hotkey("3")  # load level 3
```

The client normalizes ASCII letters to lowercase. Unsupported game keys are
acknowledged but have no effect. Keep these actions explicitly requested and
record which hotkey was invoked in the experiment output.

## Observation strategy

Choose the narrowest reliable signal:

| Goal | Preferred signal |
|---|---|
| Confirm a visual transition | Framebuffer before/after, saved as PPM if useful |
| Observe a known game state | Named RAM symbol and correct width |
| Track entities | Game-specific RAM objects when documented; otherwise decoded SAT |
| Inspect rendering setup | VDP state, palettes, tilemap, or a bounded VRAM range |
| Synchronize an action | VSync/scanline wait or a semantic memory condition |
| Reproduce controls | Explicit `Buttons` masks and frame counts |
| Exercise host cheats | `trigger_option_hotkey()` plus a game-state observation |

For Streets of Rage, resolve names and widths from
`code-analysis/addresses.csv`; do not guess offsets from generated C++. For the
sample game, most gameplay state is held in C++ members, so prefer framebuffer,
SAT, tilemap, and source-derived assertions instead of inventing RAM symbols.

## Safety and determinism

- The server listens on TCP port `6969` by default and serves one client at a
  time. Check for an existing listener/client before starting another game.
- Bind scripts to `127.0.0.1` unless the user explicitly needs a remote host.
- Remote controller state is ORed with physical input; avoid touching the
  keyboard/gamepad during deterministic runs.
- `trigger_option_hotkey()` is a host debugging facility, not an emulated
  controller event; it is ignored if debug utilities are disabled.
- One connection permits one in-flight request. Do not wait for a memory change
  that only a second request on the same client could cause; the running game
  must cause it, or use a separately coordinated producer.
- `wait_vsync()` synchronizes with running video; it does not pause or
  single-step the CPU.
- Bus reads and writes can trigger device side effects. Restrict writes to
  verified addresses, preserve 68000 big-endian widths, and print old/new values
  for patches. ROM writes affect only the in-memory cartridge image.
- `restart_game()` resets game/runtime state but preserves the TCP connection
  and in-memory ROM patches.
- Run game executables under `timeout -k`, keep their terminal/process handle,
  and confirm no game process remains after testing. Never leave a background
  SDL process behind.
- Save screenshots, logs, and probes in a temporary/output location; do not
  commit ROMs, build trees, or captures.

## Completion criteria

Deliver the script or reusable project change, the exact command to run it, and
the observed output. Distinguish among syntax validation, live connection
validation, and a gameplay path actually exercised. Do not claim a transition
was tested from a successful connection alone.
