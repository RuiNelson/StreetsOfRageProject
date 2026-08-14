"""A* over the lattice, and the vectors it hands back.

The search itself is ordinary A*: eight neighbours, a move costing its true
euclidean length, and the octile heuristic, which is exactly the free-space
optimum for those costs and therefore both admissible and consistent.

**Diagonals are only cheap on the way in.** The farther axis from the
start to the goal -- X on a tie, which is the usual approach -- is split
in half. While more than half that gap remains *and* the other axis
still has something to close, a diagonal costs its true length and is
the shortcut it always was. Once the body has closed half the gap -- or
the short axis is already aligned -- a diagonal is charged more than
walking the entire node budget on cardinals, so the last stretch is
axis-aligned unless no cardinal route can arrive at all. That is the
shape a d-pad approach wants: weave toward the target, then straighten
so the actor is not still sliding diagonally as it arrives.

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

The weight has to exceed 1 to ever walk further for alignment, because a
pixel of extra overlap costs at least a pixel of walking. At exactly 1 the
two cancel and the search keeps the flusher of those equal-score arrivals
rather than whichever it found first.
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
    never overlap. Diagonals are cheap only while more than half of the
    farther start-to-goal axis remains; after that they are a last resort.

    ``enough_contact`` raises the bar for arrival: the body must share at
    least that many px of edge with the goal for the position to count at
    all. ``maximize_contact`` instead leaves arrival alone and prefers the
    flushest arrival it can find, paying up to ``alignment_weight`` px of
    extra route per px of overlap gained. They combine: a floor plus a
    preference for doing better than the floor.
    """

    lattice = Lattice(start=start, world=world, obstacles=obstacles, step=step)
    directions = ALL_DIRECTIONS if allow_diagonals else CARDINALS
    target_box = goal.bounding_box()
    start_dx, start_dy = start.gap_to(target_box)
    # X on a tie: the usual approach axis, and the one the caller named
    # when they said "generally it's X".
    dominant_axis = "y" if start_dy > start_dx else "x"
    start_gap = start_dy if dominant_axis == "y" else start_dx
    straighten_after = start_gap * 0.5
    # A second-half diagonal must lose to every cardinal-only finish,
    # even one that visits every budgeted node. Among finishes with the
    # same number of late diagonals the geometric length still breaks ties.
    late_diagonal_penalty = max_nodes * step * DIAGONAL_COST + 1.0

    def heuristic(node: tuple[int, int]) -> float:
        dx, dy = lattice.rect_at(node).gap_to(target_box)
        return octile_distance(dx, dy)

    def cheap_diagonal(rect: Rect) -> bool:
        """May a diagonal from ``rect`` cost its true length?

        Only while more than half the farther axis remains *and* the
        other axis still has a gap to close. A diagonal after the short
        axis is already aligned would walk off a line the body already
        has, and the second half of the approach is meant to be straight.
        """

        dx, dy = rect.gap_to(target_box)
        dominant = dy if dominant_axis == "y" else dx
        other = dx if dominant_axis == "y" else dy
        return dominant > straighten_after + 1e-12 and other > 1e-12

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
    goal_misalignment = math.inf
    # A cheaper route to an already-queued node pushes a second entry rather
    # than sifting the heap; the stale one is dropped here when it surfaces.
    closed: set[tuple[int, int]] = set()

    while queue:
        f, _, _, node = heapq.heappop(queue)
        if node in closed:
            continue
        # Nothing still queued can arrive *better* than the best arrival
        # so far: `f` is a lower bound on the cost of any route through
        # this node, and an arrival's score is never below its own cost.
        # Equal `f` is still expanded -- a same-score flusher is exactly
        # the "detour no longer than the alignment it buys" case.
        if f > goal_score + 1e-12:
            break
        closed.add(node)
        cost = best_cost[node]

        expanded += 1
        rect = lattice.rect_at(node)
        if arrived(rect):
            misalignment = goal.misalignment(rect) if weight else 0.0
            score = cost + weight * misalignment
            # Equal scores prefer the flusher arrival: the weight is
            # documented as paying for alignment whenever the detour is
            # *no longer* than the overlap it buys, equality included.
            better = score < goal_score - 1e-12 or (
                weight > 0
                and abs(score - goal_score) <= 1e-12
                and misalignment < goal_misalignment
            )
            if better:
                goal_score = score
                goal_misalignment = misalignment
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
            if not direction.is_diagonal:
                move_cost = step
            elif cheap_diagonal(rect):
                move_cost = step * DIAGONAL_COST
            else:
                move_cost = late_diagonal_penalty + step * DIAGONAL_COST
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
