"""Round 6's two Southers: his state-1 AI replayed, for the one who is *not*
in the actor's hands.

``souther.py`` is the plan against one Souther, and it is measured: take a
hold, knee, knee, release, walk straight back in. Round 6 sends two of them
(two ``$55`` records after Bongo, both targeting P1 in a 1P game), and that
plan never looks at the second. Scored with ``tools/boss_fight.py --level 6``
(Blaze, no food, no police, nine fights on the plan as it stood): 7.6 hits and
two lives a fight, three of the nine lost the whole game. Nearly every hit
lands on the actor while it is *holding the other one* -- the hold roots it,
and the free Souther walks up and commits his claw.

Everything here comes from ``$15EDA (souther_state1_active_combat)`` and the
tactical handlers under it (``ai-analysis/enemy-ai.md``, "Souther"), replayed
update by update so the plan can ask one question before it takes or keeps a
hold: *can the other one commit on the actor before it is free again?*

The commit gate (every update in primary 1, before the tactical)
    ``+$50`` in ``[$18, T)`` -- ``T`` is ``$68``/``$58``/``$50`` for a target
    whose own ``+$1C`` high word says it walks into him / stands / walks away
    -- and ``+$52 < $0A`` with the target above his lane, ``< $1C``
    otherwise; skipped while ``+$77`` (the target unavailable) or ``+$66``
    (he is held). ``souther.can_commit_on`` is the same gate, one update.
Tactical 0, the standoff (``$15F98``)
    *off screen* (``+$28`` outside ``[$80, $1C0)``): a 4 px dash back in for
    ``$28`` updates (``$22`` and 4.5 px for pair role 2), lane 4 px away from
    the half of the street the target is in;
    *inside ``$19``* of the target on X: the band-restore below;
    *the target facing away from him*: the **rush** -- 4 px an update at it
    (4.5 for role 2), stopped inside ``$48`` with the lanes under ``$20``,
    while ``$179AC`` keeps the target 18-21 px *below* him (4 px up at once
    if it is above). From 18-21 px above, the lane gate is ``$1C``: the rush
    ends in a commit. This is how a Souther behind a holding actor claws it;
    *the target facing him*: the **band-restore** -- 1 px an update away
    inside ``$78`` (``$88`` role 2), 1 px toward past ``$90`` (``$98``), X
    velocity kept in between; lane: the target's own ``+$20`` negated (a
    mirror: the target walking up sends him down), 1 px up while it walks
    level, still while it stands -- plus half a pixel down for role 2
    (``addi.w #$8000`` on the fraction).
    Every ``$78`` updates of ``+$7B`` with the target's lane at ``$10`` or
    more, tactical 1 instead.
Tactical 1, the attack run (``$160D0``)
    4 px an update at the target (4.5 role 2) and ``$179AC``'s lane, until the
    target's lane is under ``$14`` or ``+$50`` under ``$19``.
Tactical 2 (``$16106``)
    counts ``+$5C`` down, then stops on X.
``$17AB8`` integrates: X free, lane clamped to ``$00..$70``.

Out of that, the fact that decides the pair fight: **a Souther the holding
actor faces away from rushes it.** The hold faces the actor at the body in its
hands, so a second Souther behind it closes at 4 px an update, settles 18-21 px
above its lane and claws. One the actor faces backs off at 1 px -- and claws
only from inside his gate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Sequence

from . import kinematics
from . import souther as single
from .tokens import PlayableCharacter, Souther

PRIMARY_ACTIVE = 0x01
PRIMARY_CLAW = 0x02
PRIMARY_HELD = 0x04

# --- The commit gate ($15EDA) --------------------------------------------------

POCKET_DX = 0x18
COMMIT_DX_CLOSING = 0x68
COMMIT_DX_STANDING = 0x58
COMMIT_DX_AWAY = 0x50
COMMIT_LANE_ABOVE = 0x0A
COMMIT_LANE_LEVEL_OR_BELOW = 0x1C

# --- The standoff ($15F98) and the attack run ($160D0) -------------------------

RESTORE_DX = 0x19  # +$50 under this: the band-restore, whatever the facing
RUSH_SPEED = 4.0
RUSH_SPEED_ROLE_TWO = 4.5  # addi.w #$8000 on the 4 px long
RUSH_STOP_DX = 0x48  # inside this with the lanes under $20: X stops
RUSH_STOP_LANE = 0x20
BAND_ROLE_ONE = (0x78, 0x90)
BAND_ROLE_TWO = (0x88, 0x98)
RESTORE_SPEED = 1.0
ATTACK_RUN_TIMER = 0x78  # +$7B
ATTACK_RUN_MIN_LANE = 0x10  # the target's lane, to start one ...
ATTACK_RUN_EXIT_LANE = 0x14  # ... and under this it stops
SCREEN_LEFT = 0x80
SCREEN_RIGHT = 0x1C0
SCREEN_CENTRE = 0x120
SCREEN_BIAS = 0x80
CLAMP_DASH_SPEED = 4.0
CLAMP_LANE_SPLIT = 0x38
CLAMP_DASH_UPDATES = 0x28
CLAMP_DASH_UPDATES_ROLE_TWO = 0x22
LANE_MIN = 0x00
LANE_MAX = 0x70

# A later boss's second role (+$5D) -- the second record of the pair.
ROLE_TWO = 2


def _hi(value: float) -> int:
    """The integer word of a 16.16 value, as the ROM's ``move.w`` reads it."""

    return int(value // 1)


def _toggle_half(value: float) -> float:
    """``addi.w #$8000`` on the fraction word: +0.5, without the carry."""

    raw = int(round(value * 65536)) & 0xFFFFFFFF
    raw = (raw & 0xFFFF0000) | ((raw + 0x8000) & 0xFFFF)
    if raw & 0x80000000:
        raw -= 1 << 32
    return raw / 65536


def keep_below_lane_velocity(d52: int, above: bool) -> float:
    """``$179AC``: keep the target 18-21 px below him; rush one above him."""

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


def commit_dx(target_vx: float, target_left_of_him: bool) -> int:
    """``T`` of the X gate, from the target's own ``+$1C`` high word."""

    hi = _hi(target_vx)
    if hi == 0:
        return COMMIT_DX_STANDING
    signed = -hi if target_left_of_him else hi
    return COMMIT_DX_CLOSING if signed < 0 else COMMIT_DX_AWAY


def commit_gate(d50: int, d52: int, *, above: bool, target_vx: float, target_left_of_him: bool) -> bool:
    lane = COMMIT_LANE_ABOVE if above else COMMIT_LANE_LEVEL_OR_BELOW
    return POCKET_DX <= d50 < commit_dx(target_vx, target_left_of_him) and d52 < lane


@dataclass(slots=True)
class TargetState:
    """The actor as his update reads it: position, ``+$1C``/``+$20``, the
    mirror bit ``+$09`` bit 1 (facing left), and ``$179F8``'s availability."""

    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    facing_left: bool = False
    unavailable: bool = False

    @classmethod
    def from_actor(cls, actor: PlayableCharacter) -> TargetState:
        return cls(
            x=actor.fine_x or float(actor.world_x),
            y=actor.fine_y or float(actor.world_y),
            vx=actor.vel_x,
            vy=actor.vel_lane,
            facing_left=actor.facing_left,
        )

    def standing(self, *, facing_left: bool) -> TargetState:
        """The same actor rooted in a hold, facing the body in its hands."""

        return replace(self, vx=0.0, vy=0.0, facing_left=facing_left, unavailable=False)


@dataclass(slots=True)
class SoutherSim:
    """His object, reduced to what primary 1 reads and writes."""

    x: float
    y: float
    vx: float
    vy: float
    primary: int
    tactical: int
    t7b: int
    t5c: int
    role_two: bool
    screen_x: int
    cam_x: int
    held: bool
    # Updates left in a state that decides nothing (hit reaction, knocked
    # down, thrown, the lethal gate), after which primary 1 resumes.
    inert: int

    @classmethod
    def from_token(cls, souther: Souther, *, cam_x: int | None = None) -> SoutherSim:
        x = souther.fine_x or float(souther.world_x)
        y = souther.fine_y or float(souther.world_y)
        if cam_x is None:
            cam_x = souther.world_x + SCREEN_BIAS - souther.screen_x if souther.screen_x else 0
        primary = souther.primary_state
        inert = 0
        if primary not in (PRIMARY_ACTIVE, PRIMARY_CLAW):
            inert = max(1, souther.reaction_timer - 2) if primary != PRIMARY_HELD else 1 << 16
        return cls(
            x=x,
            y=y,
            vx=souther.boss_vel_x,
            vy=souther.boss_vel_lane,
            primary=primary,
            tactical=souther.tactical & 0x7F,
            t7b=souther.mode_flags & 0xFF,
            t5c=souther.timer_5c & 0xFF,
            role_two=souther.pair_role == ROLE_TWO,
            screen_x=souther.screen_x or (_hi(x) - cam_x + SCREEN_BIAS),
            cam_x=cam_x,
            held=bool(souther.hold_flags & 0x01),
            inert=inert,
        )

    def copy(self) -> SoutherSim:
        return replace(self)


def _integrate(s: SoutherSim) -> None:
    s.x += s.vx
    y = s.y + s.vy
    s.y = float(LANE_MIN) if y < LANE_MIN else (float(LANE_MAX) if y >= LANE_MAX else y)


def _band_restore(s: SoutherSim, t: TargetState, *, d50: int, left: bool) -> None:
    near, far = BAND_ROLE_TWO if s.role_two else BAND_ROLE_ONE
    if d50 <= near:
        s.vx = RESTORE_SPEED if left else -RESTORE_SPEED
    elif d50 >= far:
        s.vx = -RESTORE_SPEED if left else RESTORE_SPEED
    if t.vy != 0:
        vy = -t.vy
        s.vy = _toggle_half(vy) if s.role_two else vy
    elif abs(_hi(t.vx)) >= 1:
        s.vy = -1.0
    else:
        s.vy = 0.5 if s.role_two else 0.0
    _integrate(s)


def update(s: SoutherSim, t: TargetState) -> bool:
    """One update of his; True on the one that commits the claw."""

    if s.primary == PRIMARY_CLAW:
        return False
    if s.primary != PRIMARY_ACTIVE:
        s.inert -= 1
        if s.inert <= 0:
            s.primary = PRIMARY_ACTIVE
            s.tactical = 0
            s.t7b = 0
            s.vx = s.vy = 0.0
        return False

    dx = _hi(t.x) - _hi(s.x)
    left = dx < 0
    d50 = abs(dx)
    dy = _hi(t.y) - _hi(s.y)
    above = dy < 0
    d52 = abs(dy)
    s.t7b = (s.t7b + 1) & 0xFF
    if t.unavailable:
        s.t7b = 0
    elif not s.held and commit_gate(d50, d52, above=above, target_vx=t.vx, target_left_of_him=left):
        s.primary = PRIMARY_CLAW
        s.tactical = 0
        s.t7b = 0
        return True

    speed = RUSH_SPEED_ROLE_TWO if s.role_two else RUSH_SPEED
    if s.tactical == 1:
        if _hi(t.y) < ATTACK_RUN_EXIT_LANE or d50 < RESTORE_DX:
            s.tactical = 0
        s.vx = -speed if left else speed
        s.vy = keep_below_lane_velocity(d52, above)
        _integrate(s)
    elif s.tactical == 2:
        s.t5c = (s.t5c - 1) & 0xFF
        if s.t5c == 0:
            s.tactical = 0
            s.vx = 0.0
        _integrate(s)
    else:
        if s.t7b >= ATTACK_RUN_TIMER:
            s.t7b = 0
            if t.unavailable:
                _band_restore(s, t, d50=d50, left=left)
                s.screen_x = _hi(s.x) - s.cam_x + SCREEN_BIAS
                return False
            if _hi(t.y) >= ATTACK_RUN_MIN_LANE:
                s.tactical = 1
                return False
        if not SCREEN_LEFT <= s.screen_x < SCREEN_RIGHT:
            s.vx = CLAMP_DASH_SPEED if s.screen_x < SCREEN_CENTRE else -CLAMP_DASH_SPEED
            lane = speed
            if _hi(t.y) >= CLAMP_LANE_SPLIT:
                lane = -lane
            s.vy = lane
            s.t5c = CLAMP_DASH_UPDATES_ROLE_TWO if s.role_two else CLAMP_DASH_UPDATES
            s.tactical = 2
            _integrate(s)
        elif d50 < RESTORE_DX:
            _band_restore(s, t, d50=d50, left=left)
        elif t.facing_left == left:
            # The target faces away from him: the rush.
            vx = -speed if left else speed
            if d50 < RUSH_STOP_DX and d52 < RUSH_STOP_LANE:
                vx = 0.0
            s.vx = vx
            s.vy = keep_below_lane_velocity(d52, above)
            _integrate(s)
        else:
            _band_restore(s, t, d50=d50, left=left)
    s.screen_x = _hi(s.x) - s.cam_x + SCREEN_BIAS
    return False


def commits_within(s: SoutherSim, t: TargetState, updates: int) -> int | None:
    """The update (1-based) on which he commits on a target standing as
    ``t`` for ``updates`` updates, or None. A claw already live counts as
    committed at once."""

    if s.primary == PRIMARY_CLAW:
        return 0
    sim = s.copy()
    for k in range(1, updates + 1):
        if update(sim, t):
            return k
    return None


# --- The plan -------------------------------------------------------------------

# Two updates of slack on every window below: the snapshot is up to a poll old,
# and the press reaches the game a poll later.
MARGIN_UPDATES = 2
# The claw box ($6D/$6F/$71 of set $2E44A) reaches 0..86 px ahead of him over
# lane -10..+24 of his own; a body is +-8 (souther.PLAYER_BODY_HALF_Y) and 7
# wide. Grown by the same 4 px souther.plan_engage's own escape uses.
CLAW_ESCAPE_MARGIN = 4


def updates_for_frames(frames: int) -> int:
    return math.ceil(frames / 2)


def live_southers(southers: Sequence[Souther]) -> list[Souther]:
    return [s for s in southers if not s.is_defeated and s.primary_state != 0x00]


def pick_target(actor: PlayableCharacter, southers: Sequence[Souther]) -> Souther:
    """Which of the pair the engage goes for.

    One the actor can walk into this instant first -- which after a release is
    the one it just let go, 32 px in front on its own lane -- so the hold loop
    stays on one body. Then one that can be grabbed at all (not knocked down or
    thrown, ``souther.UNTOUCHABLE_PRIMARIES``) over one that cannot. Then the
    nearest: the stable tie-break the ranking used to fall back on picked the
    lower slot, and walked the actor past one Souther to reach the other.
    """

    def in_walk_in(s: Souther) -> bool:
        return (
            single.in_grab_lane(single.lane_gap(actor, s))
            and abs(s.world_x - actor.world_x) < single.WALK_IN_DX
            and s.primary_state not in single.UNTOUCHABLE_PRIMARIES
        )

    def key(s: Souther) -> tuple:
        return (
            not in_walk_in(s),
            s.primary_state in single.UNTOUCHABLE_PRIMARIES,
            abs(s.world_x - actor.world_x) + abs(s.world_y - actor.world_y) / 2,
            s.slot,
        )

    return min(southers, key=key)


def others_eta(
    actor: PlayableCharacter,
    held: Souther,
    others: Sequence[Souther],
    *,
    updates: int,
    cam_x: int | None = None,
) -> int | None:
    """The soonest update on which another Souther commits on the actor
    rooted where it stands, facing ``held`` -- or None within ``updates``."""

    target = TargetState.from_actor(actor).standing(facing_left=held.world_x < actor.world_x)
    soonest: int | None = None
    for other in others:
        eta = commits_within(SoutherSim.from_token(other, cam_x=cam_x), target, updates)
        if eta is not None and (soonest is None or eta < soonest):
            soonest = eta
    return soonest


def hold_step(
    actor: PlayableCharacter, held: Souther, others: Sequence[Souther], *, cam_x: int | None = None
) -> single.HoldStep:
    """``souther.hold_step``, unless the other Souther arrives first.

    The loop roots the actor for a knee (17-18 frames), and the release and the
    walk back in after it; a free Souther that commits inside that time claws a
    body that cannot move. The throw is the one exit (41-46 frames, and the
    body in hand lands 100-165 px off, knocked down for ~30 updates): taken
    while another knee *and* the throw after it would no longer both fit
    before he commits. A release would not do -- the body let go lands 32 px in
    front on the actor's lane, inside his own gate, and commits at once unless
    it is walked straight back into.
    """

    step = single.hold_step(actor, held)
    if actor.action_base != 0x60 or step not in (single.HoldStep.KNEE, single.HoldStep.RELEASE):
        return step
    if step is single.HoldStep.KNEE and single.signed_health(held) <= single.HOLD_THIRD_KNEE_DAMAGE:
        return step  # the knee that kills ends it sooner than a throw would
    cid = actor.character_id
    knee = updates_for_frames(kinematics.hold_knee_frames(cid))
    throw = updates_for_frames(kinematics.hold_throw_frames(cid))
    horizon = knee + throw + MARGIN_UPDATES
    eta = others_eta(actor, held, others, updates=horizon, cam_x=cam_x)
    if eta is not None:
        return single.HoldStep.THROW
    return step


def claw_threatens(actor: PlayableCharacter, other: Souther, *, margin: int = CLAW_ESCAPE_MARGIN) -> bool:
    """A claw of his is live and the actor stands in its reach."""

    if not single.claw_is_live(other):
        return False
    ahead = (other.world_x - actor.world_x) if other.facing_left else (actor.world_x - other.world_x)
    reach = single.CLAW_REACH_X + single.PLAYER_BODY_HALF_X + margin
    return -margin <= ahead <= reach and single.in_claw_lane(single.lane_gap(actor, other), margin=margin)


def claw_escape_y(actor: PlayableCharacter, other: Souther, *, lane_lo: float, lane_hi: float) -> float | None:
    """The nearer lane out of his claw's band: above it (18 + margin over his
    lane) or below it (32 + margin under), whichever the street has room for."""

    up = other.world_y - (single.CLAW_LANE_ABOVE + single.PLAYER_BODY_HALF_Y + CLAW_ESCAPE_MARGIN)
    down = other.world_y + (single.CLAW_LANE_BELOW + single.PLAYER_BODY_HALF_Y + CLAW_ESCAPE_MARGIN)
    options = [y for y in (up, down) if lane_lo <= y <= lane_hi]
    if not options:
        return None
    return min(options, key=lambda y: abs(y - actor.world_y))


def plan_engage(
    actor: PlayableCharacter,
    target: Souther,
    others: Sequence[Souther],
    *,
    lane_lo: float,
    lane_hi: float,
) -> single.EngagePlan:
    """``souther.plan_engage`` on ``target``, with the other one's claw in it.

    His own plan already keeps the actor out of *his* gate and his claw, and
    walks in where the lean contact beats a claw. The pair adds one case the
    measured fights keep showing: the grab taken, or about to be, while the
    other one's claw is already swinging at the actor -- the hold then roots it
    right where the claw lands. Out of his band first, by lane, with X held.
    """

    plan = single.plan_engage(actor, target, lane_lo=lane_lo, lane_hi=lane_hi)
    for other in others:
        if claw_threatens(actor, other):
            escape = claw_escape_y(actor, other, lane_lo=lane_lo, lane_hi=lane_hi)
            if escape is not None:
                return single.EngagePlan(
                    single.EngageMode.ESCAPE_CLAW, actor.world_x, int(escape), False, plan.toward
                )
    return plan
