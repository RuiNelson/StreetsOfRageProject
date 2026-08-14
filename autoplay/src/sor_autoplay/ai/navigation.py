"""Where the AI's world meets the path finder.

``pathfind/`` knows about rectangles and nothing else -- deliberately, so it
can be tested exhaustively without a running ``sor``. This module is the
only place that turns *this game* into that vocabulary: tokens in,
rectangles out, a route back. It reads no RAM, touches no gamepad and emits
no tokens; ``execute.py`` owns the controller, and everything here is a pure
function of an already-built ``Context``.

Three things it decides.

**What is solid.** Breakables and pits are real geometry -- walking into one
is a wall or a fall. Enemies and the bands they swing through are *danger*,
which is different: a screen full of enemies would make every destination
unreachable if their reach were treated as concrete. So a route is planned
twice, danger first, solids alone as the fallback (see :func:`plan_route`).

**Where "arrived" is.** Every reach predicate downstream (``reach.in_punch_
band``, ``decide.in_smash_range``) compares *origin distances*, not edges, so
:func:`strike_goal` builds a goal rectangle whose edge contact means exactly
the same thing. That construction is what gives ``enough_contact`` and
``maximize_contact`` their meaning here: the contact length of those edges
*is* the lane alignment of the strike, so "at least 4px of contact" reads as
"the punch actually lands" and "maximise contact" as "line up square with
the crate's face".

**Nothing about tactics.** Which side to approach from, how far to stop
short, whether to wait out a swing -- those stay in ``execute.py``, where
they were each measured into existence. This module answers only "how do I
get from here to there without walking into anything".
"""

from __future__ import annotations

from collections.abc import Sequence

from .pathfind import (
    Direction,
    Goal,
    Path,
    Point,
    PointGoal,
    Rect,
    RegionGoal,
    find_path,
)
from .reach import PIT_AVOID_MARGIN, live_enemies
from .tokens import (
    Breakable,
    CameraRange,
    Context,
    Enemy,
    Myself,
    Partner,
    Pit,
    Stage,
    find,
    find_all,
)
from ..hitboxes import Hitbox
from ..phases import is_dangerous
from ..world_map import LANE_Y_MAX_DEFAULT, LANE_Y_MIN, lane_y_max_for_level

# The minimum length of every planned vector, in px, and so the spacing of
# the positions a route may stop at. Ground walk is a couple of px per 60 Hz
# frame and the default poll is ~2 frames, so 4px is about one tick of
# walking -- the finest granularity that still means something to a
# controller sampled this slowly.
#
# It is deliberately finer than the executor's deadbands (MOVE_DEADBAND_X is
# 5). The pockets this has to land in are small: the ground where a punch
# reaches a crate but the body is not inside it is about 10px deep, and a
# lattice too coarse to have a position inside such a pocket does not steer
# badly -- it reports the goal unreachable and the actor stops short of a
# target it could hit.
NAV_STEP = 4

# A bound on how much lattice one tick may explore. The playable band is
# about 320x112 px, so at NAV_STEP that is under 600 positions and this is
# never reached in practice -- it exists so a pathological arrangement costs
# a worse route rather than a missed tick.
NAV_MAX_NODES = 4000

# Body box used when the actor's real one is unknown (`hitbox` is None on a
# no-attack frame with a degenerate cached box). "Unknown" is not "no body":
# planning as a point would route the actor through gaps it cannot fit.
# Roughly a character's measured footprint.
NOMINAL_BODY_W = 16
NOMINAL_BODY_H = 16

# How much of the strike's lane slack must be left over on arrival for the
# blow to be worth throwing, in px. Zero would accept a corner touch -- the
# exact lane offset at which the attack box stops covering the target body.
MIN_STRIKE_CONTACT_Y = 4

# How far past the camera edge a route may be planned. The camera is what is
# reachable *now*; a little slack ahead lets a walk aim at something entering
# the screen without the world clipping the goal away.
WORLD_MARGIN_X = 32


def _rect_from_hitbox(box: Hitbox) -> Rect:
    """The lane-plane footprint of a ROM box (``z`` is height, not depth)."""

    return Rect(box.x0, box.y0, box.x1 - box.x0, box.y1 - box.y0)


def _centred(world_x: float, world_y: float, width: int, height: int) -> Rect:
    return Rect(world_x - width / 2, world_y - height / 2, width, height)


def body_rect(actor: Myself | Partner) -> Rect:
    """The actor's own footprint, as the path finder's moving rectangle."""

    box = actor.hitbox
    if box is not None and not box.is_degenerate:
        return _rect_from_hitbox(box)
    return _centred(actor.world_x, actor.world_y, NOMINAL_BODY_W, NOMINAL_BODY_H)


def lane_bounds(context: Context) -> tuple[float, float]:
    """The level's walkable lane band -- the same one ``reach`` judges by."""

    stage = find(context, Stage)
    lane_max = (
        lane_y_max_for_level(stage.level_index)
        if stage is not None
        else LANE_Y_MAX_DEFAULT
    )
    return float(LANE_Y_MIN), float(lane_max)


def world_rect(context: Context) -> Rect:
    """The rectangle a route may be planned inside.

    Vertically the level's own lane band. Horizontally the camera, which is
    what the actor can actually reach right now -- ``world_map`` tracks
    entities up to two screens past each edge, and planning across all of
    that would route around things that are not on screen.
    """

    lo, hi = lane_bounds(context)
    camera = find(context, CameraRange)
    if camera is None:
        # No camera token: plan in the lane band alone, wide enough that the
        # bounds never clip a goal. Better an unbounded X than a guessed one.
        return Rect(-1e6, lo, 2e6, hi - lo)
    left = camera.left - WORLD_MARGIN_X
    return Rect(left, lo, (camera.right + WORLD_MARGIN_X) - left, hi - lo)


def _breakable_rect(
    prop: Breakable, block_x: int, keep_reachable_within: int | None
) -> Rect:
    box = prop.hitbox
    if box is not None and not box.is_degenerate:
        return _rect_from_hitbox(box)
    # No observed footprint: the margin decide.py already names for this,
    # around the origin, with a nominal lane depth so it is a rectangle and
    # not a line.
    #
    # That margin is a deliberately generous *guess*, and pairing a generous
    # guess with a measured strike range can close the gap between them
    # entirely: 28px of assumed body plus half a 16px actor is exactly the
    # 36px a punch reaches, leaving a pocket one pixel deep that no lattice
    # will ever land in -- the actor then walks up to a crate it is allowed
    # to hit, is told the goal is unreachable, and stops. So an *assumed*
    # footprint is never allowed to be wider than the reach it would have to
    # be hit from. A real, observed hitbox is left alone: if the ROM says the
    # box is that big, it is that big.
    if keep_reachable_within is not None:
        block_x = min(
            block_x,
            max(1, keep_reachable_within - int(NOMINAL_BODY_W / 2) - NAV_STEP),
        )
    return Rect(
        prop.world_x - block_x,
        prop.world_y - NOMINAL_BODY_H / 2,
        2 * block_x,
        NOMINAL_BODY_H,
    )


def solid_obstacles(
    context: Context,
    *,
    block_x: int,
    body: Rect | None = None,
    keep_reachable_within: int | None = None,
    ignore_slots: frozenset[str] = frozenset(),
) -> list[Rect]:
    """Geometry that is physically impassable: intact props and floor holes.

    A crate and a pit are not the same kind of obstacle, and modelling them
    alike is wrong in a way that costs whole approaches. A **crate** is a
    wall: it is the *body* that must not overlap it. A **pit** is a floor
    rule the ROM applies to the object's own position, and every other pit
    check in the AI agrees -- ``reach.pit_endangers`` tests a point against
    the hole plus ``PIT_AVOID_MARGIN``. Growing the hole by that margin and
    *also* colliding a 16px-tall body against it counts the clearance twice:
    an actor standing 2px clear of the danger band, which the rest of the
    pipeline calls safe, reads as already inside it here.

    Measured, on the sweep: the actor started legally beside a pit, this
    said it was standing in one, the route left the lane to escape a hole it
    was never in, and it spent the whole run walking back around instead of
    reaching the enemy it had been punching before. So a pit is inset by
    half the body, which makes "the body overlaps this" mean exactly "the
    origin is within the margin" -- the same sentence ``pit_endangers`` says.
    """

    rects: list[Rect] = []
    for prop in find_all(context, Breakable):
        if prop.slot in ignore_slots:
            continue
        rects.append(_breakable_rect(prop, block_x, keep_reachable_within))
    inset_x = body.width / 2 if body is not None else 0.0
    inset_y = body.height / 2 if body is not None else 0.0
    for pit in find_all(context, Pit):
        # One px wider than the predicate, because the predicate is inclusive
        # (``pit_endangers`` uses ``<=``) and collision here is not (touching
        # is clearance). Without it the two disagree about exactly the
        # boundary pixel, and the route is happy to stop on the one spot
        # ``_pit_escape_mask`` will immediately try to shove it off -- the
        # same one-pixel deadlock ``_straight_mask``'s own pit dodge carries
        # a comment about.
        danger = Rect(pit.world_x, pit.lane_y, pit.width, pit.height).grown_by(
            PIT_AVOID_MARGIN + 1
        )
        rects.append(
            Rect(
                danger.x + inset_x,
                danger.y + inset_y,
                max(0.0, danger.width - 2 * inset_x),
                max(0.0, danger.height - 2 * inset_y),
            )
        )
    return rects


def enemy_rects(enemy: Enemy) -> list[Rect]:
    """An enemy's body, and the bands it is swinging through *right now*.

    The body falls back to a nominal box when the ROM box could not be
    rebuilt -- an enemy whose footprint is unknown is still somewhere not to
    walk. The reaches are the real ones, projected onto the enemy's own
    facing (``AttackRange.projected``), so a right-facing enemy blocks the
    ground to its right and not behind it.

    A reach only counts while the enemy is actually committed
    (``phases.is_dangerous``). Every enemy on screen *could* swing, and
    treating that potential as a wall is how an AI ends up cowering: measured
    on the sweep, one idle enemy standing past a pit turned a 20-tick
    straight approach into a 60-tick detour up over the pit and back down,
    and cost every attack in the run. What an idle enemy's reach means is
    "it will hit you when you get close", which is a reason to attack it, not
    a wall to route around.
    """

    rects: list[Rect] = []
    box = enemy.hitbox
    if box is not None and not box.is_degenerate:
        rects.append(_rect_from_hitbox(box))
    else:
        rects.append(
            _centred(enemy.world_x, enemy.world_y, NOMINAL_BODY_W, NOMINAL_BODY_H)
        )
    if not is_dangerous(enemy.combat_phase):
        return rects
    for reach in enemy.attack_ranges:
        projected = reach.projected(
            world_x=enemy.world_x,
            lane_y=enemy.world_y,
            # Height is not part of the lane plane the route is planned in;
            # only x/lane are read back out.
            world_z=0,
            facing_left=enemy.facing_left,
        )
        if not projected.is_degenerate:
            rects.append(_rect_from_hitbox(projected))
    return rects


def danger_obstacles(
    context: Context,
    *,
    ignore_slots: frozenset[str] = frozenset(),
) -> list[Rect]:
    """Every live enemy's body and reach -- the ground worth not crossing."""

    rects: list[Rect] = []
    for enemy in live_enemies(context):
        if enemy.slot in ignore_slots:
            continue
        rects.extend(enemy_rects(enemy))
    return rects


def strike_goal(
    body: Rect,
    target_x: float,
    target_y: float,
    *,
    stop_dx: int,
    lane_slack: int,
    inner_dx: int = 0,
    side: str = "both",
) -> Goal:
    """Standing where a forward strike on ``target`` lands.

    A **region**, not a boundary, and that is the whole design. Every reach
    predicate in the AI compares ``abs(target.world_x - actor.world_x)``
    against a threshold, so the region is the target's own position inset by
    half the body on each axis: the body overlapping it is exactly "my
    *centre* is within ``stop_dx`` on x and ``lane_slack`` on lane of the
    target's origin", which is the sentence ``in_punch_band`` already says.
    An edge-contact goal would say the same thing about the boundary alone --
    ``|dx| == stop_dx`` to the pixel -- which a lattice of whole steps
    essentially never lands on, so every approach would come back as best
    effort.

    Stopping at the *cheapest* arrival is what keeps the actor out of the
    target's lap: coming from outside, the first lattice position that
    overlaps the region is the one at its far edge, the moment the strike is
    in range.

    Contact is the **lane** overlap, which is what decides whether the blow
    connects: it holds at its maximum while the body sits wholly inside the
    band, then falls off a px per px of drift, reaching 0 exactly at
    ``lane_slack``. So ``enough_contact`` reads as "px of lane margin to
    spare" and ``maximize_contact`` as "line up square with its face".

    ``inner_dx`` is the strike's own dead zone -- the ROM's attack boxes
    start a good way in front of the actor, so a body standing *on* the
    target cannot hit it. With one, the ground is an annulus: a band on each
    side with a hole between them, and the goal becomes one region per side.
    Without it, one region. ``side`` narrows that to a single band when the
    caller has a reason to insist (turning to face an enemy at your back is
    the reason that exists today).

    Falls back to a tolerant :class:`PointGoal` when the body is bigger than
    the band is deep, which would leave no region to aim at.
    """

    half_w, half_h = body.width / 2, body.height / 2
    height = 2 * lane_slack - body.height
    top = target_y - lane_slack + half_h

    if inner_dx <= 0:
        bands = [(target_x - stop_dx + half_w, 2 * stop_dx - body.width)]
    else:
        # Each band spans |dx| in [inner_dx, stop_dx] on its own side; the
        # rectangle is that interval shrunk by the body, so "the body
        # overlaps it" means "my origin is inside the interval".
        span = (stop_dx - inner_dx) - body.width
        centre = (inner_dx + stop_dx) / 2
        bands = []
        if side in ("both", "left"):
            bands.append((target_x - centre - span / 2, span))
        if side in ("both", "right"):
            bands.append((target_x + centre - span / 2, span))

    regions = [
        Rect(left, top, width, height) for left, width in bands if width > 0 and height > 0
    ]
    if not regions:
        return PointGoal(Point(target_x, target_y), tolerance=max(stop_dx, lane_slack))
    return RegionGoal(tuple(regions), axis="y")


def plan_route(
    context: Context,
    actor: Myself | Partner,
    goal: Goal,
    *,
    solids: Sequence[Rect],
    dangers: Sequence[Rect] = (),
    enough_contact: float = 0.0,
    maximize_contact: bool = False,
) -> Path:
    """Route the actor to ``goal``, preferring to keep clear of danger.

    Two passes, and the order is the point. The first treats enemy bodies
    and their reaches as solid, which is the route worth having. The second
    drops them and keeps only what is physically impassable, because a
    screen with four enemies on it can easily have no danger-free route at
    all -- and an AI that stops moving whenever the room is busy is worse
    than one that accepts a risky path. Only a route that actually *arrives*
    wins the first pass; a best effort through danger is no better than a
    best effort without it.
    """

    world = world_rect(context)
    body = body_rect(actor)
    options = dict(
        start=body,
        goal=goal,
        world=world,
        step=NAV_STEP,
        enough_contact=enough_contact,
        maximize_contact=maximize_contact,
        max_nodes=NAV_MAX_NODES,
    )
    if dangers:
        careful = find_path(obstacles=[*solids, *dangers], **options)
        if careful.reached:
            return careful
    return find_path(obstacles=list(solids), **options)


_DIRECTION_MASKS = {
    Direction.LEFT: 0x0004,
    Direction.RIGHT: 0x0008,
    Direction.UP: 0x0001,
    Direction.DOWN: 0x0002,
    Direction.UP_LEFT: 0x0001 | 0x0004,
    Direction.UP_RIGHT: 0x0001 | 0x0008,
    Direction.DOWN_LEFT: 0x0002 | 0x0004,
    Direction.DOWN_RIGHT: 0x0002 | 0x0008,
}


def first_vector_mask(path: Path) -> int:
    """The D-pad bits for the route's first vector, 0 when it has none.

    Only the first: the whole path is replanned next tick anyway, and acting
    on more of it than that is acting on a world that has already moved.
    """

    if not path.steps:
        return 0
    return _DIRECTION_MASKS[path.steps[0].direction]


def route_mask(
    context: Context,
    actor: Myself | Partner,
    goal: Goal,
    *,
    solids: Sequence[Rect],
    dangers: Sequence[Rect] = (),
    enough_contact: float = 0.0,
    maximize_contact: bool = False,
) -> int:
    """``plan_route`` and :func:`first_vector_mask` in one call."""

    return first_vector_mask(
        plan_route(
            context,
            actor,
            goal,
            solids=solids,
            dangers=dangers,
            enough_contact=enough_contact,
            maximize_contact=maximize_contact,
        )
    )


def obstacle_sets(
    context: Context,
    *,
    block_x: int,
    body: Rect | None = None,
    keep_reachable_within: int | None = None,
    ignore_slots: frozenset[str] = frozenset(),
    ignore_enemy_slots: frozenset[str] = frozenset(),
) -> tuple[list[Rect], list[Rect]]:
    """The two obstacle sets ``plan_route`` takes, built in one pass."""

    return (
        solid_obstacles(
            context,
            block_x=block_x,
            body=body,
            keep_reachable_within=keep_reachable_within,
            ignore_slots=ignore_slots,
        ),
        danger_obstacles(context, ignore_slots=ignore_enemy_slots),
    )
