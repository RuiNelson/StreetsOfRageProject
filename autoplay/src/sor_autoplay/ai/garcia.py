"""The type-``$22`` Garcia -- Mr. X's helpers (the user's "Glasia") -- as the ROM
plays it, for ``mr_x_plan``'s lookahead.

Decoded from ``$DD78 (garcia_type22_32_dispatcher)`` and the ordinary-enemy
framework it runs on, and checked in lockstep against the Garcias of
``tools/mr_x_lab.py``'s recordings (``check_recording``). The office sends them
in pairs, 9 health each on Normal, 8 damage a hit, and the pair Mr. X arrives
with is replaced as they die. What the plan needs from them:

Personality (``+$40`` low nibble, ``$DDDA`` through ``$933C``)
    Every reset (state 1, ``$DDCA``) lands in the state the table names: 0 the
    approach (9) -- Mr. X's pair --, 3 the stalk (``$E``).
The approach (state 9, ``$E124``)
    Toward the point 32 px short of the target on its lane (``$9648``), at
    4.5 px an update (3 with ``+$40`` bit 5) along ``$982C``'s quantized
    vector, for 48 updates; within 4 px of the point, ``$DBCC`` (7). After
    each move the jab's trigger (``$E102``): box ``$12``/``$13`` (0-40 px ahead,
    lane +-8, head height) on the target's cached body -- the punch (``$A``).
The punch (state ``$A``, ``$E190``)
    Off screen it is ``$DBCC`` instead (``$92AC``). Animation ``$14``: frame 0
    and 3 carry the jab box ``$12``, 7-9 the punch ``$3E`` (16-51 px), each
    frame 4 updates; the renderer latches a frame's boxes before stepping, so
    the jab is live on the entry update -- the trigger's next update. On frame 6
    ``$3E`` must already reach the target's body, or the punch ends there (1);
    on frame 9 it ends.
Contact (``$A9BA`` on ``$AA22``)
    The player's box on his body first (a strike: hitstun, 2; a walking box:
    the hold, 5), then his box on the player's body (the hit). Blaze's punch
    (18-68 px) out-reaches his jab trigger (0-40): a punch can land first.
"""

from __future__ import annotations

import math
from enum import Enum, auto
from typing import Sequence

from .jack import _vector_velocity
from .twins import ActorSim, overlaps

GARCIA_TYPES = frozenset({0x20, 0x21, 0x22, 0x23})
OFFICE_TYPE = 0x22

ST_INIT = 0x00
ST_RESELECT = 0x01  # $DDCA
ST_HITSTUN = 0x02  # $9B36
ST_KNOCKDOWN = 0x03  # $991A
ST_PEPPER = 0x04  # $A43E
ST_HELD = 0x05  # $A04A
ST_DYING = 0x06  # $9D16
ST_EVADE = 0x07  # $DBCC
ST_APPROACH = 0x09  # $E124
ST_PUNCH = 0x0A  # $E190
ST_WANDER = 0x0B  # $E20A
ST_STALK = 0x0E  # $E01E

# $DDDA: personality -> the state (and +$31) a reset lands in.
PERSONALITY_STATE = (0x0900, 0x0F00, 0x1200, 0x0E00, 0x1300, 0x1200, 0x08E8, 0x0000)

APPROACH_SPEED = 0x480
APPROACH_SPEED_SLOW = 0x300  # +$40 bit 5
APPROACH_UPDATES = 0x30
APPROACH_OFFSET = 0x20
ARRIVE = 4
STALK_SPEED = 0x280
STALK_UPDATES = 0x50
PUNCH_CHECK_FRAME = 6
PUNCH_END_FRAME = 9
HITSTUN_UPDATES = 0x18
HIT_PUSH = 2
LANE_MIN = 2.0  # $A00E: the step is refused outside [2, $70)
LANE_MAX = 112.0
X_MAX_ROUND_8 = 0x1400
EVADE_LANE_SPEED = 3.0
EVADE_SPLIT = 0x38
EVADE_BOTTOM = 0x58
EVADE_TOP = 0x18
EVADE_PAST_DX = 0x50
EVADE_WALK = 3.0
# $DBCC's walk past the target, in legs ($DD26): a random count from $1033A and
# a random speed and frame reload from $DD68.
EVADE_LEG_UPDATES = (16, 8, 10, 5)
EVADE_LEGS = ((2.5, 6), (3.0, 5), (4.0, 4), (5.0, 4))
# The lane speed: faster when he keeps landing back in $DBCC (+$6E).
EVADE_LANE_FAST = ((0x10, 13.0), (0x05, 10.0))
SCREEN_BIAS = 0x80
ON_SCREEN = (0x80, 0x1C0)
GRAB_Z = 8

ANIM_WALK = 0x00
ANIM_HIT = 0x08
ANIM_PUNCH = 0x14
ANIM_MIRROR = 0x02

# Set $1FC70, the frames the office's Garcia shows: (reload, [(attack, body)]).
ANIMS: dict[int, tuple[int, tuple[tuple[int, int], ...]]] = {
    0x00: (5, ((0, 0x01),) * 4),
    0x02: (5, ((0, 0x01),) * 4),
    0x08: (1, ((0, 0x03),) * 4),
    0x0A: (1, ((0, 0x03),) * 4),
    0x14: (4, ((0x12, 0x01), (0, 0x01), (0, 0x01), (0x12, 0x01), (0, 0x01), (0, 0x01), (0, 0x01),
               (0x3E, 0x10), (0x3E, 0x10), (0x3E, 0x10))),
    0x16: (4, ((0x13, 0x01), (0, 0x01), (0, 0x01), (0x13, 0x01), (0, 0x01), (0, 0x01), (0, 0x01),
               (0x3F, 0x11), (0x3F, 0x11), (0x3F, 0x11))),
}

# The object shape table ($1A68E), the ids above.
SHAPES: dict[int, tuple[int, int, int, int, int, int]] = {
    0x01: (-9, 9, -8, 8, -60, 0),
    0x03: (-8, 8, -8, 8, -60, 0),
    0x10: (4, 20, -8, 8, -60, 0),
    0x11: (-20, -4, -8, 8, -60, 0),
    0x12: (0, 40, -8, 8, -50, -44),
    0x13: (-40, 0, -8, 8, -50, -44),
    0x3E: (16, 51, -8, 8, -48, -42),
    0x3F: (-51, -16, -8, 8, -48, -42),
}


class Outcome(Enum):
    NONE = auto()
    HIT = auto()  # his box on the actor's body
    STRUCK = auto()  # the actor's strike on his body
    GRAB = auto()  # the actor's walking box on his body: the hold


def _hi(value: float) -> int:
    return math.floor(value)


def _s16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big", signed=True)


def _s32(data: bytes, offset: int) -> float:
    return int.from_bytes(data[offset : offset + 4], "big", signed=True) / 65536.0


def box(box_id: int, x: int, y: int, z: int) -> tuple[int, int, int, int, int, int] | None:
    shape = SHAPES.get(box_id)
    if shape is None or not box_id:
        return None
    return (x + shape[0], x + shape[1], y + shape[2], y + shape[3], z + shape[4], z + shape[5])


class GarciaSim:
    """His object, reduced to what his states read and write."""

    __slots__ = (
        "slot", "x", "y", "z", "vx", "vy", "state", "flags", "t50", "aim_x", "aim_y",
        "speed", "anim", "frame", "countdown", "reload", "animating", "attack_id",
        "body_id", "hp", "param", "screen_x", "cam_x", "alive", "repeats",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))

    def copy(self) -> GarciaSim:
        other = GarciaSim.__new__(GarciaSim)
        for name in self.__slots__:
            setattr(other, name, getattr(self, name))
        return other

    @property
    def facing_left(self) -> bool:
        return bool(self.anim & ANIM_MIRROR)

    @classmethod
    def from_bytes(cls, data: bytes, *, slot: int, cam_x: int) -> GarciaSim:
        return cls(
            slot=slot,
            x=_s32(data, 0x10),
            y=_s32(data, 0x14),
            z=_s32(data, 0x18),
            vx=_s32(data, 0x1C),
            vy=_s32(data, 0x20),
            state=data[0x30],
            flags=data[0x31],
            t50=data[0x50],
            aim_x=_s16(data, 0x60),
            aim_y=_s16(data, 0x62),
            speed=int.from_bytes(data[0x64:0x66], "big"),
            anim=int.from_bytes(data[0x08:0x0A], "big"),
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
            alive=data[0x30] != ST_DYING and data[0] in GARCIA_TYPES,
            repeats=data[0x6E],
        )


def _goto(g: GarciaSim, word: int) -> None:
    """``move.w #word, +$30``: the state and ``+$31`` at once."""

    g.state = (word >> 8) & 0xFF
    g.flags = word & 0xFF


def _set_anim(g: GarciaSim, anim: int, a: ActorSim) -> None:
    """``$96C0``: an animation from frame 0, facing the target (left unless it
    stands strictly to his right); the boxes latch at once."""

    left = not (_hi(a.x) > _hi(g.x))
    g.anim = anim | (ANIM_MIRROR if left else 0)
    reload, frames = ANIMS.get(g.anim, (5, ((0, 0x01),)))
    g.frame = 0
    g.reload = g.countdown = reload
    g.attack_id, g.body_id = frames[0]


def _face_only(g: GarciaSim, a: ActorSim) -> None:
    left = not (_hi(a.x) > _hi(g.x))
    g.anim = (g.anim & ~ANIM_MIRROR) | (ANIM_MIRROR if left else 0)


def _on_screen(g: GarciaSim) -> bool:
    return ON_SCREEN[0] <= g.screen_x < ON_SCREEN[1]


def _approach(g: GarciaSim) -> bool:
    """``$9604``: True once within 4 px on both axes; else aims the velocity."""

    dx = int(g.aim_x) - _hi(g.x)
    dy = int(g.aim_y) - _hi(g.y)
    if abs(dx) < ARRIVE and abs(dy) < ARRIVE:
        return True
    g.vx, g.vy = _vector_velocity(dx, dy, int(g.speed))
    return False


def _move(g: GarciaSim) -> None:
    """``$9E68`` on open floor: ``$9F96``/``$A00E`` refuse a step past the
    bounds and leave the rest."""

    nx = g.x + g.vx
    if not (g.vx < 0 and nx < 0) and not (g.vx >= 0 and nx >= X_MAX_ROUND_8):
        g.x = nx
    ny = g.y + g.vy
    if LANE_MIN <= ny < LANE_MAX:
        g.y = ny


def _trigger(g: GarciaSim, a: ActorSim, box_id: int) -> bool:
    """``$AD04``: his box ``box_id`` on the target's cached body (``+$70``)."""

    b = box(box_id, _hi(g.x), _hi(g.y), _hi(g.z))
    return b is not None and a.body is not None and overlaps(b, a.body)


def contact(g: GarciaSim, a: ActorSim) -> Outcome:
    """``$A9BA``/``$AAA0``: the actor's box on his body first, then his box on
    the actor's body."""

    if a.unavailable or a.latch:
        return Outcome.NONE
    x, y, z = _hi(g.x), _hi(g.y), _hi(g.z)
    body = box(g.body_id, x, y, z)
    if a.attack is not None and body is not None and overlaps(a.attack, body):
        if a.damage:
            if 0x78 <= g.screen_x < 0x1C8:
                return Outcome.STRUCK
            return Outcome.NONE
        if not a.holding and abs(a.z - z) <= GRAB_Z:
            return Outcome.GRAB
        return Outcome.NONE
    attack = box(g.attack_id, x, y, z)
    if attack is not None and a.body is not None and overlaps(attack, a.body):
        return Outcome.HIT
    return Outcome.NONE


def _react(g: GarciaSim, a: ActorSim, out: Outcome) -> bool:
    """What a contact does to him; True when it ended his update."""

    if out is Outcome.HIT:
        a.latch = 1
        return False
    if out is Outcome.STRUCK:
        a.latch = 2
        if getattr(a, "knockdown", False):
            # A knockdown strike (the rear attack's every live update):
            # $991A's flight and floor, out of the fight past any horizon
            # the plan looks at -- held there, no box and no body.
            _goto(g, 0x0300)
            g.hp -= a.damage or 1
            g.attack_id = g.body_id = 0
            if g.hp < 0:
                _goto(g, 0x0600)
                g.alive = False
            return True
        _goto(g, 0x0200)
        return True
    if out is Outcome.GRAB:
        a.latch = 3
        _goto(g, 0x0500)
        return True
    return False


def _evade_goes_down(a: ActorSim) -> bool:
    return _hi(a.y) < EVADE_SPLIT


def garcia_update(g: GarciaSim, a: ActorSim, *, rng: int = 5) -> Outcome:
    """One update of his, then the renderer's tail (latch, step). ``rng``
    stands for ``$104D8``'s draws: bits 0-1 a ``$DBCC`` leg's count, 2-3 its
    speed."""

    out = _state(g, a, rng)
    _render(g)
    return out


def _state(g: GarciaSim, a: ActorSim, rng: int = 5) -> Outcome:
    st = g.state
    entry = not g.flags & 0x01
    if st == ST_RESELECT:
        _goto(g, PERSONALITY_STATE[g.param & 0x07])
        return Outcome.NONE
    if st == ST_APPROACH:
        if entry:
            g.flags |= 0x01
            _set_anim(g, ANIM_WALK, a)
            g.animating = True
            g.reload, g.countdown = 3, 1
            g.t50 = APPROACH_UPDATES
            g.speed = APPROACH_SPEED_SLOW if g.param & 0x20 else APPROACH_SPEED
        out = contact(g, a)
        if _react(g, a, out):
            return out
        g.t50 -= 1
        if g.t50 <= 0:
            _goto(g, 0x0100)
            return out
        g.aim_y = _hi(a.y)
        g.aim_x = _hi(a.x) + (-APPROACH_OFFSET if _hi(a.x) >= _hi(g.x) else APPROACH_OFFSET)
        if _approach(g):
            _goto(g, 0x0700)
            return out
        _move(g)
        if _trigger(g, a, 0x13 if g.facing_left else 0x12):
            _goto(g, 0x0A00)
        return out
    if st == ST_PUNCH:
        if entry:
            g.flags |= 0x01
            if not _on_screen(g):
                _goto(g, 0x0700)
                return Outcome.NONE
            g.animating = True
            _set_anim(g, ANIM_PUNCH, a)
            if g.flags & 0x04:
                g.reload = g.countdown = 4
        out = contact(g, a)
        if out is Outcome.HIT:
            a.latch = 1
            return out
        if _react(g, a, out):
            return out
        if not g.flags & 0x02 and g.frame == PUNCH_CHECK_FRAME:
            g.flags |= 0x02
            if not _trigger(g, a, 0x3F if g.facing_left else 0x3E):
                _goto(g, 0x0100)
                return out
        if g.frame == PUNCH_END_FRAME:
            _goto(g, 0x0100)
        return out
    if st == ST_EVADE:
        if entry:
            g.flags |= 0x01
            _set_anim(g, ANIM_WALK, a)
            g.reload, g.countdown = 4, 1
            g.animating = True
            g.vx = 0.0
            g.flags &= ~0x04
            if _hi(g.x) >= _hi(a.x):
                g.flags |= 0x04
            speed = EVADE_LANE_SPEED
            for at_least, fast in EVADE_LANE_FAST:
                if g.repeats >= at_least:
                    speed = fast
                    break
            g.vy = -speed if _hi(a.y) >= EVADE_SPLIT else speed
        out = contact(g, a)
        if _react(g, a, out):
            return out
        _face_only(g, a)
        if not g.flags & 0x02:
            if (g.vy >= 0 and _hi(g.y) > EVADE_BOTTOM) or (g.vy < 0 and _hi(g.y) < EVADE_TOP):
                g.flags |= 0x02
                g.t50 = 0
            else:
                _move(g)
                return out
        if g.t50 == 0:
            # A new leg ($DD26): random; the plan assumes the middle one.
            updates = EVADE_LEG_UPDATES[rng & 3]
            speed, reload = EVADE_LEGS[(rng >> 2) & 3]
            g.t50 = updates
            g.vx = -speed if g.flags & 0x04 else speed
            g.reload, g.countdown = reload, 1  # move.w #$0n01, +$0C
            return out
        g.t50 -= 1
        if g.vx < 0:
            if _hi(a.x) - EVADE_PAST_DX > _hi(g.x):
                _goto(g, 0x0100)
                return out
        elif not _hi(a.x) + EVADE_PAST_DX > _hi(g.x):
            _goto(g, 0x0100)
            return out
        nx = g.x + g.vx
        if not (g.vx < 0 and nx < 0) and not (g.vx >= 0 and nx >= X_MAX_ROUND_8):
            g.x = nx
        return out
    if st == ST_HITSTUN:
        if entry:
            g.flags |= 0x01 | 0x02
            g.animating = False
            _set_anim(g, ANIM_HIT, a)
            g.t50 = HITSTUN_UPDATES
            g.hp -= a.damage or 1
            g.x += HIT_PUSH if g.facing_left else -HIT_PUSH
            if g.hp < 0:
                _goto(g, 0x0600)
                g.alive = False
            return Outcome.NONE
        g.t50 -= 1
        if g.t50 <= 0:
            _goto(g, 0x0100)
        return Outcome.NONE
    if st == ST_DYING:
        g.alive = False
    return Outcome.NONE


def _render(g: GarciaSim) -> None:
    """The renderer's tail: ``+$28``, the frame's boxes latched, then the
    countdown stepped while animating (``emit_object_sprite_mapping``)."""

    g.screen_x = _hi(g.x) - g.cam_x + SCREEN_BIAS
    if g.state == ST_KNOCKDOWN:
        return
    reload, frames = ANIMS.get(g.anim, (None, None))
    if frames is not None:
        g.attack_id, g.body_id = frames[min(g.frame, len(frames) - 1)]
    if g.animating:
        g.countdown -= 1
        if g.countdown <= 0:
            g.countdown = g.reload
            g.frame += 1
            if frames is not None and g.frame >= len(frames):
                g.frame = 0


# --- Checking the model against a recording ---------------------------------------------

_FIELDS = ("x", "y", "vx", "vy", "state", "t50", "anim", "frame", "countdown", "attack_id", "body_id")
MODELLED = frozenset({ST_RESELECT, ST_APPROACH, ST_PUNCH, ST_EVADE})


def _signature(g: GarciaSim) -> tuple:
    return tuple(getattr(g, f) for f in _FIELDS) + (g.flags,)


def check_recording(rows: Sequence[dict], *, verbose: bool = False) -> dict:
    """Replay every Garcia of a ``tools/mr_x_lab.py`` recording, update by
    update (a frame on which his fields change), in the states the model
    replays; and every hit on the actor, by who landed it."""

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
        for i, data in sorted(before.items()):
            if i not in after or data[0] != OFFICE_TYPE:
                continue
            g0 = GarciaSim.from_bytes(data, slot=i, cam_x=prev["cam"])
            g1 = GarciaSim.from_bytes(after[i], slot=i, cam_x=row["cam"])
            if _signature(g0) == _signature(g1):
                continue
            key = f"s{g0.state:02x}"
            if g1.state in (ST_KNOCKDOWN, ST_DYING) and g0.state not in (ST_KNOCKDOWN, ST_DYING):
                # Knocked down by another object's contact (Mr. X's flight,
                # a thrown body) earlier in the pass: $AA34's object list.
                checked[f"{key}:knocked_by_other"] += 1
                continue
            if g0.state not in MODELLED:
                checked[f"{key}:skipped"] += 1
                continue
            best = None
            for rng in range(16) if g0.state == ST_EVADE else (5,):
                sim = g0.copy()
                a = actor.copy()
                out = garcia_update(sim, a, rng=rng)
                n = sum(1 for f in _FIELDS if getattr(sim, f) != getattr(g1, f))
                if best is None or n < best[0]:
                    best = (n, sim, a, out)
                if n == 0:
                    break
            _, sim, a, out = best
            his = 0xB900 + 0x80 * i
            by_him = int.from_bytes(p1_after[0x7E:0x80], "big") == his
            code = p1_after[0x7C] if by_him else 0
            actual = {1: "HIT", 2: "STRUCK", 3: "GRAB"}.get(code, "NONE")
            if out is not Outcome.NONE or actual != "NONE":
                contacts[f"{out.name}->{actual}"] += 1
            diffs = [f for f in _FIELDS if getattr(sim, f) != getattr(g1, f) and not (
                isinstance(getattr(sim, f), float) and abs(getattr(sim, f) - getattr(g1, f)) < 1e-6)]
            checked[key] += 1
            for f in diffs:
                mismatched[f"{key}:{f}"] += 1
            if diffs and len(examples) < 40:
                examples.append({
                    "f": row["f"], "slot": i, "state": key,
                    "diff": {f: [getattr(sim, f), getattr(g1, f)] for f in diffs},
                })
        prev = row
    return {
        "updates_checked": sum(v for k, v in checked.items() if not k.endswith(":skipped")),
        "checked_by_state": dict(checked),
        "mismatches": dict(mismatched),
        "contacts": dict(contacts),
        "examples": examples,
    }
