"""The street enemies -- Garcia (``$20``-``$23``), Signal (``$24``), HakuRo
(``$25``) and Nora (``$26``) -- as the ROM plays them, for ``grunt_plan``'s
lookahead.

``garcia.py`` decoded the office's type-``$22`` Garcia for Mr. X's plan and
checked it in lockstep; this is the same object, every street type, every
state a fight meets. Decoded from each type's primary-state table (the word
tables at ``$D60E``, ``$D9A2``, ``$DD80``, ``$E32E``, ``$E4DA``, ``$E8F8``,
``$10362``) and the shared ordinary-enemy framework, and checked against the
lockstep recordings of ``tools/grunt_lab.py`` (``check_recording``).

Contact (``$A9BA`` on ``$AA22``/``$AAA0``), the same for every type
    The player's box on his body first -- a strike (the player's ``+$34``
    non-zero, his screen X in ``[$78, $1C8)``) is his hitstun, a walking box
    (no damage, the player holding nobody, the heights within 8) is the hold
    -- and only when that box misses, his box on the player's body: the hit.
    Signal's contact wrapper (``$E7B0``) turns his own box on the player into
    *his* hold on the player (``$0C``: he walks round behind and throws).
The knife (Garcia ``$20``)
    A held weapon never tests contact itself (``$5E2E``'s enemy-holder path
    only places it). What cuts is his own animation: the run he enters with
    (state ``$0C``, animation ``$38``, 5 px an update straight at the player's
    spot) carries attack box ``$01`` on every frame -- his whole body, -9..+9
    -- and the stab (``$09``, animation ``$2C``) opens with it too before the
    blade's ``$14`` (32-56 px ahead). So an armed Garcia hurts by *touching*:
    whatever part of the player's body meets his during that run is a hit,
    unless the player's own walking box met his body first (the hold). Hit or
    knocked down he drops it (``$D948`` -> weapon ``+$51`` = 2) and becomes a
    plain ``$22``.
The bat and pipe (Garcia ``$23``)
    Walks to 64 px from the player on its lane (``$E348``), then swings:
    animation ``$30``, three frames of wind-up (9 updates), then box ``$18``
    24-72 px ahead for 9 -- out of the player's punch (Blaze 18-68).
The jab (Garcia ``$22``/``$21``)
    ``$E102``: box ``$12`` (0-40 px ahead, head height) on the player's body
    while he approaches, wanders or stands -- the punch at once, its first
    frame already the jab.
Signal
    Contact is a hold on the player, so his body box ``$3D`` (-11..+11) is
    the danger on every frame he stands or walks; the slide (``$0B``, 7 px an
    update falling off by 0.15625) sweeps ``$0F`` (-24..+24, at the feet) and
    has no body at all.
HakuRo
    ``$0E`` dashes at 4.5 px an update to 56 px short of the player, and
    ``$06`` (0-44 px ahead, the whole height) on the player's body is the
    strike (``$0A``); level with him within 72 px it is the jump kick
    (``$0D``). The flying kick (``$0B``) crosses the screen at 10 px an update.
Nora
    ``$F1B0`` tests the whip's box ``$22`` (32-80 px ahead, lanes -12..+10)
    on the player's body every update she walks in; the lash is frame 2 of
    animation ``$14``, 10 updates after that test passes. Closer than 32 px
    the whip cannot land at all.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import Enum, auto

from ..hazards import base_floor_z
from .jack import _vector_velocity
from .twins import ActorSim, overlaps

GARCIA_KNIFE = 0x20
GARCIA_GRABBER = 0x21
GARCIA = 0x22
GARCIA_BAT = 0x23
SIGNAL = 0x24
HAKURO = 0x25
NORA = 0x26
HAKURO_TRIO = 0x2A
MODELLED_TYPES = frozenset({GARCIA_KNIFE, GARCIA_GRABBER, GARCIA, GARCIA_BAT, SIGNAL, HAKURO, NORA, HAKURO_TRIO})
GARCIA_TYPES = frozenset({GARCIA_KNIFE, GARCIA_GRABBER, GARCIA, GARCIA_BAT})

ST_INIT = 0x00
ST_RESELECT = 0x01
ST_HITSTUN = 0x02
ST_KNOCKDOWN = 0x03
ST_PEPPER = 0x04
ST_HELD = 0x05
ST_DYING = 0x06
ST_EVADE = 0x07

# --- The animation sets (``+$04``): anim word -> (frame reload, ((attack, body), ...)) ---------

# $1FC70, every Garcia.
GARCIA_ANIMS: dict[int, tuple[int, tuple[tuple[int, int], ...]]] = {
    0x00: (5, ((0x00, 0x01),) * 4),
    0x02: (5, ((0x00, 0x01),) * 4),
    0x04: (5, ((0x00, 0x02), (0x02, 0x00), (0x1D, 0x00), (0x00, 0x00), (0x00, 0x01), (0x1C, 0x00))),
    0x06: (5, ((0x00, 0x02), (0x02, 0x00), (0x1D, 0x00), (0x00, 0x00), (0x00, 0x01), (0x1C, 0x00))),
    0x08: (1, ((0x00, 0x03),) * 4),
    0x0A: (1, ((0x00, 0x03),) * 4),
    0x0C: (6, ((0x00, 0x01), (0x00, 0x01), (0x00, 0x03))),
    0x0E: (6, ((0x00, 0x01), (0x00, 0x01), (0x00, 0x03))),
    0x10: (6, ((0x00, 0x03), (0x1C, 0x00), (0x00, 0x03))),
    0x12: (6, ((0x00, 0x03), (0x1C, 0x00), (0x00, 0x03))),
    0x14: (4, ((0x12, 0x01), (0x00, 0x01), (0x00, 0x01), (0x12, 0x01), (0x00, 0x01), (0x00, 0x01),
               (0x00, 0x01), (0x3E, 0x10), (0x3E, 0x10), (0x3E, 0x10))),
    0x16: (4, ((0x13, 0x01), (0x00, 0x01), (0x00, 0x01), (0x13, 0x01), (0x00, 0x01), (0x00, 0x01),
               (0x00, 0x01), (0x3F, 0x11), (0x3F, 0x11), (0x3F, 0x11))),
    0x18: (3, ((0x00, 0x01),)),
    0x1A: (3, ((0x00, 0x01),)),
    0x1C: (5, ((0x00, 0x01),) * 4),
    0x1E: (5, ((0x00, 0x01),) * 4),
    0x20: (5, ((0x00, 0x01),) * 4),
    0x22: (5, ((0x00, 0x01),) * 4),
    0x24: (5, ((0x00, 0x01),) * 4),
    0x26: (5, ((0x00, 0x01),) * 4),
    0x28: (5, ((0x00, 0x01), (0x14, 0x10), (0x14, 0x10))),
    0x2A: (5, ((0x00, 0x01), (0x15, 0x11), (0x15, 0x11))),
    0x2C: (5, ((0x01, 0x01), (0x14, 0x10), (0x14, 0x10))),
    0x2E: (5, ((0x01, 0x01), (0x15, 0x11), (0x15, 0x11))),
    0x30: (4, ((0x00, 0x01), (0x00, 0x16), (0x00, 0x16), (0x18, 0x10), (0x18, 0x10), (0x18, 0x10))),
    0x32: (4, ((0x00, 0x01), (0x00, 0x17), (0x00, 0x17), (0x19, 0x11), (0x19, 0x11), (0x19, 0x11))),
    0x34: (4, ((0x00, 0x01), (0x00, 0x16), (0x00, 0x16), (0x18, 0x10), (0x18, 0x10), (0x18, 0x10))),
    0x36: (4, ((0x00, 0x01), (0x00, 0x17), (0x00, 0x17), (0x19, 0x11), (0x19, 0x11), (0x19, 0x11))),
    0x38: (4, ((0x01, 0x01),) * 4),
    0x3A: (4, ((0x01, 0x01),) * 4),
}
# $22948, Signal.
SIGNAL_ANIMS: dict[int, tuple[int, tuple[tuple[int, int], ...]]] = {
    0x00: (6, ((0x3D, 0x01),) * 4),
    0x02: (6, ((0x3D, 0x01),) * 4),
    0x04: (5, ((0x00, 0x0A), (0x0A, 0x00), (0x1D, 0x00), (0x00, 0x00), (0x3D, 0x01), (0x1C, 0x00))),
    0x06: (5, ((0x00, 0x0A), (0x0A, 0x00), (0x1D, 0x00), (0x00, 0x00), (0x3D, 0x01), (0x1C, 0x00))),
    0x08: (1, ((0x00, 0x03),) * 4),
    0x0A: (1, ((0x00, 0x03),) * 4),
    0x0C: (6, ((0x3D, 0x01), (0x3D, 0x01), (0x00, 0x03))),
    0x0E: (6, ((0x3D, 0x01), (0x3D, 0x01), (0x00, 0x03))),
    0x10: (6, ((0x00, 0x03), (0x1C, 0x00), (0x00, 0x03))),
    0x12: (6, ((0x00, 0x03), (0x1C, 0x00), (0x00, 0x03))),
    0x14: (8, ((0x00, 0x00),) * 4),
    0x16: (8, ((0x00, 0x00),) * 4),
    0x18: (8, ((0x00, 0x00), (0x0F, 0x00), (0x00, 0x00), (0x00, 0x00))),
    0x1A: (8, ((0x00, 0x00), (0x0F, 0x00), (0x00, 0x00), (0x00, 0x00))),
}
# $2402C, HakuRo.
HAKURO_ANIMS: dict[int, tuple[int, tuple[tuple[int, int], ...]]] = {
    0x00: (6, ((0x00, 0x01),) * 4),
    0x02: (6, ((0x00, 0x01),) * 4),
    0x04: (5, ((0x02, 0x00), (0x02, 0x00), (0x1D, 0x00), (0x00, 0x00), (0x00, 0x01), (0x1C, 0x00))),
    0x06: (5, ((0x02, 0x00), (0x02, 0x00), (0x1D, 0x00), (0x00, 0x00), (0x00, 0x01), (0x1C, 0x00))),
    0x08: (1, ((0x00, 0x03),) * 4),
    0x0A: (1, ((0x00, 0x03),) * 4),
    0x0C: (6, ((0x00, 0x01), (0x00, 0x01), (0x00, 0x03))),
    0x0E: (6, ((0x00, 0x01), (0x00, 0x01), (0x00, 0x03))),
    0x10: (6, ((0x00, 0x03), (0x1C, 0x00), (0x00, 0x03))),
    0x12: (6, ((0x00, 0x03), (0x1C, 0x00), (0x00, 0x03))),
    0x14: (4, ((0x00, 0x04), (0x06, 0x08), (0x06, 0x08), (0x06, 0x08))),
    0x16: (4, ((0x00, 0x05), (0x07, 0x09), (0x07, 0x09), (0x07, 0x09))),
    0x18: (6, ((0x00, 0x0A), (0x0C, 0x0B), (0x0C, 0x0B))),
    0x1A: (6, ((0x00, 0x0A), (0x0D, 0x0B), (0x0D, 0x0B))),
    0x1C: (3, ((0x00, 0x0A), (0x00, 0x10), (0x00, 0x10), (0x00, 0x10), (0x00, 0x10), (0x00, 0x0A))),
    0x1E: (3, ((0x00, 0x0A), (0x00, 0x10), (0x00, 0x10), (0x00, 0x10), (0x00, 0x10), (0x00, 0x0A))),
    0x20: (2, ((0x00, 0x10),) * 4),
    0x22: (2, ((0x00, 0x10),) * 4),
    0x24: (4, ((0x00, 0x01), (0x00, 0x01))),
    0x26: (4, ((0x00, 0x01), (0x00, 0x01))),
}
# $242F8, Nora.
NORA_ANIMS: dict[int, tuple[int, tuple[tuple[int, int], ...]]] = {
    0x00: (6, ((0x00, 0x01),) * 4),
    0x02: (6, ((0x00, 0x01),) * 4),
    0x04: (5, ((0x00, 0x03), (0x00, 0x1F), (0x00, 0x1D), (0x00, 0x00), (0x00, 0x01), (0x00, 0x00))),
    0x06: (5, ((0x00, 0x03), (0x00, 0x1F), (0x00, 0x1D), (0x00, 0x00), (0x00, 0x01), (0x00, 0x00))),
    0x08: (1, ((0x00, 0x03),) * 4),
    0x0A: (1, ((0x00, 0x03),) * 4),
    0x0C: (6, ((0x00, 0x01), (0x00, 0x01), (0x00, 0x03))),
    0x0E: (6, ((0x00, 0x01), (0x00, 0x01), (0x00, 0x03))),
    0x10: (6, ((0x00, 0x03), (0x00, 0x00), (0x00, 0x03))),
    0x12: (6, ((0x00, 0x03), (0x00, 0x00), (0x00, 0x03))),
    0x14: (5, ((0x00, 0x01), (0x00, 0x01), (0x22, 0x20), (0x00, 0x20), (0x00, 0x20))),
    0x16: (5, ((0x00, 0x01), (0x00, 0x01), (0x23, 0x21), (0x00, 0x21), (0x00, 0x21))),
}
ANIMS_FOR_TYPE = {
    GARCIA_KNIFE: GARCIA_ANIMS, GARCIA_GRABBER: GARCIA_ANIMS, GARCIA: GARCIA_ANIMS, GARCIA_BAT: GARCIA_ANIMS,
    SIGNAL: SIGNAL_ANIMS, HAKURO: HAKURO_ANIMS, NORA: NORA_ANIMS, HAKURO_TRIO: HAKURO_ANIMS,
}

# The object shape table ($1A68E): every id the sets above (and $DA98's $1E) select.
SHAPES: dict[int, tuple[int, int, int, int, int, int]] = {
    0x01: (-9, 9, -8, 8, -60, 0),
    0x02: (-4, 4, -8, 8, -60, 0),
    0x03: (-8, 8, -8, 8, -60, 0),
    0x04: (-20, 8, -8, 8, -60, 0),
    0x05: (-8, 20, -8, 8, -60, 0),
    0x06: (0, 44, -8, 8, -60, 0),
    0x07: (-44, 0, -8, 8, -60, 0),
    0x08: (-24, 0, -8, 8, -60, 0),
    0x09: (0, 24, -8, 8, -60, 0),
    0x0A: (-8, 8, -8, 8, -64, 0),
    0x0B: (-8, 8, -8, 8, -48, 0),
    0x0C: (8, 48, -8, 8, -32, -16),
    0x0D: (-48, -8, -8, 8, -32, -16),
    0x0F: (-24, 24, -8, 8, -14, 0),
    0x10: (4, 20, -8, 8, -60, 0),
    0x11: (-20, -4, -8, 8, -60, 0),
    0x12: (0, 40, -8, 8, -50, -44),
    0x13: (-40, 0, -8, 8, -50, -44),
    0x14: (32, 56, -8, 8, -42, -35),
    0x15: (-56, -32, -8, 8, -42, -35),
    0x16: (-1, 17, -8, 8, -60, 0),
    0x17: (-19, -1, -8, 8, -60, 0),
    0x18: (24, 72, -8, 8, -56, -40),
    0x19: (-72, -24, -8, 8, -56, -40),
    0x1C: (-4, 4, -8, 8, -104, -44),
    0x1D: (-24, 24, -8, 8, -12, 0),
    0x1E: (-13, 13, -10, 10, -60, 0),
    0x1F: (-24, 24, -8, 8, -44, -28),
    0x20: (9, 32, -8, 8, -52, 0),
    0x21: (-32, -9, -8, 8, -52, 0),
    0x22: (32, 80, -12, 10, -44, -20),
    0x23: (-80, -32, -12, 10, -44, -20),
    0x3D: (-11, 11, -8, 8, -60, 0),
    0x3E: (16, 51, -8, 8, -48, -42),
    0x3F: (-51, -16, -8, 8, -48, -42),
}

ANIM_MIRROR = 0x02

# --- Constants from the handlers ----------------------------------------------------------------

LANE_MIN = 2.0  # $A00E: a step is refused outside [2, $70) ($A0 in round 7)
LANE_MAX = 112.0
LANE_MAX_ROUND_7 = 160.0
X_MAX = 0x1510  # $9F96: the right bound, $1400 in round 8
X_MAX_ROUND_8 = 0x1400
X_MIN_ROUND_7 = 0x2F0
ON_SCREEN = (0x80, 0x1C0)  # $92AC / $97CE
ON_SCREEN_WIDE = (0x70, 0x1D0)  # $97E6
STRUCK_SCREEN = (0x78, 0x1C8)  # $AAA0: a strike lands only here
SCREEN_BIAS = 0x80
GRAB_Z = 8
ARRIVE = 4  # $9604: within 4 px on both axes
HITSTUN_UPDATES = 0x18
HIT_PUSH = 2
GRAVITY = 1.125  # $973E: +$12000 an update
FALL_CAP = 16.0

# $DBCC, every type's state 7 (garcia.py): toward the lane band's edge away
# from the target, then legs past the target until 80 px beyond it.
EVADE_SPLIT = 0x38
EVADE_BOTTOM = 0x58
EVADE_TOP = 0x18
EVADE_PAST_DX = 0x50
EVADE_LANE_SPEED = 3.0
EVADE_LANE_FAST = ((0x10, 13.0), (0x05, 10.0))
EVADE_LEG_UPDATES = (16, 8, 10, 5)  # $1033A
EVADE_LEGS = ((2.5, 6), (3.0, 5), (4.0, 4), (5.0, 4))  # $DD68: speed, frame reload

# $22's wander ($E20A): point offsets $1031A, timers $1033A, speed/reload $10342,
# and the state it lands in after one walk cycle, $10352.
WANDER_OFFSETS = (
    (16, 16), (0, 16), (16, 0), (-16, 16), (16, -16), (-16, 0), (0, -16), (-16, -16),
    (8, 16), (0, 8), (8, 0), (-16, 8), (16, -8), (-8, 0), (0, -8), (-8, -16),
)
WANDER_SPEEDS = ((0x100, 7), (0x180, 6), (0x200, 5), (0x300, 3))
WANDER_NEXT = (0x0B00, 0x0B00, 0x0B00, 0x0C00, 0x0900, 0x0C00, 0x0100, 0x0900)
STAND_UPDATES = (35, 4, 20, 8)  # $E322

# Personality tables ($933C): +$40's low nibble -> the state a reset lands in.
PERSONALITY = {
    GARCIA_KNIFE: (0x0D00, 0x0C00),  # $D6BC
    GARCIA: (0x0900, 0x0F00, 0x1200, 0x0E00, 0x1300, 0x1200),  # $DDDA
    HAKURO: (0x1100, 0x1100, 0x0E00, 0x1300),  # $E94A
    NORA: (0x0900, 0x0A00, 0x0800),  # $F0F6
}

# Scripted entries: frozen until something else releases them -- the ride in
# ($DDE6, released by the object it spawns), rising from below deck ($E952,
# until the camera reaches him). No box, and waiting on one is a deadlock:
# the camera only moves when the actor walks the stage on. Lying in wait
# ($DE78) is not one of them: he gets up as the target comes within 80 px on
# X, and his first update of the approach is already the jab's test.
ENTRY_STATES: dict[int, frozenset[int]] = {
    GARCIA: frozenset({0x13}),
    NORA: frozenset({0x0A}),
    HAKURO: frozenset({0x13}),
}


LYING_IN_WAIT = 0x12
WAKE_DX = 0x50


def lying_in_wait(g: GruntSim) -> bool:
    return g.type == GARCIA and g.state == LYING_IN_WAIT


def in_entry(g: GruntSim) -> bool:
    return g.state in ENTRY_STATES.get(g.type, ())


def on_screen(g: GruntSim) -> bool:
    return ON_SCREEN[0] <= g.screen_x < ON_SCREEN[1]


# The player's actions some states read ($30 & $FE).
PLAYER_KNOCKED_DOWN = frozenset({0x5C, 0x7A, 0x04})
PLAYER_DOWN_RANGE = (0x54, 0x5D)  # $54..$5C: falling, lying, getting up


class Outcome(Enum):
    NONE = auto()
    HIT = auto()  # his box on the actor's body
    STRUCK = auto()  # the actor's strike on his body
    GRAB = auto()  # the actor's walking box on his body: the actor's hold
    SEIZED = auto()  # his hold on the actor (Signal's contact, the $21's full nelson)
    KNOCKED = auto()  # the actor's swung weapon on his body: down at once
    SLIPPED = auto()  # a grab contact the actor's own update refuses ($3266): he resets


def _hi(value: float) -> int:
    """The integer high word of a 16.16 value (a floor, like ``swap``)."""

    return int(value) if value >= 0 else math.floor(value)


def _s16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big", signed=True)


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def _s32(data: bytes, offset: int) -> float:
    return int.from_bytes(data[offset : offset + 4], "big", signed=True) / 65536.0


def box(box_id: int, x: int, y: int, z: int) -> tuple[int, int, int, int, int, int] | None:
    if not box_id:
        return None
    shape = SHAPES.get(box_id)
    if shape is None:
        return None
    return (x + shape[0], x + shape[1], y + shape[2], y + shape[3], z + shape[4], z + shape[5])


class GruntSim:
    """One street enemy's object, reduced to what his states read and write."""

    __slots__ = (
        "slot", "type", "x", "y", "z", "vx", "vy", "vz", "state", "flags", "t50", "t51", "t52",
        "f48", "aim_x", "aim_y", "speed", "off_x", "off_y", "anim", "frame", "countdown", "reload",
        "animating", "attack_id", "body_id", "hp", "param", "screen_x", "cam_x", "alive", "repeats",
        "damage", "w54", "armed", "level", "floor", "last_frame_tick", "rng",
        # A knife this update threw (``$D8EC``), for the object pass to fly.
        "thrown",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))

    def copy(self) -> GruntSim:
        other = GruntSim.__new__(GruntSim)
        for name in self.__slots__:
            setattr(other, name, getattr(self, name))
        return other

    @property
    def facing_left(self) -> bool:
        return bool(self.anim & ANIM_MIRROR)

    @property
    def anims(self) -> dict:
        return ANIMS_FOR_TYPE.get(self.type, GARCIA_ANIMS)

    @classmethod
    def from_bytes(cls, data: bytes, *, slot: int, cam_x: int, level: int = 0,
                   floor: float | None = None) -> GruntSim:
        z = _s32(data, 0x18)
        if floor is None:
            # On the ground his z is his floor; in the air (a vertical
            # velocity) he lands on the round's street, or lower.
            vz = _s32(data, 0x24)
            floor = z if vz == 0 else max(z, float(base_floor_z(level)))
        return cls(
            slot=slot,
            type=data[0x00],
            x=_s32(data, 0x10),
            y=_s32(data, 0x14),
            z=z,
            vx=_s32(data, 0x1C),
            vy=_s32(data, 0x20),
            vz=_s32(data, 0x24),
            state=data[0x30],
            flags=data[0x31],
            t50=data[0x50],
            t51=data[0x51],
            t52=data[0x52],
            f48=data[0x48],
            aim_x=_s16(data, 0x60),
            aim_y=_s16(data, 0x62),
            speed=_u16(data, 0x64),
            off_x=_s16(data, 0x66),
            off_y=_s16(data, 0x68),
            anim=_u16(data, 0x08),
            frame=data[0x0A],
            countdown=data[0x0D],
            reload=data[0x0C],
            animating=bool(data[0x01] & 0x04),
            attack_id=data[0x02],
            body_id=data[0x03],
            hp=_s16(data, 0x32),
            param=data[0x40],
            screen_x=_s16(data, 0x28),
            cam_x=cam_x,
            alive=data[0x30] != ST_DYING and data[0x00] in MODELLED_TYPES and _s16(data, 0x32) >= 0,
            repeats=data[0x6E],
            damage=data[0x34],
            w54=_s16(data, 0x54),
            armed=_u16(data, 0x6A) != 0,
            level=level,
            floor=floor,
            last_frame_tick=0,
            rng=5,
            thrown=None,
        )


# --- The framework ----------------------------------------------------------------------------


def _goto(g: GruntSim, word: int) -> None:
    """``move.w #word, +$30``: the state and ``+$31`` at once."""

    g.state = (word >> 8) & 0xFF
    g.flags = word & 0xFF


_NO_ANIM = (5, ((0, 0x01),))


def _latch(g: GruntSim) -> None:
    frames = ANIMS_FOR_TYPE.get(g.type, GARCIA_ANIMS).get(g.anim, _NO_ANIM)[1]
    frame = g.frame
    g.attack_id, g.body_id = frames[frame if frame < len(frames) else len(frames) - 1]


def _set_anim(g: GruntSim, anim: int, a: ActorSim) -> None:
    """``$96C0``: an animation from frame 0, facing the target (left unless it
    stands strictly to his right); the boxes latch at once."""

    left = not (int(a.x) > int(g.x))
    g.anim = anim | (ANIM_MIRROR if left else 0)
    reload, _ = g.anims.get(g.anim, (5, ((0, 0x01),)))
    g.frame = 0
    g.reload = g.countdown = reload
    _latch(g)


def _face(g: GruntSim, a: ActorSim) -> None:
    """``$9E4C``: the facing bit only, toward the target."""

    left = not (int(a.x) > int(g.x))
    g.anim = (g.anim & ~ANIM_MIRROR) | (ANIM_MIRROR if left else 0)


def _on_screen(g: GruntSim) -> bool:
    return ON_SCREEN[0] <= g.screen_x < ON_SCREEN[1]


def _on_screen_wide(g: GruntSim) -> bool:
    return ON_SCREEN_WIDE[0] <= g.screen_x < ON_SCREEN_WIDE[1]


def _refused_off_screen(g: GruntSim) -> bool:
    """``$92AC``: off screen the state is ``$DBCC`` instead."""

    if _on_screen(g):
        return False
    _goto(g, 0x0700)
    return True


def _approach(g: GruntSim) -> bool:
    """``$9604``: True once within 4 px on both axes; else aims the velocity."""

    dx = int(g.aim_x) - int(g.x)
    dy = int(g.aim_y) - int(g.y)
    if abs(dx) < ARRIVE and abs(dy) < ARRIVE:
        return True
    g.vx, g.vy = _vector_velocity(dx, dy, int(g.speed))
    return False


def _toward_target(g: GruntSim, a: ActorSim, speed: int, lead_x: int = 0) -> None:
    """``$97FE``/``$9800``: velocity at ``speed`` toward the target's spot (plus
    ``lead_x`` on the side he faces away from)."""

    tx = int(a.x) + (lead_x if g.facing_left else -lead_x)
    g.vx, g.vy = _vector_velocity(tx - int(g.x), int(a.y) - int(g.y), speed)


def _point_on_side(g: GruntSim, a: ActorSim, offset: int) -> int:
    """``$9682``: ``offset`` px from the target, on his own side of it."""

    tx = int(a.x)
    return tx - offset if tx >= int(g.x) else tx + offset


def _point_9648(g: GruntSim, a: ActorSim, offset: int) -> None:
    """``$9648``: the target's lane, ``offset`` px from it on his side."""

    g.aim_y = int(a.y)
    g.aim_x = _point_on_side(g, a, offset)


def _point_9654(g: GruntSim, a: ActorSim) -> None:
    """``$9654``: the type's approach offsets ``+$66``/``+$68``, the lane one
    reflected when it would leave ``[0, $70)``."""

    lane = int(a.y) + int(g.off_y)
    if lane < 0 or lane >= 0x70:
        lane = int(a.y) - int(g.off_y)
    g.aim_y = lane
    g.aim_x = _point_on_side(g, a, int(g.off_x))


def _x_bounds(g: GruntSim) -> tuple[float, float]:
    lo = float(X_MIN_ROUND_7) if g.level == 6 else 0.0
    hi = float(X_MAX_ROUND_8 if g.level == 7 else X_MAX)
    return lo, hi


def _advance_x(g: GruntSim) -> bool:
    """``$9F96``; False when the bound refused the step."""

    lo, hi = _x_bounds(g)
    nx = g.x + g.vx
    if g.vx < 0 and nx < lo or g.vx >= 0 and nx >= hi:
        return False
    g.x = nx
    return True


def _advance_lane(g: GruntSim) -> bool:
    """``$A00E``; False when the band refused the step."""

    top = LANE_MAX_ROUND_7 if g.level == 6 else LANE_MAX
    ny = g.y + g.vy
    if ny < LANE_MIN or ny >= top:
        return False
    g.y = ny
    return True


def _move(g: GruntSim) -> None:
    """``$9E68`` on open floor."""

    _advance_x(g)
    _advance_lane(g)


def _fall(g: GruntSim) -> bool:
    """``$973E``: gravity, then True on the update he lands on his floor."""

    g.vz = min(g.vz + GRAVITY, FALL_CAP) if g.vz >= 0 else g.vz + GRAVITY
    g.z += g.vz
    if g.vz >= 0 and g.z >= g.floor:
        g.z = g.floor
        g.vz = 0.0
        return True
    return False


def _trigger(g: GruntSim, a: ActorSim, box_id: int) -> bool:
    """``$AD04``: his box ``box_id`` on the target's cached body (``+$70``)."""

    b = box(box_id, int(g.x), int(g.y), _hi(g.z))
    return b is not None and a.body is not None and overlaps(b, a.body)


def _mirrored(g: GruntSim, right_id: int) -> int:
    return right_id + 1 if g.facing_left else right_id


def contact(g: GruntSim, a: ActorSim) -> Outcome:
    """``$AAA0``: the actor's box on his body first, then his box on the
    actor's body."""

    if a.unavailable or a.latch:
        return Outcome.NONE
    x, y, z = int(g.x), int(g.y), _hi(g.z)
    body = box(g.body_id, x, y, z)
    weapon = getattr(a, "weapon_box", None)
    if weapon is not None and body is not None and overlaps(weapon, body):
        # $AA34: the registered attackers ($FFFB22) first -- the swung weapon's
        # box on his body is $ABA4's code 5, $A9DC's knockdown.
        if STRUCK_SCREEN[0] <= g.screen_x < STRUCK_SCREEN[1]:
            return Outcome.KNOCKED
        return Outcome.NONE
    if a.attack is not None and body is not None and overlaps(a.attack, body):
        if a.damage:
            if STRUCK_SCREEN[0] <= g.screen_x < STRUCK_SCREEN[1]:
                return Outcome.STRUCK
            return Outcome.NONE
        if not a.holding and abs(a.z - z) <= GRAB_Z:
            return Outcome.GRAB
        return Outcome.NONE
    attack = box(g.attack_id, x, y, z)
    if attack is not None and a.body is not None and overlaps(attack, a.body):
        return Outcome.HIT
    return Outcome.NONE


def takes_hold(a: ActorSim, g: GruntSim) -> bool:
    """``$3266``, the actor's side of a grab contact: facing each other it is
    the front hold; facing the same way, only with him ahead of the actor (its
    back hold on him) -- a body the walking box meets *behind* the actor's
    origin is no hold at all, and ``$A04A`` puts him straight back to state 1."""

    left = bool(a.facing_left)
    if left != g.facing_left:
        return True
    return int(g.x) < int(a.x) if left else int(g.x) >= int(a.x)


def _react(g: GruntSim, a: ActorSim, out: Outcome) -> bool:
    """``$A9BA``'s table: what a contact does to him. True when it ended his
    update (his state changed)."""

    if out is Outcome.HIT:
        a.latch = 1
        return False
    if out is Outcome.STRUCK:
        a.latch = 2
        if getattr(a, "knockdown", False):
            _knock_down(g, a)
            return True
        _goto(g, 0x0200)
        return True
    if out is Outcome.GRAB:
        a.latch = 3
        _goto(g, 0x0500)
        if not takes_hold(a, g):
            g.flags = 0x40  # $A04A with the holder's +$7D clear: state 1 next update
        return True
    if out is Outcome.KNOCKED:
        _goto(g, 0x0300)
        g.hp -= getattr(a, "weapon_damage", 0) or 4
        g.attack_id = g.body_id = 0
        if g.hp < 0:
            _goto(g, 0x0600)
            g.alive = False
        return True
    return False


def _knock_down(g: GruntSim, a: ActorSim) -> None:
    """``$991A``'s flight and floor: out of the fight past any horizon the
    plan looks at -- held there, no box and no body."""

    _goto(g, 0x0300)
    g.hp -= a.damage or 1
    g.attack_id = g.body_id = 0
    if g.hp < 0:
        _goto(g, 0x0600)
        g.alive = False


def _contact_signal(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E7B0``: Signal's box on the actor is his hold on it (``$0C``), when
    the actor holds nobody and the heights are within 8; otherwise nothing."""

    out = contact(g, a)
    if out is Outcome.HIT:
        if not a.holding and abs(a.z - _hi(g.z)) < GRAB_Z:
            a.latch = 1
            _goto(g, 0x0C00)
            return Outcome.SEIZED
        return Outcome.NONE
    _react(g, a, out)
    return out


def _contact(g: GruntSim, a: ActorSim) -> tuple[Outcome, bool]:
    """The state's contact test: (outcome, whether his update ended)."""

    if g.type == SIGNAL:
        if _action(a) == 0x5C:
            _goto(g, 0x0D00)
            return Outcome.NONE, True
        out = _contact_signal(g, a)
        return out, out in (Outcome.STRUCK, Outcome.GRAB, Outcome.SEIZED, Outcome.KNOCKED)
    out = contact(g, a)
    return out, _react(g, a, out)


def _action(a: ActorSim) -> int:
    """The target's ``+$30`` with the facing bit off (idle when unknown)."""

    action = getattr(a, "action", None)
    return (action or 0x02) & 0xFE


def _target_down(a: ActorSim) -> bool:
    """``$54``-``$5C``: falling, lying or getting up."""

    return PLAYER_DOWN_RANGE[0] <= _action(a) < PLAYER_DOWN_RANGE[1]


def _target_anim_facing(a: ActorSim) -> int:
    anim = getattr(a, "anim", None)
    if anim is None:
        return ANIM_MIRROR if a.facing_left else 0
    return anim & ANIM_MIRROR


def _rand(g: GruntSim, bits: int) -> int:
    """``$104D8`` (and ``$FB09``), as the rollout's ``rng`` stands for them."""

    return g.rng & bits


# --- Shared states ----------------------------------------------------------------------------


def _st_reselect(g: GruntSim, a: ActorSim) -> Outcome:
    table = PERSONALITY.get(g.type)
    if table is None:
        return Outcome.NONE
    index = g.param & 0x0F
    _goto(g, table[index] if index < len(table) else table[0])
    return Outcome.NONE


def _st_evade(g: GruntSim, a: ActorSim) -> Outcome:
    """``$DBCC``: garcia.py's state 7, with the round's lane direction."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        if g.type not in (GARCIA_KNIFE, GARCIA_BAT):
            _set_anim(g, 0x00, a)
        g.reload, g.countdown = 4, 1
        g.animating = True
        g.vx = 0.0
        g.flags &= ~0x04
        if int(g.x) >= int(a.x):
            g.flags |= 0x04
        speed = EVADE_LANE_SPEED
        for at_least, fast in EVADE_LANE_FAST:
            if g.repeats >= at_least:
                speed = fast
                break
        down = True
        if g.level == 5:
            down = True
        elif g.level == 6:
            down = int(g.x) < 0x388
        elif g.level == 3:
            down = False
        elif g.type == SIGNAL:
            down = True
        else:
            down = int(a.y) < EVADE_SPLIT
        g.vy = speed if down else -speed
    out, ended = _contact(g, a)
    if ended:
        return out
    _face(g, a)
    if not g.flags & 0x02:
        if (g.vy >= 0 and int(g.y) > EVADE_BOTTOM) or (g.vy < 0 and int(g.y) < EVADE_TOP):
            g.flags |= 0x02
            g.t50 = 0
        else:
            _move(g)
            return out
    if g.t50 == 0:
        updates = EVADE_LEG_UPDATES[_rand(g, 3)]
        speed, reload = EVADE_LEGS[(g.rng >> 2) & 3]
        g.t50 = updates
        g.vx = -speed if g.flags & 0x04 else speed
        g.reload, g.countdown = reload, 1
        return out
    g.t50 -= 1
    if g.vx < 0:
        if int(a.x) - EVADE_PAST_DX > int(g.x):
            _goto(g, 0x0100)
            return out
    elif not int(a.x) + EVADE_PAST_DX > int(g.x):
        _goto(g, 0x0100)
        return out
    _advance_x(g)
    return out


def _st_hitstun(g: GruntSim, a: ActorSim) -> Outcome:
    """``$9B36``/``$9B88``: 24 updates; a walking box on him in them is the
    hold, a fresh strike another 24."""

    if not g.flags & 0x01:
        g.flags |= 0x01 | 0x02
        g.animating = False
        _set_anim(g, 0x08, a)
        g.t50 = HITSTUN_UPDATES
        g.hp -= a.damage or 1
        g.x += HIT_PUSH if g.facing_left else -HIT_PUSH
        if g.hp < 0:
            _goto(g, 0x0600)
            g.alive = False
        return Outcome.NONE
    out = contact(g, a)
    if out is Outcome.GRAB or out is Outcome.KNOCKED:
        _react(g, a, out)
        return out
    if out is Outcome.STRUCK:
        a.latch = 2
        if getattr(a, "knockdown", False):
            _knock_down(g, a)
            return out
        g.hp -= a.damage or 1
        if g.hp < 0:
            _goto(g, 0x0300)
            return out
        g.t50 = HITSTUN_UPDATES
    g.t50 -= 1
    if g.t50 <= 0:
        _goto(g, 0x0100)
    return out if out is not Outcome.HIT else Outcome.NONE


def _st_inert(g: GruntSim, a: ActorSim) -> Outcome:
    """Knocked down, held, dying: no box in the fight."""

    if g.state == ST_HELD and g.flags & 0x40:
        _goto(g, 0x0100)
        return Outcome.NONE
    if g.state == ST_DYING or g.hp < 0:
        g.alive = False
    g.attack_id = 0
    return Outcome.NONE


# --- Garcia $22 (and the $21/$22 approach and punch) -------------------------------------------


def _jab_trigger(g: GruntSim, a: ActorSim) -> bool:
    """``$E102``: the jab's box on the target's body -- the punch."""

    if _trigger(g, a, _mirrored(g, 0x12)):
        _goto(g, 0x0A00)
        return True
    return False


def _close_or_jab(g: GruntSim, a: ActorSim) -> bool:
    """``$E0EC``: within 48 px on X it is ``$DBCC``, else the jab trigger."""

    if abs(int(a.x) - int(g.x)) < 0x30:
        _goto(g, 0x0700)
        return True
    return _jab_trigger(g, a)


def _st_approach(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E124``: toward 32 px short of the target on its lane, 48 updates."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        _set_anim(g, 0x00, a)
        g.animating = True
        g.reload, g.countdown = 3, 1
        g.t50 = 0x30
        g.speed = 0x300 if g.param & 0x20 else 0x480
    out, ended = _contact(g, a)
    if ended:
        return out
    g.t50 -= 1
    if g.t50 <= 0:
        _goto(g, 0x0100)
        return out
    _point_9648(g, a, 0x20)
    if _approach(g):
        _goto(g, 0x0700)
        return out
    _move(g)
    _jab_trigger(g, a)
    return out


def _st_punch(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E190``: the jab (frames 0 and 3), then the punch ``$3E`` (7-9) if it
    reaches the target's body on frame 6."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        if _refused_off_screen(g):
            return Outcome.NONE
        g.animating = True
        _set_anim(g, 0x14, a)
        if g.flags & 0x04:
            g.reload = g.countdown = 4
    out = contact(g, a)
    if out is Outcome.HIT:
        a.latch = 1
        return out
    if _react(g, a, out):
        return out
    if not g.flags & 0x02 and g.frame == 6:
        g.flags |= 0x02
        if not _trigger(g, a, _mirrored(g, 0x3E)):
            _goto(g, 0x0100)
            return out
    if g.frame == 9:
        _goto(g, 0x0100)
    return out


def _st_22_wait(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E07C``: 16 updates on the spot; within 48 px ``$DBCC``, the jab's
    box on the target the punch; then within 32 lanes the approach."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        if _refused_off_screen(g):
            return Outcome.NONE
        _set_anim(g, 0x00, a)
        g.frame = 1
        _latch(g)
        g.t50 = 0x10
        g.animating = False
    out, ended = _contact(g, a)
    if ended or _close_or_jab(g, a):
        return out
    g.t50 -= 1
    if g.t50 > 0:
        return out
    if abs(int(a.y) - int(g.y)) < 0x20:
        _goto(g, 0x0900)
    else:
        _goto(g, 0x0100)
    return out


def _st_22_wander(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E20A``: one walk cycle toward a random point near the ``$9654`` one;
    the jab's box on the target is the punch."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x00, a)
        g.frame = 1
        _latch(g)
        ox, oy = WANDER_OFFSETS[g.rng & 0x0F]
        _point_9654(g, a)
        g.aim_x += ox
        g.aim_y += oy
        g.speed, reload = WANDER_SPEEDS[int(g.x) & 3]
        g.reload, g.countdown = reload, 1
        _approach(g)
    out, ended = _contact(g, a)
    if ended or _jab_trigger(g, a):
        return out
    if g.frame == 1:
        if g.flags & 0x08:
            _goto(g, WANDER_NEXT[g.rng & 7])
            return out
    else:
        g.flags |= 0x08
    _move(g)
    return out


def _st_22_stand(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E2DC``: stand a random while; within 48 px ``$DBCC``, the jab's box
    on the target the punch; then the wander."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        _set_anim(g, 0x00, a)
        g.frame = 1
        _latch(g)
        g.animating = False
        g.t50 = STAND_UPDATES[g.rng & 3]
    out, ended = _contact(g, a)
    if ended or _close_or_jab(g, a):
        return out
    g.t50 -= 1
    if g.t50 <= 0:
        _goto(g, 0x0B00)
    return out


def _st_22_stalk(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E01E``: to the ``$9654`` point at 2.5 px an update, 80 updates."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.t50 = 0x50
        g.speed = 0x280
        g.animating = True
        _set_anim(g, 0x00, a)
        g.frame = 1
        g.countdown = 1
        _latch(g)
    out, ended = _contact(g, a)
    if ended:
        return out
    g.t50 -= 1
    if g.t50 <= 0:
        _goto(g, 0x0C00)
        return out
    _point_9654(g, a)
    if _approach(g):
        _goto(g, 0x0B00)
        return out
    _move(g)
    return out


def _st_22_lying(g: GruntSim, a: ActorSim) -> Outcome:
    """``$DE78``: lying in wait, 128 updates or until the target is within 80
    px on X."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = False
        _set_anim(g, 0x04, a)
        g.frame = 3
        _latch(g)
        g.t50 = 0x80
    g.t50 = (g.t50 - 1) & 0xFF
    if g.t50 == 0 or abs(int(a.x) - int(g.x)) < 0x50:
        _goto(g, 0x0100)
        g.param = 0
    return Outcome.NONE


def _st_22_corner(g: GruntSim, a: ActorSim) -> Outcome:
    """``$DF52`` (personality 1): to the top of the street at the screen's far
    side from the target (cam + $130, or + $10) at 4 px an update; there,
    within 88 px on X ``$DBCC``, the target down the rush, and after 96
    updates the punch."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x00, a)
        g.speed = 0x400
        g.t50 = 0x60
    out, ended = _contact(g, a)
    if ended:
        return out
    g.aim_x = g.cam_x + (0x130 if int(a.x) < int(g.x) else 0x10)
    g.aim_y = 0x10
    _face(g, a)
    if not _approach(g):
        g.animating = True
        _move(g)
        return out
    g.frame, g.countdown = 1, 1
    if abs(int(a.x) - int(g.x)) < 0x58:
        _goto(g, 0x0700)
        return out
    if _action(a) in PLAYER_KNOCKED_DOWN:
        _goto(g, 0x1000)
        return out
    g.animating = False
    g.t50 -= 1
    if g.t50 <= 0:
        _goto(g, 0x0A00)
        g.flags |= 0x04
    return out


def _st_22_rush(g: GruntSim, a: ActorSim) -> Outcome:
    """``$DEC6``: at 5 px an update to 32 px from the target on its lane, then
    ``$DF0A``'s three jabs."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        g.off_y = 0
        _set_anim(g, 0x00, a)
        g.reload, g.countdown = 3, 1
        g.off_x = 0x20
        g.speed = 0x500
    out, ended = _contact(g, a)
    if ended:
        return out
    _point_9654(g, a)
    if _approach(g):
        _goto(g, 0x1100)
        return out
    _move(g)
    return out


def _st_22_jabs(g: GruntSim, a: ActorSim) -> Outcome:
    """``$DF0A``: the punch animation at reload 3, cut at frame 6 three times."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        if _refused_off_screen(g):
            return Outcome.NONE
        _set_anim(g, 0x14, a)
        g.reload, g.countdown = 3, 3
        g.t50 = 3
    out = contact(g, a)
    if out is Outcome.HIT:
        a.latch = 1
        _goto(g, 0x0100)
        return out
    if _react(g, a, out):
        return out
    if g.frame == 6:
        g.frame = 0
        g.t50 -= 1
        if g.t50 <= 0:
            _goto(g, 0x0100)
    return out


# --- Garcia $21: from behind ------------------------------------------------------------------


def _faced_by_target(g: GruntSim, a: ActorSim) -> bool:
    """``$DA6C``: the target faces him (to his left facing right, or to his
    right facing left)."""

    if int(g.x) > int(a.x):
        return bool(a.facing_left)
    return not a.facing_left


def _st_21_approach(g: GruntSim, a: ActorSim) -> Outcome:
    """``$D9BC``: to the ``$9654`` point at 2 px an update, 80 updates."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x00, a)
        g.speed = 0x200
        g.countdown = 1
        g.t50 = 0x50
    g.t50 -= 1
    if g.t50 <= 0:
        _goto(g, 0x0C00)
        return Outcome.NONE
    out, ended = _contact(g, a)
    if ended:
        return out
    _point_9654(g, a)
    _face(g, a)
    if _approach(g):
        _goto(g, 0x0C00)
        return out
    _move(g)
    return out


def _st_21_wait(g: GruntSim, a: ActorSim) -> Outcome:
    """``$DA10``: 40 updates on the ``$9654`` point -- off it (the target
    moved), or out of time, ``$DBCC``; faced by the target, the rush."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = False
        g.t50 = 0x28
    out, ended = _contact(g, a)
    if ended:
        return out
    _point_9654(g, a)
    if not _approach(g):
        _goto(g, 0x0B00 if g.param == 1 else 0x0700)
        return out
    g.t50 -= 1
    if g.t50 <= 0:
        _goto(g, 0x0B00 if g.param == 1 else 0x0700)
        return out
    if _faced_by_target(g, a):
        g.animating = True
        _goto(g, 0x0800)
    return out


def _st_21_rush(g: GruntSim, a: ActorSim) -> Outcome:
    """``$DA98``: while the target faces him, at its spot at 4.5 px an update
    with box ``$1E`` (-13..+13, lanes +-10) out; its touch is his hold on the
    target (``$09``)."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.reload = 3
        g.speed = 0x480
    if not _faced_by_target(g, a):
        _goto(g, 0x0100)
        return Outcome.NONE
    g.attack_id = 0x1E
    out = contact(g, a)
    if out is Outcome.HIT:
        a.latch = 1
        if not a.holding:
            _goto(g, 0x0900)
            return Outcome.SEIZED
        _goto(g, 0x0C00)
        return out
    if _react(g, a, out):
        return out
    _point_9648(g, a, 0)
    if _approach(g):
        _goto(g, 0x0100)
        return out
    _move(g)
    return out


# --- Garcia $20: the knife --------------------------------------------------------------------


def _st_20_run(g: GruntSim, a: ActorSim) -> Outcome:
    """``$D6C0``: the entry run, 5 px an update at the target's spot, box
    ``$01`` (his body) on every frame; past the target he brakes 0.1875 an
    update, and under 1 px an update it is ``$D7BE``."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        _set_anim(g, 0x38, a)
        _toward_target(g, a, 0x500)
        g.animating = True
        if _refused_off_screen(g):
            return Outcome.NONE
    out, ended = _contact(g, a)
    if ended:
        return out
    if not g.flags & 0x02:
        tx = int(a.x)
        passed = tx > int(g.x) if g.vx < 0 else tx < int(g.x)
        if not passed:
            _move(g)
            return out
        g.flags |= 0x02
        g.reload, g.countdown = 6, 6
    brake = 0.1875 if g.vx < 0 else -0.1875
    g.vx += brake
    if abs(g.vx) >= 1.0:
        _move(g)
        return out
    _goto(g, 0x0800)
    return out


def _st_20_walk(g: GruntSim, a: ActorSim) -> Outcome:
    """``$D76A``: armed (animation ``$1C``), to the ``$9654`` point at 2.25 px
    an update; there, ``$D7BE``."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x1C, a)
        g.countdown = 1
        g.speed = 0x240
    out, ended = _contact(g, a)
    if ended:
        return out
    _point_9654(g, a)
    if _approach(g):
        _goto(g, 0x0800)
        return out
    _move(g)
    return out


def _st_20_decide(g: GruntSim, a: ActorSim) -> Outcome:
    """``$D7BE``: 24 updates facing the target; then out of 16 lanes ``$DBCC``,
    within 96 px on X the stab (``$09``), beyond it the throw (``$0A``)."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.t50 = 0x18
        g.animating = False
        _face(g, a)
    out, ended = _contact(g, a)
    if ended:
        return out
    g.t50 -= 1
    if g.t50 > 0:
        return out
    if g.param == 1:
        _goto(g, 0x0100)
        return out
    if abs(int(a.y) - int(g.y)) > 16:
        g.off_y = -g.off_y
        _goto(g, 0x0700)
        return out
    if _refused_off_screen(g):
        return out
    _goto(g, 0x0900 if abs(int(g.x) - int(a.x)) < 0x60 else 0x0A00)
    return out


def _st_20_stab(g: GruntSim, a: ActorSim) -> Outcome:
    """``$D856``: toward 32 px from the target on its lane at 3 px an update
    until the blade's ``$14`` (32-56 px ahead) meets its body; then animation
    ``$2C`` -- his body box, then the blade -- again while it still meets."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        g.speed = 0x300
    out, ended = _contact(g, a)
    if ended:
        return out
    if not g.flags & 0x02:
        if not _trigger(g, a, _mirrored(g, 0x14)):
            _point_9648(g, a, 0x20)
            if _approach(g):
                _goto(g, 0x0700)
                return out
            _move(g)
            return out
        g.flags |= 0x02
        _set_anim(g, 0x2C, a)
        g.reload, g.countdown = 4, 4
        return out
    if g.frame != 2:
        return out
    if _trigger(g, a, _mirrored(g, 0x14)):
        g.frame = 0
        _latch(g)
    else:
        _goto(g, 0x0100)
    return out


def _st_20_throw(g: GruntSim, a: ActorSim) -> Outcome:
    """``$D8EC``: animation ``$28``; on frame 1 the knife flies (not modelled:
    ``grunt_plan`` reads the flying knife as a projectile); on 2 it is done."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x28, a)
    out, ended = _contact(g, a)
    if ended:
        return out
    if not g.flags & 0x02 and g.frame == 1:
        g.flags |= 0x02
        g.armed = False
        # $5D84, on the knife's own update after this one: 48 px on from where
        # frame 0 held it ($60A0: -8, -54), 16 px higher, 16 px an update.
        side = -1 if g.facing_left else 1
        g.thrown = KnifeSim(
            x=g.x + side * (KNIFE_HAND_X + KNIFE_LAUNCH_X), y=g.y,
            z=g.z + KNIFE_HAND_Z + KNIFE_LAUNCH_Z, vx=side * KNIFE_SPEED,
        )
    if g.frame == 2:
        _goto(g, 0x0100)
    return out


# --- Garcia $23: the bat and pipe -------------------------------------------------------------


def _st_23_walk(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E3A0``: armed (``$20``/``$24``), to the ``$9654`` point at 2.5 px an
    update; there, ``$E404``."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.speed = 0x280
        g.animating = True
        _set_anim(g, 0x24 if g.param else 0x20, a)
        g.countdown = 1
    out, ended = _contact(g, a)
    if ended:
        return out
    _point_9654(g, a)
    if _approach(g):
        _goto(g, 0x0800)
        return out
    _move(g)
    return out


def _st_23_decide(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E404``: 16 updates standing; within 32 lanes the swing's walk-up
    (``$0C``), else ``$DBCC`` on an odd X."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        _set_anim(g, 0x24 if g.param else 0x20, a)
        g.frame = 1
        _latch(g)
        g.t50 = 0x10
        g.animating = False
    out, ended = _contact(g, a)
    if ended:
        return out
    g.t50 -= 1
    if g.t50 > 0:
        return out
    if abs(int(a.y) - int(g.y)) < 0x20:
        _goto(g, 0x0C00)
        return out
    g.off_y = -g.off_y
    _goto(g, 0x0700 if int(g.x) & 1 else 0x0C00)
    return out


def _st_23_walk_up(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E348``: to 64 px from the target on its lane at 3.5 px an update, 48
    updates; there (on screen), the swing."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        g.reload, g.countdown = 3, 3
        g.t50 = 0x30
        g.speed = 0x380
    out, ended = _contact(g, a)
    if ended:
        return out
    g.t50 = (g.t50 - 1) & 0xFF
    if g.t50 & 0x80:
        _goto(g, 0x0100)
        return out
    _face(g, a)
    _point_9648(g, a, 0x40)
    if _approach(g):
        if _on_screen(g):
            _goto(g, 0x0900)
        else:
            _goto(g, 0x0700)
        return out
    _move(g)
    return out


def _st_23_swing(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E47E``: animation ``$30``/``$34`` at reload 3 -- wind-up on frames
    0-2, box ``$18`` (24-72 px ahead) on 3-5; frame 5 ends it."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        _set_anim(g, 0x34 if g.param else 0x30, a)
        g.animating = True
        g.reload, g.countdown = 3, 3
    out, ended = _contact(g, a)
    if ended:
        return out
    if g.frame == 5:
        _goto(g, 0x0100)
    return out


# --- Signal $24 -------------------------------------------------------------------------------


def _st_24_approach(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E4F6``: to the ``$9654`` point at 2 px an update, facing, 96 updates;
    there the dash (``$0A``), out of time ``$E5EC``."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x00, a)
        g.countdown = 1
        g.speed = 0x200
        g.t50 = 0x60
    g.t50 -= 1
    if g.t50 <= 0:
        _goto(g, 0x0800)
        return Outcome.NONE
    out, ended = _contact(g, a)
    if ended:
        return out
    _face(g, a)
    _point_9654(g, a)
    if _approach(g):
        _goto(g, 0x0A00)
        return out
    _move(g)
    return out


def _st_24_dash(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E54E``: 2.5 px an update on X and 2 on the lane at the ``$9654``
    point, X until past it, then the lane; then ``$E5EC``."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        _point_9654(g, a)
        g.vx = 2.5 if g.aim_x > int(g.x) else -2.5
        g.vy = 2.0 if g.aim_y > int(g.y) else -2.0
    out, ended = _contact(g, a)
    if ended:
        return out
    if not g.flags & 0x02:
        blocked = not _advance_x(g)
        if not blocked:
            if g.vx >= 0 and int(g.x) < g.aim_x or g.vx < 0 and int(g.x) >= g.aim_x:
                return out
        g.flags |= 0x02
    if not _advance_lane(g):
        g.vy = -g.vy
    if g.vy >= 0 and int(g.y) >= g.aim_y or g.vy < 0 and int(g.y) < g.aim_y:
        _goto(g, 0x0800)
    return out


def _st_24_decide(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E5EC``: 24 updates on the spot (``$DBCC`` off screen, or with the
    target down); then within 128 of ``$98E8``'s distance the walk-in (``$09``)
    -- the slide (``$0B``) when ``+$40`` is set and the target is within 8
    lanes -- and beyond it the approach."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        if not _on_screen(g):
            _goto(g, 0x0700)
            return Outcome.NONE
        g.animating = False
        g.t50 = 0x18
    out, ended = _contact(g, a)
    if ended:
        return out
    if _action(a) == 0x4A or _target_down(a):
        _goto(g, 0x0700)
        return out
    g.t50 -= 1
    if g.t50 > 0:
        return out
    dx, dy = abs(a.x - g.x), abs(a.y - g.y)
    distance = max(dx, dy) + 3.0 * min(dx, dy) / 8.0
    if distance >= 0x80:
        _goto(g, 0x0100)
        return out
    if g.param and int(a.y) - 8 < int(g.y) <= int(a.y) + 8:
        _goto(g, 0x0B00)
    else:
        _goto(g, 0x0900)
    return out


def _st_24_walk_in(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E684``: at the target's own spot at 3.5 px an update, facing, 48
    updates -- his body box is his hold on it."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        g.reload, g.countdown = 3, 3
        g.t50 = 0x30
        g.speed = 0x380
    out, ended = _contact(g, a)
    if ended:
        return out
    g.t50 = (g.t50 - 1) & 0xFF
    if g.t50 & 0x80 or _action(a) in (0x5C, 0x4A, 0x78, 0x82):
        _goto(g, 0x0100)
        return out
    _face(g, a)
    _point_9648(g, a, 0)
    if _approach(g):
        _goto(g, 0x0100)
        return out
    _move(g)
    return out


def _st_24_slide(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E80A``: animation ``$18``; from frame 1, 7 px an update his way
    falling off by 0.15625, 26 updates, box ``$0F`` at the feet and no body;
    then 8 updates getting up."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        if not (ON_SCREEN[0] <= g.screen_x < ON_SCREEN[1]):
            _goto(g, 0x0700)
            return Outcome.NONE
        g.animating = True
        _set_anim(g, 0x18, a)
        g.t50 = 0x1A
    if g.flags & 0x04:
        g.t50 -= 1
        if g.t50 <= 0:
            _goto(g, 0x0100)
        return Outcome.NONE
    out = contact(g, a)
    if out is Outcome.HIT:
        a.latch = 1
    elif _react(g, a, out):
        return out
    if g.animating:
        if not g.frame:
            return out
        g.animating = False
        g.vx = -7.0 if g.facing_left else 7.0
        g.vy = 0.0
    g.vx += 0.15625 if g.vx < 0 else -0.15625
    g.t50 -= 1
    if g.t50 > 0:
        _move(g)
        return out
    g.flags |= 0x04
    g.t50 = 8
    g.frame = 3
    _latch(g)
    return out


def _st_24_holding(g: GruntSim, a: ActorSim) -> Outcome:
    """``$E6F2``: his hold on the actor -- the throw."""

    return Outcome.SEIZED


# --- HakuRo $25 -------------------------------------------------------------------------------


def _st_25_approach(g: GruntSim, a: ActorSim) -> Outcome:
    """``$EB2A``: to the ``$9654`` point at 2 px an update, facing; there the
    stalk (``$08``)."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x00, a)
        g.countdown = 1
        g.speed = 0x200
    out, ended = _contact(g, a)
    if ended:
        return out
    _face(g, a)
    _point_9654(g, a)
    if _approach(g):
        _goto(g, 0x0800)
        return out
    _move(g)
    return out


def _st_25_stalk(g: GruntSim, a: ActorSim) -> Outcome:
    """``$EC88``: on the ``$9654`` point, facing; ``+$40`` set and within 64 px
    the backflip (``$0C``); 5 changes of the target's X velocity, or 48 moves,
    and the lane align (``$09``)."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.t50 = 8
        _set_anim(g, 0x00, a)
        g.w54 = _hi(a.vx or 0.0)
        g.t51 = 5
        g.t52 = 0x30
    out, ended = _contact(g, a)
    if ended:
        return out
    _face(g, a)
    if g.param and abs(int(a.x) - int(g.x)) < 0x40:
        _goto(g, 0x0C00)
        return out
    vx = _hi(a.vx or 0.0)
    if vx != g.w54:
        g.t51 -= 1
        if g.t51 <= 0:
            _goto(g, 0x0900)
            return out
    g.w54 = vx
    _point_9654(g, a)
    if _approach(g):
        g.t52 -= 1
        if g.t52 <= 0:
            _goto(g, 0x0900)
            return out
        g.animating = False
        g.t50 = 8
        g.frame, g.countdown = 1, 1
        return out
    g.animating = True
    _advance_lane(g)
    if g.t50 == 0:
        g.animating = True
        _advance_x(g)
        return out
    g.t50 -= 1
    return out


def _st_25_align(g: GruntSim, a: ActorSim) -> Outcome:
    """``$ED44``: 4 lanes an update onto the target's; then (random) the rush
    (``$0F``), within 96 px the dash (``$0E``), beyond it the flying kick."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        if _refused_off_screen(g):
            return Outcome.NONE
        g.animating = True
        g.countdown = 1
        g.vy = 4.0 if int(a.y) >= int(g.y) else -4.0
    out, ended = _contact(g, a)
    if ended:
        return out
    _face(g, a)
    ty = int(a.y)
    if g.vy >= 0 and ty >= int(g.y) or g.vy < 0 and ty < int(g.y):
        _advance_lane(g)
        return out
    if not g.rng & 7:
        _goto(g, 0x0F00)
    elif abs(int(a.x) - int(g.x)) < 0x60:
        _goto(g, 0x0E00)
    else:
        _goto(g, 0x0B00)
    return out


def _st_25_strike(g: GruntSim, a: ActorSim) -> Outcome:
    """``$EB6E``: animation ``$14`` -- ``$06`` (0-44 px ahead, the whole
    height) on frames 1-3; frame 3 turns into the backflip."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        if _refused_off_screen(g):
            return Outcome.NONE
        _set_anim(g, 0x14, a)
        g.animating = True
    out, ended = _contact(g, a)
    if ended:
        return out
    if g.frame == 3:
        _goto(g, 0x0C00)
        g.flags |= 0x04
    return out


def _st_25_dash(g: GruntSim, a: ActorSim) -> Outcome:
    """``$EF0A``: 128 updates at 4.5 px an update toward 56 px short of the
    target; ``$06`` on its body is the strike, level within 72 px the jump
    kick."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x00, a)
        g.reload, g.countdown = 3, 1
        g.frame = 1
        _latch(g)
        g.t50 = 0x80
    g.t50 = (g.t50 - 1) & 0xFF
    if g.t50 == 0:
        _goto(g, 0x0100)
        return Outcome.NONE
    out, ended = _contact(g, a)
    if ended:
        return out
    speed = 0x580 if g.flags & 0x02 else 0x480
    if g.param & 0x20:
        speed = 0x300
    _toward_target(g, a, speed, lead_x=0x38)
    _move(g)
    if _trigger(g, a, _mirrored(g, 0x06)):
        _goto(g, 0x0A00)
        return out
    if abs(int(g.y) - int(a.y)) < 8 and abs(int(g.x) - int(a.x)) < 0x48:
        _goto(g, 0x0D00)
    return out


def _st_25_jump_kick(g: GruntSim, a: ActorSim) -> Outcome:
    """``$EBAC``: the strike's animation in a hop (7 px an update, up 3) -- on
    the ground when within 48 px."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        if _refused_off_screen(g):
            return Outcome.NONE
        g.animating = False
        _set_anim(g, 0x14, a)
        g.vx = -7.0 if g.facing_left else 7.0
        g.vz = -3.0
        g.countdown = 1
        if abs(int(a.x) - int(g.x)) <= 0x30:
            g.flags |= 0x02
            g.animating = True
            g.frame = 1
            _latch(g)
    out, ended = _contact(g, a)
    if ended:
        return out
    if not g.flags & 0x02:
        _advance_x(g)
        if not _fall(g):
            return out
        g.flags |= 0x02
        g.animating = True
    if g.frame == 3:
        r = g.rng & 3
        if r == 0:
            _goto(g, 0x0C00)
            g.flags |= 0x04
        elif r == 1:
            _goto(g, 0x0F00)
            g.flags |= 0x02
        else:
            _goto(g, 0x0100)
    return out


def _st_25_flying_kick(g: GruntSim, a: ActorSim) -> Outcome:
    """``$EDD8``: animation ``$18`` (``$0C``, 8-48 px ahead, knee height) in a
    leap -- 10 px an update, up 10; a grab of him in the air does not hold."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x18, a)
        g.vz = -10.0
        g.vx = -10.0 if g.facing_left else 10.0
    out = contact(g, a)
    if out is Outcome.HIT:
        a.latch = 1
    elif out is Outcome.STRUCK:
        a.latch = 2
        _knock_down(g, a)
        return out
    elif out is Outcome.KNOCKED:
        _react(g, a, out)
        return out
    if g.animating and g.frame == 1:
        g.animating = False
    _advance_x(g)
    if _fall(g):
        _goto(g, 0x0E00 if g.flags & 0x80 else 0x0100)
    return out


def _st_25_backflip(g: GruntSim, a: ActorSim) -> Outcome:
    """``$EE8A``: a backflip away (5 px an update back, up 16; or 3 and 14 from
    the strike); landed, the dash."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x1C, a)
        g.vz = -16.0
        speed = 5.0
        if g.flags & 0x04:
            g.vz = -14.0
            speed = -3.0
        g.vx = -speed if g.facing_left else speed
    if g.animating and g.frame == 5:
        g.animating = False
    _advance_x(g)
    if _fall(g):
        g.vz = 0.0
        _goto(g, 0x0E00)
    return Outcome.NONE


def _st_25_rush(g: GruntSim, a: ActorSim) -> Outcome:
    """``$EFB6``: at the target at 5 px an update; within 64 px he turns back
    and up the lanes for 12 updates."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x00, a)
        g.reload, g.countdown = 4, 1
        if g.flags & 0x02:
            g.vx = -g.vx
            g.t50 = 0x0C
            g.vy = -2.0
    out, ended = _contact(g, a)
    if ended:
        return out
    if g.flags & 0x02:
        if g.t50 == 0:
            _goto(g, 0x0100)
            return out
        g.t50 -= 1
        _move(g)
        return out
    _toward_target(g, a, 0x500)
    _move(g)
    if abs(int(a.x) - int(g.x)) < 0x40:
        g.flags |= 0x02
        g.vx = -g.vx
        g.t50 = 0x0C
        g.vy = -2.0
    return out


def _st_25_knockdown_hook(g: GruntSim, a: ActorSim) -> Outcome:
    g.attack_id = g.body_id = 0
    return Outcome.NONE


# --- HakuRo $2A: the trio ---------------------------------------------------------------------
#
# Table $103AE: $F7D8 spawns two more of the type and links the three (+$70
# the leader, +$72/+$74 the others, +$76 a bit per member); $F876 (1), $FA92
# ($0F) and $F9F0 ($10) keep them in a formation about cam + $A0, and share
# $25's strike, flying kick, backflip, jump kick and dash ($0A-$0E). The fight
# is in the charge, $FB40 (8).

# $FBDE, by +$40: the charge's stop -- within 80 px the wait before the dash
# (9), within 84 the flying kick ($0B), within 80 the backflip ($0C).
TRIO_CHARGE_STOPS = ((0x50, 0x0900), (0x54, 0x0B00), (0x50, 0x0C00))


def _st_2a_charge(g: GruntSim, a: ActorSim) -> Outcome:
    """``$FB40``: 4 px an update at the target, snapped to its lane, until the
    personality's distance; with ``+$31`` bit 3, 10 updates down first."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        if g.flags & 0x08:
            g.animating = False
            _set_anim(g, 0x04, a)
            g.frame = 3
            _latch(g)
            g.t50 = 0x0A
        else:
            g.animating = True
            _set_anim(g, 0x00, a)
            g.vx = -4.0 if g.facing_left else 4.0
            g.vy = 0.0
            g.reload, g.countdown = 3, 1
    if g.flags & 0x08:
        g.t50 -= 1
        if g.t50 <= 0:
            _goto(g, 0x0800)
        return Outcome.NONE
    out, ended = _contact(g, a)
    if ended:
        return out
    _move(g)
    g.y = a.y
    dx = abs(int(g.x) - int(a.x))
    reach, state = TRIO_CHARGE_STOPS[min(g.param, 2)]
    if dx < reach:
        _goto(g, state)
        if state == 0x0B00:
            g.flags |= 0x80
    return out


def _st_2a_wait(g: GruntSim, a: ActorSim) -> Outcome:
    """``$F9B6``: 16 updates on the spot, then the dash."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = False
        _set_anim(g, 0x00, a)
        g.frame = 1
        _latch(g)
        g.t50 = 0x10
    out, ended = _contact(g, a)
    if ended:
        return out
    g.t50 -= 1
    if g.t50 <= 0:
        _goto(g, 0x0E00)
    return out


def _st_passive(g: GruntSim, a: ActorSim) -> Outcome:
    """A state the model does not move (the trio's formation walks): his body
    still takes strikes and holds; he strikes nothing."""

    out, ended = _contact(g, a)
    return out


# --- Nora $26 ---------------------------------------------------------------------------------


def _st_26_chase(g: GruntSim, a: ActorSim) -> Outcome:
    """``$F0FC``: to the ``$9654`` point at 1.5 px an update, facing; the whip
    (``$08``) after 80 moves there, or when the target has turned to her
    twice; off the wide screen, or 80 updates, ``$DBCC``."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.animating = True
        _set_anim(g, 0x00, a)
        g.countdown = 1
        g.speed = 0x180
        g.t50 = 2
        g.t51 = 0x50
        g.t52 = 0x50
    g.t52 = (g.t52 - 1) & 0xFF
    if g.t52 == 0:
        _goto(g, 0x0700)
        return Outcome.NONE
    out, ended = _contact(g, a)
    if ended:
        return out
    if not _on_screen_wide(g):
        _goto(g, 0x0700)
        return out
    # Her animation word against the target's facing bit: a mismatch sets
    # +$52's bit 1; a match with it set clears it and counts one on +$50.
    if (_target_anim_facing(a) ^ g.anim) & 0xFFFF:
        g.t52 |= 0x02
    elif g.t52 & 0x02:
        g.t52 &= ~0x02
        g.t50 -= 1
        if g.t50 <= 0:
            _goto(g, 0x0800)
            return out
    _point_9654(g, a)
    _face(g, a)
    if not _approach(g):
        g.animating = True
        _move(g)
        return out
    g.countdown = 1
    g.animating = False
    g.t51 -= 1
    if g.t51 <= 0:
        _goto(g, 0x0800)
    return out


def _st_26_whip(g: GruntSim, a: ActorSim) -> Outcome:
    """``$F1B0``: toward 56 px from the target on its lane until the whip's
    box ``$22`` meets its body; then animation ``$14`` -- the lash on frame 2
    -- and on frame 4 done (three times running after the feint)."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        if _refused_off_screen(g):
            return Outcome.NONE
        g.animating = True
        _set_anim(g, 0x00, a)
        g.t51 = 0x50
        if g.flags & 0x04:
            g.reload, g.countdown = 3, 3
            g.t50 = 3
    out = contact(g, a)
    if out is Outcome.HIT:
        a.latch = 1
    elif _react(g, a, out):
        return out
    g.t51 = (g.t51 - 1) & 0xFF
    if g.t51 == 0:
        _goto(g, 0x0700 if g.param & 0x02 else 0x0100)
        return out
    if _target_down(a):
        return out
    if not g.flags & 0x02:
        if not _trigger(g, a, _mirrored(g, 0x22)):
            _point_9648(g, a, 0x38)
            if _approach(g):
                _goto(g, 0x0700 if g.param & 0x02 else 0x0100)
                return out
            _move(g)
            return out
        g.flags |= 0x02
        _set_anim(g, 0x14, a)
    if g.frame != 4:
        return out
    if g.flags & 0x04:
        _set_anim(g, 0x00, a)
        g.flags &= ~0x02
        g.t50 -= 1
        if g.t50 > 0:
            return out
    _goto(g, 0x0700 if g.param & 0x02 else 0x0100)
    return out


def _st_26_hitstun_entry(g: GruntSim, a: ActorSim) -> Outcome:
    """``$F062``: her hit goes through ``$0B`` (the ordinary hitstun), or the
    feint (``$0C``) with ``+$40`` bit 4."""

    if g.param & 0x10:
        _goto(g, 0x0C00)
        return _st_26_feint(g, a)
    g.state = 0x0B
    return Outcome.NONE


def _st_26_feint(g: GruntSim, a: ActorSim) -> Outcome:
    """``$F078``: lying 128 updates -- or until the target is 80 px away --
    then the whip three times running."""

    if not g.flags & 0x01:
        g.flags |= 0x01
        g.hp -= a.damage or 1
        if g.hp < 0:
            _goto(g, 0x0300)
            return Outcome.NONE
        _set_anim(g, 0x04, a)
        g.frame = 3
        _latch(g)
        g.animating = False
        g.t50 = 0x80
    g.t50 = (g.t50 - 1) & 0xFF
    if g.t50 == 0 or abs(int(a.x) - int(g.x)) >= 0x50:
        _goto(g, 0x0800)
        g.flags |= 0x04
    return Outcome.NONE


# --- The thrown knife (weapon ``$08`` in flight, ``+$30`` = 3) --------------------------------

KNIFE_TYPE = 0x08
KNIFE_FLYING = 0x03
KNIFE_SPEED = 16.0
KNIFE_HAND_X = -8  # $60A0, animation $28 frame 0
KNIFE_HAND_Z = -54
KNIFE_LAUNCH_X = 48  # $5D84
KNIFE_LAUNCH_Z = 16
# Box $FA/$FB (the flying knife's animation 4/6): -5..19 (right), lanes +-20,
# z -3..9 about its own origin -- 28 lanes each way against a body's 8.
KNIFE_BOXES = ((-5, 19, -20, 20, -3, 9), (-19, 5, -20, 20, -3, 9))


class KnifeSim:
    """A knife in flight: straight on at 16 px an update; its box on the
    actor's body is the hit, the actor's strike on it knocks it away."""

    __slots__ = ("x", "y", "z", "vx", "alive")

    def __init__(self, *, x: float, y: float, z: float, vx: float) -> None:
        self.x, self.y, self.z, self.vx = x, y, z, vx
        self.alive = True

    def copy(self) -> KnifeSim:
        return KnifeSim(x=self.x, y=self.y, z=self.z, vx=self.vx)

    def box(self) -> tuple[int, int, int, int, int, int]:
        shape = KNIFE_BOXES[1 if self.vx < 0 else 0]
        x, y, z = int(self.x), int(self.y), _hi(self.z)
        return (x + shape[0], x + shape[1], y + shape[2], y + shape[3], z + shape[4], z + shape[5])

    @classmethod
    def from_bytes(cls, data: bytes) -> KnifeSim:
        return cls(x=_s32(data, 0x10), y=_s32(data, 0x14), z=_s32(data, 0x18), vx=_s32(data, 0x1C))


def knife_update(k: KnifeSim, a: ActorSim, cam_x: int) -> Outcome:
    k.x += k.vx
    screen_x = int(k.x) - cam_x + SCREEN_BIAS
    if not (0x40 <= screen_x < 0x200):
        k.alive = False
        return Outcome.NONE
    if a.unavailable or a.latch:
        return Outcome.NONE
    b = k.box()
    if a.attack is not None and a.damage and overlaps(a.attack, b):
        k.alive = False
        return Outcome.NONE
    if a.body is not None and overlaps(b, a.body):
        k.alive = False
        a.latch = 1
        return Outcome.HIT
    return Outcome.NONE


def is_enemy_knife_in_flight(data: bytes) -> bool:
    """A knife thrown by an enemy, still flying: ``+$30`` = 3, a velocity, and
    its holder link (``+$52``, kept for the credit) on an enemy slot."""

    if (data[0x00] & 0x7F) != KNIFE_TYPE or data[0x30] != KNIFE_FLYING:
        return False
    if _s32(data, 0x1C) == 0:
        return False
    return _u16(data, 0x52) >= 0xB900


# --- Dispatch ---------------------------------------------------------------------------------

_COMMON = {
    ST_RESELECT: _st_reselect,
    ST_HITSTUN: _st_hitstun,
    ST_KNOCKDOWN: _st_inert,
    ST_PEPPER: _st_inert,
    ST_HELD: _st_inert,
    ST_DYING: _st_inert,
    ST_EVADE: _st_evade,
}
HANDLERS: dict[int, dict[int, object]] = {
    GARCIA: {
        **_COMMON,
        0x08: _st_22_wait, 0x09: _st_approach, 0x0A: _st_punch, 0x0B: _st_22_wander,
        0x0C: _st_22_stand, 0x0D: _st_evade, 0x0E: _st_22_stalk, 0x0F: _st_22_corner, 0x10: _st_22_rush,
        0x11: _st_22_jabs, 0x12: _st_22_lying,
    },
    GARCIA_GRABBER: {
        **_COMMON,
        ST_RESELECT: _st_21_approach, 0x08: _st_21_rush, 0x09: _st_24_holding, 0x0A: _st_punch,
        0x0B: _st_approach, 0x0C: _st_21_wait,
    },
    GARCIA_KNIFE: {
        **_COMMON,
        0x08: _st_20_decide, 0x09: _st_20_stab, 0x0A: _st_20_throw, 0x0B: _st_inert,
        0x0C: _st_20_run, 0x0D: _st_20_walk,
    },
    GARCIA_BAT: {
        **_COMMON,
        ST_RESELECT: _st_23_walk, 0x08: _st_23_decide, 0x09: _st_23_swing, 0x0A: _st_23_walk,
        0x0B: _st_inert, 0x0C: _st_23_walk_up,
    },
    SIGNAL: {
        **_COMMON,
        ST_RESELECT: _st_24_approach, 0x08: _st_24_decide, 0x09: _st_24_walk_in, 0x0A: _st_24_dash,
        0x0B: _st_24_slide, 0x0C: _st_24_holding, 0x0D: _st_inert,
    },
    HAKURO: {
        **_COMMON,
        ST_KNOCKDOWN: _st_25_knockdown_hook,
        0x08: _st_25_stalk, 0x09: _st_25_align, 0x0A: _st_25_strike, 0x0B: _st_25_flying_kick,
        0x0C: _st_25_backflip, 0x0D: _st_25_jump_kick, 0x0E: _st_25_dash, 0x0F: _st_25_rush,
        0x10: _st_inert, 0x11: _st_25_approach, 0x12: _st_inert,
    },
    HAKURO_TRIO: {
        **_COMMON,
        ST_RESELECT: _st_passive, 0x08: _st_2a_charge, 0x09: _st_2a_wait, 0x0A: _st_25_strike,
        0x0B: _st_25_flying_kick, 0x0C: _st_25_backflip, 0x0D: _st_25_jump_kick, 0x0E: _st_25_dash,
        0x0F: _st_passive, 0x10: _st_passive,
    },
    NORA: {
        **_COMMON,
        ST_HITSTUN: _st_26_hitstun_entry, 0x08: _st_26_whip, 0x09: _st_26_chase, 0x0B: _st_hitstun,
        0x0C: _st_26_feint,
    },
}

# The states each type's model replays exactly (``check_recording`` checks these).
MODELLED_STATES: dict[int, frozenset[int]] = {
    GARCIA: frozenset({0x01, 0x07, 0x08, 0x09, 0x0A, 0x0C, 0x0E, 0x0F, 0x10, 0x11}),
    GARCIA_GRABBER: frozenset({0x01, 0x07, 0x08, 0x0A, 0x0B, 0x0C}),
    GARCIA_KNIFE: frozenset({0x01, 0x07, 0x08, 0x09, 0x0A, 0x0C, 0x0D}),
    GARCIA_BAT: frozenset({0x01, 0x07, 0x08, 0x09, 0x0A, 0x0C}),
    SIGNAL: frozenset({0x01, 0x07, 0x08, 0x09, 0x0A, 0x0B}),
    HAKURO: frozenset({0x01, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x11}),
    NORA: frozenset({0x01, 0x07, 0x08, 0x09}),
    HAKURO_TRIO: frozenset({0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E}),
}


def grunt_update(g: GruntSim, a: ActorSim, *, rng: int | None = None) -> Outcome:
    """One update of his, then the renderer's tail (latch, step). ``rng``
    stands for ``$104D8``'s draws (and ``$FB09``'s frame counter)."""

    if rng is not None:
        g.rng = rng
    table = HANDLERS.get(g.type)
    handler = table.get(g.state) if table is not None else None
    out = handler(g, a) if handler is not None else Outcome.NONE
    _render(g)
    return out


def _render(g: GruntSim) -> None:
    """The renderer's tail: ``+$28``, the frame's boxes latched, then the
    countdown stepped while animating (``emit_object_sprite_mapping``)."""

    g.screen_x = int(g.x) - g.cam_x + SCREEN_BIAS
    state = g.state
    if state == ST_KNOCKDOWN or state == ST_DYING or (state == 0x12 and g.type == HAKURO):
        g.attack_id = g.body_id = 0
        return
    frames = ANIMS_FOR_TYPE.get(g.type, GARCIA_ANIMS).get(g.anim, _NO_ANIM)[1]
    frame = g.frame
    count = len(frames)
    g.attack_id, g.body_id = frames[frame if frame < count else count - 1]
    if g.animating:
        g.countdown -= 1
        if g.countdown <= 0:
            g.countdown = g.reload
            frame += 1
            g.frame = 0 if frame >= count else frame


def threat(g: GruntSim, a: ActorSim, *, updates: int, rng: int = 5) -> int | None:
    """The first update his box lands on the actor standing still, or None."""

    sim = g.copy()
    actor = a.copy()
    knives: list[KnifeSim] = []
    for k in range(updates):
        actor.latch = 0
        out = grunt_update(sim, actor, rng=rng)
        if out in (Outcome.HIT, Outcome.SEIZED):
            return k
        for knife in knives:
            if knife.alive and knife_update(knife, actor, sim.cam_x) is Outcome.HIT:
                return k
        if sim.thrown is not None:
            knives.append(sim.thrown)
            sim.thrown = None
        if not sim.alive and not knives:
            return None
    return None


# --- Checking the model against a recording ---------------------------------------------------

_FIELDS = ("x", "y", "vx", "vy", "state", "t50", "anim", "frame", "countdown", "attack_id", "body_id")


def _signature(g: GruntSim) -> tuple:
    return tuple(getattr(g, f) for f in _FIELDS) + (g.flags,)


def check_recording(rows: Sequence[dict], *, verbose: bool = False, level: int = 0) -> dict:
    """Replay every modelled enemy of a ``tools/grunt_lab.py`` recording,
    update by update (a frame on which his fields change), in the states the
    model replays; and every hit on the actor, by who landed it."""

    from collections import Counter

    from .mr_x import actor_from_bytes

    checked: Counter[str] = Counter()
    mismatched: Counter[str] = Counter()
    contacts: Counter[str] = Counter()
    examples: list[dict] = []
    prev = None
    for row in rows:
        if prev is None or "en" not in row:
            prev = row
            continue
        before = {i: bytes.fromhex(h) for i, h in prev.get("en", ())}
        after = {i: bytes.fromhex(h) for i, h in row.get("en", ())}
        actor = actor_from_bytes(bytes.fromhex(prev["p1"]), cam_x=prev["cam"])
        p1_after = bytes.fromhex(row["p1"])
        lvl = row.get("level", level)
        for i, data in sorted(before.items()):
            if i not in after or data[0] not in MODELLED_TYPES or after[i][0] != data[0]:
                continue
            g0 = GruntSim.from_bytes(data, slot=i, cam_x=prev["cam"], level=lvl)
            g1 = GruntSim.from_bytes(after[i], slot=i, cam_x=row["cam"], level=lvl)
            if _signature(g0) == _signature(g1):
                continue
            key = f"{g0.type:02x}:s{g0.state:02x}"
            if g1.state in (ST_KNOCKDOWN, ST_DYING) and g0.state not in (ST_KNOCKDOWN, ST_DYING):
                checked[f"{key}:knocked_by_other"] += 1
                continue
            if g0.state not in MODELLED_STATES.get(g0.type, ()):
                checked[f"{key}:skipped"] += 1
                continue
            best = None
            for rng in range(16):
                sim = g0.copy()
                a = actor.copy()
                out = grunt_update(sim, a, rng=rng)
                n = sum(1 for f in _FIELDS if not _same(getattr(sim, f), getattr(g1, f)))
                if best is None or n < best[0]:
                    best = (n, sim, a, out)
                if n == 0:
                    break
            _, sim, a, out = best
            his = 0xB900 + 0x80 * i
            by_him = _u16(p1_after, 0x7E) == his
            code = p1_after[0x7C] if by_him else 0
            actual = {1: "HIT", 2: "STRUCK", 3: "GRAB"}.get(code, "NONE")
            if out is not Outcome.NONE or actual != "NONE":
                contacts[f"{g0.type:02x}:{out.name}->{actual}"] += 1
            diffs = [f for f in _FIELDS if not _same(getattr(sim, f), getattr(g1, f))]
            checked[key] += 1
            for f in diffs:
                mismatched[f"{key}:{f}"] += 1
            if diffs and len(examples) < (200 if verbose else 40):
                examples.append({
                    "f": row["f"], "slot": i, "state": key, "flags": f"{g0.flags:02x}",
                    "diff": {f: [getattr(sim, f), getattr(g1, f)] for f in diffs},
                })
        prev = row
    return {
        "updates_checked": sum(v for k, v in checked.items() if not k.endswith((":skipped", ":knocked_by_other"))),
        "checked_by_state": dict(sorted(checked.items())),
        "mismatches": dict(sorted(mismatched.items())),
        "contacts": dict(contacts),
        "examples": examples,
    }


def _same(x, y) -> bool:
    if isinstance(x, float) or isinstance(y, float):
        return abs(float(x) - float(y)) < 1e-6
    return x == y
