"""``generate_inference_tokens`` and its ``check_for_*`` derivation functions.

Every function here turns directly observed tokens into a *judgment*: a
token is added only when the judgment holds, never as a 1:1 mirror of an
observation (per ``AI.md``). The geometry they judge with lives in
``reach.py``, shared with ``decide.py``/``priority.py`` so all three stages
agree on one definition of every band.
"""

from __future__ import annotations

import math

from ..phases import CombatPhase, is_dangerous, is_punishable, should_ignore_as_target
from . import kinematics, reach
from .reach import SOUTHER_SLASH_DIST_MIN
from . import navigation as nav
from .pathfind import Point, PointGoal
from .tokens import Myself, Partner, PlayableCharacter
from .tokens import Antonio, Enemy, Grunt, Jack, Souther
from .tokens import GrabEnemy, JumpAttack, Punch, RearAttack
from .tokens import (
    AntonioIsGoingToKick,
    ClosingEnemy,
    GrabOpportunity,
    GrabReason,
    IncomingMelee,
    PunishWindow,
    ReachKind,
    SoutherIsGoingToSlash,
    SoutherPunishesJump,
    Surrounded,
    TargetInReach,
)
from .tokens import CameraRange, Pit, SafeSpot
from .tokens import IncomingProjectile, Projectile
from .tokens import Weapon, WeaponUpgrade, weapon_rank
from .tokens import Context, Token, find, find_all
from .tokens import rear_attack_behind_max_x, rear_attack_front_max_x

# Projectiles outside this time-to-impact window are not "incoming" yet.
PROJECTILE_THREAT_TICKS = 30
PROJECTILE_LANE_SLACK = 24
CAUTION_RANGE_X = 40

# object_catalog.py's Jack axe/torch helper. Unlike every other projectile
# family, this object exists while still tethered to Jack's own juggle
# animation, not only once thrown -- so its momentary spin velocity can
# point straight at the actor and satisfy _projectile_threatens without a
# real throw ever happening.
JACK_PROJECTILE_TYPE_ID = 0x28

# The juggled axe/torch stays within this radius of Jack himself; once
# thrown it opens that gap on the very next tick. Generous enough to cover
# the juggle's own spin without needing exact ROM offsets.
JACK_JUGGLE_ATTACH_RADIUS = 40

# Antonio's linked boomerang (object_catalog.py type $96). Same attach
# problem as Jack's axe: the object exists while still in his hand, and
# punching it then is just standing still in front of him.
ANTONIO_BOOMERANG_TYPE_ID = 0x96
ANTONIO_BOOMERANG_ATTACH_RADIUS = 40

# Kick gate at $16EAE (enemy-ai.md "Body state machine"): X thresholds
# selected by the target's +$1C velocity relative to Antonio's facing, and
# a lane window of $10 (or $08 when +$61 is set -- we use the looser $10
# so we never miss a kick). Distances are the ROM's own +$50/+ $52 words.
#
# After the ROM signs velocity into Antonio's facing frame (`neg` if he
# faces left), `bmi` (moving *against* his facing, i.e. toward him) uses
# $78; the non-negative / backing-away path uses $50. Standing still is
# its own path at $50 or $68 -- we take the wider $68 so a kick is never
# missed.
ANTONIO_KICK_DIST_STATIONARY = 0x68  # 104px
ANTONIO_KICK_DIST_CLOSING = 0x78  # 120px; target walking into him
ANTONIO_KICK_DIST_AWAY = 0x50  # 80px; target walking off
ANTONIO_KICK_LANE = 0x10  # 16px
# Dash/throw commit at $16E74: X in [$28, $78) and lane < $14. This is
# the opening hit of the fight -- he dashes as soon as the actor walks
# into that window. The token covers it too: a sidestep cannot leave a
# lane he tracks, so the same hop is the answer.
ANTONIO_DASH_DIST_MIN = 0x28  # 40px
ANTONIO_DASH_DIST_MAX = 0x78  # 120px
ANTONIO_DASH_LANE = 0x14  # 20px
# High-word of a 16.16 velocity is "zero" for the ROM's `tst.w $1C`. A
# couple of tenths of a pixel of walk jitter must not flip the path.
ANTONIO_STATIONARY_VEL = 0.5
# Primary $02 is the committed kick ($171CC).
ANTONIO_KICK_PRIMARY_STATE = 0x02

# Souther's linked claw/afterimage (object_catalog.py types $98/$99, created by
# $16C2E (souther_create_claw) / $16BC6 (souther_create_afterimage)). These are
# animation-synchronized attack objects that live and die with the claw
# sequence, never thrown -- so unlike Antonio's $96 they are withheld from
# IncomingProjectile *unconditionally* rather than only while attached. The
# claw is answered by DodgeSoutherSlash, which reads Souther's own state; a
# ProjectileSidestep competing with it would just split the tick.
SOUTHER_CLAW_TYPE_IDS = frozenset({0x98, 0x99})

# Souther's state 1 -> state 2 commit gate at $15EDA
# (souther_state1_active_combat). Same shape as Antonio's $16EAE kick gate: the
# X window is picked by the sign of the *target's* +$1C velocity after the ROM
# signs it into Souther's own facing frame (`neg` when +$60 is nonzero), so
# `bmi` -- walking into him -- gets the widest window.
SOUTHER_SLASH_DIST_CLOSING = 0x68  # 104px; target walking into him
SOUTHER_SLASH_DIST_STATIONARY = 0x58  # 88px
SOUTHER_SLASH_DIST_AWAY = 0x50  # 80px; target walking off
# The inner abort itself -- reach.SOUTHER_SLASH_DIST_MIN -- lives in reach.py,
# shared with execute.py's own use of the same pocket; re-imported by name
# here so existing call sites and tests keep reading it as
# ``SOUTHER_SLASH_DIST_MIN``.
# Lane gate: $0A when +$61 is set, else $1C. We take the wider $1C for the same
# reason the Antonio constants above take their wider pair -- never miss a
# strike by under-stating the box.
SOUTHER_SLASH_LANE = 0x1C  # 28px
# Primary $02 is the whole committed claw ($16118 souther_state2_claw_commit).
SOUTHER_SLASH_PRIMARY_STATE = 0x02

# The X reach of "do not jump near Souther". $16234
# (souther_counter_jump_attack) is where the number comes from: $162A4
# (souther_flag_target_jump_attack) arms +$79 from the *player's* own action
# state ($16/$17/$42/$43 -- the unarmed and armed jump-attack pairs), and
# $16234 then forces Souther straight to primary $02 with the claw spawned,
# bypassing every distance band, the inner abort and the +$66/+$77 gates.
SOUTHER_JUMP_COUNTER_DIST_X = 0x78  # 120px
# Two gates the ROM has here are deliberately **not** reproduced, both
# live-diagnosed after the AI was seen jumping straight into the claws:
#
# * $16234's own lane window ($12, 18px). The jump is horizontal, so the
#   *flight* cannot leave the lane it started on -- but Souther closes lane at
#   4px/frame ($15F98/$160D0), which erases an 18px gap in about five frames,
#   well inside the flight's own ~25. Gating on lane let the AI launch from
#   just off-lane and get counter-hit anyway.
#
# * "is the counter armed" ($15EDA and $16158 call $16234; $1619E/$161C6 do
#   not). Reading that as "then a jump is safe there" was the actual error:
#   the reason the dash handlers skip the counter is that he is *already
#   attacking*, with the type-$98 claw live and carrying hitbox/damage
#   descriptor $225C. Not being countered is not the same as not being hit,
#   and that window is the most dangerous one, not the safe one.
#
# What is genuinely safe is a Souther who cannot act at all, which
# is_punishable already names -- and there the grab outranks the hop anyway.

# The committed dash at $161C6 (souther_state2_claw_dash): +$1C = $00080000,
# i.e. 8px per 60Hz frame, and it resolves only with the target inside $18
# (24px) of its lane. Used by _souther_dash_arrives_soon, which exists because
# a Boss populates neither attack_ranges nor grunt_vel_*, so both of
# check_for_incoming_melee's ordinary tests report "no threat" while he closes
# faster than any grunt.
SOUTHER_DASH_SPEED_X = 8.0
SOUTHER_DASH_RESOLVE_LANE = 0x18  # 24px

# The shared later-boss hit reaction. $03 and $04 both decode as RECOVERY
# (phases.py), but they are not the same situation: measured live over a full
# Souther fight, $03 held 4% of ticks and $04 held 70%. $04 is where he sits,
# so keying the punish grab on is_punishable handed the top of the emergency
# table to a walk-in that never converted, for most of the fight.
SOUTHER_HIT_REACTION_PRIMARY = 0x03

# A Grunt outside this time-to-arrival window is not "closing fast" yet.
# The horizon itself now lives in reach.CLOSING_ENEMY_THREAT_FRAMES --
# shared with check_for_incoming_melee's predictive extension below, so
# "soon" means the same thing to both -- but the rear-band lane slack is
# specific to this check's own band test and stays local.
CLOSING_ENEMY_LANE_SLACK = 24

# A crowd, rather than a queue: this many live enemies inside the close box
# around the actor (or any pincer -- at least one on each side) is what makes
# it "surrounded". Two enemies arriving from the same side are an ordinary
# fight; the box is the same one RearAttack uses to decide it is boxed in.
SURROUNDED_MIN_ENEMIES = 3

# Candidate step sizes when looking for a SafeSpot. X matches
# execute.RETREAT_FROM_DANGER_DISTANCE (one retreat tick's worth of travel);
# the lane step clears PUNCH_RANGE_Y so a sidestep actually leaves the
# attacker's line rather than shuffling inside it.
SAFE_SPOT_STEP_X = 32
SAFE_SPOT_STEP_Y = 24

# See _safe_spot_candidates' docstring: a couple of px of jitter around
# dx == 0 between the actor and its threat should not flip which way "away"
# points. Same magnitude as execute.DIRECTION_HYSTERESIS_X, kept as its own
# constant since inference.py must not import execute.py.
SAFE_SPOT_SIDE_HYSTERESIS_X = 10

# Minimum clearance improvement a sidestep/diagonal candidate must offer
# over the plain X-away retreat (the first candidate _safe_spot_candidates
# returns) before check_for_safe_spots prefers it. Without this, two
# candidates scoring within a couple of px of each other on ordinary
# position jitter flipped which one won every tick -- and since the
# candidates differ in whether they add a Y step at all, that flip read live
# as the actor darting into a vertical/diagonal dash instead of holding a
# steady retreat line. Comfortably above the noise one tick of movement can
# introduce, well below the real clearance gap a genuinely better sidestep
# provides.
SAFE_SPOT_PREFERENCE_MARGIN = 12


def _actors(context: Context) -> list[PlayableCharacter]:
    return [actor for actor in (find(context, Myself), find(context, Partner)) if actor is not None]


def _projectile_threatens(projectile: Projectile, actor: PlayableCharacter) -> bool:
    """True when the projectile is heading toward the actor in-lane soon.

    Stage-hazard projectiles with zero X velocity (e.g. a vertical press) are
    treated as threats when already overlapping the actor's X column.
    """

    if abs(projectile.world_y - actor.world_y) > PROJECTILE_LANE_SLACK:
        return False

    dx = projectile.world_x - actor.world_x
    if projectile.vel_x == 0:
        # Stationary/vertical hazard: only if already on or past the actor's X.
        return abs(dx) <= CAUTION_RANGE_X

    heading_toward = (dx > 0 and projectile.vel_x < 0) or (dx < 0 and projectile.vel_x > 0)
    if not heading_toward:
        return False
    ticks = abs(dx) / abs(projectile.vel_x)
    return ticks <= PROJECTILE_THREAT_TICKS


def _antonio_still_holding_boomerang(projectile: Projectile, context: Context) -> bool:
    """True when this is Antonio's boomerang and it is still in his hand.

    Type ``$96`` exists for the whole wind-up/catch, not only once thrown
    (object_catalog.py). Punching or sidestepping it then is standing still
    in front of Antonio -- the kick trigger. Matched to a live ``Antonio``
    within ``ANTONIO_BOOMERANG_ATTACH_RADIUS``, the same attach test Jack's
    axe uses.
    """

    if projectile.type_id != ANTONIO_BOOMERANG_TYPE_ID:
        return False
    for antonio in find_all(context, Antonio):
        if (
            abs(projectile.world_x - antonio.world_x) <= ANTONIO_BOOMERANG_ATTACH_RADIUS
            and abs(projectile.world_y - antonio.world_y) <= ANTONIO_BOOMERANG_ATTACH_RADIUS
        ):
            # Still on him unless it already has a real independent throw
            # velocity. A follow-along attached object tracks him at his
            # own walk speed, well under a thrown boomerang.
            if abs(projectile.vel_x) < 2.0:
                return True
    return False


def _is_souther_claw(projectile: Projectile) -> bool:
    """True for Souther's linked claw/afterimage objects (types ``$98``/``$99``).

    Withheld from ``IncomingProjectile`` for the whole of their existence, not
    just while attached: enemy-ai.md describes them as animation-synchronized
    attack/afterimage objects, and ``$161C6 (souther_state2_claw_dash)``
    re-creates the afterimage every dash tick from Souther's own position. They
    have no independent flight to intercept, so the only honest answer is
    Souther's own state, which ``DodgeSoutherSlash`` reads.
    """

    return projectile.type_id in SOUTHER_CLAW_TYPE_IDS


def _jack_still_juggling(projectile: Projectile, context: Context) -> bool:
    """True when this is Jack's axe/torch and he has not released it yet.

    The weapon spins tethered to him for the whole juggle, so its
    instantaneous velocity can momentarily point straight at the actor and
    read exactly like an incoming throw. Matched to whichever live,
    still-juggling (``has_projectile``) Jack sits within
    ``JACK_JUGGLE_ATTACH_RADIUS`` of it, since the object carries no
    explicit owner slot.
    """

    if projectile.type_id != JACK_PROJECTILE_TYPE_ID:
        return False
    for jack in find_all(context, Jack):
        if not jack.has_projectile:
            continue
        if (
            abs(projectile.world_x - jack.world_x) <= JACK_JUGGLE_ATTACH_RADIUS
            and abs(projectile.world_y - jack.world_y) <= JACK_JUGGLE_ATTACH_RADIUS
        ):
            return True
    return False


def check_for_incoming_projectiles(context: Context) -> Context:
    """Promote only projectiles that threaten at least one playable character.

    Per ``AI.md``, ``IncomingProjectile`` is a threat judgment, not a 1:1 copy
    of every observed ``Projectile``. Jack's axe/torch is additionally held
    back while he is still juggling it (``_jack_still_juggling``) -- only a
    released throw is a real threat.
    """

    actors = _actors(context)
    if not actors:
        return set()

    incoming: set[Token] = set()
    for projectile in find_all(context, Projectile):
        if _jack_still_juggling(projectile, context):
            continue
        if _antonio_still_holding_boomerang(projectile, context):
            continue
        if _is_souther_claw(projectile):
            continue
        if any(_projectile_threatens(projectile, actor) for actor in actors):
            incoming.add(
                IncomingProjectile(
                    slot=projectile.slot,
                    world_x=projectile.world_x,
                    world_y=projectile.world_y,
                    vel_x=projectile.vel_x,
                    vel_z=projectile.vel_z,
                )
            )
    return incoming


def _closing_enemy_threatens(enemy: Grunt, actor: PlayableCharacter) -> bool:
    """True when the enemy is heading toward the actor's rear-attack band on
    X and is still off-lane enough that it is not obviously stationary,
    landing inside that band within ``reach.CLOSING_ENEMY_THREAT_FRAMES``.

    Must pick the *side-specific* band (behind vs front), not their union:
    Axel/Blaze have zero forward RearAttack reach, so an enemy closing in
    from the front must never be promoted for them, even though they do
    have a real behind band.
    """

    if abs(enemy.world_y - actor.world_y) > CLOSING_ENEMY_LANE_SLACK:
        return False

    dx = enemy.world_x - actor.world_x
    vx = enemy.grunt_vel_x
    if vx == 0:
        return False

    heading_toward = (dx > 0 and vx < 0) or (dx < 0 and vx > 0)
    if not heading_toward:
        return False

    behind = reach.enemy_behind_actor(actor, enemy)
    max_x = (
        rear_attack_behind_max_x(actor.character_id)
        if behind
        else rear_attack_front_max_x(actor.character_id)
    )
    if max_x <= 0:
        # No reach at all on this side (e.g. Axel/Blaze from the front).
        return False
    if abs(dx) <= max_x:
        # Already inside the band -- reach.in_rear_band already covers this
        # tick without needing the early-warning signal.
        return False

    # vx is px per 60 Hz frame (the ROM's own +$1C, integrated once a frame),
    # so this quotient is a frame count and belongs against a frame horizon.
    frames = (abs(dx) - max_x) / abs(vx)
    return frames <= reach.CLOSING_ENEMY_THREAT_FRAMES


def check_for_closing_enemies(context: Context) -> Context:
    """Promote Grunt enemies about to close into rear-attack range soon.

    Per ``AI.md``, this is a threat judgment, not a 1:1 copy of every
    observed ``Grunt`` -- see the module docstring on ``ClosingEnemy`` for
    why the AI needs this early-warning signal at all: the band checks in
    ``reach.py`` are purely instantaneous-position, so a fast diagonal
    closer can arrive between two polls with no warning otherwise.
    """

    actors = _actors(context)
    if not actors:
        return set()

    closing: set[Token] = set()
    for enemy in find_all(context, Grunt):
        if should_ignore_as_target(enemy.combat_phase):
            continue
        if any(_closing_enemy_threatens(enemy, actor) for actor in actors):
            closing.add(ClosingEnemy(slot=enemy.slot))
    return closing


def _connects(band, actor: PlayableCharacter, enemy: Enemy, frames) -> bool:
    """True when ``band`` holds at any frame of this move's own timeline.

    A move is not an instant -- a punch damages for 10 frames, Adam's chord
    for 18 -- so the target only has to be inside the box at *one* of the
    frames ``kinematics.connect_frames`` names, and frame 0 (the observed
    position) is always one of them. That last part is what keeps the
    prediction additive: it can offer an attack the raw position does not,
    and can never take away one it does.
    """

    return any(
        band(actor, kinematics.enemy_projected_without_crossing(actor, enemy, frame))
        for frame in frames
    )


def check_for_targets_in_reach(context: Context) -> Context:
    """Derive the per-move reach bands once per (actor, live enemy) pair.

    Computing these here instead of inside each ``could_*`` is what lets
    ``decide.py`` and ``priority.py`` ask the same question and get the same
    answer within a tick, and stops the same trigonometry from being redone
    once per verb family.

    Each band is tested across its own move's timeline rather than only at
    the instant the snapshot was taken (``kinematics.connect_frames``), so an
    enemy walking *into* range arms the move as it arrives instead of after,
    and a long move -- Adam's 21-frame chord above all -- is judged over the
    span it is actually dangerous for. A stationary enemy projects to itself,
    so nothing changes at all for a stunned, knocked-down or committed
    target.

    ``ReachKind.ACTIONABLE`` is deliberately left on the observed position.
    It is not a "would this hit" question but the "stop walking, you can
    already hit it" signal ``could_walk_to_near_enemy`` reads, and answering
    it about the future stops the approach early -- the actor stands off and
    swings at where the enemy is going to be instead of closing the last few
    pixels.
    """

    enemies = reach.live_enemies(context)
    if not enemies:
        return set()

    tokens: set[Token] = set()
    for actor in _actors(context):
        for enemy in enemies:
            pair = {"actor_slot": actor.slot, "target_slot": enemy.slot}
            if _connects(
                reach.punch_would_connect,
                actor,
                enemy,
                kinematics.connect_frames(Punch, actor, enemy),
            ):
                tokens.add(TargetInReach(**pair, kind=ReachKind.PUNCH))
            if _connects(
                reach.in_rear_band,
                actor,
                enemy,
                kinematics.connect_frames(RearAttack, actor, enemy),
            ):
                tokens.add(TargetInReach(**pair, kind=ReachKind.REAR))
            if _connects(
                reach.in_jump_attack_band,
                actor,
                enemy,
                kinematics.connect_frames(JumpAttack, actor, enemy),
            ):
                tokens.add(TargetInReach(**pair, kind=ReachKind.JUMP_ATTACK))
            if _connects(
                reach.grab_would_connect,
                actor,
                enemy,
                kinematics.connect_frames(GrabEnemy, actor, enemy),
            ):
                tokens.add(TargetInReach(**pair, kind=ReachKind.GRAB))
            if reach.enemy_actionable(actor, enemy, enemies):
                tokens.add(TargetInReach(**pair, kind=ReachKind.ACTIONABLE))
    return tokens


def check_for_incoming_melee(context: Context) -> Context:
    """Promote committed enemies close enough for their attack to land --
    *or* about to be, on their own current velocity.

    The melee counterpart of ``check_for_incoming_projectiles``: a dangerous
    phase alone is not a threat (an enemy swinging at nothing three lanes
    away is not), and neither is proximity alone. Only on-screen enemies
    qualify -- an off-screen one cannot connect this tick.

    ``reach.too_close_to_keep_approaching`` alone only sees the enemy's
    *current* position, which misses a committed fast mover: Signal's slide
    is the ROM-confirmed case (enemy-ai.md "Signal's slide is velocity, not
    a hitbox") -- state $0A sets +$1C/+$20 directly (~2.5 px/frame toward the
    target) with no attack shape anywhere in its animation set, so
    ``Enemy.attack_ranges`` is empty for it and there is nothing for a
    static reach check to find. ``reach.enemy_will_close_soon`` re-tests the
    same caution predicate ``reach.CLOSING_ENEMY_THREAT_FRAMES`` frames ahead,
    so a dangerous-phase enemy already closing distance promotes
    ``IncomingMelee`` before it arrives, not only once it has -- which is
    what lets ``could_retreat_from_danger`` (decide.py) react in time instead
    of only after the hit is already unavoidable. A stationary enemy
    projects to itself, so this never promotes anything the current-position
    test would not already have caught.
    """

    enemies = reach.on_screen_enemies(context)
    if not enemies:
        return set()

    tokens: set[Token] = set()
    for actor in _actors(context):
        for enemy in enemies:
            if not is_dangerous(enemy.combat_phase):
                continue
            imminent = (
                reach.too_close_to_keep_approaching(actor, enemy)
                or reach.enemy_will_close_soon(actor, enemy)
                or _souther_dash_arrives_soon(actor, enemy)
            )
            if not imminent:
                continue
            tokens.add(IncomingMelee(actor_slot=actor.slot, target_slot=enemy.slot))
    return tokens


def _souther_dash_arrives_soon(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """Souther's committed claw dash, which neither test above can see.

    Both of them are blind to it, for the same underlying reason: a ``Boss``
    populates neither ``attack_ranges`` (so
    ``too_close_to_keep_approaching`` falls back to a caution box built from
    the *actor's* punch reach, ~46px) nor ``grunt_vel_x``/``grunt_vel_y`` (so
    ``enemy_will_close_soon`` projects him to standing still). The dash at
    ``$161C6 (souther_state2_claw_dash)`` closes at ``$00080000`` -- 8px per
    60Hz frame, faster than any character walks -- so from 90px he arrives in
    about eleven frames while both checks report no threat at all.

    Lane is part of the test rather than slack around it: the dash writes only
    ``+$1C`` and resolves only with the target inside ``$18`` of its lane, so
    an actor already off that lane is genuinely not about to be hit -- which is
    exactly what ``DodgeSoutherSlash`` is spending the tick achieving.
    """

    if not isinstance(enemy, Souther) or not enemy.strike_is_committed():
        return False
    if abs(enemy.world_y - actor.world_y) >= SOUTHER_DASH_RESOLVE_LANE:
        return False
    travel = SOUTHER_DASH_SPEED_X * reach.CLOSING_ENEMY_THREAT_FRAMES
    return abs(enemy.world_x - actor.world_x) <= travel


# Enemy phases a hold can actually be taken on. Deliberately not
# ``is_punishable``: that set includes KNOCKDOWN (a body on the floor, which
# the contact test cannot hold) and GRABBED (already held). ATTACKING/CHARGE
# are excluded for the opposite reason -- walking into a committed enemy is
# how the actor takes the hit instead of the hold. What is left is an enemy
# standing on its feet and able to be walked into: free to act, frozen on a
# timed stun, stuck on geometry, or in the tail of its own move.
GRABBABLE_PHASES = frozenset(
    {
        CombatPhase.NORMAL,
        CombatPhase.STUNNED,
        CombatPhase.BLOCKED,
        CombatPhase.RECOVERY,
    }
)


def check_for_grab_opportunities(context: Context) -> Context:
    """Judge, per (actor, enemy) pair, whether a hold beats a strike.

    Not "every enemy that could be grabbed": a grab costs the actor its
    attack for the walk-in and locks both bodies together, so this only
    fires for the situations where that trade pays off -- see ``GrabReason``.
    Whether the grab is *reachable* is a separate question, answered by
    ``TargetInReach`` (``ReachKind.GRAB``) above; ``decide.could_grab_enemy``
    requires both.

    Most opportunities are ``Grunt``-only. Antonio and Souther are the
    exceptions: after a landed hit both sit in the shared later-boss
    ``RECOVERY`` states (primary ``$03``/``$04``), and a hold-then-suplex beats
    following up with another strike -- for Antonio because the combo is his own
    kick trigger, for Souther because ``$15EDA
    (souther_state1_active_combat)`` cannot re-arm the claw from recovery, so
    the walk-in is free. Bongo, the twins, Abadede and Mr. X stay out of scope.

    Reads the ``Surrounded`` tokens ``check_for_surrounded`` produced earlier
    in ``generate_inference_tokens``' chain -- see ``GrabReason.
    WHILE_SURROUNDED``, the one reason here that is about the actor's whole
    situation rather than about the candidate enemy itself.
    """

    enemies = reach.on_screen_enemies(context)
    if not enemies:
        return set()

    grabbable = [enemy for enemy in enemies if enemy.combat_phase in GRABBABLE_PHASES]
    if not grabbable:
        return set()

    surrounded_actors = {token.actor_slot for token in find_all(context, Surrounded)}

    tokens: set[Token] = set()
    for actor in _actors(context):
        rear = reach.rear_threats(actor, enemies)
        # Committed enemies already judged able to land on this actor. A
        # charge coming in from behind the body being grabbed is what
        # GrabReason.DODGE_CHARGE answers -- Signal's hitbox-less slide above all.
        charging = [
            enemy
            for enemy in enemies
            if any(
                token.actor_slot == actor.slot and token.target_slot == enemy.slot
                for token in find_all(context, IncomingMelee)
            )
        ]
        for enemy in grabbable:
            pair = {"actor_slot": actor.slot, "target_slot": enemy.slot}
            if isinstance(enemy, Antonio):
                if is_punishable(enemy.combat_phase):
                    tokens.add(GrabOpportunity(**pair, reason=GrabReason.ANTONIO_ON_PUNISH))
                continue
            if isinstance(enemy, Souther):
                # Only the *brief* hit reaction, primary $03 -- deliberately
                # not the whole of is_punishable the way Antonio's is.
                #
                # Measured live over a full 120s Souther fight: he sits in
                # primary $04 for 70% of it (2304 of 3304 ticks) against 4% in
                # $03, and both decode as RECOVERY. Keyed on is_punishable, the
                # grab therefore scored 61+14 = 75 -- the top of the table --
                # for most of the fight, and the walk-in never converted: 2318
                # ticks of GrabEnemy, and Souther lost 11 health in two
                # minutes while the actor lost a whole life. $04 is where he
                # *sits*, not a window.
                if enemy.primary_state == SOUTHER_HIT_REACTION_PRIMARY:
                    tokens.add(GrabOpportunity(**pair, reason=GrabReason.SOUTHER_ON_PUNISH))
                continue
            if not isinstance(enemy, Grunt):
                continue
            candidate_dx = enemy.world_x - actor.world_x
            if any(
                other.slot != enemy.slot
                # Same side of the actor, and further out than the body being
                # grabbed: the charge is coming in *through* it.
                and (other.world_x - actor.world_x) * candidate_dx > 0
                and abs(other.world_x - actor.world_x) > abs(candidate_dx)
                for other in charging
            ):
                tokens.add(GrabOpportunity(**pair, reason=GrabReason.DODGE_CHARGE))
            if actor.slot in surrounded_actors:
                # Boxed in: a body in the hands beats a strike whichever side
                # the crowd is on. CLEAR_REAR below only covers the subset
                # with a *confirmed rear* enemy.
                tokens.add(GrabOpportunity(**pair, reason=GrabReason.WHILE_SURROUNDED))
            # A rear threat that *is* the candidate is not a pincer -- the
            # actor would be walking backwards into the same enemy it is
            # already worried about, and reach.grab_would_connect (forward
            # only) would not have offered it anyway.
            if any(other.slot != enemy.slot for other in rear):
                tokens.add(GrabOpportunity(**pair, reason=GrabReason.CLEAR_REAR))
            if isinstance(enemy, Jack) and reach.enemy_forward_dx(enemy, actor) < 0:
                # Facing away: the hold lands before the axe or the lunge
                # can turn around. The opposite geometry -- Jack at the
                # actor's back -- is RearAttack, not a backwards walk-in.
                tokens.add(GrabOpportunity(**pair, reason=GrabReason.JACK_FROM_BEHIND))
            if enemy.min_reach > 0:
                # Every attack it owns starts further out than contact --
                # read from the ROM shape its animations select, not from
                # the enemy's type. See GrabReason.DEAD_ZONE.
                tokens.add(GrabOpportunity(**pair, reason=GrabReason.DEAD_ZONE))
    return tokens


def _punish_frames_left(enemy: Enemy) -> int:
    """The ROM's own countdown for this punish window, when it has one.

    Only a stunned ``Grunt`` exposes one (``+$50``, seeded with $18 for
    hitstun and $A0 for the pepper-spray immobilization). Knockdown, block
    and grab windows end on collision/animation events instead, so they
    report 0 -- "no readable timer", not "about to end".
    """

    if isinstance(enemy, Grunt) and enemy.combat_phase is CombatPhase.STUNNED:
        return enemy.stun_timer
    return 0


def check_for_punish_windows(context: Context) -> Context:
    """Promote every live enemy that currently cannot defend itself."""

    tokens: set[Token] = set()
    for enemy in reach.live_enemies(context):
        if not is_punishable(enemy.combat_phase):
            continue
        tokens.add(
            PunishWindow(target_slot=enemy.slot, frames_left=_punish_frames_left(enemy))
        )
    return tokens


def check_for_surrounded(context: Context) -> Context:
    """Judge whether an actor is boxed in rather than facing a queue.

    Judged with ``reach.SURROUNDED_NEAR_X``/``_Y`` -- the "part of this fight"
    box -- **not** the tighter ``REAR_THREAT_X``/``_Y`` this used to share
    with ``reach.rear_attack_is_warranted``. The two questions are different:
    the chord's box asks "can that enemy hit me while I turn", which is a
    hitting distance, while encirclement asks "are these enemies all in this
    exchange with me". Sharing the tighter one made the judgment collapse
    after a dozen pixels of the actor's own walking -- see that constant.
    """

    enemies = reach.on_screen_enemies(context)
    if not enemies:
        return set()

    tokens: set[Token] = set()
    for actor in _actors(context):
        near = [
            enemy
            for enemy in enemies
            if abs(enemy.world_x - actor.world_x) <= reach.SURROUNDED_NEAR_X
            and abs(enemy.world_y - actor.world_y) <= reach.SURROUNDED_NEAR_Y
        ]
        behind = sum(1 for enemy in near if reach.enemy_behind_actor(actor, enemy))
        in_front = len(near) - behind
        pincered = behind >= 1 and in_front >= 1
        if len(near) < SURROUNDED_MIN_ENEMIES and not pincered:
            continue
        tokens.add(Surrounded(actor_slot=actor.slot, in_front=in_front, behind=behind))
    return tokens


def _inside_pit(context: Context, world_x: int, world_y: int) -> bool:
    return any(reach.pit_endangers(pit, world_x, world_y) for pit in find_all(context, Pit))


def _safe_spot_candidates(
    actor: PlayableCharacter, threat: Enemy
) -> list[tuple[int, int]]:
    """Steps worth considering: away on X, and the two sidesteps, alone or
    combined with the retreat. Standing still is not a candidate -- this
    token only exists to answer "back off to *where*".

    Within ``SAFE_SPOT_SIDE_HYSTERESIS_X`` of the threat, which way is
    "away" is read off ``actor.facing_left`` instead of the raw compare
    (same convention as ``execute._back_direction_mask``: right when facing
    left) -- an actor already backed into caution range sits close enough to
    its threat that a couple of px of jitter would otherwise flip every
    candidate here, including the sidesteps, to the opposite side on
    consecutive ticks.
    """

    dx = threat.world_x - actor.world_x
    if abs(dx) <= SAFE_SPOT_SIDE_HYSTERESIS_X:
        away = SAFE_SPOT_STEP_X if actor.facing_left else -SAFE_SPOT_STEP_X
    else:
        away = -SAFE_SPOT_STEP_X if dx >= 0 else SAFE_SPOT_STEP_X
    return [
        (actor.world_x + away, actor.world_y),
        (actor.world_x + away, actor.world_y + SAFE_SPOT_STEP_Y),
        (actor.world_x + away, actor.world_y - SAFE_SPOT_STEP_Y),
        (actor.world_x, actor.world_y + SAFE_SPOT_STEP_Y),
        (actor.world_x, actor.world_y - SAFE_SPOT_STEP_Y),
    ]


def check_for_safe_spots(context: Context) -> Context:
    """Pick where to back off to, for each actor with an ``IncomingMelee``.

    Runs after ``check_for_incoming_melee`` (``generate_inference_tokens``
    threads the context through in order) because a safe spot is only
    meaningful relative to a threat worth leaving.
    """

    threats = find_all(context, IncomingMelee)
    if not threats:
        return set()

    camera = find(context, CameraRange)
    enemies = reach.live_enemies(context)

    tokens: set[Token] = set()
    for actor in _actors(context):
        threatening = [
            enemy
            for enemy in enemies
            for threat in threats
            if threat.actor_slot == actor.slot and threat.target_slot == enemy.slot
        ]
        if not threatening:
            continue
        nearest = min(
            threatening,
            key=lambda e: math.hypot(e.world_x - actor.world_x, e.world_y - actor.world_y),
        )

        # Obstacle sets for the reachability gate below, built once per actor
        # rather than per candidate (they do not depend on which candidate is
        # being judged). The threatening enemies themselves are excluded from
        # the danger set -- the actor is fleeing *because* it is already
        # right next to them, so their own reach necessarily covers the
        # ground between the actor and every candidate by construction (the
        # same reasoning execute._walk_to_near_enemy's ``alongside`` exemption
        # documents for the opposite verb: a nearby enemy currently owns the
        # patch of ground the actor stands on). Counting it as danger would
        # not steer around a *different* threat, it would just make every
        # candidate near the actor read as unreachable and disable this gate
        # entirely. Other, unrelated enemies' danger zones -- and every
        # breakable/pit -- are still real obstacles: escaping past the thing
        # chasing you does not excuse walking through a second enemy's swing
        # or a crate on the way.
        threat_slots = frozenset(enemy.slot for enemy in threatening)
        body, origin = nav.actor_footprint(actor)
        solids, dangers = nav.obstacle_sets(
            context,
            body=body,
            origin=origin,
            ignore_enemy_slots=threat_slots,
        )

        # index 0 (the plain X-away retreat) is the stability anchor: every
        # other candidate must clear it by SAFE_SPOT_PREFERENCE_MARGIN to
        # win, so a near-tie keeps resolving to the same simple retreat
        # instead of flipping to a sidestep on ordinary jitter (see that
        # constant's comment).
        best: tuple[float, tuple[int, int]] | None = None
        anchor_clearance: float | None = None
        for index, (candidate_x, candidate_y) in enumerate(_safe_spot_candidates(actor, nearest)):
            if not reach.in_playable_lane(candidate_y, context):
                continue
            if camera is not None and not reach.in_camera(camera, candidate_x, candidate_y):
                continue
            if _inside_pit(context, candidate_x, candidate_y):
                continue
            # The candidate itself is clear, but the straight-line route to
            # it might not be -- a crate, a pit, or an unrelated enemy's
            # reach can sit between the actor and an otherwise fine spot.
            # nav.plan_route already tries a danger-free route first and
            # falls back to solids-only when no such route exists (a busy
            # screen should not make every retreat "unreachable"), so this
            # reuses that same policy rather than reinventing it.
            path = nav.plan_route(
                context,
                actor,
                PointGoal(Point(candidate_x, candidate_y)),
                solids=solids,
                dangers=dangers,
            )
            if not path.reached:
                continue
            clearance = min(
                math.hypot(enemy.world_x - candidate_x, enemy.world_y - candidate_y)
                for enemy in enemies
            )
            if index == 0:
                anchor_clearance = clearance
                score = clearance
            elif anchor_clearance is None:
                score = clearance
            else:
                score = clearance - SAFE_SPOT_PREFERENCE_MARGIN
            if best is None or score > best[0]:
                best = (score, (candidate_x, candidate_y))
        if best is None:
            continue
        tokens.add(
            SafeSpot(actor_slot=actor.slot, world_x=best[1][0], world_y=best[1][1])
        )
    return tokens


def _antonio_kick_distance_threshold(
    antonio: Antonio, actor: PlayableCharacter
) -> int:
    """The ROM's X window for the 1→2 kick, given how the actor is moving.

    ``$16EAE`` reads the target's ``+$1C`` high word. Zero is the
    standing-still path (thresholds ``$50``/``$68`` selected by facing and
    ``+$31`` bit 1 -- we take the wider ``$68`` so a kick is never
    missed). Non-zero is signed relative to Antonio's facing ``+$60``:
    negative (moving *against* his facing, i.e. approaching him -- the
    ROM's ``bmi`` path) uses ``$78``, non-negative (backing away) uses
    ``$50``. Same reading as ``ANTONIO_KICK_DIST_CLOSING``/``_AWAY``'s own
    comments above, which is what this function returns.
    """

    vel = actor.vel_x
    if abs(vel) < ANTONIO_STATIONARY_VEL:
        return ANTONIO_KICK_DIST_STATIONARY
    # Sign into Antonio's facing frame the way $16EB4 does: negate if he
    # faces left, then `bmi` is "moving against his facing" = toward him.
    relative = -vel if antonio.facing_left else vel
    if relative < 0:
        return ANTONIO_KICK_DIST_CLOSING
    return ANTONIO_KICK_DIST_AWAY


def _antonio_will_kick(antonio: Antonio, actor: PlayableCharacter) -> bool:
    """True when Antonio's kick gate is already satisfied, or the kick is on.

    Already-committed (primary ``$02`` / ``CombatPhase.ATTACKING``) is
    always a kick. The predictive half mirrors ``$16E54``-``$16F0E``:
    target available, in the velocity-selected X window, and inside the
    ``$10`` lane window. ``boss_dist_*`` are the ROM's own ``+$50``/``+$52``
    words; we fall back to a computed gap if they were not populated.
    """

    if antonio.target_unavailable:
        return False
    if antonio.combat_phase in (
        CombatPhase.DEATH,
        CombatPhase.GRABBED,
        CombatPhase.RECOVERY,
    ):
        return False

    dist_x = antonio.boss_dist_x or abs(antonio.world_x - actor.world_x)
    dist_lane = antonio.boss_dist_lane or abs(antonio.world_y - actor.world_y)
    if antonio.primary_state == ANTONIO_KICK_PRIMARY_STATE:
        return dist_lane < ANTONIO_KICK_LANE
    # Already in the dash/throw commit (tactical $08): a locked-in ground
    # strike. Do *not* also fire on the uncommitted dash *window* -- that
    # window is the whole fight range, and treating it as a kick made
    # DodgeAntonioKick win every tick and never attack.
    if antonio.tactical == 0x08:
        return dist_lane < ANTONIO_DASH_LANE and dist_x < ANTONIO_DASH_DIST_MAX
    if dist_lane >= ANTONIO_KICK_LANE:
        return False
    return dist_x < _antonio_kick_distance_threshold(antonio, actor)


def check_for_antonio_kick(context: Context) -> Context:
    """Promote Antonio when his kick gate is live for a playable character.

    Per ``AI.md``, this is a threat judgment, not a 1:1 copy of every
    observed ``Antonio``. The kick is the user-reported combo-breaker:
    standing still in front of him -- the player's own signature while
    throwing a ground combo -- is one of the ROM trigger paths.
    """

    actors = _actors(context)
    if not actors:
        return set()

    tokens: set[Token] = set()
    for antonio in find_all(context, Antonio):
        if antonio.is_defeated:
            continue
        for actor in actors:
            if _antonio_will_kick(antonio, actor):
                tokens.add(
                    AntonioIsGoingToKick(
                        actor_slot=actor.slot, target_slot=antonio.slot
                    )
                )
    return tokens


def _souther_slash_distance_threshold(
    souther: Souther, actor: PlayableCharacter
) -> int:
    """The ROM's X window for the 1→2 claw commit, given the actor's motion.

    ``$15EDA (souther_state1_active_combat)`` reads the target's ``+$1C``, and
    ``beq`` on it is the standing-still path (``$58``). Non-zero is negated when
    ``+$60`` is nonzero -- signed into Souther's own frame -- so the ``bmi``
    path is "walking into him" and takes the widest window (``$68``), while
    ``bpl`` (backing away) takes the tightest (``$50``).

    The same reading as Antonio's ``_antonio_kick_distance_threshold``, and the
    same practical consequence: closing the distance is what lets him start
    from furthest out.
    """

    vel = actor.vel_x
    if abs(vel) < ANTONIO_STATIONARY_VEL:
        return SOUTHER_SLASH_DIST_STATIONARY
    relative = -vel if souther.facing_left else vel
    if relative < 0:
        return SOUTHER_SLASH_DIST_CLOSING
    return SOUTHER_SLASH_DIST_AWAY


def _souther_will_slash(souther: Souther, actor: PlayableCharacter) -> bool:
    """True when Souther's commit gate is satisfied, or the claw is already on.

    Already-committed (primary ``$02``) is always a slash. The predictive half
    mirrors ``$15EDA``: target available, ``+$66`` hard-hold clear, inside the
    lane window, and inside the velocity-selected X window but **outside** the
    ``$18`` inner abort -- that abort is a real part of the gate, not a
    conservatism, so leaving it out would report a slash from a range the ROM
    refuses to start one at.
    """

    if souther.target_unavailable:
        return False
    if souther.combat_phase in (
        CombatPhase.DEATH,
        CombatPhase.GRABBED,
        CombatPhase.RECOVERY,
    ):
        return False

    dist_x = souther.boss_dist_x or abs(souther.world_x - actor.world_x)
    dist_lane = souther.boss_dist_lane or abs(souther.world_y - actor.world_y)
    if souther.primary_state == SOUTHER_SLASH_PRIMARY_STATE:
        return True
    if dist_lane >= SOUTHER_SLASH_LANE:
        return False
    if dist_x < SOUTHER_SLASH_DIST_MIN:
        return False
    return dist_x < _souther_slash_distance_threshold(souther, actor)


def check_for_souther_slash(context: Context) -> Context:
    """Promote Souther when his claw gate is live for a playable character."""

    actors = _actors(context)
    if not actors:
        return set()

    tokens: set[Token] = set()
    for souther in find_all(context, Souther):
        if souther.is_defeated:
            continue
        for actor in actors:
            if _souther_will_slash(souther, actor):
                tokens.add(
                    SoutherIsGoingToSlash(
                        actor_slot=actor.slot, target_slot=souther.slot
                    )
                )
    return tokens


def check_for_souther_jump_counter(context: Context) -> Context:
    """Promote the actor whose next jump attack would be punished.

    Keyed on the actor alone, because ``$162A4
    (souther_flag_target_jump_attack)`` reads the player's own action state and
    nothing about the jump's target: a hop aimed at an unrelated grunt inside
    the box is answered identically.

    A jump near a live Souther loses in two independent ways, which is why this
    does not test whether ``$16234`` is currently on his call path (see the
    constants above): while he can still choose, the jump-attack action state
    hands him the counter; while he is already dashing, the type-``$98`` claw
    is a live attack object and the flight lands in it. The only Souther worth
    hopping at is one who cannot act -- and a ``GrabOpportunity`` with reason
    ``SOUTHER_ON_PUNISH`` outranks the hop there anyway.

    The X half-width is widened by the character's own free-flight reach
    (``reach.jump_attack_max_dx``), because ``+$79`` stays set for as long as
    the kick action does and Souther re-tests every frame of the flight rather
    than only its onset: a launch from just outside 120px flies straight in.
    """

    actors = _actors(context)
    if not actors:
        return set()

    southers = [
        souther
        for souther in find_all(context, Souther)
        if not souther.is_defeated and not is_punishable(souther.combat_phase)
    ]
    if not southers:
        return set()

    tokens: set[Token] = set()
    for actor in actors:
        # The actor's own deltas rather than Souther's cached +$50/+$52: those
        # words measure to *his* selected target, which in 2P need not be this
        # actor, while the flag itself is armed by either player jumping.
        flight = reach.jump_attack_max_dx(actor.character_id)
        for souther in southers:
            if abs(souther.world_x - actor.world_x) >= (
                SOUTHER_JUMP_COUNTER_DIST_X + flight
            ):
                continue
            tokens.add(SoutherPunishesJump(actor_slot=actor.slot))
            break
    return tokens


def check_for_weapon_upgrades(context: Context) -> Context:
    """Promote ground weapons that beat what the actor is carrying."""

    camera = find(context, CameraRange)
    if camera is None:
        return set()

    weapons = [
        weapon
        for weapon in find_all(context, Weapon)
        if weapon.wear < 3 and reach.in_camera(camera, weapon.world_x, weapon.world_y)
    ]
    if not weapons:
        return set()

    tokens: set[Token] = set()
    for actor in _actors(context):
        held_rank = weapon_rank(actor.held_weapon_type)
        for weapon in weapons:
            rank = weapon_rank(weapon.weapon_type)
            if rank <= held_rank:
                continue
            tokens.add(
                WeaponUpgrade(
                    actor_slot=actor.slot,
                    target_slot=weapon.slot,
                    rank=rank,
                    rank_gain=rank - held_rank,
                )
            )
    return tokens


def generate_inference_tokens(context: Context) -> Context:
    """Derive every ``Inferred`` token from direct observation.

    Three stages, because two checks read judgments the others make rather
    than raw observation, and a ``|`` chain does **not** give them that: every
    ``check_for_x(context)`` inside one expression is handed the *same*
    original set, since the name is only rebound once the whole expression has
    been evaluated. Anything that needs an earlier token therefore has to sit
    in a later statement.

    - stage 1 derives from direct observation alone;
    - ``check_for_grab_opportunities`` additionally reads ``Surrounded``
      (``GrabReason.WHILE_SURROUNDED``), so it runs after stage 1 rather
      than inside it -- it used to sit in the chain *above*
      ``check_for_surrounded`` and would have seen nothing;
    - ``check_for_safe_spots`` reads ``IncomingMelee``.
    """

    context = (
        context
        | check_for_incoming_projectiles(context)
        | check_for_closing_enemies(context)
        | check_for_targets_in_reach(context)
        | check_for_incoming_melee(context)
        | check_for_antonio_kick(context)
        | check_for_souther_slash(context)
        | check_for_souther_jump_counter(context)
        | check_for_punish_windows(context)
        | check_for_surrounded(context)
        | check_for_weapon_upgrades(context)
    )
    context = context | check_for_grab_opportunities(context)
    return context | check_for_safe_spots(context)
