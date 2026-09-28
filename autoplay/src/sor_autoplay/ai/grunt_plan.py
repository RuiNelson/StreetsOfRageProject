"""The street enemies: the plan -- take the hold, or land the punch, from where
nothing of theirs lands first.

On the ROM model in ``grunt.py``, and in the shape of ``mr_x_plan``: every
tick, programs (a stick held a while, then a tail policy; a punch or a rear
attack on update j, standing or after a walk at a target) are played through
every modelled enemy on screen under several update timings, and each is
scored by the worst: a hit (his box on the actor's body, or Signal's and the
``$21``'s holds on it) below everything, sooner worse; a hold on one of them
-- the actor's walking box on his body, which ``$AAA0`` tests *before* his own
box -- when no other's blow reaches the holder before a knee is spent; a
strike; and otherwise how the end suits the next move.

What the lookahead finds against each, from their code (``grunt.py``):

- *Garcia*: his jab trigger reaches 0-40 px ahead on his lane band (``+-16``
  lanes) and fires the moment the actor's body meets it, the jab already out
  -- so the walk straight in along his lane is his punch, not the actor's
  hold. The hold comes from off his band (the lane step into it with the
  walking box already on his X), from his back, or a punch thrown before he
  closes to 40: the actor's reach (Blaze 18-68) is longer than his trigger.
- *the knife*: the run he enters with has his whole body as its box, so the
  only safe place is out of his line -- 17 lanes off it -- or with the walking
  box already on him.
- *the bat*: it swings 24-72 px out after a 9-update wind-up, from 64 px
  away: the answer is the lane, or inside 24.
- *Signal*: touching him is his hold on the actor; his slide has no body.
- *HakuRo*: ``$06`` reaches 44 px ahead, the whole height, from a 4.5 px an
  update dash -- and chasing him keeps him out of reach, since he walks to a
  point kept off the actor's own spot (the round-1 stall, 43 s): waiting is
  what brings him in.
- *Nora*: the whip lands 32-80 px ahead 10 updates after its test passes;
  closer than 32 it cannot land at all.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Sequence

from . import grunt as model
from .grunt import GruntSim, KnifeSim, Outcome
from .mr_x import actor_step as _unarmed_step
from .mr_x import blink_step, refresh_boxes
from .mr_x_plan import SCENARIOS as _MR_X_SCENARIOS, PlanMemory as _MrXPlanMemory, _Program, _speeds, _target
from .twins import ActorSim, overlaps

__all__ = ["GruntPlan", "PlanMemory", "holder_blow", "plan", "tail_action", "relevant"]

HORIZON = 24
# mr_x_plan's five update timings, and the stick held now carried two
# updates: a tick that plans late (the live p99 is ~45 ms, three updates at
# turbo 2) lands its stick that much later, and a lane step into a Garcia's
# band timed to the update is his jab one update late.
SCENARIOS = _MR_X_SCENARIOS + ((False, 2, False),)
# ...but that last one is a *soft* timing: a hit under it costs a program
# this much and no more (worse than a burnt hold, better than any hit under
# the five), so a plan that is only unsafe when the tick runs two updates
# late does not lose to walking away (user: "A IA tende a fugir muito dos
# inimigos ... podia ser mais eficiente em tempo").
SOFT_SCENARIOS = frozenset({(False, 2, False)})
SOFT_FLOOR = -30_000.0
FIRST_DURATIONS = (2, 6, 12)
STICKS = ((0, 0), (0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1))
PUNCH_DELAYS = (0, 1, 2, 3, 5)
CHORD_DELAYS = (0, 2, 4)
# The rear attack turned onto a target: walk away from him this many updates
# (the first turns the facing), then B+C -- the box goes out behind (Blaze
# 5-53 px, a knockdown on every live update, from the third update to the
# tenth), longer than anything a Garcia's jab reaches from in front (user:
# "usar um back-attack, que é rápido e tem mais range").
TURN_CHORD_DELAYS = (1, 2, 4)
TURN_CHORD_NEAR_X = 110
TURN_CHORD_NEAR_Y = 20
STICKY = 150.0
# A kept walk is done once its point is within a pixel on every axis it
# moves, or its way on is shut: `$43AA` clamps the origin's whole pixel and
# keeps the fraction, so a walk into the camera clamp or the lane band never
# reaches a point computed at the clamp (x 2199.5 against 2199). Two ticks in a
# row with no movement at all (a prop's wall, `$3BAE`) end it too. Measured:
# a (-1, +1) kept 50 s in round 2's bottom-left corner, STICKY outbidding
# every fresh program, while a knife Garcia walked about 110 px off.
KEPT_ARRIVED_PX = 1.0
KEPT_STALL_TICKS = 2
# Scored by the worst timing, then a hundredth of the mean over them: when
# every program is a hit under the most pessimistic one (the held stick two
# updates on, a jab due in two), the one that is a hold under the other five
# is not the same as one that is a hit under all six. 60,000 (a hold) times
# a hundredth is 600: a program whose worst trails the best by more cannot win.
MEAN_WEIGHT = 0.01
MEAN_REACH = MEAN_WEIGHT * 60_000.0
# A tick's share of the lookahead: past it the best program so far is the
# plan (the kept one and the tail are played first). A tick that plans for
# 25 ms walks the old stick for 3 frames at turbo 2 -- a Garcia's jab trigger
# does not wait for it.
BUDGET_MS = 8.0
# The screening timings (stage 1) and how many programs go on to the rest,
# with a little past the budget for them.
SCREEN_SCENARIOS = ((False, 1, False),)
FINALISTS = 8
STAGE_2_GRACE = 0.005

HIT_SCORE = -1_000_000.0
HOLD_SCORE = 60_000.0
STRUCK_SCORE = 20_000.0
BURNT_HOLD_SCORE = -3_000.0
# A threat at the end of the horizon, standing there: what the next ticks inherit.
END_THREAT_UPDATES = 10
END_THREAT_SCORE = -3_000.0
# Only enemies this near can land within those updates (the flying kick
# covers 100 px in 10).
END_THREAT_DX = 110
END_THREAT_DY = 40

# Only enemies near enough to matter within the horizon are played: 28 updates
# at 10 px an update (the flying kick) is 280 px; the camera is 256 wide.
OFF_SCREEN_ENGAGE_DX = 96
RELEVANT_DX = 160
RELEVANT_DY = 90

# The hold, timed from the grab (``mr_x_plan``): a knee locks the holder 9
# updates, the release after it ~4; a blow landing before that burns the hold.
HOLD_ESCAPE_UPDATES = 7
HOLD_KNEE_SAFE_UPDATES = 13

# Off his lane band by this much before stepping in (the jab's box and the
# body are +-8 lanes each, inclusive).
OFF_BAND = 20
# The walking box on his body: a Blaze-sized reach (0..19) plus his +-9.
GRAB_REACH_X = 14
# A Garcia lying in wait gets up within 80 px on X: stand 70 out, 26 lanes off.
WAKE_X = 70
WAKE_OFF_BAND = 26


# --- The armed actor: the swung weapon -------------------------------------------------------
#
# B with a weapon ($3084) starts its own animation, and on its live frames the
# weapon object -- placed by the holder's attach table ($5FC8: x, z and a
# collision bit per frame) -- registers itself as an attacker ($95CE), and
# every enemy's contact test meets its box first ($AA34 -> $ABA4, code 5:
# $A9DC's knockdown, the weapon's +$34 off his health). The live frame, per
# weapon and character (x, z of the weapon's origin), from $5FC8; the timing
# is Blaze's, read off the recordings (frame 0 two updates, the live frame
# three for the bat and pipe -- then nine of recovery -- and five for the knife
# and the bottle).
AXEL, ADAM, BLAZE = 0, 1, 2
KNIFE, BOTTLE, BAT, PIPE, PEPPER = 0x08, 0x09, 0x0A, 0x0B, 0x0C
SWING_OFFSETS = {
    BAT: {AXEL: (36, -42), ADAM: (59, -38), BLAZE: (53, -39)},
    PIPE: {AXEL: (36, -42), ADAM: (59, -38), BLAZE: (53, -39)},
    KNIFE: {AXEL: (56, -29), ADAM: (67, -36), BLAZE: (48, -36)},
    BOTTLE: {AXEL: (54, -31), ADAM: (68, -38), BLAZE: (49, -38)},
}
# (first live update, last live update, lock), the weapon's own box (right,
# left) and its damage (+$34: $5C54, $613C, $620A, $623A).
SWING_TIMING = {BAT: (4, 6, 17), PIPE: (4, 6, 17), KNIFE: (4, 9, 10), BOTTLE: (4, 9, 10)}
WEAPON_SHAPES = {
    BAT: ((-19, 33, -24, 24, -6, 6), (-33, 19, -24, 24, -6, 6)),
    PIPE: ((-19, 35, -20, 20, -6, 6), (-35, 19, -20, 20, -6, 6)),
    KNIFE: ((-13, 11, -8, 8, -11, 5), (-15, 7, -8, 8, -11, 5)),
    BOTTLE: ((-13, 11, -8, 8, -11, 5), (-15, 7, -8, 8, -11, 5)),
}
WEAPON_DAMAGE = {BAT: 4, PIPE: 4, KNIFE: 5, BOTTLE: 3}
SWING_WEAPONS = frozenset(SWING_TIMING)
# $3084's knife rule: an object in front within 144 px and 12 lanes is the
# stab; with none the knife is thrown.
KNIFE_CONE_X = 0x90
KNIFE_CONE_LANE = 12


# --- The actor's own body while it strikes ----------------------------------------------------
#
# $4140 caches the body box of the frame the actor is on (+$70), and a punch or
# a swing moves it well forward: Blaze's punch stands her body 14-29 px ahead
# of her origin, where idle it is 2-12 -- so a punch thrown at a Garcia 60-70 px
# away walks her body into his jab trigger (0-40 ahead). Per character and
# frame, from each set at $1F20 (the player shape table $1ABA8: x0, x1, z0, z1
# facing right, lanes +-8), and the frames' update counts from $3A30 (the
# punch rows 5/31/23, the weapons' 9 and 10). A step of the plan's reads the
# frame one update behind (the renderer latches before it steps -- the same
# lag the punch's live window, verified in lockstep, carries).
PUNCH_BODY = {
    AXEL: (((0, 13, -51, 0), (9, 20, -50, 0), (0, 13, -51, 0), (0, 13, -51, 0)), (1, 5, 1, 2)),
    ADAM: (((-5, 7, -53, 0), (4, 15, -54, 0), (-5, 7, -53, 0), (-5, 7, -53, 0)), (1, 2, 2, 6)),
    BLAZE: (((14, 25, -43, 0), (19, 29, -43, 0), (14, 25, -43, 0), (14, 25, -43, 0)), (2, 5, 1, 2)),
}
_KNIFE_BODY = {
    AXEL: ((10, 20, -48, 0), (21, 32, -44, 0), (21, 32, -44, 0)),
    ADAM: ((7, 19, -50, 0), (23, 37, -42, 0), (23, 37, -42, 0)),
    BLAZE: ((11, 19, -48, 0), (14, 23, -44, 0), (11, 19, -48, 0)),
}
_BOTTLE_BODY = {
    AXEL: ((10, 18, -50, 0), (21, 32, -44, 0), (21, 32, -44, 0)),
    ADAM: ((8, 18, -48, 0), (23, 37, -42, 0), (23, 37, -42, 0)),
    BLAZE: ((11, 19, -48, 0), (14, 23, -44, 0), (11, 19, -48, 0)),
}
_STICK_BODY = {
    AXEL: ((0, 10, -52, 0), (2, 11, -50, 0), (11, 20, -52, 0), (11, 20, -52, 0)),
    ADAM: ((2, 11, -52, 0), (18, 32, -46, 0), (32, 42, -40, 0), (32, 42, -40, 0)),
    BLAZE: ((10, 19, -48, 0), (11, 21, -40, 0), (21, 31, -44, 0), (21, 31, -44, 0)),
}
SWING_BODY = {
    KNIFE: (_KNIFE_BODY, (3, 5, 2)),
    BOTTLE: (_BOTTLE_BODY, (3, 5, 2)),
    BAT: (_STICK_BODY, (3, 3, 9, 2)),
    PIPE: (_STICK_BODY, (3, 3, 9, 2)),
}


def _frame_at(durations: tuple[int, ...], step: int) -> int:
    t = max(0, step - 1)
    for frame, count in enumerate(durations):
        if t < count:
            return frame
        t -= count
    return len(durations) - 1


def _body_box(a: ActorSim, shape: tuple[int, int, int, int]) -> tuple[int, int, int, int, int, int]:
    x0, x1, z0, z1 = shape
    if a.facing_left:
        x0, x1 = -x1, -x0
    x, y, z = int(a.x), int(a.y), int(a.z)
    return (x + x0, x + x1, y - 8, y + 8, z + z0, z + z1)


def _striking_body(a: ActorSim) -> None:
    """The body box of the frame a punch or a swing stands on."""

    if getattr(a, "invulnerable", False):
        return
    swing = getattr(a, "swing", None)
    if swing is not None:
        bodies, durations = SWING_BODY[_weapon(a)]
        frames = bodies.get(a.character, bodies[BLAZE])
        a.body = _body_box(a, frames[min(_frame_at(durations, swing), len(frames) - 1)])
        return
    punch = getattr(a, "punch", None)
    if punch is not None:
        frames, durations = PUNCH_BODY.get(a.character, PUNCH_BODY[BLAZE])
        a.body = _body_box(a, frames[_frame_at(durations, punch)])


def _weapon(a: ActorSim) -> int:
    return getattr(a, "weapon", 0) or 0


def _swing_boxes(a: ActorSim) -> None:
    kind = _weapon(a)
    first, last, _ = SWING_TIMING[kind]
    if first <= a.swing <= last:
        dx, dz = SWING_OFFSETS[kind].get(a.character, SWING_OFFSETS[kind][BLAZE])
        right, left = WEAPON_SHAPES[kind]
        shape = left if a.facing_left else right
        x = int(a.x) + (-dx if a.facing_left else dx)
        y, z = int(a.y), int(a.z) + dz
        a.weapon_box = (x + shape[0], x + shape[1], y + shape[2], y + shape[3], z + shape[4], z + shape[5])
        a.weapon_damage = WEAPON_DAMAGE[kind]
    else:
        a.weapon_box = None


def _blocked(a: ActorSim) -> bool:
    x, y = a.x, a.y
    return any(x0 < x < x1 and y0 < y < y1 for x0, x1, y0, y1 in a.solids)


def actor_step(a: ActorSim, dir_x: int, dir_y: int, punch: bool = False, chord: bool = False) -> None:
    """``mr_x.actor_step``, and armed, B is the weapon's swing: standing, the
    facing it had, the weapon's box out on its live updates. A punch or a
    swing stands the actor's body where its frame puts it (``_striking_body``).
    A step that puts the actor's own position in a prop, a wall or a pit is
    undone whole, as ``$3B8A``/``$3C92`` undo it (a pit is a fall, which no
    plan takes)."""

    if getattr(a, "solids", None) and (dir_x or dir_y):
        x, y = a.x, a.y
        _actor_step(a, dir_x, dir_y, punch, chord)
        if (a.x != x or a.y != y) and _blocked(a):
            a.x, a.y = x, y
            refresh_boxes(a, a.x, a.y)
    else:
        _actor_step(a, dir_x, dir_y, punch, chord)
    _striking_body(a)


def _actor_step(a: ActorSim, dir_x: int, dir_y: int, punch: bool, chord: bool) -> None:

    if getattr(a, "swing", None) is not None:
        blink_step(a)
        a.swing += 1
        if a.swing >= SWING_TIMING[_weapon(a)][2]:
            a.swing = None
            a.weapon_box = None
            _unarmed_step(a, dir_x, dir_y)
            return
        _swing_boxes(a)
        return
    if punch and _weapon(a) in SWING_WEAPONS:
        blink_step(a)
        a.swing = 0
        a.walking = False
        a.vx = 0.0
        refresh_boxes(a, a.x, a.y)
        a.attack = None
        a.damage = 0
        _swing_boxes(a)
        return
    _unarmed_step(a, dir_x, dir_y, punch=punch, chord=chord)


def knife_would_throw(a: ActorSim, grunts: Sequence[GruntSim]) -> bool:
    """``$3084`` with a knife: no object in the front cone, and B throws it."""

    for g in grunts:
        dx = g.x - a.x
        if (dx < 0) == bool(a.facing_left) and abs(dx) < KNIFE_CONE_X and abs(g.y - a.y) <= KNIFE_CONE_LANE:
            return False
    return True


@dataclass(frozen=True, slots=True)
class GruntPlan:
    dir_x: int
    dir_y: int
    outcome: str | None  # "grab", "struck", "hit" or None
    at_update: int | None
    score: float
    label: str
    target_slot: int | None
    punch: bool = False
    chord: bool = False


def relevant(a: ActorSim, grunts: Sequence[GruntSim]) -> list[GruntSim]:
    return [
        g for g in grunts
        if g.alive
        and g.state not in (model.ST_INIT, model.ST_PEPPER, model.ST_DYING)
        and not model.in_entry(g)
        and abs(g.x - a.x) <= RELEVANT_DX
        and abs(g.y - a.y) <= RELEVANT_DY
    ]


def engages(a: ActorSim, grunts: Sequence[GruntSim]) -> bool:
    """Whether the plan has a fight here: some relevant enemy on screen, or
    off it but within ``OFF_SCREEN_ENGAGE_DX`` (about to walk on -- the stage
    walk would take the actor straight into him). One further off is walked
    to by the stage walk, which is what scrolls him in."""

    return any(_in_the_fight(a, g) for g in relevant(a, grunts))


def _in_the_fight(a: ActorSim, g: GruntSim) -> bool:
    return model.on_screen(g) or abs(g.x - a.x) <= OFF_SCREEN_ENGAGE_DX


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def _toward(value: float, target: float, dead: float = 1.5) -> int:
    if value < target - dead:
        return 1
    if value > target + dead:
        return -1
    return 0


def _engageable(g: GruntSim) -> bool:
    """A body the actor's walking box can hold (not down, held, dying or in
    the air)."""

    if not g.alive or g.state in (model.ST_KNOCKDOWN, model.ST_HELD, model.ST_DYING):
        return False
    if g.type in (model.HAKURO, model.HAKURO_TRIO) and g.state in (0x0B, 0x0C, 0x10, 0x12, 0x13):
        return False
    if g.type == model.SIGNAL and g.state in (0x0B, 0x0C):
        return False
    return g.body_id != 0


def pick_target(a: ActorSim, grunts: Sequence[GruntSim]) -> GruntSim | None:
    """The nearest engageable enemy, lanes counted double (a lane is slower to
    walk than a pixel of X) -- none the partner is fighting."""

    best = None
    best_d = math.inf
    spared = getattr(a, "spared", None) or ()
    for g in grunts:
        if g.slot in spared:
            continue
        if model.in_entry(g) or not model.on_screen(g):
            continue
        if not _engageable(g) and not model.lying_in_wait(g):
            continue
        d = abs(g.x - a.x) + 2.0 * abs(g.y - a.y)
        if d < best_d:
            best, best_d = g, d
    return best


def _side(a: ActorSim, g: GruntSim) -> int:
    s = _sign(a.x - g.x)
    if s == 0:
        s = -1 if a.facing_left else 1
    return s


def _screen_middle(a: ActorSim) -> float:
    return (a.x_lo + a.x_hi) / 2.0


def engage_aim(a: ActorSim, g: GruntSim) -> tuple[float, float]:
    """Where the tail walks: his X at the walking box's reach on the actor's
    side; his lane once there, off his band until then."""

    side = _side(a, g)
    if model.lying_in_wait(g):
        # Wake him from where his first approach update cannot jab: inside
        # the 80 px he gets up at, off his lane band.
        lane_side = _sign(a.y - g.y) or (1 if g.y < 56 else -1)
        aim_y = g.y + lane_side * WAKE_OFF_BAND
        if not (a.lane_lo + 1 <= aim_y <= a.lane_hi - 1):
            aim_y = g.y - lane_side * WAKE_OFF_BAND
        return g.x + side * WAKE_X, aim_y
    aim_x = g.x + side * GRAB_REACH_X
    dx = abs(a.x - aim_x)
    if dx <= 4:
        return aim_x, g.y
    lane_side = _sign(a.y - g.y) or (1 if g.y < 56 else -1)
    aim_y = g.y + lane_side * OFF_BAND
    if not (a.lane_lo + 1 <= aim_y <= a.lane_hi - 1):
        aim_y = g.y - lane_side * OFF_BAND
    return aim_x, aim_y


def tail_action(a: ActorSim, grunts: Sequence[GruntSim], target_slot: int | None) -> tuple[int, int]:
    """The stick the rollouts hand over to once their program runs out: toward
    the target's engage aim, facing him."""

    g = next((t for t in grunts if t.slot == target_slot and (_engageable(t) or model.lying_in_wait(t))), None)
    if g is None:
        g = pick_target(a, grunts)
    if g is None:
        # Nobody to engage on screen: toward its middle, which is what brings
        # an enemy off it in (standing still at the clamp was a deadlock -- a
        # round-7 Garcia pinned below the lift's X bound, off screen and out
        # of every strike's reach, waited for a point he could not reach).
        return _toward(a.x, _screen_middle(a), 4), 0
    aim_x, aim_y = engage_aim(a, g)
    dx = _toward(a.x, aim_x, 2)
    dy = _toward(a.y, aim_y, 1.5)
    side = _side(a, g)
    facing_him = a.facing_left == (side > 0)
    if dx == 0 and not facing_him:
        dx = -side  # the walking box points the way the actor faces
    return dx, dy


@dataclass(slots=True)
class _Result:
    hit_at: int | None
    grab_at: int | None
    struck_at: int | None
    actor: ActorSim
    grunts: tuple
    now_struck: bool | None = None
    burnt_at: int | None = None
    held_slot: int | None = None
    friendly_at: int | None = None  # a strike of the actor's met the partner


def _object_pass(grunts: list[GruntSim], a: ActorSim, knives: list[KnifeSim] | None = None) -> list[tuple[int, Outcome]]:
    """One object pass: the enemies in slot order, then the knives in flight
    (a weapon's slot sits above theirs); a knife thrown this pass flies from
    the next."""

    events: list[tuple[int, Outcome]] = []
    fresh: list[KnifeSim] = []
    for g in grunts:
        if not g.alive:
            continue
        out = model.grunt_update(g, a)
        if out is not Outcome.NONE:
            events.append((g.slot, out))
        if g.thrown is not None:
            fresh.append(g.thrown)
            g.thrown = None
    if knives is not None:
        cam_x = grunts[0].cam_x if grunts else 0
        for k in knives:
            if k.alive and model.knife_update(k, a, cam_x) is Outcome.HIT:
                events.append((-1, Outcome.HIT))
        knives[:] = [k for k in knives if k.alive] + fresh
    return events


def holder_blow(grunts: Sequence[GruntSim], a: ActorSim, updates: int, *, exclude: int | None = None,
                knives: Sequence[KnifeSim] = ()) -> int | None:
    """The first update a blow lands on a holder standing where it is for
    ``updates``, from any enemy but ``exclude`` (the one in hand) or a knife
    in flight, or None."""

    others = [g.copy() for g in grunts if g.alive and g.slot != exclude]
    flying = [k.copy() for k in knives if k.alive]
    if not others and not flying:
        return None
    h = a.copy()
    h.holding = True
    h.walking = False
    h.punch = None
    h.chord = None
    h.swing = None
    h.weapon_box = None
    h.vx = 0.0
    h.attack = None
    h.damage = 0
    refresh_boxes(h, h.x, h.y)
    for j in range(updates):
        h.latch = 0
        if h.blink:
            blink_step(h)
            refresh_boxes(h, h.x, h.y)
        for _, out in _object_pass(others, h, flying):
            if out in (Outcome.HIT, Outcome.SEIZED):
                return j
    return None


def _rollout(
    grunts0: Sequence[GruntSim],
    a0: ActorSim,
    program: _Program,
    *,
    player_first: bool,
    lead: int,
    committed: tuple[int, int],
    overrun: bool,
    horizon: int,
    target_slot: int | None,
    knives0: Sequence[KnifeSim] = (),
) -> _Result:
    grunts = [g.copy() for g in grunts0]
    knives = [k.copy() for k in knives0]
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
            stick = tail_action(a, grunts, target_slot)
        if moves == 0:
            first_stick.append(stick)
        actor_step(a, *stick)
        moves += 1

    partner = getattr(a, "partner_body", None)
    spared = getattr(a, "spared", None) or ()
    friendly: list[int] = []

    def result(**kw) -> _Result:
        now = None if not pressed_now else struck_at is not None
        return _Result(actor=a, grunts=tuple(grunts), struck_at=struck_at, now_struck=now,
                       friendly_at=friendly[0] if friendly else None, **kw)

    def check_partner(k: int) -> None:
        if partner is None or friendly:
            return
        if a.damage and a.attack is not None and overlaps(a.attack, partner):
            friendly.append(k)
        elif getattr(a, "weapon_box", None) is not None and overlaps(a.weapon_box, partner):
            friendly.append(k)

    if player_first:
        act()
        check_partner(0)
    for k in range(horizon):
        events = _object_pass(grunts, a, knives)
        for slot, out in events:
            if out in (Outcome.STRUCK, Outcome.KNOCKED) and struck_at is None and slot not in spared:
                struck_at = k
        for _, out in events:
            if out in (Outcome.HIT, Outcome.SEIZED):
                return result(hit_at=k, grab_at=None)
        for slot, out in events:
            if out is Outcome.GRAB and not _held(grunts, slot):
                # $3266 refused it (the body behind the actor's origin): no hold.
                continue
            if out is Outcome.GRAB and slot in spared:
                # The partner's fight: a hold on it is theirs to lose.
                return result(hit_at=None, grab_at=None, burnt_at=k, held_slot=slot)
            if out is Outcome.GRAB:
                blow = holder_blow(grunts, a, HOLD_KNEE_SAFE_UPDATES, exclude=slot, knives=knives)
                if blow is not None and blow < HOLD_ESCAPE_UPDATES:
                    return result(hit_at=k + blow, grab_at=None)
                if blow is not None:
                    return result(hit_at=None, grab_at=None, burnt_at=k, held_slot=slot)
                return result(hit_at=None, grab_at=k, held_slot=slot)
        if not any(g.alive for g in grunts):
            return result(hit_at=None, grab_at=None)
        act()
        check_partner(k + 1)
    return result(hit_at=None, grab_at=None)


def _held(grunts: Sequence[GruntSim], slot: int) -> bool:
    g = next((g for g in grunts if g.slot == slot), None)
    return g is not None and not g.flags & 0x40


def _end_score(result: _Result, target_slot: int | None) -> float:
    a = result.actor
    grunts = [g for g in result.grunts if g.alive]
    g = next((t for t in grunts if t.slot == target_slot and (_engageable(t) or model.lying_in_wait(t))), None)
    g = g or pick_target(a, grunts)
    score = 0.0
    if g is not None:
        aim_x, aim_y = engage_aim(a, g)
        score -= abs(a.x - aim_x) * 0.5 + abs(a.y - aim_y) * 1.0
    else:
        score -= abs(a.x - _screen_middle(a)) * 0.25
    for other in grunts:
        if abs(other.x - a.x) > END_THREAT_DX or abs(other.y - a.y) > END_THREAT_DY:
            continue
        at = model.threat(other, a, updates=END_THREAT_UPDATES)
        if at is not None:
            score += END_THREAT_SCORE + 400.0 * at
            break
    return score


def _score(result: _Result, target_slot: int | None) -> float:
    if result.friendly_at is not None:
        # Never hurt the partner (user): below every hit on the actor.
        return 2 * HIT_SCORE + 100.0 * result.friendly_at
    if result.hit_at is not None:
        return HIT_SCORE + 100.0 * result.hit_at
    if result.burnt_at is not None:
        return BURNT_HOLD_SCORE - 100.0 * result.burnt_at
    if result.grab_at is not None:
        return HOLD_SCORE - 100.0 * result.grab_at
    base = _end_score(result, target_slot)
    if result.struck_at is not None:
        base += STRUCK_SCORE - 100.0 * result.struck_at
    return base


def _programs(a: ActorSim, grunts: Sequence[GruntSim], free: bool, can_chord: bool) -> list[_Program]:
    """Every program, the decisive ones first (the tail, the punches and swings,
    the rear attacks), then the sticks: under the budget the list is cut from
    the end."""

    programs = [_Program((0, 0), 0, "tail")]
    if free:
        near = [g for g in grunts if g.alive and abs(g.x - a.x) < 120 and abs(g.y - a.y) < 40]
        towards = {(1 if g.x > a.x else -1, 0) for g in near}
        for j in PUNCH_DELAYS:
            programs.append(_Program((0, 0), j, f"punch@{j}", punch_at=j))
            if j:
                for toward in sorted(towards):
                    programs.append(_Program(toward, j, f"walk{toward[0]}x{j}+punch", punch_at=j))
    if can_chord:
        for j in CHORD_DELAYS:
            programs.append(_Program((0, 0), j, f"chord@{j}", chord_at=j))
        near_chord = [
            g for g in grunts
            if g.alive and abs(g.x - a.x) < TURN_CHORD_NEAR_X and abs(g.y - a.y) < TURN_CHORD_NEAR_Y
        ]
        aways = {(-1 if g.x > a.x else 1, 0) for g in near_chord}
        for away in sorted(aways):
            for j in TURN_CHORD_DELAYS:
                programs.append(_Program(away, j, f"turn{away[0]}x{j}+chord", chord_at=j))
    for stick in STICKS:
        for updates in FIRST_DURATIONS:
            programs.append(_Program(stick, updates, f"{stick}x{updates}", target=_target(a, stick, updates)))
    return programs


class PlanMemory(_MrXPlanMemory):
    """``mr_x_plan.PlanMemory`` plus where the actor stood when the program
    was kept, and how many ticks in a row it has not moved since."""

    __slots__ = ("pos", "stalls")

    def __init__(self) -> None:
        super().__init__()
        self.pos: tuple[float, float] | None = None
        self.stalls = 0


def _kept(memory: PlanMemory, a: ActorSim) -> _Program | None:
    """The last tick's walk from where the actor now stands, while it still
    has somewhere to go (``KEPT_ARRIVED_PX``, the clamps, ``KEPT_STALL_TICKS``)."""

    program = memory.program
    if program is None:
        return None
    pos = getattr(memory, "pos", None)
    if pos is not None and abs(a.x - pos[0]) < 0.25 and abs(a.y - pos[1]) < 0.25:
        memory.stalls = getattr(memory, "stalls", 0) + 1
    else:
        memory.stalls = 0
    kept = program.advanced_from(a)
    if kept.first_updates <= 0 or memory.stalls >= KEPT_STALL_TICKS:
        return None
    if kept.target is not None:
        dx, dy = kept.first
        tx, ty = kept.target
        shut_x = (
            dx == 0 or abs(tx - a.x) < KEPT_ARRIVED_PX
            or (dx < 0 and a.x < a.x_lo + KEPT_ARRIVED_PX) or (dx > 0 and a.x > a.x_hi - KEPT_ARRIVED_PX)
        )
        shut_y = (
            dy == 0 or abs(ty - a.y) < KEPT_ARRIVED_PX
            or (dy < 0 and a.y < a.lane_lo + KEPT_ARRIVED_PX) or (dy > 0 and a.y > a.lane_hi - KEPT_ARRIVED_PX)
        )
        if shut_x and shut_y:
            return None
    return kept


def plan(
    a: ActorSim,
    grunts: Sequence[GruntSim],
    *,
    committed: tuple[int, int] = (0, 0),
    scenarios: Sequence[tuple[bool, int, bool]] = SCENARIOS,
    memory: PlanMemory | None = None,
    trace: list | None = None,
    can_punch: bool = True,
    can_chord: bool = True,
    horizon: int = HORIZON,
    budget_ms: float | None = BUDGET_MS,
    knives: Sequence[KnifeSim] = (),
) -> GruntPlan | None:
    """This tick's stick: every program under every timing, the worst kept.
    None when no modelled enemy is near enough to matter. ``knives`` are the
    enemies' knives already in flight."""

    grunts = relevant(a, grunts)
    if not grunts or not any(_in_the_fight(a, g) for g in grunts):
        return None
    target = pick_target(a, grunts)
    target_slot = target.slot if target is not None else None
    ready = (
        getattr(a, "punch", None) is None and a.chord is None and getattr(a, "swing", None) is None
        and not a.unavailable
    )
    armed = _weapon(a) != 0
    free = can_punch and ready and (
        not armed or _weapon(a) in SWING_WEAPONS and not (_weapon(a) == KNIFE and knife_would_throw(a, grunts))
    )
    programs = _programs(a, grunts, free, can_chord and ready and not armed)
    kept = _kept(memory, a) if memory is not None else None
    if kept is not None:
        programs = [kept] + programs
    deadline = None if budget_ms is None or trace is not None else time.perf_counter() + budget_ms / 1000.0

    def play(program: _Program, scenario: tuple[bool, int, bool]) -> tuple[float, _Result, bool]:
        player_first, lead, overrun = scenario
        soft = scenario in SOFT_SCENARIOS
        result = _rollout(
            grunts, a, program, player_first=player_first, lead=lead, committed=committed,
            overrun=overrun, horizon=horizon, target_slot=target_slot, knives0=knives,
        )
        score = _score(result, target_slot)
        if soft:
            score = max(score, SOFT_FLOOR)
        if trace is not None:
            trace.append((program.label, player_first, lead, overrun, round(score), result.hit_at,
                           result.grab_at, result.struck_at))
        # Pressed now, a punch or a rear attack lands under every (hard)
        # timing or it is not pressed.
        refused = (
            not soft and (program.punch_at == 0 or program.chord_at == 0) and result.now_struck is not True
        )
        return score, result, refused

    # Stage 1, every program under the screening timings; stage 2, the best
    # of them under the rest. A rollout costs ~150 us, and the full set is
    # ~50 programs by six timings -- three times a tick's budget, which left
    # the punches and rear attacks at the end of the list never played.
    screen = [sc for sc in SCREEN_SCENARIOS if sc in scenarios] or list(scenarios[:1])
    rest = [sc for sc in scenarios if sc not in screen]
    played: list[tuple[_Program, list[tuple[float, _Result]]]] = []
    for program in programs:
        if deadline is not None and played and time.perf_counter() > deadline:
            break
        outcomes = []
        refused = False
        for scenario in screen:
            score, result, no = play(program, scenario)
            outcomes.append((score, result))
            if no:
                refused = True
                break
        if not refused:
            played.append((program, outcomes))
    played.sort(key=lambda item: -min(sc for sc, _ in item[1]))
    finalists = played[:FINALISTS]
    if kept is not None and all(p is not kept for p, _ in finalists):
        finalists += [item for item in played if item[0] is kept]

    best: GruntPlan | None = None
    best_program = None
    for program, outcomes in finalists:
        refused = False
        for scenario in rest:
            if deadline is not None and best is not None and time.perf_counter() > deadline + STAGE_2_GRACE:
                break
            worst_so_far = min(sc for sc, _ in outcomes)
            if trace is None and best is not None and worst_so_far + MEAN_REACH < best.score:
                break
            score, result, no = play(program, scenario)
            outcomes.append((score, result))
            if no:
                refused = True
                break
        if refused:
            continue
        score, result = min(outcomes, key=lambda item: item[0])
        score += MEAN_WEIGHT * sum(sc for sc, _ in outcomes) / len(outcomes)
        if program is kept and result.hit_at is None:
            score += STICKY
        if best is None or score > best.score:
            best_program = program
            punch_now = program.punch_at == 0
            chord_now = program.chord_at == 0
            stick = (0, 0) if punch_now or chord_now else (
                program.first if program.first_updates > 0 else tail_action(a, grunts, target_slot)
            )
            outcome = (
                "hit" if result.hit_at is not None
                else "grab" if result.grab_at is not None
                else "struck" if result.struck_at is not None
                else None
            )
            at = next((v for v in (result.hit_at, result.grab_at, result.struck_at) if v is not None), None)
            best = GruntPlan(
                dir_x=stick[0], dir_y=stick[1], outcome=outcome, at_update=at, score=score,
                label=program.label, target_slot=target_slot, punch=punch_now, chord=chord_now,
            )
    if memory is not None:
        memory.program = best_program
        memory.pos = (a.x, a.y)
    return best


def hold_threat(a: ActorSim, grunts: Sequence[GruntSim], *, held_slot: int | None, updates: int,
                knives: Sequence[KnifeSim] = ()) -> int | None:
    """``holder_blow`` for the hold family: the first update another enemy's
    blow (or a knife in flight) lands on the holder where it stands."""

    return holder_blow(relevant(a, grunts), a, updates, exclude=held_slot, knives=knives)
