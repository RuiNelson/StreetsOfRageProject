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

**Whether a jump may launch.** A jump has no mid-air Y, so
:func:`jump_landing_is_safe` asks the pathfinder the flight's own
question (slide this lane to the landing, pits as solids) and, when that
fails, whether a 2D walk can go around instead. :func:`hop_landing_x` is
the advance-stage counterpart: the X just past a pit the walk cannot
route around.

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
from .reach import (
    PIT_AVOID_MARGIN,
    SOUTHER_SLASH_DIST_CLOSING,
    SOUTHER_SLASH_DIST_MIN,
    SOUTHER_SLASH_LANE,
    any_pit_endangers,
    jump_attack_max_dx,
    live_enemies,
)
from .tokens import (
    Breakable,
    CameraRange,
    Context,
    Enemy,
    Myself,
    Partner,
    Pit,
    Souther,
    Stage,
    find,
    find_all,
)
from .. import prop_solids
from ..hitboxes import Hitbox
from ..phases import is_dangerous, is_punishable
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
#
# 8 rather than 4, from three 90 s live runs per value: settling for 4 lets
# the actor fight from the very edge of its own band, where its punch barely
# reaches and the enemy's covers it completely, and it took 29 damage/min
# doing so against 25 at 8 -- for the same damage dealt. It is still a floor
# and not a preference: an enemy moves, and spending steps perfecting an
# alignment it is about to invalidate is how an approach becomes a dance.
MIN_STRIKE_CONTACT_Y = 8

# How far past the camera edge a route may be planned.
#
# Must comfortably exceed every goal offset any routed verb can place beyond
# the actor's own position: WalkToAdvanceStage's fixed 40px lookahead, and a
# strike goal's stop_dx (up to punch_outer_x, ~56px, plus half the goal
# rectangle's own inset). 32 did not -- live-diagnosed: an actor standing
# within 8px of the camera's trailing edge got a WalkToAdvanceStage lookahead
# point (ahead_x = world_x + 40) that landed outside `world_rect` by exactly
# that overshoot, so no lattice position could ever satisfy the goal,
# `plan_route` reported `reached=False` every tick forever, and the actor
# stalled dead on the camera's own edge -- not merely poorly routed, unable
# to make progress at all, since advancing is what would have scrolled the
# camera and made the goal reachable again. Reproduced live at world_x=3808,
# exactly `camera.right` (the margin had already been spent getting there).
#
# 96 clears the largest goal offset with room to spare and stays well inside
# what `world_map` already tracks past each camera edge (two screens, per its
# own docs) -- planning slightly further than the camera shows is harmless,
# since every obstacle in that reach is still real, observed geometry.
WORLD_MARGIN_X = 96


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


class _OriginRule:
    """Restates rules about an *origin* as rectangles a *body* may not touch.

    Both kinds of solid geometry in this game are point rules -- the ROM
    tests the moving object's own position against them, never its box --
    while the path finder collides whole bodies. This is the conversion, and
    it is exact: for a body reaching ``a`` behind the origin and ``b`` in
    front of it, "the body overlaps ``[x0 + b, x1 - a]``" and "the origin is
    strictly inside ``(x0, x1)``" are the same statement.

    Half the body on each side is *not* the same statement, and the
    difference is a stall. A real cached box is not centred on the origin:
    measured live, Axel's spans -7..+3 of his own position facing left. Off
    by those 2px, the route stepped down at an x the ROM counted as inside a
    round-5 prop and the actor held DOWN against it for 42 seconds -- the
    identical symptom this whole model was written to remove, one prop
    further along the stage. ``strike_goal`` carries the same correction, for
    the same reason.

    Without an origin the body is assumed centred, which is the best
    available answer and the one the pre-existing pit inset already made.
    """

    def __init__(self, body: Rect | None, origin: tuple[float, float] | None) -> None:
        if body is None:
            self.behind_x = self.ahead_x = self.behind_y = self.ahead_y = 0.0
        elif origin is None:
            self.behind_x = self.ahead_x = body.width / 2
            self.behind_y = self.ahead_y = body.height / 2
        else:
            origin_x, origin_y = origin
            self.behind_x = origin_x - body.left
            self.ahead_x = body.right - origin_x
            self.behind_y = origin_y - body.top
            self.ahead_y = body.bottom - origin_y

    def rect(self, rect: Rect) -> Rect:
        """``rect`` as the ground the body must keep off."""

        left, width = _shrunk(rect.x, rect.right, self.ahead_x, self.behind_x)
        top, height = _shrunk(rect.y, rect.bottom, self.ahead_y, self.behind_y)
        return Rect(left, top, width, height)


def _shrunk(lo: float, hi: float, ahead: float, behind: float) -> tuple[float, float]:
    """One axis of the conversion, never narrower than a pixel.

    A rule can legitimately be shallower than the body is deep -- the phone
    booth's is 14px against a 16px actor -- and no rectangle can then say
    "the origin is inside" exactly. A zero-width one says nothing at all and
    is dropped by the lattice outright, turning the shallowest walls into no
    wall, so the floor is one pixel centred on the same ground: it
    over-states such a rule slightly.

    That over-statement reaches into the walkable-in-front band (every ROM
    record ends 4px past the origin on lane). A body standing legally just
    in front therefore overlaps the pixel. That is a *graze*, not "already
    inside": the lattice must keep the wall (it only drops an obstacle whose
    interior contains the body's centre) so the first step is sideways out
    of the column, not UP through the real solid. Pinning the pixel to the
    back of the interval instead left the front approach unblocked -- the
    search walked UP, the ROM undid it, and the actor froze. Centre is the
    placement that still blocks that UP step while leaving a DOWN escape.
    """

    low, high = lo + ahead, hi - behind
    if high - low >= 1.0:
        return low, high - low
    middle = (low + high) / 2
    return middle - 0.5, 1.0


def solid_obstacles(
    context: Context,
    *,
    body: Rect | None = None,
    origin: tuple[float, float] | None = None,
    ignore_slots: frozenset[str] = frozenset(),
) -> list[Rect]:
    """Geometry that is physically impassable: intact props and floor holes.

    Both are **point rules**, and both are therefore restated through
    :class:`_OriginRule` rather than collided against directly.

    A **prop** is a wall, but not the wall its sprite draws: ``prop_solids``
    carries the ROM's own per-type push-back rectangle, which for some types
    sits mostly *behind* the origin while the animation box sits in front of
    it. Routing off the sprite box planned straight through solid ground --
    the stage-5 stall that module's docstring records.

    A **pit** is a floor rule, and every other pit check in the AI agrees:
    ``reach.pit_endangers`` tests a point against the hole plus
    ``PIT_AVOID_MARGIN``. Growing the hole by that margin and *also*
    colliding a 16px-tall body against it counts the clearance twice: an
    actor standing 2px clear of the danger band, which the rest of the
    pipeline calls safe, reads as already inside it here.

    Measured, on the sweep: the actor started legally beside a pit, this
    said it was standing in one, the route left the lane to escape a hole it
    was never in, and it spent the whole run walking back around instead of
    reaching the enemy it had been punching before.
    """

    rects: list[Rect] = []
    rule = _OriginRule(body, origin)
    for prop in find_all(context, Breakable):
        if prop.slot in ignore_slots:
            continue
        solid = prop_solids.solid_box(prop.type_id, prop.world_x, prop.world_y)
        rects.append(
            rule.rect(Rect(solid.x0, solid.y0, solid.width, solid.height))
        )
    rects.extend(pit_obstacles(context, body=body, origin=origin))
    return rects


def pit_obstacles(
    context: Context,
    *,
    body: Rect | None = None,
    origin: tuple[float, float] | None = None,
) -> list[Rect]:
    """Pit solids only -- the floor holes a jump flies over but must not land in.

    Same restatement as :func:`solid_obstacles` (origin rule, inclusive
    predicate grown by one px). Breakables are omitted: a jump clears them
    in Z. Callers that need both use ``solid_obstacles``.
    """

    rule = _OriginRule(body, origin)
    rects: list[Rect] = []
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
        rects.append(rule.rect(danger))
    return rects


def commit_gate_rects(enemy: Enemy) -> list[Rect]:
    """Ground on which this enemy's committed move can still be *started*.

    Not a swing -- ``enemy_rects`` already owns those, and only while one is
    actually out. This is the ground a boss's own commit gate covers, so the
    route can be planned around the gate rather than into it.

    It exists because the two ways an approach can be safe pull in opposite
    directions. ``_approach_lane_y`` puts the *destination* off the enemy's
    lane, which is correct and not enough: the router is free to reach that
    destination by any shortest path, and the shortest path from a lane the
    enemy already shares runs diagonally through his own commit box.
    Measured live against Souther, the same two hits landed at t=1.4 and
    t=3.2 in five fights out of five, every one of them with
    ``WalkToNearEnemy`` holding the tick and the gate satisfied mid-route.

    Today that is Souther alone, from ``$15EDA (souther_state1_active_combat)``:
    he commits when ``+$50`` is in ``[$18, $68)`` and ``+$52 < $1C``. The
    ``$68`` edge is the widest of the three bands -- the one for a target
    *walking into him*, which is what an approach is. Two rectangles, one
    each side, with the ``$18`` inner abort as the hole between them: routing
    around them and in through the hole *is*
    ai-analysis/enemy-ai.md's uncommittable corridor, and the pocket the
    approach stops in sits inside the hole.

    Excluded while he cannot use the gate at all:

    - **committed already** (``strike_is_committed``): the claw is out, the
      box describes nothing, and ``DodgeSoutherSlash`` owns the answer;
    - **punishable**: his hit reaction is the one window the fight is won in,
      and walling it off would refuse the walk-in the grab needs.
    """

    if not isinstance(enemy, Souther) or enemy.is_defeated:
        return []
    if enemy.strike_is_committed() or is_punishable(enemy.combat_phase):
        return []
    height = 2.0 * SOUTHER_SLASH_LANE
    top = enemy.world_y - SOUTHER_SLASH_LANE
    width = float(SOUTHER_SLASH_DIST_CLOSING - SOUTHER_SLASH_DIST_MIN)
    return [
        Rect(enemy.world_x - SOUTHER_SLASH_DIST_CLOSING, top, width, height),
        Rect(enemy.world_x + SOUTHER_SLASH_DIST_MIN, top, width, height),
    ]


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
        rects.extend(commit_gate_rects(enemy))
    return rects


def strike_goal(
    body: Rect,
    origin_x: float,
    origin_y: float,
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

    # The region is tested against the body *rectangle*, but every reach
    # predicate is about the actor's **origin**, and a real cached box is not
    # centred on it: measured live, Axel's body spans -3..+7 of his own
    # position. Ignoring that 2px offset is not a rounding error -- it is a
    # stall. The actor parks where the region says it has arrived, 38px from
    # a crate that `in_smash_range` will only accept at 36, presses nothing,
    # and stands there: 1600 of 2500 ticks of a live run spent against one
    # crate. Shifting the region by the offset makes "the body overlaps this"
    # mean "my origin is within stop_dx", which is the predicate's sentence.
    origin_offset_x = body.center.x - origin_x
    origin_offset_y = body.center.y - origin_y
    target_x = target_x + origin_offset_x
    target_y = target_y + origin_offset_y

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


def advance_goal(context: Context, ahead_x: float) -> Goal:
    """A vertical strip at ``ahead_x``: any lane that has made that progress.

    ``WalkToAdvanceStage`` has no lane to keep. A point on the actor's own
    Y that sits in or behind a pit is unreachable -- every covering cell
    is inside the hole -- so the search's best effort is "walk up to the
    wall", which is a straight line into the pit on a lane that had room
    above or below. The strip is the sentence the verb actually means:
    get this far forward, take whichever Y is walkable.
    """

    lo, hi = lane_bounds(context)
    return RegionGoal.of(Rect(ahead_x, lo, 1.0, max(1.0, hi - lo)), axis="x")


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
    body: Rect | None = None,
    origin: tuple[float, float] | None = None,
    ignore_slots: frozenset[str] = frozenset(),
    ignore_enemy_slots: frozenset[str] = frozenset(),
) -> tuple[list[Rect], list[Rect]]:
    """The two obstacle sets ``plan_route`` takes, built in one pass."""

    return (
        solid_obstacles(context, body=body, origin=origin, ignore_slots=ignore_slots),
        danger_obstacles(context, ignore_slots=ignore_enemy_slots),
    )


def actor_footprint(
    actor: Myself | Partner,
) -> tuple[Rect, tuple[float, float]]:
    """The pair every obstacle set wants: the body, and where the actor's own
    position sits inside it.

    Together, not separately -- an origin paired with somebody else's body is
    exactly the mismatch :class:`_OriginRule` exists to get right.
    """

    return body_rect(actor), (float(actor.world_x), float(actor.world_y))


def plan_lane_route(
    context: Context,
    actor: Myself | Partner,
    target_x: float,
) -> Path:
    """Pathfinder answer to: can this body slide to ``target_x`` on its lane?

    A jump has no mid-air Y, so the world is a corridor whose height is
    exactly the body's -- the search cannot dodge around a pit the way a
    walk can. Only pits are solids: a crate is jumpable, a hole is not.
    ``reached`` means the landing origin can sit at ``target_x`` without
    overlapping a pit.
    """

    body, origin = actor_footprint(actor)
    world = world_rect(context)
    corridor = Rect(world.left, body.top, world.width, max(body.height, 1.0))
    goal = PointGoal(Point(target_x, origin[1]), tolerance=NAV_STEP)
    return find_path(
        start=body,
        goal=goal,
        world=corridor,
        obstacles=pit_obstacles(context, body=body, origin=origin),
        step=NAV_STEP,
        max_nodes=NAV_MAX_NODES,
    )


def jump_landing_is_safe(
    context: Context,
    actor: Myself | Partner,
    target_x: int,
) -> bool:
    """May a jump toward ``target_x`` launch, according to the pathfinder.

    A jump flies on the actor's current lane (no mid-air Y). Three answers:

    - The lane itself is clear to ``target_x`` (``plan_lane_route.reached``):
      yes.
    - A 2D walk can get there by leaving the lane (going around a pit):
      no -- jumping would skip the detour and fly through the hole.
    - No walk reaches (the pit spans the playable Y): yes only if the
      landing origin is not itself in a pit, i.e. this is a jump *over* to
      solid ground, not a jump *into* the hole.
    """

    if any_pit_endangers(context, target_x, actor.world_y):
        return False
    if plan_lane_route(context, actor, target_x).reached:
        return True
    body, origin = actor_footprint(actor)
    walk = plan_route(
        context,
        actor,
        PointGoal(Point(float(target_x), origin[1]), tolerance=NAV_STEP),
        solids=solid_obstacles(context, body=body, origin=origin),
        dangers=(),
    )
    if walk.reached:
        return False
    return True


def hop_landing_x(
    context: Context,
    actor: Myself | Partner,
    direction: str,
) -> int | None:
    """X just past the nearest pit that blocks this lane, if a jump can land there.

    Callers ask this only after ``plan_route`` failed to walk around.
    ``None`` when no pit sits on this Y in ``direction``, the far side is
    still a hole, or the gap is wider than this character's kick range.
    """

    going_right = direction != "left"
    max_dx = jump_attack_max_dx(actor.character_id)
    y = actor.world_y
    x = actor.world_x
    best: int | None = None
    best_dist: int | None = None
    for pit in find_all(context, Pit):
        pit_right = pit.world_x + pit.width
        pit_bottom = pit.lane_y + pit.height
        if y < pit.lane_y - PIT_AVOID_MARGIN or y > pit_bottom + PIT_AVOID_MARGIN:
            continue
        if going_right:
            if pit_right <= x:
                continue
            landing = pit_right + PIT_AVOID_MARGIN + NAV_STEP
        else:
            if pit.world_x >= x:
                continue
            landing = pit.world_x - PIT_AVOID_MARGIN - NAV_STEP
        if any_pit_endangers(context, landing, y):
            continue
        dist = abs(landing - x)
        if dist > max_dx:
            continue
        if best_dist is None or dist < best_dist:
            best = landing
            best_dist = dist
    return best
