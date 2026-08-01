"""Target selection, approach geometry, and combat intent helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..world_map import MapEntity
from . import enemies as enemy_ai
from .characters import CharacterProfile
from .enemies import CounterPlan


@dataclass(frozen=True, slots=True)
class TargetChoice:
    entity: MapEntity
    score: float
    dx: float
    dy: float
    dist: float
    plan: CounterPlan


def select_target(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    profile: CharacterProfile,
    *,
    prefer_forward: bool = True,
    include_projectiles: bool = True,
) -> TargetChoice | None:
    """Pick the most urgent combatant (or dodge-critical projectile)."""

    best: TargetChoice | None = None
    for entity in entities:
        if entity.kind not in ("enemy", "boss", "projectile"):
            continue
        if entity.kind == "projectile" and not include_projectiles:
            continue
        if entity.kind != "projectile" and entity.health is not None and entity.health <= 0:
            continue
        # Nora feint: still target low-health Noras (distrust_downed).
        plan = enemy_ai.plan_for(entity)
        dx = entity.map_x - me.map_x
        dy = entity.map_y - me.map_y
        dist = math.hypot(dx, dy)
        if dist > 360 and entity.kind != "projectile":
            continue
        if entity.kind == "projectile" and dist > 120:
            continue

        lane_pen = abs(dy) / max(1.0, profile.lane_align)
        forward_bonus = 0.0
        if prefer_forward and dx > 0:
            forward_bonus = 0.4
        elif not prefer_forward and dx < 0:
            forward_bonus = 0.4

        weight = plan.priority
        # Lower score is better.
        score = (dist / max(0.5, weight)) + lane_pen * 8.0 - forward_bonus * 20.0
        if entity.kind == "boss":
            score -= 40.0
        if entity.kind == "projectile":
            score -= 30.0  # dodge now
        if plan.distrust_downed and entity.health is not None and entity.health <= 3:
            score -= 5.0  # still finish Nora, don't ignore

        choice = TargetChoice(
            entity=entity, score=score, dx=dx, dy=dy, dist=dist, plan=plan
        )
        if best is None or choice.score < best.score:
            best = choice
    return best


def approach_vector(
    me: MapEntity,
    target: TargetChoice,
    profile: CharacterProfile,
    *,
    low_health: bool = False,
) -> tuple[float, float, bool, CounterPlan]:
    """Return (dx_sign, dy_sign, in_range, plan) with family-specific spacing."""

    return enemy_ai.adjust_approach(
        me, target.entity, profile, low_health=low_health
    )


def peril_vector(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
) -> tuple[float, float]:
    """Push away from dense clusters to a less perilous lane/side."""

    push_x = 0.0
    push_y = 0.0
    count = 0
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        dx = me.map_x - entity.map_x
        dy = me.map_y - entity.map_y
        dist = math.hypot(dx, dy)
        if dist < 1 or dist > 80:
            continue
        w = 1.0 / dist
        push_x += dx * w
        push_y += dy * w
        count += 1
    if count < 2:
        return 0.0, 0.0
    sx = 0.0 if abs(push_x) < 0.05 else (1.0 if push_x > 0 else -1.0)
    sy = 0.0 if abs(push_y) < 0.05 else (1.0 if push_y > 0 else -1.0)
    return sx, sy


def select_pickup(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    allow_health: bool,
    allow_special_life: bool,
    allow_weapons: bool = True,
    max_dist: float = 160.0,
    already_holding_weapon: bool = False,
) -> MapEntity | None:
    """Nearest acceptable ground item (pickup or free weapon)."""

    best: MapEntity | None = None
    best_d = max_dist
    for entity in entities:
        if entity.kind == "weapon":
            if not allow_weapons or already_holding_weapon:
                continue
        elif entity.kind == "pickup":
            fam = entity.family
            if fam in ("Health",) and not allow_health:
                continue
            if fam in ("Life", "Special") and not allow_special_life:
                continue
            if fam == "Score":
                pass
        else:
            continue
        d = math.hypot(entity.map_x - me.map_x, entity.map_y - me.map_y)
        if d < best_d:
            best_d = d
            best = entity
    return best


def nearest_foe(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
) -> MapEntity | None:
    best: MapEntity | None = None
    best_d = 1e9
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if entity.health is not None and entity.health <= 0:
            continue
        d = math.hypot(entity.map_x - me.map_x, entity.map_y - me.map_y)
        if d < best_d:
            best_d = d
            best = entity
    return best
