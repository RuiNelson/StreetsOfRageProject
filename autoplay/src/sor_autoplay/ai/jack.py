"""Jack (type ``$27``) and his axes (type ``$28``): the ROM model, and the plan.

Everything the AI does against him is decided here, as pure functions of the
tokens already in the context, so the decision (``decide``), the ranking
(``priority``) and the controller (``execute``) cannot disagree about it -- the
arrangement the boss modules have.

**Jack never hits anyone himself.** No animation in his set carries a strike
box (``$2556C``: the only attack boxes are the thrown-body flight's and his
axes'), and none of his state handlers tests one against a player. Every hit
he lands is one of his type-``$28`` axes -- so the plan is built around them:

**Take the hold from where no axe reaches, keep it until his axes are gone,
then spend it: knee, knee, cross over, suplex.**

The facts, all read from the disassembly (``ai-analysis/enemy-ai.md``,
"Jack"), each checked against a live trace (``tools/jack_fight.py``):

His states (``$1037C``, nineteen words)
    ``$01`` re-reads the target and jumps through ``$F2DE`` by his ``+$40``
    low nibble -- his *personality*, fixed by the ELC spawn record: 0 the
    juggle approach ``$0C``, 1 the retreat ``$0D``, 2 the jump ``$0F``, 3 the
    juggle walk ``$12``. Every reset ends there, so each Jack runs one loop:

    - 0: walk (2 px an update) to 108 px on his side of the target, on its
      lane (``$0C``, juggling); step to lane 8 or 56 -- the half the target is
      not in -- then 40 px toward it (``$08``); gate on the X distance
      (``$09``): past 64 px, back off diagonally onto its lane (``$0A`` --
      2.75 px an update *away* on X, 2.125 toward on the lane) and throw both
      axes along it (``$0B``); 40-64 px, start over; closer, back off 40 px at
      3.5 and gate again;
    - 1: retreat to the screen edge behind him and wander eight random lanes
      (``$0D``), then throw three (``$0E``); the target within 64 px on X
      aborts either into the lane dodge ``$07``;
    - 2: jump at a point near the target (``$0F``), land, then look about
      (``$10`` -- no contact test at all), throw three (``$0E``) or jump again;
    - 3: walk one animation cycle toward a point near the target, juggling
      (``$12``), then again -- or, one time in eight, throw three.
The juggle (``$F544`` spawns two axes 8 updates apart; ``$FCB6``)
    each axe flies an arc pinned to *absolute* z 128 (``move.w #$0080``),
    whatever the floor: up at -9 with ``$973E``'s gravity 1.125 for 15
    updates (apex 96), then 4 px an update back to his hand on the ground, 20
    updates a cycle. It rides 8 lanes below him at ``+$54`` px from his X,
    that offset set to +24 (facing right) or -8 (left) at each arc's start
    and drifting -1 an update: always 8-24 px in front of him. Its box
    (``$2B``, ``$2C`` for the torch set) is +-11 x +-8 x 12 high -- so on a
    floor at 160 it only meets a standing body near the bottom of its arc.
    An arc that ends with his animation off 0/2 (hit, held, throwing) drops
    the axe harmlessly (state 3, no contact test).
The throws (``$F410``, ``$F728``, ``$FEE4``)
    a thrown axe waits 16 px behind his hand and 64 px up (over every head)
    until his animation shows frame 1, then flies from 32 px in front of him
    at 10 px an update along his lane - 1, at his feet - 48 (Blaze's head).
    ``$0E`` spawns one every 12 updates (frames of 3), three in all; ``$0B``
    throws the second juggled axe the moment it returns to his hand and
    tosses the first high, to be thrown when it falls back.
Contact (``$AAA0``, ``$AB88`` inclusive on all three axes)
    the actor's walking box against his body -- ``$24`` (-12..0) facing
    right, ``$3C`` (0..12) facing left: all of it *behind* his origin -- with
    8 px of height is the grab; the axes test their own boxes on the actor's
    body in their own updates. A held Jack is placed 32 px in front of the
    holder (28 in a back hold), and his axes still in flight follow him.

Out of that, one geometry is safe by construction: **behind him**. The
juggle and every throw point the way he faces, and a hold taken from his back
keeps the axes still in the air on the far side until they drop. The planner
does not hard-code it: it is what the lookahead finds, because the front of a
juggling Jack ends in a simulated axe, and so does a front hold (the ``burnt``
check replays the axes over the hold's first updates).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Sequence

from ..world_map import LANE_Y_MAX_DEFAULT, LANE_Y_MIN
from .abadede import PUNCH_DAMAGE, PunchSpec, punch_spec
from .antonio import ActorSim, actor_update
from .jump_kick import DEFAULT_BODY, STANDING_BODY
from .souther import HoldStep
from .tokens import CameraRange, Jack, PlayableCharacter, Projectile
from .tokens.character import (
    BOTTLE_TYPE,
    KNIFE_TYPE,
    MELEE_WEAPON_SWING_BACK_X,
    MELEE_WEAPON_SWING_LIVE_UPDATES,
    MELEE_WEAPON_SWING_LOCK_UPDATES,
    MELEE_WEAPON_TYPES,
    swing_peak_x,
)

__all__ = [
    "AXE_TYPE",
    "EngageMode",
    "EngagePlan",
    "HoldStep",
    "JACK_TYPE",
    "hold_step",
    "plan_engage",
]

JACK_TYPE = 0x27
AXE_TYPE = 0x28

# --- His states ($1037C) ---------------------------------------------------------

ST_ACTIVATE = 0x00
ST_RESELECT = 0x01  # $F2CE -> $F2DE[+$40 & $F]
ST_HITSTUN = 0x02  # $9B36
ST_KNOCKDOWN = 0x03  # $F2AC -> $11
ST_PEPPER = 0x04  # $A43E
ST_HELD = 0x05  # $A04A
ST_DYING = 0x06  # $9D16
ST_EVADE = 0x07  # $F2BC -> $DBCC
ST_LANE_SETUP = 0x08  # $F5F2
ST_GATE = 0x09  # $F64A
ST_BACK_OFF = 0x0A  # $F6BC
ST_ALIGNED_THROW = 0x0B  # $F728
ST_APPROACH = 0x0C  # $F55E
ST_RETREAT = 0x0D  # $F4A6
ST_THROW = 0x0E  # $F410
ST_JUMP = 0x0F  # $F2E6
ST_LOOK = 0x10  # $F3B6
ST_FALLING = 0x11  # $991A
ST_JUGGLE_WALK = 0x12  # $F286 -> $E20A

# $F2DE: the state every reset lands in, by personality (+$40 low nibble).
PERSONALITY_STATE = (ST_APPROACH, ST_RETREAT, ST_JUMP, ST_JUGGLE_WALK)

# Handlers that run a contact test ($A9BA / $F7C0 / $9B88): the grab can only
# be taken in these. $10 tests nothing; the knockdown and the pepper freeze are
# left out (the first cannot be grabbed, the second is not known to be).
GRABBABLE_STATES = frozenset(
    {
        ST_HITSTUN,
        ST_EVADE,
        ST_LANE_SETUP,
        ST_GATE,
        ST_BACK_OFF,
        ST_ALIGNED_THROW,
        ST_APPROACH,
        ST_RETREAT,
        ST_THROW,
        ST_JUMP,
        ST_JUGGLE_WALK,
    }
)
DOWN_STATES = frozenset({ST_KNOCKDOWN, ST_FALLING, ST_DYING})

# His animation words (+$08, bit 1 the mirrored member).
ANIM_IDLE = 0x00  # the juggle stance: his axes keep flying only over 0 / 2
ANIM_THROW = 0x14
ANIM_JUMP = 0x20
ANIM_MIRROR_BIT = 0x02
THROW_ANIM_FRAMES = 4  # set animation $0A

# --- His axes ($FC14, the relative table at $103A2) ------------------------------------

AXE_INIT = 0  # $FC66
AXE_JUGGLED = 1  # $FCB6
AXE_TOSSED = 2  # $FE46
AXE_DROPPED = 3  # $FED6: falls to the floor; tests nothing itself, but its box still hits
AXE_THROWN = 4  # $FEE4
AXE_SPAWNER = 5  # $FC1C: spawns the two juggled axes

# --- Geometry --------------------------------------------------------------------

BODY_X = {False: (-12, 0), True: (0, 12)}  # $24 / $3C, keyed by facing_left
BODY_LANE = 8
JACK_BODY_Z = (-60, 0)
GRAB_Z = 8  # $AAA0: the grab needs 8 px of height
CONTACT_LANE = 16  # +-8 walking box against a +-8 body, inclusive
AXE_BOX = {
    0x2B: (-11, 11, -8, 8, -10, 2),
    0x2C: (-7, 7, -8, 8, -14, 0),
}
AXE_BOX_DEFAULT = 0x2B
TORCH_PARAM_BIT = 0x10  # his +$40 bit 4: animation $1C, box $2C
PLAYER_LANE_HALF = 8
HOLD_FRONT_DX = 32  # $A0B8: a held ordinary enemy stands 32 px in front ...
HOLD_BACK_DX = 28  # ... 28 in a back hold ($A112)

# --- The juggle ($FCB6) and the throws ($F410, $F728, $FEE4, $FE46) --------------------

JUGGLE_Z = 128.0
JUGGLE_VZ = -9.0
JUGGLE_VX = -1.0
RETURN_VX = 4.0
HAND_DX = {False: 24, True: -8}
JUGGLE_LANE = 8
SPAWN_GAP = 8
GRAVITY = 1.125  # $973E
VZ_CAP = 16.0
THROW_WAIT_DX = 16
THROW_RELEASE_DX = 48
THROW_SPEED = 10.0
THROW_WAIT_Z = 64
THROW_DROP_Z = 16
THROW_LANE = -1
THROW_RELEASE_FRAME = 1
RANGED_THROW_FRAME_UPDATES = 3  # $F410's $0303
RANGED_THROW_COUNT = 4  # $50 = 4: three spawned, the fourth loop ends it
TOSS_VZ = -22.0
TOSS_TOP = -20
TOSS_HANG = 32
ALIGNED_WAIT = 0x50  # $F728: +$54, the wait for his axe to reach the hand
ALIGNED_SECOND = 0x30  # +$50, the wait for the second throw
ABORT_DX = 0x40  # $F482

# --- His walks -----------------------------------------------------------------------

ARRIVE = 4  # $9604
APPROACH_DX = 0x6C
APPROACH_SPEED = 0x200
APPROACH_TIMEOUT = 0xA0
LANE_SETUP_SPLIT = 0x20
LANE_SETUP_HIGH = 0x08
LANE_SETUP_LOW = 0x38
STEP_DX = 0x28
GATE_FAR = 0x40
GATE_NEAR = 0x28
BACKOFF_SPEED = 0x380
BACK_OFF_VX = 2.75  # $0002C000
BACK_OFF_VY = 2.125  # $00022000
ALIGN_LANE = 8
ENEMY_LANE_MIN = 0x02  # $A00E
ENEMY_LANE_MAX = 0x70
SCREEN_BIAS = 0x80
ON_SCREEN = (0x80, 0x1C0)  # $97CE
RETREAT_EDGE = {True: 0x120, False: 0x20}  # cam_x + this, keyed by facing_left
EVADE_LANE_SPEED = 3.0  # $DBCC
EVADE_SPLIT = 0x38
EVADE_BOTTOM = 0x58
EVADE_TOP = 0x18
EVADE_PAST_DX = 0x50
# $DD26: each leg of the walk past the target is a random pair from $DD68 --
# 2.5, 3, 4 or 5 px an update -- for a random $1033A count of 16, 8, 10 or 5
# updates. The plan keeps the observed leg's speed; EVADE_WALK starts one.
EVADE_LEG_SPEEDS = (2.5, 3.0, 4.0, 5.0)
EVADE_LEG_UPDATES = (16, 8, 10, 5)
EVADE_WALK = 3.0
# $DBCC's lane direction ignores the target's half on three levels (level_ is
# the 0-based round): round 4 always up, round 6 always down, round 7 by X.
LEVEL_ROUND_4 = 3
LEVEL_ROUND_6 = 5
LEVEL_ROUND_7 = 6
LEVEL_ROUND_8 = 7
EVADE_SPLIT_X_ROUND_7 = 0x388
# $9F96 (ordinary_enemy_advance_x_bounded): the level's bounds on the walk --
# X >= 0 ($2F0 exclusive in round 7) and < $1510 ($1400 in round 8). A step
# past one is refused and nothing else happens.
X_MAX = 0x1510
X_MAX_ROUND_8 = 0x1400
X_MIN_ROUND_7 = 0x2F0
DEFAULT_WALK_SPEED = 0x200
LOOK_UPDATES = 14
LANDING_UPDATES = 4
DOWN_UPDATES = 40
JUMP_VZ = -8.0
JUMP_SPEED = 0x280

# --- The plan ------------------------------------------------------------------------

HORIZON_UPDATES = 16
FIRST_UPDATES = 2
POST_GRAB_UPDATES = 22  # an arc still in the air when the hold lands, and its return
HIT_MARGIN_X = 2
HIT_MARGIN_LANE = 1
BACK_DX = 22  # behind him: the walking box reaches his body, no axe reaches the actor
FRONT_DX = 10
AROUND_DY = 14  # the lane pocket above a juggle: 9+ lanes clear of it
BELOW_DY = 30  # ... or below it
POCKET_DY = 13  # in his $07: out of the juggle's lanes (-8 and a margin), in the punch's (CONTACT_LANE)
GRAB_REACH_X = 24  # the actor's walking box on his body, either side of him
EVADE_EXIT_DX = EVADE_PAST_DX + 8  # this far behind his walk, $DBCC reselects
# Where the actor waits out his $07, relative to cam_x: his exit 80 px past it
# (plus a step) then stays inside the screen's [0, $140) on either side.
EVADE_CENTRE = (EVADE_PAST_DX + 24, 0x140 - EVADE_PAST_DX - 24)
ZONE_AHEAD = (-16, 48)  # where a live juggle can meet a body, in his frame
ZONE_LANE = (-8, 24)
THROW_BAND = (-17, 15)  # player lanes a throw along his lane - 1 can meet
SIDE_DEADBAND_X = 4

_SCORE_GRAB = 10_000
_SCORE_HIT = -10_000
_SCORE_PER_UPDATE = 10
_DANGER_JUGGLE = 300
_DANGER_THROW = 250
_MODE_COST = {}  # filled below, after EngageMode
_REVERSE_X_COST = 3
_TOWARD_BONUS = 0.5
_KEEP_LANE_BONUS = 0.2

# The hold ($A2EC subtracts exactly 5 for the suplex; knees are the holder's +$34).
HOLD_KNEE_DAMAGE = 2
HOLD_THIRD_KNEE_DAMAGE = 3
HOLD_SUPLEX_DAMAGE = 5

_SIN_COS = [(0, 0xFFFF)] + [
    (
        round(65536 * math.sin(math.atan(r / 64.0))),
        min(0xFFFF, round(65536 * math.cos(math.atan(r / 64.0)))),
    )
    for r in range(1, 64)
]


class Outcome(Enum):
    NONE = auto()
    GRAB = auto()
    HIT = auto()
    STRUCK = auto()  # the actor's punch landed on him: his hitstun


# The punch (the actor's own, abadede.punch_spec): a hit on him is $9B88's
# stun -- 24 updates, reseeded by every new hit, his pose off the juggle stance
# so each axe drops at the end of its arc, his juggle latch cleared.
HITSTUN_UPDATES = 0x18
HIT_PUSH_X = 2
ANIM_HIT = 0x08
ANIM_HELD = 0x10
PUNCH_WAITS = tuple(range(7))
# A B pressed while $3028 still sees the last punch's +$59 bit 0 chains into
# the combo, whose finisher knocks him down -- and a knockdown hands him a fresh
# juggle when he gets up. So while he is stunned the plan does not punch again
# until the stun is nearly out.
REPUNCH_T50 = 8
PUNCH_REACH_X = 96  # worth trying: the punch box's outer edge and a few steps
PUNCH_REACH_LANE = 24
_SCORE_STRUCK = 6_000


class EngageMode(Enum):
    """Where ``engage_aim`` sends the actor -- see that function."""

    BEHIND = auto()
    """On his back side: walk into his back; no axe points there."""

    FRONT = auto()
    """No axe of his is out or coming: walk straight into him."""

    AROUND = auto()
    """In front of a live juggle: round it by the lane pocket above it (or below)."""

    CLEAR = auto()
    """A throw is out or about to be, along the actor's lane: leave its band."""

    WAIT = auto()
    """He cannot be grabbed now (down, looking about): stand off behind him."""


_MODE_COST.update(
    {
        EngageMode.BEHIND: 0,
        EngageMode.FRONT: 0,
        EngageMode.AROUND: 10,
        EngageMode.CLEAR: 20,
        EngageMode.WAIT: 5,
    }
)


@dataclass(frozen=True, slots=True)
class EngagePlan:
    """The stick this tick, and why."""

    dir_x: int  # -1 left, 0, +1 right
    dir_y: int  # -1 up (smaller lane), 0, +1 down
    mode: EngageMode
    outcome: str | None  # "grab" / "hit" / "struck" / None within the horizon
    at_update: int | None
    score: float
    punch: bool = False  # press B now, facing him


def signed_health(jack: Jack) -> int:
    health = jack.health or 0
    return health - 0x10000 if health >= 0x8000 else health


def _hi(value: float) -> int:
    return math.floor(value)


def _vector_velocity(dx: int, dy: int, speed: int) -> tuple[float, float]:
    """``$982C``: ``speed`` (8.8) along the vector, quantized like the ROM."""

    major, minor = abs(dx), abs(dy)
    swapped = minor >= major
    if swapped:
        major, minor = minor, major
    ratio = 0 if major == 0 else min(63, (minor << 6) // major)
    if ratio == 0:
        along, across = speed, 0
    else:
        sin_r, cos_r = _SIN_COS[ratio]
        along, across = (cos_r * speed) >> 16, (sin_r * speed) >> 16
    vx, vy = (across, along) if swapped else (along, across)
    return (-vx if dx < 0 else vx) / 256.0, (-vy if dy < 0 else vy) / 256.0


# --- The simulation ----------------------------------------------------------------------


class JackSim:
    """His object, reduced to what his state code reads and writes."""

    __slots__ = (
        "slot", "x", "y", "z", "floor", "state", "flags", "facing_left", "vx", "vy", "vz",
        "aim_x", "aim_y", "speed", "t50", "t51", "t54", "anim", "frame", "countdown",
        "reload", "animating", "personality", "juggle", "torch", "alive", "hold_dx", "hp",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])

    def copy(self) -> JackSim:
        return JackSim(**{name: getattr(self, name) for name in self.__slots__})

    @classmethod
    def from_token(cls, jack: Jack, *, floor: float) -> JackSim:
        z = jack.fine_z or (float(jack.world_z) if jack.world_z else floor)
        return cls(
            slot=jack.slot,
            x=jack.fine_x if jack.fine_x else float(jack.world_x),
            y=jack.fine_y if jack.fine_y else float(jack.world_y),
            z=z,
            floor=floor,
            state=jack.state,
            flags=jack.flags_31,
            facing_left=jack.facing_left,
            vx=jack.grunt_vel_x,
            vy=jack.grunt_vel_y,
            vz=jack.vel_z,
            aim_x=jack.approach_x,
            aim_y=jack.approach_y,
            speed=jack.approach_speed or DEFAULT_WALK_SPEED,
            t50=jack.stun_timer,
            t51=jack.timer_51,
            t54=jack.timer_54,
            anim=jack.anim,
            frame=jack.anim_frame,
            countdown=jack.anim_countdown,
            reload=jack.anim_reload,
            animating=jack.animating,
            personality=jack.personality & 0x03,
            juggle=jack.has_projectile,
            torch=bool(jack.script_param & TORCH_PARAM_BIT),
            alive=not jack.is_defeated and jack.state != ST_DYING,
            hold_dx=0,
            hp=signed_health(jack),
        )

    @classmethod
    def ghost(cls, axe: Projectile, *, floor: float) -> JackSim:
        """A Jack no longer in the context -- killed, his object dying -- rebuilt
        from one of his axes: they keep flying (the walk back to his hand never
        looks at him, and restarts an arc), and drop at the end of an arc now
        that his pose is off the juggle stance. Traced live: his last knee
        killed him and his axes still hit the holder."""

        return cls(
            slot=axe.owner_slot, x=float(axe.world_x) - axe.offset, y=float(axe.world_y - JUGGLE_LANE),
            z=floor, floor=floor, state=ST_DYING, flags=0x01, facing_left=axe.offset < 0,
            vx=0.0, vy=0.0, vz=0.0, aim_x=axe.world_x, aim_y=axe.world_y, speed=0, t50=0, t51=0,
            t54=0, anim=ANIM_HELD, frame=0, countdown=0, reload=0, animating=False,
            personality=0, juggle=False, torch=False, alive=False, hold_dx=0, hp=-1,
        )

    @property
    def idle(self) -> bool:
        return (self.anim & ~ANIM_MIRROR_BIT) == ANIM_IDLE

    @property
    def throwing(self) -> bool:
        return (self.anim & ~ANIM_MIRROR_BIT) == ANIM_THROW


class AxeSim:
    """One of his axes, reduced to what its own update (``$FC14``) reads."""

    __slots__ = (
        "slot", "owner", "state", "entry", "x", "y", "z", "vx", "vz", "off", "returning",
        "released", "hanging", "t50", "t51", "box", "gone", "harmless",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])

    def copy(self) -> AxeSim:
        return AxeSim(**{name: getattr(self, name) for name in self.__slots__})

    @classmethod
    def from_token(cls, axe: Projectile, owner: int | None) -> AxeSim:
        flags = axe.flags_31
        return cls(
            slot=axe.slot,
            owner=owner,
            state=axe.state,
            entry=not flags & 0x01,
            x=axe.fine_x if axe.fine_x else float(axe.world_x),
            y=axe.fine_y if axe.fine_y else float(axe.world_y),
            z=axe.fine_z if axe.fine_z else float(axe.world_z),
            vx=axe.vel_x,
            vz=axe.vel_z,
            off=axe.offset,
            returning=bool(flags & 0x02) and axe.state == AXE_JUGGLED,
            released=bool(flags & 0x02) and axe.state == AXE_THROWN,
            hanging=bool(flags & 0x02) and axe.state == AXE_TOSSED,
            t50=axe.timer_50,
            t51=1,
            box=axe.attack_box_id if axe.attack_box_id in AXE_BOX else AXE_BOX_DEFAULT,
            gone=False,
            # A dropped one may be a strike's harmless copy; the token cannot
            # tell, so it counts as the arc's own, which keeps its damage.
            harmless=False,
        )

    @classmethod
    def spawned(cls, owner: int, state: int, box: int) -> AxeSim:
        return cls(
            slot=None, owner=owner, state=state, entry=True, x=0.0, y=0.0, z=0.0, vx=0.0,
            vz=0.0, off=0.0, returning=False, released=False, hanging=False, t50=2, t51=1,
            box=box, gone=False, harmless=False,
        )


class World:
    """Every Jack and every axe on screen, and what the actor is standing on."""

    __slots__ = (
        "jacks", "axes", "cam_x", "actor_z", "body", "spawned", "punch", "struck", "level",
        "damage",
    )

    def __init__(self, jacks, axes, cam_x, actor_z, body, level=None) -> None:
        self.jacks: list[JackSim] = jacks
        self.axes: list[AxeSim] = axes
        self.cam_x: int = cam_x
        self.actor_z: float = actor_z
        self.body: tuple[int, int, int, int, int, int] = body
        self.spawned: list[AxeSim] = []
        # The actor's live punch box this update ((inner, outer) px ahead of
        # it), and whether this press has already landed on someone.
        self.punch: tuple[int, int] | None = None
        self.struck: bool = False
        # What the live strike takes off: the punch's 1, a weapon's +$34.
        self.damage: int = PUNCH_DAMAGE
        # The 0-based round (``$FFFF02``), when known: his dodge's lane
        # direction and his walks' X bounds depend on it.
        self.level: int | None = level

    def copy(self) -> World:
        return World(
            [j.copy() for j in self.jacks],
            [x.copy() for x in self.axes],
            self.cam_x,
            self.actor_z,
            self.body,
            self.level,
        )


def _goto(j: JackSim, state: int) -> None:
    """``move.w #state<<8, +$30``: the next update runs the state's entry."""

    j.state = state
    j.flags = 0


def _face(j: JackSim, a: ActorSim, anim: int) -> None:
    """``$96C0``: a new animation from frame 0, facing the target."""

    j.facing_left = not (_hi(a.x) > _hi(j.x))
    j.anim = anim | (ANIM_MIRROR_BIT if j.facing_left else 0)
    j.frame = 0
    j.countdown = j.reload = 5


def _face_only(j: JackSim, a: ActorSim) -> None:
    """``$9E4C``: turn to the target, keeping the animation where it is."""

    j.facing_left = not (_hi(a.x) > _hi(j.x))
    j.anim = (j.anim & ~ANIM_MIRROR_BIT) | (ANIM_MIRROR_BIT if j.facing_left else 0)


def _on_screen(j: JackSim, world: World) -> bool:
    screen = _hi(j.x) - world.cam_x + SCREEN_BIAS
    return ON_SCREEN[0] <= screen < ON_SCREEN[1]


def _approach(j: JackSim) -> bool:
    """``$9604``: True once within 4 px on both axes; else aims the velocity."""

    dx = int(j.aim_x) - _hi(j.x)
    dy = int(j.aim_y) - _hi(j.y)
    if abs(dx) < ARRIVE and abs(dy) < ARRIVE:
        return True
    j.vx, j.vy = _vector_velocity(dx, dy, int(j.speed))
    return False


def _move(j: JackSim) -> None:
    j.x += j.vx
    j.y = min(max(j.y + j.vy, float(ENEMY_LANE_MIN)), float(ENEMY_LANE_MAX))


def _x_bounds(level: int | None) -> tuple[float, float]:
    """``$9F96``'s bounds on his X: [0, $1510), ($2F0, ...) in round 7, [..., $1400) in round 8."""

    lo = float(X_MIN_ROUND_7) if level == LEVEL_ROUND_7 else 0.0
    hi = float(X_MAX_ROUND_8) if level == LEVEL_ROUND_8 else float(X_MAX)
    return lo, hi


def _bounded_step(j: JackSim, level: int | None) -> None:
    """``$9F96`` (ordinary_enemy_advance_x_bounded): his dodge's X step,
    refused -- and nothing else -- past the level's bounds. Traced live in
    round 5: walking right into $1510 he stood at X 5390 for 65 s."""

    lo, hi = _x_bounds(level)
    nx = j.x + j.vx
    if j.vx < 0:
        blocked = nx <= lo if level == LEVEL_ROUND_7 else nx < lo
    else:
        blocked = nx >= hi
    if not blocked:
        j.x = nx


def _evade_goes_down(j: JackSim, a: ActorSim, level: int | None) -> bool:
    """``$DBCC``'s lane direction: away from the target's half of the lanes,
    but always up in round 4, always down in round 6, and by his X in round 7."""

    if level == LEVEL_ROUND_6:
        return True
    if level == LEVEL_ROUND_7:
        return _hi(j.x) < EVADE_SPLIT_X_ROUND_7
    if level == LEVEL_ROUND_4:
        return False
    return _hi(a.y) < EVADE_SPLIT


def _spawn_juggle(j: JackSim, index: int, world: World) -> None:
    if not j.juggle:
        j.juggle = True
        world.spawned.append(AxeSim.spawned(index, AXE_SPAWNER, _box_for(j)))


def _box_for(j: JackSim) -> int:
    return 0x2C if j.torch else 0x2B


def _step_animation(j: JackSim) -> None:
    """``$B0C8``, at the end of his update: +$0D counts down while animating."""

    if not j.animating:
        return
    j.countdown -= 1
    if j.countdown <= 0:
        j.countdown = max(1, j.reload)
        j.frame = (j.frame + 1) % (THROW_ANIM_FRAMES if j.throwing else 4)


def grab_contact(j: JackSim, a: ActorSim, world: World) -> bool:
    """``$AAA0``'s grab: the walking box on his body, 8 px of height."""

    if not a.walking or a.holding or j.state not in GRABBABLE_STATES:
        return False
    if abs(world.actor_z - _hi(j.z)) > GRAB_Z:
        return False
    jx = _hi(j.x)
    b0, b1 = BODY_X[j.facing_left]
    px = _hi(a.box_x)
    w0, w1 = (px - a.walk_reach, px) if a.facing_left else (px, px + a.walk_reach)
    if w1 < jx + b0 or w0 > jx + b1:
        return False
    return abs(_hi(a.box_y) - _hi(j.y)) <= CONTACT_LANE


def _punch_span(a: ActorSim, box: tuple[int, int]) -> tuple[int, int]:
    px = _hi(a.box_x)
    return (px - box[1], px - box[0]) if a.facing_left else (px + box[0], px + box[1])


def punch_hits(j: JackSim, a: ActorSim, box: tuple[int, int], world: World) -> bool:
    """``$AAA0`` with the actor striking: its box on his body is code 2."""

    lo, hi = _punch_span(a, box)
    jx = _hi(j.x)
    b0, b1 = BODY_X[j.facing_left]
    if hi < jx + b0 or lo > jx + b1:
        return False
    if abs(_hi(a.box_y) - _hi(j.y)) > CONTACT_LANE:
        return False
    _, _, _, _, rz0, rz1 = world.body
    pz = _hi(world.actor_z)
    return _hi(j.z) + JACK_BODY_Z[0] <= pz + rz1 and _hi(j.z) >= pz + rz0


def _punch_meets_axe(x: AxeSim, a: ActorSim, box: tuple[int, int], world: World) -> bool:
    """The live punch box on an axe's body: code 2 for the axe, not its hit."""

    lo, hi = _punch_span(a, box)
    bx0, bx1, by0, by1, bz0, bz1 = AXE_BOX[x.box]
    ax, ay, az = _hi(x.x), _hi(x.y), _hi(x.z)
    if hi < ax + bx0 or lo > ax + bx1:
        return False
    if ay + by0 > _hi(a.box_y) + PLAYER_LANE_HALF or ay + by1 < _hi(a.box_y) - PLAYER_LANE_HALF:
        return False
    _, _, _, _, rz0, rz1 = world.body
    pz = _hi(world.actor_z)
    return az + bz0 <= pz + rz1 and az + bz1 >= pz + rz0


def _touch(j: JackSim, a: ActorSim, world: World) -> Outcome:
    """His contact test: the actor's live punch first (a strike is code 2 and
    no grab), else the walking box's grab."""

    if world.punch is not None and not world.struck and punch_hits(j, a, world.punch, world):
        return Outcome.STRUCK
    return Outcome.GRAB if grab_contact(j, a, world) else Outcome.NONE


def axe_hits(x: AxeSim, a: ActorSim, world: World, *, margin: bool = True) -> bool:
    """The axe's box on the actor's body, all three axes inclusive."""

    if a.untouchable:
        return False
    bx0, bx1, by0, by1, bz0, bz1 = AXE_BOX[x.box]
    ax, ay, az = _hi(x.x), _hi(x.y), _hi(x.z)
    px, py = _hi(a.box_x), _hi(a.box_y)
    mx = HIT_MARGIN_X if margin else 0
    ml = HIT_MARGIN_LANE if margin else 0
    reach = a.body_reach
    if ax + bx0 - mx > px + reach or ax + bx1 + mx < px - reach:
        return False
    if ay + by0 - ml > py + PLAYER_LANE_HALF or ay + by1 + ml < py - PLAYER_LANE_HALF:
        return False
    _, _, _, _, rz0, rz1 = world.body
    pz = _hi(world.actor_z)
    return az + bz0 <= pz + rz1 and az + bz1 >= pz + rz0


def jack_update(index: int, a: ActorSim, world: World) -> Outcome:
    """One update of his, against the actor."""

    j = world.jacks[index]
    if not j.alive:
        return Outcome.NONE
    st = j.state
    entry = not j.flags & 0x01
    if st != ST_HELD:
        j.flags |= 0x01
    outcome = Outcome.NONE

    if st == ST_ACTIVATE:
        _goto(j, ST_RESELECT)
    elif st == ST_RESELECT:
        _goto(j, PERSONALITY_STATE[j.personality])
    elif st == ST_APPROACH:
        if entry:
            _spawn_juggle(j, index, world)
            if not _on_screen(j, world):
                _goto(j, ST_EVADE)
                return outcome
            _face(j, a, ANIM_IDLE)
            j.animating = True
            j.aim_x = _hi(a.x) + (APPROACH_DX if _hi(j.x) > _hi(a.x) else -APPROACH_DX)
            j.aim_y = _hi(a.y)
            j.speed = APPROACH_SPEED
            j.t50 = APPROACH_TIMEOUT
        j.t50 -= 1
        if j.t50 <= 0:
            _goto(j, ST_RESELECT)
        elif (touched := _touch(j, a, world)) is not Outcome.NONE:
            outcome = touched
        elif _approach(j):
            _goto(j, ST_LANE_SETUP)
        else:
            _move(j)
    elif st == ST_LANE_SETUP:
        if entry:
            j.aim_y = LANE_SETUP_HIGH if _hi(a.y) > LANE_SETUP_SPLIT else LANE_SETUP_LOW
        if (touched := _touch(j, a, world)) is not Outcome.NONE:
            outcome = touched
        elif not _approach(j):
            _move(j)
        elif not j.t54 & 0x01:
            j.t54 |= 0x01
            j.aim_x += STEP_DX if _hi(a.x) > _hi(j.x) else -STEP_DX
        else:
            j.t54 = 0
            _goto(j, ST_GATE)
    elif st == ST_GATE:
        if entry:
            if not _on_screen(j, world):
                _goto(j, ST_EVADE)
                return outcome
            dx = abs(_hi(j.x) - _hi(a.x))
            if dx > GATE_FAR:
                _goto(j, ST_BACK_OFF)
                return outcome
            if dx > GATE_NEAR:
                _goto(j, ST_RESELECT)
                return outcome
            j.speed = BACKOFF_SPEED
            j.aim_x += STEP_DX if _hi(j.x) > _hi(a.x) else -STEP_DX
        if (touched := _touch(j, a, world)) is not Outcome.NONE:
            outcome = touched
        elif _approach(j):
            _goto(j, ST_GATE)
        else:
            _move(j)
    elif st == ST_BACK_OFF:
        if entry:
            j.vx = BACK_OFF_VX if _hi(a.x) < _hi(j.x) else -BACK_OFF_VX
            j.vy = BACK_OFF_VY if _hi(a.y) > _hi(j.y) else -BACK_OFF_VY
        if (touched := _touch(j, a, world)) is not Outcome.NONE:
            outcome = touched
        elif abs(_hi(a.y) - _hi(j.y)) > ALIGN_LANE:
            _move(j)
        else:
            _goto(j, ST_ALIGNED_THROW if _on_screen(j, world) else ST_EVADE)
    elif st == ST_ALIGNED_THROW:
        if entry:
            j.animating = True
            j.reload = j.countdown = 2
            j.t51 = 2
            j.t50 = ALIGNED_SECOND
            j.t54 = ALIGNED_WAIT
        if (touched := _touch(j, a, world)) is not Outcome.NONE:
            outcome = touched
        else:
            _aligned_throw(j, a)
    elif st == ST_RETREAT:
        if entry:
            _face(j, a, ANIM_IDLE)
            j.animating = True
            j.t50 = 8
        if (touched := _touch(j, a, world)) is not Outcome.NONE:
            outcome = touched
        elif abs(_hi(a.x) - _hi(j.x)) < ABORT_DX:
            _goto(j, ST_EVADE)
        else:
            if not j.flags & 0x08:
                j.flags |= 0x08
                j.aim_x = world.cam_x + RETREAT_EDGE[j.facing_left]
                if entry:
                    j.aim_y = _hi(j.y)
            if _approach(j):
                j.t50 -= 1
                if j.t50 <= 0:
                    _goto(j, ST_THROW)
                else:
                    # The next leg's lane is random ($F53C); assume he holds this one.
                    j.flags &= ~0x08
            else:
                _move(j)
    elif st == ST_THROW:
        if entry:
            _face(j, a, ANIM_THROW)
            j.reload = j.countdown = RANGED_THROW_FRAME_UPDATES
            j.animating = True
            j.t50 = RANGED_THROW_COUNT
            j.juggle = False
        if (touched := _touch(j, a, world)) is not Outcome.NONE:
            outcome = touched
        elif abs(_hi(a.x) - _hi(j.x)) < ABORT_DX:
            _goto(j, ST_EVADE)
        elif j.frame == 2:
            j.flags &= ~0x02
        elif j.frame == 0 and not j.flags & 0x02:
            j.flags |= 0x02
            j.t50 -= 1
            if j.t50 <= 0:
                _goto(j, ST_RESELECT)
            else:
                world.spawned.append(AxeSim.spawned(index, AXE_INIT, _box_for(j)))
    elif st == ST_JUMP:
        if entry:
            _face(j, a, ANIM_JUMP)
            j.animating = False
            j.aim_x, j.aim_y = _hi(a.x), _hi(a.y)
            j.speed = JUMP_SPEED
            _approach(j)
            j.vz = JUMP_VZ
            j.z += j.vz
        if (touched := _touch(j, a, world)) is not Outcome.NONE:
            outcome = touched
        elif not j.flags & 0x04:
            j.x += j.vx
            j.y = min(max(j.y + j.vy, float(ENEMY_LANE_MIN)), float(ENEMY_LANE_MAX))
            j.vz = min(j.vz + GRAVITY, VZ_CAP)
            j.z += j.vz
            if j.z >= j.floor:
                j.z = j.floor
                j.flags |= 0x04
                j.t50 = LANDING_UPDATES
        else:
            j.t50 -= 1
            if j.t50 <= 0:
                # $F3A2: look about, throw or jump again (random); the look is
                # the one the plan can least use -- assume it.
                _goto(j, ST_LOOK)
    elif st == ST_LOOK:
        if entry:
            j.t50 = LOOK_UPDATES
        j.t50 -= 1
        if j.t50 <= 0:
            _goto(j, ST_JUMP)
    elif st == ST_JUGGLE_WALK:
        if entry:
            _spawn_juggle(j, index, world)
            _face(j, a, ANIM_IDLE)
            j.frame = 1
            j.animating = True
            j.aim_x = _hi(a.x) + (STEP_DX if _hi(j.x) > _hi(a.x) else -STEP_DX)
            j.aim_y = _hi(a.y)
            j.speed = DEFAULT_WALK_SPEED
            _approach(j)
        if (touched := _touch(j, a, world)) is not Outcome.NONE:
            outcome = touched
        elif j.frame != 1:
            j.flags |= 0x08
            _move(j)
        elif j.flags & 0x08:
            _goto(j, ST_JUGGLE_WALK)
        else:
            _move(j)
    elif st == ST_EVADE:
        if entry:
            _face(j, a, ANIM_IDLE)
            j.animating = True
            j.vx = 0.0
            j.vy = EVADE_LANE_SPEED if _evade_goes_down(j, a, world.level) else -EVADE_LANE_SPEED
            if _hi(j.x) >= _hi(a.x):
                j.flags |= 0x04
            j.t50 = 0
        if (touched := _touch(j, a, world)) is not Outcome.NONE:
            outcome = touched
        else:
            # $9E4C, every update after the contact test: he faces the target.
            # In this state there is no "behind him" -- walk past him and he
            # turns, and the next arc of his juggle starts on the actor's side.
            _face_only(j, a)
        if outcome is Outcome.GRAB:
            pass
        elif not j.flags & 0x02:
            if (j.vy >= 0 and _hi(j.y) > EVADE_BOTTOM) or (j.vy < 0 and _hi(j.y) < EVADE_TOP):
                j.flags |= 0x02
                j.t50 = 0
            else:
                j.y = min(max(j.y + j.vy, float(ENEMY_LANE_MIN)), float(ENEMY_LANE_MAX))
        else:
            if j.vx == 0.0:
                j.vx = -EVADE_WALK if j.flags & 0x04 else EVADE_WALK
            if j.vx < 0 and _hi(a.x) - EVADE_PAST_DX > _hi(j.x):
                _goto(j, ST_RESELECT)
            elif j.vx > 0 and not _hi(a.x) + EVADE_PAST_DX > _hi(j.x):
                _goto(j, ST_RESELECT)
            else:
                _bounded_step(j, world.level)
    elif st in (ST_HITSTUN, ST_PEPPER):
        if st == ST_HITSTUN and (touched := _touch(j, a, world)) is not Outcome.NONE:
            outcome = touched
        else:
            j.t50 -= 1
            if j.t50 <= 0:
                _goto(j, ST_RESELECT)
    elif st in (ST_KNOCKDOWN, ST_FALLING):
        j.t54 = (j.t54 or DOWN_UPDATES) - 1
        if j.t54 <= 0:
            j.t54 = 0
            _goto(j, ST_RESELECT)
    elif st == ST_HELD:
        pass
    else:
        j.alive = st != ST_DYING

    if outcome is Outcome.GRAB:
        # $A9D4 only writes the state: $A04A places and poses him on his next
        # update (hold_is_burnt), so this pass's axes still see him juggling.
        j.state = ST_HELD
        return outcome
    if outcome is Outcome.STRUCK:
        _struck(j, a, world.damage)
        world.struck = True
        return outcome
    _step_animation(j)
    return outcome


def _struck(j: JackSim, a: ActorSim, damage: int = PUNCH_DAMAGE) -> None:
    """``$9B88``: the damage, 24 updates of stun, a 2 px push; dead only below 0."""

    j.hp -= damage
    j.juggle = False
    j.anim = ANIM_HIT | (ANIM_MIRROR_BIT if j.facing_left else 0)
    j.animating = False
    j.vx = j.vy = 0.0
    j.x += HIT_PUSH_X if _hi(j.x) > _hi(a.x) else -HIT_PUSH_X
    if j.hp < 0:
        j.state = ST_DYING
        j.alive = False
    else:
        j.state = ST_HITSTUN
        j.flags = 0x01
        j.t50 = HITSTUN_UPDATES


def _aligned_throw(j: JackSim, a: ActorSim) -> None:
    """``$F728`` past its entry: wait for the axe to reach his hand, throw it,
    then wait for the tossed one to come back down and throw that."""

    if not j.flags & 0x02:
        j.t54 -= 1
        if j.t54 <= 0:
            j.juggle = False
            _goto(j, ST_RESELECT)
            return
        if not j.flags & 0x08:
            return
        j.flags |= 0x02
        _face(j, a, ANIM_THROW)
        j.animating = False
    if j.flags & 0x10:
        j.animating = True
        if j.frame == 3:
            j.t51 -= 1
            if j.t51 <= 0:
                j.juggle = False
                _goto(j, ST_RESELECT)
                return
            j.flags &= ~0x10
            j.frame = 0
            j.animating = False
        return
    j.t50 -= 1
    if j.t50 <= 0:
        j.juggle = False
        _goto(j, ST_RESELECT)


def axe_update(x: AxeSim, a: ActorSim, world: World, *, margin: bool = True) -> Outcome:
    """One update of an axe, against the actor."""

    if x.gone:
        return Outcome.NONE
    j = world.jacks[x.owner] if x.owner is not None and x.owner < len(world.jacks) else None
    if x.state == AXE_SPAWNER:
        x.t51 -= 1
        if x.t51 <= 0:
            world.spawned.append(AxeSim.spawned(x.owner, AXE_JUGGLED, x.box))
            x.t50 -= 1
            if x.t50 <= 0:
                x.gone = True
            else:
                x.t51 = SPAWN_GAP
        return Outcome.NONE
    if x.state == AXE_INIT:
        x.state = AXE_THROWN
        x.entry = True
        return Outcome.NONE
    if x.state == AXE_DROPPED:
        return _dropped_update(x, a, world, margin=margin)
    if j is None:
        x.gone = True
        return Outcome.NONE
    if x.state == AXE_JUGGLED:
        return _juggle_update(x, j, a, world, margin=margin)
    if x.state == AXE_TOSSED:
        _toss_update(x, j)
        return Outcome.NONE
    if x.state == AXE_THROWN:
        return _thrown_update(x, j, a, world, margin=margin)
    x.gone = True
    return Outcome.NONE


def _dropped_update(x: AxeSim, a: ActorSim, world: World, *, margin: bool) -> Outcome:
    """``$FED6``: ``$100A4`` moves it (``+$1C``/``+$20``) and ``$973E`` drops
    it -- 1.125 an update, capped at 16 -- until the floor clears it. It tests
    nothing itself, but its box ($2B) stays in the player's hit test, and one
    dropped at the end of an arc keeps its damage: traced live, the arc his
    hold cut short fell 128, 137, 147, 158 onto the front holder 22 px away.
    A strike's knocked-off copy carries none (damage byte 0)."""

    hit = not x.harmless and axe_hits(x, a, world, margin=margin)
    x.x += x.vx
    x.vz = min(x.vz + GRAVITY, VZ_CAP)
    x.z += x.vz
    if x.z >= world.actor_z:
        x.gone = True
    return Outcome.HIT if hit else Outcome.NONE


def _juggle_update(x: AxeSim, j: JackSim, a: ActorSim, world: World, *, margin: bool) -> Outcome:
    if x.entry:
        x.entry = False
        x.z = JUGGLE_Z
        x.vz = JUGGLE_VZ
        x.vx = JUGGLE_VX
        x.off = float(HAND_DX[j.facing_left])
        x.returning = False
    hit = axe_hits(x, a, world, margin=margin)
    if hit and world.punch is not None and _punch_meets_axe(x, a, world.punch, world):
        # A strike on its body is code 2: a knocked-off copy, no hit this pass.
        hit = False
    x.y = j.y + JUGGLE_LANE
    x.x = _hi(j.x) + x.off
    x.off += x.vx
    if not x.returning:
        x.vz = min(x.vz + GRAVITY, VZ_CAP)
        x.z += x.vz
        if _hi(x.z) < JUGGLE_Z:
            return Outcome.HIT if hit else Outcome.NONE
        if not j.idle:
            x.state = AXE_DROPPED
            return Outcome.HIT if hit else Outcome.NONE
        x.returning = True
        x.vx = RETURN_VX
    if _hi(j.x) + HAND_DX[j.facing_left] > _hi(x.x):
        return Outcome.HIT if hit else Outcome.NONE
    if j.state == ST_ALIGNED_THROW:
        if not j.flags & 0x04:
            j.flags |= 0x04
            x.state = AXE_TOSSED
            x.entry = True
        else:
            j.flags |= 0x08
            x.state = AXE_THROWN
            x.entry = True
    else:
        x.entry = True
    return Outcome.HIT if hit else Outcome.NONE


def _toss_update(x: AxeSim, j: JackSim) -> None:
    if x.entry:
        x.entry = False
        x.vz = TOSS_VZ
        x.t50 = 0
        x.hanging = False
    if x.t50 > 0:
        x.t50 -= 1
        return
    x.vz = min(x.vz + GRAVITY, VZ_CAP)
    x.z += x.vz
    if not x.hanging:
        if _hi(x.z) > TOSS_TOP:
            return
        x.hanging = True
        x.vz = -x.vz
        x.x = _hi(j.x) + (THROW_WAIT_DX if j.facing_left else -THROW_WAIT_DX)
        x.t50 = TOSS_HANG - 1
        return
    if _hi(j.z) - THROW_WAIT_Z > _hi(x.z):
        return
    if j.throwing:
        x.state = AXE_THROWN
        x.entry = True
    else:
        x.state = AXE_DROPPED


def _thrown_update(x: AxeSim, j: JackSim, a: ActorSim, world: World, *, margin: bool) -> Outcome:
    if x.entry:
        x.entry = False
        x.released = False
        j.flags |= 0x10
        x.y = j.y + THROW_LANE
        x.z = j.z - THROW_WAIT_Z
        x.x = _hi(j.x) + (THROW_WAIT_DX if j.facing_left else -THROW_WAIT_DX)
    if not x.released:
        if j.frame != THROW_RELEASE_FRAME or not j.throwing:
            if not j.throwing:
                x.state = AXE_DROPPED
            return Outcome.NONE
        x.released = True
        x.z += THROW_DROP_Z
        x.vx = -THROW_SPEED if j.facing_left else THROW_SPEED
        x.x += -THROW_RELEASE_DX if j.facing_left else THROW_RELEASE_DX
    if world.punch is not None and _punch_meets_axe(x, a, world.punch, world):
        # $10044: a player strike bounces it harmlessly off the street.
        x.state = AXE_DROPPED
        x.harmless = True
        return Outcome.NONE
    if axe_hits(x, a, world, margin=margin):
        x.gone = True
        return Outcome.HIT
    screen = _hi(x.x) - world.cam_x + SCREEN_BIAS
    if not 0x70 <= screen < 0x1D0:
        x.gone = True
        return Outcome.NONE
    x.x += x.vx
    return Outcome.NONE


def world_update(world: World, a: ActorSim, *, margin: bool = True) -> tuple[Outcome, int | None]:
    """One object pass: every Jack, then every axe. Returns the first outcome
    and, for a grab or a strike, which Jack it was."""

    result, grabbed = Outcome.NONE, None
    for index in range(len(world.jacks)):
        outcome = jack_update(index, a, world)
        if outcome in (Outcome.GRAB, Outcome.STRUCK) and result is Outcome.NONE:
            result, grabbed = outcome, index
    for x in world.axes:
        outcome = axe_update(x, a, world, margin=margin)
        if outcome is Outcome.HIT:
            return Outcome.HIT, None
    if world.spawned:
        world.axes.extend(world.spawned)
        world.spawned = []
    world.axes = [x for x in world.axes if not x.gone]
    return result, grabbed


def hold_is_burnt(world: World, a: ActorSim, index: int, *, updates: int = POST_GRAB_UPDATES) -> bool:
    """A hold on Jack ``index``, played out with him pinned where the hold puts
    him: does any axe still in the air meet the actor before it drops?"""

    j = world.jacks[index]
    back = j.facing_left == a.facing_left
    side = -1 if a.facing_left else 1
    j.state = ST_HELD
    a.walking = False
    a.holding = True
    for update in range(updates):
        if update == 0:
            # $A04A's first pass places him in front of the holder -- but an axe
            # updated before him in the object pass still reads his juggle
            # stance, and an arc that ends now walks back to his hand. That leg
            # never looks at him again and restarts a whole arc: measured live,
            # a front hold burnt six updates after the grab by an axe the model
            # had dropped. So the stance stays for this pass.
            j.x = a.x + side * (HOLD_BACK_DX if back else HOLD_FRONT_DX)
            j.y = a.y
            j.z = world.actor_z
            j.facing_left = a.facing_left if back else not a.facing_left
        elif update == 1:
            j.anim = 0x10 | (ANIM_MIRROR_BIT if j.facing_left else 0)
            j.animating = False
        for x in world.axes:
            if axe_update(x, a, world) is Outcome.HIT:
                return True
        if world.spawned:
            world.axes.extend(world.spawned)
            world.spawned = []
        world.axes = [x for x in world.axes if not x.gone]
        if not world.axes:
            return False
    return False


# --- The plan ---------------------------------------------------------------------------


def _live_juggle(world: World, index: int) -> bool:
    j = world.jacks[index]
    if any(x.owner == index and x.state in (AXE_JUGGLED, AXE_SPAWNER) for x in world.axes):
        return True
    return j.state in (ST_APPROACH, ST_JUGGLE_WALK) and not j.juggle and j.alive


def _throw_lane(world: World, index: int, a: ActorSim) -> int | None:
    """The lane a throw of his is flying, or about to fly, along -- if it points
    at the actor's side of him."""

    j = world.jacks[index]
    toward = (_hi(a.x) - _hi(j.x)) * (-1 if j.facing_left else 1) > 0
    for x in world.axes:
        if x.owner != index:
            continue
        if x.state == AXE_THROWN:
            if not x.released and toward:
                return _hi(x.y) if not x.entry else _hi(j.y) + THROW_LANE
            if x.released and (_hi(a.x) - _hi(x.x)) * (1 if x.vx > 0 else -1) > -16:
                return _hi(x.y)
        if x.state in (AXE_INIT, AXE_TOSSED) and toward:
            return _hi(j.y) + THROW_LANE
    if j.state == ST_THROW and toward:
        return _hi(j.y) + THROW_LANE
    if j.state == ST_ALIGNED_THROW and toward:
        return _hi(j.y) + THROW_LANE
    return None


def _side(a: ActorSim, j: JackSim) -> int:
    dx = a.x - j.x
    if abs(dx) < SIDE_DEADBAND_X:
        return 1 if a.facing_left else -1
    return 1 if dx > 0 else -1


def _band_exit(a: ActorSim, j: JackSim) -> float:
    """The nearer lane out of his juggle's band (``ZONE_LANE``), the one above
    it when the actor is above his lane and there is room, and so on."""

    up = j.y + ZONE_LANE[0] - (AROUND_DY - PLAYER_LANE_HALF)
    down = j.y + ZONE_LANE[1] + (BELOW_DY - ZONE_LANE[1])
    if up < a.lane_lo:
        return min(a.lane_hi, down)
    if down > a.lane_hi:
        return up
    return up if a.y - up <= down - a.y else down


def _evade_exit(a: ActorSim, world: World, j: JackSim) -> float | None:
    """Where the actor stands to end his ``$07`` when waiting for him cannot:
    he is out of the actor's reach (past the camera clamp) and either pinned at
    the level's X bound on his walk or walking further away. ``$DBCC``
    reselects him once he is 80 px past the target on his walk: pinned, the
    actor steps that far behind it; walking away, it stands and his walk makes
    the distance (``None`` while he walks back into reach). Traced live in
    round 5: pinned at X 5390 by
    $1510, with the actor held at the camera's 5344 -- inside those 80 px --
    one Jack stood 65 s and the round clock ran out."""

    walk = -1 if j.flags & 0x04 else 1
    gap = j.x - min(max(j.x, a.x_lo), a.x_hi)
    if abs(gap) <= GRAB_REACH_X:
        return None
    lo, hi = _x_bounds(world.level)
    step = EVADE_LEG_SPEEDS[-1]
    pinned = j.x + step >= hi if walk > 0 else j.x - step <= lo
    if not pinned:
        if gap * walk < 0:
            return None  # he is walking back into reach
        # Walking on out of reach: stand, and his own walk makes the 80 px.
        # Traced live, an actor that went after the exit point kept pace ~70
        # px behind him and never let him reset.
        return a.x
    return min(max(j.x - walk * EVADE_EXIT_DX, a.x_lo), a.x_hi)


def engage_aim(a: ActorSim, world: World, index: int) -> tuple[EngageMode, float, float]:
    """Where the actor should be heading, given where he, his axes and it are.

    His juggle rides 8-24 px in front of him on lanes +0..+16 of his, so a
    body meets it anywhere ``ZONE_AHEAD`` x ``ZONE_LANE`` of him. Out of it
    there are two lanes -- 9+ above his (which still reaches his body with a
    grab) and 25+ below -- and one side: his back, 16+ px behind his origin.
    The aim leaves the band by the nearer lane, passes him on that side, and
    only comes back to his lane once clear of the band's back edge. In his
    dodge (``$07``) he turns to the actor every update, so there is no back:
    there the aim waits in the punch's pocket above him while he walks past
    (or at ``_evade_exit`` when waiting cannot end it).
    """

    j = world.jacks[index]
    facing = -1 if j.facing_left else 1
    ahead = (a.x - j.x) * facing
    dy = a.y - j.y
    back_x = j.x - facing * BACK_DX
    lane = _throw_lane(world, index, a)
    if lane is not None and THROW_BAND[0] - 2 <= a.y - lane <= THROW_BAND[1] + 2 and ahead > 0:
        up = lane + THROW_BAND[0] - 4
        down = lane + THROW_BAND[1] + 4
        if up < a.lane_lo:
            target = down
        elif down > a.lane_hi:
            target = up
        else:
            target = up if a.y - up <= down - a.y else down
        return EngageMode.CLEAR, a.x, target
    juggle = _live_juggle(world, index)
    in_band = ZONE_LANE[0] - 1 <= dy <= ZONE_LANE[1] + 1
    in_reach_x = ZONE_AHEAD[0] - 12 <= ahead <= ZONE_AHEAD[1] + 12
    if j.state == ST_EVADE and (exit_x := _evade_exit(a, world, j)) is not None:
        return EngageMode.AROUND, exit_x, a.y
    if not juggle:
        if j.state not in GRABBABLE_STATES:
            return EngageMode.WAIT, back_x - facing * 12, j.y
        if ahead <= -SIDE_DEADBAND_X:
            return EngageMode.BEHIND, back_x, j.y
        return EngageMode.FRONT, j.x + facing * FRONT_DX, j.y
    if j.state == ST_EVADE:
        # He faces the actor every update, so there is no back to go for. He
        # walks past it and leaves $07 only 80 px beyond it, and a reset off
        # screen fails $0C's entry test and puts him straight back in $07
        # (measured live: an actor that walked along with him to the camera
        # edge kept one Jack in this loop for 110 s). So wait mid-screen,
        # POCKET_DY lanes above him -- out of the juggle, in the punch's reach
        # -- and punch him as he walks by: the stun drops his axes. Traced
        # live, an actor that only kept out of the band sat at lane 2 while he
        # walked lane 91 to and fro for 50 s.
        centre_x = min(max(a.x, float(world.cam_x + EVADE_CENTRE[0])), float(world.cam_x + EVADE_CENTRE[1]))
        pocket_y = j.y - POCKET_DY
        if pocket_y >= a.lane_lo and dy < ZONE_LANE[0]:
            # Only from above his band: from below, the way there crosses it
            # (traced live, a punch thrown on the way, 15 lanes under him,
            # landed, and an axe finishing its arc hit the locked actor) --
            # there the actor waits below the band for his reset instead.
            return EngageMode.AROUND, centre_x, pocket_y
        if in_band:
            return EngageMode.AROUND, centre_x, _band_exit(a, j)
        return EngageMode.AROUND, centre_x, a.y
    if ahead <= ZONE_AHEAD[0] - 2:
        if j.state not in GRABBABLE_STATES:
            return EngageMode.WAIT, back_x - facing * 12, j.y
        return EngageMode.BEHIND, back_x, j.y
    if in_band:
        if in_reach_x or ahead < 0:
            # Inside the juggle's reach, or tucked just behind its back edge:
            # the lane first, and away from him on X while in front.
            aim_x = a.x if ahead < 0 else j.x + facing * (ZONE_AHEAD[1] + 16)
            return EngageMode.AROUND, aim_x, _band_exit(a, j)
        # In his lane band but out of the juggle's reach on X: climb out
        # before closing in.
        return EngageMode.AROUND, a.x, _band_exit(a, j)
    # Out of the band's lanes: pass him on this side, to his back.
    return EngageMode.AROUND, back_x - facing * 8, a.y


def _track(a: ActorSim, world: World, index: int) -> tuple[int, int]:
    """The tail policy: walk straight at the aim, diagonally where it can."""

    _, aim_x, aim_y = engage_aim(a, world, index)
    dir_x = 0 if abs(aim_x - a.x) <= 2 else (1 if aim_x > a.x else -1)
    dir_y = 0 if abs(aim_y - a.y) <= 1.5 else (1 if aim_y > a.y else -1)
    return dir_x, dir_y


def _time_to(a: ActorSim, aim_x: float, aim_y: float) -> float:
    straight_x, _, _, straight_y = a.speeds
    return max(abs(aim_x - a.x) / max(straight_x, 0.1), abs(aim_y - a.y) / max(straight_y, 0.1))


def _end_danger(world: World, a: ActorSim, index: int) -> int:
    danger = 0
    for i, j in enumerate(world.jacks):
        if not j.alive or j.state in DOWN_STATES:
            continue
        facing = -1 if j.facing_left else 1
        ahead = (a.x - j.x) * facing
        dy = a.y - j.y
        if _live_juggle(world, i) and ZONE_AHEAD[0] <= ahead <= ZONE_AHEAD[1] and ZONE_LANE[0] <= dy <= ZONE_LANE[1]:
            danger += _DANGER_JUGGLE
        lane = _throw_lane(world, i, a)
        if lane is not None and THROW_BAND[0] <= a.y - lane <= THROW_BAND[1]:
            danger += _DANGER_THROW
    return danger


_CANDIDATES: tuple[tuple[int, int], ...] = tuple((dx, dy) for dx in (0, 1, -1) for dy in (0, -1, 1))


def _rollout(
    world: World,
    a: ActorSim,
    index: int,
    first: tuple[int, int],
    hold: bool,
    *,
    actor_first: bool,
    punch: PunchSpec | None = None,
    punch_at: int | None = None,
) -> tuple[Outcome, int | None, World, ActorSim]:
    """Play one candidate out: ``first`` held (all along, or for
    ``FIRST_UPDATES`` and then the tail policy) -- or, with ``punch_at``,
    ``first`` (standing, or walking toward him, which turns the actor) until
    that actor update, the punch on it in the facing the actor has then, and
    its lock. A strike does not end the rollout: what follows it -- an axe on the
    locked actor, a grab once he is stunned -- still decides the score."""

    moves = 0
    punched_on: int | None = None
    struck_at: int | None = None

    def step_actor() -> None:
        nonlocal moves, punched_on
        if punch_at is not None and punch is not None and moves >= punch_at and (
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
            move = first if hold or moves < FIRST_UPDATES else _track(a, world, index)
            actor_update(a, *move)
        moves += 1

    if actor_first:
        step_actor()
    for k in range(HORIZON_UPDATES):
        world.punch = None
        if punched_on is not None and punch is not None:
            age = moves - 1 - punched_on
            if punch.live[0] <= age <= punch.live[1]:
                world.punch = punch.box
                world.damage = punch.damage
        outcome, grabbed = world_update(world, a)
        if outcome is Outcome.HIT:
            return outcome, k, world, a
        if outcome is Outcome.GRAB:
            if hold_is_burnt(world.copy(), a.copy(), grabbed):
                return Outcome.HIT, k + 1, world, a
            return outcome, k, world, a
        if outcome is Outcome.STRUCK and struck_at is None:
            struck_at = k
            if not world.jacks[grabbed].alive:
                # The punch killed him: as good as the hold.
                return Outcome.GRAB, k, world, a
        step_actor()
    world.punch = None
    if struck_at is not None:
        return Outcome.STRUCK, struck_at, world, a
    return Outcome.NONE, None, world, a


def _score(outcome: Outcome, at: int | None, world: World, a: ActorSim, index: int) -> float:
    if outcome is Outcome.GRAB:
        return _SCORE_GRAB - _SCORE_PER_UPDATE * at
    if outcome is Outcome.HIT:
        return _SCORE_HIT + _SCORE_PER_UPDATE * at
    if outcome is Outcome.STRUCK:
        return _SCORE_STRUCK - _SCORE_PER_UPDATE * at
    mode, aim_x, aim_y = engage_aim(a, world, index)
    return -(_time_to(a, aim_x, aim_y) + _MODE_COST[mode] + _end_danger(world, a, index))


def actor_body(actor: PlayableCharacter) -> tuple[int, int, int, int, int, int]:
    if actor.character_id is None:
        return DEFAULT_BODY
    return STANDING_BODY.get(actor.character_id, DEFAULT_BODY)


def build_world(
    actor: PlayableCharacter,
    jacks: Sequence[Jack],
    projectiles: Sequence[Projectile],
    *,
    camera: CameraRange | None = None,
    level: int | None = None,
) -> World:
    floor = float(actor.ground_z if actor.ground_z is not None else actor.world_z)
    if actor.is_airborne and actor.ground_z is None:
        floor = float(max((j.world_z for j in jacks), default=actor.world_z))
    sims = [JackSim.from_token(j, floor=floor) for j in jacks]
    index_of = {j.slot: i for i, j in enumerate(jacks)}
    for p in projectiles:
        if p.type_id == AXE_TYPE and p.owner_slot and p.owner_slot not in index_of:
            # His object is gone from the context (killed) but his axes fly on.
            index_of[p.owner_slot] = len(sims)
            sims.append(JackSim.ghost(p, floor=floor))
    axes = [
        AxeSim.from_token(p, index_of.get(p.owner_slot))
        for p in projectiles
        if p.type_id == AXE_TYPE and p.owner_slot in index_of
    ]
    cam_x = int(camera.left) - 0x20 if camera is not None else _hi(actor.world_x) - 0xA0
    for jack in jacks:
        if jack.screen_x:
            cam_x = jack.world_x + SCREEN_BIAS - jack.screen_x
            break
    return World(sims, axes, cam_x, floor, actor_body(actor), level)


# A weapon's own B, for the lookahead (user: "A IA não sabe que quando tem
# armas, pode atacar o Jack, mesmo que ele tenha tochas/machados, porque ao
# contrário de ataques só com os punhos, com armas, acertam no Jack sem ferir a
# personagem"). The weapon is its own object in the attacker list ($95CE), and
# $AAA0 tests a live strike box before anything lands on the striker: an axe
# whose box meets it is struck (``_punch_meets_axe``), not the actor. A bat or
# pipe's box sits out at the swing's peak (Axel 36, Blaze 53), ahead of the
# arm the axes would reach, and stays out longer than a fist -- which is what
# the user saw. What is unmeasured is *when* it is live: the swing commits the
# actor ~26 frames (13 updates), live only near its peak. So the plan plays
# every weapon strike under several live windows and keeps the worst, and a
# swing is only thrown when every one of them lands and nothing reaches the
# actor through the lock.
WEAPON_DAMAGE: dict[int, int] = {KNIFE_TYPE: 5, BOTTLE_TYPE: 3, 0x0A: 4, 0x0B: 4}
SWING_LOCK_UPDATES = MELEE_WEAPON_SWING_LOCK_UPDATES
SWING_LIVE_WINDOWS = tuple(
    (start, start + 2)
    for start in range(MELEE_WEAPON_SWING_LIVE_UPDATES[0], MELEE_WEAPON_SWING_LIVE_UPDATES[1] - 1, 2)
)
# Knife stab / bottle: the hand is the punch's; their live frames are not
# measured either, so the punch's and one two updates later.
STAB_LIVE_SHIFTS = (0, 2)


def strike_specs(character_id: int | None, weapon_type: int) -> tuple[PunchSpec, ...]:
    """Every timing a B press can have for this hand -- one for the punch,
    several for a weapon (``SWING_LIVE_WINDOWS``, ``STAB_LIVE_SHIFTS``), none
    for pepper spray (its B throws the can)."""

    punch = punch_spec(character_id)
    if weapon_type == 0:
        return (punch,)
    damage = WEAPON_DAMAGE.get(weapon_type)
    if damage is None:
        return ()
    if weapon_type in MELEE_WEAPON_TYPES:
        peak = swing_peak_x(character_id)
        box = (peak - MELEE_WEAPON_SWING_BACK_X, peak)
        return tuple(
            PunchSpec(box, live, SWING_LOCK_UPDATES, damage) for live in SWING_LIVE_WINDOWS
        )
    return tuple(
        PunchSpec(
            punch.box,
            (punch.live[0] + shift, punch.live[1] + shift),
            punch.lock + shift,
            damage,
        )
        for shift in STAB_LIVE_SHIFTS
    )


def _punch_worth_trying(world: World, index: int, a: ActorSim) -> bool:
    """A punch can land inside the horizon: on him (in a state that tests
    contact, and not while his stun still has more than ``REPUNCH_T50`` to
    run), or on a released throw coming at the actor."""

    j = world.jacks[index]
    near = abs(j.x - a.x) <= PUNCH_REACH_X and abs(j.y - a.y) <= PUNCH_REACH_LANE
    if near and j.state in GRABBABLE_STATES and not (
        j.state == ST_HITSTUN and j.t50 > REPUNCH_T50
    ):
        return True
    return any(
        x.state == AXE_THROWN
        and x.released
        and abs(x.y - a.y) <= PUNCH_REACH_LANE
        and 0 <= (a.x - x.x) * (1 if x.vx > 0 else -1) <= PUNCH_REACH_X + 40
        for x in world.axes
    )


def plan_engage(
    actor: PlayableCharacter,
    jack: Jack,
    *,
    others: Sequence[Jack] = (),
    projectiles: Sequence[Projectile] = (),
    camera: CameraRange | None = None,
    can_punch: bool = False,
    level: int | None = None,
    strikes: Sequence[PunchSpec] | None = None,
) -> EngagePlan:
    """The stick for this tick: every candidate played out against him and his axes.

    Seventeen candidates -- the nine stick positions, each either held for the
    whole horizon or for ``FIRST_UPDATES`` and then handed to the tail policy
    that walks at ``engage_aim`` -- and, with ``can_punch``, thirteen more that
    stand or walk toward him (the walk is the turn) and punch on update 0-6
    in the facing the actor has then; ``HORIZON_UPDATES`` updates each, over
    ``world_update``/``actor_update``, each twice (his update reaching the
    actor before this stick does, and after). A rollout that takes a hold
    scores by how soon -- unless the hold is burnt (``hold_is_burnt``: an axe
    still in the air meets the holder), which scores as the hit it is; a hit
    scores below everything else; the rest score by how far the actor ends
    from ``engage_aim``'s point, what that mode costs, and whether it ends in a
    live juggle's reach or a throw's lane.

    ``strikes`` is every timing the actor's B can have (``strike_specs``: the
    punch, or a weapon's several); a strike candidate scores by the worst of
    them. Without it, ``can_punch`` stands for the bare punch.
    """

    lane_lo, lane_hi = float(LANE_Y_MIN), float(LANE_Y_MAX_DEFAULT)
    x_lo, x_hi = (camera.left, camera.right) if camera is not None else (-1e9, 1e9)
    actor0 = ActorSim.from_token(actor, lane_lo=lane_lo, lane_hi=lane_hi, x_lo=x_lo, x_hi=x_hi)
    actor0.untouchable = False
    everyone = [jack] + [o for o in others if o.slot != jack.slot]
    world0 = build_world(actor, everyone, projectiles, camera=camera, level=level)
    index = 0

    moving_x = 1 if actor.vel_x > 0.5 else (-1 if actor.vel_x < -0.5 else 0)
    toward_x = 1 if world0.jacks[0].x > actor0.x else -1
    mode_now = engage_aim(actor0, world0, index)[0]
    # In his dodge the aim is a place to wait: no tie-break toward him, or the
    # first moves of every tick drift along with him to the screen's edge.
    dodging = world0.jacks[0].state == ST_EVADE
    if strikes is None:
        strikes = (punch_spec(actor.character_id),) if can_punch else ()
    specs: tuple[PunchSpec | None, ...] = tuple(strikes)
    best: EngagePlan | None = None

    def consider(first: tuple[int, int], hold: bool, punch_at: int | None) -> None:
        nonlocal best
        worst: tuple[float, Outcome, int | None] | None = None
        for spec in specs if punch_at is not None else (None,):
            for actor_first in (True, False):
                outcome, at, world, a = _rollout(
                    world0.copy(), actor0.copy(), index, first, hold,
                    actor_first=actor_first, punch=spec, punch_at=punch_at,
                )
                score = _score(outcome, at, world, a, index)
                if worst is None or score < worst[0]:
                    worst = (score, outcome, at)
                if outcome is Outcome.HIT:
                    break
            if worst is not None and worst[1] is Outcome.HIT:
                break
        assert worst is not None
        score, outcome, at = worst
        if punch_at is None:
            if moving_x and first[0] == -moving_x:
                score -= _REVERSE_X_COST
            if first[0] == toward_x and not dodging:
                score += _TOWARD_BONUS
            if first[1] == 0:
                score += _KEEP_LANE_BONUS
        if best is None or score > best.score:
            now = (0, 0) if punch_at == 0 else first
            best = EngagePlan(
                dir_x=now[0],
                dir_y=now[1],
                mode=mode_now,
                outcome=None if outcome is Outcome.NONE else outcome.name.lower(),
                at_update=at,
                score=score,
                punch=punch_at == 0,
            )

    for hold in (False, True):
        for first in _CANDIDATES:
            if hold and first == (0, 0):
                continue
            consider(first, hold, None)
    if specs and _punch_worth_trying(world0, index, actor0):
        for punch_at in PUNCH_WAITS:
            consider((0, 0), True, punch_at)
            if punch_at:
                # Walking toward him first is how the actor turns to him.
                consider((toward_x, 0), True, punch_at)
    assert best is not None
    return best


AXE_OUT_LANE = 18  # +-8 box, +-8 body, and a step
AXE_OUT_AHEAD = 160  # a released throw this far off is ~16 updates out
JUGGLE_NEAR_X = 40


def axe_threatens(actor: PlayableCharacter, jack: Jack, projectiles: Sequence[Projectile]) -> bool:
    """An axe of his is out at the actor: a throw released toward it, one about
    to be released along its lane, or a juggled one within a few steps of it.
    What ``priority`` ranks ``EngageJack`` up on -- the plan is the only thing
    that knows where they fly."""

    facing = -1 if jack.facing_left else 1
    for axe in projectiles:
        if axe.type_id != AXE_TYPE or axe.owner_slot != jack.slot:
            continue
        dy = actor.world_y - axe.world_y
        if axe.state == AXE_THROWN:
            if axe.flags_31 & 0x02:
                ahead = (actor.world_x - axe.world_x) * (1 if axe.vel_x >= 0 else -1)
                if -16 <= ahead <= AXE_OUT_AHEAD and abs(dy) <= AXE_OUT_LANE:
                    return True
            elif (actor.world_x - jack.world_x) * facing > 0 and abs(dy) <= AXE_OUT_LANE:
                return True
        elif axe.state == AXE_JUGGLED:
            if abs(actor.world_x - axe.world_x) <= JUGGLE_NEAR_X and abs(dy) <= AXE_OUT_LANE:
                return True
    return False


# --- The hold ------------------------------------------------------------------------------


def held_axes_threaten(
    actor: PlayableCharacter, jack: Jack, projectiles: Sequence[Projectile], *, updates: int = POST_GRAB_UPDATES
) -> bool:
    """With him held where he is, does an axe of his still in the air meet the actor?"""

    world = build_world(actor, [jack], projectiles)
    if not any(
        x.state in (AXE_JUGGLED, AXE_SPAWNER, AXE_INIT, AXE_THROWN)
        or (x.state == AXE_DROPPED and not x.harmless)
        for x in world.axes
    ):
        return False
    j = world.jacks[0]
    j.state = ST_HELD
    j.anim = 0x10
    a = ActorSim.from_token(
        actor, lane_lo=float(LANE_Y_MIN), lane_hi=float(LANE_Y_MAX_DEFAULT), x_lo=-1e9, x_hi=1e9
    )
    a.walking = False
    a.holding = True
    a.untouchable = False
    for _ in range(updates):
        for x in world.axes:
            if axe_update(x, a, world) is Outcome.HIT:
                return True
        world.axes = [x for x in world.axes if not x.gone]
        if not world.axes:
            return False
    return False


def axes_in_flight(jack: Jack, projectiles: Sequence[Projectile]) -> bool:
    """A juggled axe of his is still up (or about to be spawned): it follows
    him, and drops only at the end of its arc."""

    return any(
        p.type_id == AXE_TYPE
        and p.owner_slot == jack.slot
        and p.state in (AXE_INIT, AXE_JUGGLED, AXE_SPAWNER)
        for p in projectiles
    )


# Where a finisher from the front hold lands him, traced live (round 5):
SUPLEX_FLIGHT = 136  # the crossover's suplex: 58 px the way the actor faced, then a 78 px slide
THROW_FLIGHT = 274  # the B+back throw: 270-278 px behind the actor, slide included


def _throw_lands_nearer(actor: PlayableCharacter, camera: CameraRange | None) -> bool:
    """Whether the B+back throw leaves him less far outside the actor's reach
    (the camera clamp) than the crossover's suplex would."""

    if camera is None:
        return False
    if actor.facing_left:
        ahead, behind = actor.world_x - camera.left, camera.right - actor.world_x
    else:
        ahead, behind = camera.right - actor.world_x, actor.world_x - camera.left
    return max(0.0, THROW_FLIGHT - behind) < max(0.0, SUPLEX_FLIGHT - ahead)


def hold_step(
    actor: PlayableCharacter,
    jack: Jack,
    projectiles: Sequence[Projectile] = (),
    *,
    camera: CameraRange | None = None,
) -> HoldStep:
    """Spend the hold without ever standing in an axe's way.

    While a juggled axe of his is still up: in a back hold, wait -- they point
    away from a holder behind him and drop at the end of their arcs, and a
    held ordinary enemy never breaks free; a crossover or a suplex would carry
    the actor, or him, through them. In a front hold, cross over to his back
    if one would meet the actor where it stands (let go when the crossover is
    spent); a knee keeps both bodies where they are, so it waits for nothing.

    Once they are gone: knee, knee, cross over, suplex -- 2 + 2 + 5, which
    leaves a round-2 Jack (9) alive at 0; with the punch before it, one hold
    kills. From a back hold, the suplex when it
    kills, else the crossover to the front and its knees. The third knee (3,
    and it knocks him away) only when it kills or nothing else is left.

    The third knee and the crossover's suplex both land him the way the actor
    faced in the front hold (the suplex ``SUPLEX_FLIGHT`` px on), the B+back
    throw (4) ``THROW_FLIGHT`` px behind it. Near a camera bound, whichever
    leaves him less far out of the actor's reach: traced live in round 5, at
    the camera's right bound, knee, knee, cross over, suplex threw a Jack 58 px
    past it, his slide took him to 136, and his jumps kept him out of reach
    for 30 s; the throw from there landed him 278 px back, on screen.

    "Kills" is strict: an ordinary enemy dies only on a *negative* health
    word (``$A13A``'s ``bmi``), so 5 from a Jack at 5 leaves him alive at 0.
    """

    hp = signed_health(jack)
    base = actor.action_base
    flying = axes_in_flight(jack, projectiles)
    if base == 0x66:
        if flying:
            return HoldStep.WAIT
        if hp < HOLD_SUPLEX_DAMAGE or actor.crossover_spent:
            return HoldStep.SUPLEX
        return HoldStep.CROSS
    if base == 0x60:
        if flying and held_axes_threaten(actor, jack, projectiles):
            return HoldStep.RELEASE if actor.crossover_spent else HoldStep.CROSS
        if actor.knees_in_chain < 2 or hp < HOLD_KNEE_DAMAGE:
            return HoldStep.KNEE
        if hp < HOLD_THIRD_KNEE_DAMAGE:
            return HoldStep.KNEE
        if _throw_lands_nearer(actor, camera):
            return HoldStep.THROW
        return HoldStep.KNEE if actor.crossover_spent else HoldStep.CROSS
    return HoldStep.WAIT
