"""Rectangle path finding on a bounded cartesian plane.

Standalone and game-agnostic on purpose: nothing in here imports a token, a
snapshot or a memory map, and nothing reads RAM. It answers one question --
*how does this box get over there without touching those boxes* -- so it can
be tested exhaustively without a running `sor`, and so the caller that turns
the answer into d-pad input stays the only place that knows about the game.

The model is deliberately small:

- the world is a rectangle, and the moving body must stay entirely inside it;
- everything solid is a rectangle, and the body may touch one but never
  overlap it;
- the destination is a point to stand on (:class:`PointGoal`), a line to
  reach with named sides of the body (:class:`SegmentGoal`), or another
  rectangle whose named edges must meet named edges of the body
  (:class:`RectGoal` -- ``RectGoal.horizontal(crate)`` is "arrive stacked
  above or below that crate", never merely "arrive near it");
- a destination that is an *area* rather than a boundary
  (:class:`RegionGoal`) -- "get your body onto this patch of ground". The
  other three are measure-zero targets a lattice can miss forever; a region
  always has something inside it, which is what "close enough to act" means;
- how *well* the edges have to meet is a separate question, and an opt-in
  one: ``enough_contact`` requires a number of px of shared edge before an
  arrival counts, ``maximize_contact`` prefers the flushest arrival the
  search can find. Neither is on by default -- without them, edges meeting
  corner to corner count as arrival;
- the answer is a list of vectors in the eight compass directions, each at
  least ``step`` long and a whole multiple of it -- diagonals cheap on the
  first half of the farther axis, then only if cardinals cannot arrive.

That last property is the reason the search exists at all. A beat-em-up AI
does not steer with a continuous heading; it holds a direction on a d-pad for
a while. Planning in units of "hold this way for at least N px" produces
movement the game can actually execute, and the merging in
:func:`~sor_autoplay.ai.pathfind.search.find_path` means a long straight run
comes back as one vector instead of a stutter of single cells.

    >>> from sor_autoplay.ai.pathfind import Rect, PointGoal, Point, find_path
    >>> path = find_path(
    ...     start=Rect(0, 0, 16, 16),
    ...     goal=PointGoal(Point(60, 4)),
    ...     world=Rect(0, 0, 320, 112),
    ...     obstacles=[Rect(24, 0, 16, 16)],
    ...     step=8,
    ... )
    >>> path.reached
    True

See :mod:`~sor_autoplay.ai.pathfind.grid` for the collision rules (swept
moves, no corner cutting, and how an already-overlapping start escapes) and
:mod:`~sor_autoplay.ai.pathfind.search` for what a failed search returns.
"""

from __future__ import annotations

from .geometry import (
    ALL_DIRECTIONS,
    CARDINALS,
    DIAGONALS,
    HORIZONTAL_EDGES,
    VERTICAL_EDGES,
    Direction,
    Edge,
    Point,
    Rect,
    Segment,
    contact_length,
    contact_shortfall,
    octile_distance,
)
from .goals import Goal, PointGoal, RectGoal, RegionGoal, SegmentGoal
from .grid import Lattice
from .search import (
    DEFAULT_ALIGNMENT_WEIGHT,
    DEFAULT_MAX_NODES,
    Path,
    Step,
    find_path,
)

__all__ = [
    "ALL_DIRECTIONS",
    "CARDINALS",
    "DEFAULT_ALIGNMENT_WEIGHT",
    "DEFAULT_MAX_NODES",
    "DIAGONALS",
    "Direction",
    "Edge",
    "Goal",
    "HORIZONTAL_EDGES",
    "Lattice",
    "Path",
    "Point",
    "PointGoal",
    "Rect",
    "RectGoal",
    "RegionGoal",
    "Segment",
    "SegmentGoal",
    "VERTICAL_EDGES",
    "Step",
    "contact_length",
    "contact_shortfall",
    "find_path",
    "octile_distance",
]
