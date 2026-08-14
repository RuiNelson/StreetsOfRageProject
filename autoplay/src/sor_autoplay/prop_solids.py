"""The push-back rectangle a solid prop stands behind (``$3C6A``).

A breakable is not merely a sprite the AI should avoid overlapping. The ROM
gives every solid prop an explicit rectangle that no moving object's **own
position** may end up inside, and that rectangle is not the prop's animation
body box.

``sub_00003B8A`` walks the object table once per moving object, skipping any
slot without bit 0 of ``+$3A`` (the solid flag -- set on every intact
breakable sampled live), and ``sub_00003BAE`` runs the test::

    d0 = mover.x    (+$10)        ; the mover's own position: a *point*,
    d1 = mover.lane (+$14)        ; never its body box
    x0 = prop.x    + rec[0];  x1 = x0 + rec[1]
    y0 = prop.lane + rec[2];  y1 = y0 + rec[3]
    blocked  <=>  x0 < d0 < x1  and  y0 < d1 < y1

A blocked mover has that frame's whole displacement (``+$1C`` on x, ``+$20``
on lane) subtracted straight back off again, which is why walking into one
looks like the actor simply stopping.

``rec`` comes from the five-record table at ``$3C6A``, selected by the
compare chain at ``$3BC4``-``$3C00`` on the prop's *type*. That chain falls
through to the last record for every type it does not name.

Two consequences, and the AI had both wrong before this module existed.

**The solid is not the sprite.** A round-5 prop (``$1F``) at lane 96 carries
its animation body box at lane 86..106 -- in *front* of its origin -- while
the rectangle that actually stops a walking player is lane 76..100, twenty
pixels *behind* it. Planning around the sprite box therefore routes straight
through solid ground. Measured live on stage 5: the actor walked into the
prop fence, held DOWN against it and did not move again for the remaining 90
seconds of the run.

**The test is against a point.** So what a body-collision path finder needs
is this rectangle shrunk by the body, exactly the way
``navigation.solid_obstacles`` already shrinks a pit -- never the rectangle
itself.

Verified live against stage 5's 2x2 fence (props at lane 56 and lane 96, one
column): from the corridor between them, holding UP stops the player at lane
60 (``56 + 4``, the predicted edge exactly) and holding DOWN stops it at lane
75, one walk step short of the predicted 76.
"""

from __future__ import annotations

from dataclasses import dataclass

# Where the records live, for anyone re-reading the evidence.
ROM_PROP_SOLID_TABLE = 0x003C6A
PROP_SOLID_RECORD_BYTES = 8

# (dx0, width, dy0, height) per record, in table order, transcribed from the
# ROM. Every one of them ends 4px *past* the prop's own lane origin: a prop
# is solid behind its feet and walkable in front of them.
_RECORDS: tuple[tuple[int, int, int, int], ...] = (
    (-28, 56, -10, 14),
    (-28, 56, -16, 20),
    (-30, 60, -28, 32),
    (-30, 60, -20, 24),
    (-36, 72, -20, 24),
)

# The compare chain's own answers. Types it never names -- and there are
# solid ones, e.g. the round-4 props -- reach the table with the last record
# still selected, so that is the default rather than an error case.
_RECORD_BY_TYPE: dict[int, int] = {
    0x11: 0,  # phone booth
    0x19: 0,  # crate
    0x18: 1,  # round-3 prop
    0x1D: 2,
    0x1F: 3,  # round-5 prop
    0x41: 4,  # round-6 prop
}
DEFAULT_RECORD = len(_RECORDS) - 1


@dataclass(frozen=True, slots=True)
class SolidBox:
    """One prop's push-back rectangle, in absolute world coordinates.

    ``y`` is the lane axis, as everywhere else in this package. There is no
    height axis: ``sub_00003BAE`` tests x and lane only.
    """

    x0: int
    x1: int
    y0: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    def blocks(self, world_x: float, lane_y: float) -> bool:
        """Would a mover standing here have its movement undone?

        Strict on every edge, matching the two ``bcc`` exits per axis: a
        position exactly on an edge is clear.
        """

        return self.x0 < world_x < self.x1 and self.y0 < lane_y < self.y1


def record_for_type(type_id: int) -> tuple[int, int, int, int]:
    """The table record ``sub_00003BAE``'s compare chain would select."""

    return _RECORDS[_RECORD_BY_TYPE.get(type_id, DEFAULT_RECORD)]


def solid_box(type_id: int, world_x: int, lane_y: int) -> SolidBox:
    """The push-back rectangle for a prop of ``type_id`` standing there."""

    dx0, width, dy0, height = record_for_type(type_id)
    x0 = world_x + dx0
    y0 = lane_y + dy0
    return SolidBox(x0=x0, x1=x0 + width, y0=y0, y1=y0 + height)


def solid_half_width(type_id: int) -> int:
    """How far from a prop's origin its wall reaches on x.

    The records are symmetric on x (``dx0 == -width / 2``), so this is the
    single number every "how close can the actor get" question needs.
    """

    _, width, _, _ = record_for_type(type_id)
    return width // 2
