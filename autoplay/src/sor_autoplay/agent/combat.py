"""Target selection, approach geometry, and combat intent helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..phases import (
    CombatPhase,
    is_dangerous,
    is_punishable,
    should_ignore_as_target,
)
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
    my_seat: int = 1,
) -> TargetChoice | None:
    """Pick the most urgent combatant using family counters + live phases."""

    best: TargetChoice | None = None
    for entity in entities:
        if entity.kind not in ("enemy", "boss", "projectile"):
            continue
        if entity.kind == "projectile" and not include_projectiles:
            continue
        if entity.kind != "projectile" and entity.health is not None and entity.health <= 0:
            continue
        if should_ignore_as_target(entity.combat_phase):
            continue

        plan = enemy_ai.plan_for(entity)
        dx = entity.map_x - me.map_x
        dy = entity.map_y - me.map_y
        dist = math.hypot(dx, dy)
        if dist > 360 and entity.kind != "projectile":
            continue
        if entity.kind == "projectile" and dist > 140:
            continue

        lane_pen = abs(dy) / max(1.0, profile.lane_align)
        forward_bonus = 0.0
        if prefer_forward and dx > 0:
            forward_bonus = 0.4
        elif not prefer_forward and dx < 0:
            forward_bonus = 0.4

        weight = plan.priority
        score = (dist / max(0.5, weight)) + lane_pen * 8.0 - forward_bonus * 20.0

        if entity.kind == "boss":
            score -= 40.0
        if entity.kind == "projectile":
            score -= 35.0

        phase = entity.combat_phase
        # Free punish windows — strongly prefer.
        if is_punishable(phase):
            score -= 55.0
        # Dangerous commit — still need to respect, but may sidestep first.
        if is_dangerous(phase):
            score -= 12.0  # still engage, but note danger
            if phase == CombatPhase.CHARGE and dist < 80:
                score -= 8.0  # must deal with incoming charge
        # Hunting me specifically (ROM target pointer).
        if entity.targets_player == my_seat:
            score -= 25.0
        # Nora feint: low health still dangerous.
        if plan.distrust_downed and entity.health is not None and entity.health <= 3:
            score -= 5.0
        # Twin pair: prefer role-1 / unpaired (role 0) first.
        if entity.pair_role == 2 and entity.kind == "boss":
            score += 8.0

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
    """Return (dx_sign, dy_sign, in_range, plan) with phase-aware spacing."""

    dx, dy, in_range, plan = enemy_ai.adjust_approach(
        me, target.entity, profile, low_health=low_health
    )
    phase = target.entity.combat_phase

    # Knockdown / blocked / recovery: walk straight in for max damage.
    if is_punishable(phase) and phase != CombatPhase.GRABBED:
        err_x = target.entity.map_x - me.map_x
        err_y = target.entity.map_y - me.map_y
        dx = 0.0 if abs(err_x) <= 6 else (1.0 if err_x > 0 else -1.0)
        dy = 0.0 if abs(err_y) <= profile.lane_align else (1.0 if err_y > 0 else -1.0)
        in_range = abs(err_x) <= profile.strike_range + 10 and abs(err_y) <= profile.lane_align + 8
        return dx, dy, in_range, plan

    # Charge / attack: amplify sidestep (lane escape).
    if is_dangerous(phase) and plan.sidestep:
        if abs(target.dy) < 20:
            # Force a lane change away from their lane centre.
            dy = 1.0 if (me.map_y + me.world_x) % 2 == 0 else -1.0
        # Don't walk into a charge head-on.
        if phase == CombatPhase.CHARGE and abs(target.dx) < 100:
            if target.dx > 0:
                dx = -1.0  # retreat or circle
            elif target.dx < 0:
                dx = 1.0
            # Prefer circle: keep some X motion opposite after lane shift
            if abs(target.dx) < 40:
                dx = -1.0 if target.dx >= 0 else 1.0

    # Antonio live distance: object +$50 is abs X to target when kind boss $56.
    if target.entity.type_id == 0x56 and target.entity.boss_dist_x:
        dist_x = target.entity.boss_dist_x
        # Asm: attack when roughly $28-$78 and small lane sep.
        if 0x28 <= dist_x <= 0x78 and abs(target.dy) < 20:
            # Step out of the band first.
            dx = -1.0 if target.dx > 0 else 1.0
            in_range = False
        elif dist_x > 0x78:
            dx = 1.0 if target.dx > 0 else -1.0

    return dx, dy, in_range, plan


def peril_vector(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
) -> tuple[float, float]:
    """Push away from dense clusters and active attackers."""

    push_x = 0.0
    push_y = 0.0
    count = 0
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if should_ignore_as_target(entity.combat_phase):
            continue
        dx = me.map_x - entity.map_x
        dy = me.map_y - entity.map_y
        dist = math.hypot(dx, dy)
        if dist < 1 or dist > 90:
            continue
        w = 1.0 / dist
        if is_dangerous(entity.combat_phase):
            w *= 2.5
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
        if should_ignore_as_target(entity.combat_phase):
            continue
        d = math.hypot(entity.map_x - me.map_x, entity.map_y - me.map_y)
        if d < best_d:
            best_d = d
            best = entity
    return best


def count_hunters(entities: tuple[MapEntity, ...], seat: int) -> int:
    return sum(
        1
        for e in entities
        if e.kind in ("enemy", "boss") and e.targets_player == seat
    )
