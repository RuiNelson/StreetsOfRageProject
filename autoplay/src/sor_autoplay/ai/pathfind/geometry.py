"""Rectangles, segments and the eight directions -- pure geometry.

Nothing here knows about Streets of Rage. The coordinate system is a plain
cartesian plane with **y growing downwards**, which is what the game's own
lane axis does (`LANE_Y_MIN` is the top of the walkable band), so a caller
can hand over map coordinates unchanged. ``Direction.UP`` therefore means
"towards smaller y", i.e. towards the back of the lane.

Two conventions run through the whole package:

- a rectangle is ``(x, y, width, height)`` with ``x``/``y`` at its
  **top-left** corner, and widths are never negative;
- **touching is not overlapping**. Two rectangles that share an edge do not
  collide, so a body may slide flush along a wall or stop exactly against a
  crate. Only a strictly positive area of intersection counts, which is the
  distinction ``EPS`` protects against float noise.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass

# Everything smaller than this is float noise, not geometry. The package
# works in pixels, where real distances are >= 1, so a tolerance this small
# can never swallow a meaningful gap.
EPS = 1e-9


@dataclass(frozen=True)
class Point:
    """A position in the plane."""

    x: float
    y: float


@dataclass(frozen=True)
class Segment:
    """A straight line segment between two points, in any orientation.

    Goal segments are arbitrary -- a diagonal ledge is as valid as the
    horizontal line "the far side of the door" -- so the intersection test
    below is the general one, not an axis-aligned shortcut.
    """

    start: Point
    end: Point

    @property
    def length(self) -> float:
        return math.hypot(self.end.x - self.start.x, self.end.y - self.start.y)

    @property
    def axis(self) -> str | None:
        """``"x"`` for a horizontal segment, ``"y"`` for a vertical one.

        ``None`` for anything oblique -- and for those, "how much do these
        two edges coincide" has no length to measure, which is why the
        alignment preference simply does not apply to a diagonal goal.
        """

        if abs(self.start.y - self.end.y) <= EPS:
            return "x"
        if abs(self.start.x - self.end.x) <= EPS:
            return "y"
        return None

    def collinear_overlap(self, other: Segment) -> float:
        """How much of the same line the two segments share, in px.

        Zero unless both are axis-aligned the same way *and* sit on the same
        line -- two vertical edges 4px apart overlap not at all, however much
        their y spans agree.
        """

        axis = self.axis
        if axis is None or other.axis != axis:
            return 0.0

        if axis == "x":
            if abs(self.start.y - other.start.y) > EPS:
                return 0.0
            mine = (min(self.start.x, self.end.x), max(self.start.x, self.end.x))
            theirs = (min(other.start.x, other.end.x), max(other.start.x, other.end.x))
        else:
            if abs(self.start.x - other.start.x) > EPS:
                return 0.0
            mine = (min(self.start.y, self.end.y), max(self.start.y, self.end.y))
            theirs = (min(other.start.y, other.end.y), max(other.start.y, other.end.y))

        return max(0.0, min(mine[1], theirs[1]) - max(mine[0], theirs[0]))

    @property
    def bounds(self) -> Rect:
        """The smallest rectangle containing the segment (possibly flat)."""

        left = min(self.start.x, self.end.x)
        top = min(self.start.y, self.end.y)
        return Rect(
            left,
            top,
            max(self.start.x, self.end.x) - left,
            max(self.start.y, self.end.y) - top,
        )

    def intersects(self, other: Segment) -> bool:
        """Do the two segments share at least one point?

        Includes touching at an endpoint and collinear overlap, because a
        goal is "my edge reaches this line", and an edge that lands exactly
        on the line has reached it.
        """

        return _segments_intersect(self.start, self.end, other.start, other.end)


class Edge(enum.Enum):
    """A named side of a rectangle.

    A segment goal names *which* edges may satisfy it, never "any edge": the
    caller who wants to stand to the left of a doorway and face right cares
    that its **right** edge is what touches the threshold. Reaching the same
    line with the left edge means having walked past it.
    """

    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"

    @property
    def is_horizontal(self) -> bool:
        """Does this edge run along the x axis? (``TOP``/``BOTTOM``.)"""

        return self in (Edge.TOP, Edge.BOTTOM)

    @property
    def opposite(self) -> Edge:
        return _OPPOSITE_EDGES[self]


_OPPOSITE_EDGES = {
    Edge.LEFT: Edge.RIGHT,
    Edge.RIGHT: Edge.LEFT,
    Edge.TOP: Edge.BOTTOM,
    Edge.BOTTOM: Edge.TOP,
}

# The two edges that run along x, and the two that run along y. Named so a
# caller can say "the horizontal edges must meet" in those words.
HORIZONTAL_EDGES: frozenset[Edge] = frozenset({Edge.TOP, Edge.BOTTOM})
VERTICAL_EDGES: frozenset[Edge] = frozenset({Edge.LEFT, Edge.RIGHT})


class Direction(enum.Enum):
    """One of the eight unit directions a step may take.

    The values are the unit offsets, with ``UP`` towards smaller y.
    """

    RIGHT = (1, 0)
    LEFT = (-1, 0)
    UP = (0, -1)
    DOWN = (0, 1)
    UP_RIGHT = (1, -1)
    UP_LEFT = (-1, -1)
    DOWN_RIGHT = (1, 1)
    DOWN_LEFT = (-1, 1)

    @property
    def dx(self) -> int:
        return self.value[0]

    @property
    def dy(self) -> int:
        return self.value[1]

    @property
    def is_diagonal(self) -> bool:
        return self.dx != 0 and self.dy != 0


CARDINALS: tuple[Direction, ...] = (
    Direction.RIGHT,
    Direction.LEFT,
    Direction.UP,
    Direction.DOWN,
)

DIAGONALS: tuple[Direction, ...] = (
    Direction.UP_RIGHT,
    Direction.UP_LEFT,
    Direction.DOWN_RIGHT,
    Direction.DOWN_LEFT,
)

ALL_DIRECTIONS: tuple[Direction, ...] = CARDINALS + DIAGONALS

_BY_OFFSET = {direction.value: direction for direction in ALL_DIRECTIONS}


def direction_from_offset(dx: int, dy: int) -> Direction:
    """The direction of a non-zero step, normalised to unit offsets."""

    key = (_sign(dx), _sign(dy))
    if key == (0, 0):
        raise ValueError("a step has no direction")
    return _BY_OFFSET[key]


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle, anchored at its top-left corner."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError("a rectangle cannot have negative extent")

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    def moved_by(self, dx: float, dy: float) -> Rect:
        return Rect(self.x + dx, self.y + dy, self.width, self.height)

    def moved_to(self, x: float, y: float) -> Rect:
        return Rect(x, y, self.width, self.height)

    def grown_by(self, margin: float) -> Rect:
        """The same rectangle expanded by ``margin`` on every side."""

        return Rect(
            self.x - margin,
            self.y - margin,
            self.width + 2 * margin,
            self.height + 2 * margin,
        )

    def edge(self, edge: Edge) -> Segment:
        """One side of the rectangle as a segment, clockwise from its start."""

        if edge is Edge.LEFT:
            return Segment(Point(self.left, self.top), Point(self.left, self.bottom))
        if edge is Edge.RIGHT:
            return Segment(Point(self.right, self.top), Point(self.right, self.bottom))
        if edge is Edge.TOP:
            return Segment(Point(self.left, self.top), Point(self.right, self.top))
        return Segment(Point(self.left, self.bottom), Point(self.right, self.bottom))

    def overlaps(self, other: Rect) -> bool:
        """Do the two rectangles share a strictly positive area?

        Flush contact returns ``False`` -- see the module docstring.
        """

        return (
            self.left < other.right - EPS
            and other.left < self.right - EPS
            and self.top < other.bottom - EPS
            and other.top < self.bottom - EPS
        )

    def contains(self, other: Rect) -> bool:
        """Is ``other`` entirely inside this rectangle (touching allowed)?"""

        return (
            other.left >= self.left - EPS
            and other.right <= self.right + EPS
            and other.top >= self.top - EPS
            and other.bottom <= self.bottom + EPS
        )

    def contains_point(self, point: Point) -> bool:
        """Is the point inside or on the border of this rectangle?"""

        return (
            self.left - EPS <= point.x <= self.right + EPS
            and self.top - EPS <= point.y <= self.bottom + EPS
        )

    def union(self, other: Rect) -> Rect:
        """The smallest rectangle covering both.

        Used as the swept volume of an axis-aligned move: a rectangle sliding
        along one axis covers exactly the union of where it started and where
        it stopped, which is what stops a step from tunnelling through an
        obstacle thinner than the step itself.
        """

        left = min(self.left, other.left)
        top = min(self.top, other.top)
        return Rect(
            left,
            top,
            max(self.right, other.right) - left,
            max(self.bottom, other.bottom) - top,
        )

    def gap_to(self, other: Rect) -> tuple[float, float]:
        """Per-axis distance that would have to be travelled to touch ``other``.

        Zero on an axis whose spans already overlap. This is the raw material
        of the search heuristic: it is a *lower* bound on the translation any
        route needs, so a heuristic built from it never overestimates.
        """

        dx = max(0.0, other.left - self.right, self.left - other.right)
        dy = max(0.0, other.top - self.bottom, self.top - other.bottom)
        return dx, dy


def contact_length(a: Segment, b: Segment) -> float | None:
    """How much of the two edges lie against each other, in px.

    ``None`` when the question does not apply -- an oblique segment, or two
    perpendicular edges, meet at a point wherever they meet at all, so there
    is no length to measure and nothing to prefer. Callers treat that as
    "unlimited contact" rather than "no contact", so a contact requirement
    never silently makes such a goal unreachable.
    """

    if a.axis is None or a.axis != b.axis:
        return None
    return a.collinear_overlap(b)


def contact_shortfall(a: Segment, b: Segment) -> float:
    """How much of the shorter edge fails to lie against the other, in px.

    Zero when the shorter of the two is entirely covered by the longer --
    the "fully lined up" case -- and zero, too, when the pair has no length
    to measure. Touching corner to corner scores the full length of the
    shorter edge: the worst contact that still counts as contact at all, and
    exactly the outcome ``maximize_contact`` exists to walk away from.
    """

    overlap = contact_length(a, b)
    if overlap is None:
        return 0.0
    return max(0.0, min(a.length, b.length) - overlap)


def octile_distance(dx: float, dy: float) -> float:
    """Cheapest 8-direction travel distance covering the offsets ``dx``/``dy``.

    With diagonal moves costing their true euclidean length, this is exactly
    the cost of the best obstacle-free route, which makes it both admissible
    and consistent as an A* heuristic -- straight-line distance would also be
    admissible but is a weaker bound and expands more nodes.
    """

    dx, dy = abs(dx), abs(dy)
    low, high = (dx, dy) if dx < dy else (dy, dx)
    return math.sqrt(2.0) * low + (high - low)


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _orientation(a: Point, b: Point, c: Point) -> int:
    cross = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
    if cross > EPS:
        return 1
    if cross < -EPS:
        return -1
    return 0


def _on_segment(a: Point, b: Point, p: Point) -> bool:
    """Is ``p``, known to be collinear with ``ab``, inside that span?"""

    return (
        min(a.x, b.x) - EPS <= p.x <= max(a.x, b.x) + EPS
        and min(a.y, b.y) - EPS <= p.y <= max(a.y, b.y) + EPS
    )


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)

    if o1 != o2 and o3 != o4:
        return True

    # Collinear or touching cases: a shared endpoint, a point lying on the
    # other segment, or an overlapping stretch of the same line.
    if o1 == 0 and _on_segment(a, b, c):
        return True
    if o2 == 0 and _on_segment(a, b, d):
        return True
    if o3 == 0 and _on_segment(c, d, a):
        return True
    if o4 == 0 and _on_segment(c, d, b):
        return True
    return False
