"""Target selection, hit geometry, and approach helpers.

Hit rules are derived from ROM proximity tests (``SoRInteractions`` /
``find_close_interaction_target``):

- Player facing is **bit 0 of action state** (``+$30``): set = facing left.
- Lane Y for front interactions is about **±12** from the player.
- A grounded punch only lands when the foe is **in front**, **Y-aligned**,
  and within character strike range on X.

The old agent punched from loose "close" bands without facing or lane checks,
which produced air punches and wrong-direction swings.
"""

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
ON_SCREEN_LEFT = -24.0
ON_SCREEN_RIGHT = float(SCREEN_WIDTH) + 24.0
LOOKAHEAD_RIGHT = float(SCREEN_WIDTH) + 80.0
LOOKAHEAD_LEFT = -48.0

# ROM ``hasNearbyObjectInFront`` uses Y ∈ [playerY-12, playerY+12).
LANE_HIT_HALF = 12.0
# Slightly looser when walking to a foe so we still approach.
LANE_APPROACH_HALF = 16.0
# Minimum |dx| to decide "left vs right" (avoid flip-flop on top of foe).
FACE_DEADZONE = 4.0
# Rear-react distance (B+C back attack family).
REAR_REACT_RANGE = 44.0

# Legacy aliases used by older tests.
PUNCH_RANGE = 28.0
JUMP_KICK_MIN = 28.0
JUMP_KICK_MAX = 72.0


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


def player_facing_left(me: MapEntity) -> bool:
    """Player facing from action-state bit 0 (ROM: set = face left)."""

    return bool(me.action_state & 0x01)


def foe_is_to_the_left(me: MapEntity, foe: MapEntity) -> bool:
    return (foe.map_x - me.map_x) < -FACE_DEADZONE


def foe_is_to_the_right(me: MapEntity, foe: MapEntity) -> bool:
    return (foe.map_x - me.map_x) > FACE_DEADZONE


def desired_face_left(me: MapEntity, foe: MapEntity) -> bool:
    """Which way we should face to hit ``foe`` (prefer current face in deadzone)."""

    dx = foe.map_x - me.map_x
    if dx < -FACE_DEADZONE:
        return True
    if dx > FACE_DEADZONE:
        return False
    return player_facing_left(me)


def facing_toward(me: MapEntity, foe: MapEntity) -> bool:
    """True if we already face the side the foe is on."""

    dx = foe.map_x - me.map_x
    face_left = player_facing_left(me)
    if abs(dx) <= FACE_DEADZONE:
        return True  # on top of them — either face is fine
    if dx < 0:
        return face_left
    return not face_left


def lane_aligned(
    me: MapEntity,
    foe: MapEntity,
    *,
    half: float = LANE_HIT_HALF,
) -> bool:
    return abs(foe.map_y - me.map_y) <= half


def abs_dx_dy(me: MapEntity, foe: MapEntity) -> tuple[float, float]:
    return abs(foe.map_x - me.map_x), abs(foe.map_y - me.map_y)


def can_punch(
    me: MapEntity,
    foe: MapEntity,
    profile: CharacterProfile,
    *,
    require_facing: bool = True,
) -> bool:
    """True when a grounded B can reasonably connect this frame."""

    abs_dx, abs_dy = abs_dx_dy(me, foe)
    if abs_dy > LANE_HIT_HALF:
        return False
    if abs_dx > profile.strike_range:
        return False
    # Too far "inside" them on X still hits in SoR; allow 0..strike.
    if require_facing and not facing_toward(me, foe):
        return False
    return True


def can_jump_kick(
    me: MapEntity,
    foe: MapEntity,
    profile: CharacterProfile,
) -> bool:
    """Jump-kick only in the character's mid X window and same lane."""

    abs_dx, abs_dy = abs_dx_dy(me, foe)
    if abs_dy > LANE_HIT_HALF:
        return False
    if not (profile.jump_kick_min <= abs_dx <= profile.jump_kick_max):
        return False
    return True


def can_rear_hit(
    me: MapEntity,
    foe: MapEntity,
    profile: CharacterProfile,
    *,
    face_right: bool,
) -> bool:
    """Back attack only vs a foe truly behind us and in rear band."""

    if not enemy_is_behind(me, foe, face_right=face_right, max_dist=profile.rear_range_max):
        return False
    abs_dx = abs(foe.map_x - me.map_x)
    return profile.rear_range_min <= abs_dx <= profile.rear_range_max


def player_busy_attacking(me: MapEntity) -> bool:
    """True while the player is committed to an attack/rear animation."""

    base = me.action_base
    if 0x18 <= base <= 0x1F:
        return True
    if 0x20 <= base <= 0x27:
        return True
    # Mid grab-strike animation (not hold idle).
    if 0x44 <= base <= 0x4F and base != 0x4A:
        return True
    return False


def player_airborne_action(me: MapEntity) -> bool:
    base = me.action_base
    return me.is_airborne or (0x10 <= base <= 0x17)


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

        lane_pen = abs(dy) / max(1.0, LANE_HIT_HALF)
        on_strict = is_on_screen(entity, soft=False)
        screen_pen = 0.0 if on_strict else 35.0

        forward_bonus = 0.0
        if prefer_forward and dx > 0:
            forward_bonus = 0.25
        elif not prefer_forward and dx < 0:
            forward_bonus = 0.25

        weight = plan.priority
        # Prefer same-lane threats — off-lane "close" foes were air-punch bait.
        score = (dist / max(0.5, weight)) + lane_pen * 18.0 + screen_pen - forward_bonus * 12.0

        if entity.kind == "boss":
            score -= 40.0
        if entity.kind == "projectile":
            score -= 35.0

        phase = entity.combat_phase
        if is_punishable(phase):
            score -= 80.0
        if is_dangerous(phase):
            score -= 18.0
            if phase == CombatPhase.CHARGE and dist < 80:
                score -= 12.0
        if entity.targets_player == my_seat:
            score -= 30.0
        if abs(dx) < REAR_REACT_RANGE and abs(dy) < LANE_HIT_HALF + 4:
            score -= 12.0
        if plan.distrust_downed and entity.health is not None and entity.health <= 3:
            score -= 5.0
        if entity.pair_role == 2 and entity.kind == "boss":
            score += 8.0
        # Already aligned + in strike range: strong preference.
        if can_punch(me, entity, profile, require_facing=False):
            score -= 25.0

        choice = TargetChoice(
            entity=entity, score=score, dx=dx, dy=dy, dist=dist, plan=plan
        )
        if best is None or choice.score < best.score:
            best = choice
    return best


def enemy_is_behind(
    me: MapEntity,
    foe: MapEntity,
    *,
    face_right: bool,
    max_dist: float = REAR_REACT_RANGE,
) -> bool:
    """True if the foe is on our **rear** side and close enough for a back attack."""

    dx = foe.map_x - me.map_x
    dy = abs(foe.map_y - me.map_y)
    if dy > LANE_HIT_HALF:
        return False
    if abs(dx) > max_dist or abs(dx) < 6:
        return False
    if face_right and dx < -10:
        return True
    if not face_right and dx > 10:
        return True
    return False


def approach_vector(
    me: MapEntity,
    target: TargetChoice,
    profile: CharacterProfile,
    *,
    low_health: bool = False,
) -> tuple[float, float, bool, CounterPlan]:
    """Return (dx_sign, dy_sign, in_range, plan) with phase-aware spacing.

    ``in_range`` here means **geometry for a grounded punch** (facing optional
    so approach still reports readiness before the turn completes).
    """

    dx, dy, _old_in, plan = enemy_ai.adjust_approach(
        me, target.entity, profile, low_health=low_health
    )
    phase = target.entity.combat_phase
    in_range = can_punch(me, target.entity, profile, require_facing=False)

    if is_punishable(phase) and phase != CombatPhase.GRABBED:
        abs_dx = abs(target.dx)
        # Still keep a punchable gap on knockdowns — do not mount the corpse.
        stand = max(profile.approach_offset * 0.75, profile.strike_range * 0.7)
        if abs_dx > stand + 4:
            dx = 1.0 if target.dx > 0 else -1.0
        elif abs_dx < 16:
            dx = -1.0 if target.dx > 0 else 1.0
        else:
            dx = 0.0
        dy = 0.0 if lane_aligned(me, target.entity) else (1.0 if target.dy > 0 else -1.0)
        in_range = can_punch(me, target.entity, profile, require_facing=False)
        return dx, dy, in_range, plan

    if is_dangerous(phase) and plan.sidestep:
        if abs(target.dy) < 18:
            dy = 1.0 if (me.map_y + me.world_x) % 2 == 0 else -1.0
        if phase == CombatPhase.CHARGE and abs(target.dx) < 100:
            dx = -1.0 if target.dx >= 0 else 1.0

    return dx, dy, in_range, plan


def engagement_band(abs_dx: float, abs_dy: float, profile: CharacterProfile) -> str:
    """Classify distance: 'close' | 'jump' | 'approach' | 'far'.

    Off-lane foes are never 'close' — that was the main air-punch source.
    """

    if abs_dy > LANE_HIT_HALF:
        if abs_dy > LANE_APPROACH_HALF + 8:
            return "far" if abs_dx > profile.jump_kick_max else "approach"
        return "approach"
    if abs_dx <= profile.strike_range:
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
            w_bonus = 0.0
            if profile is not None:
                tid = entity.type_id & 0xFF
                if tid in profile.weak_weapons:
                    w_bonus = 80.0
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
    """Nearest on-screen foe truly behind us (for turn + back attack)."""

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
        if not enemy_is_behind(
            me, entity, face_right=face_right, max_dist=max_dist
        ):
            continue
        d = abs(entity.map_x - me.map_x)
        if d < best_d:
            best_d = d
            best = entity
    return best


def face_intent_dirs(me: MapEntity, foe: MapEntity) -> tuple[bool, bool]:
    """(left, right) D-pad to face ``foe``. Always one side when off deadzone."""

    want_left = desired_face_left(me, foe)
    if abs(foe.map_x - me.map_x) <= FACE_DEADZONE:
        # Keep current face by holding that side slightly.
        if player_facing_left(me):
            return True, False
        return False, True
    return want_left, not want_left
