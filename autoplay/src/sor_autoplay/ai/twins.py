"""Onihime and Yasha (two type-``$58`` objects, round 5): the ROM model.

Everything the AI does against the twins is decided from here, as pure
functions of the tokens already in the context -- the arrangement
``antonio.py``, ``bongo.py`` and ``abadede.py`` have. This half is the model:
both twins' AI (``$158C4 onihime_yasha_update`` and the shared later-boss
states), the actor walking and throwing the rear attack (``$322A``), and the
contact test between them (``$AAA0``), update by update. ``twins_plan.py``
is the plan built on it.

What the ROM says (``ai-analysis/enemy-ai.md``, "Onihime and Yasha"):

Two AIs, one object type
    ``boss_link_same_type_pair`` gives the twin that links second pair role 2
    and copies the role into ``+$7B``: role 2 starts on the **grab path**
    (``+$7B`` bit 1), role 1 on the **approach path**. Both share the state
    table at ``$158D8`` and every helper below.
Everything runs at 30 Hz
    Players update on one frame, objects on the next (``$AD8E``); every rate
    here is per update.
The approach twin never walks into anyone
    State 1, approach path: tactical 0 idles ten updates, tactical 1 chases
    at 4 px an update and keeps the lane gap at the edge of 32 (``$17954``:
    toward the target's lane at 1 px while 32 or more apart, *away* at 1 px
    inside 32). Whenever the target is inside 96 px on X it **backflips
    away** (``$15A64`` -> ``$15ABA``: 3 updates of wind-up, then 4 px an
    update away, 1 px an update toward the target's lane, ``v_z`` -7.25 and
    gravity 0.75 -- 21 updates, 84 px), and its own attack box in state 1 is
    cancelled on contact (``$159F8`` clears the target's ``+$7C``).
    Its one attack is the **flying kick** (state 2, ``$15D0C``): committed
    with the target 16-31 lanes off and inside 112 px (``$15A0E``), from a
    walk at once, from the idle after 10 updates of crouch (animation
    ``$28``); then 2.667 px an update at the target, ``(target lane - its
    lane) / 16`` an update on the lane (so it crosses the target's lane on
    its 16th update and keeps going), ``v_z`` -10, gravity 0.75: 28 updates
    of flight. Animation ``$2C`` from update 11 of the flight; the kick box
    (``$8B``, 3..49 ahead, 38..6 above its feet) from update 19.
The grab twin walks straight in
    Grab path: tactical 1 walks at 2 px an update and homes the lane at
    4/2/1/0 px (``$1797E``). Its walking box (``$8F``, 0..19 ahead) on the
    target's body **is the grab** (``$15B2A``) and the throw that follows is
    32 damage. It jumps in (``$15C72``: 3 px an update, ``v_z`` -10) only at
    a target that **faces it** -- inside 64 px, or 64-111 px with the target
    on the floor and walking away -- and backflips away from a target in a
    hit reaction (``$15BE8``).
A rear attack knocks a twin down
    The chord's frame carries hit property 1 (``$423C``), which ``$AAA0``
    ORs into the twin's ``+$37``: ``boss_apply_pending_damage`` then throws
    it 5 px an update away from the attacker with ``v_z`` -5, gravity 1.0,
    one bounce (``v_z`` -3), 18 updates of travel -- **90 px** -- and 30
    updates in state 3, then 8 getting up (state 5). No box in any of it.
    The damage lands on the twin's update *after* the contact.
Grab beats hit, strike beats both (``$AAA0``)
    The player's attack box against the twin's body is tested first: with
    damage out (``+$34``) it is the strike and the twin's own box is not
    tested at all that update; with none it is the player's grab. Every
    compare is inclusive on all three axes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterable, Sequence

__all__ = [
    "ActorSim",
    "Outcome",
    "TwinSim",
    "actor_update",
    "check_recording",
    "object_pass",
]

TWIN_TYPE = 0x58

# --- The shape table both the twins and the players use ($1ABA8) ----------------
#
# (x0, x1, lane0, lane1, z0, z1) about the object's origin; z grows downward, so
# a negative z is above the feet. Only the ids the twins and the three players
# can show in this fight.
SHAPES: dict[int, tuple[int, int, int, int, int, int]] = {
    # Twins (set $2DD70), and Blaze, whose sprite they share.
    0x4F: (2, 12, -8, 8, -48, 0), 0x50: (-12, -2, -8, 8, -48, 0),
    0x51: (-5, 5, -8, 8, -48, 0), 0x52: (-5, 5, -8, 8, -48, 0),
    0x65: (-13, -6, -8, 8, -52, -24), 0x66: (6, 13, -8, 8, -52, -24),
    0x6B: (6, 14, -8, 8, -44, 0), 0x6C: (-14, -6, -8, 8, -44, 0),
    0x6D: (6, 18, -8, 8, -48, 0), 0x6E: (-16, -4, -8, 8, -48, 0),
    0x6F: (6, 13, -8, 8, -48, 0), 0x70: (-13, -6, -8, 8, -48, 0),
    0x73: (-13, 13, -8, 8, 0, 0), 0x74: (-13, 13, -8, 8, 0, 0),
    0x79: (8, 16, -8, 8, -42, 0), 0x7A: (-16, -8, -8, 8, -42, 0),
    0x7B: (-1, 7, -8, 8, -51, -28), 0x7C: (-7, 1, -8, 8, -51, -28),
    0x7D: (-8, 3, -8, 8, -48, -28), 0x7E: (-3, 8, -8, 8, -48, -28),
    0x7F: (-6, 2, -8, 8, -44, -28), 0x80: (-2, 6, -8, 8, -44, -28),
    0x81: (-4, 5, -8, 8, -43, -31), 0x82: (-5, 4, -8, 8, -43, -31),
    0x8B: (3, 49, -8, 8, -38, -6), 0x8C: (-43, 3, -8, 8, -38, -6),
    0x8F: (0, 19, -8, 8, -48, 0), 0x90: (-19, 0, -8, 8, -48, 0),
    # Blaze's rear attack (animation $24/$26).
    0x75: (-13, -5, -8, 8, -44, -28), 0x76: (5, 13, -8, 8, -44, -28),
    0x77: (-7, -2, -8, 8, -44, -28), 0x78: (2, 7, -8, 8, -44, -28),
    0x8D: (-53, -5, -8, 8, -64, -24), 0x8E: (5, 53, -8, 8, -64, -24),
    # Axel.
    0x01: (0, 13, -8, 8, -51, 0), 0x02: (-3, 7, -8, 8, -50, 0),
    0x04: (-13, 0, -8, 8, -51, 0), 0x05: (-7, 3, -8, 8, -50, 0),
    0x06: (-7, 3, -8, 8, -50, 0), 0x15: (-11, 0, -8, 8, -50, 0),
    0x16: (11, 22, -8, 8, -50, 0), 0x17: (-7, 3, -8, 8, -52, 0),
    0x18: (-3, 7, -8, 8, -52, 0), 0x49: (-40, -8, -8, 8, -72, -40),
    0x4A: (8, 40, -8, 8, -72, -40), 0x4D: (0, 16, -8, 8, -57, 0),
    0x4E: (-16, 0, -8, 8, -57, 0),
    # Adam.
    0x91: (-5, 7, -8, 8, -53, 0), 0x92: (-7, 5, -8, 8, -53, 0),
    0x93: (-5, 4, -8, 8, -51, 0), 0x94: (-4, 5, -8, 8, -51, 0),
    0xA9: (11, 20, -8, 8, -53, -35), 0xAA: (-20, -11, -8, 8, -53, -35),
    0xAB: (11, 20, -8, 8, -55, -37), 0xAC: (-20, -11, -8, 8, -55, -37),
    0xCF: (0, 20, -8, 8, -60, 0), 0xD0: (-20, 0, -8, 8, -60, 0),
    0xDF: (-42, 14, -8, 8, -43, -17), 0xE0: (-12, 44, -8, 8, -43, -33),
    0xA3: (2, 16, -8, 8, -40, 0), 0xA4: (-16, -2, -8, 8, -40, 0),
}

# --- The twins' animations (set $2DD70) ------------------------------------------
#
# ``+$08`` is a byte offset into the set's word table, four per mirrored pair;
# bit 1 is the left-facing member. Value: (per-frame updates, [(attack, body)]).
# A duration of 0 is a static frame (``$B0C8``'s countdown wraps at 256).
TWIN_ANIMS: dict[int, tuple[int, tuple[tuple[int, int], ...]]] = {
    0x00: (0, ((0x8F, 0x4F),)),
    0x02: (0, ((0x90, 0x50),)),
    0x04: (5, ((0x8F, 0x51),) * 4),
    0x06: (5, ((0x90, 0x52),) * 4),
    0x08: (10, ((0, 0),) * 2),
    0x0A: (10, ((0, 0),) * 2),
    0x0C: (0, ((0, 0x6D),)),
    0x0E: (0, ((0, 0x6E),)),
    0x10: (0, ((0, 0x65),)),
    0x12: (0, ((0, 0x66),)),
    0x14: (0, ((0, 0),)),
    0x16: (0, ((0, 0),)),
    0x18: (0, ((0, 0),)),
    0x1A: (0, ((0, 0),)),
    0x1C: (10, ((0, 0),) * 3),
    0x1E: (10, ((0, 0),) * 3),
    0x20: (0, ((0, 0x6D),)),
    0x22: (0, ((0, 0x6E),)),
    0x24: (0, ((0, 0x7B),)),
    0x26: (0, ((0, 0x7C),)),
    0x28: (0, ((0, 0x79),)),
    0x2A: (0, ((0, 0x7A),)),
    0x2C: (4, ((0, 0x7D), (0, 0x7F), (0x8B, 0x81), (0x8B, 0x81))),
    0x2E: (4, ((0, 0x7E), (0, 0x80), (0x8C, 0x82), (0x8C, 0x82))),
    0x30: (0, ((0, 0x6F),)),
    0x32: (0, ((0, 0x70),)),
    0x34: (0, ((0, 0x6B),)),
    0x36: (0, ((0, 0x6C),)),
    0x38: (2, ((0, 0),) * 11),
    0x3A: (2, ((0, 0),) * 11),
    0x3C: (2, ((0, 0),) * 32),
    0x3E: (2, ((0, 0),) * 32),
    0x40: (2, ((0, 0),) * 10 + ((0x8F, 0),) * 2),
    0x42: (2, ((0, 0),) * 10 + ((0x90, 0),) * 2),
    0x44: (2, ((0x8F, 0),) * 2 + ((0x73, 0),) * 10 + ((0x8F, 0),)),
    0x46: (2, ((0x90, 0),) * 2 + ((0x74, 0),) * 10 + ((0x90, 0),)),
}
ANIM_MIRROR = 0x02
ANIM_IDLE = 0x00
ANIM_WALK = 0x04
ANIM_HIT = 0x08
ANIM_GET_UP = 0x1C
ANIM_LEAP = 0x24  # flying kick, rising
ANIM_CROUCH = 0x28  # flying kick wind-up, and its landing
ANIM_KICK = 0x2C  # flying kick, falling (kick box on frames 2-3)
ANIM_FLIP = 0x40  # the backflip (no body box at all)
ANIM_JUMP_IN = 0x44  # the grab twin's jump-in (no body box at all)

# --- Their state machine ----------------------------------------------------------

PRIMARY_INIT = 0x00
PRIMARY_ACTIVE = 0x01
PRIMARY_COMMIT = 0x02  # flying kick, or the throw of a grabbed player
PRIMARY_REACTION = 0x03  # hitstun / knockdown flight ($163D0)
PRIMARY_HELD = 0x04
PRIMARY_GET_UP = 0x05  # also the lethal gate ($164FC)
PRIMARY_POLICE = 0x0A

MODE_GRAB_BIT = 0x02  # +$7B bit 1

# $15A0E: the flying kick's commit window.
COMMIT_LANE_MIN = 0x10
COMMIT_LANE_MAX = 0x20  # exclusive
COMMIT_DX = 0x70  # exclusive
FLIP_DX = 0x60  # $15A64: backflip inside this
IDLE_UPDATES = 10  # $15A7E
CHASE_SPEED = 4.0  # $1792C
CHASE_LANE_GAP = 0x20  # $17954
FLIP_WINDUP = 4  # $15ABA launches on +$78 == 4
FLIP_SPEED = 4.0  # $17942, away from the target
FLIP_VZ = -7.25  # $FFF8C000
GRAVITY = 0.75  # $C000
KICK_WINDUP = 0x0A  # $15D0C launches on +$78 == $0A (9 skipped from a walk)
KICK_ANIM_AT = 0x14
KICK_REINIT_AT = 0x2A
KICK_END_AT = 0x2C
KICK_SPEED = 0x0002AAAA / 65536.0
KICK_VZ = -10
GRAB_WALK_SPEED = 2.0  # $17924
JUMP_IN_SPEED = 3.0  # $17928
JUMP_IN_VZ = -10.0  # $FFF60000
JUMP_IN_NEAR_DX = 0x40
JUMP_IN_FAR_DX = 0x70
JUMP_IN_HOP = 0x1C  # $15CE0: 28 px up on frame 2, back on frame 12
LEAP_STAGGERED_DX = 0x90  # $15BE8
LEAP_SCREEN_MIN = 0x80  # exclusive, signed
LEAP_SCREEN_MAX = 0x1C0  # exclusive
BOSS_LANE_MAX = 0x70  # $17AB8
SCREEN_BIAS = 0x80

# boss_apply_pending_damage ($17C36) and state 3 ($163D0).
HITSTUN_UPDATES = 8
KNOCKDOWN_UPDATES = 0x1E
KNOCKBACK_VX = 5.0
KNOCKBACK_VZ = -5.0
KNOCKDOWN_GRAVITY = 1.0
BOUNCE_VZ = -3.0
GET_UP_UPDATES = 8
DEATH_UPDATES = 0x6E
SHAKE_X = 2

# $AAA0: a player's strike registers only on a twin whose +$28 is in this band.
STRIKE_SCREEN_MIN = 0x78
STRIKE_SCREEN_MAX = 0x1C8  # exclusive
GRAB_Z = 8  # $AADC: a player's grab needs the heights within 8

# --- The players --------------------------------------------------------------------

AXEL, ADAM, BLAZE = 0, 1, 2
# Standing and walking box ids (right-facing, left-facing): (attack, body).
_IDLE_BOXES = {
    AXEL: ((0, 0x01), (0, 0x04)),
    ADAM: ((0, 0x91), (0, 0x92)),
    BLAZE: ((0, 0x4F), (0, 0x50)),
}
_WALK_BOXES = {
    AXEL: ((0x4D, 0x02), (0x4E, 0x06)),
    ADAM: ((0xCF, 0x93), (0xD0, 0x94)),
    BLAZE: ((0x8F, 0x51), (0x90, 0x52)),
}
# The rear attack, update by update from the press (``$322A``), as measured in
# lockstep (``tools/twins_lab.py``) and read from ``$3A30``'s timing rows and
# ``$423C``'s damage bytes: (right-facing attack, body, left-facing attack,
# body, height above the floor, damage). Axel and Blaze play animation $24 in
# place -- Blaze 3 + 8 + 3 updates (row 26), Axel 1 + 5 + 2 (row 8). Adam's
# chord is a hop: action $22 crouches 5 updates, $24 leaves the floor at v_z
# -6.25 under 0.90625 of gravity and puts its box out 10 updates after the
# press for 9 (frames 1-2), and the landing ($14) locks 5 more. Every live
# update carries hit property 1: a knockdown.
def _hop(steps: int, start: float = -6.25, gravity: float = 0.90625) -> list[float]:
    heights, z, vz = [], 0.0, start
    for _ in range(steps):
        z += vz
        heights.append(min(z, 0.0))
        vz += gravity
    return heights


_ADAM_HOP = _hop(14)
CHORD_SCHEDULES: dict[int, tuple[tuple[int, int, int, int, float, int], ...]] = {
    BLAZE: (
        ((0, 0x75, 0, 0x76, 0.0, 0),) * 3
        + ((0x8D, 0x77, 0x8E, 0x78, 0.0, 2),) * 8
        + ((0, 0x75, 0, 0x76, 0.0, 0),) * 3
    ),
    AXEL: (
        ((0, 0x15, 0, 0x16, 0.0, 0),) * 1
        + ((0x49, 0x17, 0x4A, 0x18, 0.0, 3),) * 5
        + ((0, 0x15, 0, 0x16, 0.0, 0),) * 2
    ),
    ADAM: (
        ((0, 0xA3, 0, 0xA4, 0.0, 0),) * 5
        + tuple((0, 0xA9, 0, 0xAA, _ADAM_HOP[i], 0) for i in range(5))
        + tuple((0xDF, 0xAB, 0xE0, 0xAC, _ADAM_HOP[5 + i], 3) for i in range(9))
        + ((0, 0xA3, 0, 0xA4, 0.0, 0),) * 5
    ),
}


def chord_schedule(character: int):
    return CHORD_SCHEDULES.get(character, CHORD_SCHEDULES[BLAZE])


def chord_live_steps(character: int) -> tuple[int, int]:
    """(first, last) update after the press with the box out."""

    live = [i for i, step in enumerate(chord_schedule(character)) if step[5]]
    return live[0], live[-1]



# $3614's walk tables, per update: (straight X, diagonal X, diagonal lane,
# straight lane).
WALK_SPEEDS = {
    AXEL: (3.0, 2.25, 2.0, 2.375),
    ADAM: (2.5, 1.75, 1.25, 1.5),
    BLAZE: (3.25, 3.25, 1.625, 1.625),
}
# $43AA: the camera clamp (cam + $20 .. cam + $120) and the lane band.
PLAYER_X_MIN_OFFSET = 0x20
PLAYER_X_MAX_OFFSET = 0x120
PLAYER_LANE_MIN = 2
PLAYER_LANE_MAX = 0x70

# The player's +$7C contact codes $AA22 writes.
CODE_HIT = 1
CODE_STRUCK = 2
CODE_GRABBED_BOSS = 3


def _hi(value: float) -> int:
    """The high word of a 16.16 value, as ``move.w`` reads it."""

    return math.floor(value)


def _fixed(value: float) -> int:
    return round(value * 65536)


def _unfixed(value: int) -> float:
    return value / 65536.0


class Outcome(Enum):
    NONE = auto()
    HIT = auto()  # the flying kick landed on the actor
    GRABBED = auto()  # the grab twin took the actor (the throw is 32 damage)
    STRUCK = auto()  # the actor's rear attack registered on this twin
    HELD = auto()  # the actor's walking box took this twin into a hold


def box(box_id: int, x: int, y: int, z: int) -> tuple[int, int, int, int, int, int] | None:
    shape = SHAPES.get(box_id)
    if shape is None or not box_id:
        return None
    return (x + shape[0], x + shape[1], y + shape[2], y + shape[3], z + shape[4], z + shape[5])


def overlaps(a: tuple, b: tuple) -> bool:
    """``$AB88`` on all three axes: inclusive."""

    return a[0] <= b[1] and a[1] >= b[0] and a[2] <= b[3] and a[3] >= b[2] and a[4] <= b[5] and a[5] >= b[4]


# --- The actor ------------------------------------------------------------------


class ActorSim:
    """The actor as a twin's update reads it: position, boxes, availability.

    ``chord`` is the rear attack's update since the press
    (``CHORD_SCHEDULES``), or None when free.
    ``attack``/``body`` are the boxes ``$4140`` cached at the end of its last
    update -- before ``$43AA``'s clamp, so at a clamp they stand one step
    past where the actor does.
    """

    __slots__ = (
        "x", "y", "z", "facing_left", "character", "walking", "vx", "chord",
        "x_lo", "x_hi", "lane_lo", "lane_hi", "attack", "body", "damage",
        "knockdown", "unavailable", "untouchable", "holding", "latch", "invulnerable",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))

    def copy(self) -> ActorSim:
        other = ActorSim.__new__(ActorSim)
        for name in self.__slots__:
            setattr(other, name, getattr(self, name))
        return other

    @classmethod
    def standing(
        cls,
        *,
        x: float,
        y: float,
        z: int,
        facing_left: bool,
        character: int,
        cam_x: int,
        walking: bool = False,
        chord: tuple[int, int] | None = None,
        vx: float = 0.0,
    ) -> ActorSim:
        a = cls(
            x=float(x), y=float(y), z=int(z), facing_left=facing_left, character=character,
            walking=walking, vx=vx, chord=chord,
            x_lo=float(cam_x + PLAYER_X_MIN_OFFSET), x_hi=float(cam_x + PLAYER_X_MAX_OFFSET),
            lane_lo=float(PLAYER_LANE_MIN), lane_hi=float(PLAYER_LANE_MAX),
            attack=None, body=None, damage=0, knockdown=False,
            unavailable=False, untouchable=False, holding=False, latch=0, invulnerable=False,
        )
        refresh_boxes(a, a.x, a.y)
        return a


def chord_damage(character: int) -> int:
    return max(step[5] for step in chord_schedule(character))


def refresh_boxes(a: ActorSim, box_x: float, box_y: float) -> None:
    """``$4140``: the boxes of the frame the actor is on, where it stands."""

    left = 1 if a.facing_left else 0
    z = a.z
    if a.chord is not None:
        step = chord_schedule(a.character)[a.chord]
        attack_id, body_id = (step[2], step[3]) if a.facing_left else (step[0], step[1])
        z = _hi(a.z + step[4])
        a.damage = step[5]
        a.knockdown = step[5] > 0
    elif a.walking:
        attack_id, body_id = _WALK_BOXES.get(a.character, _WALK_BOXES[BLAZE])[left]
        a.damage = 0
        a.knockdown = False
    else:
        attack_id, body_id = _IDLE_BOXES.get(a.character, _IDLE_BOXES[BLAZE])[left]
        a.damage = 0
        a.knockdown = False
    x, y = _hi(box_x), _hi(box_y)
    a.attack = box(attack_id, x, y, z) if attack_id else None
    # $4140 caches no body at all while +$4B bit 1 is set (the blink after a
    # knockdown or a respawn): nothing lands on it.
    a.body = box(body_id, x, y, z) if body_id and not a.invulnerable else None


def actor_update(a: ActorSim, dir_x: int, dir_y: int, chord: bool = False) -> None:
    """One update of the actor: the rear attack's schedule, or the stick.

    ``chord`` presses B+C on this update; it starts only from the ground
    control (free, or on the update the previous chord hands back). The last
    update of a schedule falls straight into the ground control in the same
    update (``$20EC`` -> ``$2CD2``).
    """

    if a.chord is not None:
        step = a.chord + 1
        if step >= len(chord_schedule(a.character)):
            a.chord = None
        else:
            a.chord = step
            refresh_boxes(a, a.x, a.y)
            return
    if chord:
        a.chord = 0
        a.walking = False
        a.vx = 0.0
        refresh_boxes(a, a.x, a.y)
        return
    if dir_x:
        a.facing_left = dir_x < 0
    a.walking = bool(dir_x or dir_y)
    straight_x, diagonal_x, diagonal_y, straight_y = WALK_SPEEDS.get(a.character, WALK_SPEEDS[BLAZE])
    if dir_x and dir_y:
        step_x, step_y = diagonal_x, diagonal_y
    else:
        step_x, step_y = straight_x, straight_y
    a.vx = dir_x * step_x
    x = a.x + dir_x * step_x
    y = a.y + dir_y * step_y
    refresh_boxes(a, x, y)
    a.x = _clamp_word(x, a.x_lo, a.x_hi)
    a.y = _clamp_word(y, a.lane_lo, a.lane_hi)


def _clamp_word(value: float, lo: float, hi: float) -> float:
    """``$43AA``: compares and rewrites the integer word only -- the fraction
    survives the clamp."""

    whole = _hi(value)
    if whole < lo:
        return lo + (value - whole)
    if whole > hi:
        return hi + (value - whole)
    return value


# --- The twins --------------------------------------------------------------------


class TwinSim:
    """One twin, reduced to what its own update reads and writes."""

    __slots__ = (
        "slot", "x", "y", "z", "vx", "vy", "vz", "ground", "primary", "tac", "t78",
        "anim", "frame", "countdown", "reload", "shown_attack", "shown_body", "screen_x",
        "cam_x", "mode", "toggle", "role", "unavailable", "f4b", "pending",
        "f37", "r62", "r63", "f66", "f6d", "hp", "left", "above", "d50", "d52",
        "partner", "gone",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))

    def copy(self) -> TwinSim:
        other = TwinSim.__new__(TwinSim)
        for name in self.__slots__:
            setattr(other, name, getattr(self, name))
        return other

    @classmethod
    def from_bytes(cls, data: bytes, *, slot: int, cam_x: int) -> TwinSim:
        """From the object's own 128 bytes (the lab's recordings)."""

        def s32(offset: int) -> float:
            return int.from_bytes(data[offset : offset + 4], "big", signed=True) / 65536.0

        def u32(offset: int) -> float:
            return int.from_bytes(data[offset : offset + 4], "big") / 65536.0

        def s16(offset: int) -> int:
            return int.from_bytes(data[offset : offset + 2], "big", signed=True)

        return cls(
            slot=slot,
            x=u32(0x10), y=u32(0x14), z=u32(0x18),
            vx=s32(0x1C), vy=s32(0x20), vz=s32(0x24),
            ground=u32(0x4C),
            primary=data[0x30], tac=data[0x67], t78=data[0x78],
            anim=int.from_bytes(data[0x08:0x0A], "big"), frame=data[0x0A], countdown=data[0x0D],
            reload=data[0x0C],
            shown_attack=data[0x02], shown_body=data[0x03],
            screen_x=s16(0x28), cam_x=cam_x,
            mode=data[0x7B], toggle=data[0x7A], role=data[0x5D],
            unavailable=data[0x77], f4b=data[0x4B], pending=data[0x6C],
            f37=data[0x37], r62=data[0x62], r63=data[0x63], f66=data[0x66], f6d=data[0x6D],
            hp=s16(0x32), left=bool(data[0x60]), above=bool(data[0x61]),
            d50=int.from_bytes(data[0x50:0x52], "big"), d52=int.from_bytes(data[0x52:0x54], "big"),
            partner=None, gone=False,
        )


def _duration(anim: int) -> int:
    return TWIN_ANIMS.get(anim, (0, ((0, 0),)))[0]


def set_anim(t: TwinSim, anim: int, left: bool) -> None:
    """``$1588A`` -> ``$B1A2``: from frame 0, countdown reseeded, boxes latched."""

    t.anim = anim | (ANIM_MIRROR if left else 0)
    t.frame = 0
    t.countdown = t.reload = _duration(t.anim)
    frames = TWIN_ANIMS.get(t.anim, (0, ((0, 0),)))[1]
    t.shown_attack, t.shown_body = frames[0]


def reinit_anim(t: TwinSim) -> None:
    """``$15898``: the current animation from frame 0."""

    set_anim(t, t.anim & ~ANIM_MIRROR, bool(t.anim & ANIM_MIRROR))


def emit(t: TwinSim) -> None:
    """The renderer's tail for a twin (``$AF46`` / ``$B0B6``): ``+$28``, this
    frame's boxes, then the frame timer. Its ``+$01`` bit 3 skips the cull, so
    this runs on or off screen."""

    t.screen_x = _hi(t.x) - t.cam_x + SCREEN_BIAS
    frames = TWIN_ANIMS.get(t.anim, (0, ((0, 0),)))[1]
    index = t.frame if t.frame < len(frames) else 0
    t.shown_attack, t.shown_body = frames[index]
    t.countdown = (t.countdown - 1) & 0xFF
    if t.countdown == 0:
        # The reload is +$0C, written when the animation was started -- not
        # the current animation's own: state 3 adds $0C and 4 to +$08 in
        # flight and never restarts it.
        t.countdown = t.reload
        t.frame += 1
        if t.frame >= len(frames):
            t.frame = 0


def integrate(t: TwinSim) -> None:
    """``$17AB8``: X free, lane clamped to ``$00..$70``, height not below the
    floor."""

    t.x += t.vx
    y = t.y + t.vy
    t.y = 0.0 if y < 0 else (float(BOSS_LANE_MAX) if y >= BOSS_LANE_MAX else y)
    z = t.z + t.vz
    t.z = t.ground if z > t.ground else z


def _measure(t: TwinSim, a: ActorSim, *, face: bool, x_only: bool = False) -> None:
    """``$17B0C`` (``face``: the facing bit follows the target) / ``$17A94``
    and ``$17B2C``."""

    dx = _hi(a.x) - _hi(t.x)
    t.left = dx < 0
    t.d50 = abs(dx)
    if face:
        t.anim = (t.anim & ~ANIM_MIRROR) | (ANIM_MIRROR if t.left else 0)
    if not x_only:
        dy = _hi(a.y) - _hi(t.y)
        t.above = dy < 0
        t.d52 = abs(dy)


def _on_floor(t: TwinSim) -> bool:
    return _hi(t.z) == _hi(t.ground)


def contact(t: TwinSim, a: ActorSim, margin: int = 0) -> int:
    """``$AA34`` / ``$AAA0`` for this twin against the actor: the ``d7`` it
    returns (0 none, 1 its box on the actor, 2 the actor's strike on it, 3 the
    actor's grab on it)."""

    if a.untouchable or (a.latch & 1):
        return 0
    body_box = box(t.shown_body, _hi(t.x), _hi(t.y), _hi(t.z)) if t.shown_body else None
    if a.attack is not None and body_box is not None and overlaps(body_box, a.attack):
        if a.damage:
            if STRIKE_SCREEN_MIN <= t.screen_x < STRIKE_SCREEN_MAX:
                return 2
            return 0
        if a.holding or a.latch == CODE_GRABBED_BOSS:
            return 0
        if abs(a.z - _hi(t.z)) > GRAB_Z:
            return 0
        return 3
    if not t.shown_attack or a.body is None:
        return 0
    attack_box = box(t.shown_attack, _hi(t.x), _hi(t.y), _hi(t.z))
    if attack_box is not None and margin:
        # The planner's conservatism: its box a little wider and a lane or
        # two deeper than the ROM's, so a plan never lives on the boundary.
        x0, x1, y0, y1, z0, z1 = attack_box
        attack_box = (x0 - margin, x1 + margin, y0 - margin, y1 + margin, z0 - margin, z1 + margin)
    if attack_box is not None and overlaps(attack_box, a.body):
        return 1
    return 0


def _apply_pending_damage(t: TwinSim, a: ActorSim) -> bool:
    """``boss_apply_pending_damage`` ($17C36). True when it took the update."""

    if t.f6d:
        t.pending = 0
        return False
    damage = t.pending
    if not damage:
        return False
    t.vx = t.vy = t.vz = 0.0
    t.pending = 0
    t.hp -= damage
    knock = True
    if t.hp > 0:
        if t.f37 & 1:
            t.f37 &= ~1
        elif _on_floor(t):
            knock = False
    if knock and t.f66:
        t.f66 = 0
        t.f37 |= 2
    if knock:
        t.r62 = KNOCKDOWN_UPDATES
        t.vx = -KNOCKBACK_VX
        t.vz = KNOCKBACK_VZ
        t.r63 = 2
    else:
        t.r62 = HITSTUN_UPDATES
    t.primary = PRIMARY_REACTION
    t.tac = 0
    anim = ANIM_HIT
    if _hi(a.x) - _hi(t.x) < 0:
        anim |= ANIM_MIRROR
        t.vx = -t.vx
    if t.f66 & 4:
        anim ^= ANIM_MIRROR
    t.anim = anim
    integrate(t)
    reinit_anim(t)
    return True


def _chase_lane(t: TwinSim) -> float:
    """``$17954``: toward the target's lane from 32 out, away inside it."""

    speed = 1.0 if t.d52 >= CHASE_LANE_GAP else -1.0
    return -speed if t.above else speed


def _home_lane(t: TwinSim) -> float:
    """``$1797E``: toward the target's lane, 4/2/1/0 px by the gap."""

    d = t.d52
    speed = 4.0 if d >= 0x20 else (2.0 if d >= 0x10 else (1.0 if d >= 0x08 else 0.0))
    return -speed if t.above else speed


def _toward(t: TwinSim, speed: float) -> float:
    return -speed if t.left else speed


def _flip(t: TwinSim) -> None:
    """``$15ABA``: the backflip (approach tactical 2, grab tactical 3)."""

    t.t78 = (t.t78 + 1) & 0xFF
    if t.t78 < FLIP_WINDUP:
        return
    if t.t78 == FLIP_WINDUP:
        t.vy = -1.0 if t.above else 1.0
        t.vz = FLIP_VZ
        t.vx = FLIP_SPEED if t.left else -FLIP_SPEED
        integrate(t)
        return
    _fall(t)


def _fall(t: TwinSim) -> None:
    """``loc_15AF4``: airborne under gravity, or landed back in state 1."""

    if not _on_floor(t):
        t.vz += GRAVITY
        integrate(t)
        return
    t.vx = t.vy = t.vz = 0.0
    t.t78 = 0
    t.tac = 0
    t.primary = PRIMARY_ACTIVE
    set_anim(t, ANIM_IDLE, t.left)


def _arm_flip(t: TwinSim, *, tactical: int) -> None:
    t.t78 = 0
    t.tac = tactical
    set_anim(t, ANIM_FLIP, t.left)


def _approach_path(t: TwinSim, a: ActorSim, d7: int) -> Outcome:
    if d7 == 1:
        a.latch = 0  # $159F8: its box on the target in state 1 is no hit
    if t.f4b & 1:
        t.f4b &= ~1
        if t.role == 0:
            t.mode |= MODE_GRAB_BIT
            return Outcome.NONE
    if (
        not t.unavailable
        and t.tac != 2
        and COMMIT_LANE_MIN <= t.d52 < COMMIT_LANE_MAX
        and t.d50 < COMMIT_DX
    ):
        t.tac = 0
        t.primary = PRIMARY_COMMIT
        if t.anim >= 4:
            t.t78 = 9
            return Outcome.NONE
        t.t78 = 0
        set_anim(t, ANIM_CROUCH, t.left)
        return Outcome.NONE
    if t.tac == 0:
        if t.d50 < FLIP_DX:
            _arm_flip(t, tactical=2)
            return Outcome.NONE
        t.t78 = (t.t78 + 1) & 0xFF
        if t.t78 >= IDLE_UPDATES:
            t.t78 = 0
            t.tac = 1
            set_anim(t, ANIM_WALK, t.left)
            return Outcome.NONE
        if t.anim >= 4:
            set_anim(t, ANIM_IDLE, t.left)
        return Outcome.NONE
    if t.tac == 1:
        if t.d50 < FLIP_DX:
            _arm_flip(t, tactical=2)
            return Outcome.NONE
        t.vx = _toward(t, CHASE_SPEED)
        t.vy = _chase_lane(t)
        integrate(t)
        return Outcome.NONE
    _flip(t)
    return Outcome.NONE


def _leap_at_staggered(t: TwinSim) -> bool:
    """``$15BE8``: a backflip away from a target that cannot be taken."""

    if not t.unavailable or t.d50 >= LEAP_STAGGERED_DX:
        return False
    if not LEAP_SCREEN_MIN < t.screen_x < LEAP_SCREEN_MAX:
        return False
    _arm_flip(t, tactical=3)
    return True


def _jump_in(t: TwinSim, a: ActorSim) -> bool:
    """``$15C72``: the grab twin jumps at a target that faces it."""

    if t.d50 >= JUMP_IN_NEAR_DX:
        if _hi(t.ground) != a.z:
            return False
        if t.d50 >= JUMP_IN_FAR_DX:
            return False
        moving_left = _hi(a.vx) < 0
        if t.left:
            if not moving_left:
                return False
        elif moving_left:
            return False
    if t.left:
        if a.facing_left:
            return False
    elif not a.facing_left:
        return False
    t.tac = 2
    t.t78 = 0
    t.vz = JUMP_IN_VZ
    t.vx = _toward(t, JUMP_IN_SPEED)
    integrate(t)
    set_anim(t, ANIM_JUMP_IN, t.left)
    return True


def _grab_path(t: TwinSim, a: ActorSim, d7: int) -> Outcome:
    if d7 == 1:
        if t.unavailable or t.tac == 3:
            a.latch = 0
        elif _on_floor(t) or a.z == _hi(t.ground):
            t.primary = PRIMARY_COMMIT
            t.tac = 0
            return Outcome.GRABBED
        else:
            a.latch = 0
    if t.tac == 0:
        if t.f4b & 1:
            t.f4b &= ~1
            if t.role == 0:
                t.mode &= ~MODE_GRAB_BIT
                return Outcome.NONE
        if _leap_at_staggered(t) or _jump_in(t, a):
            return Outcome.NONE
        if t.unavailable:
            return Outcome.NONE
        was = t.toggle & 1
        t.toggle ^= 1
        if not was or t.role != 0:
            t.tac = 1
            set_anim(t, ANIM_WALK, t.left)
            return Outcome.NONE
        t.mode &= ~MODE_GRAB_BIT
        return Outcome.NONE
    if t.tac == 1:
        if _leap_at_staggered(t) or _jump_in(t, a):
            return Outcome.NONE
        t.vx = _toward(t, GRAB_WALK_SPEED)
        t.vy = _home_lane(t)
        integrate(t)
        return Outcome.NONE
    if t.tac == 2:
        if t.countdown == 2:
            if t.frame == 2:
                t.z -= JUMP_IN_HOP
            elif t.frame == 12:
                t.z += JUMP_IN_HOP
        _fall(t)
        return Outcome.NONE
    _flip(t)
    return Outcome.NONE


def _code(t: TwinSim, a: ActorSim, d7: int) -> None:
    """``$17B52``'s bookkeeping for the code ``$AAA0`` returned."""

    if d7 == 2:
        if not t.r62 and not t.f6d:
            t.pending = a.damage
            t.f37 = (t.f37 & ~1) | (1 if a.knockdown else 0)
    elif d7 == 3:
        t.f66 |= 1
    if d7:
        a.latch = d7


def _state1(t: TwinSim, a: ActorSim, margin: int = 0) -> Outcome:
    t.f37 &= 1
    t.unavailable = 1 if a.unavailable else 0
    _measure(t, a, face=True)
    if _apply_pending_damage(t, a):
        return Outcome.NONE
    if t.f66 & 1:
        return Outcome.NONE
    d7 = contact(t, a, margin)
    _code(t, a, d7)
    if d7 == 2:
        outcome = Outcome.STRUCK
    elif d7 == 3:
        outcome = Outcome.HELD
    else:
        outcome = Outcome.NONE
    if t.mode & MODE_GRAB_BIT:
        result = _grab_path(t, a, d7)
    else:
        result = _approach_path(t, a, d7)
    return result if result is not Outcome.NONE else outcome


def _state2(t: TwinSim, a: ActorSim, margin: int = 0) -> Outcome:
    t.f37 &= 1
    t.unavailable = 1 if a.unavailable else 0
    _measure(t, a, face=False)
    if _apply_pending_damage(t, a):
        return Outcome.NONE
    if t.f66 & 1:
        return Outcome.NONE
    d7 = contact(t, a, margin)
    _code(t, a, d7)
    if t.mode & MODE_GRAB_BIT:
        # The throw of a grabbed actor: never reached by a plan that avoids
        # the grab, and not replayed.
        return Outcome.NONE
    # $15D44: its kick on the actor hands it +$7D = 1 and flies on.
    struck = Outcome.HIT if d7 == 1 else (
        Outcome.STRUCK if d7 == 2 else (Outcome.HELD if d7 == 3 else Outcome.NONE)
    )
    t.t78 = (t.t78 + 1) & 0xFF
    tt = t.t78
    if tt == KICK_REINIT_AT:
        set_anim(t, ANIM_IDLE, t.left)
        return struck
    if tt == KICK_END_AT:
        if t.role == 0:
            t.mode |= MODE_GRAB_BIT
        t.t78 = 0
        t.primary = PRIMARY_ACTIVE
        set_anim(t, ANIM_IDLE, t.left)
        return struck
    if tt < KICK_WINDUP:
        return struck
    if tt == KICK_WINDUP:
        dy = _fixed(a.y) - _fixed(t.y)
        t.vy = _unfixed(dy >> 4)
        low = _fixed(t.vz) & 0xFFFF
        t.vz = _unfixed((KICK_VZ << 16) | low)
        t.vx = -KICK_SPEED if t.left else KICK_SPEED
        set_anim(t, ANIM_LEAP, t.left)
        integrate(t)
        return struck
    if tt == KICK_ANIM_AT:
        set_anim(t, ANIM_KICK, t.left)
    if not _on_floor(t):
        t.vz += GRAVITY
        integrate(t)
        return struck
    if t.vz != 0.0:
        t.vx = t.vy = t.vz = 0.0
        set_anim(t, ANIM_CROUCH, t.left)
    return struck


def _state3(t: TwinSim, a: ActorSim) -> Outcome:
    """``$163D0``: hitstun, or the knockdown's flight and bounce."""

    _measure(t, a, face=False, x_only=True)
    if t.r63:
        if t.z != t.ground:
            t.vz += KNOCKDOWN_GRAVITY
            if t.vz == 0.0 and t.r63 == 2:
                t.anim += 0x0C
        else:
            t.r63 -= 1
            if t.r63 == 0:
                t.vx = 0.0
                t.vz = 0.0
            else:
                t.vz = BOUNCE_VZ
                t.anim += 4
    elif t.anim <= 0x0A:
        t.x += -SHAKE_X if t.r62 & 1 else SHAKE_X
    t.r62 = (t.r62 - 1) & 0xFF
    if t.r62:
        integrate(t)
        return Outcome.NONE
    if t.f66:
        t.primary = PRIMARY_HELD
        return Outcome.NONE
    if t.anim <= 0x0A:
        t.primary = PRIMARY_ACTIVE
        set_anim(t, ANIM_IDLE, t.left)
        return Outcome.NONE
    t.f66 = 0
    t.primary = PRIMARY_GET_UP
    if t.hp > 0:
        t.r62 = GET_UP_UPDATES
        set_anim(t, ANIM_GET_UP, t.left)
    else:
        t.r62 = DEATH_UPDATES
    return Outcome.NONE


def _state5(t: TwinSim) -> None:
    """``$164FC``: getting up (health left), or the lethal gate."""

    if t.hp > 0:
        t.f4b |= 1
        t.r62 = (t.r62 - 1) & 0xFF
        if t.r62 == 0:
            t.primary = PRIMARY_ACTIVE
            set_anim(t, ANIM_IDLE, t.left)
        return
    t.r62 = (t.r62 - 1) & 0xFF
    if t.r62 == 0:
        t.gone = True
        if t.partner is not None:
            t.partner.role = 0


def twin_update(t: TwinSim, a: ActorSim, margin: int = 0) -> Outcome:
    """One update of one twin against the actor, then its renderer tail.
    ``margin`` grows the twin's attack box for a planner (0: the ROM)."""

    if t.gone:
        return Outcome.NONE
    if t.primary == PRIMARY_ACTIVE:
        outcome = _state1(t, a, margin)
    elif t.primary == PRIMARY_COMMIT:
        outcome = _state2(t, a, margin)
    elif t.primary == PRIMARY_REACTION:
        outcome = _state3(t, a)
    elif t.primary == PRIMARY_GET_UP:
        _state5(t)
        outcome = Outcome.NONE
    else:
        outcome = Outcome.NONE
    emit(t)
    return outcome


def object_pass(twins: Sequence[TwinSim], a: ActorSim, margin: int = 0) -> list[Outcome]:
    """Every twin's update, in slot order, as one object pass: the actor's
    ``+$7C`` latch starts clear (its own update cleared it) and a code a twin
    hands it hides the actor from the next twin's test (``$AA34``)."""

    a.latch = 0
    return [twin_update(t, a, margin) for t in twins]


def link_pair(twins: Iterable[TwinSim]) -> None:
    pair = [t for t in twins if not t.gone]
    for t in pair:
        t.partner = next((o for o in pair if o is not t and t.role), None)


# --- Offline check against a lockstep recording (tools/twins_lab.py) ----------


_TWIN_FIELDS = (
    ("x", 1e-6), ("y", 1e-6), ("z", 1e-6), ("vx", 1e-6), ("vy", 1e-6), ("vz", 1e-6),
    ("primary", 0), ("tac", 0), ("t78", 0), ("anim", 0), ("frame", 0), ("countdown", 0),
    ("shown_attack", 0), ("shown_body", 0), ("screen_x", 0), ("mode", 0), ("toggle", 0),
    ("r62", 0), ("r63", 0), ("hp", 0), ("pending", 0),
)


def _actor_from_bytes(data: bytes, *, cam_x: int) -> ActorSim:
    """The actor as the twins' update reads it, straight from its bytes: the
    boxes ``$4140`` cached, not rebuilt."""

    def s16(offset: int) -> int:
        return int.from_bytes(data[offset : offset + 2], "big", signed=True)

    def s32(offset: int) -> float:
        return int.from_bytes(data[offset : offset + 4], "big", signed=True) / 65536.0

    def cached(offset: int):
        words = tuple(s16(offset + 2 * i) for i in range(6))
        return None if words[0] == 0 else words

    action = data[0x30]
    a = ActorSim(
        x=s32(0x10), y=s32(0x14), z=s16(0x18), facing_left=bool(data[0x09] & 2),
        character=data[0x50], walking=False, vx=s32(0x1C), chord=None,
        x_lo=float(cam_x + PLAYER_X_MIN_OFFSET), x_hi=float(cam_x + PLAYER_X_MAX_OFFSET),
        lane_lo=float(PLAYER_LANE_MIN), lane_hi=float(PLAYER_LANE_MAX),
        attack=cached(0x64), body=cached(0x70), damage=data[0x34], knockdown=bool(data[0x42] & 1),
        unavailable=bool(data[0x59] & 2) or bool(data[0x4B] & 2) or 0x5A <= action <= 0x5F,
        untouchable=bool(data[0x59] & 2), holding=bool(s16(0x4C)), latch=0,
        invulnerable=bool(data[0x4B] & 2),
    )
    return a


def check_recording(rows: Sequence[dict], *, verbose: bool = False) -> dict:
    """Replay a ``twins_lab.py`` recording: every object pass of the twins,
    predicted from the previous frame's bytes, against the next frame's."""

    from collections import Counter

    checked: Counter[str] = Counter()
    mismatched: Counter[str] = Counter()
    examples: list[dict] = []
    for before, after in zip(rows, rows[1:]):
        b_twins = {index: bytes.fromhex(h) for index, h in before["tw"]}
        a_twins = {index: bytes.fromhex(h) for index, h in after["tw"]}
        if not b_twins or set(b_twins) != set(a_twins):
            continue
        changed = any(b_twins[i][0x0D] != a_twins[i][0x0D] or b_twins[i][0x10:0x1C] != a_twins[i][0x10:0x1C] for i in b_twins)
        if not changed:
            continue  # the players' frame
        p1 = bytes.fromhex(before["p1"])
        actor = _actor_from_bytes(p1, cam_x=after["cam"])
        sims = {i: TwinSim.from_bytes(data, slot=i, cam_x=after["cam"]) for i, data in b_twins.items()}
        link_pair(sims.values())
        order = sorted(sims)
        actor.latch = 0
        outcomes = {}
        for i in order:
            outcomes[i] = twin_update(sims[i], actor)
        p1_after = bytes.fromhex(after["p1"])
        for i in order:
            sim = sims[i]
            real = TwinSim.from_bytes(a_twins[i], slot=i, cam_x=after["cam"])
            state = f"p{b_twins[i][0x30]}t{b_twins[i][0x67]}m{b_twins[i][0x7B] & 2}"
            if b_twins[i][0x30] not in (1, 2, 3, 5):
                continue
            checked[state] += 1
            bad = []
            for name, tolerance in _TWIN_FIELDS:
                predicted, actual = getattr(sim, name), getattr(real, name)
                if abs(predicted - actual) > tolerance:
                    bad.append(name)
            for name in bad:
                mismatched[f"{state}:{name}"] += 1
            if bad and len(examples) < (200 if verbose else 30):
                examples.append(
                    {
                        "f": after["f"],
                        "slot": i,
                        "state": state,
                        "outcome": outcomes[i].name,
                        "p1_7c": p1_after[0x7C],
                        "diff": {n: [getattr(sim, n), getattr(real, n)] for n in bad},
                    }
                )
    return {
        "updates_checked": sum(checked.values()),
        "checked_by_state": dict(checked),
        "mismatches": dict(mismatched),
        "examples": examples,
    }


# --- From the tokens -------------------------------------------------------------


def twin_from_token(twin, *, cam_x: int) -> TwinSim:
    """A ``TwinSim`` from an ``Onihime`` token (``observe`` fills every field
    the update reads)."""

    slot = twin.slot
    index = int(slot[3:]) if isinstance(slot, str) and slot.startswith("obj") and slot[3:].isdigit() else 0
    health = twin.health or 0
    if health >= 0x8000:
        health -= 0x10000
    return TwinSim(
        slot=index,
        x=twin.fine_x or float(twin.world_x),
        y=twin.fine_y or float(twin.world_y),
        z=twin.fine_z or float(twin.ground_z or 0),
        vx=twin.boss_vel_x,
        vy=twin.boss_vel_lane,
        vz=twin.vel_z,
        ground=twin.ground_fine or float(twin.ground_z or 0),
        primary=twin.primary_state,
        tac=twin.tactical,
        t78=twin.phase_timer,
        anim=twin.anim,
        frame=twin.anim_frame,
        countdown=twin.anim_countdown,
        reload=twin.anim_reload,
        shown_attack=twin.attack_box_id,
        shown_body=twin.body_box_id,
        screen_x=twin.screen_x,
        cam_x=cam_x,
        mode=twin.mode_flags,
        toggle=twin.toggle_7a,
        role=twin.pair_role,
        unavailable=twin.target_unavailable,
        f4b=twin.flags_4b,
        pending=twin.pending_damage,
        f37=twin.flags_37,
        r62=twin.reaction_timer,
        r63=twin.bounce_63,
        f66=twin.hold_flags,
        f6d=twin.flags_6d,
        hp=health,
        left=False,
        above=False,
        d50=twin.boss_dist_x,
        d52=twin.boss_dist_lane,
        partner=None,
        gone=False,
    )


CHORD_ACTIONS = (0x20, 0x4A)  # $322A: unarmed, and with a weapon in hand
# Adam's chord: crouch, hop, landing -- bare ($22, $24, $14) and with a weapon
# in hand ($4C, $4E, $40; the action table at $2F2C gives them the same
# animations, $0C / $24 / $0C). Measured live: armed, his hop read as free.
ADAM_CHORD_CROUCH = (0x22, 0x4C)
ADAM_CHORD_HOP = (0x24, 0x4E)
ADAM_CHORD_LANDING = (0x14, 0x40)
ADAM_CHORD_ACTIONS = ADAM_CHORD_CROUCH + ADAM_CHORD_HOP + ADAM_CHORD_LANDING
FREE_ACTIONS = frozenset(range(0x02, 0x10)) | frozenset(range(0x30, 0x3C))
# $3A30's per-frame rows for animation $24: Axel row 8, Blaze row 26.
_CHORD_FRAME_UPDATES = {AXEL: (1, 5, 2), BLAZE: (3, 8, 3)}


def chord_step_from(character: int, action: int, frame: int, countdown: int) -> int | None:
    """The chord schedule's step from the actor's own bytes, or None when the
    actor is not in its rear attack."""

    base = action & 0xFE
    if character == ADAM:
        if base in ADAM_CHORD_CROUCH:
            return max(0, 5 - countdown)
        if base in ADAM_CHORD_HOP:
            return (5 + max(0, 5 - countdown)) if frame == 0 else (10 + max(0, 8 - countdown) if frame == 1 else 18)
        if base in ADAM_CHORD_LANDING:
            return 19 + max(0, 5 - countdown)
        return None
    if base not in CHORD_ACTIONS:
        return None
    rows = _CHORD_FRAME_UPDATES.get(character, _CHORD_FRAME_UPDATES[BLAZE])
    frame = min(frame, len(rows) - 1)
    step = sum(rows[:frame]) + max(0, rows[frame] - countdown)
    return min(step, sum(rows) - 1)


def actor_from_token(actor, *, cam_x: int) -> ActorSim:
    """An ``ActorSim`` from the ``Myself`` token."""

    base = actor.action_state & 0xFE
    character = actor.character_id if actor.character_id in (AXEL, ADAM, BLAZE) else BLAZE
    chord = chord_step_from(character, actor.action_state, actor.anim_frame, actor.anim_countdown)
    walking = base not in (0x02, 0x30) and base in FREE_ACTIONS
    a = ActorSim(
        x=actor.fine_x or float(actor.world_x),
        y=actor.fine_y or float(actor.world_y),
        z=int(actor.ground_z or actor.world_z or 0),
        facing_left=actor.facing_left,
        character=character,
        walking=walking,
        vx=actor.vel_x,
        chord=chord,
        x_lo=float(cam_x + PLAYER_X_MIN_OFFSET),
        x_hi=float(cam_x + PLAYER_X_MAX_OFFSET),
        lane_lo=float(PLAYER_LANE_MIN),
        lane_hi=float(PLAYER_LANE_MAX),
        attack=None,
        body=None,
        damage=0,
        knockdown=False,
        unavailable=bool(actor.flags_59 & 2) or bool(actor.flags_4b & 2) or 0x5A <= actor.action_state <= 0x5F,
        untouchable=bool(actor.flags_59 & 2),
        holding=actor.is_holding_enemy,
        latch=0,
        invulnerable=bool(actor.flags_4b & 2),
    )
    refresh_boxes(a, a.x, a.y)
    return a
