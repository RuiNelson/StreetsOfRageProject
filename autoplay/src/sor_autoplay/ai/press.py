"""Round 6's drop press (type ``$42``): when it falls, and where it hurts.

Read off the disassembly (``sub_00007A6C``, whose state table is ``$7A7C``)
and checked against live traces (``tools/stage_walk_diag.py --level 6``): six
presses stand on lane 112 -- the bottom of the street -- at X 1832, 2632,
3688, 4520, 4776 and 4904, each at z ``$40``, 96 px over the floor.

- **Armed** (state 1, ``$7AA4``) until a player's X is in ``(x - $30, x +
  $60]`` -- either player, on any lane.
- **Shaking** (2, ``$7ADE``) for 11 updates.
- **Falling** (3, ``$7B48``): 2 px an update, half a pixel more every
  update, and on every one of them it tests two attack boxes against both
  players (``sub_00007BCE`` with ``+$2`` = ``$F4``, then ``$EA``): 20 damage
  (``+$34`` = ``$14``, ``$7A8E``) and a knockdown. Each box is 16 px tall at
  the press's own height, so it meets a standing body only under z ~112 --
  about the last 6 of the 16 updates the fall takes.
- **Down, rising, up** (4-7: four bounces, 50 updates, the climb back, 50
  more), then armed again (8 -> 1). None of these test contact: for ~8 s the
  ground is free.

The boxes are not under the press. ``$EA`` reaches 48 px behind it and 12 to
48 lanes *above* it, ``$F4`` 16 to 56 px ahead and from 8 lanes above to 40
below. With the press on the bottom lane, ``$EA`` is the one a walk along the
street meets: both live hits in the trace were it (x 1811 lane 71 under the
press at 1832, x 4503 lane 87 under 4520).

So its ground is not stood on from the moment the press is committed --
shaking, falling, or armed with a player already inside its window -- until
it lands: a wall to the router (``navigation.press_obstacles``), and a zone
to walk out of when the actor is already in it (``execute._press_escape_mask``).
Armed with nobody in the window it is left alone on purpose: the window
starts exactly where ``$EA`` does, so an actor kept out of the zone before it
drops would never set it off, and the walk would wait on it forever.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from .pathfind import Rect
from .tokens import Context, Myself, Partner, Press, find_all

PRESS_TYPE = 0x42

STATE_ARMED = 1
STATE_SHAKING = 2
STATE_FALLING = 3

# $7AA4: d0 = x - $30 must be below the player's X, d0 + $90 at or above it.
TRIGGER_BEHIND_X = 0x30
TRIGGER_AHEAD_X = 0x60

# The two boxes the fall tests, (x0, x1, lane0, lane1) from the press's own
# position: shape records $F4 and $EA of $1A68E with their $1AB8E lane pairs.
DROP_BOXES: tuple[tuple[int, int, int, int], ...] = (
    (16, 56, -8, 40),  # $F4
    (-48, 0, -48, -12),  # $EA
)

# Room past the boxes for the update between two observations: a walk covers
# up to 3.25 px on X and 2.375 on the lane in one.
ZONE_MARGIN_X = 4
ZONE_MARGIN_Y = 3

# The directions an escape may walk, straight ones first: on a tie the step
# that keeps to one axis is the one that does not wander into the other box.
_ESCAPE_STEPS: tuple[tuple[int, int], ...] = (
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),
    (-1, -1),
    (1, -1),
    (-1, 1),
    (1, 1),
)
# Longer than any zone takes to leave at the slowest walk (Adam's 1.5 px of
# lane an update, across a zone 42 lanes deep).
ESCAPE_HORIZON_UPDATES = 40


def in_trigger_window(press: Press, world_x: float) -> bool:
    """Would a player standing at ``world_x`` set this press off (``$7AA4``)?"""

    return press.world_x - TRIGGER_BEHIND_X < world_x <= press.world_x + TRIGGER_AHEAD_X


def is_committed(press: Press, player_xs: Iterable[float]) -> bool:
    """Will this press fall before anyone could walk under it and out again?"""

    if press.state in (STATE_SHAKING, STATE_FALLING):
        return True
    return press.state == STATE_ARMED and any(in_trigger_window(press, x) for x in player_xs)


def drop_zones(press: Press) -> tuple[Rect, ...]:
    """The ground the fall's boxes cover, grown by the margins.

    A body test, like the ROM's: ``$AB88`` overlaps the press's box with the
    player's own body box, so a body overlapping one of these is a hit.
    """

    return tuple(
        Rect(
            press.world_x + x0 - ZONE_MARGIN_X,
            press.world_y + y0 - ZONE_MARGIN_Y,
            (x1 - x0) + 2 * ZONE_MARGIN_X,
            (y1 - y0) + 2 * ZONE_MARGIN_Y,
        )
        for x0, x1, y0, y1 in DROP_BOXES
    )


def lands_in_reach(context: Context, body: Rect) -> bool:
    """Would ``body``, set down here, stand in a live press's drop zone?

    For moves that put the actor somewhere and keep it there -- a jump's
    landing, a hold's crossover -- so armed counts as well as committed: the
    window starts where ``$EA`` does, a landing inside the zone sets the
    press off, and the actor is still locked in the move when it comes down.
    Measured live: knee, knee, then the crossover carried a hold on a Jack
    from x 4452 to 4508, under the press at 4520; the back hold and the
    release held the actor there until the box landed.
    """

    return any(
        body.overlaps(zone)
        for press in find_all(context, Press)
        if press.state in (STATE_ARMED, STATE_SHAKING, STATE_FALLING)
        for zone in drop_zones(press)
    )


def committed_zones(context: Context) -> list[Rect]:
    """Every committed press's drop zones -- the players' X being what arms one."""

    xs = [player.world_x for player in (*find_all(context, Myself), *find_all(context, Partner))]
    return [
        zone
        for press in find_all(context, Press)
        if is_committed(press, xs)
        for zone in drop_zones(press)
    ]


def escape_step(
    body: Rect,
    origin: tuple[float, float],
    zones: Sequence[Rect],
    *,
    speeds: tuple[float, float, float, float],
    constrain: Callable[[float, float, float], tuple[float, float] | None],
    horizon: int = ESCAPE_HORIZON_UPDATES,
) -> tuple[int, int]:
    """The walk that takes ``body`` clear of every zone in the fewest updates.

    Each of the eight directions is walked forward update by update at the
    character's own speeds (``kinematics.walk_speeds``: straight X, diagonal
    X, diagonal lane, straight lane), with ``constrain(x, lane, vel_x)``
    playing what the ROM does to the step: the new origin, clamped to the
    lane band and the camera, or ``None`` when a wall or a pit undoes it (the
    origin stays put). The first direction to clear wins, straight before
    diagonal on a tie; when none clears inside the horizon, the one that ends
    overlapping least.

    Returns ``(step_x, step_y)``, each -1, 0 or +1 (+1 on the lane is down).
    """

    x0, y0 = origin
    straight_x, diagonal_x, diagonal_y, straight_y = speeds
    best: tuple[float, int, tuple[int, int]] | None = None
    for order, (step_x, step_y) in enumerate(_ESCAPE_STEPS):
        vx = step_x * (diagonal_x if step_y else straight_x)
        vy = step_y * (diagonal_y if step_x else straight_y)
        x, y = x0, y0
        score: float | None = None
        for update in range(1, horizon + 1):
            moved = constrain(x + vx, y + vy, vx)
            if moved is not None:
                x, y = moved
            if not any(body.moved_by(x - x0, y - y0).overlaps(zone) for zone in zones):
                score = update
                break
        if score is None:
            # Never clear: after every direction that is, by what is left.
            score = horizon + _overlap_area(body.moved_by(x - x0, y - y0), zones)
        if best is None or (score, order) < (best[0], best[1]):
            best = (score, order, (step_x, step_y))
    assert best is not None
    return best[2]


def _overlap_area(body: Rect, zones: Sequence[Rect]) -> float:
    total = 0.0
    for zone in zones:
        width = min(body.right, zone.right) - max(body.left, zone.left)
        height = min(body.bottom, zone.bottom) - max(body.top, zone.top)
        if width > 0 and height > 0:
            total += width * height
    return total
