"""What counts as "arrived".

Two kinds of destination, because navigation asks two different questions.
"Stand on that spot" is a *point*: the moving rectangle has arrived once it
covers the point. "Get to the far side of this line" is a *segment*, and
there the useful test is not proximity but which side of the body touches
it -- walking up to a threshold with your right edge and walking through it
until your left edge touches are opposite outcomes from the same line. So a
segment goal names the edges that may satisfy it, and only those.

Both kinds also answer ``bounding_box``, which the search uses purely as a
lower bound for its heuristic. A goal never has to be reachable, or even
inside the world.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .geometry import Edge, Point, Rect, Segment


@runtime_checkable
class Goal(Protocol):
    """Anything the search can aim at."""

    def is_reached(self, rect: Rect) -> bool:
        """Has a body at ``rect`` arrived?"""

    def bounding_box(self) -> Rect:
        """A rectangle the goal lies within, for the heuristic's lower bound."""


@dataclass(frozen=True)
class PointGoal:
    """Reached when the moving rectangle covers ``point``.

    Covering, not centring: a body cannot generally land its centre on an
    arbitrary point when every step is a multiple of the step length, and
    "I am standing on it" is what callers actually mean. ``tolerance``
    widens the body for the test only -- it never lets it pass an obstacle.
    """

    point: Point
    tolerance: float = 0.0

    def is_reached(self, rect: Rect) -> bool:
        target = rect.grown_by(self.tolerance) if self.tolerance else rect
        return target.contains_point(self.point)

    def bounding_box(self) -> Rect:
        return Rect(self.point.x, self.point.y, 0.0, 0.0).grown_by(self.tolerance)


@dataclass(frozen=True)
class SegmentGoal:
    """Reached when one of ``edges`` of the moving rectangle meets ``segment``.

    A body that swallows the segment whole -- segment strictly inside the
    rectangle, no edge crossing it -- has *not* reached this goal. That is
    deliberate: the edge is the point of the test, and a goal small enough to
    fit inside the body wants to be a :class:`PointGoal` instead.
    """

    segment: Segment
    edges: frozenset[Edge] = field(default_factory=lambda: frozenset(Edge))

    def __post_init__(self) -> None:
        if not self.edges:
            raise ValueError("a segment goal needs at least one edge to be reached by")

    @classmethod
    def of(cls, segment: Segment, edges: Iterable[Edge]) -> SegmentGoal:
        """Build one from any iterable of edges, so callers need no frozenset."""

        return cls(segment, frozenset(edges))

    def is_reached(self, rect: Rect) -> bool:
        return any(rect.edge(edge).intersects(self.segment) for edge in self.edges)

    def bounding_box(self) -> Rect:
        return self.segment.bounds
