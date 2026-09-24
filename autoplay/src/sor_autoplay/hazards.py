"""Pause, police-special, floor-hole, and collision-wall detection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .world_map import LANE_Y_MAX_DEFAULT, lane_y_max_for_level

# What a collision class *is* depends on the round. The class map ($FFA000)
# holds a nibble per 8x8 cell, and sub_00019BD8 points $FFFC34 at a byte
# table of floor kinds and $FFFC38 at a word table of surface heights for the
# round, both indexed by class. sub_0000AD30 answers "what floor is at this
# point" from them:
#
#     kind = kinds[class]  if probe_z >= surfaces[class]  else 0
#
# where z grows downward and a standing player's z *is* its floor's surface
# ($3E78 writes it). The floor probe under the feet ($3D34) jumps on the kind
# through a four-entry table: 0 is no floor -- the player falls ($3DDC) until
# sub_0000358C takes a life at z $1C0; 1 is floor; 2 is floor that carries
# the player +1 px an update ($3E4A) and 3 the same at -1 ($3E52), round 6's
# conveyor belts. The wall probe ($3C92) asks the same question 8 px ahead of
# the mover on its own lane, 8 px above its feet, and a floor standing that
# high undoes the step: that is a wall.
#
# Transcribed from $19C04, classes 0-5 as ((kinds), (surfaces)). The two
# tables overlap in ROM, so a class past the round's own few reads the other
# table's bytes -- a kind of 4 or more is past the jump table, and no map of
# that round uses the class.
_ROUNDS_1_TO_5 = ((0, 1, 16, 0, 0, 160), (4096, 160, 4, 10, 1, 258))
FLOOR_TABLES: dict[int, tuple[tuple[int, ...], tuple[int, ...]]] = {
    0: _ROUNDS_1_TO_5,
    1: _ROUNDS_1_TO_5,
    2: _ROUNDS_1_TO_5,
    3: _ROUNDS_1_TO_5,
    4: _ROUNDS_1_TO_5,
    # Round 6, the factory: class 2 is floor at z 0 -- 160 px of machine
    # housing -- and 3/4 are the belts. It has no hole at all.
    5: ((0, 1, 1, 2, 3, 0), (4096, 160, 0, 160, 160, 4)),
    # Round 7, the lift (state.py scans nothing there).
    6: ((0, 1, 1, 1, 16, 0), (4096, 136, 0, 96, 4, 6)),
    7: ((0, 1, 16, 0, 0, 168), (4096, 168, 112, 112, 16, 70)),
}

FLOOR_NONE = 0
FLOOR_SOLID = 1
FLOOR_CONVEYOR_RIGHT = 2
FLOOR_CONVEYOR_LEFT = 3
_FLOOR_KINDS = frozenset({FLOOR_NONE, FLOOR_SOLID, FLOOR_CONVEYOR_RIGHT, FLOOR_CONVEYOR_LEFT})

# The class a round's street is made of: its surface is where everyone stands.
BASE_FLOOR_CLASS = 1
# $3C92 probes 8 px above the feet.
WALL_PROBE_Z = 8

# One cell of the class map, on both axes: a nibble covers 8 px of X
# (``collision_class_at``) and a row 8 lanes.
CELL = 8


@dataclass(frozen=True, slots=True)
class FloorHole:
    """One region of terrain as an axis-aligned box.

    Used for holes (``find_floor_holes``: a connected region's bounding box,
    so the map and navigator do not thrash on a tile staircase) and for walls
    (``find_collision_barriers``: exact, one box per run of cells).
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


def _floor_table(level_index: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    return FLOOR_TABLES.get(level_index, _ROUNDS_1_TO_5)


def floor_kind(level_index: int, klass: int) -> int | None:
    """What floor ``klass`` is in this round, or ``None`` for a class no map of it uses."""

    kinds, _ = _floor_table(level_index)
    if not 0 <= klass < len(kinds) or kinds[klass] not in _FLOOR_KINDS:
        return None
    return kinds[klass]


def base_floor_z(level_index: int) -> int:
    """The street's own surface height (``BASE_FLOOR_CLASS``) for this round.

    A standing body's ``world_z`` (+$18) *is* its floor's surface once it has
    landed on it (``$3E78``, cited above); z grows downward, so a body
    reading meaningfully *more* than this has not reached the floor yet.
    Used by ``reach.enemy_still_emerging`` for an ordinary enemy scripted to
    rise from below the ground before it becomes reachable (round 5's
    HakuRo, ``ai-analysis/enemy-ai.md``'s "HakuRo: rising from below deck") --
    the same reference ``is_wall_class`` already measures a class's own
    surface against, just read for the plain street class instead of a
    raised one.
    """

    _, surfaces = _floor_table(level_index)
    return surfaces[BASE_FLOOR_CLASS]


def is_hole_class(level_index: int, klass: int) -> bool:
    """No floor at all: a player standing here falls until it loses a life."""

    return floor_kind(level_index, klass) == FLOOR_NONE


def is_wall_class(level_index: int, klass: int) -> bool:
    """Floor standing ``WALL_PROBE_Z`` or more above the street's: ``$3C92``
    refuses a walk into it. A belt is floor at the street's own height."""

    kind = floor_kind(level_index, klass)
    if kind is None or kind == FLOOR_NONE:
        return False
    _, surfaces = _floor_table(level_index)
    return surfaces[klass] <= surfaces[BASE_FLOOR_CLASS] - WALL_PROBE_Z


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

    The scan starts on a cell edge: a window starting mid-cell (every
    ``camera_x - 512`` does) sampled each cell once but reported it up to 7 px
    off where it really starts.
    """

    if stride <= 0 or not cmap:
        return ()

    world_x_min -= world_x_min % CELL
    map_width = stride * 16
    map_rows = len(cmap) // stride
    cols = max(1, (world_x_max - world_x_min + CELL - 1) // CELL)
    rows = max(1, (lane_max + CELL) // CELL)
    grid = [[False] * cols for _ in range(rows)]

    for row in range(rows):
        lane = row * CELL
        if lane > lane_max:
            break
        if lane >> 3 >= map_rows:
            break
        for col in range(cols):
            wx = world_x_min + col * CELL
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

            width = (max_c - min_c + 1) * CELL
            height = (max_r - min_r + 1) * CELL
            if width < min_width and height < min_height:
                continue
            regions.append(
                FloorHole(
                    world_x=world_x_min + min_c * CELL,
                    lane_y=min_r * CELL,
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
    level_index: int | None = None,
) -> tuple[FloorHole, ...]:
    """Scan for hole cells and return one AABB per connected component.

    With ``level_index`` the round's own floor table decides what a hole is
    (``is_hole_class``: in rounds 1-5 classes 3 and 4 are holes as well as
    0, and round 6 has none on its map); without it, ``hole_class`` alone.
    Cells are 8×8 (half of a 16px collision column × lane>>3). Adjacent hole
    cells (4-connected) form one hole; we store the bounding box only so the
    HUD draws a single clean rectangle per gap instead of a tile staircase.
    """

    if world_x_max is None:
        world_x_max = stride * 16 if stride > 0 else 0
    if level_index is None:
        match = lambda klass: klass == hole_class  # noqa: E731
    else:
        match = lambda klass: is_hole_class(level_index, klass)  # noqa: E731
    return _find_class_regions(
        cmap,
        stride=stride,
        lane_max=lane_max,
        world_x_min=world_x_min,
        world_x_max=world_x_max,
        match=match,
    )


def find_collision_barriers(
    cmap: bytes,
    *,
    stride: int,
    level_index: int,
    lane_max: int = LANE_Y_MAX_DEFAULT,
    world_x_min: int = 0,
    world_x_max: int | None = None,
) -> tuple[FloorHole, ...]:
    """Walls (``is_wall_class``): the ground ``$3C92`` refuses a walk into.

    Exact, not a bounding box. A round-6 housing is a slanted block -- its
    left edge steps 8 px right per 8-lane row, x 2512..2680 on lanes 0-7 down
    to 2568..2680 on lanes 56-63 -- and its bounding box covers the floor the
    steps leave free: an actor standing there has its centre inside the box,
    the path finder drops an obstacle the body is buried in, and the walk goes
    straight back into the real wall. So this is one rectangle per run of wall
    cells along a row, merged down the rows while the run keeps the same X
    extent (a square block stays one rectangle).

    Only the round's walls: class 3/4 in round 6 are belts, floor at the
    street's own height, which the old ``class >= 2`` rule filed as barriers.
    """

    if stride <= 0 or not cmap:
        return ()
    map_width = stride * 16
    if world_x_max is None:
        world_x_max = map_width
    x_lo = max(0, world_x_min - world_x_min % CELL)
    x_hi = min(world_x_max, map_width)
    rows = min(len(cmap) // stride, lane_max // CELL + 1)

    def is_wall(x: int, lane: int) -> bool:
        return is_wall_class(
            level_index, collision_class_at(cmap, stride=stride, world_x=x, lane_y=lane)
        )

    regions: list[FloorHole] = []
    # Runs still growing down the rows: (x0, x1) -> the lane they started on.
    open_runs: dict[tuple[int, int], int] = {}
    for row in range(rows + 1):
        lane = row * CELL
        runs: list[tuple[int, int]] = []
        x = x_lo
        while row < rows and x < x_hi:
            if not is_wall(x, lane):
                x += CELL
                continue
            start = x
            while x < x_hi and is_wall(x, lane):
                x += CELL
            runs.append((start, x))
        still_open = {run: open_runs.pop(run, lane) for run in runs}
        for (x0, x1), top in open_runs.items():
            regions.append(FloorHole(world_x=x0, lane_y=top, width=x1 - x0, height=lane - top))
        open_runs = still_open

    regions.sort(key=lambda h: (h.world_x, h.lane_y))
    return tuple(regions)


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
        level_index=level_index,
    )


def barriers_for_level(
    cmap: bytes,
    *,
    stride: int,
    level_index: int,
    camera_x: int,
    margin_x: int = 512,
) -> tuple[FloorHole, ...]:
    """Return the walls near the camera for navigation."""

    lane_max = lane_y_max_for_level(level_index)
    x0 = max(0, camera_x - margin_x)
    x1 = camera_x + 320 + margin_x
    return find_collision_barriers(
        cmap,
        stride=stride,
        level_index=level_index,
        lane_max=lane_max,
        world_x_min=x0,
        world_x_max=x1,
    )
