"""Onihime/Yasha (`$58`) ROM gate model — deny commits, then punish.

The twins draw **no RNG**. Every attack they own is gated on player geometry
and player state, so an expert denies the gate instead of reacting to the
animation. Gates verified against `output/sor.asm` (see
`StreetsOfRageRecompilation/ai-analysis/enemy-ai.md`, twins section):

| Gate | ROM | Condition |
| --- | --- | --- |
| Throw commit (`+$30` → `$02`) | `$159F8` | `+$77 == 0` **and** lane `+$52` ∈ [`$10`,`$20`) **and** X `+$50` < `$70` |
| Jump-attack arm | `$15A64` | X `+$50` < `$60`, unconditional otherwise |
| Leap-to-grab arm | `$15BE8` | `+$77 != 0` (player staggered) **and** X < `$90` |
| Grab jump-in | `$15C72` | X < `$40`, or `$40`–`$70` with player grounded, closing **and** facing |
| Grab finalize | `$15B2A` | contact, `+$77 == 0`, at least one body grounded |

`$179F8` sets `+$77 = 1` for a player in hurt/knockdown states `$5A`–`$5F` or
carrying the `+$59`/`+$4B` bit-1 interaction flags.

Two consequences drive the whole doctrine:

* **The lane band [16,32) is the throw trigger.** Coplanar (< 16) is *safer*
  than a half-step sidestep, and it is also punch range. Fight coplanar; when
  a real commit forces a lane leave, go past 32 — never park in between.
* **A grab twin's fast options need our mistake.** Its leap needs us already
  staggered; its jump-in needs us walking into it. Hold the lane and let it
  walk in, and it arrives with nothing.

`+$50`/`+$52` are the ROM's own absolute deltas in world units, so the raw
thresholds apply directly to ``MapEntity`` world coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..phases import is_dangerous, is_punishable
from ..world_map import LANE_Y_MIN, MapEntity, lane_y_max_for_level


TWIN_TYPE = 0x58

# --- Raw ROM gate thresholds (world units) ---------------------------------
THROW_LANE_MIN = 0x10  # 16 — below this the throw commit cannot fire
THROW_LANE_MAX = 0x20  # 32 — at or above this the throw commit cannot fire
THROW_X = 0x70  # 112
JUMP_ATTACK_X = 0x60  # 96
LEAP_GRAB_X = 0x90  # 144
JUMP_IN_NEAR_X = 0x40  # 64
JUMP_IN_FAR_X = 0x70  # 112

# --- Doctrine margins ------------------------------------------------------
# Observations are ~4 frames apart and a chasing twin closes a few px per
# frame, so leave the band with margin instead of landing on 32 exactly.
LANE_SAFE_CLEARANCE = 40.0
# Coplanar attack band. Must stay under THROW_LANE_MIN with sample margin.
LANE_COPLANAR_MAX = 12.0
# Elevation slack before a body counts as airborne.
AIRBORNE_Z_MARGIN = 12.0

# --- Measured strike geometry (live teleport sweep, this ROM) --------------
# P1 placed at a fixed offset from a live twin, one B, boss health word read
# back: misses at 8/12/16/20/24, hits at 28/32/36/40/44/48/52, misses at
# 56/60/64/68/72. The punch therefore has a **near dead zone** — a body that
# has closed onto us is not hit by it, which is exactly where the twins land.
PUNCH_MIN_X = 26.0
# Keep a little inside the far edge; a chasing body covers a few px per sample.
PUNCH_MAX_TRIM = 4.0
# Outgoing damage read from the player's `+$34` descriptor while the animation
# runs: normal punch 1 over ~10 damaging frames, back attack ($20) 3 over 10.
PUNCH_DAMAGE = 1
REAR_DAMAGE = 3
# Boss health at the encounter, and their contact damage against an 80 HP bar.
TWIN_HEALTH = 22
TWIN_CONTACT_DAMAGE = 32


def punch_band(profile) -> tuple[float, float]:
    """Horizontal window in which a normal punch actually reaches a twin."""

    return PUNCH_MIN_X, max(PUNCH_MIN_X + 4.0, profile.strike_range - PUNCH_MAX_TRIM)


def can_strike(me: MapEntity, twin: MapEntity, profile) -> bool:
    """True when a grounded B on this body would land, per the measured band."""

    if is_airborne(twin, me):
        return False
    lo, hi = punch_band(profile)
    dx = abs(float(twin.world_x) - float(me.world_x))
    dy = abs(float(twin.world_y) - float(me.world_y))
    return lo <= dx <= hi and dy <= LANE_COPLANAR_MAX + 2.0


def too_close(me: MapEntity, twin: MapEntity) -> bool:
    """Body has closed inside the punch arc — swinging here whiffs."""

    return abs(float(twin.world_x) - float(me.world_x)) < PUNCH_MIN_X

# Lane scan step when searching for a safe depth.
_LANE_STEP = 2.0

# Base health from `$17EDC` when the health word is unreadable.
BASE_HEALTH = 0x20

# ROM player walk clamp ($43AA), camera-relative; retreat goals stay inside.
WALK_BAND_MIN = 40.0
WALK_BAND_MAX = 280.0


def is_twin(entity: MapEntity) -> bool:
    """True for a live-or-dead type-`$58` boss object."""

    return entity.kind == "boss" and entity.type_id == TWIN_TYPE


def live_twins(entities) -> tuple[MapEntity, ...]:
    """Living type-`$58` bosses in scan order."""

    return tuple(e for e in entities if is_twin(e) and not e.is_defeated)


def is_grab_mode(twin: MapEntity) -> bool:
    """True when this twin runs the grab/throw AI path (`+$7B` bit 1).

    Init copies `+$5D` into `+$7B`, so role 2 starts on the grab path. The bit
    is authoritative because a survivor can promote or drop grab mode at
    runtime; `pair_role` is only the seed and is used when `+$7B` is
    unreadable (older observer samples default it to zero).
    """

    if twin.mode_flags:
        return bool(twin.mode_flags & 0x02)
    return twin.pair_role == 2


def effective_hp(twin: MapEntity) -> int:
    """Comparable remaining HP for focus ranking (lower = better focus)."""

    if twin.is_defeated:
        return 0x7FFF
    if twin.health is None:
        return BASE_HEALTH
    if twin.health >= 0x8000:
        return 0x7FFF
    return int(twin.health)


def is_airborne(twin: MapEntity, me: MapEntity) -> bool:
    """True while the twin is off the ground (jump arc / leap / throw).

    `$15ABA` decides this exactly the same way: compare live height `+$18`
    against the body's own ground snapshot `+$4C`. The player's elevation is
    the wrong reference — a standing twin does not share the player's plane,
    and using it classified every body as airborne.

    Punching an airborne twin whiffs: ten live punches at dx 5-43, dy 1-7
    dealt zero damage while the target was mid-arc.
    """

    if twin.ground_z is None:
        return False
    return abs(float(twin.world_z) - float(twin.ground_z)) > AIRBORNE_Z_MARGIN


def in_throw_band(lane_delta: float) -> bool:
    """True when this lane separation arms the throw commit (`$159F8`)."""

    return THROW_LANE_MIN <= abs(lane_delta) < THROW_LANE_MAX


@dataclass(frozen=True, slots=True)
class TwinThreat:
    """What one twin can do to this player *right now*, per ROM gates."""

    twin: MapEntity
    grab_mode: bool
    dx: float
    dy: float
    committed: bool
    can_throw_commit: bool
    can_jump_attack: bool
    can_leap_grab: bool
    can_jump_in: bool

    @property
    def slot(self) -> str:
        return self.twin.slot

    @property
    def can_act(self) -> bool:
        """True when any gate is open, i.e. standing here is not free."""

        return (
            self.can_throw_commit
            or self.can_jump_attack
            or self.can_leap_grab
            or self.can_jump_in
        )


def assess(me: MapEntity, twin: MapEntity) -> TwinThreat:
    """Evaluate every ROM commit gate for one twin against this player."""

    dx = abs(float(twin.world_x) - float(me.world_x))
    dy = abs(float(twin.world_y) - float(me.world_y))
    grab = is_grab_mode(twin)
    # $179F8: hurt/knockdown states make us "unavailable" (+$77 = 1).
    staggered = me.is_hurt or me.is_held_by_enemy
    grounded = not me.is_airborne
    committed = is_dangerous(twin.combat_phase)
    # A body already inside a commit or a reaction is not re-arming this frame.
    idle = not committed and not is_punishable(twin.combat_phase)

    return TwinThreat(
        twin=twin,
        grab_mode=grab,
        dx=dx,
        dy=dy,
        committed=committed,
        # $159F8 approach commit: available target, band lane, close X.
        can_throw_commit=(
            idle
            and not grab
            and not staggered
            and in_throw_band(dy)
            and dx < THROW_X
        ),
        # $15A64: distance only — the one gate positioning cannot deny.
        can_jump_attack=idle and not grab and dx < JUMP_ATTACK_X,
        # $15BE8: pounces only on an already staggered player.
        can_leap_grab=idle and grab and staggered and dx < LEAP_GRAB_X,
        # $15C72: needs us grounded and closing on it (facing test mirrors).
        can_jump_in=idle and grab and grounded and dx < JUMP_IN_FAR_X,
    )


# Expert feign window. $15C72 needs the player *facing* the boss and closing,
# so a turned back closes the grab twin's jump-in outright and an approach twin
# has nothing but its lane-crossing hop. Let a rear twin walk into back-attack
# range instead of turning to meet it.
REAR_BAIT_MAX = 110.0


@dataclass(frozen=True, slots=True)
class TwinScene:
    """Doctrine for the whole twin fight this frame."""

    threats: tuple[TwinThreat, ...]
    focus: MapEntity | None
    lane_unsafe: bool
    retreat_from: MapEntity | None
    hold_for_walk_in: MapEntity | None
    bait_rear: MapEntity | None

    @property
    def active(self) -> bool:
        return bool(self.threats)

    @property
    def pair(self) -> bool:
        return len(self.threats) >= 2

    def threat_for(self, twin: MapEntity) -> TwinThreat | None:
        for threat in self.threats:
            if threat.slot == twin.slot:
                return threat
        return None


def scene(me: MapEntity, entities) -> TwinScene:
    """Build the twin doctrine: focus, lane safety, retreat, and hold rules."""

    threats = tuple(assess(me, twin) for twin in live_twins(entities))
    if not threats:
        return TwinScene((), None, False, None, None, None)

    focus = _focus(threats)
    # Only an *armed* gate is worth a decision. Using raw geometry here fired
    # the band exit against grab-mode twins (which have no throw commit at
    # all) and against bodies already committed or in hitstun, which starved
    # every grounded punch in the live Round-5 handoff.
    lane_unsafe = any(t.can_throw_commit for t in threats)

    # While staggered, every grab twin inside $90 has its leap armed.
    retreat = None
    if me.is_hurt or me.is_held_by_enemy:
        leapers = [t for t in threats if t.grab_mode and t.dx < LEAP_GRAB_X]
        if leapers:
            retreat = min(leapers, key=lambda t: t.dx).twin

    # Walking into a grab twin is what arms its jump-in. Let it come instead,
    # unless it is already punishable or already inside strike range.
    hold = None
    if focus is not None:
        focus_threat = next(t for t in threats if t.slot == focus.slot)
        if (
            focus_threat.grab_mode
            and not is_punishable(focus.combat_phase)
            and JUMP_IN_NEAR_X <= focus_threat.dx < JUMP_IN_FAR_X
        ):
            hold = focus

    return TwinScene(threats, focus, lane_unsafe, retreat, hold, None)


def rear_bait_target(
    me: MapEntity,
    entities,
    *,
    face_right: bool,
    rear_min: float,
) -> MapEntity | None:
    """A twin closing on our back that we should let arrive.

    Keeping the back turned denies `$15C72` (its facing/closing test) and sets
    up the rear attack, which is the speedrun answer to this pair. Only twins
    that are still outside the back-attack band qualify — once inside it, the
    attack itself fires.
    """

    best = None
    for twin in live_twins(entities):
        if is_dangerous(twin.combat_phase):
            continue
        dx = float(twin.world_x) - float(me.world_x)
        if abs(float(twin.world_y) - float(me.world_y)) > LANE_COPLANAR_MAX:
            continue
        behind = dx < 0 if face_right else dx > 0
        if not behind:
            continue
        distance = abs(dx)
        if distance <= rear_min or distance > REAR_BAIT_MAX:
            continue
        if best is None or distance < abs(float(best.world_x) - float(me.world_x)):
            best = twin
    return best


def _focus(threats: tuple[TwinThreat, ...]) -> MapEntity | None:
    """Lowest HP first, then the nearest body, then the grab twin.

    While the pair is linked the grab twin is the only grab source — the
    approach twin cannot promote until `+$5D == 0`, which requires its partner
    to already be dead. Killing it first removes the whole grab tree for the
    rest of the paired phase.
    """

    if not threats:
        return None
    best = min(
        threats,
        key=lambda t: (effective_hp(t.twin), t.dx, 0 if t.grab_mode else 1, t.slot),
    )
    return best.twin


def safe_lane(
    me: MapEntity,
    entities,
    *,
    level_index: int,
    prefer: float | None = None,
) -> float:
    """Nearest depth that is outside every live twin's throw band.

    Scans outward from ``prefer`` (default: the player's own lane) so the
    result is both legal and the cheapest move. Coplanar depths qualify —
    being *on* a twin's lane never arms the throw commit, only the half-step
    diagonal does.
    """

    twins = live_twins(entities)
    lane_min = float(LANE_Y_MIN + 6)
    lane_max = float(lane_y_max_for_level(level_index) - 6)
    origin = float(me.world_y) if prefer is None else float(prefer)
    origin = min(max(origin, lane_min), lane_max)
    if not twins:
        return origin

    def safe(lane: float) -> bool:
        return not any(in_throw_band(lane - float(t.world_y)) for t in twins)

    if safe(origin):
        return origin

    steps = int((lane_max - lane_min) / _LANE_STEP) + 1
    for step in range(1, steps + 1):
        offset = step * _LANE_STEP
        for candidate in (origin - offset, origin + offset):
            if lane_min <= candidate <= lane_max and safe(candidate):
                return candidate
    return origin


def retreat_goal(
    me: MapEntity,
    twin: MapEntity,
    *,
    level_index: int,
    entities,
    distance: float = LEAP_GRAB_X + 16.0,
) -> tuple[float, float]:
    """World goal that leaves ``twin``'s leap range without leaving the arena.

    Retreats on X away from the body, and lands on a depth that is safe for
    every live twin.
    """

    side = -1.0 if float(twin.world_x) > float(me.world_x) else 1.0
    goal_x = float(me.world_x) + side * distance
    # Clamp inside the ROM walk band ($43AA: camera-relative 32..288) so a
    # cornered retreat holds a direction into a wall instead of latching a goal
    # it can never reach. Lane escape still applies through goal_y.
    map_goal = float(me.map_x) + side * distance
    clamped = min(max(map_goal, WALK_BAND_MIN), WALK_BAND_MAX)
    goal_x = float(me.world_x) + (clamped - float(me.map_x))
    goal_y = safe_lane(me, entities, level_index=level_index)
    return goal_x, goal_y
