"""Mr. X: the plan -- take one hold, and never give him a turn back.

On the ROM model in ``mr_x.py``. What makes it the plan:

1. **The hold loop.** His hold (state ``$A``) reads the holder's ``+$7D`` on
   one substate only; a knee there is 2 points and 12 updates of shake, and
   a release there sends him to the retreat, whose first update tests contact
   where he stands, 24 px in front of the actor -- before he moves. A walk
   straight back in is the re-grab, 3 frames after the release (measured in
   lockstep, ``tools/mr_x_lab.py --actor hold``). Knee, knee, release: 4
   points every ~30 updates, and he never acts. ``hold_step`` below.
2. **Taking the hold** (``plan``): a lookahead over his AI and every bullet,
   the nine sticks each held a while and then handed to a tail policy
   (``tail_action``), each played under five update timings and scored by
   the worst -- a hold by how soon, a hit (his lunge, 34 on Normal, or a
   bullet, 20) below everything. What it finds, each from his code:

   - *the gun*: walking up to lane 2.5, waiting there 21 updates and firing,
     he has no box out at all -- walking into him is a hold;
   - *the walk-in*: he closes the lane 8 px an update while the gap is 16 or
     more and tests contact after the step; a walking box already on his X
     (``dx`` 0..27, facing him) with the lane gap 16..23 before his step is a
     hold on it, and never a lunge (his range test ran first);
   - *the lunge*: its box reaches 64 px ahead for 11 updates but only 8
     lanes either side: 17 lanes off it misses, and the retreat's first
     update, where the lunge left him, is the hold.
3. Bullets whose slot sits below his are set up a pass late, which moves
   their whole flight an update; the rollouts fire each bullet both ways.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from . import garcia as garcia_model
from . import mr_x as model
from .mr_x import BulletSim, MrXSim, Outcome
from .mr_x import actor_step
from .twins import BLAZE, WALK_SPEEDS, ActorSim

__all__ = ["MrXPlan", "PlanMemory", "garcia_hold_step", "garcia_threat", "hold_step", "holder_blow", "plan", "tail_action"]

HORIZON = 32
HORIZON_GUN = 44  # while he walks up, waits or fires
FIRST_DURATIONS = (1, 3, 6, 12)
STICKS = ((0, 0), (0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1))
STICKY = 150.0
GRAB_SCORE = 100_000.0
STRUCK_SCORE = 20_000.0
PUNCH_DELAYS = (0, 1, 2, 3, 4, 5)
HIT_SCORE = -1_000_000.0

# The walking box on his body: a Blaze-sized reach (0..19) plus his +-8.
GRAB_REACH_X = 14
# Out of the lunge's lane band (his +-8 against a body's +-8, inclusive).
LUNGE_CLEAR_LANE = 18
# The walk-in's step lands on this lane gap: in [16, 24) it steps 8 and
# tests; the tail waits a little wider.
STEP_IN_LANE = 20

PLAYER_FIRST, OBJECTS_FIRST = True, False
SCENARIOS: tuple[tuple[bool, int, bool], ...] = (
    (OBJECTS_FIRST, 1, False),
    (PLAYER_FIRST, 1, False),
    (OBJECTS_FIRST, 0, False),
    (PLAYER_FIRST, 0, False),
    (OBJECTS_FIRST, 0, True),
)


@dataclass(frozen=True, slots=True)
class MrXPlan:
    dir_x: int
    dir_y: int
    outcome: str | None  # "grab", "struck", "hit" or None
    at_update: int | None
    score: float
    label: str
    mode: str
    punch: bool = False  # press B this tick (the punch lands under every timing)
    chord: bool = False  # press B+C this tick (the rear attack lands under every timing)


@dataclass(frozen=True, slots=True)
class _Program:
    first: tuple[int, int]
    first_updates: int
    label: str
    punch_at: int | None = None
    chord_at: int | None = None
    # Where the first stick leaves the actor: kept from tick to tick by the
    # distance still to go, not by ticks -- a tick is not exactly an update,
    # and the step-in and the lunge's lane dodge are a lane or two wide.
    target: tuple[float, float] | None = None

    def advanced_from(self, a: ActorSim) -> _Program:
        """The same program from where the actor now stands. A punch still to
        come is scored fresh every tick, not carried."""

        if self.target is None or self.first_updates <= 0:
            return _Program(self.first, 0, f"{self.label}~")
        straight_x, diagonal_x, diagonal_y, straight_y = _speeds(a)
        dx, dy = self.first
        step_x = diagonal_x if dy else straight_x
        step_y = diagonal_y if dx else straight_y
        left = 0
        if dx:
            left = max(left, math.ceil(max(0.0, (self.target[0] - a.x) * dx) / step_x - 1e-9))
        if dy:
            left = max(left, math.ceil(max(0.0, (self.target[1] - a.y) * dy) / step_y - 1e-9))
        return _Program(self.first, min(left, self.first_updates), f"{self.label}~", target=self.target)


def _speeds(a: ActorSim) -> tuple[float, float, float, float]:
    return WALK_SPEEDS.get(a.character, WALK_SPEEDS[BLAZE])


def _target(a: ActorSim, stick: tuple[int, int], updates: int) -> tuple[float, float]:
    straight_x, diagonal_x, diagonal_y, straight_y = _speeds(a)
    dx, dy = stick
    step_x = diagonal_x if dy else straight_x
    step_y = diagonal_y if dx else straight_y
    x = min(max(a.x + dx * step_x * updates, a.x_lo), a.x_hi)
    y = min(max(a.y + dy * step_y * updates, a.lane_lo), a.lane_hi)
    return x, y


class PlanMemory:
    """The last tick's program, kept unless something is really better (the
    receding horizon's near-ties otherwise walk a path none of them had)."""

    __slots__ = ("program",)

    def __init__(self) -> None:
        self.program: _Program | None = None


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def _toward(value: float, target: float, dead: float = 1.5) -> int:
    if value < target - dead:
        return 1
    if value > target + dead:
        return -1
    return 0


def _lane_room(a: ActorSim, lane: float) -> float:
    return min(max(lane, a.lane_lo + 1), a.lane_hi - 1)


def _lunge_end_x(m: MrXSim) -> float:
    """Where the lunge's dash leaves him (``$13DE6``: ``+$1C`` += ``+$5E``,
    then the move, until ``+$54`` runs out)."""

    x, vx, acc, steps = m.x, m.vx, m.acc, m.t54 - 1
    if m.primary == model.PRIMARY_WALK_IN or m.sub == 0:
        # Not set up yet: 18 toward his facing, 2 off before each of 4 moves.
        facing = -1 if m.facing_left else 1
        vx, acc, steps = facing * model.LUNGE_SPEED, -facing * model.LUNGE_DECEL, model.LUNGE_DASH - 1
    elif m.sub != 1:
        return x
    for _ in range(max(0, steps)):
        vx += acc
        x += vx
    return x


def _side(a: ActorSim, m: MrXSim) -> int:
    """Which side of him the actor stands on (+1 to his right)."""

    s = _sign(a.x - m.x)
    if s == 0:
        s = -1 if a.facing_left else 1
    return s


def engage_mode(m: MrXSim) -> str:
    """What the tail does about him, by what his next decision reads."""

    p = m.primary
    if p == model.PRIMARY_GUN:
        return "gun"
    if p == model.PRIMARY_LUNGE:
        return "lunge"
    if (p == model.PRIMARY_RETREAT and m.sub == 0) or p in (model.PRIMARY_HURT, model.PRIMARY_HELD):
        # The retreat's first update tests contact where he stands, before he
        # moves -- after a release, a punch's shake or the lunge.
        return "regrab"
    if p in (model.PRIMARY_WALK_IN, model.PRIMARY_REPOSITION):
        return "close"
    # He decides next, or will once up or done backing off: $130EE walks in
    # under $80 on X and goes to the gun beyond it.
    return "keep_away"


# $130EE: at |dx| of $80 or more, on screen, he goes to the gun.
KEEP_AWAY_DX = 0x80 + 16

# Home: pressed against the camera's right edge (cam + $120), facing the
# wall. A Garcia coming from the right aims 32 px past the actor ($9648) --
# screen X $1C0, off screen, where his punch is refused ($92AC: $DBCC
# instead) and his arrival turns him to $DBCC as well: from the right no
# Garcia strikes. One from the left comes at the actor's back, into the rear
# attack (B+C: Blaze's box 5-53 px behind, a knockdown on every live update).
# Exactly on the clamp: one step off it (3.25 px) and his point is back on
# screen. (The left edge has no such pocket: his point there is screen X $80,
# on screen.) Measured before it: the two Garcias arriving from both sides at
# once, at the street's top or bottom edge, were most of a fight's hits.
HOME_DEAD_X = 0.5


def _home_x(a: ActorSim) -> float:
    return a.x_hi


def _keep_away_x(a: ActorSim, m: MrXSim) -> float:
    """Where to stand so his decision reads the gun: home when he is that far
    to its left; else this far out on the side with room, the actor's own
    side first."""

    if _home_x(a) - m.x >= KEEP_AWAY_DX:
        return _home_x(a)
    side = _side(a, m)
    for s in (side, -side):
        x = m.x + s * KEEP_AWAY_DX
        if a.x_lo + 2 <= x <= a.x_hi - 2:
            return x
    return a.x_hi - 2 if m.x - a.x_lo < a.x_hi - m.x else a.x_lo + 2


def _at_home_facing_the_wall(a: ActorSim, dx: int, aim_x: float) -> int:
    """At home, the stick's X: into the clamp to turn to the wall (it does not
    move), else ``dx``."""

    if dx == 0 and aim_x == _home_x(a) and a.facing_left:
        return 1
    return dx


def _street_lane(a: ActorSim) -> float:
    """The actor's lane, off the street's edges."""

    return min(max(a.y, a.lane_lo + EDGE_MARGIN), a.lane_hi - EDGE_MARGIN)


def _garcia_tail(a: ActorSim, garcias: Sequence) -> tuple[int, int]:
    """With him not there (the office's first waves): home, facing the wall,
    off the street's edges -- the Garcias come at the actor's back, into the
    rear attack."""

    home = _home_x(a)
    dx = _at_home_facing_the_wall(a, _toward(a.x, home, HOME_DEAD_X), home)
    return dx, _toward(a.y, _street_lane(a), 3)


# Keep-away's lane: off his by this much, on the side with room, and never
# on the street's edges -- a Garcia coming up the street corners an actor there.
KEEP_AWAY_LANE = 32
EDGE_MARGIN = 20


def _keep_away_lane(a: ActorSim, m: MrXSim) -> float:
    lo, hi = a.lane_lo + EDGE_MARGIN, a.lane_hi - EDGE_MARGIN
    above, below = m.y - KEEP_AWAY_LANE, m.y + KEEP_AWAY_LANE
    options = [lane for lane in (above, below) if lo <= lane <= hi]
    if not options:
        return min(max(m.y + (KEEP_AWAY_LANE if m.y < (lo + hi) / 2 else -KEEP_AWAY_LANE), lo), hi)
    return min(options, key=lambda lane: abs(lane - a.y))


def tail_action(a: ActorSim, m: MrXSim | None, garcias: Sequence = ()) -> tuple[int, int]:
    """The stick the rollouts hand over to once their program runs out."""

    if m is None:
        return _garcia_tail(a, garcias)
    if m.gone or m.primary in (model.PRIMARY_HELD_BACK, model.PRIMARY_DYING):
        return 0, 0
    if m.primary == model.PRIMARY_HELD and a.holding:
        return 0, 0
    mode = engage_mode(m)
    side = _side(a, m)
    dl = a.y - m.y
    lane_side = _sign(dl) or (1 if m.y < 56 else -1)
    if mode in ("gun", "regrab"):
        # No box of his is out: into him, the walking box first.
        aim_x = m.x + side * (GRAB_REACH_X - 4)
        aim_y = model.GUN_LANE if (mode == "gun" and m.sub <= 1) else m.y
        dx = _toward(a.x, aim_x)
        if dx == 0:
            dx = -side  # keep walking into him: the box is out only while walking
        return dx, _toward(a.y, aim_y)
    if mode == "lunge":
        end_x = _lunge_end_x(m)
        aim_y = _lane_room(a, m.y + lane_side * LUNGE_CLEAR_LANE)
        if abs(aim_y - m.y) < LUNGE_CLEAR_LANE:
            aim_y = _lane_room(a, m.y - lane_side * LUNGE_CLEAR_LANE)
        aim_x = end_x + side * GRAB_REACH_X
        return _toward(a.x, aim_x), _toward(a.y, aim_y, 0.5)
    if mode == "keep_away":
        aim_x = _keep_away_x(a, m)
        aim_y = _keep_away_lane(a, m)
        dx = _at_home_facing_the_wall(a, _toward(a.x, aim_x, HOME_DEAD_X), aim_x)
        return dx, _toward(a.y, aim_y, 3)
    # Walking in or repositioning at the actor: the lane he closes 8 at a time
    # kept as wide as it goes, the walking box on his X.
    aim_x = m.x + side * GRAB_REACH_X
    aim_y = a.lane_hi - 1 if lane_side > 0 else a.lane_lo + 1
    dx = _toward(a.x, aim_x, 3)
    dy = _toward(a.y, aim_y, 1)
    facing_him = a.facing_left == (side > 0)
    if dx == 0 and not facing_him:
        dx = -side  # the walking box points the way the actor faces
    return dx, dy


@dataclass(slots=True)
class _Result:
    hit_at: int | None
    grab_at: int | None
    actor: ActorSim
    boss: MrXSim | None
    struck_at: int | None = None
    now_struck: bool | None = None  # a punch pressed on the first update: did it land?
    hit_damage: int = 0
    garcia_held_at: int | None = None  # the walking box took a Garcia instead
    garcias: tuple = ()
    burnt_at: int | None = None  # his hold, but a blow lands before a knee can be spent


def _double(bullets: Sequence[BulletSim]) -> list[BulletSim]:
    return [b.copy() for b in bullets]


# Damage a hit costs on Normal: his lunge, a bullet, a Garcia's jab or punch.
DAMAGE = {"m": 34, "b": 20, "g": 8}


def _object_pass(m: MrXSim | None, garcias: list, bullets: list[BulletSim], a: ActorSim) -> list[tuple[str, str]]:
    """One object pass: the bullets in flight, then him and his Garcias in slot
    order, then his new bullets' set-up -- (who, outcome name) per contact."""

    events: list[tuple[str, str]] = []
    for b in bullets:
        out = model.bullet_update(b, a)
        if out is not Outcome.NONE:
            events.append(("b", out.name))
    order = [(g.slot, "g", g) for g in garcias if g.alive]
    if m is not None and not m.gone:
        order.append((m.slot, "m", m))
    order.sort(key=lambda item: item[0])
    spawned: list[BulletSim] = []
    for _, kind, obj in order:
        if kind == "g":
            out = garcia_model.garcia_update(obj, a)
        else:
            out = model.mr_x_update(obj, a, rng=1, spawned=spawned)
            model.emit(obj)
        if out.name != "NONE":
            events.append((kind, out.name))
    for b in spawned:
        late = b.copy()
        late.fresh = False
        late.delay = 1
        b.fresh = False
        bullets.extend((b, late))
    bullets[:] = [b for b in bullets if b.state == 1]
    return events


def _rollout(
    m0: MrXSim | None,
    bullets0: Sequence[BulletSim],
    a0: ActorSim,
    program: _Program,
    *,
    player_first: bool,
    lead: int,
    committed: tuple[int, int],
    overrun: bool,
    horizon: int,
    garcias0: Sequence = (),
) -> _Result:
    m = m0.copy() if m0 is not None else None
    garcias = [g.copy() for g in garcias0]
    bullets = _double(bullets0)
    a = a0.copy()
    moves = 0
    player_updates = 0
    first_stick: list[tuple[int, int]] = []
    pressed_now: list[bool] = []
    struck_at: int | None = None

    def act() -> None:
        nonlocal moves, player_updates
        player_updates += 1
        a.latch = 0
        if player_updates <= lead:
            actor_step(a, *committed)
            return
        if overrun and moves == 1 and first_stick:
            actor_step(a, *first_stick[0])
            moves += 1
            return
        if program.punch_at is not None and moves == program.punch_at and a.punch is None:
            actor_step(a, 0, 0, punch=True)
            if moves == 0:
                pressed_now.append(True)
            moves += 1
            return
        if program.chord_at is not None and moves == program.chord_at and a.chord is None and a.punch is None:
            actor_step(a, 0, 0, chord=True)
            if moves == 0:
                pressed_now.append(True)
            moves += 1
            return
        if moves < program.first_updates:
            stick = program.first
        else:
            stick = tail_action(a, m, garcias)
        if moves == 0:
            first_stick.append(stick)
        actor_step(a, *stick)
        moves += 1

    def result(**kw) -> _Result:
        now = None if not pressed_now else struck_at is not None
        return _Result(actor=a, boss=m, struck_at=struck_at, now_struck=now, garcias=tuple(garcias), **kw)

    if player_first:
        act()
    for k in range(horizon):
        events = _object_pass(m, garcias, bullets, a)
        for who, what in events:
            if what == "STRUCK" and struck_at is None:
                struck_at = k
        for who, what in events:
            if what == "HIT":
                return result(hit_at=k, grab_at=None, hit_damage=DAMAGE[who])
        for who, what in events:
            if what == "GRAB" and who == "m":
                blow = _hold_burn(garcias, bullets, a)
                if blow is not None and blow[0] < HOLD_ESCAPE_UPDATES:
                    # Too soon even to let go: the hold is the blow.
                    return result(hit_at=k + blow[0], grab_at=None, hit_damage=blow[1])
                if blow is not None:
                    return result(hit_at=None, grab_at=None, burnt_at=k)
                return result(hit_at=None, grab_at=k)
            if what == "GRAB" and who == "g":
                if m is not None:
                    # Held, the actor stands a knee and a release at least:
                    # whatever lands on it then -- his lunge, the other
                    # Garcia, a bullet -- is what the hold cost.
                    others = [g for g in garcias if g.alive and g.state != garcia_model.ST_HELD]
                    blow = holder_blow(m, others, bullets, a, GARCIA_KNEE_UPDATES)
                    if blow is not None:
                        return result(hit_at=k + blow[0], grab_at=None, hit_damage=blow[1])
                return result(hit_at=None, grab_at=None, garcia_held_at=k)
        if m is not None and m.primary == model.PRIMARY_DYING:
            return result(hit_at=None, grab_at=k)
        act()
    return result(hit_at=None, grab_at=None)


# The hold, timed from the grab: he stands on the next update and reads on
# the one after; a knee on that read locks the holder 9 updates, a release
# ~4 (the back press), and a free actor needs ~3 more to step off a jab or
# have a punch out. A blow landing before HOLD_KNEE_SAFE_UPDATES leaves no
# knee to spend -- the hold is let go at once, worth nothing (and he backs
# off) -- and one before HOLD_ESCAPE_UPDATES lands on the holder.
HOLD_ESCAPE_UPDATES = 7
HOLD_KNEE_SAFE_UPDATES = 18
BURNT_GRAB_SCORE = -3_000.0


# A Garcia in hand: the throw (B+back) locks the holder 41-46 frames, a knee
# 17-18 and the release after it ~8 (kinematics.HOLD_*_FRAMES).
GARCIA_THROW_UPDATES = 23
GARCIA_KNEE_UPDATES = 9 + 4


def holder_blow(m: MrXSim | None, garcias: Sequence, bullets: Sequence[BulletSim], a: ActorSim,
                updates: int = HOLD_KNEE_SAFE_UPDATES) -> tuple[int, int] | None:
    """The first blow on a holder standing where it is for ``updates`` -- a
    Garcia's jab or punch, a bullet already fired, his lunge (``m``: None when
    he is the one in hand, and then he has no box out) -- as (updates from
    now, damage), or None. Played through ``garcia.py`` and ``mr_x.py``."""

    if m is None and not bullets and not any(g.alive for g in garcias):
        return None
    h = a.copy()
    h.holding = True
    h.walking = False
    h.punch = None
    h.vx = 0.0
    h.attack = None
    h.damage = 0
    model.refresh_boxes(h, h.x, h.y)
    boss = m.copy() if m is not None else None
    sims = [g.copy() for g in garcias]
    shots = _double(bullets)
    for j in range(updates):
        h.latch = 0
        if h.blink:
            model.blink_step(h)
            model.refresh_boxes(h, h.x, h.y)
        for who, what in _object_pass(boss, sims, shots, h):
            if what == "HIT":
                return j, DAMAGE[who]
    return None


def _hold_burn(garcias: Sequence, bullets: Sequence[BulletSim], a: ActorSim,
               updates: int = HOLD_KNEE_SAFE_UPDATES) -> tuple[int, int] | None:
    """His hold, from the grab: the first blow on the holder (``holder_blow``
    with him in hand)."""

    return holder_blow(None, garcias, bullets, a, updates)


def garcia_hold_step(a: ActorSim, m: MrXSim | None, garcias: Sequence, bullets: Sequence[BulletSim]) -> str:
    """One of his Garcias in hand while he lives: "throw" when nothing lands
    on the holder through the throw's lock (the Garcia is laid down 100 px
    and more away, and knocks down whatever stands behind the actor, Mr. X
    included); else "knee" when a knee and the release after it fit; else
    "release"."""

    if holder_blow(m, garcias, bullets, a, GARCIA_THROW_UPDATES) is None:
        return "throw"
    if holder_blow(m, garcias, bullets, a, GARCIA_KNEE_UPDATES) is None:
        return "knee"
    return "release"


# Scores: his hold is the plan; with him gone (the office's first waves) a
# Garcia's hold is the kill, and a strike on one buys its 24 updates of hitstun.
GARCIA_HOLD_SCORE = 60_000.0
GARCIA_HOLD_WITH_HIM = -5_000.0
GARCIA_STRUCK_SCORE = 8_000.0


def _score(result: _Result) -> float:
    if result.hit_at is not None:
        return HIT_SCORE + 100.0 * result.hit_at - 1000.0 * result.hit_damage
    if result.burnt_at is not None:
        return BURNT_GRAB_SCORE - 100.0 * result.burnt_at
    if result.grab_at is not None:
        return GRAB_SCORE - 100.0 * result.grab_at + (500.0 if result.struck_at is not None else 0.0)
    m = result.boss
    if result.garcia_held_at is not None:
        if m is None:
            return GARCIA_HOLD_SCORE - 100.0 * result.garcia_held_at
        return GARCIA_HOLD_WITH_HIM
    a = result.actor
    if m is None:
        base = -(abs(a.x - _home_x(a)) * 0.5 + abs(a.y - _street_lane(a)))
        if result.struck_at is not None:
            base += GARCIA_STRUCK_SCORE - 100.0 * result.struck_at
        return base
    if result.struck_at is not None:
        # A punch: 1 point and a shake -- his or a Garcia's -- no hold.
        return STRUCK_SCORE - 100.0 * result.struck_at
    # Nothing decided in the horizon: how the end suits what he does next.
    mode = engage_mode(m)
    dx = abs(a.x - m.x)
    dl = abs(a.y - m.y)
    if mode in ("gun", "regrab"):
        return -(dx + dl) * 1.0
    if mode == "keep_away":
        edge = min(a.y - a.lane_lo, a.lane_hi - a.y)
        return (
            -max(0.0, KEEP_AWAY_DX - dx) * 2.0 - max(0.0, 24 - dl) - max(0.0, EDGE_MARGIN - edge)
            - abs(a.x - _keep_away_x(a, m)) * 0.25
        )
    if mode == "lunge":
        return -max(0.0, LUNGE_CLEAR_LANE - dl) * 20.0 - abs(dx - GRAB_REACH_X) * 0.5
    return dl * 1.0 - abs(dx - GRAB_REACH_X) * 0.5


CHORD_DELAYS = (0, 1, 2, 3, 4, 5)


def _programs(a: ActorSim, m: MrXSim | None, free: bool, garcias: Sequence = (),
              can_chord: bool = False) -> list[_Program]:
    programs = [_Program((0, 0), 0, "tail")]
    for stick in STICKS:
        for updates in FIRST_DURATIONS:
            programs.append(_Program(stick, updates, f"{stick}x{updates}", target=_target(a, stick, updates)))
    if can_chord:
        # The rear attack standing, on update j: in the facing the actor has
        # (B+C with no direction -- $322A runs before the walk).
        for j in CHORD_DELAYS:
            programs.append(_Program((0, 0), j, f"chord@{j}", chord_at=j))
    if free:
        # A punch on update j, standing or after walking at him (the walk is
        # the turn: B with a turn on one press is thrown the old way).
        targets = [m] if m is not None else []
        targets += [g for g in garcias if g.alive]
        towards = {(1 if t.x > a.x else -1, 0) for t in targets} or {(0, 0)}
        for j in PUNCH_DELAYS:
            programs.append(_Program((0, 0), j, f"punch@{j}", punch_at=j))
            if j:
                for toward in sorted(towards):
                    programs.append(_Program(toward, j, f"walk{toward[0]}x{j}+punch", punch_at=j))
    return programs


def plan(
    a: ActorSim,
    m: MrXSim | None,
    bullets: Sequence[BulletSim] = (),
    *,
    garcias: Sequence = (),
    committed: tuple[int, int] = (0, 0),
    scenarios: Sequence[tuple[bool, int, bool]] = SCENARIOS,
    memory: PlanMemory | None = None,
    trace: list | None = None,
    can_punch: bool = True,
    can_chord: bool = True,
) -> MrXPlan:
    """This tick's stick: every program under every timing, the worst kept."""

    horizon = HORIZON_GUN if m is not None and m.primary == model.PRIMARY_GUN else HORIZON
    ready = getattr(a, "punch", None) is None and a.chord is None and not a.unavailable
    free = can_punch and ready
    programs = _programs(a, m, free, garcias, can_chord=can_chord and ready)
    regrab_window = m is not None and engage_mode(m) == "regrab"
    kept = None
    if memory is not None and memory.program is not None:
        kept = memory.program.advanced_from(a)
        if kept.first_updates > 0:
            programs = [kept] + programs
        else:
            kept = None
    best: MrXPlan | None = None
    best_program = None
    for program in programs:
        worst: tuple[float, _Result] | None = None
        total = 0.0
        played = 0
        admissible = True
        for player_first, lead, overrun in scenarios:
            result = _rollout(
                m, bullets, a, program, player_first=player_first, lead=lead,
                committed=committed, overrun=overrun, horizon=horizon, garcias0=garcias,
            )
            score = _score(result)
            total += score
            played += 1
            if trace is not None:
                trace.append((program.label, player_first, lead, overrun, round(score), result.hit_at, result.grab_at))
            if worst is None or score < worst[0]:
                worst = (score, result)
            if (program.punch_at == 0 or program.chord_at == 0) and result.now_struck is not True:
                # No punch or rear attack that can miss: pressed now, it lands
                # under every timing or it is not pressed (the user's rule for
                # the twins' rear attack, kept here).
                admissible = False
                break
            if trace is None and best is not None and worst[0] <= best.score and (
                not regrab_window or worst[0] <= HIT_SCORE / 2
            ):
                # Scored by the worst timing, it can no longer win.
                break
        assert worst is not None
        if not admissible:
            continue
        # At a re-grab window (his shake, the retreat's first update) a miss
        # only lets him back off: there the mean over the timings, so a grab
        # that lands under four of five beats one never tried. Anywhere else
        # the worst timing -- a step-in that some timings turn into his lunge
        # is a lunge.
        score, result = worst
        if regrab_window and score > HIT_SCORE / 2:
            score = total / played
        if program is kept and result.hit_at is None:
            score += STICKY
        if best is None or score > best.score:
            best_program = program
            punch_now = program.punch_at == 0
            chord_now = program.chord_at == 0
            stick = (0, 0) if punch_now or chord_now else (
                program.first if program.first_updates > 0 else tail_action(a, m, garcias)
            )
            outcome = (
                "hit" if result.hit_at is not None
                else "grab" if result.grab_at is not None
                else "struck" if result.struck_at is not None
                else None
            )
            at = next((v for v in (result.hit_at, result.grab_at, result.struck_at) if v is not None), None)
            best = MrXPlan(
                dir_x=stick[0], dir_y=stick[1], outcome=outcome, at_update=at, score=score,
                label=program.label, mode=engage_mode(m) if m is not None else "helpers", punch=punch_now,
                chord=chord_now,
            )
    assert best is not None
    if memory is not None:
        memory.program = best_program
    return best


# --- The hold ------------------------------------------------------------------------

# A knee locks the holder 17-18 frames: 9 updates. A threat is looked for as
# far as a knee, the release after it and a step take (HOLD_KNEE_SAFE_UPDATES).
KNEE_UPDATES = 9
THREAT_UPDATES = HOLD_KNEE_SAFE_UPDATES


def garcia_threat(a: ActorSim, garcias: Sequence, *, updates: int = THREAT_UPDATES) -> tuple[int, bool] | None:
    """The first update a Garcia's box lands on the actor standing where it is
    (a holder does not move), and whether he comes from behind it -- played
    through ``garcia.py``, his approach and his jab as the ROM runs them."""

    a = a.copy()
    a.walking = False
    a.holding = True
    sims = [g.copy() for g in garcias if g.alive]
    for k in range(updates):
        a.latch = 0
        if a.blink:
            model.blink_step(a)
            model.refresh_boxes(a, a.x, a.y)
        for g in sorted(sims, key=lambda g: g.slot):
            if garcia_model.garcia_update(g, a).name == "HIT":
                behind = (g.x > a.x) == a.facing_left
                return k, behind
    return None


def reads_the_hold(primary: int, substate: int) -> bool:
    """``$13598``: state ``$A`` substate 1 reads the holder's ``+$7D``; 0 is
    the update that stands him in front, 2-3 the shake a knee buys."""

    return primary == model.PRIMARY_HELD and substate == 1


def hold_step(*, action_base: int, knees_in_chain: int, primary: int, substate: int, health: int) -> str:
    """Knee, knee, release -- each on an update he reads. A knee is the
    holder's ``+$34`` (2); at 2 or less it kills, so the last one needs no
    finisher. A back hold (``$66``: he was grabbed from behind, state ``$B``)
    has the suplex (5) only, and is released otherwise -- a crossover frees
    him there. Returns "knee", "release", "suplex" or "wait"."""

    if action_base == 0x60:
        if not reads_the_hold(primary, substate):
            return "wait"
        if knees_in_chain < 2 or health <= 2:
            return "knee"
        return "release"
    if action_base == 0x66:
        if primary == model.PRIMARY_HELD_BACK and health <= 5:
            return "suplex"
        return "release"
    return "wait"
