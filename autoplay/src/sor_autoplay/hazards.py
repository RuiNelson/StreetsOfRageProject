"""Pause, police-special, floor-hole, and collision-barrier detection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .world_map import LANE_Y_MAX_DEFAULT, lane_y_max_for_level

# Live round-4 sampling: class 0 = pit/open, class 1 = solid walkable floor.
# Live round-6 factory sampling: class 2 = solid wall / machine housing that
# blocks horizontal walk at standing height (RIGHT into a class-2 column
# advances 0 px). Classes ≥ 2 are treated as navigation barriers.
WALKABLE_COLLISION_CLASS = 1
BARRIER_COLLISION_MIN_CLASS = 2


@dataclass(frozen=True, slots=True)
class FloorHole:
    """One connected terrain region as an axis-aligned bounding box.

    Used for pits (class 0) and for solid barriers (class ≥ 2). Adjacent matching
    cells form one component; we store the bounding box so the map and navigator
    do not thrash on a tile staircase.
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

    ``stride`` is the row pitch **and** the map's own width in columns, so a
    level is exactly ``stride * 16`` px wide. A column past that is off the
    map and must read as 0 -- ``row * stride + col`` would otherwise land in
    the *next lane row*'s bytes and report that row's terrain here. The
    scanners above routinely ask: ``holes_for_level``/``barriers_for_level``
    sweep ``camera_x - 512 .. camera_x + 832``, which runs past the blockmap
    near the end of every stage, and class 0 is the pit class -- so the wrap
    invented a pit (or a class-2 barrier) out of an adjacent lane's data,
    which reaches the AI as a phantom ``Pit`` token and the HUD as a hole
    that is not there.
    """

    if stride <= 0 or not cmap:
        return 0
    if world_x < 0:
        world_x = 0
    if lane_y < 0:
        lane_y = 0
    col = world_x >> 4
    row = lane_y >> 3
    if col >= stride:
        return 0
    index = row * stride + col
    if index < 0 or index >= len(cmap):
        return 0
    raw = cmap[index]
    if (world_x & 0x0F) < 8:
        return (raw >> 4) & 0x0F
    return raw & 0x0F


def _find_class_regions(
    cmap: bytes,
    *,
    stride: int,
    lane_max: int,
    world_x_min: int,
    world_x_max: int,
    match,
    min_width: int = 16,
    min_height: int = 16,
) -> tuple[FloorHole, ...]:
    """Connected AABBs for cells where ``match(class)`` is true.

    Only cells that are actually **on the map** are considered. The callers'
    scan window is deliberately wider than the level (``holes_for_level``
    sweeps ``camera_x - 512 .. camera_x + 832``), and the map itself is
    exactly ``stride * 16`` px wide, so the window runs off the end near
    every stage's end. Off-map cells cannot be told apart from real terrain
    by their class alone -- ``collision_class_at`` reports 0 for them, which
    is *also* the pit class -- so the bound has to be applied here, or the
    entire off-map tail scans as one enormous hole.

    The same holds on the lane axis for rows the caller never read: the
    buffer is ``len(cmap) // stride`` rows tall, and a row past that is
    "not sampled", not "open floor".
    """

    if stride <= 0 or not cmap:
        return ()

    cell_w = 8
    cell_h = 8
    map_width = stride * 16
    map_rows = len(cmap) // stride
    cols = max(1, (world_x_max - world_x_min + cell_w - 1) // cell_w)
    rows = max(1, (lane_max + cell_h) // cell_h)
    grid = [[False] * cols for _ in range(rows)]

    for row in range(rows):
        lane = row * cell_h
        if lane > lane_max:
            break
        if lane >> 3 >= map_rows:
            break
        for col in range(cols):
            wx = world_x_min + col * cell_w
            if wx < 0 or wx >= map_width:
                continue
            klass = collision_class_at(cmap, stride=stride, world_x=wx, lane_y=lane)
            if match(klass):
                grid[row][col] = True

    visited = [[False] * cols for _ in range(rows)]
    regions: list[FloorHole] = []

    for row in range(rows):
        for col in range(cols):
            if not grid[row][col] or visited[row][col]:
                continue
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
            if width < min_width and height < min_height:
                continue
            regions.append(
                FloorHole(
                    world_x=world_x_min + min_c * cell_w,
                    lane_y=min_r * cell_h,
                    width=width,
                    height=height,
                )
            )

    regions.sort(key=lambda h: (h.world_x, h.lane_y))
    return tuple(regions)


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

    if world_x_max is None:
        world_x_max = stride * 16 if stride > 0 else 0
    return _find_class_regions(
        cmap,
        stride=stride,
        lane_max=lane_max,
        world_x_min=world_x_min,
        world_x_max=world_x_max,
        match=lambda klass: klass == hole_class,
    )


def find_collision_barriers(
    cmap: bytes,
    *,
    stride: int,
    lane_max: int = LANE_Y_MAX_DEFAULT,
    world_x_min: int = 0,
    world_x_max: int | None = None,
    min_class: int = BARRIER_COLLISION_MIN_CLASS,
) -> tuple[FloorHole, ...]:
    """Scan for solid wall / machine-housing cells (class ≥ ``min_class``).

    Round-6 factory presses sit as type-``$42`` crushers, but the walk path is
    blocked by collision-class **2** columns on the upper lanes. Class 1 remains
    walkable floor past the housing on the lower lanes. These AABBs feed the
    same hole-detour navigator so progress does not hold RIGHT into a wall.
    """

    if world_x_max is None:
        world_x_max = stride * 16 if stride > 0 else 0
    return _find_class_regions(
        cmap,
        stride=stride,
        lane_max=lane_max,
        world_x_min=world_x_min,
        world_x_max=world_x_max,
        match=lambda klass: klass >= min_class,
        # Keep modest walls (a thin pillar) — drop only tiny noise.
        min_width=16,
        min_height=8,
    )


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


def barriers_for_level(
    cmap: bytes,
    *,
    stride: int,
    level_index: int,
    camera_x: int,
    margin_x: int = 512,
) -> tuple[FloorHole, ...]:
    """Return solid collision barriers near the camera for navigation."""

    lane_max = lane_y_max_for_level(level_index)
    x0 = max(0, camera_x - margin_x)
    x1 = camera_x + 320 + margin_x
    return find_collision_barriers(
        cmap,
        stride=stride,
        lane_max=lane_max,
        world_x_min=x0,
        world_x_max=x1,
    )
