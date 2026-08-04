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
from ..world_map import (
    LOOT_REACH_X,
    SCREEN_WIDTH,
    MapEntity,
    is_in_loot_camera,
)
from . import enemies as enemy_ai
from . import stage as stage_rules
from .characters import CharacterProfile
from .enemies import CounterPlan
from .fuzzy import clamp01, falling
from .jump_kick import (
    JumpKickPlan,
    can_jump_kick_solved,
    solve_jump_kick,
)
from .weapons import (
    SPECS as _WEAPON_SPECS,
    is_weapon_upgrade,
    weapon_utility,
    weapon_value,
)
from .knowledge import Relation, TacticalKnowledgeGraph


# map_x is camera-relative: 0 = left edge of the visible screen, 320 = right.
# The ROM activates ordinary enemies in a slightly wider -16..336 band
# ($A59C -> $97E6), but activation is not visibility: the agent must not chase
# an actor until it has actually entered the camera view.
ON_SCREEN_LEFT = 0.0
ON_SCREEN_RIGHT = float(SCREEN_WIDTH)
ACTIVATION_LEFT = -16.0
ACTIVATION_RIGHT = float(SCREEN_WIDTH) + 16.0

# ROM ``hasNearbyObjectInFront`` uses Y ∈ [playerY-12, playerY+12).
LANE_HIT_HALF = 12.0
# Slightly looser when walking to a foe so we still approach.
LANE_APPROACH_HALF = 16.0
# ROM $3136 interaction box is ±$14 X, ±$10 lane Y and ±$08 height Z.
# Stay a few units inside it so polling/animation movement cannot leave the
# player one pixel outside when the B edge reaches the game.
PICKUP_SAFE_X = LOOT_REACH_X
PICKUP_SAFE_Y = 12.0
PICKUP_SAFE_Z = 6.0
DANGER_REACT_X = 100.0
# A closing enemy covers roughly 20 px during the player's punch startup in
# the Round-1 lockstep trace. Begin a grounded interrupt before the static
# hitbox overlaps; by its active frame the enemy has entered strike range.
PREEMPTIVE_PUNCH_LEAD = 24.0
# Enemy collision lanes are wider than the player's conservative ±12 punch
# lane. Live Round-1 punches still connected at 14–15 px lane separation.
ENEMY_PUNCH_LANE_HALF = 20.0
# Garcia moved roughly 13 lane units in one four-frame observation. React
# before it reaches the actual collision lane instead of waiting at ±20.
THREAT_LANE_REACT_HALF = ENEMY_PUNCH_LANE_HALF + 16.0
THREAT_LANE_ESCAPE = 24.0
ENEMY_LANE_MIN = 2.0
ENEMY_LANE_MAX = 112.0
# Garcia pack types — exclude Signal ($24): prefer jump-ins over grounded
# intercept punches that walk into its slide/flank.
BASIC_ENEMY_TYPES = frozenset({0x20, 0x21, 0x22, 0x23})
# Signal's dispatcher table at ROM $E4DA maps state $08 to the sweep selector
# ($E5EC) and state $0B to the actual low sliding kick ($E80A): animation $18,
# X velocity $00070000. Jump before generic grounded-interrupt logic handles it.
SIGNAL_TYPE = 0x24
SIGNAL_SWEEP_STATES = frozenset({0x08, 0x0B})
SIGNAL_SWEEP_REACT_X = 120.0
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
    utility: float = 0.0
    explanation: tuple[str, ...] = ()


def is_on_screen(entity: MapEntity, *, soft: bool = False) -> bool:
    """True if the entity is in the camera band (or ROM activation if soft).

    Strict mode matches the 320 px Mega Drive viewport in camera-relative X.
    Soft mode uses the ROM activation margin (-16..336) for diagnostics only.
    Combat goals use strict mode. Loot goals use ``is_loot_on_camera`` (walk
    band ± pickup reach), which is tighter than the full CRT.
    """

    left = ACTIVATION_LEFT if soft else ON_SCREEN_LEFT
    right = ACTIVATION_RIGHT if soft else ON_SCREEN_RIGHT
    return left <= entity.map_x <= right


def is_loot_on_camera(entity: MapEntity) -> bool:
    """True when a ground item is inside the walk-band camera ± pickup box."""

    return is_in_loot_camera(entity.map_x)


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
    min_range: float = 0.0,
) -> bool:
    """True when a grounded B can reasonably connect this frame.

    ``min_range`` is the near dead zone: a body that has closed *inside* the
    punch arc is not hit by it. Measured live against an Onihime/Yasha body by
    teleport sweep (probe: place P1 at a fixed offset, one B, read boss `+$32`):
    misses at 8-24 px, clean hits at 28-52 px, misses again past 56. Callers
    that know their target's dead zone pass it; the default keeps the historic
    0..strike behaviour for families that were never measured.
    """

    abs_dx, abs_dy = abs_dx_dy(me, foe)
    if abs_dy > LANE_HIT_HALF:
        return False
    if abs_dx > profile.strike_range or abs_dx < min_range:
        return False
    if require_facing and not facing_toward(me, foe):
        return False
    return True


def can_collect_pickup(me: MapEntity, item: MapEntity) -> bool:
    """Whether B is safely inside the ROM's three-axis pickup search box."""

    return (
        abs(item.world_x - me.world_x) <= PICKUP_SAFE_X
        and abs(item.world_y - me.world_y) <= PICKUP_SAFE_Y
        and abs(item.world_z - me.world_z) <= PICKUP_SAFE_Z
    )


def player_can_start_ground_action(me: MapEntity) -> bool:
    """True in grounded idle/walk states that accept a new action edge.

    Holding a weapon moves the player from the ordinary ``$02–$0E`` family
    into ``$30–$3A``. The latter dispatches through ROM routine ``$2D20``,
    which accepts both weapon attack and the ``$3010`` jump input.
    """

    base = me.action_base
    return 0x02 <= base <= 0x0E or 0x30 <= base <= 0x3A


def enemy_attack_committed(me: MapEntity, foe: MapEntity) -> bool:
    """True while a nearby foe is in a decoded attack/wind-up state."""

    return (
        is_dangerous(foe.combat_phase)
        and abs(foe.map_x - me.map_x) <= DANGER_REACT_X
    )


def signal_sweep_threat(me: MapEntity, foe: MapEntity) -> bool:
    """True while a nearby Signal is selecting or executing its low sweep."""

    state = (foe.primary_state >> 8) & 0xFF
    abs_dx, abs_dy = abs_dx_dy(me, foe)
    return (
        foe.type_id == SIGNAL_TYPE
        and state in SIGNAL_SWEEP_STATES
        and abs_dx <= SIGNAL_SWEEP_REACT_X
        and abs_dy <= ENEMY_PUNCH_LANE_HALF
    )


def should_intercept_basic_enemy(
    me: MapEntity,
    foe: MapEntity,
    profile: CharacterProfile,
) -> bool:
    """Meet a nearby Garcia/Signal with a punch before its approach connects."""

    return (
        foe.type_id in BASIC_ENEMY_TYPES
        and not is_punishable(foe.combat_phase)
        and abs(foe.map_x - me.map_x)
        <= profile.strike_range + PREEMPTIVE_PUNCH_LEAD
        and lane_aligned(me, foe)
    )


def can_jump_kick(
    me: MapEntity,
    foe: MapEntity,
    profile: CharacterProfile,
    *,
    loose_lane: bool = False,
    entities: tuple[MapEntity, ...] | None = None,
    partner: MapEntity | None = None,
    plan_out: list[JumpKickPlan] | None = None,
) -> bool:
    """Whether a C→B jump-kick can hit ``foe`` (solver-backed when possible).

    Live: jump is action ``$10/$11``, free flight ``$12/$13``, kick ``$16``.
    Must be **C then B on later frames** — simultaneous B+C is the rear attack.

    When ``entities`` is provided, the ROM physics solver decides connectability
    and multi-hit value. Without it, a soft FAQ distance band is used (tests /
    coarse callers). Optional ``plan_out`` receives the winning :class:`JumpKickPlan`.
    """

    abs_dx, abs_dy = abs_dx_dy(me, foe)
    lane = LANE_HIT_HALF + (6.0 if loose_lane else 0.0)
    if abs_dy > lane:
        return False

    if entities is not None:
        ok, plan = can_jump_kick_solved(
            me,
            foe,
            profile,
            entities=entities,
            partner=partner,
            loose_lane=loose_lane,
        )
        if plan is not None and plan_out is not None:
            plan_out.clear()
            plan_out.append(plan)
        return ok

    if not (profile.jump_kick_min <= abs_dx <= profile.jump_kick_max):
        return False
    return True


def evaluate_jump_kick(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    profile: CharacterProfile,
    *,
    primary: MapEntity | None = None,
    partner: MapEntity | None = None,
) -> JumpKickPlan | None:
    """Full jump-kick solve: parameters + predicted hits (multi-enemy aware)."""

    return solve_jump_kick(
        me,
        entities,
        profile,
        primary=primary,
        partner=partner,
    )


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
    """True in normal or held-weapon jump actions. Not ``world_z``."""

    base = me.action_base
    return 0x10 <= base <= 0x17 or 0x3C <= base <= 0x42


def player_jump_starting(me: MapEntity) -> bool:
    """Jump launch state; an attack edge is too early here."""

    base = me.action_base
    return base in (0x10, 0x3C)


def player_jump_attack_ready(me: MapEntity) -> bool:
    """Free-flight state (``$12/$13``) that accepts B and enters ``$16``."""

    return me.action_base == 0x12


def player_jump_landing(me: MapEntity) -> bool:
    """Landing state; do not turn it into a ground attack."""

    return me.action_base in (0x14, 0x40)


def player_jump_attacking(me: MapEntity) -> bool:
    """Air-attack animation (``$16/$17``)."""

    return me.action_base == 0x16


def can_queue_normal_combo(
    me: MapEntity,
    foe: MapEntity,
    profile: CharacterProfile,
) -> bool:
    """Whether to send the B edge that queues the next grounded combo hit.

    ROM ``$201E`` accepts a new attack edge during action ``$18/$19`` and
    stores it in player ``+$58`` bit 5.  ``player_normal_attack_input`` later
    consumes that bit to advance the action chain.  Allow a little knockback
    slack beyond the first-hit box so a connecting jab can continue.
    """

    if me.action_base != 0x18:
        return False
    if me.action_flags & 0x20:
        return False
    abs_dx, abs_dy = abs_dx_dy(me, foe)
    if abs_dy > LANE_HIT_HALF + 6.0:
        return False
    if abs_dx > profile.strike_range + 20.0:
        return False
    return facing_toward(me, foe)


def select_target(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    profile: CharacterProfile,
    *,
    prefer_forward: bool = True,
    include_projectiles: bool = True,
    my_seat: int = 1,
    graph: TacticalKnowledgeGraph | None = None,
    preferred_slot: str | None = None,
    switch_margin: float = 0.12,
) -> TargetChoice | None:
    """Choose a reachable combatant by fuzzy peril/value with hysteresis."""

    choices: list[TargetChoice] = []
    for entity in entities:
        if entity.kind not in ("enemy", "boss", "projectile"):
            continue
        # Round-6 type-$42 presses are solid avoid-only hazards (no smash path).
        # Policy routes around them; they must not steal combat targeting.
        if stage_rules.is_stage_press(entity):
            continue
        # Jack's state-$01 type-$28 objects are the axes/torches visibly
        # juggling around him, not launched threats. Do not let those helpers
        # outrank Jack's vulnerable body forever.
        if (
            entity.kind == "projectile"
            and not enemy_ai.dangerous_projectile(entity)
        ):
            continue
        if entity.kind == "projectile" and not include_projectiles:
            continue
        if entity.kind != "projectile" and entity.is_defeated:
            continue
        if should_ignore_as_target(entity.combat_phase):
            continue

        reachable = (
            graph.entity_has(entity, Relation.REACHABLE)
            if graph is not None
            else is_on_screen(entity)
        )
        if not reachable:
            continue

        plan = enemy_ai.plan_for(entity, entities)
        dx = entity.map_x - me.map_x
        dy = entity.map_y - me.map_y
        dist = math.hypot(dx, dy)
        # A visible boss locks progression and stays a target across the whole
        # arena. Ordinary enemies retain a locality bound to avoid long chases.
        if dist > 220 and entity.kind not in ("projectile", "boss"):
            continue
        if entity.kind == "projectile" and dist > 140:
            continue

        phase = entity.combat_phase
        closeness = falling(dist, 20.0, 260.0 if entity.kind == "boss" else 220.0)
        lane_access = falling(abs(dy), 8.0, 72.0)
        peril = 0.15
        reasons = [f"near={closeness:.2f}", f"lane={lane_access:.2f}"]
        if entity.kind == "projectile" or plan.kind == enemy_ai.ThreatKind.PROJECTILE:
            peril = 1.0
            reasons.append("ranged")
        if is_dangerous(phase):
            peril = 1.0
            reasons.append("attacking")
        if entity.targets_player == my_seat:
            peril = max(peril, 0.82)
            reasons.append("targets-me")
        if entity.kind == "boss":
            peril = max(peril, 0.70)
            reasons.append("boss")
        if abs(dx) < REAR_REACT_RANGE and abs(dy) < LANE_HIT_HALF + 4:
            peril = max(peril, 0.62)
            reasons.append("contact-band")

        punish = 1.0 if is_punishable(phase) else 0.0
        boss = 1.0 if entity.kind == "boss" else 0.0
        forward = 1.0 if (prefer_forward and dx > 0) or (not prefer_forward and dx < 0) else 0.0
        strike = 1.0 if can_punch(me, entity, profile, require_facing=False) else 0.0
        priority = enemy_ai.target_priority_membership(entity)
        reasons.append(f"family-priority={priority:.2f}")
        utility = (
            0.24 * closeness
            + 0.25 * peril
            + 0.10 * lane_access
            + 0.22 * punish
            + 0.10 * boss
            + 0.03 * forward
            + 0.03 * strike
            + 0.22 * priority
        )
        if entity.kind == "projectile":
            utility = max(utility, 0.98)
        elif is_dangerous(phase):
            utility = max(utility, 0.82)
        if entity.kind == "boss":
            utility = max(utility, 0.94)
        if entity.slot == preferred_slot:
            reasons.append("current-focus")
        utility = min(1.0, utility)

        choice = TargetChoice(
            entity=entity,
            score=1.0 - utility,
            dx=dx,
            dy=dy,
            dist=dist,
            plan=plan,
            utility=utility,
            explanation=tuple(reasons),
        )
        choices.append(choice)

    if not choices:
        return None
    best = max(choices, key=lambda choice: choice.utility)
    current = next(
        (choice for choice in choices if choice.entity.slot == preferred_slot),
        None,
    )
    if current is not None and best.entity.slot != current.entity.slot:
        challenger_dangerous = (
            is_dangerous(best.entity.combat_phase)
            or best.entity.kind == "projectile"
        )
        current_dangerous = (
            is_dangerous(current.entity.combat_phase)
            or current.entity.kind == "projectile"
        )
        challenger_priority = enemy_ai.target_priority_membership(best.entity)
        current_priority = enemy_ai.target_priority_membership(current.entity)
        material_priority_jump = challenger_priority >= current_priority + 0.12
        if not (
            (challenger_dangerous and not current_dangerous)
            or material_priority_jump
        ):
            if best.utility < current.utility + switch_margin:
                return current
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
    entities: tuple[MapEntity, ...] | list[MapEntity] | None = None,
) -> tuple[float, float, bool, CounterPlan]:
    """Return (dx_sign, dy_sign, in_range, plan) with phase-aware spacing.

    ``in_range`` here means **geometry for a grounded punch** (facing optional
    so approach still reports readiness before the turn completes).

    """

    dx, dy, _old_in, plan = enemy_ai.adjust_approach(
        me,
        target.entity,
        profile,
        low_health=low_health,
        entities=entities,
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
        if entity.is_defeated:
            continue
        if should_ignore_as_target(entity.combat_phase):
            continue
        if not is_on_screen(entity):
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


def select_breakable(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    max_dist: float = 200.0,
    prefer_forward: bool = True,
    graph: TacticalKnowledgeGraph | None = None,
) -> MapEntity | None:
    """Nearest on-screen breakable (phone booth / crate) to smash for loot."""

    best: MapEntity | None = None
    best_score = 1e9
    for entity in entities:
        if entity.kind != "breakable":
            continue
        if graph is not None and not graph.entity_has(entity, Relation.REACHABLE):
            continue
        if not is_on_screen(entity):
            continue
        dx = entity.map_x - me.map_x
        dy = entity.map_y - me.map_y
        dist = math.hypot(dx, dy)
        if dist > max_dist:
            continue
        score = dist + abs(dy) * 2.0
        if prefer_forward and dx > 0:
            score -= 15.0
        elif not prefer_forward and dx < 0:
            score -= 15.0
        if score < best_score:
            best_score = score
            best = entity
    return best


def can_break(
    me: MapEntity,
    prop: MapEntity,
    profile: CharacterProfile,
    *,
    require_facing: bool = True,
) -> bool:
    """Grounded punch range vs a breakable (same box scale as enemy punch)."""

    return can_punch(me, prop, profile, require_facing=require_facing)


# Legacy name: known weapon types for pickup upgrade gates.
_WEAPON_BASE_VALUE = {tid: weapon_utility(tid) for tid in _WEAPON_SPECS}


def select_pickup(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    allow_health: bool,
    allow_special_life: bool,
    allow_weapons: bool = True,
    max_dist: float = 160.0,
    already_holding_weapon: bool = False,
    held_weapon_type: int = 0,
    profile: CharacterProfile | None = None,
    graph: TacticalKnowledgeGraph | None = None,
) -> MapEntity | None:
    best: MapEntity | None = None
    best_score = 1e9
    for entity in entities:
        if entity.kind == "weapon":
            if not allow_weapons:
                continue
            tid = entity.type_id & 0xFF
            current_type = held_weapon_type & 0xFF
            holding_weapon = already_holding_weapon or 0x08 <= current_type <= 0x0C
            if holding_weapon:
                # A caller that only knows the old Boolean API cannot compare
                # qualities safely; policy passes the concrete +$60 type.
                if current_type not in _WEAPON_BASE_VALUE:
                    continue
                if not is_weapon_upgrade(current_type, tid, profile):
                    continue
            # Prefer a materially stronger weapon, but preserve enough travel
            # cost that the agent does not cross the whole screen for a tiny
            # improvement.
            w_bonus = -80.0 * weapon_value(tid, profile)
        elif entity.kind == "pickup":
            fam = entity.family
            if fam in ("Health",) and not allow_health:
                continue
            if fam in ("Life", "Special") and not allow_special_life:
                continue
            w_bonus = 0.0
        else:
            continue
        if graph is not None and not graph.entity_has(entity, Relation.COLLECTIBLE):
            continue
        elif graph is None:
            # Without a graph, still enforce ROM free-ground rules and camera.
            if not entity.is_free_ground_item:
                continue
        # Walk-band ± pickup reach — not the full CRT or the diagnostic view ring.
        if not is_loot_on_camera(entity):
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
    *,
    graph: TacticalKnowledgeGraph | None = None,
) -> MapEntity | None:
    best: MapEntity | None = None
    best_d = 1e9
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if graph is not None and not graph.entity_has(entity, Relation.REACHABLE):
            continue
        if entity.is_defeated:
            continue
        if should_ignore_as_target(entity.combat_phase):
            continue
        if not is_on_screen(entity):
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
        and not e.is_defeated
        and not should_ignore_as_target(e.combat_phase)
        and e.targets_player == seat
        and is_on_screen(e)
    )


def closest_behind(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    face_right: bool,
    max_dist: float = REAR_REACT_RANGE,
    graph: TacticalKnowledgeGraph | None = None,
) -> MapEntity | None:
    """Nearest on-screen foe truly behind us (for turn + back attack)."""

    best: MapEntity | None = None
    best_d = max_dist
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if graph is not None and not graph.entity_has(entity, Relation.REACHABLE):
            continue
        if entity.is_defeated:
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
