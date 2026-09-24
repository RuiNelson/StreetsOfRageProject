"""Mr. X (type ``$35``, round 8): the ROM model.

He is the older bespoke framework Abadede belongs to (``$1306A (mr_x_boss_update)``;
``ai-analysis/enemy-ai.md``, "Mr. X body and attack state machine"): a
primary at ``+$30`` dispatched through the relative word table at ``$130B8``,
a substate at ``+$5B`` (``$12B4C``), one word timer at ``+$54``, the target at
``+$5C``, X/lane/height as 16.16 at ``+$10``/``+$14``/``+$18`` and their
velocities at ``+$1C``/``+$20``/``+$24``. Every update is one object pass, 30
Hz. What the plan rests on:

State 3 decides (``$130EE``)
    Standing, facing the target. Off screen (``$97CE``: ``+$28`` outside
    ``[$80, $1C0)``), a coin: walk in (6) or reposition (4). On screen,
    ``|dx| < $80`` walks in; otherwise ``+$54`` (10) runs out and he goes to
    the gun (7). He tests contact only while he waits.
State 6 walks in (``$13B6C``)
    8 px an update on whichever axis is still far -- X while ``|dx| >= $40``,
    the lane while ``|dl| >= $10`` -- and inside both, the lunge (2), with no
    contact test on that update. After the move, the contact test.
State 2 is the lunge (``$13D86``)
    Set-up (no test), then four updates at 16/14/12/10 px (``+$1C`` = 18,
    less 2 each, before the move) with the test before each move, a switch
    update, and six standing updates with the test on five of them. His box
    (``$3A``/``$39``: 8 behind to 64 ahead, lane +-8, the whole height) is out
    through all of it, and it lands ``+$34`` (34 on Normal). Then the retreat
    (5), or one time in four, on screen, the gun.
State 5 backs off (``$13AFA``)
    Facing the target, 8 px an update away from it for 40 updates or until
    ``+$28`` leaves ``[$B8, $188)``; then state 1 (``$130D6``) and state 3.
    Its set-up falls into the first update: the contact test runs where the
    hold released him, before he moves.
State 7 is the gun (``$13BD0``)
    Up the street at 8 px an update to lane 2.5 (the test after each move),
    21 updates there (the test on each), turned to the target's side, then 30
    updates of fire: a bullet (type ``$36``) whenever his frame (``+$0A``,
    stepped every second update) changes to an even one -- eight, fanning
    from straight down the street (index 0) to level with his facing (7), 24
    px an update, 48 px up, 20 damage (``$1417C``). No box of his is out: the
    gun sequence can only be walked into, which is a hold. Then state 4.
State 4 repositions (``$1314C``)
    8 px an update in X toward the target and in lane down or up
    (``$13FFC``), until the screen band ``[$B8, $188)`` stops him (state 3)
    or ``|dl| < $10`` and ``|dx| < $50`` starts the lunge.
The contact test (``$13ED8``, ``$AA22``)
    The player's box on his body first (a strike, ``+$34`` set: 2; else a
    grab: 3), then his box on the player's body (1). A grab puts him in state
    ``$A`` (held in front) or ``$B`` (from behind) by the holder's ``+$7D``
    (``$13F5E``); a strike in state 8 (10 updates of shake, then the
    retreat), or 9 (a knockdown) if it carries the knockdown property.
The hold (state ``$A``, ``$13598``)
    Substate 0 stands him 24 px in front of the holder, facing it, ``+$54`` =
    40; substate 1 reads the holder's ``+$7D`` every update (``$1362A``): 0
    (released) the retreat -- whose first update tests contact where he
    stands, so a walk straight back in is the re-grab; 3 (a knee) the holder's
    ``+$34``, 10 updates of shake and the set-up again; 4 (the third knee) a
    knockdown in 6; 5/7 (a throw) state ``$C``; 6 (the suplex) state ``$B``;
    9 (a crossover) ``+$54`` = 8. Forty updates with nothing read and he is
    free.

The bullets (``$140DC``): set-up (``$140EA``) puts one ``(dx, dlane)`` from
his origin (``$350FC``, X mirrored with his facing) and 48 px up, at the
table's velocity; each update after, off screen or below lane 112.5 it is
gone, else the contact test (its ``$3B`` box: X +-4, lane +-2, 8 px tall; on
the player's body: the hit), then it moves.
"""

from __future__ import annotations

import math
from enum import Enum, auto
from typing import Sequence

from .twins import (
    ADAM,
    AXEL,
    BLAZE,
    PLAYER_LANE_MAX,
    PLAYER_LANE_MIN,
    PLAYER_X_MAX_OFFSET,
    PLAYER_X_MIN_OFFSET,
    ActorSim,
    _clamp_word,
    _hi,
    actor_update,
    chord_step_from,
    overlaps,
    refresh_boxes,
)

__all__ = [
    "BulletSim",
    "MrXSim",
    "Outcome",
    "actor_from_bytes",
    "check_recording",
    "mr_x_update",
    "object_pass",
]

MR_X_TYPE = 0x35
BULLET_TYPE = 0x36
SHELL_TYPE = 0x37

# --- His states ($130B8) -------------------------------------------------------

PRIMARY_ENTRANCE = 0x00  # $13E3E: 0 $13E4C, 1 the stand-up $13E6C, 2 $13E9E
PRIMARY_RESUME = 0x01  # $130D6: straight to 3
PRIMARY_LUNGE = 0x02  # $13D86: 0 set-up, 1 the dash, 2 the follow-through
PRIMARY_DECIDE = 0x03  # $130EE
PRIMARY_REPOSITION = 0x04  # $1314C
PRIMARY_RETREAT = 0x05  # $13AFA
PRIMARY_WALK_IN = 0x06  # $13B54
PRIMARY_GUN = 0x07  # $13BD0: 0 set-up, 1 up the street, 2 the wait, 3 the fire
PRIMARY_HURT = 0x08  # $1371C
PRIMARY_KNOCKDOWN = 0x09  # $13778
PRIMARY_HELD = 0x0A  # $1353A
PRIMARY_HELD_BACK = 0x0B  # $13218
PRIMARY_THROWN = 0x0C  # $132B2
PRIMARY_SUPLEXED = 0x0D  # $1344A
PRIMARY_DYING = 0x0E  # $13808

# --- Speeds, gates and timers ----------------------------------------------------

WALK_SPEED = 8.0  # $14072: +$1C = +$20 = $80000
DECIDE_UPDATES = 10
DECIDE_WALK_DX = 0x80  # $130EE: |dx| under it walks in
WALK_LANE_GATE = 0x10  # $13B6C: $00100040
WALK_X_GATE = 0x40
REPOSITION_LANE_GATE = 0x10  # $13188: $00100050
REPOSITION_X_GATE = 0x50
LUNGE_SPEED = 18.0  # $13D94
LUNGE_DECEL = 2.0
LUNGE_DASH = 5
LUNGE_HOLD = 6
RETREAT_UPDATES = 0x28
SCREEN_BAND_MIN = 0xB8  # $13188, $13B22, $13886
SCREEN_BAND_MAX = 0x188
ON_SCREEN_MIN = 0x80  # $97CE
ON_SCREEN_MAX = 0x1C0
STRIKE_SCREEN_MIN = 0x78  # $AAA0
STRIKE_SCREEN_MAX = 0x1C8
GUN_LANE = 2.5  # $13BFC: $28000
GUN_WAIT = 0x15
GUN_TURN_AT = 0x11  # $13C4E: +$1 bit 2 cleared from here
GUN_SHOTS = 0x10
GUN_STEP = 2
REPOSITION_LANE_MIN = 3.0  # $13188
REPOSITION_LANE_MAX = 112.5
WALK_LANE_MIN = 2.5  # $13B96
HURT_UPDATES = 10
HELD_UPDATES = 0x28
HELD_BACK_UPDATES = 0x1E
HELD_STAND_DX = 0x18
KNOCKDOWN_VX = 4.0  # $13FB4
KNOCKDOWN_ACC = 0x3000 / 65536.0
KNOCKDOWN_VZ = -8.0
KNOCKDOWN_GRAVITY = 0x12000 / 65536.0  # $13788
LANDING_GRAVITY = 0xC000 / 65536.0  # $1292E
FLOOR_ROUND_8 = 0xA8  # $1296A: $A0, or $A8 in level index 7
FLOOR = 0xA0
FLOOR_WAIT = 6  # $137CA
GET_UP_UPDATES = 5
DEATH_HP = 0
SCREEN_BIAS = 0x80

# The target's +$2C against $121: $13FFC's "is the target high on screen".
TARGET_HIGH_Y = 0x121 + 0x18

# --- Animations (set $3468A) and boxes ($1A68E) -------------------------------------
#
# +$08 picks the animation, bit 1 its mirror. His fighting animations carry one
# pair of boxes on every frame; the rest are listed by frame.
ANIM_MIRROR = 0x02
ANIM_WALK = 0x00
ANIM_GUN_UP = 0x04
ANIM_FIRE = 0x08
ANIM_LUNGE = 0x0C
ANIM_HURT = 0x10
ANIM_HELD = 0x14
ANIM_FLY = 0x18
ANIM_THROWN = 0x1C
ANIM_BULLET = 0x20

_ANIM_FRAMES: dict[int, tuple[tuple[int, int], ...]] = {
    0x00: ((0, 0x38),) * 4,
    0x02: ((0, 0x38),) * 4,
    0x04: ((0, 0x38),) * 3,
    0x06: ((0, 0x38),) * 3,
    0x08: ((0, 0x38),) * 16,
    0x0A: ((0, 0x38),) * 16,
    0x0C: ((0x3A, 0x38),) * 2,
    0x0E: ((0x39, 0x38),) * 2,
    0x10: ((0, 0x38), (0xD0, 0x0F)),
    0x12: ((0, 0x38), (0xE0, 0x0F)),
    0x14: ((0, 0), (0x5E, 0), (0, 0)),
    0x16: ((0, 0), (0x5F, 0), (0, 0)),
    0x18: ((0x5C, 0), (0x5E, 0), (0, 0)),
    0x1A: ((0x5D, 0), (0x5F, 0), (0, 0)),
    0x1C: ((0, 0), (0, 0), (0x5E, 0)),
    0x1E: ((0, 0), (0, 0), (0x5F, 0)),
    0x20: ((0x3B, 0x63),) * 3,
    0x22: ((0x3B, 0x63),) * 3,
}

# The object shape table ($1A68E): (x0, x1, lane0, lane1, z0, z1) about the
# origin, inclusive. Only the ids his fight shows.
SHAPES: dict[int, tuple[int, int, int, int, int, int]] = {
    0x38: (-8, 8, -8, 8, -80, 0),
    0x39: (-64, 8, -8, 8, -80, 0),
    0x3A: (-8, 64, -8, 8, -80, 0),
    0x3B: (-4, 4, -2, 2, -8, 0),
    0x63: (-4, 4, -8, 8, -2, 0),
    0x0F: (-24, 24, -8, 8, -14, 0),
    0x5C: (-56, 0, -8, 8, -32, 0),
    0x5D: (0, 56, -8, 8, -32, 0),
    0x5E: (-32, 0, -8, 8, -48, 0),
    0x5F: (0, 32, -8, 8, -48, 0),
    0xD0: (0, 0, -8, 8, 0, 0),
    0xE0: (0, 0, -8, 8, 0, 0),
}

# $350FC: per bullet index, (vx, vy, frame, dx, dlane); X mirrored when he faces left.
BULLET_TABLE: tuple[tuple[float, float, int, int, int], ...] = (
    (0.0, 24.0, 0, 10, 32),
    (5.0, 23.375, 0, 10, 32),
    (10.5, 21.5625, 1, 20, 14),
    (15.0625, 18.5625, 1, 20, 14),
    (18.875, 14.8125, 1, 24, 12),
    (21.6875, 10.0625, 1, 24, 12),
    (23.5, 5.0, 2, 32, 10),
    (24.0, 0.0, 2, 32, 10),
)
BULLET_RISE = 0x30  # $140EA: 48 px up
BULLET_LANE_MAX = 112.5  # $1417C: $708000
BULLET_DAMAGE = 0x14

# A player's hold family ($60-$6F) and its +$7D codes ($32F2 via the hold moves).
HOLD_CODE_RELEASED = 0
HOLD_CODE_FRONT = 1
HOLD_CODE_BACK = 2
HOLD_CODE_KNEE = 3
HOLD_CODE_THIRD_KNEE = 4
HOLD_CODE_SUPLEX = 6
HOLD_CODE_CROSSOVER = 9
# $13F5E: the holder's +$7D -> the state a grab puts him in ($FF: none).
GRAB_STATE = (0x0A, 0x0A, 0x0B, 0x0A, 0x0A, 0x0A, 0x0B, 0x0A, 0x0A, 0x0A, 0x0A, 0xFF)
GRAB_Z = 8  # $AADC

# The player's contact codes $AA22 writes to +$7C.
CODE_HIT = 1
CODE_STRUCK = 2
CODE_GRAB = 3


class Outcome(Enum):
    NONE = auto()
    HIT = auto()  # his lunge, or a bullet, landed on the actor
    GRAB = auto()  # the actor's walking box took him into a hold
    STRUCK = auto()  # the actor's strike registered on him


def box(box_id: int, x: int, y: int, z: int) -> tuple[int, int, int, int, int, int] | None:
    shape = SHAPES.get(box_id)
    if shape is None or not box_id:
        return None
    return (x + shape[0], x + shape[1], y + shape[2], y + shape[3], z + shape[4], z + shape[5])


def _s16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big", signed=True)


def _s32(data: bytes, offset: int) -> float:
    return int.from_bytes(data[offset : offset + 4], "big", signed=True) / 65536.0


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


# --- Him ------------------------------------------------------------------------


class MrXSim:
    """His object, reduced to what his states read and write."""

    __slots__ = (
        "slot", "x", "y", "z", "vx", "vy", "vz", "acc", "grav", "shake",
        "primary", "sub", "t54", "t56", "anim", "frame", "last_frame",
        "flags1", "f37", "hp", "damage", "screen_x", "cam_x", "floor",
        "attack_id", "body_id", "latch", "gone",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))

    def copy(self) -> MrXSim:
        other = MrXSim.__new__(MrXSim)
        for name in self.__slots__:
            setattr(other, name, getattr(self, name))
        return other

    @property
    def facing_left(self) -> bool:
        return bool(self.anim & ANIM_MIRROR)

    @classmethod
    def from_bytes(cls, data: bytes, *, slot: int, cam_x: int, level_index: int = 7) -> MrXSim:
        return cls(
            slot=slot,
            x=_s32(data, 0x10),
            y=_s32(data, 0x14),
            z=_s32(data, 0x18),
            vx=_s32(data, 0x1C),
            vy=_s32(data, 0x20),
            vz=_s32(data, 0x24),
            acc=_s32(data, 0x5E),
            grav=_s32(data, 0x62),
            shake=_s16(data, 0x5E),
            primary=data[0x30],
            sub=data[0x5B],
            t54=_u16(data, 0x54),
            t56=_u16(data, 0x56),
            anim=_u16(data, 0x08),
            frame=data[0x0A],
            last_frame=data[0x5A],
            flags1=data[0x01],
            f37=data[0x37],
            hp=_s16(data, 0x32),
            damage=data[0x34],
            screen_x=_s16(data, 0x28),
            cam_x=cam_x,
            floor=FLOOR_ROUND_8 if level_index == 7 else FLOOR,
            attack_id=data[0x02],
            body_id=data[0x03],
            latch=0,
            gone=False,
        )


def set_anim(m: MrXSim, anim: int) -> None:
    """``sub_140CE``/``init_object_animation_frame``: frame 0, boxes now."""

    m.anim = anim
    m.frame = 0
    m.attack_id, m.body_id = _ANIM_FRAMES.get(anim & ~0, ((0, 0),))[0]


def _frame_boxes(m: MrXSim) -> None:
    frames = _ANIM_FRAMES.get(m.anim)
    if frames:
        m.attack_id, m.body_id = frames[min(m.frame, len(frames) - 1)]


def _face(m: MrXSim, a: ActorSim) -> None:
    """``$14048``: bit 1 of the animation by the target's side (``sub.l``)."""

    left = a.x - m.x < 0
    base = m.anim & ~ANIM_MIRROR
    m.anim = base | (ANIM_MIRROR if left else 0)
    _frame_boxes(m)


def _signs_toward(m: MrXSim, a: ActorSim) -> None:
    """``$1401E``: the velocities' signs toward the target (``$12A4E``)."""

    x_sign = 1 if a.x - m.x >= 0 else -1
    y_sign = 1 if a.y - m.y >= 0 else -1
    if (m.vx < 0) != (x_sign < 0):
        m.vx = -m.vx
    if (m.vy < 0) != (y_sign < 0):
        m.vy = -m.vy


def _walk_setup(m: MrXSim, a: ActorSim) -> None:
    """``$14072``: both velocities 8 toward the target, the walk, facing it."""

    m.flags1 |= 0x0C
    m.vx = WALK_SPEED
    m.vy = WALK_SPEED
    _signs_toward(m, a)
    set_anim(m, ANIM_WALK)
    _face(m, a)


def _range(m: MrXSim, a: ActorSim, lane_gate: int, x_gate: int) -> tuple[int, int, int]:
    """``$12A78``: (d7, |dlane|, |dx|) on the integer words."""

    dl = abs(_hi(a.y) - _hi(m.y))
    dx = abs(_hi(a.x) - _hi(m.x))
    d7 = (1 if dl >= lane_gate else 0) | (2 if dx >= x_gate else 0)
    return d7, dl, dx


def _on_screen(m: MrXSim) -> bool:
    return ON_SCREEN_MIN <= m.screen_x < ON_SCREEN_MAX


def _in_band(m: MrXSim) -> bool:
    return SCREEN_BAND_MIN <= m.screen_x < SCREEN_BAND_MAX


def _integrate(m: MrXSim) -> None:
    m.x += m.vx
    m.y += m.vy
    m.z += m.vz


def contact(m: MrXSim, a: ActorSim) -> int:
    """``$AA22``/``$AAA0`` on the actor: 2 a strike on him, 3 a grab, 1 his
    box on the actor's body, 0 nothing."""

    if a.unavailable or a.latch:
        return 0
    x, y, z = _hi(m.x), _hi(m.y), _hi(m.z)
    body = box(m.body_id, x, y, z)
    if a.attack is not None and body is not None and overlaps(a.attack, body):
        if a.damage:
            if STRIKE_SCREEN_MIN <= m.screen_x < STRIKE_SCREEN_MAX:
                return CODE_STRUCK
            return 0
        if not a.holding and abs(a.z - z) <= GRAB_Z:
            return CODE_GRAB
        return 0
    attack = box(m.attack_id, x, y, z)
    if attack is not None and a.body is not None and overlaps(attack, a.body):
        return CODE_HIT
    return 0


def _knockdown_flight(m: MrXSim, a: ActorSim) -> None:
    """``$13FB4``: 4 px an update the way the target faces, slowing."""

    m.acc = -KNOCKDOWN_ACC
    m.vz = KNOCKDOWN_VZ
    m.vx = KNOCKDOWN_VX
    if a.facing_left:
        m.vx = -m.vx
        m.acc = -m.acc


def _dispatch(m: MrXSim, a: ActorSim) -> Outcome:
    """``$13ED8``: the contact test and what each code does to him."""

    code = contact(m, a)
    if code == CODE_HIT:
        a.latch = CODE_HIT
        return Outcome.HIT
    if code == CODE_STRUCK:
        a.latch = CODE_STRUCK
        m.primary, m.sub = PRIMARY_HURT, 0
        if getattr(a, "knockdown", False):
            m.primary, m.sub = PRIMARY_KNOCKDOWN, 0
            _knockdown_flight(m, a)
        m.hp -= a.damage
        if m.hp <= 0:
            m.primary, m.sub = PRIMARY_DYING, 0
        return Outcome.STRUCK
    if code == CODE_GRAB:
        a.latch = CODE_GRAB
        m.primary, m.sub = PRIMARY_HELD, 0
        return Outcome.GRAB
    return Outcome.NONE


# --- His states --------------------------------------------------------------------


def _decide(m: MrXSim, a: ActorSim, rng: int) -> Outcome:
    if not _on_screen(m):
        m.sub = 0
        m.primary = PRIMARY_REPOSITION if rng & 1 else PRIMARY_WALK_IN
        return Outcome.NONE
    _, _, dx = _range(m, a, 0x10, 0x50)
    if dx < DECIDE_WALK_DX:
        m.primary, m.sub = PRIMARY_WALK_IN, 0
        return Outcome.NONE
    m.t54 = (m.t54 - 1) & 0xFFFF
    if m.t54 == 0:
        m.primary, m.sub = PRIMARY_GUN, 0
        return Outcome.NONE
    out = _dispatch(m, a)
    _face(m, a)
    return out


def _to_decide(m: MrXSim, a: ActorSim) -> None:
    m.t54 = DECIDE_UPDATES
    m.flags1 &= ~0x04
    m.primary = PRIMARY_DECIDE


def _resume(m: MrXSim, a: ActorSim) -> Outcome:
    _walk_setup(m, a)
    _to_decide(m, a)
    return Outcome.NONE


def _reposition(m: MrXSim, a: ActorSim) -> Outcome:
    if m.sub == 0:
        m.flags1 |= 0x04
        _walk_setup(m, a)
        _signs_toward(m, a)
        m.vy = WALK_SPEED
        screen_y = getattr(a, "screen_y", None)
        if screen_y is None:
            # +$2C, as the renderer leaves it: the lane and the height, biased.
            screen_y = _hi(a.y) + int(a.z) + 126
        target_high = screen_y - 0x121 < 0x18
        if not target_high:
            m.vy = -m.vy
        m.sub = 1
        return Outcome.NONE
    _integrate(m)
    if m.y <= REPOSITION_LANE_MIN:
        m.y = REPOSITION_LANE_MIN
        m.vy = 0.0
    elif m.y >= REPOSITION_LANE_MAX:
        m.y = REPOSITION_LANE_MAX
        m.vy = 0.0
    if (m.vx < 0 and m.screen_x < SCREEN_BAND_MIN) or (m.vx >= 0 and m.screen_x >= SCREEN_BAND_MAX):
        _face(m, a)
        m.vy = WALK_SPEED
        _signs_toward(m, a)
        _to_decide(m, a)
        return Outcome.NONE
    d7, _, _ = _range(m, a, REPOSITION_LANE_GATE, REPOSITION_X_GATE)
    if d7 == 0:
        m.primary, m.sub = PRIMARY_LUNGE, 0
        return Outcome.NONE
    return _dispatch(m, a)


def _walk_in(m: MrXSim, a: ActorSim) -> Outcome:
    if m.sub == 0:
        _walk_setup(m, a)
        m.sub = 1
        return Outcome.NONE
    d7, _, _ = _range(m, a, WALK_LANE_GATE, WALK_X_GATE)
    if d7 == 0:
        m.primary, m.sub = PRIMARY_LUNGE, 0
        return Outcome.NONE
    if d7 & 1:
        m.y += m.vy
    if d7 & 2:
        m.x += m.vx
    if m.y <= WALK_LANE_MIN:
        m.y = WALK_LANE_MIN
    _face(m, a)
    _signs_toward(m, a)
    return _dispatch(m, a)


def _lunge(m: MrXSim, a: ActorSim, rng: int) -> Outcome:
    if m.sub == 0:
        m.flags1 &= ~0x04
        m.anim = ANIM_LUNGE
        _face(m, a)
        set_anim(m, m.anim)
        m.vy = 0.0
        m.vx = -LUNGE_SPEED
        m.acc = LUNGE_DECEL
        if not m.facing_left:
            m.vx, m.acc = -m.vx, -m.acc
        m.t54 = LUNGE_DASH
        m.sub = 1
        return Outcome.NONE
    if m.sub == 1:
        m.t54 = (m.t54 - 1) & 0xFFFF
        if m.t54 == 0:
            m.t54 = LUNGE_HOLD
            m.sub = 2
            return Outcome.NONE
        m.vx += m.acc
        out = _dispatch(m, a)
        _integrate(m)
        return out
    m.t54 = (m.t54 - 1) & 0xFFFF
    if m.t54 != 0:
        return _dispatch(m, a)
    m.primary, m.sub = PRIMARY_RETREAT, 0
    if not _on_screen(m):
        return _dispatch(m, a)
    if rng & 3 == 0:
        m.primary = PRIMARY_GUN
        return _dispatch(m, a)
    return Outcome.NONE


def _retreat(m: MrXSim, a: ActorSim) -> Outcome:
    if m.sub == 0:
        _walk_setup(m, a)
        m.vx = -m.vx
        m.vy = 0.0
        m.t54 = RETREAT_UPDATES
        m.sub = 1
        # $13B06 falls into $13B22.
    if not _in_band(m):
        m.t54 = DECIDE_UPDATES
        m.primary = PRIMARY_RESUME
        return Outcome.NONE
    m.t54 = (m.t54 - 1) & 0xFFFF
    if m.t54 == 0:
        m.t54 = DECIDE_UPDATES
        m.primary = PRIMARY_RESUME
        return Outcome.NONE
    out = _dispatch(m, a)
    _integrate(m)
    return out


def _gun(m: MrXSim, a: ActorSim, spawned: list) -> Outcome:
    if m.sub == 0:
        _walk_setup(m, a)
        m.vy = -WALK_SPEED
        m.vx = 0.0
        m.sub = 1
        return Outcome.NONE
    if m.sub == 1:
        if m.y > GUN_LANE:
            _integrate(m)
            return _dispatch(m, a)
        m.y = GUN_LANE
        m.flags1 |= 0x04
        set_anim(m, ANIM_GUN_UP | (m.anim & ANIM_MIRROR))
        m.t54 = GUN_WAIT
        m.sub = 2
        m.last_frame = 0xFF
        return Outcome.NONE
    if m.sub == 2:
        m.t54 = (m.t54 - 1) & 0xFFFF
        if m.t54 != 0:
            if m.t54 <= GUN_TURN_AT:
                m.flags1 &= ~0x04
            return _dispatch(m, a)
        m.flags1 |= 0x04
        left = a.x - m.x < 0
        set_anim(m, ANIM_FIRE | (ANIM_MIRROR if left else 0))
        m.flags1 &= ~0x04
        m.t54 = GUN_SHOTS
        m.t56 = GUN_STEP
        m.sub = 3
        return Outcome.NONE
    m.t56 = (m.t56 - 1) & 0xFFFF
    if m.t56 == 0:
        m.t56 = GUN_STEP
        m.t54 = (m.t54 - 1) & 0xFFFF
        if m.t54 == 0:
            _walk_setup(m, a)
            m.primary, m.sub = PRIMARY_REPOSITION, 0
            return Outcome.NONE
        m.frame = (m.frame + 1) & 0xFF
    if m.last_frame != m.frame:
        m.last_frame = m.frame
        if m.frame % 2 == 0:
            spawned.append(spawn_bullet(m, m.frame // 2))
    return _dispatch(m, a)


def _hurt(m: MrXSim, a: ActorSim) -> Outcome:
    if m.sub == 0:
        m.flags1 &= ~0x04
        set_anim(m, ANIM_HURT | (m.anim & ANIM_MIRROR))
        m.t54 = HURT_UPDATES
        m.sub = 1
        m.shake = 1
        return Outcome.NONE
    m.t54 = (m.t54 - 1) & 0xFFFF
    if m.t54 == 0:
        m.primary, m.sub = PRIMARY_RETREAT, 0
        return Outcome.NONE
    m.x += m.shake
    m.shake = -m.shake
    return Outcome.NONE


def _knockdown(m: MrXSim, a: ActorSim) -> Outcome:
    if m.sub == 0:
        m.flags1 &= ~0x04
        set_anim(m, ANIM_FLY if m.vx < 0 else ANIM_FLY | ANIM_MIRROR)
        m.grav = KNOCKDOWN_GRAVITY
        m.vy = 0.0
        m.sub = 1
        return Outcome.NONE
    if m.sub == 1:
        if m.vz > 0:
            m.vz = 0.0
            m.grav = LANDING_GRAVITY
            m.frame += 1
            _frame_boxes(m)
            m.sub = 2
            return Outcome.NONE
        m.vx += m.acc
        m.vz += m.grav
        _integrate(m)
        return Outcome.NONE
    if m.sub == 2:
        if m.z < m.floor:
            m.vx += m.acc
            m.vz += m.grav
            _integrate(m)
            return Outcome.NONE
        m.z = float(m.floor)
        if m.vz > 1.0:
            m.vz = -math.floor(m.vz * 65536 / 8) / 65536.0
            _integrate(m)
            return Outcome.NONE
        m.vz = 0.0
        m.t54 = FLOOR_WAIT
        m.sub = 3
        return Outcome.NONE
    m.t54 = (m.t54 - 1) & 0xFFFF
    if m.t54 == 0:
        m.primary, m.sub = PRIMARY_ENTRANCE, 1
    return Outcome.NONE


def _entrance(m: MrXSim, a: ActorSim) -> Outcome:
    if m.sub in (0, 1):
        m.flags1 = (m.flags1 & ~0x04) | 0x08
        m.t54 = GET_UP_UPDATES
        m.sub = 2
        set_anim(m, ANIM_FLY)
        m.frame += 2
        _frame_boxes(m)
        _face(m, a)
        return Outcome.NONE
    m.t54 = (m.t54 - 1) & 0xFFFF
    if m.t54 == 0:
        _walk_setup(m, a)
        m.flags1 &= ~0x04
        m.t54 = DECIDE_UPDATES
        m.primary = PRIMARY_DECIDE
    return Outcome.NONE


def _held_released(m: MrXSim, a: ActorSim) -> Outcome:
    """State ``$A`` once the actor has let go: substate 0 stands him 24 px in
    front of it (``$1354C``), 1 reads the cleared ``+$7D`` and goes to the
    retreat (``$13642``), 2-3 finish a knee's shake first."""

    if m.sub == 0:
        m.x = a.x + (-HELD_STAND_DX if a.facing_left else HELD_STAND_DX)
        m.y = a.y
        m.t54 = HELD_UPDATES
        m.sub = 1
        return Outcome.NONE
    if m.sub == 1:
        m.primary, m.sub = PRIMARY_RETREAT, 0
        return Outcome.NONE
    if m.sub == 2:
        m.t54 = HURT_UPDATES
        m.sub = 3
        return Outcome.NONE
    m.t54 = (m.t54 - 1) & 0xFFFF
    if m.t54 == 0:
        m.sub = 0
    return Outcome.NONE


def mr_x_update(m: MrXSim, a: ActorSim, *, rng: int = 1, spawned: list | None = None) -> Outcome:
    """One of his updates, from his own dispatcher. ``rng`` stands for
    ``$104D8``: bit 0 is state 3's off-screen coin, the low two bits the
    lunge's gun draw (0: the gun). A state the model does not replay (held,
    thrown, dying) is left as it is."""

    spawned = spawned if spawned is not None else []
    m.latch = 0
    p = m.primary
    if p == PRIMARY_DECIDE:
        return _decide(m, a, rng)
    if p == PRIMARY_RESUME:
        return _resume(m, a)
    if p == PRIMARY_WALK_IN:
        return _walk_in(m, a)
    if p == PRIMARY_LUNGE:
        return _lunge(m, a, rng)
    if p == PRIMARY_RETREAT:
        return _retreat(m, a)
    if p == PRIMARY_GUN:
        return _gun(m, a, spawned)
    if p == PRIMARY_REPOSITION:
        return _reposition(m, a)
    if p == PRIMARY_HURT:
        return _hurt(m, a)
    if p == PRIMARY_KNOCKDOWN:
        return _knockdown(m, a)
    if p == PRIMARY_ENTRANCE and m.sub != 0:
        return _entrance(m, a)
    if p == PRIMARY_HELD and not a.holding:
        return _held_released(m, a)
    return Outcome.NONE


def emit(m: MrXSim) -> None:
    """After his update: the lane word held at 0 or more (the fraction kept,
    as ``$43AA`` does for a player -- seen on the walk up to the gun lane,
    7.5 - 8 reading 0.5), and the renderer's ``+$28``."""

    whole = _hi(m.y)
    if whole < 0:
        m.y = m.y - whole
    m.screen_x = _hi(m.x) - m.cam_x + SCREEN_BIAS


def forced_knockdown(m: MrXSim, a: ActorSim) -> bool:
    """``$13082``: a player's respawn landing (``$9494`` sets bit 0 of
    ``$FFFA53``) knocks him down on his next update, unless he is down, held
    or dead already. True when it did."""

    if m.hp <= 0 or m.primary in (PRIMARY_KNOCKDOWN, PRIMARY_HELD):
        return False
    m.primary, m.sub = PRIMARY_KNOCKDOWN, 0
    _knockdown_flight(m, a)
    return True


# --- The bullets ------------------------------------------------------------------------


class BulletSim:
    """One ``$36``. ``delay`` counts passes before its set-up has run (a slot
    below his is set up a pass late); ``fresh`` marks one fired this pass."""

    __slots__ = ("slot", "x", "y", "z", "vx", "vy", "state", "screen_x", "cam_x", "fresh", "delay")

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))

    def copy(self) -> BulletSim:
        other = BulletSim.__new__(BulletSim)
        for name in self.__slots__:
            setattr(other, name, getattr(self, name))
        return other

    @classmethod
    def from_bytes(cls, data: bytes, *, slot: int, cam_x: int) -> BulletSim:
        if data[0x30] == 0:
            # Fired into a slot below his: $140EA runs on the next pass.
            vx, vy, _, dx, dl = BULLET_TABLE[min(data[0x58], len(BULLET_TABLE) - 1)]
            left = bool(data[0x59])
            x = _s32(data, 0x10) + (-dx if left else dx)
            b = cls(
                slot=slot, x=x, y=_s32(data, 0x14) + dl, z=_s32(data, 0x18) - BULLET_RISE,
                vx=-vx if left else vx, vy=vy, state=1, screen_x=0, cam_x=cam_x,
                fresh=False, delay=1,
            )
            b.screen_x = _hi(b.x) - cam_x + SCREEN_BIAS
            return b
        return cls(
            slot=slot,
            x=_s32(data, 0x10),
            y=_s32(data, 0x14),
            z=_s32(data, 0x18),
            vx=_s32(data, 0x1C),
            vy=_s32(data, 0x20),
            state=data[0x30],
            screen_x=_s16(data, 0x28),
            cam_x=cam_x,
            fresh=False,
            delay=0,
        )


def spawn_bullet(m: MrXSim, index: int) -> BulletSim:
    """``$13CFA`` then ``$140EA``: the bullet as its set-up leaves it."""

    vx, vy, _, dx, dl = BULLET_TABLE[min(index, len(BULLET_TABLE) - 1)]
    left = m.facing_left
    x = m.x + (-dx if left else dx)
    b = BulletSim(
        slot=None,
        x=x,
        y=m.y + dl,
        z=m.z - BULLET_RISE,
        vx=-vx if left else vx,
        vy=vy,
        state=1,
        screen_x=0,
        cam_x=m.cam_x,
        fresh=True,
        delay=0,
    )
    b.screen_x = _hi(b.x) - b.cam_x + SCREEN_BIAS
    return b


def bullet_box(b: BulletSim) -> tuple[int, int, int, int, int, int] | None:
    return box(0x3B, _hi(b.x), _hi(b.y), _hi(b.z))


def bullet_update(b: BulletSim, a: ActorSim) -> Outcome:
    """``$1417C``: off screen or past the street it is gone; else the test,
    then the move."""

    if b.state != 1:
        return Outcome.NONE
    if b.delay:
        b.delay -= 1
        return Outcome.NONE
    if not (ON_SCREEN_MIN <= b.screen_x < ON_SCREEN_MAX) or b.y > BULLET_LANE_MAX:
        b.state = 0
        return Outcome.NONE
    out = Outcome.NONE
    if not a.unavailable and not a.latch:
        hit = bullet_box(b)
        if hit is not None and a.body is not None and overlaps(hit, a.body):
            a.latch = CODE_HIT
            out = Outcome.HIT
    b.x += b.vx
    b.y += b.vy
    b.screen_x = _hi(b.x) - b.cam_x + SCREEN_BIAS
    return out


def object_pass(m: MrXSim | None, bullets: list[BulletSim], a: ActorSim, *, rng: int = 1) -> list[Outcome]:
    """One object pass: the bullets in flight, him, and the bullets his update
    fires (their set-up this pass, their first test the next)."""

    outcomes: list[Outcome] = []
    for b in bullets:
        outcomes.append(bullet_update(b, a))
    if m is not None and not m.gone:
        spawned: list[BulletSim] = []
        outcomes.append(mr_x_update(m, a, rng=rng, spawned=spawned))
        emit(m)
        bullets.extend(spawned)
    bullets[:] = [b for b in bullets if b.state == 1]
    return outcomes


# --- The actor's punch ---------------------------------------------------------------------
#
# ``controls-and-input.md``, "Measured normal punch" (as ``abadede.py`` has it):
# the box ahead of the origin, the updates after the press it is live on, and
# the lock. One point, no knockdown; a strike on him is tested before his box.
PUNCH_BOX_X = {AXEL: (16, 57), ADAM: (8, 54), BLAZE: (18, 68)}
PUNCH_LIVE = {AXEL: (2, 6), ADAM: (2, 6), BLAZE: (3, 7)}
PUNCH_LOCK = 10
PUNCH_DAMAGE = 1


def blink_step(a: ActorSim) -> None:
    """``$4F4C``, early in the player's update: the blink's countdown
    (``+$49``, armed at 48 by ``$4F62`` on getting up from a knockdown and on
    a respawn); ``$4140`` caches no body while it runs -- nothing lands, and a
    Garcia's jab trigger, which reads that body, never fires."""

    if a.blink:
        a.blink -= 1
        a.invulnerable = a.blink > 0


def actor_step(a: ActorSim, dir_x: int, dir_y: int, punch: bool = False, chord: bool = False) -> None:
    """One actor update: the blink, then the rear attack's schedule
    (``twins.CHORD_SCHEDULES``: B+C, the box behind, every live update a
    knockdown), the punch on its frames (standing, the facing it had when
    pressed), or the stick."""

    blink_step(a)
    if a.chord is not None or (chord and getattr(a, "punch", None) is None):
        actor_update(a, 0, 0, chord=chord and a.chord is None)
        return
    step = getattr(a, "punch", None)
    if step is not None:
        step += 1
        if step >= PUNCH_LOCK:
            a.punch = None
        else:
            a.punch = step
            _punch_boxes(a)
            return
    if punch:
        a.punch = 0
        a.walking = False
        a.vx = 0.0
        _punch_boxes(a)
        return
    actor_update(a, dir_x, dir_y)


def _punch_boxes(a: ActorSim) -> None:
    refresh_boxes(a, a.x, a.y)
    first, last = PUNCH_LIVE.get(a.character, PUNCH_LIVE[BLAZE])
    if first <= a.punch <= last:
        lo, hi = PUNCH_BOX_X.get(a.character, PUNCH_BOX_X[BLAZE])
        x, y, z = _hi(a.x), _hi(a.y), a.z
        if a.facing_left:
            lo, hi = -hi, -lo
        a.attack = (x + lo, x + hi, y - 8, y + 8, z - 60, z - 20)
        a.damage = PUNCH_DAMAGE
    else:
        a.attack = None
        a.damage = 0
    a.knockdown = False


# --- The actor, from its bytes -------------------------------------------------------------


def actor_from_bytes(data: bytes, *, cam_x: int) -> ActorSim:
    """The actor as his update reads it: position, the ``+$64``/``+$70`` boxes
    ``$4140`` cached, ``+$34``, availability."""

    character = data[0x50] if data[0x50] in (AXEL, ADAM, BLAZE) else BLAZE
    a = ActorSim(
        x=_s32(data, 0x10),
        y=_s32(data, 0x14),
        z=_s16(data, 0x18),
        facing_left=bool(data[0x09] & 0x02),
        character=character,
        walking=(data[0x30] & 0xFE) in range(0x06, 0x10),
        vx=_s32(data, 0x1C),
        chord=None,
        x_lo=float(cam_x + PLAYER_X_MIN_OFFSET),
        x_hi=float(cam_x + PLAYER_X_MAX_OFFSET),
        lane_lo=float(PLAYER_LANE_MIN),
        lane_hi=float(PLAYER_LANE_MAX),
        attack=None,
        body=None,
        damage=data[0x34],
        knockdown=bool(data[0x42] & 1),
        unavailable=bool(data[0x59] & 0x02) or bool(data[0x7C] & 0x01),
        untouchable=False,
        holding=_u16(data, 0x4C) != 0 or data[0x7C] == CODE_GRAB,
        latch=0,
        invulnerable=bool(data[0x4B] & 0x02),
        punch=None,
        blink=data[0x49] if data[0x4B] & 0x02 else 0,
    )
    a.chord = chord_step_from(character, data[0x30], data[0x0A], data[0x0D])
    words = [_s16(data, 0x64 + 2 * i) for i in range(6)]
    if any(words):
        a.attack = tuple(words)
    body = [_s16(data, 0x70 + 2 * i) for i in range(6)]
    if any(body):
        a.body = tuple(body)
    a.screen_y = _s16(data, 0x2C)  # type: ignore[attr-defined]
    return a


# --- Checking the model against a recording ------------------------------------------------

_FIELDS = ("x", "y", "z", "vx", "vy", "vz", "primary", "sub", "t54", "anim", "attack_id", "body_id", "hp")
MODELLED = frozenset(
    {
        PRIMARY_DECIDE, PRIMARY_RESUME, PRIMARY_WALK_IN, PRIMARY_LUNGE, PRIMARY_RETREAT,
        PRIMARY_GUN, PRIMARY_REPOSITION, PRIMARY_HURT, PRIMARY_KNOCKDOWN,
    }
)


def _signature(m: MrXSim) -> tuple:
    return tuple(getattr(m, f) for f in _FIELDS) + (m.frame, m.t56, m.shake)


def check_recording(rows: Sequence[dict], *, verbose: bool = False) -> dict:
    """Replay a ``tools/mr_x_lab.py`` recording: every frame on which his
    fields change is one of his updates, predicted from the frame before
    (both RNG draws tried, the one that matches kept) and compared field by
    field; every bullet's position the same. Also every hit on the actor, with
    what the model says landed it."""

    from collections import Counter

    checked: Counter[str] = Counter()
    mismatched: Counter[str] = Counter()
    contacts: Counter[str] = Counter()
    spawns_checked: Counter[str] = Counter()
    bullet_hits: Counter[str] = Counter()
    examples: list[dict] = []
    bullets_checked = bullet_mismatches = 0
    prev = None
    for row in rows:
        if prev is None or not row.get("mx") or not prev.get("mx"):
            prev = row
            continue
        cam = prev["cam"]
        before = MrXSim.from_bytes(bytes.fromhex(prev["mx"][0][1]), slot=prev["mx"][0][0], cam_x=cam)
        after = MrXSim.from_bytes(bytes.fromhex(row["mx"][0][1]), slot=row["mx"][0][0], cam_x=row["cam"])
        if _signature(before) == _signature(after):
            prev = row
            continue
        key = f"p{before.primary}s{before.sub}"
        if before.primary not in MODELLED:
            checked[f"{key}:skipped"] += 1
            prev = row
            continue
        actor = actor_from_bytes(bytes.fromhex(prev["p1"]), cam_x=cam)
        best = None
        for rng in (1, 0, 2, 3):
            sim = before.copy()
            spawned: list[BulletSim] = []
            outcome = mr_x_update(sim, actor.copy(), rng=rng, spawned=spawned)
            emit(sim)
            diffs = [f for f in _FIELDS if abs(getattr(sim, f) - getattr(after, f)) > 1e-6]
            if best is None or len(diffs) < len(best[0]):
                best = (diffs, sim, spawned, outcome)
            if not diffs:
                break
        diffs, sim, spawned, outcome = best
        # The contact his update made, against the player's +$7C/+$7E after.
        after_p1 = bytes.fromhex(row["p1"])
        his = 0xB900 + 0x80 * row["mx"][0][0]
        by_other = after_p1[0x7C] and int.from_bytes(after_p1[0x7E:0x80], "big") != his
        code = after_p1[0x7C] if not by_other else 0
        actual = {CODE_HIT: "HIT", CODE_STRUCK: "STRUCK", CODE_GRAB: "GRAB"}.get(code, "NONE")
        if by_other and outcome.name != "NONE":
            contacts["another object's contact first"] += 1
        elif outcome.name != "NONE" or actual != "NONE":
            contacts[f"{outcome.name}->{actual}"] += 1
        # The bullets it fired, against the slots that appeared.
        if spawned:
            # Any slot (a bullet that died this pass can hand its slot on),
            # this frame or the next pass's: a slot below his is set up on
            # the next pass, a whole update late.
            index = rows.index(row)
            new_slots = [
                BulletSim.from_bytes(bytes.fromhex(h), slot=i, cam_x=later["cam"])
                for later in rows[index : index + 4]
                for i, h in later.get("bu", ())
            ]
            for b in spawned:
                spawns_checked["fired"] += 1
                match = [
                    n for n in new_slots
                    if abs(n.x - b.x) < 1e-6 and abs(n.y - b.y) < 1e-6 and abs(n.z - b.z) < 1e-6
                    and abs(n.vx - b.vx) < 1e-6 and abs(n.vy - b.vy) < 1e-6
                ]
                if not match:
                    spawns_checked["unmatched"] += 1
        if diffs and after.primary == PRIMARY_KNOCKDOWN and before.primary != PRIMARY_KNOCKDOWN:
            # The respawn's forced reaction ($13082), not his own update.
            sim = before.copy()
            forced_knockdown(sim, actor)
            mr_x_update(sim, actor.copy(), spawned=[])
            emit(sim)
            diffs = [f for f in _FIELDS if abs(getattr(sim, f) - getattr(after, f)) > 1e-6]
            key = f"{key}:forced"
        his_address = 0xB900 + 0x80 * row["mx"][0][0]
        struck_by = int.from_bytes(after_p1[0x7E:0x80], "big")
        if actor.latch == 0 and after_p1[0x7C] and struck_by != his_address and outcome.name != "NONE":
            # Another object's contact came first in the pass (a helper's
            # punch): his own test skipped the actor.
            checked[f"{key}:other_contact"] += 1
            prev = row
            continue
        checked[key] += 1
        for f in diffs:
            mismatched[f"{key}:{f}"] += 1
        if diffs and len(examples) < 30:
            examples.append(
                {
                    "f": row["f"],
                    "state": key,
                    "diff": {f: [getattr(sim, f), getattr(after, f)] for f in diffs},
                }
            )
        prev = row
    # Bullets: each one's step against the next frame's bytes, by slot.
    by_frame = [r for r in rows if "bu" in r]
    for r0, r1 in zip(by_frame, by_frame[1:]):
        now = {i: bytes.fromhex(h) for i, h in r0["bu"]}
        nxt = {i: bytes.fromhex(h) for i, h in r1["bu"]}
        for i, data in now.items():
            if i not in nxt or data == nxt[i]:
                continue
            b = BulletSim.from_bytes(data, slot=i, cam_x=r0["cam"])
            if b.state != 1:
                continue
            a = actor_from_bytes(bytes.fromhex(r0["p1"]), cam_x=r0["cam"])
            hit = bullet_update(b, a)
            p1 = bytes.fromhex(r1["p1"])
            by = int.from_bytes(p1[0x7E:0x80], "big") == 0xB900 + 0x80 * i and p1[0x7C] == CODE_HIT
            if hit is Outcome.HIT or by:
                bullet_hits[f"{hit.name}->{'HIT' if by else 'NONE'}"] += 1
            if b.state != 1:
                continue
            got = BulletSim.from_bytes(nxt[i], slot=i, cam_x=r1["cam"])
            bullets_checked += 1
            if abs(b.x - got.x) > 1e-6 or abs(b.y - got.y) > 1e-6:
                bullet_mismatches += 1
    return {
        "updates_checked": sum(v for k, v in checked.items() if not k.endswith(":skipped")),
        "checked_by_state": dict(checked),
        "mismatches": dict(mismatched),
        "contacts": dict(contacts),
        "bullets_fired": dict(spawns_checked),
        "bullet_hits": dict(bullet_hits),
        "bullet_steps": bullets_checked,
        "bullet_mismatches": bullet_mismatches,
        "examples": examples if verbose or examples else [],
    }
