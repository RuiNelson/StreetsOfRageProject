"""A* over the lattice, and the vectors it hands back.

The search itself is ordinary A*: eight neighbours, a move costing its true
euclidean length, and the octile heuristic, which is exactly the free-space
optimum for those costs and therefore both admissible and consistent. Two
things are worth knowing about the result.

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
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence
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
    max_nodes: int = DEFAULT_MAX_NODES,
) -> Path:
    """Plan a route for ``start`` to reach ``goal`` without hitting anything.

    ``step`` is the minimum length of every returned vector; each one is a
    whole multiple of it. ``world`` bounds the plane -- the body must stay
    entirely inside it -- and ``obstacles`` are rectangles it may touch but
    never overlap.
    """

    lattice = Lattice(start=start, world=world, obstacles=obstacles, step=step)
    directions = ALL_DIRECTIONS if allow_diagonals else CARDINALS
    target_box = goal.bounding_box()

    def heuristic(node: tuple[int, int]) -> float:
        dx, dy = lattice.rect_at(node).gap_to(target_box)
        return octile_distance(dx, dy)

    origin = (0, 0)
    if goal.is_reached(start):
        return Path((), True, start, start, 0)

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
    # A cheaper route to an already-queued node pushes a second entry rather
    # than sifting the heap; the stale one is dropped here when it surfaces.
    closed: set[tuple[int, int]] = set()

    while queue:
        _, _, _, node = heapq.heappop(queue)
        if node in closed:
            continue
        closed.add(node)
        cost = best_cost[node]

        expanded += 1
        rect = lattice.rect_at(node)
        if goal.is_reached(rect):
            goal_node = node
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
    steps = _merge(_reconstruct(came_from, origin, end), step)
    return Path(
        steps=steps,
        reached=goal_node is not None,
        start=start,
        final=lattice.rect_at(end),
        nodes_expanded=expanded,
    )


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
