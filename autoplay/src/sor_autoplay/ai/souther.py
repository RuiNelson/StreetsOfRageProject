"""Souther (type ``$55``, round 2): the ROM model, and the plan built on it.

Everything the AI does against him is decided here, as pure functions of the
tokens already in the context, so the decision (``decide``), the ranking
(``priority``) and the controller (``execute``) cannot disagree about it.

**The plan, in one line: take one hold, and never give him back a turn.**

1. *Engage* -- reach grab contact without ever standing where his claw can
   start or land (``plan_engage``);
2. *hold loop* -- knee, knee, release, re-grab, repeated from that one hold
   until he is dead (``hold_step``). Every cycle is 4 damage for about 55
   frames, and he never leaves the actor's hands for more than a few frames.

Both halves come straight from the disassembly, and the hold loop was then
measured frame by frame in lockstep (``tools/souther_hold_lab.py``). The
facts it rests on, with where each one lives:

The claw commit (``$15EDA souther_state1_active_combat``)
    fires when ``+$50`` (X gap) is in ``[$18, T)`` -- ``T`` is ``$68``/
    ``$58``/``$50`` for a target walking in / standing / backing off -- and
    ``+$52`` (lane gap) is under **``$0A`` when the target is above him**
    (``+$61``, ``smi`` of target lane minus his, from ``$17B2C``) and
    ``$1C`` otherwise, with ``+$66`` (held) clear. The side matters by a
    factor of almost three, and every earlier Souther attempt used ``$1C``
    for both.
The claw itself
    is *his own* attack box, animation ``+$8 = 4`` of set ``$2E44A``: 20
    frames, shapes ``$6D``/``$6F``/``$71`` reaching 0..48, 46..86 and 40..80
    px forward, all three over lane **-10..+24** of his own lane. The type-``$98``
    "claw" object carries no box at all. During the claw his *body* box leans
    forward too (shapes ``$69``/``$6B``: 12..36, 12..42 px).
Grab beats hit (``$AAA0``)
    tests the player's attack box against his body box *first*; when they
    overlap it returns the grab (code 3) or a hit, and his own attack box is
    never tested that frame. Walking into him with the walking box out is
    therefore safe whenever that box reaches his body -- including through
    the claw's forward lean.
He updates at 30 Hz
    every timer and speed of his runs once per two frames (``+$62`` counts
    down every other frame in every lab trace).
The hold
    ``$3266`` takes it when the two face each other (front ``$60``) or the
    actor is behind (back ``$66``). Knees are ``$2BA8``'s chain ``$6A``
    -> ``$6C`` -> ``$6E`` (2, 2, then 3 and a knockback that ends the hold).
    Holding *back* in a front hold counts ``+$63`` down from 3 and drops the
    hold when it goes negative (``loc_235A``); the boss is then released
    straight to primary 1, 32 px in front of the actor (``$17D76``), on the
    actor's lane. Only one crossover per hold (``$26E2`` refuses a second via
    the player's ``+$4B`` bit 7, and the second one lands the actor next to a
    free boss -- measured: 20 damage three frames later).

Measured with ``tools/souther_hold_lab.py`` (Blaze, lockstep): knee, knee,
release, walk straight back in -- re-held 4-6 frames after the release, six
cycles in a row, no damage; with two frames of injected input delay he *does*
commit, 3 frames after the release, and the walk-in still takes the hold at
frame 6 because his leaning body walks into the actor's box. The throw and
the suplex both leave him 100-165 px away on the actor's lane, which is the
re-approach every earlier plan paid for.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .tokens import PlayableCharacter, Souther

# --- The commit gate ($15EDA) -------------------------------------------------

POCKET_DX = 0x18  # +$50 < $18: the inner abort -- he cannot start a claw here
COMMIT_DX_CLOSING = 0x68  # target walking into him (the widest window)
COMMIT_LANE_ABOVE = 0x0A  # +$61 set: target strictly above his lane
COMMIT_LANE_LEVEL_OR_BELOW = 0x1C

# --- His claw (his own attack box, anim +$8 = 4 of set $2E44A) ---------------

CLAW_LANE_ABOVE = 10  # shape lane -10..+24 about his own lane
CLAW_LANE_BELOW = 24
CLAW_REACH_X = 86  # shape $6F (frames 3-6): 46..86 px forward
# The player's body box is lane +-8 (+$70); half its width, conservatively.
PLAYER_BODY_HALF_Y = 8
PLAYER_BODY_HALF_X = 7

# --- Grab contact ($AAA0 code 3) ----------------------------------------------

# How far the actor's *walking* attack box (+$64) reaches ahead of its own
# origin. Measured for Blaze in the lab (x0 = origin - 19 facing left); Axel
# and Adam are unmeasured and get a conservative figure, which only ever makes
# the walk-in zone smaller.
WALK_BOX_REACH_X: dict[int, int] = {2: 19}
DEFAULT_WALK_BOX_REACH_X = 14
IDLE_BODY_FRONT_X = 12  # shape $65 (idle): -10..+12
CLAW_BODY_FRONT_X = 36  # shape $69, the claw's first frame (12..36) -- the nearer lean
# Both boxes are lane +-8, so contact needs the two lanes strictly under 16
# apart; one pixel of margin.
GRAB_LANE = 15

# --- The hold ------------------------------------------------------------------

HOLD_KNEE_DAMAGE = 2  # $6A and $6C
HOLD_THIRD_KNEE_DAMAGE = 3  # $6E -- and the knockback that ends the hold
HOLD_SUPLEX_DAMAGE = 5
# The release countdown ends on the 8th back frame from a fresh 3 in every lab
# cycle (the player's front-hold handler steps it about once per two frames).
RELEASE_FRAMES_PER_COUNT = 2

# --- The engage geometry ---------------------------------------------------------

# Above him the commit lane is only 10 px and the grab's own lane is 15, so an
# actor 11-15 px above his lane can be neither committed on nor out of reach.
# He drifts *up* one px per update whenever the actor walks level toward him
# (``$1609E``'s band-restore), so the aim sits in the middle of that band and
# the executor's lane deadband re-lifts before the gate can open.
ABOVE_AIM_DY = -15
# Below him the gate is 28 px and the claw's deep side reaches 24 + 8 = 32, so
# the corridor aims past both with the deadband to spare; his level-walk drift
# only ever widens this side, which is what makes it the stable one.
BELOW_AIM_DY = 38
# How much room a side needs before it can be used at all.
ABOVE_ROOM = -ABOVE_AIM_DY + 4
BELOW_ROOM = BELOW_AIM_DY + 4
# Walk straight in on his lane from here: inside it, even a claw he commits
# this instant leans his body into the actor's walking box before it can land
# (claw body front 36 + walking box 19 = 55, less margin). Measured from the
# re-grab: committed 3 frames after the release, held at 6, no damage.
WALK_IN_DX = 48
# Close the lane from below only inside his inner abort, where the lanes the
# converging actor passes through (16-28 px under him: inside his claw, not yet
# inside the grab) cannot be committed on.
CONVERGE_DX = POCKET_DX - 4
# Where the walk-in and the pocket aim on X: short of his origin on the
# actor's own side, so the walk never carries through him.
WALK_IN_STOP_DX = 8
POCKET_STOP_DX = 12
# Below this X gap the raw side compare is walk jitter.
SIDE_DEADBAND_X = 6

# Primaries he cannot act *or be grabbed* in: the hit reaction, the lethal
# gate, the grabbee/throw states and the police reaction never call $17B52.
UNTOUCHABLE_PRIMARIES = frozenset({0x03, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A})
CLAW_PRIMARY = 0x02


def signed_health(souther: Souther) -> int:
    health = souther.health or 0
    return health - 0x10000 if health >= 0x8000 else health


def walk_box_reach_x(character_id: int | None) -> int:
    if character_id is None:
        return DEFAULT_WALK_BOX_REACH_X
    return WALK_BOX_REACH_X.get(character_id, DEFAULT_WALK_BOX_REACH_X)


def lane_gap(actor: PlayableCharacter, souther: Souther) -> int:
    """Signed lane offset of the actor from his lane: negative is above him."""

    return actor.world_y - souther.world_y


def commit_lane(dy: int) -> int:
    """The lane gate ``$15EDA`` applies for an actor ``dy`` off his lane."""

    return COMMIT_LANE_ABOVE if dy < 0 else COMMIT_LANE_LEVEL_OR_BELOW


def can_commit_on(actor: PlayableCharacter, souther: Souther) -> bool:
    """Would ``$15EDA`` start a claw on this actor from here, on a free tick?

    The widest X window (walking in) on purpose -- the approach always is --
    and the side-dependent lane gate the ROM actually applies.
    """

    if souther.is_defeated or souther.primary_state != 0x01:
        return False
    adx = abs(souther.world_x - actor.world_x)
    dy = lane_gap(actor, souther)
    return POCKET_DX <= adx < COMMIT_DX_CLOSING and abs(dy) < commit_lane(dy)


def in_claw_lane(dy: int, *, margin: int = 0) -> bool:
    """Is a body ``dy`` off his lane inside the claw's lane band?"""

    return -(CLAW_LANE_ABOVE + PLAYER_BODY_HALF_Y + margin) < dy < (
        CLAW_LANE_BELOW + PLAYER_BODY_HALF_Y + margin
    )


def in_grab_lane(dy: int) -> bool:
    return abs(dy) <= GRAB_LANE


def claw_is_live(souther: Souther) -> bool:
    return souther.primary_state == CLAW_PRIMARY


def side_of(actor: PlayableCharacter, souther: Souther) -> int:
    """+1 when the actor stands on his right, -1 on his left.

    Read off facing inside ``SIDE_DEADBAND_X``: the engage always walks
    *toward* him, so the way the actor faces is the way he lies, and a raw
    position compare there is only walk jitter.
    """

    dx = actor.world_x - souther.world_x
    if abs(dx) < SIDE_DEADBAND_X:
        return 1 if actor.facing_left else -1
    return 1 if dx > 0 else -1


class EngageMode(Enum):
    """What the engage is doing this tick -- see ``plan_engage``."""

    WALK_IN = auto()
    """In the grab's lane and inside the lean-contact range: walk into him."""

    CONVERGE = auto()
    """Inside his inner abort from below: close the lane, keep closing X."""

    CORRIDOR_ABOVE = auto()
    """Hold 11-18 px above his lane (gate-proof, grab-ready) and close X."""

    CORRIDOR_BELOW = auto()
    """Hold past his gate and his claw's deep side below him, and close X."""

    ESCAPE_CLAW = auto()
    """A claw is live and the actor is in its band out of grab reach: leave."""


@dataclass(frozen=True, slots=True)
class EngagePlan:
    mode: EngageMode
    target_x: int
    target_y: int
    # The walk-in needs the walking box out every frame: X must be pressed
    # toward him even when the target is inside the executor's deadband.
    press_toward: bool
    # -1 left, +1 right: the only X direction this plan may ever press.
    toward: int


def _side_has_room(souther: Souther, *, above: bool, lane_lo: float, lane_hi: float) -> bool:
    if above:
        return souther.world_y - ABOVE_ROOM >= lane_lo
    return souther.world_y + BELOW_ROOM <= lane_hi


def corridor_side(
    actor: PlayableCharacter, souther: Souther, *, lane_lo: float, lane_hi: float
) -> bool:
    """True for the corridor above him, False for below.

    The side the actor is already on, while it has room: changing sides means
    crossing his lane, which is exactly the ground the corridor exists to keep
    out of. Level with him, above wins -- its gate is 10 px against 28 and its
    claw band 18 against 32 -- and when a side has no room the other one is
    all there is.
    """

    dy = lane_gap(actor, souther)
    above_ok = _side_has_room(souther, above=True, lane_lo=lane_lo, lane_hi=lane_hi)
    below_ok = _side_has_room(souther, above=False, lane_lo=lane_lo, lane_hi=lane_hi)
    if dy < -2 and above_ok:
        return True
    if dy > 2 and below_ok:
        return False
    if above_ok:
        return True
    return not below_ok


def plan_engage(
    actor: PlayableCharacter, souther: Souther, *, lane_lo: float, lane_hi: float
) -> EngagePlan:
    """Where the actor goes this tick to take a hold on Souther, and how.

    In order of precedence:

    - **walk in** once the actor is in the grab's lane and within
      ``WALK_IN_DX``: contact is the grab, and even a claw committed now leans
      his body into the actor's walking box before it can land;
    - **escape** a live claw the actor is inside the lane band of but cannot
      reach -- lane only, X held, and never by facing away from him;
    - **converge** from below once inside his inner abort;
    - otherwise the **corridor**: close X toward his pocket at a lane his
      commit gate cannot use.
    """

    side = side_of(actor, souther)
    toward = -side
    adx = abs(souther.world_x - actor.world_x)
    dy = lane_gap(actor, souther)
    walk_in_x = int(souther.world_x + side * WALK_IN_STOP_DX)
    pocket_x = int(souther.world_x + side * POCKET_STOP_DX)

    if in_grab_lane(dy) and adx < WALK_IN_DX:
        # Keep whatever lane the actor already has inside the grab band --
        # moving to his exact lane only crosses the 10 px gate above him for
        # nothing -- but pull a body at the band's edge a little further in.
        target_y = actor.world_y
        if abs(dy) > GRAB_LANE - 3:
            target_y = int(souther.world_y + (GRAB_LANE - 3) * (1 if dy > 0 else -1))
        return EngagePlan(EngageMode.WALK_IN, walk_in_x, target_y, True, toward)

    above = corridor_side(actor, souther, lane_lo=lane_lo, lane_hi=lane_hi)
    above_y = int(souther.world_y + ABOVE_AIM_DY)
    below_y = int(souther.world_y + BELOW_AIM_DY)

    if claw_is_live(souther):
        if in_claw_lane(dy, margin=4) and adx < CLAW_REACH_X + PLAYER_BODY_HALF_X + 8:
            escape_y = above_y - (CLAW_LANE_ABOVE + PLAYER_BODY_HALF_Y + 4 + ABOVE_AIM_DY)
            target_y = int(escape_y) if above else below_y
            return EngagePlan(EngageMode.ESCAPE_CLAW, actor.world_x, target_y, False, toward)

    if not above and adx < CONVERGE_DX:
        return EngagePlan(EngageMode.CONVERGE, walk_in_x, int(souther.world_y), False, toward)

    if above:
        return EngagePlan(EngageMode.CORRIDOR_ABOVE, pocket_x, above_y, False, toward)
    return EngagePlan(EngageMode.CORRIDOR_BELOW, pocket_x, below_y, False, toward)


class HoldStep(Enum):
    """The hold loop's next input -- see ``hold_step``."""

    KNEE = auto()
    RELEASE = auto()
    CROSS = auto()
    SUPLEX = auto()
    WAIT = auto()


def hold_step(actor: PlayableCharacter, souther: Souther) -> HoldStep:
    """Knee, knee, release -- and only ever finish when finishing kills.

    Front hold: two knees, then hand him back to the walk-in (the release),
    because the third B is ``$6E``'s knockback, which throws him 90 px down
    the actor's lane and makes the next hold a re-approach. The one exception
    is a knee that kills.

    Back hold (a grab taken from behind): the suplex only when it is lethal,
    since otherwise it leaves him 100 px away; else the one crossover this
    hold allows, back to the front and its knees -- or, with that crossover
    already spent, the release.
    """

    hp = signed_health(souther)
    base = actor.action_base
    if base == 0x66:
        if hp <= HOLD_SUPLEX_DAMAGE:
            return HoldStep.SUPLEX
        return HoldStep.RELEASE if actor.crossover_spent else HoldStep.CROSS
    if base == 0x60:
        knees = actor.knees_in_chain
        if knees < 2:
            return HoldStep.KNEE
        if hp <= HOLD_THIRD_KNEE_DAMAGE:
            return HoldStep.KNEE
        return HoldStep.RELEASE
    return HoldStep.WAIT


def release_press_frames(countdown: int) -> int:
    """How many frames of *back* drop the hold from this countdown value.

    ``loc_235A`` releases on the frame ``+$63`` goes negative, so from ``c``
    that is ``c + 1`` steps. A value outside 0..3 (``$FF`` right after a
    release) is treated as a fresh 3.
    """

    if not 0 <= countdown <= 3:
        countdown = 3
    return RELEASE_FRAMES_PER_COUNT * (countdown + 1)
