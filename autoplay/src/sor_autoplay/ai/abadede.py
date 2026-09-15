"""Abadede (type ``$30``, round 3): the ROM model, and the plan built on it.

Everything the AI does against him is decided here, as pure functions of the
tokens already in the context, so ``decide``, ``priority`` and ``execute``
cannot disagree about it -- the arrangement ``antonio.py``, ``souther.py``
and ``bongo.py`` already have.

**The plan, in one line: take one hold, and never give him back a turn.**
The hold loop is Souther's -- knee, knee, release, walk straight back in --
timed to the one substate of his hold that reads the holder's move. What is
his alone is how a hold is reached.

He predates the later-boss framework (``$143D0``; ``ai-analysis/enemy-ai.md``,
"Abadede"): a primary at ``+$30`` dispatched through ``$14466``, a substate
at ``+$5B`` under it, one word timer at ``+$54``, the target at ``+$5C``. The
facts the plan rests on:

Everything runs at 30 Hz
    ``$AD8E`` updates the players, waits a VBlank, then every object: one
    *update* is two frames, and every speed below is per update.
Approach, pause, retreat, charge
    State 1 walks at the target at 6 px an update on both axes -- X only
    while ``|dx| >= $18`` -- until the lane gap is under ``$10``. State 2
    then stands for four updates, re-aiming, and decides: a lane gap of
    ``$10`` or more walks again; ``$50 < |dx| <= $70`` on screen backs off
    first (state 3: 6 px an update away from the target, facing it, for 20
    updates or until he leaves ``[$80, $1C0)`` of the screen); anything else
    charges. The charge (state 7) runs at 12 px an update on the lane it
    started on and never re-aims; at ``|dx| < $10`` it brakes for 2 updates
    and punches for 15, then backs off; at a screen edge it stops and decides
    again. (Round 8's variant -- a non-zero low nibble of ``+$40`` -- decides
    on a ``$18`` lane gap instead, and never backs off first.)
Only the run hurts
    His update runs the contact test (``$AA22``) in states 1, 2, 3 and the
    charge's run and punch. His walk box (anims ``$04``/``$06``: 8 behind to
    32 ahead, lane +-2) on a player's body in states 1/2 is his grab and
    throw (state 8); the run's box (anims ``$08``/``$0A``: 16 behind to 32
    ahead, lane +-8) is his ``+$34`` in damage, 32 on Normal. The punch that
    ends the charge has no body box -- nothing touches him -- and its contact
    code is erased in the same update (``$14CDC`` clears the target's
    ``+$7C``), so it never lands on the player it is aimed at; in state 3 his
    contact is ignored outright (``$1550E``).
The grab beats the hit, and his body is wider than his boxes
    ``$AAA0`` tests the player's attack box against his body first (lane
    +-10: contact up to 18 lanes apart) and only then his box on the player
    (lane +-8 against +-8: 16). **17-18 lanes off his run, the walking box
    takes him and nothing of his reaches the player.** A strike (``+$34``
    set) there is a hit on him instead: a punch is 1 point and 11 updates of
    shake, then the retreat -- whose first contact test, on his feet where
    the punch left him, a walk-in turns into a hold.
The hold
    A grab puts him in state ``$B``: substate 0 stands him 24 px in front of
    the holder, facing it, with ``+$54`` = 40; substate 1 then reads the
    holder's ``+$7D`` every update (``$14992``; the holder writes it from its
    action through ``$32F2``): 1/2 (a front/back hold) nothing; 3 (a knee,
    ``$6A``/``$6C``) the holder's ``+$34`` as damage and 12 updates of shake
    before he reads again; 4 (the third knee, ``$6E``) a knockdown; 5/7 (a
    throw) the throw's flight and 4 points; 6 (the suplex) 5 points; 9 (a
    crossover) the timer held at 30; **0 (released) straight to state 3**,
    whose first contact test, 24 px in front of the holder, is the re-grab.
    Forty updates with nothing read and he frees himself.

Out of that, the plan (``plan_engage``): a lookahead over his AI -- the nine
sticks, each held a while and then handed to a tail policy that follows his
phases (``engage_mode``), plus a punch pressed on a chosen update, standing
or after walking toward him (the ROM samples the facing a punch starts with:
B and a turn on one press is thrown the old way, so the walk is the turn) --
scored by the worse of two update orders: a hold by how soon, a punch that
lands on his run next, a hit below everything. The tail stands 17-18 lanes off a
charge's lane with the walking box toward him, walks into him from 11-15
lanes while he walks in or pauses, and waits in front of him, box out, while
he cannot collide.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Sequence

from .antonio import PLAYER_LANE_MAX, PLAYER_LANE_MIN, ActorSim, actor_update
from .souther import HoldStep, release_press_frames, signed_health
from .tokens import Abadede, Boss, CameraRange, PlayableCharacter

__all__ = [
    "AbadedeSim",
    "EngageMode",
    "EngagePlan",
    "HoldStep",
    "Outcome",
    "PunchSpec",
    "boss_update",
    "build_sims",
    "charge_is_pressing",
    "contact",
    "engage_mode",
    "hold_step",
    "plan_engage",
    "plan_from_sims",
    "punch_spec",
    "reads_the_hold",
    "release_press_frames",
    "signed_health",
    "simulate",
]

ABADEDE_TYPE = 0x30

# --- His states (the primary table at $14466) --------------------------------------

PRIMARY_INIT = 0x00  # $144E0
PRIMARY_APPROACH = 0x01  # $145EC: 0 $145F8 set-up, 1 $14616 the walk
PRIMARY_PAUSE = 0x02  # $14656
PRIMARY_RETREAT = 0x03  # $146F0: 0 $146FC set-up, 1 $1472E the walk away
PRIMARY_STRUCK = 0x04  # $1477A: a strike landed; sets up the shake
PRIMARY_SHAKE = 0x05  # $147A6
PRIMARY_KNOCKDOWN = 0x06  # $14B0E
PRIMARY_CHARGE = 0x07  # $14BDC: 0 set-up, 1 the run, 2 the brake, 3 the punch
PRIMARY_THROWS_PLAYER = 0x08  # $14D04
PRIMARY_SUPLEXED = 0x09  # $1512E
PRIMARY_GET_UP = 0x0A  # $14A8A
PRIMARY_HELD = 0x0B  # $1485C
PRIMARY_DYING = 0x0C  # $15266
PRIMARY_HELD_BACK = 0x0D  # $14EA2
PRIMARY_THROWN = 0x0E  # $14F46

SUB_SETUP = 0
SUB_RUN = 1  # the approach's walk, the retreat's walk, the charge's run
SUB_BRAKE = 2
SUB_PUNCH = 3
# State $B: 0 stands him in front of the holder, 1 reads the holder's +$7D,
# 2/3 the shake a knee buys, 4 the third knee's knockdown on its way.
HELD_STAND = 0
HELD_READING = 1
HELD_KNEE_SHAKE = 2
HELD_KNEE_SHAKING = 3

# --- Speeds, gates and timers ------------------------------------------------------

WALK_SPEED = 6.0  # $1577C: +$1C = +$20 = $60000, turned toward the target
CHARGE_SPEED = 12.0  # $14BEC: $FFF40000, turned toward the target
APPROACH_LANE_GATE = 0x10  # $12A78 with $00100018: under it the walk ends ...
APPROACH_X_GATE = 0x18  # ... and X only moves this far out
PAUSE_UPDATES = 4
# $146C4: round 8's variant (a non-zero low nibble of +$40) decides on this
# lane gap instead, and never backs off first.
VARIANT_LANE_GATE = 0x18
RETREAT_DX_MIN = 0x50  # $14694: 80 < |dx| <= 112, on screen: back off first
RETREAT_DX_MAX = 0x70
RETREAT_UPDATES = 0x14
CHARGE_STOP_DX = 0x10  # $14C38: the run ends inside 16 px of the target
BRAKE_UPDATES = 2
PUNCH_UPDATES = 0x0F
SHAKE_UPDATES = 0x0A
GET_UP_UPDATES = 8
HOLD_UPDATES = 0x28
KNEE_SHAKE_UPDATES = 0x0A
HOLD_STAND_DX = 0x18  # $1486E: held, he stands this far in front of the holder

# His +$28 is biased: $80 is the screen's left edge.
SCREEN_BIAS = 0x80
ON_SCREEN_MIN = 0x80  # $97CE
ON_SCREEN_MAX = 0x1C0
STRIKE_SCREEN_MIN = 0x78  # $AAA0: a strike only counts inside [$78, $1C8)
STRIKE_SCREEN_MAX = 0x1C8
CHARGE_EDGE_LEFT = 0x80  # $14C38: a run to the left goes on past $80 ...
CHARGE_EDGE_RIGHT = 0x1C0  # ... one to the right stops from $1C0

# The states his model does not replay: a rough number of updates before he is
# back on his feet (state $A), so a rollout does not expect him sooner.
KNOCKDOWN_UPDATES = 24  # $15604's flight at gravity 1.125, the bounce, +$54 = 6
THROWN_UPDATES = 40
FOREVER = 1 << 16

# --- Animations (set $34B94) and boxes ($1A68E, lanes $1AB8E) ------------------------
#
# +$08 selects the animation, bit 1 its mirrored (left-facing) member. Every
# frame of the animations he fights in carries the same pair of boxes, so the
# pair follows from the animation alone: (attack id, body id).

ANIM_MIRROR_BIT = 0x02
ANIM_WALK = 0x04
ANIM_CHARGE = 0x08
ANIM_PUNCH = 0x14
ANIM_SHAKE = 0x20
ANIM_GET_UP = 0x2C

_FRAME_BOXES: dict[int, tuple[int, int]] = {
    0x04: (0x37, 0x2E),
    0x06: (0x36, 0x2D),
    0x08: (0x33, 0x2E),
    0x0A: (0x32, 0x2D),
    0x14: (0x31, 0x00),
    0x16: (0x30, 0x00),
}

# (x0, x1, lane0, lane1) about his origin, inclusive. $30, the left punch's,
# is recorded with a negative width: $AB88 then needs the other box to
# contain [x - 32, x], which no player body is wide enough to do.
_SHAPES: dict[int, tuple[int, int, int, int]] = {
    0x2D: (-12, 12, -10, 10),
    0x2E: (-12, 12, -10, 10),
    0x36: (-32, 8, -2, 2),
    0x37: (-8, 32, -2, 2),
    0x32: (-32, 16, -8, 8),
    0x33: (-16, 32, -8, 8),
    0x31: (-32, 0, -8, 8),
}

# A player's attack and body boxes are lane +-8.
PLAYER_BOX_LANE = 8

# --- The actor's punch (controls-and-input.md, "Measured normal punch") --------------
#
# Its box ahead of the actor's origin, and the actor updates -- counted from the
# one that took the B edge -- on which +$34 is set: 3-12 frames after the edge
# for Axel and Adam, 5-14 for Blaze, at one player update every two frames.
_PUNCH_BOX_X: dict[int, tuple[int, int]] = {0: (16, 57), 1: (8, 54), 2: (18, 68)}
_PUNCH_LIVE: dict[int, tuple[int, int]] = {0: (2, 6), 1: (2, 6), 2: (3, 7)}
DEFAULT_PUNCH_BOX_X = (16, 54)
DEFAULT_PUNCH_LIVE = (3, 6)
PUNCH_LOCK_UPDATES = 10
PUNCH_DAMAGE = 1

# --- The hold ------------------------------------------------------------------------

HOLD_KNEE_DAMAGE = 2  # the holder's +$34 on $6A/$6C, read by $149DA
HOLD_THIRD_KNEE_DAMAGE = 3
HOLD_SUPLEX_DAMAGE = 5  # $151C4


class Outcome(Enum):
    NONE = auto()
    GRAB = auto()
    STRUCK = auto()  # the actor's strike on his body: code 2
    HIT = auto()
    # Code 3 landed on him but $3266 will not take the hold: he is in state
    # $B for nothing. ``boss_update`` plays it on and returns NONE.
    REFUSED = auto()


def _hi(value: float) -> int:
    """The high word of a 16.16 value, as the ROM's ``move.w`` reads it."""

    return math.floor(value)


@dataclass(frozen=True, slots=True)
class PunchSpec:
    """The actor's punch: its box's X reach ahead, the live updates, the lock."""

    box: tuple[int, int]
    live: tuple[int, int]
    lock: int = PUNCH_LOCK_UPDATES


def punch_spec(character_id: int | None) -> PunchSpec:
    if character_id is None:
        return PunchSpec(DEFAULT_PUNCH_BOX_X, DEFAULT_PUNCH_LIVE)
    return PunchSpec(
        _PUNCH_BOX_X.get(character_id, DEFAULT_PUNCH_BOX_X),
        _PUNCH_LIVE.get(character_id, DEFAULT_PUNCH_LIVE),
    )


# --- The simulation ----------------------------------------------------------------------


class AbadedeSim:
    """His object, reduced to what his states read and write."""

    __slots__ = (
        "x", "y", "primary", "sub", "t54", "vx", "vy", "anim", "jitter",
        "screen_x", "cam_x", "inert", "variant",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])

    def copy(self) -> AbadedeSim:
        return AbadedeSim(**{name: getattr(self, name) for name in self.__slots__})

    @property
    def facing_left(self) -> bool:
        return bool(self.anim & ANIM_MIRROR_BIT)

    @property
    def boxes(self) -> tuple[int, int]:
        return _FRAME_BOXES.get(self.anim, (0, 0))

    @classmethod
    def from_token(cls, boss: Boss, *, cam_x: int) -> AbadedeSim:
        x = boss.fine_x if boss.fine_x else float(boss.world_x)
        y = boss.fine_y if boss.fine_y else float(boss.world_y)
        screen_x = boss.screen_x if boss.screen_x else _hi(x) - cam_x + SCREEN_BIAS
        primary = boss.primary_state
        return cls(
            x=x,
            y=y,
            primary=primary,
            sub=boss.substate,
            t54=boss.timer_54,
            vx=boss.boss_vel_x,
            vy=boss.boss_vel_lane,
            anim=boss.anim,
            jitter=1,
            screen_x=screen_x,
            cam_x=cam_x,
            inert=_inert_updates(primary, boss.substate, boss.timer_54),
            variant=bool(boss.script_param & 0x0F),
        )


def _inert_updates(primary: int, sub: int, t54: int) -> int:
    """Updates before a state the model does not replay hands him to state $A."""

    if primary == PRIMARY_KNOCKDOWN:
        # $14B98: on the floor, +$54 counts the last of it down.
        return t54 if sub == 3 and t54 else KNOCKDOWN_UPDATES
    if primary in (PRIMARY_THROWN, PRIMARY_SUPLEXED):
        return THROWN_UPDATES
    if primary in (PRIMARY_DYING, PRIMARY_THROWS_PLAYER):
        return FOREVER
    return 0


def _set_anim(b: AbadedeSim, anim: int) -> None:
    """``$1572A``: a new animation, its mirror taken from ``+$1C`` (``$156E0``)."""

    b.anim = anim | (ANIM_MIRROR_BIT if b.vx < 0 else 0)


def _mirror_from_vx(b: AbadedeSim) -> None:
    """``$156E0``: facing the way he moves."""

    b.anim = (b.anim & ~ANIM_MIRROR_BIT) | (ANIM_MIRROR_BIT if b.vx < 0 else 0)


def _face(b: AbadedeSim, t: ActorSim) -> None:
    """``$15704``: facing the target (``$12A4E``'s long compare)."""

    b.anim = (b.anim & ~ANIM_MIRROR_BIT) | (ANIM_MIRROR_BIT if t.x - b.x < 0 else 0)


def _reaim(b: AbadedeSim, t: ActorSim) -> None:
    """``$1566E``: each velocity turned toward the target (a zero gap counts as
    ahead, a zero speed as positive), the facing following a turned X."""

    right = t.x - b.x >= 0
    down = t.y - b.y >= 0
    if (b.vx >= 0) != right:
        b.vx = -b.vx
        _mirror_from_vx(b)
    if (b.vy >= 0) != down:
        b.vy = -b.vy


def _walk_aimed(b: AbadedeSim, t: ActorSim) -> None:
    """``$1577C``: the walk animation (mirrored by the *old* velocity), 6 px an
    update on both axes, turned toward the target."""

    _set_anim(b, ANIM_WALK)
    b.vx = WALK_SPEED
    b.vy = WALK_SPEED
    _reaim(b, t)


def _gaps(b: AbadedeSim, t: ActorSim) -> tuple[int, int]:
    """``$12A78``'s high-word distances: (|lane|, |X|)."""

    return abs(_hi(t.y) - _hi(b.y)), abs(_hi(t.x) - _hi(b.x))


def _on_screen(b: AbadedeSim) -> bool:
    return ON_SCREEN_MIN <= b.screen_x < ON_SCREEN_MAX


def _emit(b: AbadedeSim) -> None:
    """The renderer's pass: ``+$28`` (bit 3 of his ``+$01`` skips the culling,
    so it is written off screen as well). The boxes follow the animation."""

    b.screen_x = _hi(b.x) - b.cam_x + SCREEN_BIAS


def _meets(lo: int, hi: int, ay: int, bx: int, by: int, shape: tuple[int, int, int, int]) -> bool:
    return (
        lo <= bx + shape[1]
        and hi >= bx + shape[0]
        and ay - PLAYER_BOX_LANE <= by + shape[3]
        and ay + PLAYER_BOX_LANE >= by + shape[2]
    )


def _his_box_hurts(b: AbadedeSim) -> bool:
    """``$1550E``: his box on a player is his grab in states 1/2 and the run's
    hit in the charge; state 3 drops it, and the punch's is erased by
    ``$14CDC`` in the same update."""

    if b.primary in (PRIMARY_APPROACH, PRIMARY_PAUSE):
        return True
    return b.primary == PRIMARY_CHARGE and b.sub == SUB_RUN


HIT_MARGIN_X = 2


def _hold_taken(a: ActorSim, b: AbadedeSim) -> bool:
    """``$3266``: the actor takes the hold his grab code hands it when the two
    face each other (front), or face the same way with him ahead of the actor
    (back, an unsigned compare of the X words). From behind the actor facing
    its way, the code lands on him -- state ``$B`` -- and the actor takes
    nothing: he stands up 24 px in front of it, reads ``+$7D`` = 0 and backs
    off. Measured live: one such contact cost four updates."""

    if a.facing_left != b.facing_left:
        return True
    ax, bx = _hi(a.x) & 0xFFFF, _hi(b.x) & 0xFFFF
    return bx < ax if a.facing_left else bx >= ax


def contact(
    b: AbadedeSim,
    a: ActorSim,
    *,
    punch: tuple[int, int] | None = None,
    margin: bool = True,
) -> Outcome:
    """``$AAA0`` in his update: the actor's attack box on his body first -- a
    strike (``punch``, the live box's X reach ahead of the actor) or the
    walking box's grab -- and only if that misses, his box on the actor's
    body. When the actor's box does meet his body and yet counts for nothing
    (a strike off his screen band, a grab refused to a holder), nothing else
    is tested either.

    The actor's body is taken at its widest both ways; ``margin`` grows his
    box by ``HIT_MARGIN_X`` on X only -- the lanes are exact integers on both
    sides, and the plan stands on the one lane where his box misses.
    """

    if a.untouchable:
        # $AA34 tests nothing on a player in a hit reaction (+$59 bit 1) or
        # with a contact code still latched in +$7C.
        return Outcome.NONE
    attack_id, body_id = b.boxes
    bx, by = _hi(b.x), _hi(b.y)
    ax, ay = _hi(a.box_x), _hi(a.box_y)
    body = _SHAPES.get(body_id)
    if body is not None:
        if punch is not None:
            lo, hi = (ax - punch[1], ax - punch[0]) if a.facing_left else (ax + punch[0], ax + punch[1])
            if _meets(lo, hi, ay, bx, by, body):
                if STRIKE_SCREEN_MIN <= b.screen_x < STRIKE_SCREEN_MAX:
                    return Outcome.STRUCK
                return Outcome.NONE
        elif a.walking:
            lo, hi = (ax - a.walk_reach, ax) if a.facing_left else (ax, ax + a.walk_reach)
            if _meets(lo, hi, ay, bx, by, body):
                if a.holding:
                    return Outcome.NONE
                return Outcome.GRAB if _hold_taken(a, b) else Outcome.REFUSED
    box = _SHAPES.get(attack_id)
    if box is None or not _his_box_hurts(b):
        return Outcome.NONE
    grow = HIT_MARGIN_X if margin else 0
    if (
        bx + box[0] - grow <= ax + a.body_reach
        and bx + box[1] + grow >= ax - a.body_reach
        and by + box[2] <= ay + PLAYER_BOX_LANE
        and by + box[3] >= ay - PLAYER_BOX_LANE
    ):
        return Outcome.HIT
    return Outcome.NONE


# --- One update of each state he fights in -------------------------------------------


def _approach_setup(b: AbadedeSim, t: ActorSim) -> None:
    """``$145F8``."""

    b.sub = SUB_RUN
    _walk_aimed(b, t)
    _face(b, t)


def _approach_step(b: AbadedeSim, t: ActorSim) -> None:
    """``$14616`` after its contact test."""

    _reaim(b, t)
    lane, adx = _gaps(b, t)
    if lane >= APPROACH_LANE_GATE:
        # loc_1564A: the lane always, X only this far out. No clamp.
        b.y += b.vy
        if adx >= APPROACH_X_GATE:
            b.x += b.vx
        return
    b.t54 = PAUSE_UPDATES
    b.primary = PRIMARY_PAUSE


def _pause_step(b: AbadedeSim, t: ActorSim) -> None:
    """``$14656`` after its contact test."""

    b.t54 = (b.t54 - 1) & 0xFFFF
    if b.t54:
        _reaim(b, t)
        return
    lane, adx = _gaps(b, t)
    if b.variant:
        if lane >= VARIANT_LANE_GATE:
            b.primary, b.sub = PRIMARY_APPROACH, SUB_SETUP
        else:
            b.primary, b.sub = PRIMARY_CHARGE, SUB_SETUP
    elif lane >= APPROACH_LANE_GATE:
        b.primary, b.sub = PRIMARY_APPROACH, SUB_SETUP
    elif RETREAT_DX_MIN < adx <= RETREAT_DX_MAX and _on_screen(b):
        b.primary, b.sub = PRIMARY_RETREAT, SUB_SETUP
    else:
        b.primary, b.sub = PRIMARY_CHARGE, SUB_SETUP


def _retreat_setup(b: AbadedeSim, t: ActorSim) -> None:
    """``$146FC``: the walk away from the target, facing it."""

    _walk_aimed(b, t)
    _face(b, t)
    b.vx = -b.vx
    b.vy = 0.0
    b.sub = SUB_RUN
    b.t54 = RETREAT_UPDATES


def _retreat_step(b: AbadedeSim) -> None:
    """``$1472E`` after its contact test (the screen test comes first)."""

    if _on_screen(b):
        b.t54 = (b.t54 - 1) & 0xFFFF
        if b.t54:
            b.x += b.vx
            b.y += b.vy
            return
    b.t54 = PAUSE_UPDATES
    b.primary, b.sub = PRIMARY_PAUSE, SUB_SETUP


def _charge_setup(b: AbadedeSim, t: ActorSim) -> None:
    """``$14BEC``: the run's animation, 12 px an update toward the target, no
    lane speed -- the lane he starts on is the lane he keeps."""

    _set_anim(b, ANIM_CHARGE)
    b.vy = 0.0
    b.vx = -CHARGE_SPEED
    _reaim(b, t)
    b.sub = SUB_RUN


def _charge_step(b: AbadedeSim, t: ActorSim) -> None:
    """``$14C38`` after its contact test. The screen edges are read off the
    ``+$28`` the last render left, before this update's step."""

    if abs(_hi(t.x) - _hi(b.x)) >= CHARGE_STOP_DX:
        b.x += b.vx
        b.y += b.vy
        if b.vx < 0:
            stop = b.screen_x <= CHARGE_EDGE_LEFT
        else:
            stop = b.screen_x >= CHARGE_EDGE_RIGHT
        if stop:
            # loc_14C74
            _walk_aimed(b, t)
            _reaim(b, t)
            b.t54 = 1
            b.primary, b.sub = PRIMARY_PAUSE, SUB_SETUP
        return
    b.t54 = BRAKE_UPDATES
    b.sub = SUB_BRAKE


def _brake_step(b: AbadedeSim) -> None:
    """``$14CB4``: no contact test."""

    b.t54 = (b.t54 - 1) & 0xFFFF
    if not b.t54:
        b.t54 = PUNCH_UPDATES
        _set_anim(b, ANIM_PUNCH)
        b.sub = SUB_PUNCH


def _punch_step(b: AbadedeSim) -> None:
    """``$14CDC``: its contact test lands nowhere (see ``_his_box_hurts``)."""

    b.t54 = (b.t54 - 1) & 0xFFFF
    if not b.t54:
        b.primary, b.sub = PRIMARY_RETREAT, SUB_SETUP


def _struck_setup(b: AbadedeSim, t: ActorSim) -> None:
    """``$1477A``: the shake's animation, facing the target."""

    b.t54 = SHAKE_UPDATES
    b.jitter = 1
    _set_anim(b, ANIM_SHAKE)
    _face(b, t)
    b.primary = PRIMARY_SHAKE


def _shake_step(b: AbadedeSim) -> None:
    """``$147A6``: a pixel either way (loc_12ADC), then the retreat."""

    b.t54 = (b.t54 - 1) & 0xFFFF
    if not b.t54:
        b.primary, b.sub = PRIMARY_RETREAT, SUB_SETUP
        return
    b.x += b.jitter
    b.jitter = -b.jitter


def _get_up_step(b: AbadedeSim, t: ActorSim) -> None:
    """State $A: ``$14A96`` then ``$14AFA``."""

    if b.sub == SUB_SETUP:
        _set_anim(b, ANIM_GET_UP)
        _reaim(b, t)
        _face(b, t)
        b.t54 = GET_UP_UPDATES
        b.sub = 1
        return
    b.t54 = (b.t54 - 1) & 0xFFFF
    if not b.t54:
        b.primary, b.sub = PRIMARY_APPROACH, SUB_SETUP


def _released_step(b: AbadedeSim, a: ActorSim) -> None:
    """A hold the actor is no longer in (``$148C8``, ``$14F06``): the next read
    of the holder's ``+$7D`` finds it clear and sends him to state 3."""

    if b.primary == PRIMARY_HELD_BACK:
        if b.sub == SUB_SETUP:
            b.sub = 1
        else:
            b.primary, b.sub = PRIMARY_RETREAT, SUB_SETUP
        return
    if b.sub == HELD_READING:
        b.primary, b.sub = PRIMARY_RETREAT, SUB_SETUP  # $149AA
    elif b.sub == HELD_KNEE_SHAKE:
        b.t54 = KNEE_SHAKE_UPDATES  # $14A10
        b.sub = HELD_KNEE_SHAKING
    elif b.sub == HELD_KNEE_SHAKING:
        b.t54 = (b.t54 - 1) & 0xFFFF  # $14A42
        if not b.t54:
            b.sub = HELD_STAND
    elif b.sub == HELD_STAND:
        # $1486E: stood 24 px in front of the (former) holder, facing it.
        d = -HOLD_STAND_DX if a.facing_left else HOLD_STAND_DX
        b.x = a.x + d
        b.y = a.y
        b.anim = (b.anim & ~ANIM_MIRROR_BIT) | (0 if a.facing_left else ANIM_MIRROR_BIT)
        b.t54 = HOLD_UPDATES
        b.sub = HELD_READING
    else:
        b.primary, b.sub = PRIMARY_KNOCKDOWN, SUB_SETUP
        b.inert = KNOCKDOWN_UPDATES


def boss_update(
    b: AbadedeSim,
    a: ActorSim,
    target: ActorSim | None = None,
    *,
    punch: tuple[int, int] | None = None,
    margin: bool = True,
) -> Outcome:
    """One of his updates: his state's code against the actor (his target is
    ``target`` when that is someone else), then the renderer. ``punch`` is the
    actor's live strike box, if it has one this update."""

    t = a if target is None else target
    p, s = b.primary, b.sub
    if (
        (p == PRIMARY_APPROACH and s != SUB_SETUP)
        or p == PRIMARY_PAUSE
        or (p == PRIMARY_RETREAT and s != SUB_SETUP)
        or (p == PRIMARY_CHARGE and s == SUB_RUN)
    ):
        # $154E0 first; any contact ends his update there.
        outcome = contact(b, a, punch=punch, margin=margin)
        if outcome is Outcome.REFUSED:
            b.primary, b.sub = PRIMARY_HELD, HELD_STAND
            outcome = Outcome.NONE
            _emit(b)
            return outcome
        if outcome is not Outcome.NONE:
            _emit(b)
            return outcome
    if p == PRIMARY_APPROACH:
        if s == SUB_SETUP:
            _approach_setup(b, t)
        else:
            _approach_step(b, t)
    elif p == PRIMARY_PAUSE:
        _pause_step(b, t)
    elif p == PRIMARY_RETREAT:
        if s == SUB_SETUP:
            _retreat_setup(b, t)
        else:
            _retreat_step(b)
    elif p == PRIMARY_CHARGE:
        if s == SUB_SETUP:
            _charge_setup(b, t)
        elif s == SUB_RUN:
            _charge_step(b, t)
        elif s == SUB_BRAKE:
            _brake_step(b)
        else:
            _punch_step(b)
    elif p == PRIMARY_STRUCK:
        _struck_setup(b, t)
    elif p == PRIMARY_SHAKE:
        _shake_step(b)
    elif p == PRIMARY_GET_UP:
        _get_up_step(b, t)
    elif p == PRIMARY_INIT:
        b.primary, b.sub = PRIMARY_APPROACH, SUB_SETUP
    elif p in (PRIMARY_HELD, PRIMARY_HELD_BACK):
        if not a.holding:
            _released_step(b, a)
    else:
        b.inert -= 1
        if b.inert <= 0:
            b.primary, b.sub = PRIMARY_GET_UP, SUB_SETUP
    _emit(b)
    return Outcome.NONE


# --- The plan ----------------------------------------------------------------------------

# How far ahead every candidate is played out, in updates (two frames each):
# the rest of a retreat (20), the pause (5), and a run from across the screen
# (~12) -- the whole cycle between two of his contacts.
HORIZON_UPDATES = 40
FIRST_UPDATES = 2
HOLD_CANDIDATES: tuple[int | None, ...] = (FIRST_UPDATES, 6, 14, None)
# The punch is pressed on one of these updates, standing still until then.
PUNCH_WAITS = tuple(range(7))
# Off the lane his run keeps: his box misses up to 16, the walking box still
# reaches his body up to 18.
SWEET_DY = (17, 18)
# Walking into him while he walks in or pauses: out of his walk box's lane
# (+-2 against +-8: 10) and inside his approach's gate (16).
WALK_IN_DY = (11, 15)
# While he backs off: just inside the gate, so the pause decides a run, with
# the sweet band a couple of lane steps away on the same side.
SET_UP_DY = (13, 15)
# In front of him while he cannot collide, the walking box on his body.
READY_LANE = 14
READY_REACH = 28
# Knocked down or getting up: this far off him on X, WALK_IN's lane.
WAIT_DX = 40

_SCORE_GRAB = 10_000
_SCORE_STRUCK = 5_000
_SCORE_HIT = -10_000
_SCORE_PER_UPDATE = 10
_REVERSE_X_COST = 3
_TOWARD_BONUS = 0.5
_KEEP_LANE_BONUS = 0.2
_DANGER_RUN = 400
_DANGER_GRAB = 300
_DANGER_PAUSE = 200


class EngageMode(Enum):
    """What the tail policy is doing -- see ``engage_mode``."""

    SWEET = auto()
    """His run is coming: 17-18 lanes off its lane, the walking box at him."""

    READY = auto()
    """He cannot collide and is grabbable next: in front of him, box out."""

    WALK_IN = auto()
    """He walks in or pauses: into him from 11-15 lanes off."""

    SET_UP = auto()
    """He backs off: just inside his gate, on the side the sweet band fits."""

    WAIT = auto()
    """Knocked down, thrown, getting up: off him on X, on WALK_IN's lane."""


@dataclass(frozen=True, slots=True)
class EngagePlan:
    """The stick this tick (or the punch), and why."""

    dir_x: int  # -1 left, 0, +1 right
    dir_y: int  # -1 up (smaller lane), 0, +1 down
    punch: bool
    mode: EngageMode
    outcome: str | None  # "grab" / "struck" / "hit" / None within the horizon
    at_update: int | None
    score: float


def _toward(a: ActorSim, b: AbadedeSim) -> int:
    dx = b.x - a.x
    if abs(dx) < 4:
        return -1 if a.facing_left else 1
    return 1 if dx > 0 else -1


def _facing(a: ActorSim) -> int:
    return -1 if a.facing_left else 1


def _run_is_coming(a: ActorSim, b: AbadedeSim) -> bool:
    """Is his run (or the one he is setting up) heading at the actor?"""

    if b.sub == SUB_SETUP:
        return True
    ahead = (a.x - b.x) * (1 if b.vx >= 0 else -1)
    return ahead > -(16 + a.body_reach)


def engage_mode(a: ActorSim, b: AbadedeSim) -> EngageMode:
    """Which of the plan's phases the actor is in, given his state."""

    p, s = b.primary, b.sub
    if p == PRIMARY_CHARGE and s in (SUB_SETUP, SUB_RUN):
        return EngageMode.SWEET if _run_is_coming(a, b) else EngageMode.SET_UP
    if p in (PRIMARY_CHARGE, PRIMARY_STRUCK, PRIMARY_SHAKE, PRIMARY_HELD, PRIMARY_HELD_BACK):
        return EngageMode.READY
    if p == PRIMARY_RETREAT:
        return EngageMode.READY if s == SUB_SETUP else EngageMode.SET_UP
    if p in (PRIMARY_APPROACH, PRIMARY_PAUSE, PRIMARY_INIT):
        return EngageMode.WALK_IN
    return EngageMode.WAIT


def _band_side(a: ActorSim, b: AbadedeSim, far: int) -> int:
    """+1 below his lane, -1 above: the side the actor is on while a band
    ``far`` lanes off fits in the street, else the other."""

    by = _hi(b.y)
    first = 1 if _hi(a.y) >= by else -1
    for side in (first, -first):
        if a.lane_lo <= by + side * far <= a.lane_hi:
            return side
    return first


def _lane_into(a: ActorSim, lo: int, hi: int) -> int:
    y = _hi(a.y)
    if y > hi:
        return -1
    if y < lo:
        return 1
    return 0


def _band(b: AbadedeSim, side: int, near: int, far: int) -> tuple[int, int]:
    by = _hi(b.y)
    ends = (by + side * near, by + side * far)
    return min(ends), max(ends)


class _Tail:
    """The tail policy of one rollout: whatever ``engage_mode`` says, the
    sides chosen once per rollout so it does not dither between them."""

    __slots__ = ("sweet_side", "walk_side")

    def __init__(self) -> None:
        self.sweet_side: int | None = None
        self.walk_side: int | None = None

    def move(self, a: ActorSim, b: AbadedeSim) -> tuple[int, int]:
        mode = engage_mode(a, b)
        toward = _toward(a, b)
        facing_him = _facing(a) == toward
        if mode is EngageMode.SWEET:
            if self.sweet_side is None:
                self.sweet_side = _band_side(a, b, SWEET_DY[1])
            lo, hi = _band(b, self.sweet_side, *SWEET_DY)
            return _band_step(a, toward, facing_him, lo, hi)
        if mode is EngageMode.READY:
            return _ready_step(a, b, toward, facing_him)
        if mode is EngageMode.WALK_IN:
            if self.walk_side is None:
                self.walk_side = _band_side(a, b, WALK_IN_DY[1])
            lo, hi = _band(b, self.walk_side, *WALK_IN_DY)
            dir_y = _lane_into(a, lo, hi)
            rel = (b.x - a.x) * _facing(a)
            dir_x = toward if (not facing_him or rel > READY_REACH) else 0
            if dir_x == 0 and dir_y == 0:
                # The walking box needs a walk: step along the band.
                dir_y = 1 if _hi(a.y) < (lo + hi) / 2 else -1
            return dir_x, dir_y
        if mode is EngageMode.SET_UP:
            side = _band_side(a, b, SWEET_DY[1])
            lo, hi = _band(b, side, *SET_UP_DY)
            dir_y = _lane_into(a, lo, hi)
            return (0 if facing_him else toward), dir_y
        # WAIT
        side = _band_side(a, b, WALK_IN_DY[1])
        lo, hi = _band(b, side, *WALK_IN_DY)
        dir_y = _lane_into(a, lo, hi)
        aim_x = b.x - toward * WAIT_DX
        dir_x = 0 if abs(aim_x - a.x) <= 3 else (1 if aim_x > a.x else -1)
        return dir_x, dir_y


def _band_step(a: ActorSim, toward: int, facing_him: bool, lo: int, hi: int) -> tuple[int, int]:
    """Into the lane band ``[lo, hi]`` with the walking box toward him:
    inside it, a walk at him; outside, whichever lane step lands in it --
    straight (a lane walk keeps the facing and the box) or diagonal (turning
    to him on the way) -- else the faster straight one."""

    y = _hi(a.y)
    if lo <= y <= hi:
        return toward, 0
    dir_y = 1 if y < lo else -1
    _, _, diagonal_y, straight_y = a.speeds
    if facing_him and lo <= _hi(a.y + dir_y * straight_y) <= hi:
        return 0, dir_y
    if lo <= _hi(a.y + dir_y * diagonal_y) <= hi:
        return toward, dir_y
    return (0 if facing_him else toward), dir_y


def _ready_step(a: ActorSim, b: AbadedeSim, toward: int, facing_him: bool) -> tuple[int, int]:
    """In front of him with the walking box on his body, walking: at him from
    further than the box reaches, along the lane once there, and a turn when
    he is behind the actor."""

    by, y = _hi(b.y), _hi(a.y)
    dir_y = _lane_into(a, by - READY_LANE, by + READY_LANE)
    rel = (b.x - a.x) * _facing(a)
    if rel > READY_REACH:
        return _facing(a), dir_y
    if rel >= -8:
        if dir_y == 0:
            dir_y = (1 if y < by else -1) if abs(y - by) > 6 else (-1 if y < by else 1)
            if not a.lane_lo <= a.y + dir_y * a.speeds[3] <= a.lane_hi:
                dir_y = -dir_y
        return 0, dir_y
    return toward, dir_y


def _end_danger(a: ActorSim, b: AbadedeSim) -> float:
    """What of his bears on where a rollout left the actor."""

    ax, ay = _hi(a.x), _hi(a.y)
    bx, by = _hi(b.x), _hi(b.y)
    lane = abs(ay - by)
    danger = 0.0
    if b.primary == PRIMARY_CHARGE and b.sub in (SUB_SETUP, SUB_RUN):
        if _run_is_coming(a, b) and lane <= 16:
            danger += _DANGER_RUN
    elif b.primary == PRIMARY_PAUSE and lane < APPROACH_LANE_GATE and abs(ax - bx) < 90:
        danger += _DANGER_PAUSE
    if b.primary in (PRIMARY_APPROACH, PRIMARY_PAUSE) and lane <= 10:
        ahead = (ax - bx) * (-1 if b.facing_left else 1)
        if -8 - a.body_reach <= ahead <= 32 + a.body_reach:
            danger += _DANGER_GRAB
    return danger


_MODE_COST = {
    EngageMode.SWEET: 0,
    EngageMode.READY: 1,
    EngageMode.WALK_IN: 3,
    EngageMode.SET_UP: 6,
    EngageMode.WAIT: 8,
}

_CANDIDATES: tuple[tuple[int, int], ...] = tuple(
    (dx, dy) for dx in (0, 1, -1) for dy in (0, -1, 1)
)


def _rollout(
    b: AbadedeSim,
    a: ActorSim,
    target: ActorSim | None,
    first: tuple[int, int],
    hold: int | None,
    tail: _Tail,
    *,
    actor_first: bool,
    horizon: int,
    punch: PunchSpec | None = None,
    punch_at: int | None = None,
) -> tuple[Outcome, int | None, AbadedeSim, ActorSim]:
    """Play one candidate out: ``first`` for ``hold`` updates (None: all of
    them), then the tail policy -- or, with ``punch_at``, ``first`` (standing,
    or walking toward him, which turns the actor) until that actor update,
    the punch on it in the facing the actor has then, and its lock.
    ``actor_first`` picks which body the next update reaches first: a
    snapshot can land on either side of ``$AD8E``'s VBlank wait, and the plan
    has to survive both."""

    moves = 0
    punched_on: int | None = None

    def step_actor() -> None:
        nonlocal moves, punched_on
        if punch_at is not None and moves >= punch_at and (
            punched_on is None or moves - punched_on < punch.lock
        ):
            if punched_on is None:
                # In the facing it has: the ROM samples the facing a punch
                # starts with, and a turn on the same press is a committed
                # miss (``execute._facing_prop``) -- the actor turns by walking.
                punched_on = moves
            a.walking = False
            a.vx = 0.0
            a.box_x, a.box_y = a.x, a.y
        else:
            move = first if hold is None or moves < hold else tail.move(a, b)
            actor_update(a, *move)
        moves += 1

    if actor_first:
        step_actor()
    for k in range(horizon):
        live = None
        if punched_on is not None and punch is not None:
            age = moves - 1 - punched_on
            if punch.live[0] <= age <= punch.live[1]:
                live = punch.box
        outcome = boss_update(b, a, target, punch=live, margin=True)
        if outcome is not Outcome.NONE:
            return outcome, k, b, a
        step_actor()
    return Outcome.NONE, None, b, a


def _score(outcome: Outcome, at: int | None, b: AbadedeSim, a: ActorSim) -> float:
    if outcome is Outcome.GRAB:
        return _SCORE_GRAB - _SCORE_PER_UPDATE * at
    if outcome is Outcome.STRUCK:
        return _SCORE_STRUCK - _SCORE_PER_UPDATE * at
    if outcome is Outcome.HIT:
        return _SCORE_HIT + _SCORE_PER_UPDATE * at
    return -(_MODE_COST[engage_mode(a, b)] + _end_danger(a, b))


def build_sims(
    actor: PlayableCharacter,
    boss: Abadede,
    *,
    camera: CameraRange | None = None,
) -> tuple[AbadedeSim, ActorSim]:
    """His object and the actor as the model takes them, from the tokens."""

    lane_lo, lane_hi = float(PLAYER_LANE_MIN), float(PLAYER_LANE_MAX)
    x_lo, x_hi = (camera.left, camera.right) if camera is not None else (-1e9, 1e9)
    cam_x = int(camera.left) - 0x20 if camera is not None else 0
    if boss.screen_x:
        cam_x = boss.world_x + SCREEN_BIAS - boss.screen_x
    a = ActorSim.from_token(actor, lane_lo=lane_lo, lane_hi=lane_hi, x_lo=x_lo, x_hi=x_hi)
    b = AbadedeSim.from_token(boss, cam_x=cam_x)
    return b, a


def plan_engage(
    actor: PlayableCharacter,
    boss: Abadede,
    *,
    camera: CameraRange | None = None,
    partner: PlayableCharacter | None = None,
    can_punch: bool = True,
) -> EngagePlan:
    """The stick (or the punch) for this tick: every candidate played against
    his AI. ``can_punch`` is False when a B press would not be a punch (a
    weapon in hand swings instead; an item underfoot is picked up)."""

    b0, a0 = build_sims(actor, boss, camera=camera)
    target0: ActorSim | None = None
    if partner is not None and boss.targets_player not in (None, actor.player_index):
        target0 = ActorSim.from_token(
            partner, lane_lo=a0.lane_lo, lane_hi=a0.lane_hi, x_lo=a0.x_lo, x_hi=a0.x_hi
        )
        target0.walking = False
        target0.vx = 0.0
        target0.untouchable = target0.unavailable = False
    moving_x = 1 if actor.vel_x > 0.5 else (-1 if actor.vel_x < -0.5 else 0)
    return plan_from_sims(
        b0,
        a0,
        target=target0,
        moving_x=moving_x,
        punch=punch_spec(actor.character_id) if can_punch else None,
    )


def _punch_worth_trying(b: AbadedeSim) -> bool:
    """Only his run can be met by a punch inside the horizon."""

    if b.primary == PRIMARY_CHARGE:
        return b.sub in (SUB_SETUP, SUB_RUN)
    return b.primary == PRIMARY_PAUSE


def plan_from_sims(
    b0: AbadedeSim,
    a0: ActorSim,
    *,
    target: ActorSim | None = None,
    moving_x: int = 0,
    punch: PunchSpec | None = None,
    horizon: int = HORIZON_UPDATES,
) -> EngagePlan:
    """``plan_engage`` on bodies already built -- the planner itself, for the
    tools and the offline tests that drive the model directly."""

    a0 = a0.copy()
    # A hit reaction's immunity ends on the floor landing, which the rollout
    # does not model -- so the plan assumes it already has.
    a0.untouchable = a0.unavailable = False
    toward_x = _toward(a0, b0)
    mode_now = engage_mode(a0, b0)
    best: EngagePlan | None = None

    def consider(first, hold, punch_at) -> None:
        nonlocal best
        worst: tuple[float, Outcome, int | None] | None = None
        for actor_first in (False, True):
            outcome, at, b, a = _rollout(
                b0.copy(), a0.copy(), target, first, hold, _Tail(),
                actor_first=actor_first, horizon=horizon, punch=punch, punch_at=punch_at,
            )
            score = _score(outcome, at, b, a)
            if worst is None or score < worst[0]:
                worst = (score, outcome, at)
            if outcome is Outcome.HIT:
                break  # already the worse of the two
        assert worst is not None
        score, outcome, at = worst
        if punch_at is None:
            if moving_x and first[0] == -moving_x:
                score -= _REVERSE_X_COST
            if first[0] == toward_x:
                score += _TOWARD_BONUS
            if first[1] == 0:
                score += _KEEP_LANE_BONUS
        if best is None or score > best.score:
            now = (0, 0) if punch_at == 0 else first
            best = EngagePlan(
                dir_x=now[0],
                dir_y=now[1],
                punch=punch_at == 0,
                mode=mode_now,
                outcome=None if outcome is Outcome.NONE else outcome.name.lower(),
                at_update=at,
                score=score,
            )

    for hold in HOLD_CANDIDATES:
        for first in _CANDIDATES:
            if hold is None and first == (0, 0):
                continue  # standing still is the (0, 0) first move's own tail
            consider(first, hold, None)
    if punch is not None and _punch_worth_trying(b0):
        for wait in PUNCH_WAITS:
            consider((0, 0), None, wait)
            if wait:
                # Walking toward him first is how the actor turns to him.
                consider((toward_x, 0), None, wait)
    assert best is not None
    return best


def simulate(
    boss: Abadede,
    actor: PlayableCharacter,
    inputs: Sequence[tuple[int, int]],
    *,
    camera: CameraRange | None = None,
    margin: bool = False,
) -> list[tuple[Outcome, float, float, int, int]]:
    """Play ``inputs`` (one stick per update) against his AI, for tests and
    tools: per update, the outcome and his ``(x, y, primary, substate)``."""

    b, a = build_sims(actor, boss, camera=camera)
    trace = []
    for move in inputs:
        outcome = boss_update(b, a, margin=margin)
        trace.append((outcome, b.x, b.y, b.primary, b.sub))
        if outcome is not Outcome.NONE:
            break
        actor_update(a, *move)
    return trace


# --- The hold loop ---------------------------------------------------------------------


def reads_the_hold(boss: Boss) -> bool:
    """Is he in the one substate of his hold that reads the holder's move?

    ``$148C8`` (state ``$B`` substate 1) acts on the holder's ``+$7D`` every
    update; substate 0 is the update that stands him in front of the holder,
    2-3 the shake a knee buys (12 updates in all), and none of them read it.
    A knee pressed during the shake is read only once the shake is over --
    by then late in its animation -- so the loop waits for this.
    """

    return boss.primary_state == PRIMARY_HELD and boss.substate == HELD_READING


def hold_step(actor: PlayableCharacter, boss: Boss) -> HoldStep:
    """Knee, knee, release -- each on an update he reads -- and a finisher
    only when it kills.

    Front hold (``$60``): two knees (2 points each), then the release -- he
    reads the cleared ``+$7D`` and goes to state 3, whose first contact test
    on his feet 24 px in front of the actor is the re-grab. The third knee
    (``$6E``, 3 points) only when it kills: otherwise it knocks him down and
    the next hold is a whole charge away.

    Back hold (``$66``, a grab taken from behind): the suplex (5 points) only
    when it kills; else the one crossover the hold allows, which he reads as
    "held on" (9: the timer at 30) and which lands the actor in a front hold
    and its knees -- in state ``$D`` (a back hold he was handed as one) a
    crossover frees him, so that one is released.
    """

    hp = signed_health(boss)
    base = actor.action_base
    reading = reads_the_hold(boss)
    if base == 0x60:
        if not reading:
            return HoldStep.WAIT
        if actor.knees_in_chain < 2 or hp <= HOLD_THIRD_KNEE_DAMAGE:
            return HoldStep.KNEE
        return HoldStep.RELEASE
    if base == 0x66:
        if hp <= HOLD_SUPLEX_DAMAGE:
            return HoldStep.SUPLEX
        if boss.primary_state == PRIMARY_HELD:
            if not reading:
                return HoldStep.WAIT
            if not actor.crossover_spent:
                return HoldStep.CROSS
        return HoldStep.RELEASE
    return HoldStep.WAIT


def charge_is_pressing(boss: Boss) -> bool:
    """His run is on its way or running: the moments no other business may
    take the actor's stick."""

    if boss.primary_state == PRIMARY_CHARGE:
        return boss.substate in (SUB_SETUP, SUB_RUN)
    return boss.primary_state == PRIMARY_PAUSE and boss.timer_54 <= 2
