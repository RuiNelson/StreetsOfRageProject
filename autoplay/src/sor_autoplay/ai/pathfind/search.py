"""A* over the lattice, and the vectors it hands back.

**One or two axis-aligned legs beat A*.** Before any search, the planner
asks whether the goal can be reached by walking only along Y, only along X,
or Y and then X -- never the other way around, and never a diagonal. That
is how a beat-em-up body actually closes: get on the lane, then walk in.
A free-space diagonal is shorter and is rejected anyway. The corridor is
accepted only when every step of both legs is walkable and the arrival
satisfies the same ``arrived`` test A* would use (``enough_contact``
included). Among such arrivals the cheapest wins. ``maximize_contact``
is stricter: the two legs have to line up flush, otherwise a corner clip
would steal the tick from the around-the-crate walk A* is there to find.
Anything the two legs cannot reach -- a crate that has to be walked
around, a goal sitting behind a wall -- falls through to the A* below,
diagonals and all.

The search itself is then ordinary A*: eight neighbours, a move costing its
true euclidean length, and the octile heuristic, which is exactly the
free-space optimum for those costs and therefore both admissible and
consistent. Two things are worth knowing about the result.

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

    When a one- or two-leg axis-aligned route (Y first, then X) already
    reaches, that route is returned and A* is not run.
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

    axis = _axis_aligned_yx(lattice=lattice, goal=goal, arrived=arrived, weight=weight)
    if axis is not None:
        return axis

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
            if misalignment <= 0:
                # Flush arrival: nothing cheaper can also be better aligned.
                break
            # Otherwise keep expanding *through* this position -- the better
            # lined-up spot is usually a step or two further along.
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


def _axis_aligned_yx(
    *,
    lattice: Lattice,
    goal: Goal,
    arrived: Callable[[Rect], bool],
    weight: float,
) -> Path | None:
    """A Y-then-X (or single-axis) route to the goal, or ``None``.

    ``None`` means "A* should decide": no arrival sat on that corridor, the
    only one was the origin itself, or ``maximize_contact`` is on and the
    two legs cannot line up. Staying put is ``find_path``'s early return;
    a start that has already arrived but is not flush, and a corner clip
    that would satisfy a bare arrival, both still want A* when alignment
    was asked for -- walking around a crate to stand square on its face is
    not a Y-then-X corridor.
    """

    column = [(0, 0), *_walk_line(lattice, (0, 0), Direction.UP)]
    column.extend(_walk_line(lattice, (0, 0), Direction.DOWN))

    best_key: tuple[float, float, int, int, int, int] | None = None
    best_node: tuple[int, int] | None = None
    best_rect: Rect | None = None
    visited = 0

    for _, j in column:
        row = [(0, j), *_walk_line(lattice, (0, j), Direction.LEFT)]
        row.extend(_walk_line(lattice, (0, j), Direction.RIGHT))
        visited += len(row)
        for i, _ in row:
            node = (i, j)
            rect = lattice.rect_at(node)
            if not arrived(rect):
                continue
            cost = lattice.step * (abs(i) + abs(j))
            misalignment = goal.misalignment(rect) if weight else 0.0
            # Misalignment is the second key so a score tie prefers the
            # flusher arrival -- at the default weight, 4 px of overlap
            # costs the same as the 8 px walk that buys them.
            key = (cost + weight * misalignment, misalignment, abs(j), abs(i), j, i)
            if best_key is None or key < best_key:
                best_key = key
                best_node = node
                best_rect = rect

    if best_node is None or best_node == (0, 0) or best_rect is None:
        return None
    if weight and goal.misalignment(best_rect) > 0:
        return None

    i, j = best_node
    return Path(
        steps=_yx_steps(i, j, lattice.step),
        reached=True,
        start=lattice.start,
        final=best_rect,
        nodes_expanded=visited,
        misalignment=goal.misalignment(best_rect),
        contact=goal.contact(best_rect),
    )


def _walk_line(
    lattice: Lattice,
    start: tuple[int, int],
    direction: Direction,
) -> list[tuple[int, int]]:
    """Every lattice node reachable by repeating ``direction`` from ``start``."""

    # The playable band is a few hundred px; this is a fuse, not a budget.
    limit = max(8, int(max(lattice.world.width, lattice.world.height) / lattice.step) + 8)
    nodes: list[tuple[int, int]] = []
    node = start
    while len(nodes) < limit:
        if not lattice.can_move(node, direction):
            break
        node = (node[0] + direction.dx, node[1] + direction.dy)
        nodes.append(node)
    return nodes


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
