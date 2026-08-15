"""A* over the lattice, and the vectors it hands back.

The search itself is ordinary A*: eight neighbours, a move costing its true
euclidean length, and the octile heuristic, which is exactly the free-space
optimum for those costs and therefore both admissible and consistent.

**A reachable Y-then-X finish cuts the search short.** After a node is
expanded, and before its eight neighbours are generated, the planner asks
whether the goal can be reached from *here* by walking only along Y, only
along X, or Y and then X -- never the other way around, and never a
diagonal. That is how a beat-em-up body actually closes: get on the lane,
then walk in. If those one or two legs are walkable and satisfy the same
``arrived`` test A* would use (``enough_contact`` included), the route is
the A* prefix to this node plus those legs, and the search stops. A
free-space start therefore comes out as Y then X even though a diagonal is
shorter; a start boxed in still walks around with A* and only straightens
once a node can see the goal that way. ``maximize_contact`` is stricter:
the two legs have to line up flush, otherwise a corner clip would hide the
around-the-crate walk the rest of A* is there to find.

Two other things are worth knowing about the result.

**The vectors are merged, not one per cell.** A route of nine cells to the
right is one ``Step`` of ``9 * step`` px, not nine of ``step``. That is the
whole point of the minimum length: a caller driving a d-pad wants "hold right
for this far", and a stream of one-cell hops is both unusable and, once
turned into input, indistinguishable from noise.

**A failed search still answers.** When no route reaches the goal, the path
returned is the best-effort one -- the route to the expanded position that
came closest to the goal -- with ``reached=False``. An AI that must act every
tick is better served by "walk this far towards it and re-plan when the world
has moved" than by an empty answer, and the flag keeps the two cases
distinguishable for callers that do care.

**Arriving is not always enough; arriving lined up can matter.** Two edges
that meet corner to corner satisfy a goal and are useless in practice -- a
body barely clipping the top of a crate cannot act on it. Two opt-in
parameters address that, and they are different tools:

- ``enough_contact`` is a *requirement*. It raises the bar for arrival
  itself: nothing counts until the body shares at least that many px of edge
  with the goal. Use it when a number is genuinely needed ("my attack box is
  16px wide, so 16px of overlap or it was not a hit"). If no reachable
  position clears the bar, the search reports the usual best effort with
  ``reached=False`` rather than pretending.
- ``maximize_contact`` is a *preference*. It leaves arrival alone and makes
  the search prefer the flushest arrival it can find: each one is scored
  ``cost + alignment_weight * misalignment`` and the search keeps going
  until no unexplored node could beat the best score, which the admissible
  heuristic makes a cheap test (``f`` is a lower bound on the cost of any
  route through that node, and an arrival's score is never below its cost).
  Off by default, because it costs extra expansions and most callers want
  the cheapest route that qualifies.

The weight has to exceed 1 to ever change anything, because a pixel of extra
overlap costs at least a pixel of walking -- at exactly 1 the two cancel and
the first arrival wins every tie.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .geometry import (
    ALL_DIRECTIONS,
    CARDINALS,
    EPS,
    Direction,
    Rect,
    direction_from_offset,
    octile_distance,
)
from .goals import Goal
from .grid import Lattice

DIAGONAL_COST = math.sqrt(2.0)

# A ceiling on how much of the lattice one call may explore. Reaching it
# returns the best effort so far instead of stalling an AI tick; a 320x112
# playfield at an 8px step is under 600 cells, so only a pathological world
# or a tiny step gets anywhere near this.
DEFAULT_MAX_NODES = 20_000

# How many px of travel one px of missing edge overlap is worth while
# ``maximize_contact`` is on. Anything at or below 1 is inert (see the module
# docstring); 2 means the search will spend the walk needed to line an edge
# up whenever the detour is no longer than the alignment it buys, which is
# the "as flush as the geometry allows" reading without chasing arbitrarily
# long detours for it.
DEFAULT_ALIGNMENT_WEIGHT = 2.0

# A crate-sized goal window is a handful of lattice cells and is cheap to
# try in full. A full-height segment at a 1px step is thousands, and trying
# every one from every expanded node is what froze the viewer.
MAX_YX_WINDOW = 64


@dataclass(frozen=True)
class Step:
    """One movement vector: a direction and how far to travel along it."""

    direction: Direction
    length: float

    @property
    def dx(self) -> float:
        return self.direction.dx * self.length

    @property
    def dy(self) -> float:
        return self.direction.dy * self.length


@dataclass(frozen=True)
class Path:
    """The answer: where to go, and whether it actually gets there."""

    steps: tuple[Step, ...]
    reached: bool
    start: Rect
    final: Rect
    nodes_expanded: int
    # How much of the shorter contact edge did not line up on arrival, in px;
    # 0 for a flush arrival, and for goals that have no edges to line up.
    misalignment: float = 0.0
    # How much edge the arrival actually shares with the goal, in px;
    # ``inf`` when the goal has no measurable contact (a point, an oblique
    # segment) and 0.0 when the goal was not reached at all.
    contact: float = 0.0

    def __bool__(self) -> bool:
        return bool(self.steps)

    @property
    def length(self) -> float:
        """Total distance travelled, diagonals counted at their true length."""

        return sum(math.hypot(step.dx, step.dy) for step in self.steps)

    def positions(self) -> tuple[Rect, ...]:
        """Every position the body stops at, starting with ``start``."""

        rects = [self.start]
        for step in self.steps:
            rects.append(rects[-1].moved_by(step.dx, step.dy))
        return tuple(rects)


def find_path(
    *,
    start: Rect,
    goal: Goal,
    world: Rect,
    obstacles: Sequence[Rect] = (),
    step: float,
    allow_diagonals: bool = True,
    enough_contact: float = 0.0,
    maximize_contact: bool = False,
    alignment_weight: float = DEFAULT_ALIGNMENT_WEIGHT,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> Path:
    """Plan a route for ``start`` to reach ``goal`` without hitting anything.

    ``step`` is the minimum length of every returned vector; each one is a
    whole multiple of it. ``world`` bounds the plane -- the body must stay
    entirely inside it -- and ``obstacles`` are rectangles it may touch but
    never overlap.

    ``enough_contact`` raises the bar for arrival: the body must share at
    least that many px of edge with the goal for the position to count at
    all. ``maximize_contact`` instead leaves arrival alone and prefers the
    flushest arrival it can find, paying up to ``alignment_weight`` px of
    extra route per px of overlap gained. They combine: a floor plus a
    preference for doing better than the floor.

    Mid-search, a node from which the goal is one or two axis-aligned legs
    away (Y first, then X) finishes that way instead of generating more
    neighbours.
    """

    lattice = Lattice(start=start, world=world, obstacles=obstacles, step=step)
    directions = ALL_DIRECTIONS if allow_diagonals else CARDINALS
    target_box = goal.bounding_box()

    def heuristic(node: tuple[int, int]) -> float:
        dx, dy = lattice.rect_at(node).gap_to(target_box)
        return octile_distance(dx, dy)

    weight = alignment_weight if maximize_contact else 0.0

    def arrived(rect: Rect) -> bool:
        """Goal satisfied *and*, if one was asked for, contact enough."""

        if not goal.is_reached(rect):
            return False
        return enough_contact <= 0 or goal.contact(rect) >= enough_contact - 1e-9

    origin = (0, 0)
    if arrived(start) and (weight <= 0 or goal.misalignment(start) <= 0):
        return Path((), True, start, start, 0, goal.misalignment(start), goal.contact(start))

    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    best_cost: dict[tuple[int, int], float] = {origin: 0.0}
    # Ties are broken by insertion order so the same world always plans the
    # same route -- a wandering AI is impossible to debug otherwise.
    counter = 0
    start_h = heuristic(origin)
    queue: list[tuple[float, float, int, tuple[int, int]]] = [
        (start_h, start_h, counter, origin)
    ]

    closest = origin
    closest_key = (start_h, 0.0)
    expanded = 0
    goal_node: tuple[int, int] | None = None
    goal_score = math.inf
    # When the search finishes by Y-then-X from an expanded node, this is
    # that node; reconstruction walks A* to it and then appends the two legs.
    yx_from: tuple[int, int] | None = None
    goal_window = _touch_window(lattice, target_box)
    # A cheaper route to an already-queued node pushes a second entry rather
    # than sifting the heap; the stale one is dropped here when it surfaces.
    closed: set[tuple[int, int]] = set()

    while queue:
        f, _, _, node = heapq.heappop(queue)
        if node in closed:
            continue
        # Nothing still queued can arrive better than the best arrival so
        # far: `f` is a lower bound on the cost of any route through this
        # node, and an arrival's score is never below its own cost.
        if f >= goal_score - 1e-12:
            break
        closed.add(node)
        cost = best_cost[node]

        expanded += 1
        rect = lattice.rect_at(node)
        if arrived(rect):
            misalignment = goal.misalignment(rect) if weight else 0.0
            score = cost + weight * misalignment
            if score < goal_score:
                goal_score = score
                goal_node = node
                yx_from = None
            if misalignment <= 0:
                # Flush arrival: nothing cheaper can also be better aligned.
                break
            # Otherwise keep expanding *through* this position -- the better
            # lined-up spot is usually a step or two further along.
        finish = _best_yx_from(
            lattice,
            node,
            arrived,
            goal,
            goal_window,
            require_flush=weight > 0,
        )
        if finish is not None:
            arrival, arrival_rect = finish
            extra = step * (
                abs(arrival[0] - node[0]) + abs(arrival[1] - node[1])
            )
            misalignment = goal.misalignment(arrival_rect) if weight else 0.0
            score = cost + extra + weight * misalignment
            if score < goal_score:
                goal_score = score
                goal_node = arrival
                yx_from = node
            if misalignment <= 0:
                break
        if expanded >= max_nodes:
            break

        for direction in directions:
            if not lattice.can_move(node, direction):
                continue
            neighbour = (node[0] + direction.dx, node[1] + direction.dy)
            move_cost = step * (DIAGONAL_COST if direction.is_diagonal else 1.0)
            tentative = cost + move_cost
            if tentative >= best_cost.get(neighbour, math.inf) - 1e-12:
                continue

            best_cost[neighbour] = tentative
            came_from[neighbour] = node
            h = heuristic(neighbour)
            counter += 1
            heapq.heappush(queue, (tentative + h, h, counter, neighbour))

            # Closest-so-far is tracked on push, not on expansion: a search
            # that runs out of budget should still be able to report the
            # nearest place it found, even if it never got to stand there.
            key = (h, tentative)
            if key < closest_key:
                closest_key = key
                closest = neighbour

    end = goal_node if goal_node is not None else closest
    final = lattice.rect_at(end)
    if yx_from is not None and goal_node is not None:
        prefix = _reconstruct(came_from, origin, yx_from)
        di = goal_node[0] - yx_from[0]
        dj = goal_node[1] - yx_from[1]
        steps = _merge(prefix, step) + _yx_steps(di, dj, step)
    else:
        steps = _merge(_reconstruct(came_from, origin, end), step)
    # Measured once, on the position actually chosen: the caller wants to
    # know how flush the arrival was whether or not the search was told to
    # care about it.
    reached = goal_node is not None
    return Path(
        steps=steps,
        reached=reached,
        start=start,
        final=final,
        nodes_expanded=expanded,
        misalignment=goal.misalignment(final) if reached else 0.0,
        contact=goal.contact(final) if reached else 0.0,
    )


def _best_yx_from(
    lattice: Lattice,
    origin: tuple[int, int],
    arrived: Callable[[Rect], bool],
    goal: Goal,
    window: tuple[int, int, int, int] | None,
    *,
    require_flush: bool,
) -> tuple[tuple[int, int], Rect] | None:
    """Y-then-X arrival from ``origin`` onto the goal window, or ``None``.

    Small windows (a crate, a point at a coarse step) are tried in full.
    Large ones (a full-height segment at 1px) only aim at the cheapest
    cell and the aligned one -- walking every row from every expanded
    node is what froze the viewer.
    """

    if window is None:
        return None

    best_key: tuple[int, float, int, int, int, int] | None = None
    best_node: tuple[int, int] | None = None
    best_rect: Rect | None = None

    for node in _yx_aims(origin, window, require_flush):
        if node == origin:
            continue
        if not _yx_clear(lattice, origin, node):
            continue
        rect = lattice.rect_at(node)
        if not arrived(rect):
            continue
        misalignment = goal.misalignment(rect)
        if require_flush and misalignment > 0:
            continue
        di = abs(node[0] - origin[0])
        dj = abs(node[1] - origin[1])
        key = (di + dj, misalignment, dj, di, node[1], node[0])
        if best_key is None or key < best_key:
            best_key = key
            best_node = node
            best_rect = rect

    if best_node is None or best_rect is None:
        return None
    return best_node, best_rect


def _touch_window(lattice: Lattice, box: Rect) -> tuple[int, int, int, int] | None:
    """Inclusive lattice ranges whose body can touch ``box``, or ``None``."""

    start, step = lattice.start, lattice.step
    i_lo = math.ceil((box.left - start.x - start.width) / step - EPS)
    i_hi = math.floor((box.right - start.x) / step + EPS)
    j_lo = math.ceil((box.top - start.y - start.height) / step - EPS)
    j_hi = math.floor((box.bottom - start.y) / step + EPS)
    if i_lo > i_hi or j_lo > j_hi:
        return None
    return i_lo, i_hi, j_lo, j_hi


def _yx_aims(
    origin: tuple[int, int],
    window: tuple[int, int, int, int],
    require_flush: bool,
) -> list[tuple[int, int]]:
    """Window cells worth finishing toward from ``origin``."""

    i_lo, i_hi, j_lo, j_hi = window
    i0, j0 = origin
    cheap = (_clamp(i0, i_lo, i_hi), _clamp(j0, j_lo, j_hi))
    aligned = (_align_index(i_lo, i_hi), _align_index(j_lo, j_hi))
    size = (i_hi - i_lo + 1) * (j_hi - j_lo + 1)
    if size <= MAX_YX_WINDOW:
        cells = [
            (i, j) for j in range(j_lo, j_hi + 1) for i in range(i_lo, i_hi + 1)
        ]
        # Flush wants the centred face first; otherwise the cheapest L.
        if require_flush:
            cells.sort(
                key=lambda node: (
                    abs(node[0] - aligned[0]) + abs(node[1] - aligned[1]),
                    abs(node[1] - aligned[1]),
                    abs(node[0] - aligned[0]),
                )
            )
        else:
            cells.sort(
                key=lambda node: (
                    abs(node[0] - i0) + abs(node[1] - j0),
                    abs(node[1] - j0),
                    abs(node[0] - i0),
                )
            )
        return cells
    if require_flush:
        return [aligned]
    if aligned == cheap:
        return [cheap]
    return [cheap, aligned]


def _align_index(lo: int, hi: int) -> int:
    """Lattice index at the middle of the window -- the flush-aligned aim."""

    return int(round((lo + hi) / 2.0))


def _clamp(value: int, lo: int, hi: int) -> int:
    return lo if value < lo else hi if value > hi else value


def _yx_clear(lattice: Lattice, start: tuple[int, int], end: tuple[int, int]) -> bool:
    """Can the body walk Y then X from ``start`` to ``end`` in two sweeps?"""

    corner = (start[0], end[1])
    return _axis_clear(lattice, start, corner) and _axis_clear(lattice, corner, end)


def _axis_clear(lattice: Lattice, start: tuple[int, int], end: tuple[int, int]) -> bool:
    """Is the axis-aligned run from ``start`` to ``end`` standable and unswept?"""

    if start == end:
        return start == (0, 0) or lattice.is_free(start)
    if start[0] != end[0] and start[1] != end[1]:
        return False
    if not lattice.is_free(end):
        return False
    if start == (0, 0) and not lattice.start_is_free:
        # A hanging origin cannot be judged by one big sweep: intermediates
        # still have to walk back into the world one cell at a time.
        di = 0 if end[0] == start[0] else (1 if end[0] > start[0] else -1)
        dj = 0 if end[1] == start[1] else (1 if end[1] > start[1] else -1)
        direction = direction_from_offset(di, dj)
        node = start
        while node != end:
            if not lattice.can_move(node, direction):
                return False
            node = (node[0] + di, node[1] + dj)
        return True
    swept = lattice.rect_at(start).union(lattice.rect_at(end))
    return not any(swept.overlaps(obstacle) for obstacle in lattice.obstacles)


def _yx_steps(i: int, j: int, step: float) -> tuple[Step, ...]:
    """The one or two vectors that walk to lattice node ``(i, j)``, Y first."""

    steps: list[Step] = []
    if j:
        steps.append(Step(Direction.UP if j < 0 else Direction.DOWN, abs(j) * step))
    if i:
        steps.append(Step(Direction.LEFT if i < 0 else Direction.RIGHT, abs(i) * step))
    return tuple(steps)


def _reconstruct(
    came_from: dict[tuple[int, int], tuple[int, int]],
    origin: tuple[int, int],
    end: tuple[int, int],
) -> list[Direction]:
    moves: list[Direction] = []
    node = end
    while node != origin:
        previous = came_from[node]
        moves.append(direction_from_offset(node[0] - previous[0], node[1] - previous[1]))
        node = previous
    moves.reverse()
    return moves


def _merge(moves: list[Direction], step: float) -> tuple[Step, ...]:
    """Collapse consecutive cells in the same direction into one vector."""

    merged: list[Step] = []
    for direction in moves:
        if merged and merged[-1].direction is direction:
            merged[-1] = Step(direction, merged[-1].length + step)
        else:
            merged.append(Step(direction, step))
    return tuple(merged)
