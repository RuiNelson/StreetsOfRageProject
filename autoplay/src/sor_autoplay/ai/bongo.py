"""Bongo (type ``$57``, round 4): the ROM model, and the plan built on it.

Everything the AI does against him is decided here, as pure functions of the
tokens already in the context, so the decision (``decide``), the ranking
(``priority``) and the controller (``execute``) cannot disagree about it --
the arrangement ``antonio.py`` and ``souther.py`` already have.

**The plan, in one line: take one hold, and never give him back a turn.**
Once held, the loop is Antonio's and Souther's (``hold_step``): knee, knee,
release, walk straight back in. What is his alone is how the first hold is
reached, because he never stands still near the actor unless something has
just put him there.

The facts it rests on, all read from the disassembly (``$174E0`` onwards; see
``ai-analysis/enemy-ai.md``, "Bongo"):

Everything runs at 30 Hz
    ``$AD8E`` updates both players, waits a VBlank, then every object: one
    *update* is two game frames, and every speed below is per update.
He never touches anyone himself
    none of his own animations (set ``$2EF62``) carries an attack box in the
    states he fights in, and ``$174E0`` clears his ``+$34`` every update. His
    one weapon is the **flame**, type ``$97`` (``$1781E``), a separate object
    born the update his charge launches, riding 20 px ahead of him (``$178D0``:
    his X +-``$14``, his lane +4, his height -``$33``/``$34``) and carrying his
    ``+$4A`` as its damage -- ``$20`` (32) on Normal, so three kill.
The flame's box
    grows through its ignition (anim ``$38``: ``$9D``, ``$9F``, ``$A1``, four
    updates each) to ``$A3`` for good: **x +4..+76 ahead of him, lane -6..+28
    of his**. Against a player body (lane +-8) that is every lane from 14
    above him to 36 below: small above, huge below. It has no body box, so
    nothing a player does can touch it.
State 1 (``$175BA``): the approach
    faces the target first -- a target behind him costs a 10-update turn
    (anim ``$30``) standing still -- then walks at it 0.5 px an update and
    keeps the lane gap in ``[$50, $60)``, stepping away 0.5 px when closer
    (a level target counts as below: he steps *up*) and in when further. The
    moment the X gap is under ``$B0`` (176) he winds up.
State 2 (``$17682``): wind-up and charge
    the wind-up is tacticals 0-2 (anims ``$24``, ``$28``, ``$2C``; 5, 5 and 10
    updates on ``+$68``), still drifting at state 1's last velocities. Its
    last update launches the charge: the flame, 2 px an update on his facing,
    and a lane velocity ``+$52 / (+$50 / 2)`` toward the target's lane --
    so he would arrive level with it as he reaches it -- capped at 6.
    Tactical 3 then adds 0.125 to both speeds every update (to 6), the lane
    only while ``+$52 >= 8``, and **never re-aims**: the lane velocity keeps
    the sign it launched with. With the target behind him and ``+$50 >=
    $50``, tactical 4 runs on for 20 more updates or until his screen X
    leaves ``[$50, $1F0)``, then state 1 again, facing away: a turn.
Grab beats hit (``$AAA0``) -- but not the flame on a holder
    his update tests the actor's walking box against his body first (a grab,
    code 3), and the flame -- in a later slot -- only afterwards; with the
    grab's code latched in the actor's ``+$7C``, ``$AA34`` tests the flame
    against nothing that update. From the next one it does, and a holder is
    not spared: the flame has no body box, so ``$AAA0`` never enters the grab
    path that shields a holder from Antonio's kick. An igniting flame stays
    placed on him through a hold, and a front hold stands him 32 px out
    facing the holder: a front grab inside the first 12 updates after a
    launch is the flame's hit (``_grab_is_burnt``).

Out of all of that, two geometries are safe from the flame and still reach
his body: **15-16 lanes above him** (the flame's top edge is 14 above, the
grab's lane is 16), and **behind him** once his origin has run past the
actor by 8 px (the flame starts 4 px ahead of him). The planner does not
hard-code either; it plays his AI forward and keeps what it finds.

The plan (``plan_engage``): the nine sticks, each held for 2, 8, 16 updates
or the whole horizon and then handed to a tail policy that follows the
fight's phases (``engage_mode``) -- walk in while contact comes before his
launch (the entrance, every release), stalk a few lanes above him while he
walks in, sit level on the bottom clamp (or below him) through a wind-up, and
through a charge hold the dodge lane read off his predicted path, above him
first. The hold loop that follows is ``souther.hold_step``'s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Sequence

from .antonio import (
    PLAYER_LANE_MAX,
    PLAYER_LANE_MIN,
    ActorSim,
    Outcome,
    actor_update,
)
from .souther import HoldStep, hold_step as _shared_hold_step, release_press_frames
from .tokens import Bongo, Boss, CameraRange, PlayableCharacter, Projectile

__all__ = [
    "BongoSim",
    "EngageMode",
    "EngagePlan",
    "FlameSim",
    "HoldStep",
    "Outcome",
    "boss_update",
    "hold_step",
    "plan_engage",
    "release_press_frames",
    "signed_health",
    "simulate",
]

BONGO_TYPE = 0x57
FLAME_TYPE = 0x97

# --- His states ------------------------------------------------------------------

PRIMARY_INIT = 0x00
PRIMARY_ACTIVE = 0x01  # $175BA: face, approach, keep the lane gap
PRIMARY_CHARGE = 0x02  # $17682: wind-up (tacticals 0-2), charge (3-4)
PRIMARY_HIT = 0x03
PRIMARY_HELD = 0x04
PRIMARY_POLICE = 0x0A

TAC_WINDUP_0 = 0
TAC_WINDUP_1 = 1
TAC_WINDUP_2 = 2
TAC_CHARGE = 3
TAC_RUNOUT = 4

# --- State 1 -------------------------------------------------------------------

APPROACH_SPEED = 0.5  # +$1C = $8000 (pair role 2: $10000)
APPROACH_SPEED_PAIR_TWO = 1.0
LANE_STEP = 0.5
LANE_AWAY_BELOW = 0x50  # +$52 < $50: step away
LANE_TOWARD_FROM = 0x60  # +$52 >= $60: step in
WINDUP_DX = 0xB0  # +$50 < $B0 starts the wind-up
TURN_UPDATES = 0x0A

# --- State 2 -------------------------------------------------------------------

WINDUP_UPDATES = (5, 5, 10)  # +$68 per wind-up tactical
CHARGE_SPEED = 2.0
CHARGE_ACCEL = 0.125  # $2000 an update, both axes
CHARGE_MAX_SPEED = 6.0
CHARGE_LANE_ACCEL_D52 = 8  # the lane speeds up only while +$52 >= 8
PASS_DX = 0x50  # target behind him and +$50 >= $50: tactical 4
RUNOUT_UPDATES = 0x14

# Both his screen checks read +$28, his biased screen X ($80 = the left edge)
# as the renderer left it: state 1/2's edge nudge ($17744) keeps him inside
# [$50, $1F0), and tactical 4 ends the charge outside it.
SCREEN_BIAS = 0x80
SCREEN_MIN = 0x50
SCREEN_MAX = 0x1F0

BOSS_LANE_MIN = 0x00  # $17AB8
BOSS_LANE_MAX = 0x70

# --- His animations (set $2EF62) and boxes ($1A68E) -------------------------------
#
# ``+$08`` is a byte offset into the set's word table, bit 1 selecting the
# left-facing member. Every entry below is decoded from the ROM: (per-frame
# updates, [(attack id, body id) per frame]).

ANIM_MIRROR_BIT = 0x02
ANIM_IDLE = 0x00
ANIM_CHARGE = 0x04
ANIM_WINDUP = (0x24, 0x28, 0x2C)
ANIM_TURN = 0x30
ANIM_FLAME_IGNITE = 0x38
ANIM_FLAME = 0x3C

_ANIMATIONS: dict[int, tuple[int, list[tuple[int, int]]]] = {
    0x00: (10, [(0, 0x95)] * 4),
    0x02: (10, [(0, 0x94)] * 4),
    0x04: (6, [(0, 0x95)] * 4),
    0x06: (6, [(0, 0x94)] * 4),
    0x08: (0, [(0, 0x9B)]),  # hit reaction
    0x0A: (0, [(0, 0x9A)]),
    0x0C: (0, [(0, 0x99)]),  # held, front
    0x0E: (0, [(0, 0x98)]),
    0x10: (0, [(0, 0x9B)]),  # held, back
    0x12: (0, [(0, 0x9A)]),
    0x24: (10, [(0, 0x95)] * 4),
    0x26: (10, [(0, 0x94)] * 4),
    0x28: (10, [(0, 0x95)] * 4),
    0x2A: (10, [(0, 0x94)] * 4),
    0x2C: (10, [(0, 0x95)] * 4),
    0x2E: (10, [(0, 0x94)] * 4),
    0x30: (0, [(0, 0x97)]),
    0x32: (0, [(0, 0x96)]),
    # The flame's own (type $97, same set).
    0x38: (4, [(0x9D, 0), (0x9F, 0), (0xA1, 0)]),
    0x3A: (4, [(0x9C, 0), (0x9E, 0), (0xA0, 0)]),
    0x3C: (1, [(0xA3, 0)] * 4),
    0x3E: (1, [(0xA2, 0)] * 4),
}

# (x0, x1, lane0, lane1, z0, z1) about the object's origin, inclusive.
_SHAPES: dict[int, tuple[int, int, int, int, int, int]] = {
    0x94: (-14, 18, -8, 8, -64, 0),
    0x95: (-18, 14, -8, 8, -64, 0),
    0x96: (-16, 16, -8, 8, -64, 0),
    0x97: (-16, 16, -8, 8, -64, 0),
    0x98: (-24, 6, -8, 8, -54, 0),
    0x99: (-6, 24, -8, 8, -54, 0),
    0x9A: (-8, 16, -8, 8, -58, 0),
    0x9B: (-16, 8, -8, 8, -58, 0),
    0x9C: (-12, 20, -10, 24, -20, 2),
    0x9D: (-16, 16, -10, 24, -20, 2),
    0x9E: (-24, 16, -10, 24, -22, 6),
    0x9F: (-16, 24, -10, 24, -22, 6),
    0xA0: (-34, 16, -10, 24, -22, 16),
    0xA1: (-16, 34, -10, 24, -22, 16),
    0xA2: (-56, 16, -10, 24, -26, 20),
    0xA3: (-16, 56, -10, 24, -26, 20),
}

# --- The flame (type $97: $1781E creates it, $17858 runs it) --------------------

FLAME_DX = 0x14  # $178D0: 20 px ahead of him on his facing ...
FLAME_DLANE = 4  # ... his lane + 4 ...
FLAME_DZ_FRAME0 = 0x33  # ... and this far above him on his frame 0 (or $15),
FLAME_DZ = 0x34  # this far otherwise
FLAME_IGNITING = 0  # +$30: anim $38, positioned on him whatever he is doing
FLAME_BURNING = 1  # anim $3C; gone the first update he is out of primary 2
# $17858: the ignition hands over to anim $3C when its own +$0D reads 1 on
# frame 2 -- the last update of the ignition's last frame.
FLAME_IGNITION_LAST_FRAME = 2

# --- The actor ---------------------------------------------------------------------

# Standing body box height per character (Axel, Adam, Blaze): the flame's
# ignition box ($9D, up to 49 px above the floor) clears Blaze's head and
# not the other two.
BODY_TOP_Z: dict[int, int] = {0: -51, 1: -53, 2: -48}
DEFAULT_BODY_TOP_Z = -53
CONTACT_LANE = 16  # a player box is lane +-8, his are too; inclusive

# --- The hold ----------------------------------------------------------------------

PENDING_CONTACT_BIT = 0x01  # +$66 bit 0, as Antonio's


def signed_health(boss: Boss) -> int:
    health = boss.health or 0
    return health - 0x10000 if health >= 0x8000 else health


def _hi(value: float) -> int:
    """The high word of a 16.16 value, as the ROM's ``move.w`` reads it."""

    return math.floor(value)


# --- The simulation ------------------------------------------------------------------


class FlameSim:
    """His flame, reduced to what its own update (``$17858``) reads."""

    __slots__ = ("state", "x", "y", "z", "anim", "frame", "countdown", "reload", "shown", "screen_x", "slot")

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])

    def copy(self) -> FlameSim:
        return FlameSim(**{name: getattr(self, name) for name in self.__slots__})

    @classmethod
    def from_token(cls, flame: Projectile, *, parent_z: int = 0) -> FlameSim:
        """Its height is carried relative to his (``parent_z``), the way
        ``$178D0`` places it: only the first update's test uses it before
        it is placed on him again."""

        duration = _ANIMATIONS.get(flame.anim, (1, []))[0]
        return cls(
            state=flame.state,
            x=float(flame.world_x),
            y=float(flame.world_y),
            z=parent_z - FLAME_DZ,
            anim=flame.anim,
            frame=flame.anim_frame,
            countdown=flame.anim_countdown,
            reload=duration,
            shown=flame.attack_box_id,
            screen_x=flame.screen_x,
            slot=flame.slot,
        )

    @property
    def facing_left(self) -> bool:
        return bool(self.anim & ANIM_MIRROR_BIT)


class BongoSim:
    """His object, reduced to what his state-1/state-2 code reads and writes."""

    __slots__ = (
        "x", "y", "z", "primary", "tactical", "t68", "t79", "vx", "vy",
        "anim", "frame", "countdown", "reload", "shown_attack", "shown_body",
        "screen_x", "cam_x", "pair_role", "inert", "pending_hold", "flame",
        "flame_known",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])

    def copy(self) -> BongoSim:
        fields = {name: getattr(self, name) for name in self.__slots__}
        if self.flame is not None:
            fields["flame"] = self.flame.copy()
        return BongoSim(**fields)

    @property
    def facing_left(self) -> bool:
        return bool(self.anim & ANIM_MIRROR_BIT)

    @classmethod
    def from_token(
        cls,
        bongo: Bongo,
        *,
        cam_x: int,
        flame: Projectile | None = None,
        flame_known: bool = False,
    ) -> BongoSim:
        """``flame`` is his linked ``$97``. ``flame_known``: the caller
        looked for it, so none means none -- without it no flame is carried
        over (a charge launched inside the rollout still makes one)."""

        x = bongo.fine_x if bongo.fine_x else float(bongo.world_x)
        y = bongo.fine_y if bongo.fine_y else float(bongo.world_y)
        primary = bongo.primary_state
        inert = 0
        if primary not in (PRIMARY_ACTIVE, PRIMARY_CHARGE):
            if primary in (PRIMARY_HELD, PRIMARY_POLICE):
                inert = 1 << 16
            elif primary == PRIMARY_INIT:
                inert = 1
            else:
                # Hit reaction, lethal gate, thrown, knocked down: +$62 is
                # the reaction timer those states count. Two updates early,
                # so a boss who gets up sooner than it says is still seen.
                inert = max(1, bongo.reaction_timer - 2)
        screen_x = bongo.screen_x if bongo.screen_x else _hi(x) - cam_x + SCREEN_BIAS
        anim = bongo.anim
        return cls(
            x=x,
            y=y,
            # Heights are carried relative to his floor: the flame's is his
            # less $33/$34, and the actor stands on the same floor.
            z=0,
            primary=primary,
            tactical=bongo.tactical,
            t68=bongo.timer_68,
            t79=bongo.timer_79,
            vx=bongo.boss_vel_x,
            vy=bongo.boss_vel_lane,
            anim=anim,
            frame=bongo.anim_frame,
            countdown=bongo.anim_countdown,
            reload=_ANIMATIONS.get(anim, (10, []))[0],
            shown_attack=bongo.attack_box_id,
            shown_body=bongo.body_box_id,
            screen_x=screen_x,
            cam_x=cam_x,
            pair_role=bongo.pair_role,
            inert=inert,
            pending_hold=bool(bongo.hold_flags & PENDING_CONTACT_BIT),
            flame=FlameSim.from_token(flame) if flame is not None else None,
            flame_known=flame_known,
        )


def _frame_ids(anim: int, frame: int) -> tuple[int, int]:
    _, frames = _ANIMATIONS.get(anim, (0, [(0, 0)]))
    if not frames:
        return 0, 0
    return frames[frame] if 0 <= frame < len(frames) else frames[0]


def _set_anim_reset(o, anim: int) -> None:
    """``$B1A2`` (``init_object_animation_frame``): frame 0, timer reseeded,
    boxes from frame 0."""

    o_duration = _ANIMATIONS.get(anim, (0, []))[0]
    o.anim = anim
    o.frame = 0
    o.countdown = o_duration
    o.reload = o_duration
    ids = _frame_ids(anim, 0)
    if isinstance(o, BongoSim):
        o.shown_attack, o.shown_body = ids
    else:
        o.shown = ids[0]


def _set_anim_keep(b: BongoSim, anim: int) -> None:
    """``$17A34``: a new animation that keeps the frame index and the running
    countdown -- only the reload and frame 0's boxes change."""

    b.anim = anim
    b.reload = _ANIMATIONS.get(anim, (0, []))[0]
    b.shown_attack, b.shown_body = _frame_ids(anim, 0)


def _step_frame(o) -> None:
    """The tail of ``$AF46``: ``+$0D`` down, and on reaching zero the reload
    and the next frame (wrapping)."""

    o.countdown = (o.countdown - 1) & 0xFF
    if o.countdown:
        return
    o.countdown = o.reload
    o.frame += 1
    count = len(_ANIMATIONS.get(o.anim, (0, [(0, 0)]))[1])
    if o.frame >= count:
        o.frame = 0


def _emit(b: BongoSim) -> None:
    """The renderer's pass for him: ``+$28``, the boxes of the frame about to
    show, then the frame timer. (Bit 3 of his ``+$01`` skips the culling, so
    it runs off screen as well.)"""

    b.screen_x = _hi(b.x) - b.cam_x + SCREEN_BIAS
    b.shown_attack, b.shown_body = _frame_ids(b.anim, b.frame)
    _step_frame(b)


def _emit_flame(f: FlameSim, cam_x: int) -> None:
    f.screen_x = _hi(f.x) - cam_x + SCREEN_BIAS
    f.shown = _frame_ids(f.anim, f.frame)[0]
    _step_frame(f)


def _integrate(b: BongoSim) -> None:
    """``$17AB8``: X free, the lane clamped to ``$00..$70``."""

    b.x += b.vx
    y = b.y + b.vy
    b.y = float(BOSS_LANE_MIN) if y < BOSS_LANE_MIN else (float(BOSS_LANE_MAX) if y >= BOSS_LANE_MAX else y)


def _edge_nudge_and_integrate(b: BongoSim) -> None:
    """``$17744``: back inside ``[$50, $1F0)`` of the screen, then integrate."""

    d1 = b.screen_x
    if d1 < SCREEN_MIN:
        b.x -= d1 - SCREEN_MIN
    elif d1 - SCREEN_MAX >= 0:
        b.x -= d1 - SCREEN_MAX
    _integrate(b)


def _not_high_word(value: float) -> float:
    """``not.w`` on a 16.16 long's high word, as ``$17608`` does to +$1C."""

    raw = int(round(value * 65536)) & 0xFFFFFFFF
    raw ^= 0xFFFF0000
    if raw & 0x80000000:
        raw -= 1 << 32
    return raw / 65536


def _launch_lane_speed(d50: int, d52: int) -> float:
    """``$17712``: ``+$52 / (+$50 / 2)`` in 8.8, capped at 6."""

    d0 = (d50 >> 1) or 1
    quotient = ((d52 << 8) // d0) & 0xFFFF
    speed = quotient / 256
    return min(speed, CHARGE_MAX_SPEED)


def _speed_up(v: float) -> float:
    """``$17778``: magnitude + 0.125, capped at 6, sign kept (a zero counts
    as positive: the ROM tests the high word)."""

    magnitude = min(abs(v) + CHARGE_ACCEL, CHARGE_MAX_SPEED)
    return -magnitude if v < 0 else magnitude


def _spawn_flame(b: BongoSim) -> None:
    """``$1781E``: a fresh ``$97`` on anim ``$38``, placed on him."""

    f = FlameSim(
        state=FLAME_IGNITING, x=0.0, y=0.0, z=0, anim=ANIM_FLAME_IGNITE, frame=0,
        countdown=0, reload=0, shown=0, screen_x=0, slot=None,
    )
    _set_anim_reset(f, ANIM_FLAME_IGNITE)
    _place_flame(f, b)
    b.flame = f


def _place_flame(f: FlameSim, b: BongoSim) -> None:
    """``$178D0``: 20 px ahead of him, his lane + 4, above his head."""

    left = b.facing_left
    f.anim = (f.anim & ~ANIM_MIRROR_BIT) | (ANIM_MIRROR_BIT if left else 0)
    f.x = float(_hi(b.x) + (-FLAME_DX if left else FLAME_DX))
    f.y = float(_hi(b.y) + FLAME_DLANE)
    f.z = b.z - (FLAME_DZ_FRAME0 if b.frame in (0, 0x15) else FLAME_DZ)


def _measure(b: BongoSim, t: ActorSim) -> tuple[bool, bool, int, int]:
    """``$17AF6``: (target left of him, target above him, +$50, +$52)."""

    dx = _hi(t.x) - _hi(b.x)
    dy = _hi(t.y) - _hi(b.y)
    return dx < 0, dy < 0, abs(dx), abs(dy)


def _active_step(b: BongoSim, t: ActorSim) -> None:
    """One update of state 1 after the contact test (``$175BA``)."""

    left, above, d50, d52 = _measure(b, t)
    if b.tactical:
        # $17672: the turn, standing still until +$68 runs out, then the
        # idle animation facing the target.
        b.t68 = (b.t68 - 1) & 0xFF
        if b.t68:
            return
        b.tactical = 0
        _set_anim_reset(b, ANIM_IDLE | (ANIM_MIRROR_BIT if left else 0))
        return
    speed = APPROACH_SPEED_PAIR_TWO if b.pair_role == 2 else APPROACH_SPEED
    if b.facing_left != left:
        # $1765E: the target is behind him -- stop and turn.
        b.vx = b.vy = 0.0
        b.tactical = 1
        b.t68 = TURN_UPDATES
        _set_anim_reset(b, ANIM_TURN | (ANIM_MIRROR_BIT if left else 0))
        return
    b.vx = _not_high_word(speed) if b.facing_left else speed
    if d52 < LANE_AWAY_BELOW:
        vy = -LANE_STEP
    elif d52 >= LANE_TOWARD_FROM:
        vy = LANE_STEP
    else:
        vy = 0.0
    b.vy = -vy if above else vy
    if d50 >= WINDUP_DX:
        _edge_nudge_and_integrate(b)
        return
    # $1764E: the wind-up, from this update on, without moving on this one.
    b.t68 = WINDUP_UPDATES[0]
    b.primary = PRIMARY_CHARGE
    b.tactical = TAC_WINDUP_0
    _set_anim_keep(b, ANIM_WINDUP[0] | (ANIM_MIRROR_BIT if left else 0))


def _charge_step(b: BongoSim, t: ActorSim) -> None:
    """One update of state 2 after the contact test (``$17682``)."""

    left, above, d50, d52 = _measure(b, t)
    tac = b.tactical
    mirror = ANIM_MIRROR_BIT if b.facing_left else 0
    if tac in (TAC_WINDUP_0, TAC_WINDUP_1, TAC_WINDUP_2):
        b.t68 = (b.t68 - 1) & 0xFF
        if b.t68:
            _edge_nudge_and_integrate(b)
            return
        if tac < TAC_WINDUP_2:
            b.tactical = tac + 1
            b.t68 = WINDUP_UPDATES[tac + 1]
            _set_anim_keep(b, ANIM_WINDUP[tac + 1] | mirror)
            return
        # $176E6: the launch -- the flame, and velocities that would bring
        # him level with the target as he reaches it.
        _spawn_flame(b)
        b.vx = -CHARGE_SPEED if b.facing_left else CHARGE_SPEED
        vy = _launch_lane_speed(d50, d52)
        b.vy = -vy if above else vy
        b.tactical = TAC_CHARGE
        _set_anim_keep(b, ANIM_CHARGE | mirror)
        return
    if tac == TAC_CHARGE:
        behind = b.facing_left != left
        if behind and d50 >= PASS_DX:
            b.tactical = TAC_RUNOUT
            b.t79 = RUNOUT_UPDATES
        b.vx = _speed_up(b.vx)
        if d52 >= CHARGE_LANE_ACCEL_D52:
            b.vy = _speed_up(b.vy)
        _integrate(b)
        return
    if tac == TAC_RUNOUT:
        b.t79 = (b.t79 - 1) & 0xFF
        sx = b.screen_x
        if not b.t79 or sx < 0 or sx < SCREEN_MIN or sx >= SCREEN_MAX:
            # $177FE: back to state 1, facing the way he ran.
            b.tactical = 0
            b.primary = PRIMARY_ACTIVE
            _set_anim_keep(b, ANIM_IDLE | mirror)
            return
        _integrate(b)
        return
    _integrate(b)


def _box(shape: int, x: int, y: int, z: int) -> tuple[int, int, int, int, int, int] | None:
    ext = _SHAPES.get(shape)
    if ext is None:
        return None
    return x + ext[0], x + ext[1], y + ext[2], y + ext[3], z + ext[4], z + ext[5]


def grab_contact(b: BongoSim, a: ActorSim) -> bool:
    """``$AAA0`` in his update: the actor's walking box on his body box.

    Both lanes +-8 and every compare inclusive; ``$AAA0`` refuses a grab to
    an actor already holding, and ``$AA34`` tests nothing on one in a hit
    reaction or with a contact code still latched.
    """

    if not a.walking or a.holding or a.untouchable:
        return False
    body = _box(b.shown_body, _hi(b.x), _hi(b.y), b.z)
    if body is None:
        return False
    ax, ay = _hi(a.box_x), _hi(a.box_y)
    lo, hi = (ax - a.walk_reach, ax) if a.facing_left else (ax, ax + a.walk_reach)
    return lo <= body[1] and hi >= body[0] and ay - 8 <= body[3] and ay + 8 >= body[2]


def flame_contact(
    f: FlameSim, a: ActorSim, *, body_top: int, actor_z: int, margin: bool = True
) -> bool:
    """``$AAA0`` in the flame's update: its latched box on the actor's body.

    The body is taken at its widest (``ActorSim.body_reach`` either side) and
    lane +-8; ``margin`` grows the flame by 2 px and a lane, as Antonio's
    simulated kick is grown. **A holding actor is not spared**: ``$AAA0``'s
    grab path -- the thing that shields a holder from Antonio's kick -- is
    only entered for an object with a body box, and the flame has none
    (``move.b $3(a0),d1; beq``), so it goes straight to its attack box on the
    actor's body. Measured live: three hits in the first scored fight, all of
    them with Bongo held.
    """

    if a.untouchable:
        return False
    box = _box(f.shown, _hi(f.x), _hi(f.y), f.z)
    if box is None:
        return False
    grow_x = 2 if margin else 0
    grow_y = 1 if margin else 0
    ax, ay = _hi(a.box_x), _hi(a.box_y)
    return (
        box[0] - grow_x <= ax + a.body_reach
        and box[1] + grow_x >= ax - a.body_reach
        and box[2] - grow_y <= ay + 8
        and box[3] + grow_y >= ay - 8
        and box[4] <= actor_z
        and box[5] >= actor_z + body_top
    )


def _flame_update(b: BongoSim, a: ActorSim | None, *, body_top: int, actor_z: int, margin: bool) -> bool:
    """``$17858``: the contact test, then the ignition's hand-over or the
    burning flame's check on him, then its place on him. True on a hit."""

    f = b.flame
    assert f is not None
    hit = a is not None and flame_contact(f, a, body_top=body_top, actor_z=actor_z, margin=margin)
    if f.state == FLAME_IGNITING:
        if f.countdown == 1 and f.frame == FLAME_IGNITION_LAST_FRAME:
            _set_anim_reset(f, ANIM_FLAME | (f.anim & ANIM_MIRROR_BIT))
            f.state = FLAME_BURNING
        _place_flame(f, b)
    elif b.primary != PRIMARY_CHARGE:
        b.flame = None
        return hit
    else:
        _place_flame(f, b)
    return hit


# How many passes after a grab the flame is followed for: its ignition is 12
# updates long, and one more retires it.
POST_GRAB_UPDATES = 14
# $17D76 / $17DB0 for $57: a held Bongo stands this far out on the holder's
# facing, facing it in a front hold and away from it in a back hold.
HOLD_DX = 32


def _grab_is_burnt(b: BongoSim, a: ActorSim, *, body_top: int, actor_z: int) -> bool:
    """Would the flame land on the actor in the hold this grab starts?

    The grab's own pass: his update still runs to its end (``$17B52`` only
    sets the pending contact), the flame's test is skipped (the grab's code
    is in the actor's ``+$7C``), and it is placed on him. From the next pass
    he is held -- ``$17DFA``/``$17E22`` put him ``HOLD_DX`` out on the
    holder's facing, facing it (front) or away from it (back) -- and the
    flame tests the holder first thing in each of its updates: a burning one
    once more where it was, then it is gone; an igniting one every update of
    the ignition left, placed on him each time -- so in a front hold it sits
    on the holder.
    """

    if b.flame is None:
        return False
    sim = b.copy()
    if sim.primary == PRIMARY_ACTIVE:
        _active_step(sim, a)
    else:
        _charge_step(sim, a)
    if sim.flame is None:
        return False
    _flame_update(sim, None, body_top=body_top, actor_z=actor_z, margin=False)
    if sim.flame is None:
        return False
    _emit(sim)
    _emit_flame(sim.flame, sim.cam_x)
    holder = a.copy()
    holder.holding = True
    holder.walking = False
    facing = -1 if holder.facing_left else 1
    front = (sim.x > holder.x) == sim.facing_left
    sim.x = float(_hi(holder.x) + facing * HOLD_DX)
    sim.y = float(_hi(holder.y))
    held_left = holder.facing_left != front
    sim.anim = (0x0C if front else 0x10) | (ANIM_MIRROR_BIT if held_left else 0)
    sim.frame = 0
    sim.primary = PRIMARY_HELD
    for _ in range(POST_GRAB_UPDATES):
        if sim.flame is None:
            return False
        if _flame_update(sim, holder, body_top=body_top, actor_z=actor_z, margin=True):
            return True
        if sim.flame is not None:
            _emit_flame(sim.flame, sim.cam_x)
    return False


def boss_update(
    b: BongoSim,
    a: ActorSim,
    target: ActorSim | None = None,
    *,
    margin: bool = True,
    body_top: int = DEFAULT_BODY_TOP_Z,
    actor_z: int | None = None,
) -> Outcome:
    """One object pass: his update against the actor (and his target, if not
    the actor), then his flame's, then the renderer for both."""

    target = a if target is None else target
    az = b.z if actor_z is None else actor_z
    freed = False
    if b.primary in (PRIMARY_ACTIVE, PRIMARY_CHARGE):
        if b.pending_hold and a.holding:
            # $17CF2, first in both states: the grab $AAA0 handed the actor
            # on its last update becomes his held state now.
            b.pending_hold = False
            b.primary = PRIMARY_HELD
            b.inert = 1 << 16
        elif grab_contact(b, a):
            return Outcome.HIT if _grab_is_burnt(b, a, body_top=body_top, actor_z=az) else Outcome.GRAB
        elif b.primary == PRIMARY_ACTIVE:
            _active_step(b, target)
        else:
            _charge_step(b, target)
    else:
        # Hit reaction, held, thrown, knocked down: nothing collides and
        # nothing decides until the reaction runs out. The first free update
        # shows no body box yet, so a walk-in cannot be assumed.
        b.inert -= 1
        if b.inert <= 0:
            b.primary = PRIMARY_ACTIVE
            b.tactical = 0
            b.vx = b.vy = 0.0
            left = _hi(target.x) < _hi(b.x)
            _set_anim_reset(b, ANIM_IDLE | (ANIM_MIRROR_BIT if left else 0))
            freed = True
    outcome = Outcome.NONE
    if b.flame is not None:
        if _flame_update(b, a, body_top=body_top, actor_z=az, margin=margin):
            outcome = Outcome.HIT
    if freed:
        b.shown_attack, b.shown_body = 0, 0
        b.screen_x = _hi(b.x) - b.cam_x + SCREEN_BIAS
    else:
        _emit(b)
    if b.flame is not None:
        _emit_flame(b.flame, b.cam_x)
    return outcome


# --- The plan ---------------------------------------------------------------------

# How far ahead every candidate is played out, in updates (two frames each).
# Long enough to see a wind-up launch and the charge that follows reach the
# actor from his wind-up gate ($B0 out: ~40 updates), which is where every
# decision against him pays off or not.
HORIZON_UPDATES = 44
# How long a candidate holds its own stick before the tail policy takes over
# (None: the whole horizon). The short hold is the tail's own first move; the
# long ones are how a dodge that runs one way for a second is ever found --
# the tail alone turns back to its aim.
FIRST_UPDATES = 2
HOLD_UPDATES: tuple[int | None, ...] = (FIRST_UPDATES, 8, 16, None)
# The pocket: his lane less ours at the grab. The flame reaches 14 lanes
# above him against a body's +-8 and the grab 16, so hi(ours) must be 16 or
# 15 above his -- exactly, which is why the flame is simulated without a
# lane margin (a margin of one would leave only 16, which the 1.625 px lane
# step of Blaze's walk does not always land on).
POCKET_DY = (16, 15)
# Behind him: his origin this far past the actor's and the flame, 4 px ahead
# of him, has gone by; the actor's walking box still reaches his back up to
# walk reach + his body's back edge (18) behind.
BEHIND_CLEAR_DX = 9
# Before the wind-up: this far above him, so state 1 keeps stepping him
# *down* -- onto the bottom clamp, which is where his charge cannot leave.
STALK_DY = (1, 7)
# Where the actor stands off him on X while he walks in: past his $B0 gate,
# so the wind-up starts only once the actor has its lane.
STALK_DX = WINDUP_DX + 8
# With no room above him: this far below him at launch. He dives toward it
# and the actor climbs past his lane the other way (the flame's top edge is
# only 14 above him).
DIVE_DY = (0, 24, 40)
# He counts as on the bottom clamp from here down.
BOTTOM_LANE = BOSS_LANE_MAX - 4
# Grab contact is expected this many updates before his launch at the latest.
WALK_IN_SLACK = 3
# Scores. A hold ends the question; a hit is the one thing never chosen while
# anything else exists; the rest is progress toward the aim minus danger.
_SCORE_GRAB = 10_000
_SCORE_HIT = -10_000
_SCORE_PER_UPDATE = 10
_DANGER_FLAME = 400
_REVERSE_X_COST = 3
_TOWARD_BONUS = 0.5
_KEEP_LANE_BONUS = 0.2


class EngageMode(Enum):
    """What the tail policy is doing -- see ``engage_mode``."""

    WALK_IN = auto()
    """He cannot launch before the walking box reaches him: lane, then in."""

    POCKET = auto()
    """His charge is coming: 16 lanes above him, walking at him."""

    BEHIND = auto()
    """He has run past: after him, into his lane band, facing his back."""

    LEVEL = auto()
    """Wind-up with him on the bottom clamp: sit level on the clamp."""

    DIVE = auto()
    """Wind-up with no room above him: stand below him for the launch."""

    STALK = auto()
    """He walks in: a few lanes above him, beyond his wind-up gate."""

    WAIT = auto()
    """He is in a reaction: close in on his lane for when he gets up."""


@dataclass(frozen=True, slots=True)
class EngagePlan:
    """The stick this tick, and why."""

    dir_x: int  # -1 left, 0, +1 right
    dir_y: int  # -1 up (smaller lane), 0, +1 down
    mode: EngageMode
    outcome: str | None  # "grab" / "hit" / None within the horizon
    at_update: int | None
    score: float


def updates_to_launch(b: BongoSim, d50: int | None = None) -> int | None:
    """Updates until his charge launches, if nothing interrupts him: the
    wind-up left, the turn before it, or -- walking in -- the whole wind-up
    once inside his gate. None when no launch is on its way."""

    windup = sum(WINDUP_UPDATES)
    if b.primary == PRIMARY_CHARGE and b.tactical <= TAC_WINDUP_2:
        return b.t68 + sum(WINDUP_UPDATES[b.tactical + 1 :])
    if b.primary == PRIMARY_ACTIVE and b.tactical:
        return b.t68 + 1 + windup
    if b.primary == PRIMARY_ACTIVE and (d50 is None or d50 < WINDUP_DX):
        return 1 + windup
    return None


def _charging(b: BongoSim) -> bool:
    return b.primary == PRIMARY_CHARGE and b.tactical >= TAC_CHARGE


def _toward(a: ActorSim, b: BongoSim) -> int:
    dx = b.x - a.x
    if abs(dx) < 4:
        return -1 if a.facing_left else 1
    return 1 if dx > 0 else -1


def _contact_updates(a: ActorSim, b: BongoSim) -> float:
    """A rough count of updates for the walking box to reach his body --
    the lane first (straight), then X."""

    straight_x, _, _, straight_y = a.speeds
    dy = abs(_hi(a.y) - _hi(b.y))
    body = _SHAPES.get(0x94 if b.facing_left else 0x95, (-16, 16))
    near = -body[0] if a.x < b.x else body[1]
    gap_x = max(0.0, abs(a.x - b.x) - a.walk_reach - near)
    return max(0.0, dy - (CONTACT_LANE - 4)) / max(straight_y, 0.1) + gap_x / max(straight_x, 0.1)


def engage_mode(a: ActorSim, b: BongoSim) -> EngageMode:
    """Which of the plan's phases the actor is in, given where both are."""

    if b.primary not in (PRIMARY_ACTIVE, PRIMARY_CHARGE):
        return EngageMode.WAIT
    d50 = abs(_hi(a.x) - _hi(b.x))
    if _charging(b):
        ahead = (a.x - b.x) * (-1 if b.facing_left else 1)
        return EngageMode.BEHIND if ahead <= -BEHIND_CLEAR_DX else EngageMode.POCKET
    launch = updates_to_launch(b, d50)
    if launch is not None and _contact_updates(a, b) + WALK_IN_SLACK <= launch:
        return EngageMode.WALK_IN
    if b.primary == PRIMARY_CHARGE:
        return EngageMode.LEVEL if _hi(b.y) >= BOTTOM_LANE else EngageMode.DIVE
    return EngageMode.STALK


def _lane_step(a: ActorSim, lo: float, hi: float) -> int:
    """The lane press that brings hi(lane) into ``[lo, hi]``."""

    y = _hi(a.y)
    if y > hi:
        return -1
    if y < lo:
        return 1
    return 0


def _predict_charge(b: BongoSim, updates: int) -> list[tuple[float, float]]:
    """His ``(x, lane)`` over the next updates of a charge already launched,
    the lane speeding up all the way -- which it does while the actor is 8+
    lanes off his, the only place a dodge ever stands."""

    x, y, vx, vy = b.x, b.y, b.vx, b.vy
    path = []
    for _ in range(updates):
        if b.tactical == TAC_CHARGE:
            vx = _speed_up(vx)
            vy = _speed_up(vy)
        x += vx
        y = y + vy
        y = float(BOSS_LANE_MIN) if y < BOSS_LANE_MIN else (float(BOSS_LANE_MAX) if y >= BOSS_LANE_MAX else y)
        path.append((x, y))
    return path


def _dodge_lane(a: ActorSim, b: BongoSim, path: Sequence[tuple[float, float]]) -> tuple[int, bool] | None:
    """The lane to hold while his flame crosses the actor's X, and whether it
    is the side above him (the pocket's side, where a grab is still possible).

    Over the updates his flame's X span covers the actor's body, above him
    means ``hi(his lane) - 16`` at his highest, below him ``+ 37`` at his
    lowest. The side reachable before the flame arrives wins, above first;
    with neither reachable, the nearer miss. None when the flame never
    crosses this X at all.
    """

    ax = a.x
    left = b.facing_left
    window: list[tuple[int, int]] = []
    for n, (x, y) in enumerate(path):
        f0, f1 = (x - 76 - 2, x - 4 + 2) if left else (x + 4 - 2, x + 76 + 2)
        if f0 <= ax + a.body_reach and f1 >= ax - a.body_reach:
            window.append((n, _hi(y)))
    if not window:
        return None
    first = window[0][0]
    above = min(y for _, y in window) - POCKET_DY[0]
    below = max(y for _, y in window) + 37
    lane = _hi(a.y)
    budget = a.speeds[3] * (first + 1) + 0.5
    above_ok = above >= a.lane_lo and lane - above <= budget
    below_ok = below <= a.lane_hi and below - lane <= budget
    if above_ok:
        return above, True
    if below_ok:
        return below, False
    miss_above = (lane - above - budget) if above >= a.lane_lo else 1e9
    miss_below = (below - lane - budget) if below <= a.lane_hi else 1e9
    if miss_above <= miss_below:
        return max(above, int(a.lane_lo)), True
    return min(below, int(a.lane_hi)), False


class _Tail:
    """The tail policy of one rollout: whatever ``engage_mode`` says, with
    the charge's dodge lane worked out once, from his path, when it launches."""

    __slots__ = ("dive", "dodge", "path")

    def __init__(self, dive: int, path: Sequence[tuple[float, float]] | None = None) -> None:
        self.dive = dive
        self.dodge: tuple[int, bool] | None = None
        self.path = path

    def move(self, a: ActorSim, b: BongoSim) -> tuple[int, int]:
        mode = engage_mode(a, b)
        by = _hi(b.y)
        toward = _toward(a, b)
        if mode is not EngageMode.POCKET:
            self.dodge = None
        if mode is EngageMode.WALK_IN or mode is EngageMode.WAIT:
            dy = by - _hi(a.y)
            dir_y = 0 if abs(dy) <= CONTACT_LANE - 6 else (1 if dy > 0 else -1)
            straight_x, _, _, straight_y = a.speeds
            lane_left = max(0.0, abs(dy) - (CONTACT_LANE - 6)) / max(straight_y, 0.1)
            body = _SHAPES.get(0x94 if b.facing_left else 0x95, (-16, 16))
            near = -body[0] if a.x < b.x else body[1]
            gap = abs(a.x - b.x) - a.walk_reach - near
            if mode is EngageMode.WAIT:
                gap -= 24  # stand off him until he is up
            dir_x = toward if gap > 0 and gap / max(straight_x, 0.1) >= lane_left else 0
            if mode is EngageMode.WALK_IN and abs(dy) <= CONTACT_LANE - 2:
                dir_x = toward
            return dir_x, dir_y
        if mode is EngageMode.POCKET:
            if self.dodge is None:
                path = self.path if self.path is not None else _predict_charge(b, HORIZON_UPDATES)
                self.path = None
                self.dodge = _dodge_lane(a, b, path) or (by - POCKET_DY[0], True)
            lane, above = self.dodge
            lo, hi = (lane, lane + 1) if above else (lane, lane + 3)
            dir_y = _lane_step(a, lo, hi)
            return (toward if dir_y == 0 else 0), dir_y
        if mode is EngageMode.BEHIND:
            away = -1 if b.facing_left else 1
            return away, _lane_step(a, by - (CONTACT_LANE - 4), by + (CONTACT_LANE - 4))
        if mode is EngageMode.LEVEL:
            return 0, 1
        if mode is EngageMode.DIVE:
            target = min(by + self.dive, a.lane_hi)
            return 0, _lane_step(a, target, target + 3)
        # STALK: above him by a few lanes, off his gate on X until the lane
        # is right, then let him walk in. His X is taken where the edge nudge
        # ($17744) will put him: inside [$50, $1F0) of the screen.
        lo, hi = by - STALK_DY[1], by - STALK_DY[0]
        if lo < a.lane_lo:
            lo, hi = by + DIVE_DY[-1], by + DIVE_DY[-1] + 4
        dir_y = _lane_step(a, lo, hi)
        bx = min(max(b.x, b.cam_x + SCREEN_MIN - SCREEN_BIAS), b.cam_x + SCREEN_MAX - SCREEN_BIAS - 1)
        d50 = abs(a.x - bx)
        dir_x = 0
        if dir_y and d50 < STALK_DX:
            dir_x = -toward
        elif not dir_y and d50 > STALK_DX + 8:
            dir_x = toward
        return dir_x, dir_y


def _end_danger(b: BongoSim, a: ActorSim) -> float:
    """His flame, or a charge about to leave, bearing on where the rollout
    left the actor."""

    danger = 0.0
    ax, ay = _hi(a.x), _hi(a.y)
    bx, by = _hi(b.x), _hi(b.y)
    ahead = (ax - bx) * (-1 if b.facing_left else 1)
    in_band = by - 16 < ay < by + 38
    if _charging(b) and ahead > -8 and in_band:
        danger += _DANGER_FLAME
    return danger


_MODE_COST = {
    EngageMode.WALK_IN: 0,
    EngageMode.BEHIND: 0,
    EngageMode.POCKET: 4,
    EngageMode.LEVEL: 8,
    EngageMode.WAIT: 10,
    EngageMode.STALK: 12,
    EngageMode.DIVE: 16,
}

_CANDIDATES: tuple[tuple[int, int], ...] = tuple(
    (dx, dy) for dx in (0, 1, -1) for dy in (0, -1, 1)
)


def _rollout(
    b: BongoSim,
    a: ActorSim,
    target: ActorSim | None,
    first: tuple[int, int],
    hold: int | None,
    tail: _Tail,
    *,
    actor_first: bool,
    body_top: int,
    horizon: int,
) -> tuple[Outcome, int | None, BongoSim, ActorSim]:
    """Play one candidate out: ``first`` for ``hold`` updates (None: all of
    them), then the tail policy. ``actor_first`` picks which of the two
    bodies the next update reaches first -- the snapshot can land on either
    side of ``$AD8E``'s VBlank wait, and the plan has to survive both."""

    moves = 0

    def step_actor() -> None:
        nonlocal moves
        move = first if hold is None or moves < hold else tail.move(a, b)
        actor_update(a, *move)
        moves += 1

    if actor_first:
        step_actor()
    for k in range(horizon):
        outcome = boss_update(b, a, target, margin=True, body_top=body_top)
        if outcome is not Outcome.NONE:
            return outcome, k, b, a
        step_actor()
    return Outcome.NONE, None, b, a


def _score(outcome: Outcome, at: int | None, b: BongoSim, a: ActorSim) -> float:
    if outcome is Outcome.GRAB:
        return _SCORE_GRAB - _SCORE_PER_UPDATE * at
    if outcome is Outcome.HIT:
        return _SCORE_HIT + _SCORE_PER_UPDATE * at
    mode = engage_mode(a, b)
    return -(_MODE_COST[mode] + _end_danger(b, a) + abs(_hi(a.y) - _hi(b.y)) * 0.05)


def _split_flames(bongo: Bongo, projectiles: Sequence[Projectile]) -> Projectile | None:
    flames = [p for p in projectiles if p.type_id == FLAME_TYPE]
    linked = next((p for p in flames if bongo.child_slot and p.slot == bongo.child_slot), None)
    if linked is None and len(flames) == 1:
        linked = flames[0]
    return linked


def build_sims(
    actor: PlayableCharacter,
    bongo: Bongo,
    *,
    camera: CameraRange | None = None,
    projectiles: Sequence[Projectile] | None = None,
) -> tuple[BongoSim, ActorSim]:
    """His object and the actor as the model takes them, from the tokens."""

    lane_lo, lane_hi = float(PLAYER_LANE_MIN), float(PLAYER_LANE_MAX)
    x_lo, x_hi = (camera.left, camera.right) if camera is not None else (-1e9, 1e9)
    cam_x = int(camera.left) - 0x20 if camera is not None else 0
    if bongo.screen_x:
        cam_x = bongo.world_x + SCREEN_BIAS - bongo.screen_x
    a = ActorSim.from_token(actor, lane_lo=lane_lo, lane_hi=lane_hi, x_lo=x_lo, x_hi=x_hi)
    flame = _split_flames(bongo, projectiles or ()) if projectiles is not None else None
    b = BongoSim.from_token(bongo, cam_x=cam_x, flame=flame, flame_known=projectiles is not None)
    return b, a


def plan_engage(
    actor: PlayableCharacter,
    bongo: Bongo,
    *,
    camera: CameraRange | None = None,
    partner: PlayableCharacter | None = None,
    projectiles: Sequence[Projectile] | None = None,
) -> EngagePlan:
    """The stick for this tick: every candidate played out against his AI.

    The nine stick positions, each held for ``FIRST_UPDATES`` and then handed
    to the tail policy (``_track``) with each launch offset in ``DIVE_DY``,
    ``HORIZON_UPDATES`` updates each, over ``boss_update``/``actor_update``
    -- and each twice, with his update reaching the actor before this stick
    does and after. A candidate is scored by the worse of the two: a hold by
    how soon, a hit below everything else by how soon, the rest by the
    phase the rollout ends in and whether his flame bears on it there.
    """

    b0, a0 = build_sims(actor, bongo, camera=camera, projectiles=projectiles)
    body_top = BODY_TOP_Z.get(actor.character_id, DEFAULT_BODY_TOP_Z)
    target0: ActorSim | None = None
    if partner is not None and bongo.targets_player not in (None, actor.player_index):
        target0 = ActorSim.from_token(
            partner, lane_lo=a0.lane_lo, lane_hi=a0.lane_hi, x_lo=a0.x_lo, x_hi=a0.x_hi
        )
        target0.walking = False
        target0.vx = 0.0
        target0.untouchable = target0.unavailable = False
    moving_x = 1 if actor.vel_x > 0.5 else (-1 if actor.vel_x < -0.5 else 0)
    return plan_from_sims(b0, a0, body_top=body_top, target=target0, moving_x=moving_x)


def plan_from_sims(
    b0: BongoSim,
    a0: ActorSim,
    *,
    body_top: int = DEFAULT_BODY_TOP_Z,
    target: ActorSim | None = None,
    moving_x: int = 0,
) -> EngagePlan:
    """``plan_engage`` on bodies already built -- the planner itself, for
    the tools and the offline tests that drive the model directly."""

    a0 = a0.copy()
    # A hit reaction's immunity ends on the floor landing, which the rollout
    # does not model -- so the plan assumes it already has.
    a0.untouchable = a0.unavailable = False
    target0 = target
    toward_x = _toward(a0, b0)
    mode_now = engage_mode(a0, b0)
    dives = DIVE_DY if mode_now in (EngageMode.DIVE, EngageMode.STALK, EngageMode.LEVEL) else DIVE_DY[:1]
    # His charge, once launched, flies the same whatever the actor does (bar
    # the lane speeding up, which the dodge assumes): one path for every tail.
    path0 = _predict_charge(b0, HORIZON_UPDATES) if _charging(b0) else None
    best: EngagePlan | None = None
    for hold in HOLD_UPDATES:
        for first in _CANDIDATES:
            if hold is None and first == (0, 0):
                continue  # standing still is the (0, 0) first move's own tail
            for dive in dives if hold == HOLD_UPDATES[0] else dives[:1]:
                worst: tuple[float, Outcome, int | None] | None = None
                for actor_first in (False, True):
                    outcome, at, b, a = _rollout(
                        b0.copy(), a0.copy(), target0, first, hold, _Tail(dive, path0),
                        actor_first=actor_first, body_top=body_top, horizon=HORIZON_UPDATES,
                    )
                    score = _score(outcome, at, b, a)
                    if worst is None or score < worst[0]:
                        worst = (score, outcome, at)
                    if outcome is Outcome.HIT:
                        break  # already the worse of the two
                assert worst is not None
                score, outcome, at = worst
                if moving_x and first[0] == -moving_x:
                    score -= _REVERSE_X_COST
                if first[0] == toward_x:
                    score += _TOWARD_BONUS
                if first[1] == 0:
                    score += _KEEP_LANE_BONUS
                if best is None or score > best.score:
                    best = EngagePlan(
                        dir_x=first[0],
                        dir_y=first[1],
                        mode=mode_now,
                        outcome=None if outcome is Outcome.NONE else outcome.name.lower(),
                        at_update=at,
                        score=score,
                    )
    assert best is not None
    return best


def simulate(
    bongo: Bongo,
    actor: PlayableCharacter,
    inputs: Sequence[tuple[int, int]],
    *,
    camera: CameraRange | None = None,
    margin: bool = False,
    projectiles: Sequence[Projectile] | None = None,
) -> list[tuple[Outcome, float, float, int, int]]:
    """Play ``inputs`` (one stick per update) against his AI, for tests and
    tools: per update, the outcome and his ``(x, y, primary, tactical)``."""

    b, a = build_sims(actor, bongo, camera=camera, projectiles=projectiles)
    body_top = BODY_TOP_Z.get(actor.character_id, DEFAULT_BODY_TOP_Z)
    trace = []
    for move in inputs:
        outcome = boss_update(b, a, margin=margin, body_top=body_top)
        trace.append((outcome, b.x, b.y, b.primary, b.tactical))
        if outcome is not Outcome.NONE:
            break
        actor_update(a, *move)
    return trace


# --- The hold loop ---------------------------------------------------------------


def hold_step(actor: PlayableCharacter, bongo: Bongo) -> HoldStep:
    """Knee, knee, release -- and only ever finish when finishing kills.

    Souther's loop (``souther.hold_step``): the knee chain, the release
    countdown and the crossover flag are the holding player's own bytes, and
    a released later boss goes to primary 1 in front of the actor through the
    shared ``$17CF2`` -- Bongo 32 px out (``$17D76``), facing it, straight
    into his wind-up: 21 updates in which the walking box, already touching
    his body, takes him again.

    Nothing about the flame belongs here: one still igniting when a front
    hold starts is placed on him and lands on the holder whatever it does
    (``$17858`` retires it only from anim ``$3C``, and a holder is not
    spared), so the only answer is not to take that grab -- which
    ``plan_engage`` scores as the hit it is (``_grab_is_burnt``).
    """

    return _shared_hold_step(actor, bongo)


def linked_flame(bongo: Bongo, projectiles: Sequence[Projectile]) -> Projectile | None:
    """His flame among the projectiles: the ``$97`` his ``+$6E`` names, or
    the only one there is."""

    return _split_flames(bongo, projectiles)


def charge_is_pressing(bongo: Bongo, *, lead: int = 6) -> bool:
    """His charge is running, or its launch is ``lead`` updates away or less:
    the moments no other business may take the actor's stick."""

    if bongo.primary_state != PRIMARY_CHARGE:
        return False
    if bongo.tactical >= TAC_CHARGE:
        return True
    left = bongo.timer_68 + sum(WINDUP_UPDATES[bongo.tactical + 1 :])
    return left <= lead
