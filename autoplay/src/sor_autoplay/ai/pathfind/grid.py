"""The lattice the search walks on, and what a body is allowed to do on it.

The grid is not a partition of the world -- it is a lattice of *body
positions* anchored at the start rectangle, one cell equal to the requested
step length. Anchoring it at the start is what makes the guarantee in the
package docstring hold without any post-processing: every reachable position
sits at ``start + (i, j) * step``, so every move between neighbours is a
whole number of steps long, and merging a run of identical moves can only
produce a longer multiple. Quantising to a world-anchored grid instead would
force a ragged first step to get onto it.

Collision is decided for the **whole body**, never its centre:

- the body must stay inside the world bounds;
- it must not overlap an obstacle (flush contact is fine);
- the swept box of a move must be clear too, so a step cannot tunnel through
  an obstacle thinner than the step;
- a diagonal must not cut a corner: both L-shaped detours around it have to
  be walkable. Two crates touching at their corners form a wall here, which
  is the conservative reading and the one that does not walk a body into
  geometry it cannot actually pass.

A body that is *already* inside an obstacle -- spawned there, pushed there,
or simply modelled with a hitbox larger than the game's -- is the one
exception. Those obstacles are dropped from the collision set for the whole
search, because a body sitting in the middle of a crate cannot leave it in
one step and would otherwise be planned as permanently stuck. It costs
nothing in practice: a route that re-entered an obstacle it had already left
is never cheaper than one that did not, so the search does not produce one.
"""

from __future__ import annotations

from collections.abc import Sequence

from .geometry import Direction, Rect


class Lattice:
    """Body positions reachable by whole steps from the start rectangle."""

    def __init__(
        self,
        *,
        start: Rect,
        world: Rect,
        obstacles: Sequence[Rect],
        step: float,
    ) -> None:
        if step <= 0:
            raise ValueError("the step length must be positive")

        self.start = start
        self.world = world
        self.step = step
        # Obstacles that cannot ever matter are dropped once here rather than
        # skipped on every one of the thousands of overlap tests a search
        # runs: degenerate ones, ones outside the world, and the ones the
        # body already stands in (see the module docstring).
        relevant = tuple(
            obstacle
            for obstacle in obstacles
            if obstacle.width > 0 and obstacle.height > 0 and obstacle.overlaps(world)
        )
        self.ignored = tuple(
            obstacle for obstacle in relevant if obstacle.overlaps(start)
        )
        self.obstacles = tuple(
            obstacle for obstacle in relevant if not obstacle.overlaps(start)
        )
        self.start_is_free = self._is_free(start)
        self._free: dict[tuple[int, int], bool] = {}

    def rect_at(self, node: tuple[int, int]) -> Rect:
        i, j = node
        return self.start.moved_by(i * self.step, j * self.step)

    def is_free(self, node: tuple[int, int]) -> bool:
        """Can the body stand here?"""

        cached = self._free.get(node)
        if cached is None:
            cached = self._is_free(self.rect_at(node))
            self._free[node] = cached
        return cached

    def can_move(self, node: tuple[int, int], direction: Direction) -> bool:
        """Is a single step from ``node`` in ``direction`` walkable?"""

        target = (node[0] + direction.dx, node[1] + direction.dy)
        if not self.is_free(target):
            return False

        if node == (0, 0) and not self.start_is_free:
            # A start that is still not free once its own obstacles have been
            # dropped is one hanging out of the world. Judge the first move
            # only by where it lands, so the body can walk back in.
            return True

        if not direction.is_diagonal:
            return self._sweep_is_free(node, target)

        side_x = (node[0] + direction.dx, node[1])
        side_y = (node[0], node[1] + direction.dy)
        if not self.is_free(side_x) or not self.is_free(side_y):
            return False
        # Both L-shaped detours, each leg swept -- a diagonal is allowed only
        # where the two routes it stands in for are themselves walkable.
        return (
            self._sweep_is_free(node, side_x)
            and self._sweep_is_free(side_x, target)
            and self._sweep_is_free(node, side_y)
            and self._sweep_is_free(side_y, target)
        )

    def _sweep_is_free(self, node: tuple[int, int], other: tuple[int, int]) -> bool:
        swept = self.rect_at(node).union(self.rect_at(other))
        return not any(swept.overlaps(obstacle) for obstacle in self.obstacles)

    def _is_free(self, rect: Rect) -> bool:
        if not self.world.contains(rect):
            return False
        return not any(rect.overlaps(obstacle) for obstacle in self.obstacles)
