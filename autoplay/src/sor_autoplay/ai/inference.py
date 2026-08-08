"""``generate_inference_tokens`` and its ``check_for_*`` derivation functions."""

from __future__ import annotations

from ..phases import CombatPhase
from .character import Myself, Partner, PlayableCharacter
from .enemy import Enemy
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


def check_for_incoming_projectiles(context: Context) -> Context:
    return {
        IncomingProjectile(
            slot=projectile.slot,
            world_x=projectile.world_x,
            world_y=projectile.world_y,
            vel_x=projectile.vel_x,
            vel_z=projectile.vel_z,
        )
        for projectile in find_all(context, Projectile)
    }


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

        threat_level = len(targeting)
        threat_level += sum(1 for e in targeting if _is_close_and_facing_caution(e, actor))
        threat_level += len(nearby) // 2
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
    """Returns context | check_for_incoming_projectiles(context) | check_for_danger_zone(context)."""

    return context | check_for_incoming_projectiles(context) | check_for_danger_zone(context)
