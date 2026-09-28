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

A move's sweep is only tested when it can find something the two ends did
not: a body at least a step (plus ``2 * EPS``) long along the move's axis
covers the whole swept strip with its start and end positions, so an
obstacle meeting the strip meets one of them, and both ends are already
known free when the sweep is asked about. Every character body is 16 px or
more against a 4 px step, and the sweep was most of what a search cost --
a route to an unreachable goal explored the whole lattice twice and held
the AI's tick for up to a second (``tools/grunt_fight.py --profile-ms``).

"Inside" means the body's **centre** sits in the obstacle's interior, not
that the rectangles merely overlap. A 1px-tall floor (a wall shallower than
the body) is routinely overlapped by a body standing legally in front of it;
treating that graze as "already inside" dropped the wall and routed through
the real solid -- the first-level phone-booth stall.
"""

from __future__ import annotations

from collections.abc import Sequence

from .geometry import EPS, Direction, Rect


_DIR_PARAMS: dict[Direction, tuple[int, int, bool]] = {}


def _dir_params(direction: Direction) -> tuple[int, int, bool]:
    """Cached ``(dx, dy, is_diagonal)`` for a direction.

    The ``Direction.dx``/``dy``/``is_diagonal`` properties re-read
    ``direction.value`` on every call; the search asks several times per
    neighbour, so the tuple is computed once per direction instead.
    """

    cached = _DIR_PARAMS.get(direction)
    if cached is None:
        dx, dy = direction.value
        cached = (dx, dy, dx != 0 and dy != 0)
        _DIR_PARAMS[direction] = cached
    return cached


def _center_buried_in(start: Rect, obstacle: Rect) -> bool:
    """True when the body is sitting *in* the obstacle, not merely clipping it.

    A graze -- the 1px floor of a wall shallower than the body -- is not
    "already inside". Dropping those lets the search walk through the real
    solid the over-statement was standing in for.
    """

    centre = start.center
    return (
        obstacle.left + EPS < centre.x < obstacle.right - EPS
        and obstacle.top + EPS < centre.y < obstacle.bottom - EPS
    )


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
            obstacle for obstacle in relevant if _center_buried_in(start, obstacle)
        )
        self.obstacles = tuple(
            obstacle for obstacle in relevant if obstacle not in self.ignored
        )
        # Coordinate caches for the hot loop: the same geometry as the Rect
        # methods below, but as plain floats so thousands of overlap tests
        # per search cost comparisons instead of dataclass allocations and
        # property lookups. ``obstacles`` stays the public, Rect-typed tuple.
        self._sx = start.x
        self._sy = start.y
        self._bw = start.width
        self._bh = start.height
        self._wl = world.x
        self._wt = world.y
        self._wr = world.x + world.width
        self._wb = world.y + world.height
        self._obs: tuple[tuple[float, float, float, float], ...] = tuple(
            (o.x, o.y, o.x + o.width, o.y + o.height) for o in self.obstacles
        )
        self.start_is_free = self._is_free_coords(self._sx, self._sy)
        self._free: dict[tuple[int, int], bool] = {}
        # ``search._axis_clear``'s memo: (start, end) -> clear.
        self.runs: dict[tuple[tuple[int, int], tuple[int, int]], bool] = {}
        # Whether a sweep along each axis can see more than its two ends (the
        # module docstring): only for a body shorter than a step on that axis.
        self._sweep_x = start.width < step + 2 * EPS
        self._sweep_y = start.height < step + 2 * EPS

    def coords_at(self, node: tuple[int, int]) -> tuple[float, float]:
        """Top-left corner of the body at ``node``, without allocating a Rect.

        Pure arithmetic on purpose: the coordinates are an affine function
        of the indices, so a dict cache would cost more per hit than the two
        multiplications it saves.
        """

        return (self._sx + node[0] * self.step, self._sy + node[1] * self.step)

    def rect_at(self, node: tuple[int, int]) -> Rect:
        x, y = self.coords_at(node)
        return Rect(x, y, self._bw, self._bh)

    def is_free(self, node: tuple[int, int]) -> bool:
        """Can the body stand here?"""

        cached = self._free.get(node)
        if cached is None:
            x, y = self.coords_at(node)
            cached = self._is_free_coords(x, y)
            self._free[node] = cached
        return cached

    def swept_is_free_coords(
        self, ax: float, ay: float, bx: float, by: float
    ) -> bool:
        """Is the swept volume between two body origins clear of obstacles?

        The union of the body at ``(ax, ay)`` and at ``(bx, by)``, tested
        without allocating either rectangle.
        """

        bw, bh = self._bw, self._bh
        x0 = ax if ax < bx else bx
        y0 = ay if ay < by else by
        ax1 = ax + bw
        bx1 = bx + bw
        x1 = ax1 if ax1 > bx1 else bx1
        ay1 = ay + bh
        by1 = by + bh
        y1 = ay1 if ay1 > by1 else by1
        eps = EPS
        for ox0, oy0, ox1, oy1 in self._obs:
            if x0 < ox1 - eps and ox0 < x1 - eps and y0 < oy1 - eps and oy0 < y1 - eps:
                return False
        return True

    def can_move(self, node: tuple[int, int], direction: Direction) -> bool:
        """Is a single step from ``node`` in ``direction`` walkable?"""

        dx, dy, is_diag = _dir_params(direction)
        ax, ay = self.coords_at(node)
        return self.can_move_from(node, ax, ay, dx, dy, is_diag)

    def can_move_from(
        self,
        node: tuple[int, int],
        ax: float,
        ay: float,
        dx: int,
        dy: int,
        is_diag: bool,
    ) -> bool:
        """``can_move`` with the node's coordinates already computed.

        The search expands a node once but tests up to eight neighbours from
        it; looking the same coordinates up per neighbour is pure overhead.
        Target and side coordinates are affine in the node's, so they are
        derived arithmetically rather than looked up.
        """

        target = (node[0] + dx, node[1] + dy)
        if not self.is_free(target):
            return False

        if node == (0, 0) and not self.start_is_free:
            # A start that is still not free once its own obstacles have been
            # dropped is one hanging out of the world. Judge the first move
            # only by where it lands, so the body can walk back in.
            return True

        step = self.step
        bx = ax + dx * step
        by = ay + dy * step
        if not is_diag:
            return self.swept_is_free_coords(ax, ay, bx, by)

        side_x = (node[0] + dx, node[1])
        side_y = (node[0], node[1] + dy)
        if not self.is_free(side_x) or not self.is_free(side_y):
            return False
        sx, sy = ax + dx * step, ay
        qx, qy = ax, ay + dy * step
        # Both L-shaped detours, each leg swept -- a diagonal is allowed only
        # where the two routes it stands in for are themselves walkable.
        return (
            self.swept_is_free_coords(ax, ay, sx, sy)
            and self.swept_is_free_coords(sx, sy, bx, by)
            and self.swept_is_free_coords(ax, ay, qx, qy)
            and self.swept_is_free_coords(qx, qy, bx, by)
        )

    def _sweep_is_free(self, node: tuple[int, int], other: tuple[int, int]) -> bool:
        ax, ay = self.coords_at(node)
        bx, by = self.coords_at(other)
        return self.swept_is_free_coords(ax, ay, bx, by)

    def _is_free(self, rect: Rect) -> bool:
        return self._is_free_coords(rect.x, rect.y)

    def _is_free_coords(self, x: float, y: float) -> bool:
        bw, bh = self._bw, self._bh
        x1 = x + bw
        y1 = y + bh
        eps = EPS
        if x < self._wl - eps or x1 > self._wr + eps or y < self._wt - eps or y1 > self._wb + eps:
            return False
        for ox0, oy0, ox1, oy1 in self._obs:
            if x < ox1 - eps and ox0 < x1 - eps and y < oy1 - eps and oy0 < y1 - eps:
                return False
        return True
