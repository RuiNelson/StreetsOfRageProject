# `megadrive_remote` client reference

The authoritative sources are:

- `MegaDriveEnvironment/python/src/megadrive_remote/client.py`
- `MegaDriveEnvironment/python/src/megadrive_remote/models.py`
- `MegaDriveEnvironment/python/README.md`
- `MegaDriveEnvironment/docs/remote-access-protocol.md`

Re-read them when the local API changes. The package currently requires Python
3.9+ and has no runtime dependencies.

## Import and connect

From the meta-repository:

```bash
PYTHONPATH=MegaDriveEnvironment/python/src python3 /path/to/probe.py
```

```python
from megadrive_remote import (
    Buttons,
    MegaDriveClient,
    RemoteTimeoutError,
    TilemapPlane,
)

with MegaDriveClient("127.0.0.1", 6969) as game:
    game.ping()
```

Constructor options are `connect_timeout` (default 5 seconds) and `io_timeout`
(default 10 seconds or `None`). Use the context manager so disconnect always
releases the socket and any remote buttons.

## Control and synchronization

```python
game.restart_game(timeout_ms=5_000)
game.press_buttons(
    player1=Buttons.A | Buttons.RIGHT,
    player2=Buttons.NONE,
    frames=3,
)
game.release_buttons()  # emergency/explicit release; normal press releases too
game.wait_vsync(2)
game.wait_hsync_count(10, timeout_ms=1_000)
game.wait_hsync_reach_line(120, timeout_ms=1_000)
```

Buttons are `UP`, `DOWN`, `LEFT`, `RIGHT`, `A`, `B`, `C`, `START`, and `NONE`.
Combine masks with `|`.

`press_buttons` waits for the next VSync, holds the mask for the requested full
frame intervals, releases it, and then returns. Its default timeout scales with
the frame count.

## Memory

```python
raw = game.read_memory(0xFFFF00, 16)
game.write_memory(0xFF0000, b"\x01\x02")

state = game.read_value(0xFFFF00, width=2)
game.write_value(0xFFFF20, 0x07, width=1)

changed = game.wait_memory_changed(
    0xFFFF00, width=2, timeout_ms=5_000
)
matched = game.wait_memory_equals(
    0xFFFF00,
    0x0012,
    width=2,
    mask=0xFFFF,
    timeout_ms=5_000,
)
```

Widths are 1, 2, or 4 bytes; multi-byte values use 68000 big-endian order and
wait addresses must be naturally aligned. `wait_memory_changed` captures the
initial value when the command begins. Catch `RemoteTimeoutError` when a timeout
is an expected result of the experiment.

## Video and VDP

```python
frame = game.read_framebuffer()
print(frame.width, frame.height, frame.pitch, frame.pixel(10, 20))
frame.save_ppm("frame.ppm")

vdp = game.read_vdp_state()
vram_slice = game.read_vram(offset=0xC000, length=128)
palettes = game.read_palettes()       # 64 PaletteEntry values
sprites = game.read_sat()             # 80 decoded Sprite values
plane_a = game.read_tilemap(TilemapPlane.A)
entry = plane_a.at(4, 3)
```

`Framebuffer.pixel()` and `PaletteEntry.rgb` return native 3-bit RGB channels
in `0..7`. `Framebuffer.rgb888()` expands them to packed 8-bit RGB.

Useful decoded sprite fields include `x`, `y`, dimensions, link, base tile,
palette, priority, flips, raw tile word, and VRAM address. Tilemap entries expose
the tile index, palette, priority, flips, and VRAM address.

## Compact evidence output

Prefer deterministic JSON or a small dictionary over prose-only logs:

```python
import json

print(json.dumps({
    "game_state": f"0x{state:04X}",
    "frame_size": [frame.width, frame.height],
    "visible_sprites": sum(sprite.x != 0 or sprite.y != 0 for sprite in sprites),
}, sort_keys=True))
```

For repeated observations, include an explicit frame index and only the fields
needed to answer the question. Avoid dumping all 64 KiB of VRAM or the entire
framebuffer to stdout.
