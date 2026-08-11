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
from . import reach
from .tokens import Myself, Partner, PlayableCharacter
from .tokens import Enemy, Grunt
from .tokens import (
    ActionableTarget,
    ClosingEnemy,
    GrabIntoDeadZone,
    GrabToClearRear,
    InGrabReach,
    InJumpAttackReach,
    InPunchReach,
    InRearReach,
    IncomingMelee,
    PunishWindow,
    Surrounded,
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

# A Grunt outside this time-to-arrival window is not "closing fast" yet.
# ~200ms at the 33ms poll default: covers one missed poll plus margin for
# the slowest measured RearAttack startup (Adam, 21 frames).
CLOSING_ENEMY_THREAT_TICKS = 6
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


def check_for_incoming_projectiles(context: Context) -> Context:
    """Promote only projectiles that threaten at least one playable character.

    Per ``AI.md``, ``IncomingProjectile`` is a threat judgment, not a 1:1 copy
    of every observed ``Projectile``.
    """

    actors = _actors(context)
    if not actors:
        return set()

    incoming: set[Token] = set()
    for projectile in find_all(context, Projectile):
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
    landing inside that band within ``CLOSING_ENEMY_THREAT_TICKS``.

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

    ticks = (abs(dx) - max_x) / abs(vx)
    return ticks <= CLOSING_ENEMY_THREAT_TICKS


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


def check_for_targets_in_reach(context: Context) -> Context:
    """Derive the per-move reach bands once per (actor, live enemy) pair.

    Computing these here instead of inside each ``could_*`` is what lets
    ``decide.py`` and ``priority.py`` ask the same question and get the same
    answer within a tick, and stops the same trigonometry from being redone
    once per verb family.
    """

    enemies = reach.live_enemies(context)
    if not enemies:
        return set()

    tokens: set[Token] = set()
    for actor in _actors(context):
        for enemy in enemies:
            pair = {"actor_slot": actor.slot, "target_slot": enemy.slot}
            if reach.punch_would_connect(actor, enemy):
                tokens.add(InPunchReach(**pair))
            if reach.in_rear_band(actor, enemy):
                tokens.add(InRearReach(**pair))
            if reach.in_jump_attack_band(actor, enemy):
                tokens.add(InJumpAttackReach(**pair))
            if reach.grab_would_connect(actor, enemy):
                tokens.add(InGrabReach(**pair))
            if reach.enemy_actionable(actor, enemy, enemies):
                tokens.add(ActionableTarget(**pair))
    return tokens


def check_for_incoming_melee(context: Context) -> Context:
    """Promote committed enemies close enough for their attack to land.

    The melee counterpart of ``check_for_incoming_projectiles``: a dangerous
    phase alone is not a threat (an enemy swinging at nothing three lanes
    away is not), and neither is proximity alone. Only on-screen enemies
    qualify -- an off-screen one cannot connect this tick.
    """

    enemies = reach.on_screen_enemies(context)
    if not enemies:
        return set()

    tokens: set[Token] = set()
    for actor in _actors(context):
        for enemy in enemies:
            if not is_dangerous(enemy.combat_phase):
                continue
            if not reach.too_close_to_keep_approaching(actor, enemy):
                continue
            tokens.add(IncomingMelee(actor_slot=actor.slot, target_slot=enemy.slot))
    return tokens


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
    fires for the situations where that trade pays off -- see the concrete
    ``GrabOpportunity`` subclasses. Whether the grab is *reachable* is a
    separate question, answered by ``InGrabReach`` above;
    ``decide.could_grab_enemy`` requires both.

    ``Grunt`` only, like ``check_for_closing_enemies``: the ROM does let a
    player hold the later bosses, but per-boss tactics are out of scope.
    """

    enemies = reach.on_screen_enemies(context)
    if not enemies:
        return set()

    grabbable = [enemy for enemy in enemies if enemy.combat_phase in GRABBABLE_PHASES]
    if not grabbable:
        return set()

    tokens: set[Token] = set()
    for actor in _actors(context):
        rear = reach.rear_threats(actor, enemies)
        for enemy in grabbable:
            if not isinstance(enemy, Grunt):
                continue
            pair = {"actor_slot": actor.slot, "target_slot": enemy.slot}
            # A rear threat that *is* the candidate is not a pincer -- the
            # actor would be walking backwards into the same enemy it is
            # already worried about, and reach.grab_would_connect (forward
            # only) would not have offered it anyway.
            if any(other.slot != enemy.slot for other in rear):
                tokens.add(GrabToClearRear(**pair))
            if enemy.min_reach > 0:
                # Every attack it owns starts further out than contact --
                # read from the ROM shape its animations select, not from
                # the enemy's type. See GrabIntoDeadZone.
                tokens.add(GrabIntoDeadZone(**pair))
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

    Uses the same close box as ``reach.rear_attack_is_warranted``'s
    boxed-in test, so "surrounded" and "the chord is warranted" cannot
    disagree about what counts as close.
    """

    enemies = reach.on_screen_enemies(context)
    if not enemies:
        return set()

    tokens: set[Token] = set()
    for actor in _actors(context):
        near = [
            enemy
            for enemy in enemies
            if abs(enemy.world_x - actor.world_x) <= reach.REAR_THREAT_X
            and abs(enemy.world_y - actor.world_y) <= reach.REAR_THREAT_Y
        ]
        behind = sum(1 for enemy in near if reach.enemy_behind_actor(actor, enemy))
        in_front = len(near) - behind
        pincered = behind >= 1 and in_front >= 1
        if len(near) < SURROUNDED_MIN_ENEMIES and not pincered:
            continue
        tokens.add(Surrounded(actor_slot=actor.slot, in_front=in_front, behind=behind))
    return tokens


def _inside_pit(context: Context, world_x: int, world_y: int) -> bool:
    for pit in find_all(context, Pit):
        if (
            pit.world_x - reach.PIT_AVOID_MARGIN <= world_x <= pit.world_x + pit.width + reach.PIT_AVOID_MARGIN
            and pit.lane_y - reach.PIT_AVOID_MARGIN <= world_y <= pit.lane_y + pit.height + reach.PIT_AVOID_MARGIN
        ):
            return True
    return False


def _safe_spot_candidates(
    actor: PlayableCharacter, threat: Enemy
) -> list[tuple[int, int]]:
    """Steps worth considering: away on X, and the two sidesteps, alone or
    combined with the retreat. Standing still is not a candidate -- this
    token only exists to answer "back off to *where*"."""

    away = -SAFE_SPOT_STEP_X if threat.world_x >= actor.world_x else SAFE_SPOT_STEP_X
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

        best: tuple[float, tuple[int, int]] | None = None
        for candidate_x, candidate_y in _safe_spot_candidates(actor, nearest):
            if not reach.in_playable_lane(candidate_y, context):
                continue
            if camera is not None and not reach.in_camera(camera, candidate_x, candidate_y):
                continue
            if _inside_pit(context, candidate_x, candidate_y):
                continue
            clearance = min(
                math.hypot(enemy.world_x - candidate_x, enemy.world_y - candidate_y)
                for enemy in enemies
            )
            if best is None or clearance > best[0]:
                best = (clearance, (candidate_x, candidate_y))
        if best is None:
            continue
        tokens.add(
            SafeSpot(actor_slot=actor.slot, world_x=best[1][0], world_y=best[1][1])
        )
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

    ``check_for_safe_spots`` reads the ``IncomingMelee`` tokens produced
    earlier in this same chain, so the context is threaded through the
    calls in order rather than unioned from independent snapshots.
    """

    context = (
        context
        | check_for_incoming_projectiles(context)
        | check_for_closing_enemies(context)
        | check_for_targets_in_reach(context)
        | check_for_incoming_melee(context)
        | check_for_grab_opportunities(context)
        | check_for_punish_windows(context)
        | check_for_surrounded(context)
        | check_for_weapon_upgrades(context)
    )
    return context | check_for_safe_spots(context)
