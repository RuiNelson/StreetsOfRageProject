"""Target selection, approach geometry, and combat intent helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..world_map import MapEntity
from .characters import CharacterProfile


# Horizontal distance at which we consider ourselves "in strike range".
DEFAULT_STRIKE = 28.0


@dataclass(frozen=True, slots=True)
class TargetChoice:
    entity: MapEntity
    score: float
    dx: float
    dy: float
    dist: float


def _threat_weight(entity: MapEntity) -> float:
    if entity.kind == "boss":
        return 3.0
    # Signal (throws) and Jack (projectiles) slightly higher priority.
    if entity.family in ("Signal", "Jack", "Haku-Ro"):
        return 1.6
    if entity.family == "Nora":
        return 1.3
    return 1.0


def select_target(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    profile: CharacterProfile,
    *,
    prefer_forward: bool = True,
) -> TargetChoice | None:
    """Pick the most urgent combatant to engage."""

    best: TargetChoice | None = None
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if entity.health is not None and entity.health <= 0:
            continue
        dx = entity.map_x - me.map_x
        dy = entity.map_y - me.map_y
        dist = math.hypot(dx, dy)
        # Soft ignore far off-screen dormant spawns unless no closer targets.
        if dist > 360:
            continue
        # Prefer same-lane targets; lane mismatch costs score.
        lane_pen = abs(dy) / max(1.0, profile.lane_align)
        # Prefer on-screen and slightly ahead in progress direction.
        forward_bonus = 0.0
        if prefer_forward and dx > 0:
            forward_bonus = 0.4
        elif not prefer_forward and dx < 0:
            forward_bonus = 0.4
        weight = _threat_weight(entity)
        # Lower score is better.
        score = (dist / weight) + lane_pen * 8.0 - forward_bonus * 20.0
        if entity.kind == "boss":
            score -= 40.0
        choice = TargetChoice(entity=entity, score=score, dx=dx, dy=dy, dist=dist)
        if best is None or choice.score < best.score:
            best = choice
    return best


def approach_vector(
    me: MapEntity,
    target: TargetChoice,
    profile: CharacterProfile,
    *,
    low_health: bool = False,
) -> tuple[float, float, bool]:
    """Return (dx_sign, dy_sign, in_range) toward a good strike position.

    Signs are -1 / 0 / +1 in map space (dx>0 means target is to the right).
    """

    # Stand slightly to the side of the target at approach_offset.
    desired_x = target.entity.map_x
    if abs(target.dx) > 4:
        side = -1.0 if target.dx > 0 else 1.0  # stand on the side we approach from
        offset = profile.approach_offset
        if low_health:
            offset = profile.caution_range
        desired_x = target.entity.map_x + side * offset

    err_x = desired_x - me.map_x
    err_y = target.entity.map_y - me.map_y

    dx = 0.0
    dy = 0.0
    if abs(err_x) > 6:
        dx = 1.0 if err_x > 0 else -1.0
    if abs(err_y) > profile.lane_align:
        dy = 1.0 if err_y > 0 else -1.0

    in_range = (
        abs(target.dx) <= profile.strike_range + 6
        and abs(target.dy) <= profile.lane_align + 6
    )
    return dx, dy, in_range


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
    # Normalize to signs.
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
) -> MapEntity | None:
    """Nearest acceptable ground item (pickup or free weapon)."""

    best: MapEntity | None = None
    best_d = max_dist
    for entity in entities:
        if entity.kind == "weapon":
            if not allow_weapons:
                continue
        elif entity.kind == "pickup":
            fam = entity.family
            if fam in ("Health",) and not allow_health:
                continue
            if fam in ("Life", "Special") and not allow_special_life:
                continue
            if fam == "Score":
                # Score items are free for anyone nearby.
                pass
        else:
            continue
        d = math.hypot(entity.map_x - me.map_x, entity.map_y - me.map_y)
        if d < best_d:
            best_d = d
            best = entity
    return best
