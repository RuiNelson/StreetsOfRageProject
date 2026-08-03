"""Pause, police-special, floor-hole, and collision-barrier detection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from . import memory_map as mm
from .world_map import LANE_Y_MAX_DEFAULT, lane_y_max_for_level

# Live round-4 sampling: class 0 = pit/open, class 1 = solid walkable floor.
# Live round-6 factory sampling: class 2 = solid wall / machine housing that
# blocks horizontal walk at standing height (RIGHT into a class-2 column
# advances 0 px). Classes ≥ 2 are treated as navigation barriers.
WALKABLE_COLLISION_CLASS = 1
BARRIER_COLLISION_MIN_CLASS = 2


# Terrain solid kinds for routing. Only real pits use "standing inside → escape"
# rewrites. Barriers and presses are AABB over-estimates of walls/crushers:
# the player can legally stand inside those AABBs (free cells inside the box),
# so treating them as pits caused stage-6 UP/DOWN/LEFT/RIGHT shake.
HOLE_KIND_PIT = "pit"
HOLE_KIND_BARRIER = "barrier"
HOLE_KIND_PRESS = "press"


@dataclass(frozen=True, slots=True)
class FloorHole:
    """One connected terrain region as an axis-aligned bounding box.

    Used for pits (class 0), solid barriers (class ≥ 2), and press bodies.
    Adjacent matching cells form one component; we store the bounding box so
    the map and navigator do not thrash on a tile staircase.

    ``kind``:
      - ``pit``: open void — emergency escape when standing inside is correct.
      - ``barrier`` / ``press``: path blockers only — never "escape hole" thrash.
    """

    world_x: int
    lane_y: int
    width: int
    height: int
    kind: str = HOLE_KIND_PIT

    @property
    def world_x_end(self) -> int:
        return self.world_x + self.width

    @property
    def lane_y_end(self) -> int:
        return self.lane_y + self.height

    @property
    def is_pit(self) -> bool:
        return self.kind == HOLE_KIND_PIT


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
    kind: str = HOLE_KIND_PIT,
) -> tuple[FloorHole, ...]:
    """Connected AABBs for cells where ``match(class)`` is true."""

    if stride <= 0 or not cmap:
        return ()

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
                    kind=kind,
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
        kind=HOLE_KIND_PIT,
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

    Tagged ``kind=barrier`` so standing inside the (over-estimated) AABB never
    triggers pit-style emergency escape thrash.
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
        kind=HOLE_KIND_BARRIER,
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
