"""Symbolic navigation AI: terrain facts, latched detours, approach geometry.

Design (explainable production-style planner):

1. **Terrain facts** from the collision-class hole map and live breakables.
2. **Latched detour plans** for pits (stage 4): once a hole blocks progress,
   commit to one safe lane and finish the vertical move before resuming X.
   Recomputing the detour side every poll caused UP/DOWN shakiness.
3. **Side-only breakable approach**: SoR smash boxes require horizontal
   facing in the same lane. Walking onto a crate from pure top/bottom never
   lands a grounded B — approach the side X first, then match lane. When a
   hole sits beside the prop, score both stand-offs and **latch** the only
   safe side (e.g. hole left of crate → approach from the right).
4. **Jump landing safety**: refuse jump-kicks whose arc or landing cell is a
   pit (observed stage-4 death: jump into a hole while chasing).

This module does not emit controller edges; it returns waypoints and booleans
that policy/walk consume.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from ..hazards import FloorHole
from ..world_map import LANE_Y_MIN, MapEntity, lane_y_max_for_level
from .characters import CharacterProfile

# Probe distance for "next step into void" (matches held-walk cadence).
_STEP_X = 16.0
_STEP_Y = 12.0
# Keep a healthy margin outside hole AABBs (player body is wider than 1 px).
_HOLE_MARGIN = 12.0
_HOLE_APPROACH_MARGIN = 16.0
# Breakables: horizontal stand-off; never park on the prop's X from off-lane.
_BREAK_SIDE_MIN = 18.0
_BREAK_TOP_BOTTOM_X = 14.0  # |dx| below this with large |dy| = top/bottom
# Stand must stay outside hole AABBs by this margin (body + animation drift).
_BREAK_STAND_HOLE_MARGIN = 16.0
# Jump arc samples from takeoff → landing.
_JUMP_SAMPLES = (0.35, 0.55, 0.75, 0.95, 1.0)
_JUMP_LAND_MARGIN = 16.0
# Detour lane hysteresis: stick with a side unless it becomes illegal.
_DETOUR_ARRIVE_EPS = 7.0
_DETOUR_STALE_TICKS = 90
# Illegal stand utility (in a pit): never choose unless both sides fail.
_STAND_ILLEGAL = -10_000.0


class NavPhase(Enum):
    IDLE = auto()
    DETOUR = auto()  # move to latched safe lane (vertical first)
    ADVANCE = auto()  # hold safe lane while clearing the hole on X


@dataclass(frozen=True, slots=True)
class NavWaypoint:
    """One world-space goal produced by the symbolic navigator."""

    goal_x: float
    goal_y: float
    reason: str
    # When True, walk must prefer finishing this waypoint before combat loot
    # detours steal the latch (used for hole detours).
    committed: bool = False


@dataclass
class NavMemory:
    """Persistent navigation plan so hole routing does not oscillate.

    Hole detours and breakable-side choice are separate latches: finishing a
    pit route must not forget which side of a crate is the only solid stand.
    """

    phase: NavPhase = NavPhase.IDLE
    # Identity of the hole we are routing (AABB key).
    hole_x: int = -1
    hole_y: int = -1
    hole_w: int = 0
    hole_h: int = 0
    detour_lane: float | None = None
    # +1 = progress right, -1 = left (locked with the hole plan).
    progress_sign: int = 1
    age: int = 0
    # Breakable approach latch: which side of ``break_slot`` to stand on.
    # -1 = stand left of prop (approach from left), +1 = stand right.
    break_slot: str = ""
    break_side: int = 0
    break_age: int = 0

    def clear(self) -> None:
        """Clear hole-detour state only; keep breakable side commitment."""

        self.phase = NavPhase.IDLE
        self.hole_x = -1
        self.hole_y = -1
        self.hole_w = 0
        self.hole_h = 0
        self.detour_lane = None
        self.progress_sign = 1
        self.age = 0

    def clear_break(self) -> None:
        self.break_slot = ""
        self.break_side = 0
        self.break_age = 0

    def clear_all(self) -> None:
        self.clear()
        self.clear_break()

    def matches_hole(self, hole: FloorHole) -> bool:
        return (
            self.hole_x == hole.world_x
            and self.hole_y == hole.lane_y
            and self.hole_w == hole.width
            and self.hole_h == hole.height
        )

    def latch_hole(self, hole: FloorHole, detour_lane: float, progress_sign: int) -> None:
        self.phase = NavPhase.DETOUR
        self.hole_x = hole.world_x
        self.hole_y = hole.lane_y
        self.hole_w = hole.width
        self.hole_h = hole.height
        self.detour_lane = float(detour_lane)
        self.progress_sign = 1 if progress_sign >= 0 else -1
        self.age = 0

    def latch_break_side(self, slot: str, side: int) -> None:
        side_i = -1 if side < 0 else 1
        if self.break_slot == slot and self.break_side == side_i:
            self.break_age += 1
            return
        self.break_slot = slot
        self.break_side = side_i
        self.break_age = 0

    @property
    def hole_key(self) -> FloorHole | None:
        if self.phase == NavPhase.IDLE or self.hole_x < 0:
            return None
        return FloorHole(
            world_x=self.hole_x,
            lane_y=self.hole_y,
            width=self.hole_w,
            height=self.hole_h,
        )


def point_in_hole(
    world_x: float,
    lane_y: float,
    holes: tuple[FloorHole, ...],
    *,
    margin: float = _HOLE_MARGIN,
) -> FloorHole | None:
    for hole in holes:
        if (
            hole.world_x - margin <= world_x <= hole.world_x_end + margin
            and hole.lane_y - margin <= lane_y <= hole.lane_y_end + margin
        ):
            return hole
    return None


def segment_hits_hole(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    holes: tuple[FloorHole, ...],
    *,
    margin: float = _HOLE_MARGIN,
    samples: int = 6,
) -> FloorHole | None:
    """Sample the straight segment for a pit collision."""

    if samples < 2:
        samples = 2
    for i in range(samples + 1):
        t = i / samples
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t
        hit = point_in_hole(x, y, holes, margin=margin)
        if hit is not None:
            return hit
    return None


def path_blocked_ahead(
    world_x: float,
    lane_y: float,
    *,
    progress_right: bool,
    holes: tuple[FloorHole, ...],
    step: float = _STEP_X,
    margin: float = _HOLE_APPROACH_MARGIN,
) -> FloorHole | None:
    """Hole that a short step in the progress direction would enter."""

    trial_x = world_x + (step if progress_right else -step)
    return point_in_hole(trial_x, lane_y, holes, margin=margin)


def safe_detour_lanes(
    world_x: float,
    trial_x: float,
    hole: FloorHole,
    holes: tuple[FloorHole, ...],
    *,
    level_index: int,
    clearance: float = 14.0,
) -> tuple[float, ...]:
    """Candidate lanes above/below ``hole`` that are free at current and trial X."""

    lane_min = float(LANE_Y_MIN + 4)
    lane_max = float(lane_y_max_for_level(level_index) - 4)
    raw = (
        float(hole.lane_y) - clearance,
        float(hole.lane_y_end) + clearance,
    )
    out: list[float] = []
    for candidate in raw:
        if not lane_min <= candidate <= lane_max:
            continue
        if point_in_hole(world_x, candidate, holes, margin=8.0) is not None:
            continue
        if point_in_hole(trial_x, candidate, holes, margin=12.0) is not None:
            continue
        out.append(candidate)
    return tuple(out)


def choose_detour_lane(
    lane_y: float,
    candidates: tuple[float, ...],
    *,
    preferred: float | None = None,
) -> float | None:
    """Pick a detour lane with hysteresis on ``preferred``."""

    if not candidates:
        return None
    if preferred is not None:
        for candidate in candidates:
            if abs(candidate - preferred) <= 6.0:
                return preferred
        # Preferred side still listed?
        if preferred in candidates:
            return preferred
        nearest_pref = min(candidates, key=lambda c: abs(c - preferred))
        # Keep preferred if it is still the closest option.
        if abs(nearest_pref - preferred) <= 10.0:
            return nearest_pref
    return min(candidates, key=lambda c: (abs(c - lane_y), c))


def escape_hole_waypoint(
    world_x: float,
    lane_y: float,
    hole: FloorHole,
    *,
    level_index: int,
) -> NavWaypoint:
    """Push out of an overlapping pit AABB toward the nearest solid edge."""

    mid_x = (hole.world_x + hole.world_x_end) / 2.0
    mid_y = (hole.lane_y + hole.lane_y_end) / 2.0
    gx = float(hole.world_x - 18.0 if world_x >= mid_x else hole.world_x_end + 18.0)
    gy = float(hole.lane_y - 14.0 if lane_y >= mid_y else hole.lane_y_end + 14.0)
    lane_min = float(LANE_Y_MIN + 4)
    lane_max = float(lane_y_max_for_level(level_index) - 4)
    gy = max(lane_min, min(lane_max, gy))
    return NavWaypoint(gx, gy, "nav escape hole", committed=True)


def route_to_goal(
    me: MapEntity,
    goal_x: float,
    goal_y: float,
    holes: tuple[FloorHole, ...],
    memory: NavMemory,
    *,
    level_index: int,
    progress_right: bool | None = None,
    reason: str = "walk",
) -> NavWaypoint:
    """Insert a latched hole-detour waypoint when the straight path is void.

    Without holes, returns the requested goal. With holes, commits to
    DETOUR → ADVANCE so stage-4 progress does not flicker UP/DOWN.
    """

    wx, wy = float(me.world_x), float(me.world_y)
    gx, gy = float(goal_x), float(goal_y)
    if not holes:
        memory.clear()
        return NavWaypoint(gx, gy, reason)

    # Emergency: already inside a pit.
    current = point_in_hole(wx, wy, holes, margin=0.0)
    if current is not None:
        memory.clear()
        return escape_hole_waypoint(wx, wy, current, level_index=level_index)

    if progress_right is None:
        progress_right = gx >= wx
    progress_sign = 1 if progress_right else -1
    trial_x = wx + (_STEP_X if progress_right else -_STEP_X)

    memory.age += 1
    if memory.age > _DETOUR_STALE_TICKS and memory.phase != NavPhase.IDLE:
        memory.clear()

    # Continue a latched plan for the same hole.
    if memory.phase != NavPhase.IDLE and memory.detour_lane is not None:
        hole = memory.hole_key
        if hole is None:
            memory.clear()
        else:
            # Still relevant if the original hole is near our X corridor.
            still_near = (
                wx - 40.0 <= hole.world_x_end + 8.0
                and wx + 40.0 >= hole.world_x - 8.0
            ) or (
                min(wx, gx) - 8.0 <= hole.world_x_end
                and max(wx, gx) + 8.0 >= hole.world_x
            )
            if not still_near:
                memory.clear()
            elif memory.phase == NavPhase.DETOUR:
                if abs(wy - memory.detour_lane) > _DETOUR_ARRIVE_EPS:
                    return NavWaypoint(
                        wx,
                        memory.detour_lane,
                        "nav detour lane",
                        committed=True,
                    )
                memory.phase = NavPhase.ADVANCE
                memory.age = 0
            if memory.phase == NavPhase.ADVANCE:
                # Hold the safe lane until we clear the hole's far edge.
                far = (
                    float(hole.world_x_end + 20.0)
                    if memory.progress_sign > 0
                    else float(hole.world_x - 20.0)
                )
                cleared = (
                    wx >= hole.world_x_end + 8.0
                    if memory.progress_sign > 0
                    else wx <= hole.world_x - 8.0
                )
                if not cleared:
                    return NavWaypoint(
                        far,
                        memory.detour_lane,
                        "nav advance past hole",
                        committed=True,
                    )
                memory.clear()

    # If the requested goal itself sits in a hole, nudge it first.
    goal_hit = point_in_hole(gx, gy, holes, margin=8.0)
    if goal_hit is not None:
        mid = (goal_hit.world_x + goal_hit.world_x_end) / 2.0
        gx = float(
            goal_hit.world_x - 14.0 if gx >= mid else goal_hit.world_x_end + 14.0
        )
        mid_y = (goal_hit.lane_y + goal_hit.lane_y_end) / 2.0
        gy = float(
            goal_hit.lane_y - 12.0 if gy >= mid_y else goal_hit.lane_y_end + 12.0
        )

    # Straight path blocked (segment or short progress step).
    blocked = segment_hits_hole(
        wx, wy, gx, gy, holes, margin=_HOLE_MARGIN, samples=8
    )
    if blocked is None:
        blocked = path_blocked_ahead(
            wx, wy, progress_right=progress_right, holes=holes
        )
        # Only treat progress-step block when the goal also wants that X dir.
        if blocked is not None and (gx - wx) * progress_sign <= 0:
            blocked = None

    if blocked is not None:
        candidates = safe_detour_lanes(
            wx, trial_x, blocked, holes, level_index=level_index
        )
        preferred = (
            memory.detour_lane if memory.matches_hole(blocked) else None
        )
        detour = choose_detour_lane(wy, candidates, preferred=preferred)
        if detour is not None:
            memory.latch_hole(blocked, detour, progress_sign)
            if abs(wy - detour) > _DETOUR_ARRIVE_EPS:
                return NavWaypoint(
                    wx, detour, "nav detour lane", committed=True
                )
            memory.phase = NavPhase.ADVANCE
            far = (
                float(blocked.world_x_end + 20.0)
                if progress_sign > 0
                else float(blocked.world_x - 20.0)
            )
            return NavWaypoint(
                far, detour, "nav advance past hole", committed=True
            )
        # No safe lane: back off horizontally.
        retreat = wx - 28.0 * progress_sign
        return NavWaypoint(retreat, wy, "nav retreat hole", committed=True)

    return NavWaypoint(gx, gy, reason)


def _break_side_dist(profile: CharacterProfile) -> float:
    return max(_BREAK_SIDE_MIN, profile.approach_offset * 0.7)


def stand_point_for_side(
    prop: MapEntity,
    side: int,
    profile: CharacterProfile,
) -> tuple[float, float]:
    """World stand-off on the left (side<0) or right (side>0) of ``prop``."""

    dist = _break_side_dist(profile)
    sign = -1.0 if side < 0 else 1.0
    return float(prop.world_x) + sign * dist, float(prop.world_y)


def score_breakable_stand(
    me: MapEntity,
    stand_x: float,
    stand_y: float,
    holes: tuple[FloorHole, ...],
    *,
    side: int,
    progress_right: bool,
) -> float:
    """Higher is better. Illegal stands (in a pit) score ``_STAND_ILLEGAL``."""

    if point_in_hole(
        stand_x, stand_y, holes, margin=_BREAK_STAND_HOLE_MARGIN
    ) is not None:
        return _STAND_ILLEGAL
    # Also reject stands whose lane-match point is solid but a short step
    # toward the prop face drops into the hole (hole abuts the crate).
    face_x = stand_x + (8.0 if side < 0 else -8.0)
    if point_in_hole(
        face_x, stand_y, holes, margin=_BREAK_STAND_HOLE_MARGIN * 0.75
    ) is not None:
        return _STAND_ILLEGAL

    wx, wy = float(me.world_x), float(me.world_y)
    utility = 0.0
    # Prefer a clear straight path; detours are still possible but cost more.
    if segment_hits_hole(
        wx, wy, stand_x, stand_y, holes, margin=_HOLE_MARGIN, samples=8
    ) is not None:
        utility -= 80.0
    else:
        utility += 40.0
    # Travel cost.
    utility -= 0.35 * (abs(stand_x - wx) + abs(stand_y - wy))
    # Mild progress bias when both sides are otherwise equal.
    if progress_right and side < 0:
        utility += 4.0
    elif not progress_right and side > 0:
        utility += 4.0
    # Prefer the side we already occupy (reduces thrash) — only if solid.
    if (me.world_x < stand_x and side > 0) or (me.world_x > stand_x and side < 0):
        # Already on the outer side of this stand.
        utility += 6.0
    elif (side < 0 and me.world_x <= stand_x + 4) or (
        side > 0 and me.world_x >= stand_x - 4
    ):
        utility += 12.0
    return utility


def choose_breakable_side(
    me: MapEntity,
    prop: MapEntity,
    profile: CharacterProfile,
    holes: tuple[FloorHole, ...],
    memory: NavMemory | None,
    *,
    progress_right: bool = True,
) -> int:
    """Pick -1 (left stand) or +1 (right stand) with hole safety + hysteresis."""

    left_x, left_y = stand_point_for_side(prop, -1, profile)
    right_x, right_y = stand_point_for_side(prop, 1, profile)
    scores = {
        -1: score_breakable_stand(
            me, left_x, left_y, holes, side=-1, progress_right=progress_right
        ),
        1: score_breakable_stand(
            me, right_x, right_y, holes, side=1, progress_right=progress_right
        ),
    }

    # Hysteresis: keep the latched side while it remains legal.
    if (
        memory is not None
        and memory.break_slot == prop.slot
        and memory.break_side in (-1, 1)
        and scores[memory.break_side] > _STAND_ILLEGAL / 2
    ):
        return memory.break_side

    # Prefer any legal side; if both illegal, pick the less-bad (still solidest).
    legal = {s: u for s, u in scores.items() if u > _STAND_ILLEGAL / 2}
    pool = legal if legal else scores
    best = max(pool.items(), key=lambda item: (item[1], item[0]))[0]
    return best


def breakable_side_approach(
    me: MapEntity,
    prop: MapEntity,
    profile: CharacterProfile,
    *,
    progress_right: bool = True,
    holes: tuple[FloorHole, ...] = (),
    memory: NavMemory | None = None,
) -> NavWaypoint:
    """Waypoint that approaches a breakable from a **safe** left/right stand.

    Grounded smash needs same-lane facing. Pure top/bottom walks never land B.
    When a hole sits on one side of the prop (classic stage-4: pit left of
    crate), only the solid side is latched so the agent does not thrash between
    the void stand and a hole detour.
    """

    side = choose_breakable_side(
        me,
        prop,
        profile,
        holes,
        memory,
        progress_right=progress_right,
    )
    if memory is not None:
        memory.latch_break_side(prop.slot, side)

    stand_x, stand_y = stand_point_for_side(prop, side, profile)
    abs_dx = abs(float(prop.world_x) - float(me.world_x))
    abs_dy = abs(float(prop.world_y) - float(me.world_y))
    side_name = "L" if side < 0 else "R"

    # If the chosen stand is still illegal (both sides over pits), retreat to a
    # solid lane offset rather than walk into the void.
    if point_in_hole(
        stand_x, stand_y, holes, margin=_BREAK_STAND_HOLE_MARGIN
    ) is not None:
        escape_y = float(me.world_y)
        for delta in (24.0, -24.0, 40.0, -40.0):
            trial = float(me.world_y) + delta
            if point_in_hole(
                float(me.world_x), trial, holes, margin=10.0
            ) is None:
                escape_y = trial
                break
        return NavWaypoint(
            float(me.world_x),
            escape_y,
            f"break retreat hole {prop.label}",
            committed=True,
        )

    # Phase A: leave a top/bottom stack — move to side X first at current Y,
    # but only if that intermediate point is not a pit.
    if abs_dx <= _BREAK_TOP_BOTTOM_X and abs_dy > 10.0:
        mid_y = float(me.world_y)
        if point_in_hole(
            stand_x, mid_y, holes, margin=_BREAK_STAND_HOLE_MARGIN
        ) is None:
            return NavWaypoint(
                stand_x,
                mid_y,
                f"break side-align {side_name} {prop.label}",
                committed=True,
            )
        # Intermediate at current Y is void — go straight to stand (router
        # will detour around the hole).
        return NavWaypoint(
            stand_x,
            stand_y,
            f"break safe {side_name} {prop.label}",
            committed=True,
        )

    # Phase B: hold side X while matching lane (never walk to prop.x off-lane).
    if abs_dy > 10.0:
        return NavWaypoint(
            stand_x,
            stand_y,
            f"break lane {side_name} {prop.label}",
            committed=True,
        )

    # Phase C: fine close at side stand-off.
    return NavWaypoint(
        stand_x,
        stand_y,
        f"break close {side_name} {prop.label}",
        committed=True,
    )


def breakable_side_ready(
    me: MapEntity,
    prop: MapEntity,
    profile: CharacterProfile,
    *,
    holes: tuple[FloorHole, ...] = (),
) -> bool:
    """True when geometry is a side smash on solid ground, not top/bottom."""

    abs_dx = abs(float(prop.map_x) - float(me.map_x))
    abs_dy = abs(float(prop.map_y) - float(me.map_y))
    if abs_dy > 12.0:
        return False
    if abs_dx < _BREAK_SIDE_MIN * 0.55:
        return False
    if abs_dx > profile.strike_range + 4.0:
        return False
    # Refuse to "ready" a smash while standing in/over a pit.
    if point_in_hole(
        float(me.world_x),
        float(me.world_y),
        holes,
        margin=_BREAK_STAND_HOLE_MARGIN,
    ) is not None:
        return False
    return True


def jump_landing_safe(
    me: MapEntity,
    target: MapEntity | None,
    holes: tuple[FloorHole, ...],
    *,
    land_x: float | None = None,
    land_y: float | None = None,
    margin: float = _JUMP_LAND_MARGIN,
) -> bool:
    """False if a jump-kick arc toward the target crosses or lands in a pit."""

    if not holes:
        return True
    x0, y0 = float(me.world_x), float(me.world_y)
    if land_x is None:
        land_x = float(target.world_x) if target is not None else x0
    if land_y is None:
        land_y = float(target.world_y) if target is not None else y0
    # Jump kicks mostly keep lane; bias landing Y toward current lane.
    land_y = y0 * 0.65 + float(land_y) * 0.35
    for t in _JUMP_SAMPLES:
        x = x0 + (float(land_x) - x0) * t
        y = y0 + (float(land_y) - y0) * t
        if point_in_hole(x, y, holes, margin=margin) is not None:
            return False
    # Also reject if the immediate forward step under the jump is void.
    mid_x = x0 + (float(land_x) - x0) * 0.5
    if point_in_hole(mid_x, y0, holes, margin=margin) is not None:
        return False
    return True


def progress_goal(
    me: MapEntity,
    *,
    progress_right: bool,
    horizontal: bool,
    lead: float,
    preferred_lane: float | None = None,
    note: str = "",
) -> NavWaypoint:
    """Raw stage-progress goal. Hole routing is applied once in ``route_to_goal``.

    ``lead`` is already signed (positive = right, negative = left).
    """

    del progress_right  # retained for call-site clarity / future corridor bias
    wx, wy = float(me.world_x), float(me.world_y)
    gy = preferred_lane if preferred_lane is not None else wy
    label = f"progress ({note})" if note else "nav progress"
    if not horizontal:
        hold = f"progress ({note})" if note else "nav hold lane"
        return NavWaypoint(wx, float(gy), hold)
    gx = wx + float(lead)
    return NavWaypoint(gx, float(gy), label)
