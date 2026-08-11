"""``generate_inference_tokens`` and its ``check_for_*`` derivation functions."""

from __future__ import annotations

from ..phases import CombatPhase, should_ignore_as_target
from .tokens import Myself, Partner, PlayableCharacter
from .tokens import Enemy, Jack
from .tokens import ClosingEnemy, Grunt
from .tokens import IncomingProjectile, Projectile
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
    have a real behind band. This mirrors decide.py's own
    facing-aware ``_enemy_behind_actor`` test rather than importing it, to
    keep the existing no-cross-import convention between the two modules.
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

    behind = (dx > 0) if actor.facing_left else (dx < 0)
    max_x = (
        rear_attack_behind_max_x(actor.character_id)
        if behind
        else rear_attack_front_max_x(actor.character_id)
    )
    if max_x <= 0:
        # No reach at all on this side (e.g. Axel/Blaze from the front).
        return False
    if abs(dx) <= max_x:
        # Already inside the band -- decide._in_rear_band already covers
        # this tick without needing the early-warning signal.
        return False

    ticks = (abs(dx) - max_x) / abs(vx)
    return ticks <= CLOSING_ENEMY_THREAT_TICKS


def check_for_closing_enemies(context: Context) -> Context:
    """Promote Grunt enemies about to close into rear-attack range soon.

    Per ``AI.md``, this is a threat judgment, not a 1:1 copy of every
    observed ``Grunt`` -- see the module docstring on ``ClosingEnemy`` for
    why the AI needs this early-warning signal at all: the band checks in
    ``decide.py`` are purely instantaneous-position, so a fast diagonal
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


def generate_inference_tokens(context: Context) -> Context:
    """Derive ``IncomingProjectile``/``ClosingEnemy`` tokens from direct
    observation."""

    return (
        context
        | check_for_incoming_projectiles(context)
        | check_for_closing_enemies(context)
    )
