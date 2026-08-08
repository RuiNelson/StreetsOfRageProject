"""``generate_inference_tokens`` and its ``check_for_*`` derivation functions."""

from __future__ import annotations

from ..phases import CombatPhase, is_dangerous
from .character import Myself, Partner, PlayableCharacter
from .enemy import Enemy, Jack
from .hazard_tokens import DangerZone, IncomingProjectile, Projectile
from .tokens import Context, Token, find, find_all

# Deliberately a rough v1 bounding box.
DANGER_ZONE_MARGIN = 16
CAUTION_RANGE_X = 40
CAUTION_RANGE_Y = 24
# Wider than the caution range: proximity clustering per AI.md -- "a cluster
# of Enemy tokens positioned in close proximity to one another" contributes a
# smaller weight even before any of them targets the player.
CLUSTER_RANGE_X = 80
CLUSTER_RANGE_Y = 40
# Projectiles outside this time-to-impact window are not "incoming" yet.
PROJECTILE_THREAT_TICKS = 30
PROJECTILE_LANE_SLACK = 24

# Relative strength weights for danger-zone scoring (enemy-ai.md combat table).
# Jack and Nora hit harder / tank more; Signal/Haku-Ro are mid; Garcia is base.
_ENEMY_THREAT_WEIGHT: dict[int, int] = {
    0x20: 1,
    0x21: 1,
    0x22: 1,
    0x23: 2,  # strong Garcia damage $0C
    0x24: 2,  # Signal — slides, throws
    0x25: 2,  # Haku-Ro
    0x2A: 2,
    0x26: 2,  # Nora
    0x27: 3,  # Jack
    0x30: 5,  # bosses
    0x35: 5,
    0x55: 5,
    0x56: 5,
    0x57: 5,
    0x58: 5,
}


def _actors(context: Context) -> list[PlayableCharacter]:
    return [actor for actor in (find(context, Myself), find(context, Partner)) if actor is not None]


def _is_facing(enemy: Enemy, target_world_x: int) -> bool:
    return target_world_x <= enemy.world_x if enemy.facing_left else target_world_x >= enemy.world_x


def _is_close_and_facing_caution(enemy: Enemy, actor: PlayableCharacter) -> bool:
    return (
        enemy.combat_phase is CombatPhase.UNKNOWN
        and abs(enemy.world_x - actor.world_x) <= CAUTION_RANGE_X
        and abs(enemy.world_y - actor.world_y) <= CAUTION_RANGE_Y
        and _is_facing(enemy, actor.world_x)
    )


def _enemy_weight(enemy: Enemy) -> int:
    base = _ENEMY_THREAT_WEIGHT.get(enemy.type_id & 0xFF, 1)
    if is_dangerous(enemy.combat_phase):
        base += 2
    if isinstance(enemy, Jack) and enemy.has_projectile:
        base += 1
    return base


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


def check_for_danger_zone(context: Context) -> Context:
    zones: set[Token] = set()
    enemies = find_all(context, Enemy)
    for actor in _actors(context):
        targeting = [e for e in enemies if e.targets_player == actor.player_index]
        targeting_slots = {e.slot for e in targeting}
        # Proximity clustering: enemies merely nearby (not already counted via
        # targeting) contribute a smaller weight -- avoid double-counting.
        nearby = [
            e
            for e in enemies
            if e.slot not in targeting_slots
            and abs(e.world_x - actor.world_x) <= CLUSTER_RANGE_X
            and abs(e.world_y - actor.world_y) <= CLUSTER_RANGE_Y
        ]

        threat_level = sum(_enemy_weight(e) for e in targeting)
        threat_level += sum(
            _enemy_weight(e) for e in targeting if _is_close_and_facing_caution(e, actor)
        )
        threat_level += sum(_enemy_weight(e) for e in nearby) // 2
        # Incoming projectiles also raise the local threat.
        threat_level += len(
            [
                p
                for p in find_all(context, IncomingProjectile)
                if abs(p.world_x - actor.world_x) <= CLUSTER_RANGE_X
                and abs(p.world_y - actor.world_y) <= CLUSTER_RANGE_Y
            ]
        )
        if threat_level <= 0:
            continue

        cluster = [*targeting, *nearby]
        world_xs = [actor.world_x, *(e.world_x for e in cluster)]
        world_ys = [actor.world_y, *(e.world_y for e in cluster)]
        zones.add(
            DangerZone(
                slot=actor.slot,
                left=min(world_xs) - DANGER_ZONE_MARGIN,
                right=max(world_xs) + DANGER_ZONE_MARGIN,
                top=min(world_ys) - DANGER_ZONE_MARGIN,
                bottom=max(world_ys) + DANGER_ZONE_MARGIN,
                threat_level=threat_level,
            )
        )
    return zones


def generate_inference_tokens(context: Context) -> Context:
    """Derive IncomingProjectile / DangerZone tokens from direct observation.

    Incoming projectiles are computed first so danger-zone scoring can include
    them without a second pass.
    """

    incoming = check_for_incoming_projectiles(context)
    with_incoming = context | incoming
    return with_incoming | check_for_danger_zone(with_incoming)
