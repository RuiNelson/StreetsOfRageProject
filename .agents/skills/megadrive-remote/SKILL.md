---
name: megadrive-remote
description: Control, test, inspect, and automate a running MegaDriveEnvironment application through the typed megadrive_remote Python client. Use for remote joystick input, deterministic frame-based button presses, game restart, 24-bit bus memory reads/writes/waits, ROM patching, VDP framebuffer/VRAM/palette/SAT/tilemap inspection, HSync/VSync waits, gameplay smoke tests, entering Streets of Rage levels, or diagnosing application progression through TCP port 6969.
---

# Mega Drive Remote

Use the source client at `MegaDriveEnvironment/python/src/megadrive_remote` to
drive a running `MegaDriveEnvironment` application through its binary TCP
server. Work from the repository root unless a command says otherwise.

## Prepare

1. Read `MegaDriveEnvironment/python/README.md` for the public Python API.
2. Read `MegaDriveEnvironment/docs/remote-access-protocol.md` only when wire
   details or server behavior matter.
3. Build and start the target application with remote access enabled. The
   default is one client on `0.0.0.0:6969`; constructor port `0` disables it.
4. Prefer the checkout's current client without installing it:

```bash
PYTHONPATH=MegaDriveEnvironment/python/src python3 program.py
```

Use `scripts/probe.py` for a non-mutating connectivity/VDP smoke test. Add
`--restart` only when a cold game restart is intended.

```bash
python3 .agents/skills/megadrive-remote/scripts/probe.py \
  --wait-frames 3 --capture /tmp/megadrive-frame.ppm
```

## Write automation

Use a context manager and state-driven waits:

```python
from megadrive_remote import Buttons, MegaDriveClient

with MegaDriveClient("127.0.0.1", 6969) as md:
    md.ping()
    md.press_buttons(player1=Buttons.START, frames=1)
    state = md.wait_memory_changed(0xFFFF00, width=2, timeout_ms=5_000)
    md.wait_vsync(2, timeout_ms=2_000)
    md.read_framebuffer().save_ppm("/tmp/frame.ppm")
```

Follow these rules:

- Pass controller arguments by keyword: `press_buttons(player1=..., frames=...)`.
  The controller arguments are keyword-only. The constructor timeout keyword is
  `io_timeout`, not `timeout`.
- Express button durations in frames. `press_buttons()` begins at the next
  VSync, combines masks with OR, releases automatically, and then replies.
- Use memory state and `wait_memory_changed()` / `wait_memory_equals()` instead
  of long fixed sleeps. Values are big-endian and widths are 1, 2, or 4 bytes.
- Treat bus addresses as 24-bit. ROM writes patch only the loaded in-memory
  cartridge image. Save and restore original bytes when a test must be clean.
- `restart_game()` preserves the process, window, TCP connection, and complete
  patched ROM. It clears CPU/WRAM/VDP/Z80/sound/remote-controller state and
  returns after the replacement CPU invocation starts.
- Serialize requests. The server accepts one request at a time; do not try to
  satisfy a blocking request with a second command on the same connection.
- Always close the client. Explicitly call `release_buttons()` before cleanup
  if an automation may abort while working around protocol calls.

## Inspect VDP output

`read_framebuffer()` returns the final compositor buffer in native BGR order,
with each channel in `0..7`. Use `.pixel()`, `.rgb888()`, or `.save_ppm()`.

Capture timing matters: immediately after a game-state transition, the HUD may
exist before the level has populated every plane and sprite. Wait at least a
few VSyncs after reaching a stable state; use 60–180 frames when validating a
fully settled scene. Do not diagnose a plane/compositor bug from the first
frame of a transition.

Use:

- `read_vdp_state()` for one coherent raw state snapshot;
- `read_vram()`, `read_palettes()`, and `read_sat()` for focused inspection;
- `read_tilemap(TilemapPlane.A/B/WINDOW)` for decoded nametables;
- `wait_hsync_count()` or `wait_hsync_reach_line()` for raster-sensitive tests.

## Automate Streets of Rage

Develop new gameplay automations incrementally. Do not write an untested full
route in one pass:

1. Add one small input/state transition to a temporary Python program.
2. Run it from a known reset state.
3. Verify the result through both relevant RAM values and VDP output. Wait for
   the scene to settle before judging a framebuffer.
4. Reset, add only the next step, and repeat from the beginning.

Keep the final natural demonstration separate from this development loop. Once
the route is proven, launch a fresh process and run the consolidated script
without intermediate resets or memory writes so the user can watch the genuine
controller path.

Use these confirmed work-RAM values:

| Address | Width | Meaning |
|---:|---:|---|
| `0xFFFF00` | 2 | Game state |
| `0xFFFF02` | 2 | Level (`0` is level 1) |
| `0xFFFF04` | 2 | Wave |
| `0xFFF904` | 2 | Character-select substate |
| `0xFFFB0E` | 2 | Main-menu substate (`0x02` is interactive) |
| `0xFFB840` | 2 | Main-menu cursor (`0` is 1 PLAYER) |
| `0xFFB858` | 2 | P1 character-selection slot |

Relevant game states are `0x06` story, `0x0A` title, `0x12` player-mode menu,
`0x22` character select, `0x2A` level intro, and `0x16` active gameplay. These
steps assume the application is already running; `restart_game()` returns at
cold boot, before the logo/story/title sequence completes.

When the user asks to watch a natural boot or suspects state skipping, launch
a fresh application process and do not call `restart_game()` or write memory.
Use read-only state checks only for timing, keep the same process throughout,
and leave its window open when requested. Run the bundled natural-input path:

```bash
PYTHONPATH=MegaDriveEnvironment/python/src \
  python3 .agents/skills/megadrive-remote/scripts/enter_first_level.py \
  --character axel
```

To exercise the real input path:

1. Send no input during the SEGA logo. Wait for story state `0x06`, leave it
   visible for about 75 VSyncs, then tap Start for one frame.
2. Wait for title state `0x0A`, leave the three-character title visible for
   about 75 VSyncs, then tap Start for one frame.
3. Wait for state `0x12` and main-menu substate `0x02`. Read the menu cursor as
   a 2-byte value and verify it is `0` (1 PLAYER), then confirm with Start.
4. Wait for state `0x22` and character-select substate `0x04`. Read the P1 slot
   at `0xFFB858` as a 2-byte value: slot `0` is Adam, `1` Axel, and `2` Blaze.
   Move one slot at a time and verify each change before confirming with A.
5. Let level-intro state `0x2A` progress to active gameplay state `0x16`.
6. Confirm level is `0`, wait about 180 further VSyncs for the entrance fall and
   round setup, then re-check state and level. Do not invent object-field
   offsets to detect landing unless they have been independently verified.

If a one-frame tap is ignored, use a bounded retry: re-read the state, wait a
few VSyncs, and tap again only while still in the same expected state. Never
use an unbounded input loop. Declare first-level success only at state `0x16`
with level `0`; `0x14` is its transient initialization state.

For a direct level-1 diagnostic warp, write level and wave to zero, then write
game state `0x28`. This tests memory control, not the menu/controller path.

## Verify and report

Report observable evidence rather than only “connected”:

- state transitions and final state;
- framebuffer dimensions and a digest or saved capture;
- counts/dimensions from palettes, SAT, and tilemap when inspected;
- whether reset cleared WRAM and preserved a temporary ROM patch;
- timeouts or server errors with the operation that produced them.

Keep ad-hoc programs in a temporary directory and remove them after use. Keep
captures only when they help the user verify the result.
