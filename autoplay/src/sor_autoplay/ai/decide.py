"""``generate_decision_tokens`` and its ``should_*`` candidate generators.

Per ``AI.md``, each ``should_*`` function is concerned only with whether a
decision is possible and sensible — never with relative importance across
decisions, which is ``determine_priority_decision``'s job (``priority.py``).
Multiple qualifying candidates of the same decision type (e.g. two ``Punch``
candidates against two different enemies) are all emitted; nothing here picks
a "best" one.

Ranges and input contracts come from ``ai-analysis``:

- punch inner/outer boxes: ``controls-and-input.md`` (per character)
- weapon damage rank: ``items-and-weapons.md`` (knife 5 > bat/pipe 4 > …)
- pickup search box ``$3136``: ±20 X, ±16 lane Y
- rear attack B+C: ``$322A``
- enemy-held counter C then B: ``controls-and-input.md`` hold section
"""

from __future__ import annotations

import math

from ..phases import CombatPhase, is_dangerous, should_ignore_as_target
from .attack_decisions import (
    CounterGrab,
    JumpAttack,
    Punch,
    RearAttack,
    Supplex,
    ThrowKnife,
)
from .character import (
    Myself,
    Partner,
    PlayableCharacter,
    punch_inner_x,
    punch_outer_x,
    PUNCH_RANGE_Y,
)
from .enemy import Enemy
from .essential import AnimationInProgress, CameraRange, Stage
from .hazard_tokens import DangerZone, IncomingProjectile
from .pickup_tokens import (
    PLAYER_MAX_HEALTH,
    HealthPickup,
    LifePickup,
    Pickup,
    ScorePickup,
    SpecialPickup,
    Weapon,
    is_weapon_type,
    weapon_rank,
)
from .police_decision import CallPolice
from .tokens import Context, Token, find, find_all
from .walk_decisions import (
    Sidestep,
    WalkToAdvanceStage,
    WalkToCoordinate,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)

# Placeholder heuristic thresholds, subject to future tuning against real
# gameplay.
CAUTION_RANGE_X = 40
CAUTION_RANGE_Y = 24
POLICE_HEALTH_PERCENT_THRESHOLD = 25.0
POLICE_DANGER_THRESHOLD = 3
POLICE_LOW_HEALTH_DANGER_THRESHOLD = 1

JUMP_ATTACK_RANGE_X = 56  # jump-kick horizontal reach ~54–75 px (controls ms)
JUMP_ATTACK_RANGE_Y = 16
# Knife throw cone (items-and-weapons.md): |ΔX| < $90 (144), lane ±12 — use a
# conservative AI band so we don't throw into empty space at max ROM range.
KNIFE_RANGE_X = 90
KNIFE_RANGE_Y = 16
# Knife melee-vs-throw decision in ROM: foe in front |ΔX| < 144. Prefer melee
# (Punch path while holding knife) inside this band; ThrowKnife outside it.
KNIFE_MELEE_X = 40
DANGER_ZONE_RETREAT_THRESHOLD = 4
PROJECTILE_DODGE_TICKS = 20  # ~0.33s at 60fps -- placeholder, tunable

# Health food is worth walking to once missing at least this much of a bar.
# Small apple is +20, so below 60/80 we can fully use one; full food always
# helps when not full.
HEALTH_PICKUP_MISSING_MIN = 16  # slightly under a fifth of max health
# Prefer health items aggressively under this percent.
HEALTH_CRITICAL_PERCENT = 40.0


def _is_holding_enemy(actor: PlayableCharacter) -> bool:
    held = actor.held_weapon_type
    return held != 0 and not is_weapon_type(held)


def _actors(context: Context) -> list[PlayableCharacter]:
    return [actor for actor in (find(context, Myself), find(context, Partner)) if actor is not None]


def _blocked(context: Context, actor: PlayableCharacter) -> bool:
    return find(context, AnimationInProgress, slot=actor.slot) is not None


def _is_facing(enemy: Enemy, target_world_x: int) -> bool:
    return target_world_x <= enemy.world_x if enemy.facing_left else target_world_x >= enemy.world_x


def _enemy_behind_actor(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """True when the enemy sits on the player's back side (rear-attack box)."""

    if actor.facing_left:
        return enemy.world_x > actor.world_x
    return enemy.world_x < actor.world_x


def _in_punch_band(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """True when the enemy is inside the punch attack box, not the dead zone.

    Measured punch boxes (controls-and-input.md) have an *inner* edge: a body
    that has closed inside +16 (Axel) / +8 (Adam) / +18 (Blaze) is never hit.
    """

    dx = abs(enemy.world_x - actor.world_x)
    dy = abs(enemy.world_y - actor.world_y)
    if dy > PUNCH_RANGE_Y:
        return False
    inner = punch_inner_x(actor.character_id)
    outer = punch_outer_x(actor.character_id)
    return inner <= dx <= outer


def _in_rear_band(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """True when a rear/escape chord can connect (behind or overlapping).

    Axel rear box X −40..−8; Blaze −53..−5; Adam hop −42..+14. Use a shared
    band that covers the overlap/behind case where a forward punch fails.
    """

    dx = enemy.world_x - actor.world_x
    dy = abs(enemy.world_y - actor.world_y)
    if dy > PUNCH_RANGE_Y + 4:
        return False
    # Absolute separation: on top of the player, or just behind.
    adx = abs(dx)
    if adx > 48:
        return False
    # Prefer rear when behind, or when inside the forward punch dead zone.
    if _enemy_behind_actor(actor, enemy):
        return adx <= 48
    return adx < punch_inner_x(actor.character_id)


def _is_close_and_facing_caution(enemy: Enemy, actor: PlayableCharacter) -> bool:
    return (
        enemy.combat_phase is CombatPhase.UNKNOWN
        and abs(enemy.world_x - actor.world_x) <= CAUTION_RANGE_X
        and abs(enemy.world_y - actor.world_y) <= CAUTION_RANGE_Y
        and _is_facing(enemy, actor.world_x)
    )


def _in_camera(camera: CameraRange, world_x: int, world_y: int) -> bool:
    return camera.left <= world_x <= camera.right and camera.top <= world_y <= camera.bottom


def should_punch(context: Context) -> Context:
    decisions: set[Token] = set()
    enemies = [e for e in find_all(context, Enemy) if not should_ignore_as_target(e.combat_phase)]
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        for enemy in enemies:
            # Only punch targets roughly in front; rear is RearAttack's job.
            if _enemy_behind_actor(actor, enemy) and abs(enemy.world_x - actor.world_x) > 4:
                continue
            if _in_punch_band(actor, enemy):
                decisions.add(Punch(actor_slot=actor.slot, target_slot=enemy.slot))
    return decisions


def should_rear_attack(context: Context) -> Context:
    """B+C rear/escape when a close foe is behind or inside the punch dead zone."""

    decisions: set[Token] = set()
    enemies = [e for e in find_all(context, Enemy) if not should_ignore_as_target(e.combat_phase)]
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.is_airborne:
            continue
        for enemy in enemies:
            if _in_rear_band(actor, enemy):
                decisions.add(RearAttack(actor_slot=actor.slot, target_slot=enemy.slot))
    return decisions


def should_counter_grab(context: Context) -> Context:
    """Enemy-held counter sequence (C crossover, then B throw).

    Does not require AnimationInProgress absence — observe treats
    HELD_BY_ENEMY as free-to-act so this can fire.
    """

    decisions: set[Token] = set()
    for actor in _actors(context):
        if actor.combat_phase is not CombatPhase.HELD_BY_ENEMY:
            continue
        # $7E is already the counter throw animation — no new edge needed.
        if actor.action_base == 0x7E:
            continue
        decisions.add(CounterGrab(actor_slot=actor.slot))
    return decisions


def should_walk_to_near_enemy(context: Context) -> Context:
    decisions: set[Token] = set()
    enemies = [e for e in find_all(context, Enemy) if not should_ignore_as_target(e.combat_phase)]
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if not enemies:
            continue
        # Already in a connectable band — let attack decisions own this tick.
        if any(_in_punch_band(actor, e) or _in_rear_band(actor, e) for e in enemies):
            continue
        nearest = min(
            enemies,
            key=lambda e: math.hypot(e.world_x - actor.world_x, e.world_y - actor.world_y),
        )
        decisions.add(WalkToNearEnemy(actor_slot=actor.slot, target_slot=nearest.slot))
    return decisions


def should_walk_to_advance_stage(context: Context) -> Context:
    """Progress the stage when there is nothing else to fight.

    Only sensible when no live enemy is on screen -- should_walk_to_near_enemy
    already covers the case where one exists, so this and that function are
    mutually exclusive by construction and never compete for the same actor.
    """

    decisions: set[Token] = set()
    stage = find(context, Stage)
    if stage is None or stage.direction == "none":
        return decisions
    enemies = [e for e in find_all(context, Enemy) if not should_ignore_as_target(e.combat_phase)]
    if enemies:
        return decisions
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        decisions.add(WalkToAdvanceStage(actor_slot=actor.slot, direction=stage.direction))
    return decisions


def should_sidestep(context: Context) -> Context:
    decisions: set[Token] = set()
    enemies = find_all(context, Enemy)
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        for enemy in enemies:
            if enemy.targets_player != actor.player_index:
                continue
            # CombatPhase.UNKNOWN on a nearby, player-facing enemy means
            # "insufficient information," never "safe" — treat it with the
            # same caution as a confirmed-dangerous phase.
            if is_dangerous(enemy.combat_phase) or _is_close_and_facing_caution(enemy, actor):
                direction = "up" if enemy.world_y > actor.world_y else "down"
                decisions.add(Sidestep(actor_slot=actor.slot, threat_slot=enemy.slot, direction=direction))
    return decisions


def should_call_police(context: Context) -> Context:
    decisions: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if actor.specials <= 0:
            continue
        danger = find(context, DangerZone, slot=actor.slot)
        if danger is None:
            continue
        if danger.threat_level >= POLICE_DANGER_THRESHOLD or (
            actor.health_percent < POLICE_HEALTH_PERCENT_THRESHOLD
            and danger.threat_level >= POLICE_LOW_HEALTH_DANGER_THRESHOLD
        ):
            decisions.add(CallPolice(actor_slot=actor.slot))
    return decisions


def should_supplex(context: Context) -> Context:
    decisions: set[Token] = set()
    enemies = [e for e in find_all(context, Enemy) if not should_ignore_as_target(e.combat_phase)]
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if not _is_holding_enemy(actor):
            continue
        if not enemies:
            continue
        nearest = min(
            enemies,
            key=lambda e: math.hypot(e.world_x - actor.world_x, e.world_y - actor.world_y),
        )
        decisions.add(Supplex(actor_slot=actor.slot, target_slot=nearest.slot))
    return decisions


def should_jump_attack(context: Context) -> Context:
    decisions: set[Token] = set()
    enemies = [e for e in find_all(context, Enemy) if not should_ignore_as_target(e.combat_phase)]
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.is_airborne:
            continue
        for enemy in enemies:
            if (
                abs(enemy.world_x - actor.world_x) <= JUMP_ATTACK_RANGE_X
                and abs(enemy.world_y - actor.world_y) <= JUMP_ATTACK_RANGE_Y
            ):
                # Prefer jump-kick against mid-range packs / punishable foes
                # just outside punch outer — not point-blank (punch is faster).
                dx = abs(enemy.world_x - actor.world_x)
                if dx < punch_outer_x(actor.character_id):
                    continue
                decisions.add(JumpAttack(actor_slot=actor.slot, target_slot=enemy.slot))
    return decisions


def should_throw_knife(context: Context) -> Context:
    decisions: set[Token] = set()
    enemies = [e for e in find_all(context, Enemy) if not should_ignore_as_target(e.combat_phase)]
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.held_weapon_type != 0x08:
            continue
        if not enemies:
            continue
        nearest = min(
            enemies,
            key=lambda e: math.hypot(e.world_x - actor.world_x, e.world_y - actor.world_y),
        )
        # ROM: knife B is melee ($46) when a foe is in the front cone; throw
        # ($44) otherwise. Prefer not emitting ThrowKnife inside melee band —
        # Punch/held attack covers that path with the same B edge.
        in_melee_range = (
            abs(nearest.world_x - actor.world_x) <= KNIFE_MELEE_X
            and abs(nearest.world_y - actor.world_y) <= KNIFE_RANGE_Y
        )
        if in_melee_range:
            continue
        if (
            abs(nearest.world_x - actor.world_x) <= KNIFE_RANGE_X
            and abs(nearest.world_y - actor.world_y) <= KNIFE_RANGE_Y
        ):
            decisions.add(ThrowKnife(actor_slot=actor.slot, target_slot=nearest.slot))
    return decisions


def should_walk_to_weapon(context: Context) -> Context:
    decisions: set[Token] = set()
    camera = find(context, CameraRange)
    if camera is None:
        return decisions
    weapons = [
        w
        for w in find_all(context, Weapon)
        if _in_camera(camera, w.world_x, w.world_y) and w.wear < 3
    ]
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        held_rank = weapon_rank(actor.held_weapon_type)
        upgrades = [w for w in weapons if weapon_rank(w.weapon_type) > held_rank]
        if not upgrades:
            continue
        best = max(upgrades, key=lambda w: weapon_rank(w.weapon_type))
        decisions.add(WalkToWeapon(actor_slot=actor.slot, target_slot=best.slot))
    return decisions


def _pickup_is_useful(actor: PlayableCharacter, pickup: Pickup) -> bool:
    """Whether collecting this consumable makes sense for this actor now."""

    if isinstance(pickup, HealthPickup):
        missing = PLAYER_MAX_HEALTH - actor.health
        if missing <= 0:
            return False
        # Always take food when critical; otherwise require room for most of it.
        if actor.health_percent < HEALTH_CRITICAL_PERCENT:
            return True
        return missing >= min(HEALTH_PICKUP_MISSING_MIN, pickup.health_delta)
    if isinstance(pickup, LifePickup):
        return True
    if isinstance(pickup, SpecialPickup):
        # Round 8 forces specials to 0 at spawn; still useful if already 0 mid-run.
        return actor.specials < 3
    if isinstance(pickup, ScorePickup):
        # Low urgency — only when nothing dangerous is pressing (caller still
        # emits; emergency ranking keeps it behind combat).
        return True
    return False


def should_walk_to_pickup(context: Context) -> Context:
    decisions: set[Token] = set()
    camera = find(context, CameraRange)
    if camera is None:
        return decisions
    pickups = [
        p for p in find_all(context, Pickup) if _in_camera(camera, p.world_x, p.world_y)
    ]
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        useful = [p for p in pickups if _pickup_is_useful(actor, p)]
        if not useful:
            continue
        # Prefer health when hurt, then life, special, score.
        def _rank(p: Pickup) -> tuple[int, int]:
            if isinstance(p, HealthPickup):
                urgency = 3 if actor.health_percent < HEALTH_CRITICAL_PERCENT else 2
                return (urgency, p.health_delta)
            if isinstance(p, LifePickup):
                return (2, 0)
            if isinstance(p, SpecialPickup):
                return (1, 0)
            if isinstance(p, ScorePickup):
                return (0, p.points)
            return (0, 0)

        best = max(
            useful,
            key=lambda p: (
                _rank(p),
                -math.hypot(p.world_x - actor.world_x, p.world_y - actor.world_y),
            ),
        )
        decisions.add(WalkToPickup(actor_slot=actor.slot, target_slot=best.slot))
    return decisions


def should_retreat_from_danger_zone(context: Context) -> Context:
    decisions: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        zone = find(context, DangerZone, slot=actor.slot)
        if zone is None or zone.threat_level < DANGER_ZONE_RETREAT_THRESHOLD:
            continue
        centroid_x = (zone.left + zone.right) / 2
        centroid_y = (zone.top + zone.bottom) / 2
        target_x = actor.world_x + (actor.world_x - centroid_x)
        target_y = actor.world_y + (actor.world_y - centroid_y)
        decisions.add(WalkToCoordinate(actor_slot=actor.slot, target_x=int(target_x), target_y=int(target_y)))
    return decisions


def should_dodge_projectile(context: Context) -> Context:
    decisions: set[Token] = set()
    projectiles = find_all(context, IncomingProjectile)
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        for projectile in projectiles:
            if projectile.vel_x == 0:
                # Vertical/static hazard: step in Y away from its lane.
                if abs(projectile.world_x - actor.world_x) > CAUTION_RANGE_X:
                    continue
                direction = "up" if projectile.world_y >= actor.world_y else "down"
                decisions.add(
                    Sidestep(actor_slot=actor.slot, threat_slot=projectile.slot, direction=direction)
                )
                continue
            dx = projectile.world_x - actor.world_x
            heading_toward = (dx > 0 and projectile.vel_x < 0) or (dx < 0 and projectile.vel_x > 0)
            if not heading_toward:
                continue
            ticks_to_impact = abs(dx) / abs(projectile.vel_x)
            if ticks_to_impact > PROJECTILE_DODGE_TICKS:
                continue
            if abs(projectile.world_y - actor.world_y) > CAUTION_RANGE_Y:
                continue
            direction = "up" if projectile.world_y > actor.world_y else "down"
            decisions.add(Sidestep(actor_slot=actor.slot, threat_slot=projectile.slot, direction=direction))
    return decisions


def generate_decision_tokens(context: Context) -> Context:
    """Returns context | every should_* candidate that applies."""

    return (
        context
        | should_counter_grab(context)
        | should_walk_to_near_enemy(context)
        | should_walk_to_advance_stage(context)
        | should_sidestep(context)
        | should_punch(context)
        | should_rear_attack(context)
        | should_call_police(context)
        | should_supplex(context)
        | should_jump_attack(context)
        | should_throw_knife(context)
        | should_walk_to_weapon(context)
        | should_walk_to_pickup(context)
        | should_retreat_from_danger_zone(context)
        | should_dodge_projectile(context)
    )
