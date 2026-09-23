"""Onihime and Yasha: the plan -- rear attacks from the edge, planned on the
ROM model in ``twins.py``.

The user's plan, and what the ROM makes of it (``twins.py`` has the decode):

1. **An edge, and the twins behind.** The actor goes to the camera edge on
   the side away from the grab twin and faces the wall. The grab twin only
   ever jumps at a target that *faces* it (``$15C72``), so a back turned to
   it leaves it one move: walking in at 2 px an update. The approach twin
   keeps its distance whatever the facing (a backflip inside 96 px).
2. **Let them come; align the lane.** The grab twin homes the lane itself
   (``$1797E``: 4/2/1/0 px). The actor's lane is spent on the approach twin:
   its only attack, the flying kick, needs the target 16-31 lanes off inside
   112 px (``$15A0E``), so a lane held close to its own denies it -- and the
   same kick, once launched, is a fixed ballistic path the lookahead can
   either step out of or meet with the rear attack on its way down.
3. **The rear attack, exactly when it lands.** B+C (``$322A``). Blaze's box
   is out on updates 3-10 after the press (``$3A30`` row 26: 3, 8, 3) and
   reaches 5-53 px behind her; Axel's on 1-5 (row 8: 1, 5, 2), 8-40 px. A
   strike is tested before the twin's own box (``$AAA0``) and knocks it down
   90 px away for 39 updates. During the chord the actor's body box moves
   *behind* it (Blaze's ``$75``/``$77``), toward the twin -- so a chord
   pressed with the grab twin already close is a grab during its own
   startup. The lookahead plays all of it.

The lookahead (``plan``): a handful of stick programs -- stand, a lane step
up or down, toward the wall, each held 1, 5 or 12 updates -- and the rear
attack now or after 2/4/6 updates, each then handed to a reactive tail
(``tail_action``: the chord when a twin's body will be in the box, a lane
held on the approach twin, a dodge off a flying kick's path, back to the
wall), played out against both twins for ``HORIZON`` updates (longer while a
kick is in the air) under both update orders, and scored by the worse: a hit
below everything, a strike by how soon, the rest by the end position.

No chord that can miss (user: "não quero que dê ataques em falso"): a
program whose first update presses B+C is admissible only if that press
strikes a twin under every timing; otherwise it is dropped, whatever it
scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from . import twins as model
from .twins import (
    ActorSim,
    Outcome,
    TwinSim,
    actor_update,
    object_pass,
)

__all__ = ["TwinsPlan", "plan", "choose_wall", "tail_action"]

HORIZON = 30
HORIZON_MAX = 40
FIRST_DURATIONS = (1, 5, 12)
CHORD_DELAYS = (2, 4, 6)
# Lane the tail keeps on the approach twin while it is inside this on X: well
# outside its 112 px commit window, so the lane is right before the window.
GUARD_DX = 150
# Inside this lane gap the approach twin cannot commit (its window is 16-31);
# the tail keeps the gap below it with this much room for its 1 px drift.
GUARD_GAP = 10
# The kick is a fixed path: the tail steps off it while it is still in the
# air, to this many lanes off its lane at the updates the box can land.
DODGE_GAP = 20
# The grab twin counts as "coming" inside this on X; beyond it (or down) the
# approach twin is let commit.
BUSY_DX = 150
# Lanes kept free between the actor and either edge of the band when nothing
# else wants the lane: a kick is stepped off by the lane, and a cornered actor
# has one way out.
LANE_ROOM = 24
# What keeping to the last tick's program is worth (PlanMemory): more than
# the noise between near-ties, far less than a strike.
STICKY = 150
# Scores.
_SCORE_HIT = -1_000_000
_SCORE_HIT_PER_UPDATE = 1_000
_SCORE_STRIKE = 5_000
_SCORE_STRIKE_PER_UPDATE = 40
_SCORE_HELD = -60_000
_SCORE_FACING_OPEN = -60
_SCORE_PER_PX_FROM_HOME = 0.25
_SCORE_COMMIT_RISK = -400
_SCORE_KICK_PATH = -20_000
# A chord that lands on nobody is 14 updates of lock for nothing (Blaze).
_SCORE_WHIFF = -300
_SCORE_PER_LANE_CORNERED = 20


@dataclass(frozen=True, slots=True)
class TwinsPlan:
    """The stick and the buttons for this tick, and why."""

    dir_x: int
    dir_y: int
    chord: bool
    wall: int  # -1: the left edge is home, +1: the right
    outcome: str | None  # "strike" / "hit" / None within the horizon
    at_update: int | None
    score: float
    label: str


def _alive(t: TwinSim) -> bool:
    return not t.gone and t.hp > 0


def _is_grabber(t: TwinSim) -> bool:
    return bool(t.mode & model.MODE_GRAB_BIT)


def choose_wall(a: ActorSim, twins: Sequence[TwinSim]) -> int:
    """Which edge is home: the one that puts the grab twin behind the actor.

    With no grab twin alive, the nearest living twin decides. A twin level
    with the actor keeps the wall the actor already faces.
    """

    live = [t for t in twins if _alive(t)]
    if not live:
        return -1 if a.facing_left else 1
    grabbers = [t for t in live if _is_grabber(t)]
    pool = grabbers or live
    key = min(pool, key=lambda t: abs(t.x - a.x))
    dx = key.x - a.x
    if abs(dx) < 2:
        return -1 if a.facing_left else 1
    return -1 if dx > 0 else 1


def _home_x(a: ActorSim, wall: int) -> float:
    return a.x_lo if wall < 0 else a.x_hi


# --- The tail: a reactive policy the lookahead continues every program with ----


def _chord_box(a: ActorSim, step: int | None = None) -> tuple[int, int, int, int, int, int] | None:
    """The chord's box on ``step`` (its first live update by default), where
    the actor stands now."""

    schedule = model.chord_schedule(a.character)
    if step is None:
        step = model.chord_live_steps(a.character)[0]
    entry = schedule[step]
    attack_id = entry[2] if a.facing_left else entry[0]
    return model.box(attack_id, model._hi(a.x), model._hi(a.y), model._hi(a.z + entry[4]))


def _predicted_body(t: TwinSim, k: int) -> tuple | None:
    """Where the twin's body will be ``k`` updates on, if it keeps doing what
    it does: a walk on its velocity, a flying kick on its ballistic path. None
    when it will have no body box (a backflip, a knockdown)."""

    if t.primary == model.PRIMARY_ACTIVE:
        if (t.anim & ~model.ANIM_MIRROR) in (model.ANIM_FLIP, model.ANIM_JUMP_IN):
            return None
        x = t.x + t.vx * k
        y = min(max(t.y + t.vy * k, 0.0), float(model.BOSS_LANE_MAX))
        body = t.shown_body or (0x51 if not (t.anim & model.ANIM_MIRROR) else 0x52)
        return model.box(body, model._hi(x), model._hi(y), model._hi(t.z))
    if t.primary == model.PRIMARY_COMMIT and not _is_grabber(t):
        if t.t78 < model.KICK_WINDUP:
            return model.box(t.shown_body, model._hi(t.x), model._hi(t.y), model._hi(t.z)) if t.shown_body else None
        x, y, z, vz = t.x, t.y, t.z, t.vz
        for _ in range(k):
            if model._hi(z) == model._hi(t.ground) and vz >= 0:
                break
            vz += model.GRAVITY
            x += t.vx
            y = min(max(y + t.vy, 0.0), float(model.BOSS_LANE_MAX))
            z = min(z + vz, t.ground)
        body = 0x81 if not (t.anim & model.ANIM_MIRROR) else 0x82
        return model.box(body, model._hi(x), model._hi(y), model._hi(z))
    return None


def chord_would_land(a: ActorSim, twins: Sequence[TwinSim]) -> bool:
    """The tail's cheap test: a twin's predicted body inside the chord's box
    early in its live window (so a small misprediction still lands)."""

    if a.chord is not None:
        return False
    first, last = model.chord_live_steps(a.character)
    for t in twins:
        if not _alive(t):
            continue
        for k in range(first, first + max(2, last - first - 1)):
            reach = _chord_box(a, k)
            if reach is None:
                continue
            # The twin's update after the actor's step k tests the body where
            # it stood after k or k+1 of its own updates, by the order.
            for ahead in (k, k + 1):
                body = _predicted_body(t, ahead)
                if body is not None and model.overlaps(body, reach):
                    return True
    return False


def kick_threats(t: TwinSim, a: ActorSim, *, any_height: bool = False) -> list[tuple[int, float]]:
    """``(updates from now, lane)`` for every update the approach twin's
    flying kick could land on the actor where it stands -- box out, low
    enough, in reach on X -- from its ballistic path (a crouch still to go
    launches at the actor's lane as it is now)."""

    threats: list[tuple[int, float]] = []
    if not _alive(t) or t.primary != model.PRIMARY_COMMIT or _is_grabber(t) or t.pending:
        return threats
    x, y, z, vz, tt = t.x, t.y, t.z, t.vz, t.t78
    vx, vy = t.vx, t.vy
    k = 0
    if tt < model.KICK_WINDUP:
        k = model.KICK_WINDUP - tt
        dy = model._fixed(a.y) - model._fixed(y)
        vy = model._unfixed(dy >> 4)
        vx = -model.KICK_SPEED if a.x < x else model.KICK_SPEED
        vz = float(model.KICK_VZ)
        tt = model.KICK_WINDUP
        x += vx
        y += vy
        z += vz
    for _ in range(48):
        if model._hi(z) == model._hi(t.ground) and vz >= 0:
            break
        k += 1
        tt += 1
        vz += model.GRAVITY
        x += vx
        y = min(max(y + vy, 0.0), float(model.BOSS_LANE_MAX))
        z = min(z + vz, t.ground)
        # Box out from +$78 28 (animation $2C frame 2); low enough for a
        # standing body within 42 px of the floor -- or, for a chord that
        # hops (Adam's), anywhere: the hop lifts his body into the kick.
        if tt >= 28 and (any_height or t.ground - z <= 42) and abs(x - a.x) <= 64:
            threats.append((k, y))
    return threats


def _kick_lanes(t: TwinSim, a: ActorSim) -> list[float]:
    return [lane for _, lane in kick_threats(t, a)]


def _grabber_busy(twins: Sequence[TwinSim], a: ActorSim) -> bool:
    """No grab twin can reach the actor soon: every one down, or far."""

    for t in twins:
        if not _alive(t) or not _is_grabber(t):
            continue
        if t.primary in (model.PRIMARY_REACTION, model.PRIMARY_GET_UP) and t.hp > 0:
            continue
        if abs(t.x - a.x) > BUSY_DX:
            continue
        return False
    return True


def tail_action(a: ActorSim, twins: Sequence[TwinSim], wall: int) -> tuple[int, int, bool]:
    """The reactive policy every program continues with.

    The chord when a twin's body will be in its box -- unless a flying kick
    would land inside the chord's lock without that chord meeting it; a step
    off any flying kick's path; the approach twin's lane held while the grab
    twin is coming (so its kick never adds a second threat), left free while
    the grab twin is down or far (so it commits, and its kick is met or
    stepped off); the wall faced and the edge kept."""

    if a.chord is not None:
        return 0, 0, False
    threats = [
        (k, lane, t) for t in twins for k, lane in kick_threats(t, a)
    ]
    lock = len(model.chord_schedule(a.character)) + 1
    if chord_would_land(a, twins):
        hops = any(step[4] for step in model.chord_schedule(a.character))
        during = [
            (k, lane, t) for t in twins for k, lane in kick_threats(t, a, any_height=True)
        ] if hops else threats
        blocked = any(
            k <= lock and abs(lane - a.y) <= 18 and not _chord_meets(a, t)
            for k, lane, t in during
        )
        if not blocked:
            return 0, 0, True
    dir_y = 0
    near = [(k, lane) for k, lane, _ in threats if abs(lane - a.y) < DODGE_GAP]
    if near:
        lane = min(near)[1]
        room_up = a.y - a.lane_lo
        room_down = a.lane_hi - a.y
        if lane >= a.y:
            dir_y = -1 if room_up > 4 else 1
        else:
            dir_y = 1 if room_down > 4 else -1
    elif not threats and not _grabber_busy(twins, a):
        guards = [
            t for t in twins
            if _alive(t) and not _is_grabber(t) and t.primary == model.PRIMARY_ACTIVE
            and abs(t.x - a.x) < GUARD_DX
        ]
        if guards:
            t = min(guards, key=lambda o: abs(o.x - a.x))
            gap = t.y - a.y
            if abs(gap) > GUARD_GAP / 2:
                dir_y = 1 if gap > 0 else -1
    if not dir_y and not threats:
        # Room to step off a flying kick either way: back toward mid-band.
        if a.y < a.lane_lo + LANE_ROOM:
            dir_y = 1
        elif a.y > a.lane_hi - LANE_ROOM:
            dir_y = -1
    face = wall
    dir_x = 0
    if (face < 0) != a.facing_left:
        dir_x = face  # one step turns the actor
    elif face == wall and abs(a.x - _home_x(a, wall)) > 3 and not _twin_in_front(a, twins):
        dir_x = wall
    if dir_y and _twin_in_front(a, twins):
        # A lane step puts the walking box out, and a twin standing in front
        # of it is a hold (``$AAA0``, the actor's box on its body).
        dir_y = 0 if not near else dir_y
    return dir_x, dir_y, False


def facing_side(a: ActorSim, twins: Sequence[TwinSim], wall: int) -> int:
    """Which way the actor should face (-1 left, +1 right): its back to the
    twin whose body will come to it next.

    The grab twin, while it is coming: facing it is its jump-in (``$15C72``).
    With the grab twin down or far, a flying kick in the air: its back to
    the kicker, so the rear attack meets it on the way down or on its
    landing. Otherwise the wall."""

    live = [t for t in twins if _alive(t)]
    if not _grabber_busy(live, a):
        grabbers = [t for t in live if _is_grabber(t) and t.primary not in (model.PRIMARY_REACTION, model.PRIMARY_GET_UP)]
        if grabbers:
            key = min(grabbers, key=lambda t: abs(t.x - a.x))
            if abs(key.x - a.x) >= 2:
                return -1 if key.x > a.x else 1
    kickers = [t for t in live if _airborne_kick(t)]
    if kickers:
        key = min(kickers, key=lambda t: abs(t.x - a.x))
        # Where it will come down: its X velocity is fixed from the launch.
        land_x = key.x + key.vx * max(0, 38 - key.t78) if key.t78 >= model.KICK_WINDUP else key.x
        if abs(land_x - a.x) >= 2:
            return -1 if land_x > a.x else 1
    return wall


def _twin_in_front(a: ActorSim, twins: Sequence[TwinSim]) -> bool:
    """A grounded twin body within the walking box's reach ahead."""

    for t in twins:
        if not _alive(t) or not t.shown_body:
            continue
        ahead = (t.x - a.x) * (-1 if a.facing_left else 1)
        if -4 <= ahead <= 40 and abs(t.y - a.y) <= 20 and model._on_floor(t):
            return True
    return False


def _chord_meets(a: ActorSim, t: TwinSim) -> bool:
    """Would a chord pressed now meet this twin's body in its live window?"""

    first, last = model.chord_live_steps(a.character)
    for k in range(first, last + 1):
        reach = _chord_box(a, k)
        if reach is None:
            continue
        for ahead in (k, k + 1):
            body = _predicted_body(t, ahead)
            if body is not None and model.overlaps(body, reach):
                return True
    return False


# --- The lookahead ---------------------------------------------------------------


@dataclass(slots=True)
class _Program:
    first: tuple[int, int]
    first_updates: int
    chord_at: int | None
    label: str

    def advanced(self, updates: int = 1) -> _Program:
        """The same program one tick on: its stick held that much less, its
        chord that much sooner."""

        chord_at = None if self.chord_at is None else max(0, self.chord_at - updates)
        if self.chord_at is not None and self.chord_at - updates < 0:
            chord_at = None  # already pressed
        return _Program(
            self.first, max(0, self.first_updates - updates), chord_at, f"{self.label}~"
        )


class PlanMemory:
    """The program the last tick chose, so the next one can keep to it.

    A receding horizon re-chooses every tick among programs that score alike,
    and the trajectory it walks then matches none of them: measured offline,
    an intercept ("walk down-right 12 updates, then the tail's chord") won one
    tick and lost the next to a near-tie, three times over, until the chord
    came an update late. The last choice, advanced by the ticks since, is
    scored again with ``STICKY`` added, so it is kept unless something is
    really better."""

    __slots__ = ("program",)

    def __init__(self) -> None:
        self.program: _Program | None = None


def _programs(wall: int, free: bool, kick_in_air: bool = False) -> list[_Program]:
    # The tail from now first: it wins every tie, so a plan that sees nothing
    # better does what the tail would -- a "stand one update, then the tail"
    # program winning a tie would stand, re-plan, and stand again.
    programs: list[_Program] = [_Program((0, 0), 0, None, "tail")]
    if free:
        programs.append(_Program((0, 0), 0, 0, "chord"))
    sticks = [(0, 0), (0, -1), (0, 1), (wall, 0), (wall, -1), (wall, 1)]
    if kick_in_air:
        # A flying kick in the air: the tail's step off its path decides every
        # update. A held stick that steps toward the path "for now" is chosen
        # again next tick, and again -- measured offline, the step off never
        # came. Only the chord competes with the tail then.
        sticks = [(0, 0)]
    for stick in sticks:
        for updates in FIRST_DURATIONS:
            programs.append(_Program(stick, updates, None, f"{stick}x{updates}"))
    if free:
        for delay in CHORD_DELAYS:
            for stick in ((0, 0),) if kick_in_air else ((0, 0), (0, -1), (0, 1)):
                programs.append(_Program(stick, delay, delay, f"{stick}x{delay}+chord"))
    return programs


@dataclass(slots=True)
class _Result:
    hit_at: int | None
    strikes: list[tuple[int, int]]
    held: int
    twins: list[TwinSim]
    actor: ActorSim
    whiffs: int = 0
    # The chord pressed on the program's first update, if it presses one:
    # whether it struck (None: its first update pressed nothing).
    now_struck: bool | None = None


def _airborne_kick(t: TwinSim) -> bool:
    return _alive(t) and t.primary == model.PRIMARY_COMMIT and not _is_grabber(t) and not t.pending


# The timing the decision lands at, which the plan cannot see: the snapshot
# can fall before the player's update or before the objects' ($AD8E), and the
# stick written after planning can miss the next player update and land on the
# one after -- measured live at 2x turbo (120 fps, ~2.2 ms a snapshot, ~1.4
# frames a tick): 0-1 player updates of lead. Every program is scored by the
# worst of the five, with the stick already held (``committed``) playing the
# lead.
PLAYER_FIRST, OBJECTS_FIRST = True, False
# (which update comes first, player updates on the held stick, the first
# decision held one update longer -- the next tick late).
SCENARIOS: tuple[tuple[bool, int, bool], ...] = (
    (OBJECTS_FIRST, 1, False),
    (PLAYER_FIRST, 1, False),
    (OBJECTS_FIRST, 0, False),
    (PLAYER_FIRST, 0, False),
    (OBJECTS_FIRST, 0, True),
)


def _rollout(
    twins0: Sequence[TwinSim],
    a0: ActorSim,
    program: _Program,
    wall: int,
    *,
    player_first: bool,
    lead: int = 0,
    committed: tuple[int, int] = (0, 0),
    overrun: bool = False,
) -> _Result:
    twins = [t.copy() for t in twins0]
    model.link_pair(twins)
    a = a0.copy()
    strikes: list[tuple[int, int]] = []
    held = 0
    player_updates = 0
    moves = 0
    chords: list[bool] = []  # one per chord pressed: did it strike?

    first_stick: list[tuple[int, int]] = []
    now_index: list[int] = []

    def act() -> None:
        nonlocal moves, player_updates
        player_updates += 1
        if player_updates <= lead:
            actor_update(a, *committed)
            return
        if overrun and moves == 1 and first_stick:
            # The next tick came late: the first stick is still held.
            actor_update(a, *first_stick[0])
            moves += 1
            return
        if program.chord_at is not None and moves == program.chord_at and a.chord is None:
            actor_update(a, 0, 0, True)
            chords.append(False)
            if moves == 0:
                now_index.append(len(chords) - 1)
        elif moves < program.first_updates:
            actor_update(a, *program.first)
            if moves == 0:
                first_stick.append(program.first)
        else:
            dx, dy, chord = tail_action(a, twins, wall)
            if chord and a.chord is None:
                chords.append(False)
                if moves == 0:
                    now_index.append(len(chords) - 1)
            elif moves == 0:
                first_stick.append((dx, dy))
            actor_update(a, dx, dy, chord)
        moves += 1

    def now_struck() -> bool | None:
        return chords[now_index[0]] if now_index else None

    def whiffs() -> int:
        # A chord still on its frames at the end may yet land: not a whiff.
        closed = chords[:-1] if a.chord is not None and chords else chords
        return sum(1 for struck in closed if not struck)

    if player_first:
        act()
    k = 0
    while True:
        outcomes = object_pass(twins, a)
        for t, outcome in zip(twins, outcomes):
            if outcome in (Outcome.HIT, Outcome.GRABBED):
                return _Result(k, strikes, held, twins, a, whiffs(), now_struck())
            if outcome is Outcome.STRUCK:
                strikes.append((k, t.slot))
                if chords:
                    chords[-1] = True
            elif outcome is Outcome.HELD:
                held += 1
        k += 1
        if k >= HORIZON_MAX or (k >= HORIZON and not any(_airborne_kick(t) for t in twins)):
            break
        act()
    return _Result(None, strikes, held, twins, a, whiffs(), now_struck())


def _score(result: _Result, wall: int) -> float:
    if result.hit_at is not None:
        return _SCORE_HIT + _SCORE_HIT_PER_UPDATE * result.hit_at
    score = 0.0
    for at, _slot in result.strikes:
        score += _SCORE_STRIKE - _SCORE_STRIKE_PER_UPDATE * at
    score += _SCORE_HELD * result.held
    score += _SCORE_WHIFF * result.whiffs
    a = result.actor
    score -= _SCORE_PER_PX_FROM_HOME * abs(a.x - _home_x(a, wall))
    room = min(a.y - a.lane_lo, a.lane_hi - a.y)
    if room < LANE_ROOM:
        score -= _SCORE_PER_LANE_CORNERED * (LANE_ROOM - room)
    for t in result.twins:
        if not _alive(t) or _is_grabber(t):
            continue
        if t.primary == model.PRIMARY_ACTIVE and t.d50 < model.COMMIT_DX + 8:
            if model.COMMIT_LANE_MIN - 2 <= abs(t.y - a.y) < model.COMMIT_LANE_MAX + 2:
                score += _SCORE_COMMIT_RISK
        if _airborne_kick(t):
            lanes = _kick_lanes(t, a)
            if any(abs(lane - a.y) <= 16 for lane in lanes):
                score += _SCORE_KICK_PATH
    return score


def plan(
    a: ActorSim,
    twins: Sequence[TwinSim],
    *,
    wall: int | None = None,
    committed: tuple[int, int] = (0, 0),
    scenarios: Sequence[tuple[bool, int, bool]] = SCENARIOS,
    trace: list | None = None,
    memory: PlanMemory | None = None,
) -> TwinsPlan:
    """The stick and buttons for this tick: every program played out under
    every timing scenario, scored by the worst. A program whose running worst
    already falls below the best found is dropped without the rest."""

    wall = choose_wall(a, twins) if wall is None else wall
    free = a.chord is None and not a.unavailable
    best: TwinsPlan | None = None
    best_program: _Program | None = None
    kick_in_air = any(kick_threats(t, a) for t in twins)
    programs = _programs(wall, free, kick_in_air)
    # A chord is pressed only when it lands (user: "não quero que dê ataques
    # em falso"): a program that presses now is admissible only if that press
    # strikes a twin under every timing -- dropped, not merely scored down.
    tail_presses_now = free and tail_action(a, twins, wall)[2]
    kept: _Program | None = None
    if memory is not None and memory.program is not None:
        kept = memory.program.advanced()
        # Not a chord still to come: a tick is not exactly an update, and a
        # press carried from tick to tick drifts late (measured offline: a
        # "chord in 4" kept three ticks fired as a whiff into a flying kick);
        # the chord is scored fresh every tick. Not a step while a kick is in
        # the air either (above).
        if (
            kept.chord_at is not None
            or kept.first_updates <= 0
            or (kick_in_air and kept.first != (0, 0))
        ):
            kept = None
        else:
            programs = [kept] + programs
    for program in programs:
        presses_now = program.chord_at == 0 or (
            program.first_updates == 0 and program.chord_at is None and tail_presses_now
        )
        worst: tuple[float, _Result] | None = None
        admissible = True
        for player_first, lead, overrun in scenarios:
            result = _rollout(
                twins, a, program, wall, player_first=player_first, lead=lead,
                committed=committed, overrun=overrun,
            )
            score = _score(result, wall)
            if trace is not None:
                trace.append(
                    (program.label, player_first, lead, overrun, round(score), result.hit_at,
                     result.strikes, result.whiffs)
                )
            if worst is None or score < worst[0]:
                worst = (score, result)
            if presses_now and result.now_struck is not True:
                admissible = False
                if trace is None:
                    break
            if trace is None and best is not None and worst[0] <= best.score:
                break
        assert worst is not None
        if not admissible:
            continue
        score, result = worst
        if program is kept and result.hit_at is None:
            score += STICKY
        if best is None or score > best.score:
            best_program = program
            if program.chord_at == 0:
                dir_x, dir_y, chord = 0, 0, True
            elif program.first_updates > 0:
                dir_x, dir_y = program.first
                chord = False
            else:
                dir_x, dir_y, chord = tail_action(a, twins, wall)
            outcome = "hit" if result.hit_at is not None else ("strike" if result.strikes else None)
            at = result.hit_at if result.hit_at is not None else (result.strikes[0][0] if result.strikes else None)
            best = TwinsPlan(
                dir_x=dir_x, dir_y=dir_y, chord=chord, wall=wall, outcome=outcome,
                at_update=at, score=score, label=program.label,
            )
    if best is None:
        # Every program pressed a chord that could miss: stand still instead.
        best = TwinsPlan(
            dir_x=0, dir_y=0, chord=False, wall=wall, outcome=None, at_update=None,
            score=float("-inf"), label="hold",
        )
    elif best.chord and best_program is not None and best_program.chord_at != 0 and not tail_presses_now:
        best = TwinsPlan(
            dir_x=best.dir_x, dir_y=best.dir_y, chord=False, wall=wall, outcome=best.outcome,
            at_update=best.at_update, score=best.score, label=best.label,
        )
    if memory is not None:
        memory.program = best_program
    return best
