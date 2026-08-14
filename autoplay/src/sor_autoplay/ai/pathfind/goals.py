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

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .geometry import (
    HORIZONTAL_EDGES,
    VERTICAL_EDGES,
    Edge,
    Point,
    Rect,
    Segment,
    contact_length,
    contact_shortfall,
)


@runtime_checkable
class Goal(Protocol):
    """Anything the search can aim at."""

    def is_reached(self, rect: Rect) -> bool:
        """Has a body at ``rect`` arrived?"""

    def bounding_box(self) -> Rect:
        """A rectangle the goal lies within, for the heuristic's lower bound."""

    def contact(self, rect: Rect) -> float:
        """How much edge an *arrived* body actually shares with the goal, in px.

        ``math.inf`` when the goal has no measurable contact -- covering a
        point, or meeting an oblique line -- so that a caller's
        ``enough_contact`` requirement passes rather than making such a goal
        permanently unreachable.
        """

    def misalignment(self, rect: Rect) -> float:
        """How badly an *arrived* body is lined up, in px, 0 being perfect.

        Arrival is a yes/no question, but not every arrival is as good as
        every other: an edge that meets its counterpart corner to corner has
        technically arrived and is useless in practice. This grades the ones
        that qualify, and ``find_path``'s ``maximize_contact`` decides
        whether extra walking may be spent improving it.

        Only ever called on a rectangle that :meth:`is_reached` accepted.
        """


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

    def contact(self, rect: Rect) -> float:
        """Not applicable: a point has no edge to share."""

        return math.inf

    def misalignment(self, rect: Rect) -> float:
        """Always 0: covering a point has no better or worse way of doing it."""

        return 0.0


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

    def _touching(self, rect: Rect) -> list[Segment]:
        return [
            rect.edge(edge)
            for edge in self.edges
            if rect.edge(edge).intersects(self.segment)
        ]

    def contact(self, rect: Rect) -> float:
        """The most edge any arriving side shares with the segment."""

        lengths = [
            length
            for edge in self._touching(rect)
            if (length := contact_length(edge, self.segment)) is not None
        ]
        return max(lengths, default=math.inf)

    def misalignment(self, rect: Rect) -> float:
        """The best (smallest) shortfall among the edges that have arrived.

        Zero for an oblique segment: an axis-aligned edge crossing a diagonal
        line touches it at a point no matter where along it the body stands,
        so there is nothing to prefer.
        """

        return min(
            (contact_shortfall(edge, self.segment) for edge in self._touching(rect)),
            default=0.0,
        )


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

    def _touching(self, rect: Rect) -> list[tuple[Segment, Segment]]:
        pairs = []
        for own, other in self.contacts:
            mine, theirs = rect.edge(own), self.target.edge(other)
            if mine.intersects(theirs):
                pairs.append((mine, theirs))
        return pairs

    def contact(self, rect: Rect) -> float:
        """The most edge any met pairing actually shares."""

        lengths = [
            length
            for mine, theirs in self._touching(rect)
            if (length := contact_length(mine, theirs)) is not None
        ]
        return max(lengths, default=math.inf)

    def misalignment(self, rect: Rect) -> float:
        """The best (smallest) shortfall among the pairings that have met.

        Two boxes stacked but barely overlapping score their whole shared
        width here; slid until the narrower one sits entirely over the other,
        they score 0.
        """

        return min(
            (contact_shortfall(mine, theirs) for mine, theirs in self._touching(rect)),
            default=0.0,
        )


__all__ = [
    "Goal",
    "HORIZONTAL_EDGES",
    "PointGoal",
    "RectGoal",
    "SegmentGoal",
    "VERTICAL_EDGES",
]
