"""Pause, police-special, and floor-hole detection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from . import memory_map as mm
from .world_map import LANE_Y_MAX_DEFAULT, lane_y_max_for_level


@dataclass(frozen=True, slots=True)
class FloorHole:
    """One connected open-floor / pit region (axis-aligned bounding box).

    Built by scanning the collision-class map and merging adjacent class-0
    cells into a single rectangle per connected component so the map does not
    draw a staircase of tiny tiles.
    """

    world_x: int
    lane_y: int
    width: int
    height: int

    @property
    def world_x_end(self) -> int:
        return self.world_x + self.width

    @property
    def lane_y_end(self) -> int:
        return self.lane_y + self.height


def is_paused(pause_text_flag: int) -> bool:
    """True when the in-game pause screen is up.

    ``$FFFA46 (pause_text_flag)`` is written as 3 on pause and 0 on resume
    (``handle_pause_start_input``). While paused, ``game_mode_ingame`` does
    ``bclr #1, pause_text_flag`` every frame so the value becomes **1** after
    the first paused frame. The game itself tests with ``tst.b``.
    """

    return (pause_text_flag & 0xFF) != 0


def is_police_special_active(police_special_active: int) -> bool:
    """True while the global police-special sequence is running."""

    return (police_special_active & 0xFF) != 0


def collision_class_at(
    cmap: bytes,
    *,
    stride: int,
    world_x: int,
    lane_y: int,
) -> int:
    """Return the 4-bit collision class at world (X, lane), matching ``sub_0000AD30``.

    Indexing:
      col = world_x >> 4
      row = lane_y >> 3
      byte = cmap[row * stride + col]
      nibble = high if (world_x & 0xF) < 8 else low
    """

    if stride <= 0 or not cmap:
        return 0
    if world_x < 0:
        world_x = 0
    if lane_y < 0:
        lane_y = 0
    col = world_x >> 4
    row = lane_y >> 3
    index = row * stride + col
    if index < 0 or index >= len(cmap):
        return 0
    raw = cmap[index]
    if (world_x & 0x0F) < 8:
        return (raw >> 4) & 0x0F
    return raw & 0x0F


def find_floor_holes(
    cmap: bytes,
    *,
    stride: int,
    lane_max: int = LANE_Y_MAX_DEFAULT,
    world_x_min: int = 0,
    world_x_max: int | None = None,
    hole_class: int = 0,
) -> tuple[FloorHole, ...]:
    """Scan for open/hole cells and return one AABB per connected component.

    Live round-4 sampling: class ``0`` = pit/open, class ``1`` = solid floor.
    Cells are 8×8 (half of a 16px collision column × lane>>3). Adjacent hole
    cells (4-connected) form one hole; we store the bounding box only so the
    HUD draws a single clean rectangle per gap instead of a tile staircase.
    """

    if stride <= 0 or not cmap:
        return ()
    if world_x_max is None:
        world_x_max = stride * 16

    cell_w = 8
    cell_h = 8
    cols = max(1, (world_x_max - world_x_min + cell_w - 1) // cell_w)
    rows = max(1, (lane_max + cell_h) // cell_h)
    grid = [[False] * cols for _ in range(rows)]

    for row in range(rows):
        lane = row * cell_h
        if lane > lane_max:
            break
        for col in range(cols):
            wx = world_x_min + col * cell_w
            if collision_class_at(cmap, stride=stride, world_x=wx, lane_y=lane) == hole_class:
                grid[row][col] = True

    visited = [[False] * cols for _ in range(rows)]
    holes: list[FloorHole] = []

    for row in range(rows):
        for col in range(cols):
            if not grid[row][col] or visited[row][col]:
                continue
            # BFS connected component (4-neighbour).
            q: deque[tuple[int, int]] = deque([(row, col)])
            visited[row][col] = True
            min_r = max_r = row
            min_c = max_c = col
            while q:
                r, c = q.popleft()
                min_r = min(min_r, r)
                max_r = max(max_r, r)
                min_c = min(min_c, c)
                max_c = max(max_c, c)
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                        continue
                    if visited[nr][nc] or not grid[nr][nc]:
                        continue
                    visited[nr][nc] = True
                    q.append((nr, nc))

            width = (max_c - min_c + 1) * cell_w
            height = (max_r - min_r + 1) * cell_h
            # Drop single-cell noise (smaller than half a metatile column).
            if width < 16 and height < 16:
                continue
            holes.append(
                FloorHole(
                    world_x=world_x_min + min_c * cell_w,
                    lane_y=min_r * cell_h,
                    width=width,
                    height=height,
                )
            )

    # Stable left-to-right order for the HUD.
    holes.sort(key=lambda h: (h.world_x, h.lane_y))
    return tuple(holes)


def holes_for_level(
    cmap: bytes,
    *,
    stride: int,
    level_index: int,
    camera_x: int,
    margin_x: int = 512,
) -> tuple[FloorHole, ...]:
    """Return holes near the camera (and a bit ahead) for the current level."""

    lane_max = lane_y_max_for_level(level_index)
    x0 = max(0, camera_x - margin_x)
    x1 = camera_x + 320 + margin_x
    return find_floor_holes(
        cmap,
        stride=stride,
        lane_max=lane_max,
        world_x_min=x0,
        world_x_max=x1,
        hole_class=0,
    )
