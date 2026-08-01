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
from ..world_map import SCREEN_WIDTH, MapEntity
from . import enemies as enemy_ai
from .characters import CharacterProfile
from .enemies import CounterPlan


# map_x is camera-relative: 0 = left edge of visible screen, 320 = right.
# Only fight threats near the visible band — do not chase dormant off-screen spawns.
ON_SCREEN_LEFT = -24.0
ON_SCREEN_RIGHT = float(SCREEN_WIDTH) + 24.0
# Soft lookahead: allow slightly ahead of camera so we meet wave edges.
LOOKAHEAD_RIGHT = float(SCREEN_WIDTH) + 80.0
LOOKAHEAD_LEFT = -48.0

# Defaults if a profile omits bands (should not happen).
PUNCH_RANGE = 32.0
JUMP_KICK_MIN = 28.0
JUMP_KICK_MAX = 72.0
REAR_REACT_RANGE = 48.0


@dataclass(frozen=True, slots=True)
class TargetChoice:
    entity: MapEntity
    score: float
    dx: float
    dy: float
    dist: float
    plan: CounterPlan


def is_on_screen(entity: MapEntity, *, soft: bool = False) -> bool:
    """True if the entity is in (or just outside) the camera band on X."""

    left = LOOKAHEAD_LEFT if soft else ON_SCREEN_LEFT
    right = LOOKAHEAD_RIGHT if soft else ON_SCREEN_RIGHT
    return left <= entity.map_x <= right


def select_target(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    profile: CharacterProfile,
    *,
    prefer_forward: bool = True,
    include_projectiles: bool = True,
    my_seat: int = 1,
) -> TargetChoice | None:
    """Pick the most urgent **on-screen** combatant."""

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

        # Hard reject far off-screen dormant spawns (was causing chase-off-screen).
        if entity.kind != "projectile" and not is_on_screen(entity, soft=True):
            continue
        if entity.kind == "projectile" and not is_on_screen(entity, soft=True):
            continue

        plan = enemy_ai.plan_for(entity)
        dx = entity.map_x - me.map_x
        dy = entity.map_y - me.map_y
        dist = math.hypot(dx, dy)
        if dist > 220 and entity.kind != "projectile":
            continue
        if entity.kind == "projectile" and dist > 140:
            continue

        lane_pen = abs(dy) / max(1.0, profile.lane_align)
        # Prefer on-screen (strict) over soft lookahead.
        on_strict = is_on_screen(entity, soft=False)
        screen_pen = 0.0 if on_strict else 35.0

        forward_bonus = 0.0
        if prefer_forward and dx > 0:
            forward_bonus = 0.25
        elif not prefer_forward and dx < 0:
            forward_bonus = 0.25

        weight = plan.priority
        # Closest on-screen threats first; less weight on "forward only".
        score = (dist / max(0.5, weight)) + lane_pen * 10.0 + screen_pen - forward_bonus * 12.0

        if entity.kind == "boss":
            score -= 40.0
        if entity.kind == "projectile":
            score -= 35.0

        phase = entity.combat_phase
        if is_punishable(phase):
            score -= 80.0  # free punish beats merely-closer idle foes
        if is_dangerous(phase):
            score -= 18.0  # react to attackers hard
            if phase == CombatPhase.CHARGE and dist < 80:
                score -= 12.0
        # Behind us or hunting us — react now.
        if entity.targets_player == my_seat:
            score -= 30.0
        if abs(dx) < REAR_REACT_RANGE and abs(dy) < profile.lane_align + 12:
            score -= 12.0  # close threats matter, but not more than knockdown
        if plan.distrust_downed and entity.health is not None and entity.health <= 3:
            score -= 5.0
        if entity.pair_role == 2 and entity.kind == "boss":
            score += 8.0

        choice = TargetChoice(
            entity=entity, score=score, dx=dx, dy=dy, dist=dist, plan=plan
        )
        if best is None or choice.score < best.score:
            best = choice
    return best


def enemy_is_behind(me: MapEntity, foe: MapEntity, *, face_right: bool | None = None) -> bool:
    """True if the foe is on our rear side.

    Without a reliable facing bit on players, infer from relative X: if we have
    a preferred face (last walk dir), use that; else treat "behind" as the side
    opposite stage progress is not used here — pure geometry for reaction.
    """

    dx = foe.map_x - me.map_x
    if face_right is None:
        # Symmetric: not used alone; callers pass walk dir when known.
        return False
    if face_right and dx < -8:
        return True
    if not face_right and dx > 8:
        return True
    return False


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

    # Wider "in range" so we stop passive walking and start fighting sooner.
    abs_dx = abs(target.dx)
    abs_dy = abs(target.dy)
    punch_range = profile.strike_range + 10
    if abs_dx <= punch_range and abs_dy <= profile.lane_align + 10:
        in_range = True

    if is_punishable(phase) and phase != CombatPhase.GRABBED:
        err_x = target.entity.map_x - me.map_x
        err_y = target.entity.map_y - me.map_y
        dx = 0.0 if abs(err_x) <= 6 else (1.0 if err_x > 0 else -1.0)
        dy = 0.0 if abs(err_y) <= profile.lane_align else (1.0 if err_y > 0 else -1.0)
        in_range = abs(err_x) <= punch_range and abs(err_y) <= profile.lane_align + 8
        return dx, dy, in_range, plan

    if is_dangerous(phase) and plan.sidestep:
        if abs(target.dy) < 20:
            dy = 1.0 if (me.map_y + me.world_x) % 2 == 0 else -1.0
        if phase == CombatPhase.CHARGE and abs(target.dx) < 100:
            if abs(target.dx) < 40:
                dx = -1.0 if target.dx >= 0 else 1.0
            else:
                dx = -1.0 if target.dx > 0 else 1.0

    if target.entity.type_id == 0x56 and target.entity.boss_dist_x:
        dist_x = target.entity.boss_dist_x
        if 0x28 <= dist_x <= 0x78 and abs(target.dy) < 20:
            dx = -1.0 if target.dx > 0 else 1.0
            in_range = False
        elif dist_x > 0x78:
            dx = 1.0 if target.dx > 0 else -1.0

    return dx, dy, in_range, plan


def engagement_band(abs_dx: float, abs_dy: float, profile: CharacterProfile) -> str:
    """Classify distance: 'close' | 'jump' | 'approach' | 'far'.

    Jump windows are per character (GameFAQs). Back-attack range is checked
    separately via ``rear_in_band`` because it overlaps jump for Adam/Blaze.
    """

    if abs_dy > profile.lane_align + 16:
        return "approach"
    if abs_dx <= profile.strike_range + 8:
        return "close"
    if profile.jump_kick_min <= abs_dx <= profile.jump_kick_max:
        return "jump"
    if abs_dx <= profile.jump_kick_max + 40:
        return "approach"
    return "far"


def rear_in_band(abs_dx: float, profile: CharacterProfile) -> bool:
    """True when distance matches this character's back-attack sweet spot."""

    return profile.rear_range_min <= abs_dx <= profile.rear_range_max


def peril_vector(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
) -> tuple[float, float]:
    push_x = 0.0
    push_y = 0.0
    count = 0
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if should_ignore_as_target(entity.combat_phase):
            continue
        if not is_on_screen(entity, soft=True):
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
    profile: CharacterProfile | None = None,
) -> MapEntity | None:
    best: MapEntity | None = None
    best_score = 1e9
    for entity in entities:
        if entity.kind == "weapon":
            if not allow_weapons or already_holding_weapon:
                continue
            # Prefer character-strong weapons; deprioritize weak ones (Blaze knives).
            w_bonus = 0.0
            if profile is not None:
                tid = entity.type_id & 0xFF
                if tid in profile.weak_weapons:
                    w_bonus = 80.0  # almost ignore unless very close
                elif tid in profile.preferred_weapons:
                    w_bonus = -20.0
        elif entity.kind == "pickup":
            fam = entity.family
            if fam in ("Health",) and not allow_health:
                continue
            if fam in ("Life", "Special") and not allow_special_life:
                continue
            w_bonus = 0.0
        else:
            continue
        if not is_on_screen(entity, soft=True):
            continue
        d = math.hypot(entity.map_x - me.map_x, entity.map_y - me.map_y)
        score = d + w_bonus
        if score < best_score and d <= max_dist + 40:
            best_score = score
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
        if not is_on_screen(entity, soft=True):
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
        if e.kind in ("enemy", "boss")
        and e.targets_player == seat
        and is_on_screen(e, soft=True)
    )


def closest_behind(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    face_right: bool,
    max_dist: float = REAR_REACT_RANGE,
) -> MapEntity | None:
    """Nearest on-screen foe on our rear side (for turn-and-strike)."""

    best: MapEntity | None = None
    best_d = max_dist
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if entity.health is not None and entity.health <= 0:
            continue
        if should_ignore_as_target(entity.combat_phase):
            continue
        if not is_on_screen(entity, soft=False):
            continue
        if not enemy_is_behind(me, entity, face_right=face_right):
            continue
        if abs(entity.map_y - me.map_y) > 20:
            continue
        d = abs(entity.map_x - me.map_x)
        if d < best_d:
            best_d = d
            best = entity
    return best
