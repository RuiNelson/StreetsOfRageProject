"""Antonio (type ``$56``, round 1): the ROM model, and the plan built on it.

Everything the AI does against him is decided here, as pure functions of the
tokens already in the context, so the decision (``decide``), the ranking
(``priority``) and the controller (``execute``) cannot disagree about it --
the same arrangement ``souther.py`` has for round 2.

**The plan, in one line: take one hold, and never give him back a turn.**

1. *Engage* -- reach grab contact without ever standing where his kick can
   start or land. Not a hand-written corridor this time but a **lookahead over
   his own AI**: ``simulate`` runs his state-1 decision code update by update
   (the gates, every tactical handler, the integration, the animation that
   decides which boxes are live), and ``plan_engage`` tries each of the nine
   stick positions against it and keeps the one that gets the hold soonest
   without ever letting the kick box meet the actor's body;
2. *hold loop* -- knee, knee, release, re-grab, repeated from that one hold
   until he is dead (``hold_step``), exactly as against Souther: the release is
   player-side (``loc_235A``) and so is the knee chain, and a released later
   boss goes straight back to primary 1 in front of the actor.

The facts it rests on, all read from the disassembly (``$16CE4`` onwards; see
``ai-analysis/enemy-ai.md``, "Antonio"):

Everything runs at 30 Hz
    ``$AD8E`` updates both players, waits a VBlank, then every object. So one
    *update* here is two game frames, for him and for the actor alike, and
    every speed below is per update.
The kick gate (``$16EAE``, run every update in primary 1)
    X: ``+$50 < $78`` when the target's own ``+$1C`` high word, signed into
    his frame, says it is walking *into* him; ``< $50`` walking away; standing
    still, ``< $68`` or ``< $50`` by which side of him it stands on (and its
    ``+$31`` bit 1, which no player code ever sets). Lane: ``+$52 < $08``
    when the target is **above** his lane (``+$61``), ``< $10`` otherwise.
    Every earlier Antonio attempt used ``$10`` for both sides.
The dash (``$16E74``, checked *before* the kick gate)
    ``+$50`` in ``[$28, $78)`` and ``+$52 < $14`` arms tactical ``$08``:
    4 px an update straight at the target, homing its lane at
    ``$1797E``'s 4/2/1/0 px, until ``+$50 >= $E0`` or it is inside ``$28``
    with ``+$52 >= $10``. It is harmless in itself (animation 0, no attack
    box); it is how he carries himself into kick range.
His own lane (tactical 0, ``$179AC``, every update the target is within
    ``$78``) keeps the target **18-21 px below him** -- away at 1 px or 4 px,
    toward at 1/2/4 -- and rushes *up* at 4 px whenever the target is above
    him. So he parks just outside his own below-gate, and above him is the
    one side he closes on at once.
The kick itself (primary 2, ``$171CC``)
    animation ``$04``, 3 updates a frame, starting on frame 1 (frame 0 if the
    idle happened to show frame 2): frame 1 reaches 30 px forward, frame 2
    60 px, frames 3-6 12..84 px, frame 7 nothing, and it ends as frame 8 comes
    up -- 21 updates, during which he does not move. His body leans with it:
    -6..22 px on frames 1-2, 14..40 px on 3-6.
Grab beats hit (``$AAA0``)
    the actor's walking box against his body box is tested *first*, and on
    overlap (no damage out, not already holding, 8 px of height) it is the
    grab and his attack box is not tested at all that update. All three axes
    compare inclusively (``$AB88``). So a walk that meets his leaning body
    takes the hold even through a kick already on its frames.
Screen and camera
    ``+$28`` is his biased screen X (``$80`` = the left edge), written by the
    renderer; off-screen, tactical ``$09`` walks him back in at 4 px an update
    and skips both gates.
Who he can reach (``$179F8``, ``$AA34``)
    both gates are skipped while the target is in a hit reaction (``+$59``
    bit 1, until its floor landing), has ``+$4B`` bit 1 set, or is in action
    ``$5A``-``$5F`` -- re-read off the target every update -- and no contact
    at all is tested on a player in a hit reaction or with a contact code
    still latched in ``+$7C``. A knocked-down actor is never kicked again.
His boomerang (type ``$96``, ``$17206`` / ``$17262``)
    rides his animation, boxless, until frame 2 of the wind-up launches it
    64 px ahead at 14 px an update. Out, it sheds 0.4375 an update and dives
    down the street (+4.5 lane, shedding 0.1875) for 32 updates, turning
    ~280 px out; back, it homes on its own ``+$78`` (``$172F6``'s ``lea``
    was meant to read the target's lane: it reads 0, the top of the street)
    while tactical 7 walks him toward that lane and catches it within 8 px
    of his hand. ``_boomerang_step`` flies it inside every rollout, and
    ``_boomerang_path`` follows it past the horizon.

Out of all of that one geometry is safe by construction: **8-16 px above his
lane**. The kick needs ``< 8`` there, the grab touches at ``<= 16``. The
planner does not hard-code it, though -- it is what the lookahead finds,
because every other place the actor can stand inside his X window ends in a
simulated kick.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Sequence

from ..memory_map import PLAYER_HIT_REACTION_BIT
from ..world_map import LANE_Y_MAX_DEFAULT, LANE_Y_MIN
from . import kinematics
from .reach import PLAYER_BODY_REACH_X, DEFAULT_PLAYER_BODY_REACH_X, walk_box_reach_x
from .souther import HoldStep, hold_step as _shared_hold_step, release_press_frames
from .tokens import Antonio, Boss, CameraRange, PlayableCharacter, Projectile

__all__ = [
    "EngageMode",
    "EngagePlan",
    "HoldStep",
    "hold_step",
    "kick_gate_open",
    "plan_engage",
    "release_press_frames",
    "signed_health",
]

# --- His gates ($16DA0 antonio_state1_active_combat) ----------------------------

NEAR_DX = 0x78  # +$50 < $78 sets +$6A bit 0: tactical 0's back-off owns him
DASH_DX_MIN = 0x28  # $16E74: +$50 in [$28, $78) ...
DASH_DX_MAX = 0x78
DASH_LANE = 0x14  # ... and +$52 < $14 arms tactical 8
DASH_SPEED = 4.0
DASH_STOP_DX = 0xE0  # $16F68: +$50 >= $E0 ends the dash
DASH_KEEP_LANE = 0x10  # ... or inside $28 with +$52 >= $10
KICK_DX_CLOSING = 0x78  # $16EAE: target walking into him
KICK_DX_AWAY = 0x50  # walking away
KICK_DX_STILL_WIDE = 0x68  # standing, (+$60 != 0) == (target +$31 bit 1)
KICK_DX_STILL_NARROW = 0x50  # standing, otherwise
KICK_LANE_ABOVE = 0x08  # +$61 set: the target is strictly above his lane
KICK_LANE_LEVEL_OR_BELOW = 0x10
TARGET_FLAG_31_BIT = 0x02
# $179F8, before either gate on every update: the target is unavailable
# (+$77, both gates skipped) while its +$59 bit 1 (a hit reaction, until the
# floor landing) or +$4B bit 1 is set, or its action is $5A-$5F.
TARGET_HIT_REACTION_BIT = PLAYER_HIT_REACTION_BIT
TARGET_FLAG_4B_BIT = 0x02
TARGET_UNAVAILABLE_ACTIONS = range(0x5A, 0x60)
# $AA34: a player in a hit reaction, or with a contact code in +$7C not yet
# consumed (bit 0), is tested against nothing.
CONTACT_LATCH_BIT = 0x01

# --- His movement ----------------------------------------------------------------

BACKOFF_SPEED_X = 1.5  # tactical 0, away from the target
BACKOFF_UPDATES = 0x20
POSE_DX = 0xC0  # tactical 0 with the target this far: the pose (tactical 1)
REENTRY_SPEED = 4.0  # tactical 9
REENTRY_UPDATES = 0x48
REENTRY_UPDATES_PAIR_TWO = 0x46
BOSS_LANE_MIN = 0x00  # $17AB8 clamps every later boss to $00..$70
BOSS_LANE_MAX = 0x70
BAND_CENTRE_LANE = 0x38
SCREEN_LEFT = 0x80  # +$28 on-screen band ($16DE6)
SCREEN_RIGHT = 0x1C0
SCREEN_CENTRE = 0x120
SCREEN_BIAS = 0x80

# --- His animations (set $2E8B4) and boxes ($1A68E) ------------------------------
#
# ``+$08`` is a byte offset into the set's word table: four per mirrored pair,
# bit 1 selecting the left-facing member. Every left-facing frame names the id
# after its right-facing twin, whose extents are the mirror image.

ANIM_IDLE = 0x00
ANIM_KICK = 0x04
ANIM_STAND = 0x24  # tactical 3
ANIM_WALK = 0x28  # tactical 2/4/9
ANIM_POSE = 0x2C  # tactical 1
ANIM_WINDUP = 0x30  # tactical 6, the boomerang wind-up
ANIM_THROW = 0x34  # tactical 7
ANIM_MIRROR_BIT = 0x02

KICK_END_FRAME = 8  # $171CC: +$0A reaching 8 returns him to primary 1
KICK_FRAME_UPDATES = 3

# (frame count, per-frame updates, [(attack id, body id) per frame]) for the
# right-facing member of each pair the AI can meet him in.
_ANIMATIONS: dict[int, tuple[int, list[tuple[int, int]]]] = {
    ANIM_IDLE: (6, [(0, 0x76)] * 4),
    ANIM_KICK: (
        KICK_FRAME_UPDATES,
        [(0, 0x76), (0x84, 0x7C), (0x88, 0x7C)] + [(0x80, 0x7E)] * 4 + [(0, 0x76)] * 2,
    ),
    0x08: (0, [(0, 0x78)]),  # hit reaction
    0x0C: (0, [(0, 0x78)]),  # held, front
    0x10: (0, [(0, 0x82)]),  # held, back
    ANIM_STAND: (6, [(0, 0x76)] * 4),
    ANIM_WALK: (6, [(0, 0x76)] * 4),
    ANIM_POSE: (6, [(0, 0x76), (0, 0x86)]),
    ANIM_WINDUP: (6, [(0, 0x76)] + [(0, 0x7A)] * 4 + [(0, 0x76)]),
    ANIM_THROW: (6, [(0, 0x76)] * 4),
}

# Box X extents about his origin. Every one of them is lane -8..+8.
_SHAPE_X: dict[int, tuple[int, int]] = {
    0x76: (-14, 15), 0x77: (-15, 14),
    0x78: (-14, 15), 0x79: (-15, 14),
    0x7A: (-8, 22), 0x7B: (-22, 8),
    0x7C: (-6, 22), 0x7D: (-22, 6),
    0x7E: (14, 40), 0x7F: (-40, -14),
    0x80: (12, 84), 0x81: (-84, -12),
    0x82: (-18, 14), 0x83: (-14, 18),
    0x84: (-8, 30), 0x85: (-30, 8),
    0x86: (-32, 0), 0x87: (0, 32),
    0x88: (-8, 60), 0x89: (-60, 8),
}

# Boxes are lane -8..+8 on both sides, compared inclusively: lanes 16 apart
# still touch.
CONTACT_LANE = 16
# The ROM's player clamp ($43AA) -- where the actor can actually stand.
PLAYER_LANE_MIN = LANE_Y_MIN
PLAYER_LANE_MAX = LANE_Y_MAX_DEFAULT

# --- His boomerang (type $96: $17206 spawns it, $17262 runs it) -----------------

BOOMERANG_TYPE = 0x96
# $17272, keyed by its +$30.
BOOMERANG_ATTACHED = 0  # $173D8: rides his animation's offset records, no box
BOOMERANG_OUT = 1  # $172B2
BOOMERANG_BACK = 2  # $17320
BOOMERANG_KNOCKED = 3  # $1727A: a player's attack sent it off, harmless
# The wind-up's frame 2 ($17494/$173A0 record 12, mirrored 13) names child
# animation $40/$42, and $17450 launches it from 64 px ahead of him.
BOOMERANG_LAUNCH_FRAME = 2
BOOMERANG_LAUNCH_DX = 64
BOOMERANG_SPEED = 14.0
BOOMERANG_LANE_SPEED = 4.5
BOOMERANG_DECEL_X = 0.4375  # $7000 an update against the throw, out and back
BOOMERANG_DECEL_LANE = 0.1875  # $FFFFD000 an update, out
BOOMERANG_OUT_UPDATES = 0x20  # +$6B
BOOMERANG_HOMING = 0.1875  # $3000 an update toward +$52, back ...
BOOMERANG_HOMING_STOP = 4  # ... until within 4 px, then no lane velocity
BOOMERANG_SCREEN_MIN = -0x80  # +$28 outside [-$80, $2C0) despawns it, back
BOOMERANG_SCREEN_MAX = 0x2C0
CATCH_REACH = 0x18  # $17132: his hand, 24 px ahead of him ...
CATCH_WINDOW = 8  # ... catches it inside 8 px
ANIM_BOOMERANG_RIGHT = 0x40
ANIM_BOOMERANG_LEFT = 0x42
# Its attack box per latched id (set $2E8B4, animations $40/$42: four frames,
# one update each), X extents about its origin. Every one is lane -8..+8.
_BOOMERANG_BOX_X: dict[int, tuple[int, int]] = {
    0xA4: (-4, 22), 0xAA: (-18, 18), 0xA8: (-20, 6), 0xA6: (-20, 16),
    0xA5: (-22, 4), 0xAB: (-18, 18), 0xA9: (-6, 20), 0xA7: (-16, 20),
}
_BOOMERANG_FRAMES: dict[int, tuple[int, ...]] = {
    ANIM_BOOMERANG_RIGHT: (0xA4, 0xAA, 0xA8, 0xA6),
    ANIM_BOOMERANG_LEFT: (0xA5, 0xAB, 0xA9, 0xA7),
}

# --- The hold ----------------------------------------------------------------------

HOLD_KNEE_DAMAGE = 2
HOLD_THIRD_KNEE_DAMAGE = 3
HOLD_SUPLEX_DAMAGE = 5
PRIMARY_ACTIVE = 0x01
PRIMARY_KICK = 0x02
PRIMARY_HELD = 0x04
PRIMARY_POLICE = 0x0A
# +$66 bit 0: a contact on him waiting for his next update. $17CF2, first in
# both states, dispatches it on the other body's +$7D -- the hold among them.
PENDING_CONTACT_BIT = 0x01

# --- The planner -------------------------------------------------------------------

# How far ahead every candidate is played out, in updates (two frames each).
# Long enough to see a dash from the edge of his window arrive (120 px at the
# two bodies' combined 7+ px an update) and a kick reach its 84 px frames.
HORIZON_UPDATES = 14
# How long a candidate holds its own stick before the tail policy takes over.
FIRST_UPDATES = 2
# Where the engage wants to be: above his lane by this much, which is inside
# the grab's 16 and outside the kick's 8 with 4 px to spare either way.
POCKET_DY = 12
POCKET_MIN_DY = KICK_LANE_ABOVE + 1  # "above him" for the aim: kick-proof
# Where the walk-in aims on X: short of his origin, so it never carries
# through him. The walking box meets his body long before.
WALK_IN_STOP_DX = 8
# The X gap at which no gate of his can fire at all ($78, plus slack).
SAFE_DX = NEAR_DX + 4
FAR_DX = SAFE_DX + 12
# Below him, the lane kept while getting out of his X window: past his own
# 18-21 px band, so he closes lane rather than arming the dash.
RETREAT_DY = 24
# With no room above him, lure him down by standing this far below, far out.
LURE_DY = 36
SIDE_DEADBAND_X = 4
# Conservatism of the simulated hit: his attack box grown by this much on X
# and on lane. The grab is simulated exactly -- a pessimistic grab is what
# stops a walk-in that would have worked.
HIT_MARGIN_X = 2
HIT_MARGIN_LANE = 1
# Scores. A hold ends the question; a hit is the one thing never chosen while
# anything else exists; the rest is progress toward the aim minus danger.
_SCORE_GRAB = 10_000
_SCORE_HIT = -10_000
_SCORE_PER_UPDATE = 10
_DANGER_KICK_REACH = 400
_DANGER_KICK_GATE = 250
_DANGER_DASH_BELOW = 100
# His boomerang's path past the rollout, the actor standing where the rollout
# left it: a hit anywhere on it is danger. Followed long enough for its whole
# return, from the turn ~280 px out back to his hand. Measured live before the
# boomerang was modelled: Adam dithered 5 px off his lane 130 px out, and a
# boomerang coming back from an earlier throw landed.
_DANGER_BOOMERANG = 300
BOOMERANG_FOLLOW_UPDATES = 72
_REVERSE_X_COST = 3
# Tie-breaks between candidates that score the same -- two sticks that both
# take the hold on the same update, say. Walking *at* him keeps the walking
# box deepest in his body, and a lane change that buys nothing is one more
# thing to be off by. Both far below one update's worth of any other term.
_TOWARD_BONUS = 0.5
_KEEP_LANE_BONUS = 0.2


class EngageMode(Enum):
    """Where ``engage_aim`` sends the actor -- see that function."""

    POCKET = auto()
    """Above his lane by 9+ px: walk in along the pocket, 12 px above him."""

    RISE = auto()
    """Above him but inside the 8 px kick lane: climb to the pocket."""

    CLIMB = auto()
    """Level or below, out of his X window: cross above his lane there."""

    RETREAT = auto()
    """Level or below, inside his X window: get out of it before climbing."""

    LURE = auto()
    """No room above him in the band: stand low and far until he comes down."""


@dataclass(frozen=True, slots=True)
class EngagePlan:
    """The stick this tick, and why."""

    dir_x: int  # -1 left, 0, +1 right
    dir_y: int  # -1 up (smaller lane), 0, +1 down
    mode: EngageMode
    outcome: str | None  # "grab" / "hit" / None within the horizon
    at_update: int | None
    score: float


def signed_health(boss: Boss) -> int:
    health = boss.health or 0
    return health - 0x10000 if health >= 0x8000 else health


def _hi(value: float) -> int:
    """The high word of a 16.16 value, as the ROM's ``move.w`` reads it."""

    return math.floor(value)


# --- The kick gate, from tokens ---------------------------------------------------


def kick_dx_threshold(*, target_vx: float, target_left_of_him: bool, target_flags_31: int) -> int:
    """``$16EAE``'s X window for this target's own velocity and side."""

    vx_hi = _hi(target_vx)
    if vx_hi == 0:
        flag = bool(target_flags_31 & TARGET_FLAG_31_BIT)
        return KICK_DX_STILL_WIDE if target_left_of_him == flag else KICK_DX_STILL_NARROW
    signed = -vx_hi if target_left_of_him else vx_hi
    return KICK_DX_CLOSING if signed < 0 else KICK_DX_AWAY


def kick_lane(target_above: bool) -> int:
    return KICK_LANE_ABOVE if target_above else KICK_LANE_LEVEL_OR_BELOW


def kick_gate_open(antonio: Antonio, actor: PlayableCharacter) -> bool:
    """Would ``$16EAE`` start a kick on ``actor`` from here, on a free update?

    Exactly the ROM's gate on the observed positions -- or a kick already on
    its frames. Not a prediction: ``plan_engage`` is the one that looks ahead.
    """

    if antonio.is_defeated:
        return False
    if antonio.primary_state == PRIMARY_KICK:
        return True
    if antonio.primary_state != PRIMARY_ACTIVE or antonio.target_unavailable:
        return False
    dx = actor.world_x - antonio.world_x
    dy = actor.world_y - antonio.world_y
    threshold = kick_dx_threshold(
        target_vx=actor.vel_x, target_left_of_him=dx < 0, target_flags_31=actor.flags_31
    )
    return abs(dx) < threshold and abs(dy) < kick_lane(dy < 0)


# --- The simulation ------------------------------------------------------------------


class Outcome(Enum):
    NONE = auto()
    GRAB = auto()
    HIT = auto()


class BoomerangSim:
    """His boomerang, reduced to what its own update (``$17262``) reads."""

    __slots__ = (
        "state", "x", "y", "vx", "vy", "anim", "frame", "shown", "screen_x",
        "countdown", "lane_target", "above", "turn_lane", "knock_timer", "slot",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])

    def copy(self) -> BoomerangSim:
        return BoomerangSim(**{name: getattr(self, name) for name in self.__slots__})

    @classmethod
    def from_token(cls, boomerang: Projectile) -> BoomerangSim:
        return cls(
            state=boomerang.state,
            x=boomerang.fine_x if boomerang.fine_x else float(boomerang.world_x),
            y=boomerang.fine_y if boomerang.fine_y else float(boomerang.world_y),
            vx=boomerang.vel_x,
            vy=boomerang.vel_lane,
            anim=boomerang.anim,
            frame=boomerang.anim_frame,
            shown=boomerang.attack_box_id,
            screen_x=boomerang.screen_x,
            countdown=boomerang.countdown,
            lane_target=boomerang.lane_target,
            above=boomerang.lane_target_above,
            turn_lane=boomerang.turn_lane,
            knock_timer=boomerang.knock_timer,
            slot=boomerang.slot,
        )

    @classmethod
    def on_his_hand(cls) -> BoomerangSim:
        """A fresh one from ``$17206``: attached, boxless, its slot unknown."""

        return cls(
            state=BOOMERANG_ATTACHED, x=0.0, y=0.0, vx=0.0, vy=0.0, anim=0, frame=0,
            shown=0, screen_x=0, countdown=0, lane_target=0, above=False, turn_lane=0,
            knock_timer=0, slot=None,
        )


class BossSim:
    """His object, reduced to what his state-1/state-2 code reads and writes."""

    __slots__ = (
        "x", "y", "primary", "tactical", "t78", "t5c", "t6b", "vx", "vy",
        "anim", "frame", "countdown", "shown_attack", "shown_body",
        "screen_x", "cam_x", "pair_role", "inert", "unavailable", "pending_hold",
        "boomerang", "boomerang_known", "strays",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])

    def copy(self) -> BossSim:
        fields = {name: getattr(self, name) for name in self.__slots__}
        if self.boomerang is not None:
            fields["boomerang"] = self.boomerang.copy()
        fields["strays"] = [stray.copy() for stray in self.strays]
        return BossSim(**fields)

    @classmethod
    def from_token(
        cls,
        antonio: Antonio,
        *,
        cam_x: int,
        boomerang: Projectile | None = None,
        strays: Sequence[Projectile] = (),
        boomerang_known: bool = False,
    ) -> BossSim:
        """``boomerang`` is his linked one (``+$6E``), ``strays`` older ones
        still out. ``boomerang_known``: the caller looked for his ``$96``, so
        no ``boomerang`` means he has none -- which tactical 7 acts on.
        Without it no boomerang is modelled at all."""

        x = antonio.fine_x if antonio.fine_x else float(antonio.world_x)
        y = antonio.fine_y if antonio.fine_y else float(antonio.world_y)
        primary = antonio.primary_state
        inert = 0
        if primary not in (PRIMARY_ACTIVE, PRIMARY_KICK):
            if primary in (PRIMARY_HELD, PRIMARY_POLICE):
                inert = HORIZON_UPDATES * 4
            elif primary == 0x00:
                inert = 1
            else:
                # Hit reaction, lethal gate, thrown, knocked down: +$62 is the
                # reaction timer those states count. Two updates early, so a
                # boss who gets up sooner than the timer says is still seen.
                inert = max(1, antonio.reaction_timer - 2)
        screen_x = antonio.screen_x if antonio.screen_x else _hi(x) - cam_x + SCREEN_BIAS
        return cls(
            x=x,
            y=y,
            primary=primary,
            tactical=antonio.tactical,
            t78=antonio.phase_timer,
            t5c=antonio.timer_5c,
            t6b=antonio.timer_6b,
            vx=antonio.boss_vel_x,
            vy=antonio.boss_vel_lane,
            anim=antonio.anim,
            frame=antonio.anim_frame,
            countdown=antonio.anim_countdown,
            shown_attack=antonio.attack_box_id,
            shown_body=antonio.body_box_id,
            screen_x=screen_x,
            cam_x=cam_x,
            pair_role=antonio.pair_role,
            inert=inert,
            unavailable=bool(antonio.target_unavailable),
            pending_hold=bool(antonio.hold_flags & PENDING_CONTACT_BIT),
            boomerang=BoomerangSim.from_token(boomerang) if boomerang is not None else None,
            boomerang_known=boomerang_known,
            strays=[BoomerangSim.from_token(stray) for stray in strays],
        )


class ActorSim:
    """The actor, moved the way ``$3614``'s walk tables move it."""

    __slots__ = (
        "x", "y", "facing_left", "walking", "vx", "flags_31", "speeds",
        "walk_reach", "body_reach", "lane_lo", "lane_hi", "x_lo", "x_hi", "holding",
        "untouchable", "unavailable", "box_x", "box_y",
    )

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])

    def copy(self) -> ActorSim:
        return ActorSim(**{name: getattr(self, name) for name in self.__slots__})

    @classmethod
    def from_token(
        cls, actor: PlayableCharacter, *, lane_lo: float, lane_hi: float, x_lo: float, x_hi: float
    ) -> ActorSim:
        walking = (actor.action_base & 0xF0) == 0 and actor.action_base >= 0x06
        walking |= 0x30 <= actor.action_base <= 0x3A and actor.action_base != 0x30
        body = PLAYER_BODY_REACH_X.get(actor.character_id, DEFAULT_PLAYER_BODY_REACH_X)
        x = float(actor.world_x)
        box_x = x
        if (x <= x_lo and actor.vel_x < 0) or (x >= x_hi and actor.vel_x > 0):
            # Walking into the camera clamp: its boxes were cached where the
            # step took it, before $43AA put it back (see actor_update).
            box_x = x + actor.vel_x
        y = float(actor.world_y)
        box_y = y
        if (y <= lane_lo and actor.vel_lane < 0) or (y >= lane_hi and actor.vel_lane > 0):
            # The same on the lane, which $43AA clamps too. Measured: a walk
            # held up into the top of the street, 16 lanes above him, was
            # refused the hold -- its box had been cached a step higher.
            box_y = y + actor.vel_lane
        return cls(
            x=x,
            y=y,
            facing_left=actor.facing_left,
            walking=walking,
            vx=actor.vel_x,
            flags_31=actor.flags_31,
            speeds=kinematics.walk_speeds(actor.character_id),
            walk_reach=walk_box_reach_x(actor.character_id),
            body_reach=body,
            lane_lo=lane_lo,
            lane_hi=lane_hi,
            x_lo=x_lo,
            x_hi=x_hi,
            holding=actor.is_holding_enemy,
            untouchable=bool(actor.flags_59 & TARGET_HIT_REACTION_BIT)
            or bool(actor.contact_code & CONTACT_LATCH_BIT),
            unavailable=bool(actor.flags_59 & TARGET_HIT_REACTION_BIT)
            or bool(actor.flags_4b & TARGET_FLAG_4B_BIT)
            or actor.action_state in TARGET_UNAVAILABLE_ACTIONS,
            box_x=box_x,
            box_y=box_y,
        )


def _set_anim(b: BossSim, anim: int, mirror: bool) -> None:
    """``$1588A`` -> ``$B1A2``: a new animation from frame 0, timer reseeded."""

    b.anim = anim | (ANIM_MIRROR_BIT if mirror else 0)
    b.frame = 0
    b.countdown = _ANIMATIONS.get(anim, (6, [(0, 0x76)]))[0]


def _frame_ids(anim: int, frame: int) -> tuple[int, int]:
    pair = anim & ~ANIM_MIRROR_BIT
    _, frames = _ANIMATIONS.get(pair, (6, [(0, 0x76)]))
    attack, body = frames[frame] if 0 <= frame < len(frames) else frames[0]
    if anim & ANIM_MIRROR_BIT:
        attack = attack + 1 if attack else 0
        body = body + 1 if body else 0
    return attack, body


def _emit(b: BossSim) -> None:
    """The renderer's tail (``$AF46``/``$B0C8``): latch this frame's boxes and
    ``+$28``, then step the frame timer."""

    b.screen_x = _hi(b.x) - b.cam_x + SCREEN_BIAS
    b.shown_attack, b.shown_body = _frame_ids(b.anim, b.frame)
    duration, frames = _ANIMATIONS.get(b.anim & ~ANIM_MIRROR_BIT, (6, [(0, 0x76)]))
    if duration == 0:
        return
    b.countdown -= 1
    if b.countdown <= 0:
        b.countdown = duration
        b.frame += 1
        if b.frame >= len(frames):
            b.frame = 0


def _integrate(b: BossSim) -> None:
    """``$17AB8``: X free, lane clamped to ``$00..$70``."""

    b.x += b.vx
    y = b.y + b.vy
    b.y = BOSS_LANE_MIN if y < BOSS_LANE_MIN else (float(BOSS_LANE_MAX) if y >= BOSS_LANE_MAX else y)


def _edge_nudge_and_integrate(b: BossSim) -> None:
    """``$17088``: pushed back toward the screen when far off either edge."""

    d0 = b.screen_x
    d1 = 0x40 - d0
    if d1 >= 0:
        b.x += d1
    else:
        d1 = 0x200 - d0
        if d1 < 0:
            b.x += d1
    if d0 < 0x60:
        b.vx += 1.0
    elif d0 >= 0x1E0:
        b.vx -= 1.0
    _integrate(b)


def _backoff_lane_velocity(d52: int, above: bool) -> float:
    """``$179AC``: keep a target below him 18-21 px down; rush one above."""

    if above:
        return -4.0
    if d52 >= 0x20:
        return 4.0
    if d52 >= 0x1A:
        return 2.0
    if d52 >= 0x16:
        return 1.0
    if d52 >= 0x12:
        return 0.0
    if d52 >= 0x08:
        return -1.0
    return -4.0


def _dash_lane_velocity(d52: int, above: bool) -> float:
    """``$1797E``: home on the target's lane, 4/2/1/0 px by the gap."""

    if d52 >= 0x20:
        speed = 4.0
    elif d52 >= 0x10:
        speed = 2.0
    elif d52 >= 0x08:
        speed = 1.0
    else:
        speed = 0.0
    return -speed if above else speed


def _oscillate(b: BossSim) -> float:
    """``$17A6E``: a slow +-1 px lane wobble on a 64-update cycle."""

    b.t6b = (b.t6b + 1) & 0xFF
    if b.t6b < 0x20:
        return 1.0
    if b.t6b < 0x40:
        return -1.0
    b.t6b = 0
    return 1.0


def _reset(b: BossSim, left: bool) -> None:
    """``$1700E``: back to tactical 0 and the idle animation."""

    b.tactical = 0
    b.t78 = 0
    _set_anim(b, ANIM_IDLE, left)


def _arm_dash(b: BossSim, left: bool) -> None:
    """``$16E88``: tactical 8, 4 px an update at the target, lane untouched."""

    b.tactical = 8
    b.vx = -DASH_SPEED if left else DASH_SPEED
    if b.anim != ANIM_IDLE:
        _set_anim(b, ANIM_IDLE, left)
    _integrate(b)


def _kick_gate(b: BossSim, t: ActorSim, *, left: bool, above: bool, d50: int, d52: int, margin: bool) -> bool:
    threshold = kick_dx_threshold(target_vx=t.vx, target_left_of_him=left, target_flags_31=t.flags_31)
    lane = kick_lane(above)
    if margin:
        threshold += 2
        lane += 1
    return d50 < threshold and d52 < lane


def _active_step(b: BossSim, t: ActorSim, *, margin: bool) -> None:
    """One update of primary 1 after the contact test (``$16DA0`` from ``$16DE6``)."""

    # $179F8 re-reads +$77 off the target first thing in every update.
    b.unavailable = t.unavailable
    # Then the boomerang upkeep: below tactical 6, with none on his hand --
    # none at all, or his linked one still out -- $17206 spawns a fresh one
    # and relinks +$6E to it. One still flying flies on unlinked: it can
    # still hit, but tactical 7 only ever waits on (and catches) his own.
    if b.boomerang_known and b.tactical < 6:
        m = b.boomerang
        if m is None or m.state != BOOMERANG_ATTACHED:
            if m is not None:
                b.strays.append(m)
            b.boomerang = BoomerangSim.on_his_hand()
    tx, ty = _hi(t.x), _hi(t.y)
    bx, by = _hi(b.x), _hi(b.y)
    dxs, dys = tx - bx, ty - by
    left, above = dxs < 0, dys < 0
    d50, d52 = abs(dxs), abs(dys)

    if not SCREEN_LEFT <= b.screen_x < SCREEN_RIGHT:
        b.vx = REENTRY_SPEED if b.screen_x < SCREEN_CENTRE else -REENTRY_SPEED
        b.vy = REENTRY_SPEED if ty < BAND_CENTRE_LANE else -REENTRY_SPEED
        b.t5c = REENTRY_UPDATES_PAIR_TWO if b.pair_role == 2 else REENTRY_UPDATES
        b.tactical = 9
        if (b.anim & ~ANIM_MIRROR_BIT) != ANIM_WALK:
            _set_anim(b, ANIM_WALK, left)
        _integrate(b)
        return

    near = False
    if not b.unavailable:
        near = d50 < NEAR_DX
        dash_lo, dash_hi, dash_lane = DASH_DX_MIN, DASH_DX_MAX, DASH_LANE
        if margin:
            dash_lo, dash_hi, dash_lane = dash_lo - 2, dash_hi + 2, dash_lane + 1
        if b.tactical != 8 and dash_lo <= d50 < dash_hi and d52 < dash_lane:
            _arm_dash(b, left)
            return
        if _kick_gate(b, t, left=left, above=above, d50=d50, d52=d52, margin=margin):
            old_frame = b.frame
            b.tactical = 0
            b.t78 = 0
            b.primary = PRIMARY_KICK
            _set_anim(b, ANIM_KICK, left)
            b.frame = 0 if old_frame == 2 else 1
            return

    tac = b.tactical
    if tac == 0:
        if b.t78:
            b.t78 -= 1
            b.vy = _backoff_lane_velocity(d52, above)
            _integrate(b)
        elif near:
            b.t78 = BACKOFF_UPDATES - 1
            b.vx = BACKOFF_SPEED_X if left else -BACKOFF_SPEED_X
            b.vy = _backoff_lane_velocity(d52, above)
            _integrate(b)
        else:
            b.vx = b.vy = 0.0
            if d50 >= POSE_DX:
                b.t78 = 0x1C
                b.tactical = 1
                _set_anim(b, ANIM_POSE, left)
            else:
                b.vy = -1.0 if above else 1.0
                b.tactical = 5
    elif tac == 1:
        b.t78 = (b.t78 - 1) & 0xFF
        if b.t78:
            return
        if near:
            _reset(b, left)
            return
        d1 = -1.0 if d50 >= 0x80 else 1.0
        b.vx = d1 if left else -d1
        b.vy = 0.0
        b.t78 = 0x1C
        b.tactical = 2
        _set_anim(b, ANIM_WALK, left)
    elif tac in (2, 4):
        b.t78 = (b.t78 - 1) & 0xFF
        if b.t78:
            b.vy = _oscillate(b)
            _edge_nudge_and_integrate(b)
            return
        if near:
            _reset(b, left)
            return
        b.vx = b.vy = 0.0
        if tac == 2 and d50 < 0x14:
            b.t78 = 0x1C
            b.tactical = 3
            _set_anim(b, ANIM_STAND, left)
            return
        b.vy = -1.0 if above else 1.0
        b.tactical = 5
    elif tac == 3:
        b.t78 = (b.t78 - 1) & 0xFF
        if b.t78:
            _edge_nudge_and_integrate(b)
            return
        if near:
            _reset(b, left)
            return
        b.vx = -1.0 if left else 1.0
        b.vy = 0.0
        b.t78 = 0x1C
        b.tactical = 4
        _set_anim(b, ANIM_WALK, left)
    elif tac == 5:
        if near:
            _reset(b, left)
            return
        if by in (BOSS_LANE_MIN, BOSS_LANE_MAX):
            b.vy = -b.vy
            _edge_nudge_and_integrate(b)
            return
        if d52 < DASH_LANE:
            b.vx = b.vy = 0.0
            b.t78 = 0x24
            b.tactical = 6
            _set_anim(b, ANIM_WINDUP, left)
            return
        _edge_nudge_and_integrate(b)
    elif tac == 6:
        b.t78 = (b.t78 - 1) & 0xFF
        if b.t78:
            _edge_nudge_and_integrate(b)
            return
        b.tactical = 7
        _set_anim(b, ANIM_THROW, left)
    elif tac == 7:
        if near:
            _reset(b, left)
            return
        # $17132: a target that turned its back gets the dash from $E0 out.
        facing_away = t.facing_left == left
        if facing_away and d50 < DASH_STOP_DX and d52 < DASH_LANE:
            _arm_dash(b, left)
            return
        # $17168: otherwise he waits on the boomerang -- walking 1 px an
        # update toward the lane it homes on while it comes back, catching it
        # within 8 px of his hand ($18 ahead), and back to tactical 0 once
        # there is no boomerang left at all.
        m = b.boomerang
        if m is None and b.boomerang_known:
            _reset(b, left)
            return
        if m is not None and m.state == BOOMERANG_BACK:
            gap = by - m.lane_target
            b.vy = 0.0 if gap == 0 else (-1.0 if gap > 0 else 1.0)
            hand = bx + (-CATCH_REACH if b.anim & ANIM_MIRROR_BIT else CATCH_REACH)
            if abs(hand - _hi(m.x)) < CATCH_WINDOW:
                b.boomerang = None
                _reset(b, left)
                return
        _edge_nudge_and_integrate(b)
    elif tac == 8:
        if d50 >= DASH_STOP_DX or (d50 < DASH_DX_MIN and d52 >= DASH_KEEP_LANE):
            b.vx = 0.0
            b.tactical = 0
        b.vy = _dash_lane_velocity(d52, above)
        _integrate(b)
    elif tac == 9:
        b.t5c = (b.t5c - 1) & 0xFF
        if not b.t5c:
            b.tactical = 0
            b.vx = 0.0
        _integrate(b)
    else:
        _integrate(b)


def contact(b: BossSim, a: ActorSim, *, margin: bool = True) -> Outcome:
    """``$AAA0`` for this pair: grab first, then his attack on the actor.

    Uses the boxes his last update latched (``shown_*``), exactly as the ROM
    does -- the frame on screen is the frame that collides.
    """

    if b.primary not in (PRIMARY_ACTIVE, PRIMARY_KICK):
        return Outcome.NONE
    if a.holding or a.untouchable:
        # $AA34 tests nothing against a player in a hit reaction (+$59 bit 1,
        # which lasts until the floor landing: a knocked-down actor is not
        # kicked again) or one whose +$7C bit 0 is still latched (the code it
        # was just handed), and $AAA0 refuses a grab to one with +$4C set.
        # Measured in lockstep (tools/antonio_lab.py): the updates between a
        # re-grab and his own $17CF2 catching up leave him on kick frame 1
        # with the actor in its hold, and nothing lands.
        return Outcome.NONE
    # The actor's boxes as its own update cached them -- at a camera or lane
    # clamp, one step past where it stands (actor_update).
    dy = abs(_hi(a.box_y) - _hi(b.y))
    bx, ax = _hi(b.x), _hi(a.box_x)
    body = _SHAPE_X.get(b.shown_body)
    if a.walking and body is not None and dy <= CONTACT_LANE:
        lo, hi = (ax - a.walk_reach, ax) if a.facing_left else (ax, ax + a.walk_reach)
        if lo <= bx + body[1] and hi >= bx + body[0]:
            return Outcome.GRAB
    attack = _SHAPE_X.get(b.shown_attack)
    if attack is None:
        return Outcome.NONE
    grow_x = HIT_MARGIN_X if margin else 0
    grow_y = HIT_MARGIN_LANE if margin else 0
    if dy > CONTACT_LANE + grow_y:
        return Outcome.NONE
    if bx + attack[0] - grow_x <= ax + a.body_reach and bx + attack[1] + grow_x >= ax - a.body_reach:
        return Outcome.HIT
    return Outcome.NONE


def _lane_clamp(y: float) -> float:
    """``$17AB8``'s lane clamp, ``$00..$70``, which his boomerang shares."""

    return float(BOSS_LANE_MIN) if y < BOSS_LANE_MIN else (float(BOSS_LANE_MAX) if y >= BOSS_LANE_MAX else y)


def _boomerang_emit(m: BoomerangSim, cam_x: int) -> None:
    """The renderer's tail for it: latch this frame's box and ``+$28``, step."""

    m.screen_x = _hi(m.x) - cam_x + SCREEN_BIAS
    frames = _BOOMERANG_FRAMES.get(m.anim)
    if frames is not None:
        m.shown = frames[m.frame % len(frames)]
        m.frame = (m.frame + 1) % len(frames)


def boomerang_contact(m: BoomerangSim, a: ActorSim, *, margin: bool = True) -> bool:
    """``$AA22`` with the boomerang as the attacker: its latched box on the
    actor's body. (A player's attack on it knocks it away instead; the plan
    never throws one.)"""

    if a.untouchable:
        return False
    box = _BOOMERANG_BOX_X.get(m.shown)
    if box is None:
        return False
    grow_x = HIT_MARGIN_X if margin else 0
    grow_y = HIT_MARGIN_LANE if margin else 0
    if abs(_hi(a.box_y) - _hi(m.y)) > CONTACT_LANE + grow_y:
        return False
    mx, ax = _hi(m.x), _hi(a.box_x)
    return mx + box[0] - grow_x <= ax + a.body_reach and mx + box[1] + grow_x >= ax - a.body_reach


def _fly(m: BoomerangSim, a: ActorSim | None, cam_x: int, *, margin: bool) -> tuple[bool, bool]:
    """One update of a boomerang off his hand: (it hit the actor, it is
    still there). ``a`` None flies it without testing contact."""

    if m.state == BOOMERANG_KNOCKED:
        m.knock_timer -= 1
        if m.knock_timer <= 0:
            return False, False
        m.x += m.vx
        m.y = _lane_clamp(m.y + m.vy)
        return False, True
    if a is not None and boomerang_contact(m, a, margin=margin):
        return True, True
    # $7000 an update, negated for the right-thrown $40: always against the
    # throw -- slowing it out, then bringing it back.
    m.vx += -BOOMERANG_DECEL_X if m.anim == ANIM_BOOMERANG_RIGHT else BOOMERANG_DECEL_X
    if m.state == BOOMERANG_OUT:
        m.vy -= BOOMERANG_DECEL_LANE
        m.countdown -= 1
        if m.countdown <= 0:
            # $172F6: +$52 from its own +$78 (the lea), +$61 which side.
            m.lane_target = m.turn_lane
            m.above = m.turn_lane < _hi(m.y)
            m.vx = m.vy = 0.0
            m.state = BOOMERANG_BACK
    else:
        if abs(_hi(m.y) - m.lane_target) >= BOOMERANG_HOMING_STOP:
            m.vy += -BOOMERANG_HOMING if m.above else BOOMERANG_HOMING
        else:
            m.vy = 0.0
        if not BOOMERANG_SCREEN_MIN <= m.screen_x < BOOMERANG_SCREEN_MAX:
            return False, False
    m.x += m.vx
    m.y = _lane_clamp(m.y + m.vy)
    _boomerang_emit(m, cam_x)
    return False, True


def _boomerang_step(b: BossSim, a: ActorSim | None, *, margin: bool) -> Outcome:
    """One update of his boomerangs, after his own (they live in later
    slots): the linked one, which his wind-up launches, and any older one
    still out. ``a`` None flies them without testing contact."""

    if not b.boomerang_known:
        return Outcome.NONE
    m = b.boomerang
    if m is None or m.state == BOOMERANG_ATTACHED:
        # $173D8: riding his animation's records; the wind-up's frame 2
        # names child animation $40/$42, and that launches it ($17450). It
        # reads his +$0A before the renderer steps it: the frame about to
        # be shown.
        if (
            b.primary == PRIMARY_ACTIVE
            and (b.anim & ~ANIM_MIRROR_BIT) == ANIM_WINDUP
            and b.frame == BOOMERANG_LAUNCH_FRAME
        ):
            left = bool(b.anim & ANIM_MIRROR_BIT)
            b.boomerang = BoomerangSim(
                state=BOOMERANG_OUT,
                x=float(_hi(b.x) + (-BOOMERANG_LAUNCH_DX if left else BOOMERANG_LAUNCH_DX)),
                y=float(_hi(b.y)),
                vx=-BOOMERANG_SPEED if left else BOOMERANG_SPEED,
                vy=BOOMERANG_LANE_SPEED,
                anim=ANIM_BOOMERANG_LEFT if left else ANIM_BOOMERANG_RIGHT,
                frame=0,
                shown=0,
                screen_x=0,
                countdown=BOOMERANG_OUT_UPDATES,
                lane_target=0,
                above=False,
                turn_lane=m.turn_lane if m is not None else 0,
                knock_timer=0,
                slot=m.slot if m is not None else None,
            )
            _boomerang_emit(b.boomerang, b.cam_x)
    else:
        hit, alive = _fly(m, a, b.cam_x, margin=margin)
        if hit:
            return Outcome.HIT
        if not alive:
            b.boomerang = None
    if b.strays:
        kept = []
        for stray in b.strays:
            hit, alive = _fly(stray, a, b.cam_x, margin=margin)
            if hit:
                return Outcome.HIT
            if alive:
                kept.append(stray)
        b.strays = kept
    return Outcome.NONE


def _flying(m: BoomerangSim | None) -> bool:
    return m is not None and m.state in (BOOMERANG_OUT, BOOMERANG_BACK)


def _boomerang_coming(b: BossSim) -> bool:
    """One in flight, or about to be: his wind-up is still playing."""

    if _flying(b.boomerang) or any(_flying(stray) for stray in b.strays):
        return True
    m = b.boomerang
    return (
        b.boomerang_known
        and (m is None or m.state == BOOMERANG_ATTACHED)
        and b.primary == PRIMARY_ACTIVE
        and b.tactical == 6
    )


def _boomerang_path(b: BossSim, updates: int) -> list[list[tuple[int, int, int]]]:
    """Where his boomerangs will be, update by update, if nothing interrupts
    him: the wind-up plays on (for the launch) and he stands where he is
    (for the catch). Their flight never looks at the actor, so one path
    serves every candidate of a plan; entry ``k`` (every boomerang then in
    flight) is after update ``k + 1``."""

    if not _boomerang_coming(b):
        return []
    sim = b.copy()
    path: list[list[tuple[int, int, int]]] = []
    for _ in range(updates):
        _boomerang_step(sim, None, margin=False)
        if sim.primary == PRIMARY_ACTIVE and sim.tactical == 6:
            _emit(sim)
        m = sim.boomerang
        if m is not None and m.state == BOOMERANG_BACK:
            hand = _hi(sim.x) + (-CATCH_REACH if sim.anim & ANIM_MIRROR_BIT else CATCH_REACH)
            if abs(hand - _hi(m.x)) < CATCH_WINDOW:
                sim.boomerang = None
        flying = [x for x in [sim.boomerang, *sim.strays] if _flying(x)]
        if not flying and not _boomerang_coming(sim):
            break
        path.append([(_hi(x.x), _hi(x.y), x.shown) for x in flying])
    return path


def _path_hits(entries: Sequence[Sequence[tuple[int, int, int]]], a: ActorSim) -> bool:
    ax, ay = _hi(a.box_x), _hi(a.box_y)
    for points in entries:
        for x, y, shown in points:
            box = _BOOMERANG_BOX_X.get(shown)
            if box is None or abs(ay - y) > CONTACT_LANE + HIT_MARGIN_LANE:
                continue
            if x + box[0] - HIT_MARGIN_X <= ax + a.body_reach and x + box[1] + HIT_MARGIN_X >= ax - a.body_reach:
                return True
    return False


def boss_update(b: BossSim, a: ActorSim, target: ActorSim | None = None, *, margin: bool = True) -> Outcome:
    """One update of his, against the actor (and his target, if not the actor)."""

    target = a if target is None else target
    if b.pending_hold and a.holding and b.primary in (PRIMARY_ACTIVE, PRIMARY_KICK):
        # $17CF2, before the contact test in both states: the grab $AAA0
        # handed the actor on its last update becomes his held state now.
        b.pending_hold = False
        b.primary = PRIMARY_HELD
        b.inert = HORIZON_UPDATES * 4
        return Outcome.NONE
    if b.primary == PRIMARY_KICK:
        outcome = contact(b, a, margin=margin)
        if outcome is not Outcome.NONE:
            return outcome
        if b.frame >= KICK_END_FRAME:
            b.primary = PRIMARY_ACTIVE
            _set_anim(b, ANIM_IDLE, _hi(target.x) < _hi(b.x))
        # His boomerangs update in the same object pass, before the renderer
        # steps his frame (measured in lockstep: a launch read after the
        # step came one update early).
        outcome = _boomerang_step(b, a, margin=margin)
        _emit(b)
        return outcome
    if b.primary == PRIMARY_ACTIVE:
        outcome = contact(b, a, margin=margin)
        if outcome is not Outcome.NONE:
            return outcome
        _active_step(b, target, margin=margin)
        # His boomerangs update in the same object pass, before the renderer
        # steps his frame (measured in lockstep: a launch read after the
        # step came one update early).
        outcome = _boomerang_step(b, a, margin=margin)
        _emit(b)
        return outcome
    # Hit reaction, held, thrown, knocked down: nothing collides and nothing
    # decides until the reaction runs out. The first free update shows no body
    # box yet (a body on the floor has none), so a walk-in cannot be assumed.
    # His boomerang flies on whatever he is doing.
    b.inert -= 1
    if b.inert <= 0:
        b.primary = PRIMARY_ACTIVE
        b.tactical = 0
        b.t78 = 0
        b.vx = b.vy = 0.0
        _set_anim(b, ANIM_IDLE, _hi(target.x) < _hi(b.x))
        b.shown_attack, b.shown_body = 0, 0
        b.screen_x = _hi(b.x) - b.cam_x + SCREEN_BIAS
    return _boomerang_step(b, a, margin=margin)


def actor_update(a: ActorSim, dir_x: int, dir_y: int) -> None:
    """One update of the actor holding this stick (``$3614``'s walk tables)."""

    if dir_x:
        a.facing_left = dir_x < 0
    a.walking = bool(dir_x or dir_y)
    straight_x, diagonal_x, diagonal_y, straight_y = a.speeds
    if dir_x and dir_y:
        step_x, step_y = diagonal_x, diagonal_y
    else:
        step_x, step_y = straight_x, straight_y
    a.vx = dir_x * step_x
    x = a.x + dir_x * step_x
    y = a.y + dir_y * step_y
    # $4140 caches the player's boxes at the end of its own update; the object
    # pass's $43AA clamps it to the camera and the lane band only afterwards.
    # So at a clamp the boxes his $AAA0 reads stand where the step would have
    # taken it -- measured in lockstep: a walk pinned at the camera's left
    # edge grabbed him 2 px short of where the clamped box reaches.
    a.box_x, a.box_y = x, y
    a.x = min(max(x, a.x_lo), a.x_hi)
    a.y = min(max(y, a.lane_lo), a.lane_hi)


# --- The plan ---------------------------------------------------------------------


def _side(a: ActorSim, b: BossSim) -> int:
    """+1 when the actor is on his right, -1 on his left (facing inside the
    deadband: the engage walks toward him, so facing says where he is)."""

    dx = a.x - b.x
    if abs(dx) < SIDE_DEADBAND_X:
        return 1 if a.facing_left else -1
    return 1 if dx > 0 else -1


def engage_aim(a: ActorSim, b: BossSim) -> tuple[EngageMode, float, float]:
    """Where the actor should be heading, given where both bodies are."""

    side = _side(a, b)
    dx = abs(a.x - b.x)
    dy = a.y - b.y
    pocket_y = b.y - POCKET_DY
    far_x = min(max(b.x + side * FAR_DX, a.x_lo), a.x_hi)
    if pocket_y < a.lane_lo:
        return EngageMode.LURE, far_x, min(a.lane_hi, b.y + LURE_DY)
    if dy <= -POCKET_MIN_DY:
        return EngageMode.POCKET, b.x + side * WALK_IN_STOP_DX, pocket_y
    if dy < 0:
        return EngageMode.RISE, a.x, pocket_y
    if dx >= SAFE_DX:
        hold_x = min(max(b.x + side * max(dx, SAFE_DX), a.x_lo), a.x_hi)
        return EngageMode.CLIMB, hold_x, pocket_y
    return EngageMode.RETREAT, far_x, min(a.lane_hi, max(a.y, b.y + RETREAT_DY))


_MODE_COST = {
    EngageMode.POCKET: 0,
    EngageMode.RISE: 6,
    EngageMode.CLIMB: 20,
    EngageMode.LURE: 30,
    EngageMode.RETREAT: 40,
}


def _track(a: ActorSim, b: BossSim) -> tuple[int, int]:
    """The tail policy: walk straight at the aim, diagonally where it can."""

    _, aim_x, aim_y = engage_aim(a, b)
    dir_x = 0 if abs(aim_x - a.x) <= 2 else (1 if aim_x > a.x else -1)
    dir_y = 0 if abs(aim_y - a.y) <= 1.5 else (1 if aim_y > a.y else -1)
    return dir_x, dir_y


def _time_to(a: ActorSim, aim_x: float, aim_y: float) -> float:
    straight_x, _, _, straight_y = a.speeds
    return max(abs(aim_x - a.x) / max(straight_x, 0.1), abs(aim_y - a.y) / max(straight_y, 0.1))


def _end_danger(
    bosses: Sequence[BossSim], a: ActorSim, follow: Sequence[list] = ()
) -> int:
    danger = 0
    ax, ay = _hi(a.x), _hi(a.y)
    for index, b in enumerate(bosses):
        path = follow[index] if index < len(follow) else None
        if path and _boomerang_coming(b) and _path_hits(path[HORIZON_UPDATES:], a):
            danger += _DANGER_BOOMERANG
        bx, by = _hi(b.x), _hi(b.y)
        dxs, dys = ax - bx, ay - by
        d50, d52 = abs(dxs), abs(dys)
        if b.primary == PRIMARY_KICK:
            ahead = dxs if not (b.anim & ANIM_MIRROR_BIT) else -dxs
            if 0 <= ahead <= 84 + a.body_reach + HIT_MARGIN_X and d52 <= CONTACT_LANE + 2:
                danger += _DANGER_KICK_REACH
        elif b.primary == PRIMARY_ACTIVE and not b.unavailable:
            if _kick_gate(b, a, left=dxs < 0, above=dys < 0, d50=d50, d52=d52, margin=True):
                danger += _DANGER_KICK_GATE
            elif DASH_DX_MIN <= d50 < DASH_DX_MAX and d52 < DASH_LANE and dys > -POCKET_MIN_DY:
                danger += _DANGER_DASH_BELOW
    return danger


_CANDIDATES: tuple[tuple[int, int], ...] = tuple(
    (dx, dy) for dx in (0, 1, -1) for dy in (0, -1, 1)
)


def _rollout(
    bosses: list[BossSim],
    a: ActorSim,
    target: ActorSim | None,
    first: tuple[int, int],
    hold: bool,
    *,
    actor_first: bool,
) -> tuple[Outcome, int | None, list[BossSim], ActorSim]:
    """Play one candidate out. ``actor_first`` picks which of the two bodies
    the next update reaches first -- the snapshot can land on either side of
    ``$AD8E``'s VBlank wait, and the plan has to survive both."""

    moves = 0

    def step_actor() -> None:
        nonlocal moves
        move = first if hold or moves < FIRST_UPDATES else _track(a, bosses[0])
        actor_update(a, *move)
        moves += 1

    if actor_first:
        step_actor()
    for k in range(HORIZON_UPDATES):
        for b in bosses:
            outcome = boss_update(b, a, target)
            if outcome is not Outcome.NONE:
                return outcome, k, bosses, a
        step_actor()
    return Outcome.NONE, None, bosses, a


def _score(
    outcome: Outcome,
    at: int | None,
    bosses: list[BossSim],
    a: ActorSim,
    follow: Sequence[list] = (),
) -> float:
    if outcome is Outcome.GRAB:
        return _SCORE_GRAB - _SCORE_PER_UPDATE * at
    if outcome is Outcome.HIT:
        return _SCORE_HIT + _SCORE_PER_UPDATE * at
    mode, aim_x, aim_y = engage_aim(a, bosses[0])
    return -(_time_to(a, aim_x, aim_y) + _MODE_COST[mode] + _end_danger(bosses, a, follow))


def split_boomerangs(
    antonio: Antonio, projectiles: Sequence[Projectile]
) -> tuple[Projectile | None, list[Projectile]]:
    """His linked boomerang (the ``$96`` his ``+$6E`` names) and any older
    one still out. With no link known, one on his hand is taken as his."""

    boomerangs = [p for p in projectiles if p.type_id == BOOMERANG_TYPE]
    linked = next((p for p in boomerangs if antonio.child_slot and p.slot == antonio.child_slot), None)
    if linked is None and not antonio.child_slot:
        linked = next((p for p in boomerangs if p.state == BOOMERANG_ATTACHED), None)
    strays = [
        p
        for p in boomerangs
        if p is not linked and p.state in (BOOMERANG_OUT, BOOMERANG_BACK, BOOMERANG_KNOCKED)
    ]
    return linked, strays


def plan_engage(
    actor: PlayableCharacter,
    antonio: Antonio,
    *,
    camera: CameraRange | None = None,
    others: Sequence[Antonio] = (),
    partner: PlayableCharacter | None = None,
    projectiles: Sequence[Projectile] | None = None,
) -> EngagePlan:
    """The stick for this tick: every candidate played out against his AI.

    Seventeen candidates -- the nine stick positions, each either held for
    the whole horizon or for ``FIRST_UPDATES`` and then handed to the tail
    policy that walks at ``engage_aim`` -- of ``HORIZON_UPDATES`` updates
    each, over ``boss_update``/``actor_update``, and each one twice: once
    with his update reaching the actor before this stick does, once after.
    A snapshot can land on either side of ``$AD8E``'s VBlank wait, and a
    candidate is scored by the worse of the two -- which is what keeps the
    stick on him at the moment of contact: let go a frame early and the
    walking box that was the grab is gone, and the kick it was beating lands.

    A rollout that takes the hold scores by how soon; one that is hit scores
    below everything else by how soon; the rest score by how far the actor
    ends from ``engage_aim``'s point, what that mode costs, and whether his
    gate or his kick is live on the actor where the rollout ends.
    """

    lane_lo, lane_hi = float(PLAYER_LANE_MIN), float(PLAYER_LANE_MAX)
    x_lo, x_hi = (camera.left, camera.right) if camera is not None else (-1e9, 1e9)
    cam_x = int(camera.left) - 0x20 if camera is not None else 0
    if antonio.screen_x:
        cam_x = antonio.world_x + SCREEN_BIAS - antonio.screen_x
    actor0 = ActorSim.from_token(actor, lane_lo=lane_lo, lane_hi=lane_hi, x_lo=x_lo, x_hi=x_hi)
    # A hit reaction's immunity ends on the floor landing, which the rollout
    # does not model -- so the plan assumes it already has: his gates live and
    # his kick landing, the side that never walks into one.
    actor0.untouchable = actor0.unavailable = False
    linked, strays = split_boomerangs(antonio, projectiles or ())
    bosses0 = [
        BossSim.from_token(
            antonio,
            cam_x=cam_x,
            boomerang=linked,
            strays=strays,
            boomerang_known=projectiles is not None,
        )
    ] + [BossSim.from_token(other, cam_x=cam_x) for other in others]
    # Its flight never looks at the actor: one path past the horizon for all.
    follow = [_boomerang_path(b, HORIZON_UPDATES + BOOMERANG_FOLLOW_UPDATES) for b in bosses0]
    target0: ActorSim | None = None
    if partner is not None and antonio.targets_player not in (None, actor.player_index):
        target0 = ActorSim.from_token(partner, lane_lo=lane_lo, lane_hi=lane_hi, x_lo=x_lo, x_hi=x_hi)
        target0.walking = False
        target0.vx = 0.0
        target0.untouchable = target0.unavailable = False

    moving_x = 1 if actor.vel_x > 0.5 else (-1 if actor.vel_x < -0.5 else 0)
    toward_x = 1 if bosses0[0].x > actor0.x else -1
    mode_now = engage_aim(actor0, bosses0[0])[0]
    best: EngagePlan | None = None
    for hold in (False, True):
        for first in _CANDIDATES:
            if hold and first == (0, 0):
                continue  # the same rollout as the tail-free "stand"
            worst: tuple[float, Outcome, int | None] | None = None
            for actor_first in (False, True):
                outcome, at, bosses, a = _rollout(
                    [b.copy() for b in bosses0],
                    actor0.copy(),
                    target0,
                    first,
                    hold,
                    actor_first=actor_first,
                )
                score = _score(outcome, at, bosses, a, follow)
                if worst is None or score < worst[0]:
                    worst = (score, outcome, at)
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
    antonio: Antonio,
    actor: PlayableCharacter,
    inputs: Sequence[tuple[int, int]],
    *,
    camera: CameraRange | None = None,
    margin: bool = False,
    boomerang: Projectile | None = None,
    boomerang_known: bool = False,
    strays: Sequence[Projectile] = (),
) -> list[tuple[Outcome, float, float, int, int]]:
    """Play ``inputs`` (one stick per update) against his AI, for tests and
    tools: per update, the outcome and his ``(x, y, primary, tactical)``."""

    x_lo, x_hi = (camera.left, camera.right) if camera is not None else (-1e9, 1e9)
    cam_x = int(camera.left) - 0x20 if camera is not None else 0
    if antonio.screen_x:
        cam_x = antonio.world_x + SCREEN_BIAS - antonio.screen_x
    a = ActorSim.from_token(
        actor, lane_lo=float(PLAYER_LANE_MIN), lane_hi=float(PLAYER_LANE_MAX), x_lo=x_lo, x_hi=x_hi
    )
    b = BossSim.from_token(
        antonio, cam_x=cam_x, boomerang=boomerang, strays=strays, boomerang_known=boomerang_known
    )
    trace = []
    for move in inputs:
        outcome = boss_update(b, a, margin=margin)
        trace.append((outcome, b.x, b.y, b.primary, b.tactical))
        if outcome is not Outcome.NONE:
            break
        actor_update(a, *move)
    return trace


# --- The hold loop ---------------------------------------------------------------


def hold_step(actor: PlayableCharacter, antonio: Antonio) -> HoldStep:
    """Knee, knee, release -- and only ever finish when finishing kills.

    The same loop as Souther's (``souther.hold_step``): every piece of it is
    the *player's* code -- the knee chain in ``+$58``/``+$61``, ``loc_235A``'s
    release countdown, the one crossover in ``+$4B`` bit 7 -- and a released
    later boss goes to primary 1 in front of the actor through the shared
    ``$17CF2``. Antonio lands 40 px out (``$17D76``'s ``$28``) where Souther
    lands 32, and his first free update from there is either the dash, which
    walks his body into the actor's box, or the kick, whose frame-1 lean
    (-6..22 px) meets the walking box before its 30 px reach meets the body.
    """

    return _shared_hold_step(actor, antonio)
