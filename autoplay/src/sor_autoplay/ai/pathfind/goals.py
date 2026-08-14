"""What counts as "arrived".

Three kinds of destination, because navigation asks three different
questions.

"Stand on that spot" is a *point*: the moving rectangle has arrived once it
covers the point. "Get to the far side of this line" is a *segment*, and
there the useful test is not proximity but which side of the body touches
it -- walking up to a threshold with your right edge and walking through it
until your left edge touches are opposite outcomes from the same line. So a
segment goal names the edges that may satisfy it, and only those.

"Get to that box" is a *rectangle*, and it is the same question as the
segment one asked about both bodies at once: not "how near", but **which of
my edges must meet which of its edges**. A body that has to line up its
bottom edge with a crate's top edge is not served by a distance test -- it
would report success from beside the crate, at zero distance, in exactly the
position that cannot act on it. So :class:`RectGoal` is defined by *pairs*
of edges, and :meth:`RectGoal.horizontal` / :meth:`RectGoal.vertical` name
the two pairings that are almost always the ones wanted: the facing pairs
(my bottom to its top, or my top to its bottom) rather than the aligned ones
(my top to its top), which two same-height boxes satisfy simply by standing
side by side.

A rectangle goal says nothing about *not overlapping* the target -- that is
a collision question, and the answer is to pass the same rectangle in
``obstacles`` as well. The two compose exactly: the body is then stopped
flush against the target, which is the position where the edges meet.

All three kinds also answer ``bounding_box``, which the search uses purely
as a lower bound for its heuristic. A goal never has to be reachable, or
even inside the world.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .geometry import HORIZONTAL_EDGES, VERTICAL_EDGES, Edge, Point, Rect, Segment


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


@dataclass(frozen=True)
class RectGoal:
    """Reached when a named edge of the body meets a named edge of ``target``.

    ``contacts`` holds ``(own_edge, target_edge)`` pairs, and *any* one of
    them satisfying the goal is enough. "Meeting" is segment intersection, so
    two collinear edges whose spans overlap have met -- which is what makes
    the flush position, the one where the body stops against the target as an
    obstacle, count as arrival rather than as one pixel short of it.

    Build it with :meth:`horizontal`, :meth:`vertical` or :meth:`of` rather
    than by listing pairs by hand; the constructor stays open for the cases
    those three do not cover.
    """

    target: Rect
    contacts: frozenset[tuple[Edge, Edge]]

    def __post_init__(self) -> None:
        if not self.contacts:
            raise ValueError("a rectangle goal needs at least one pair of edges")

    @classmethod
    def of(
        cls,
        target: Rect,
        own_edges: Iterable[Edge],
        target_edges: Iterable[Edge],
    ) -> RectGoal:
        """Every pairing of an own edge with a target edge.

        Explicit and unsurprising, but note that a cross product includes the
        *aligned* pairings (own top with target top), which same-height boxes
        satisfy just by standing side by side. When the intent is "the boxes
        must be stacked", :meth:`horizontal` is the one that says it.
        """

        pairs = {(own, other) for own in own_edges for other in target_edges}
        return cls(target, frozenset(pairs))

    @classmethod
    def horizontal(cls, target: Rect) -> RectGoal:
        """Reached when the boxes are stacked: the horizontal edges meet.

        Either way round -- the body's bottom on the target's top, or its top
        on the target's bottom -- so the search is free to approach from
        whichever side is cheaper. Pass ``target`` in ``obstacles`` too if the
        body must stop *against* it rather than be free to pass through.
        """

        return cls(target, frozenset({(Edge.BOTTOM, Edge.TOP), (Edge.TOP, Edge.BOTTOM)}))

    @classmethod
    def vertical(cls, target: Rect) -> RectGoal:
        """Reached when the boxes are side by side: the vertical edges meet."""

        return cls(target, frozenset({(Edge.RIGHT, Edge.LEFT), (Edge.LEFT, Edge.RIGHT)}))

    @property
    def own_edges(self) -> frozenset[Edge]:
        """The body edges any pairing may be satisfied by."""

        return frozenset(own for own, _ in self.contacts)

    def is_reached(self, rect: Rect) -> bool:
        return any(
            rect.edge(own).intersects(self.target.edge(other))
            for own, other in self.contacts
        )

    def bounding_box(self) -> Rect:
        return self.target


__all__ = [
    "Goal",
    "HORIZONTAL_EDGES",
    "PointGoal",
    "RectGoal",
    "SegmentGoal",
    "VERTICAL_EDGES",
]
