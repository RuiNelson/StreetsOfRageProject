"""``generate_decision_tokens`` and its ``could_*`` candidate generators.

Per ``AI.md``, each ``could_*`` function is concerned only with whether a
decision is possible and sensible — never with relative importance across
decisions, which is ``determine_priority_decision``'s job (``priority.py``).
"""

from __future__ import annotations

import math

from ..phases import CombatPhase, should_ignore_as_target
from ..world_map import LANE_Y_MAX_DEFAULT, LANE_Y_MIN, lane_y_max_for_level
from .tokens import (
    CounterGrab,
    FlipHold,
    JumpAttack,
    AttackHeldEnemy,
    Punch,
    RearAttack,
    ReleaseGrab,
    SmashBreakable,
    SprayPepper,
    StabWithKnifeOrBottle,
    Supplex,
    SwingBatOrPipe,
    TechRecover,
    ThrowHeldEnemy,
    ThrowKnife,
    ThrowPepper,
)
from .tokens import (
    MELEE_WEAPON_TYPES,
    Myself,
    Partner,
    PlayableCharacter,
    punch_inner_x,
    punch_outer_x,
    PUNCH_RANGE_Y,
    rear_attack_behind_max_x,
    rear_attack_front_max_x,
)
from .tokens import ClosingEnemy, Enemy
from .tokens import AnimationInProgress, CameraRange, Stage
from .tokens import Breakable
from .tokens import (
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
from .tokens import CallPolice
from .tokens import Context, Token, find, find_all
from .tokens import (
    WalkToAdvanceStage,
    WalkToBreakable,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)

# Police special is scarce (usually 1/life). Only panic-level situations.
POLICE_HEALTH_PERCENT_THRESHOLD = 18.0
# On the last life a KO risks a continue/game-over screen instead of a free
# respawn at full health (player-health-lives-and-combat.md) -- call police
# sooner rather than risk it.
POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE = 35.0

# Jump-kick is a *horizontal* attack — never a stationary hop.
JUMP_ATTACK_MIN_DX = 28  # must leave punch outer / need air travel
# Early-kick free-flight range per character_id (controls-and-input.md
# "Closed-form trajectory summary"): 60/69/75 px -- Axel's real reach is well
# short of Blaze's, so a flat cap either strands Axel mid-air or under-uses
# Blaze's longer kick.
JUMP_ATTACK_MAX_DX_BY_CHARACTER: dict[int, int] = {0: 60, 1: 69, 2: 75}  # Axel, Adam, Blaze
JUMP_ATTACK_MAX_DX_DEFAULT = 72
JUMP_ATTACK_RANGE_Y = 14


def _jump_attack_max_dx(character_id: int | None) -> int:
    if character_id is None:
        return JUMP_ATTACK_MAX_DX_DEFAULT
    return JUMP_ATTACK_MAX_DX_BY_CHARACTER.get(character_id, JUMP_ATTACK_MAX_DX_DEFAULT)


KNIFE_RANGE_X = 90
KNIFE_RANGE_Y = 16
KNIFE_MELEE_X = 40
PEPPER_SPRAY_TYPE = 0x0C

HEALTH_PICKUP_MISSING_MIN = 16
HEALTH_CRITICAL_PERCENT = 40.0

BREAKABLE_PUNCH_X = 36
BREAKABLE_PUNCH_Y = 16
BREAKABLE_BLOCK_X = 28  # treat as path obstacle within this X of the walk line
BREAKABLE_BLOCK_Y = 20
REAR_THREAT_X = 56
REAR_THREAT_Y = 24


def _is_holding_enemy(actor: PlayableCharacter) -> bool:
    held = actor.held_weapon_type
    return held != 0 and not is_weapon_type(held)


def _actors(context: Context) -> list[PlayableCharacter]:
    return [actor for actor in (find(context, Myself), find(context, Partner)) if actor is not None]


def _blocked(context: Context, actor: PlayableCharacter) -> bool:
    return find(context, AnimationInProgress, slot=actor.slot) is not None


def _enemy_behind_actor(actor: PlayableCharacter, enemy: Enemy) -> bool:
    if actor.facing_left:
        return enemy.world_x > actor.world_x
    return enemy.world_x < actor.world_x


def _enemy_in_front(actor: PlayableCharacter, enemy: Enemy) -> bool:
    return not _enemy_behind_actor(actor, enemy)


def _in_punch_band(actor: PlayableCharacter, enemy: Enemy) -> bool:
    dx = abs(enemy.world_x - actor.world_x)
    dy = abs(enemy.world_y - actor.world_y)
    if dy > PUNCH_RANGE_Y:
        return False
    outer = punch_outer_x(actor.character_id, actor.held_weapon_type)
    return punch_inner_x(actor.character_id) <= dx <= outer


def _in_rear_band(actor: PlayableCharacter, enemy: Enemy) -> bool:
    dx = enemy.world_x - actor.world_x
    dy = abs(enemy.world_y - actor.world_y)
    if dy > PUNCH_RANGE_Y:
        return False
    adx = abs(dx)
    if _enemy_behind_actor(actor, enemy):
        return adx <= rear_attack_behind_max_x(actor.character_id)
    return adx <= rear_attack_front_max_x(actor.character_id)


def _in_camera(camera: CameraRange, world_x: int, world_y: int) -> bool:
    return camera.left <= world_x <= camera.right and camera.top <= world_y <= camera.bottom


def _in_playable_lane(world_y: int, context: Context) -> bool:
    """False for an enemy positioned outside the level's actual walkable Y
    band -- e.g. stage 1's scripted "behind a door" placeholder, which is a
    real Enemy object (tracked, health, combat_phase) at an anomalously high
    world_y the player can never physically reach. Without this filter the
    AI repeatedly commits to attacks/chases against a target it can never
    connect with, and it can also block could_walk_to_advance_stage
    forever the same way an abandoned 0-HP straggler does."""

    stage = find(context, Stage)
    lane_max = lane_y_max_for_level(stage.level_index) if stage is not None else LANE_Y_MAX_DEFAULT
    return LANE_Y_MIN <= world_y <= lane_max


def _live_enemies(context: Context) -> list[Enemy]:
    return [
        e
        for e in find_all(context, Enemy)
        if not should_ignore_as_target(e.combat_phase) and _in_playable_lane(e.world_y, context)
    ]


def _on_screen_enemies(context: Context) -> list[Enemy]:
    camera = find(context, CameraRange)
    enemies = _live_enemies(context)
    if camera is None:
        return enemies
    return [e for e in enemies if _in_camera(camera, e.world_x, e.world_y)]


def _rear_threats(actor: PlayableCharacter, enemies: list[Enemy]) -> list[Enemy]:
    return [
        e
        for e in enemies
        if _enemy_behind_actor(actor, e)
        and abs(e.world_x - actor.world_x) <= REAR_THREAT_X
        and abs(e.world_y - actor.world_y) <= REAR_THREAT_Y
    ]


STAB_WEAPON_TYPES = frozenset({0x08, 0x09})  # knife, bottle


def _could_melee_strike(context: Context, *, held_types: frozenset[int] | None, decision_cls) -> Context:
    """Shared body for ``could_punch`` / ``could_swing_bat_or_pipe`` /
    ``could_stab_with_knife_or_bottle`` / ``could_spray_pepper``: they
    issue the identical B-button input (see execute.py's
    ``_execute_melee_strike``), gated only on which weapon type (if any)
    the actor holds. ``held_types=None`` means unarmed (``Punch``)."""

    decisions: set[Token] = set()
    enemies = _live_enemies(context)
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        held_matches = (
            actor.held_weapon_type == 0 if held_types is None else actor.held_weapon_type in held_types
        )
        if not held_matches:
            continue
        for enemy in enemies:
            if _enemy_behind_actor(actor, enemy) and abs(enemy.world_x - actor.world_x) > 4:
                continue
            if _in_punch_band(actor, enemy):
                decisions.add(decision_cls(actor_slot=actor.slot, target_slot=enemy.slot))
    return decisions


def could_punch(context: Context) -> Context:
    return _could_melee_strike(context, held_types=None, decision_cls=Punch)


def could_swing_bat_or_pipe(context: Context) -> Context:
    return _could_melee_strike(context, held_types=MELEE_WEAPON_TYPES, decision_cls=SwingBatOrPipe)


def could_stab_with_knife_or_bottle(context: Context) -> Context:
    return _could_melee_strike(
        context, held_types=STAB_WEAPON_TYPES, decision_cls=StabWithKnifeOrBottle
    )


def could_spray_pepper(context: Context) -> Context:
    return _could_melee_strike(
        context, held_types=frozenset({PEPPER_SPRAY_TYPE}), decision_cls=SprayPepper
    )


def could_rear_attack(context: Context) -> Context:
    decisions: set[Token] = set()
    enemies = _live_enemies(context)
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
            # ClosingEnemy is the early-warning signal from inference.py: an
            # enemy not yet in the instantaneous band but projected to
            # arrive within a few ticks, closing diagonally too fast for a
            # purely position-based check to react in time.
            if _in_rear_band(actor, enemy) or find(context, ClosingEnemy, slot=enemy.slot) is not None:
                decisions.add(RearAttack(actor_slot=actor.slot, target_slot=enemy.slot))
    return decisions


def could_counter_grab(context: Context) -> Context:
    decisions: set[Token] = set()
    for actor in _actors(context):
        if actor.combat_phase is not CombatPhase.HELD_BY_ENEMY:
            continue
        if actor.action_base == 0x7E:
            continue
        decisions.add(CounterGrab(actor_slot=actor.slot))
    return decisions


def could_tech_recover(context: Context) -> Context:
    """Fires precisely inside the C+Up bounce-cancel window
    (controls-and-input.md "C+Up landing tech"). Like ``could_counter_grab``,
    this bypasses the generic ``_blocked`` gate on purpose: the actor is
    airborne/hurt (``HURT_PLAYER``) for this whole window and would
    otherwise never be judged free to act."""

    decisions: set[Token] = set()
    for actor in _actors(context):
        if not actor.throw_tech_ready:
            continue
        decisions.add(TechRecover(actor_slot=actor.slot))
    return decisions


def could_hold_actions(context: Context) -> Context:
    """While grabbing an enemy: knee, throw-back, flip→suplex, or release.

    Never leave the AI idle in a hold — that was a common failure mode.
    """

    decisions: set[Token] = set()
    enemies = _live_enemies(context)
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if not _is_holding_enemy(actor):
            continue
        base = actor.action_base
        # Grab-acquire / mid-throw animations: don't spam new edges.
        if base in (0x28, 0x2A, 0x2C, 0x2E, 0x62, 0x64, 0x68, 0x6A, 0x6C, 0x6E):
            continue

        nearest = None
        if enemies:
            nearest = min(
                enemies,
                key=lambda e: math.hypot(e.world_x - actor.world_x, e.world_y - actor.world_y),
            )
        target_slot = nearest.slot if nearest is not None else actor.slot
        rear = _rear_threats(actor, enemies)

        if base == 0x66:
            # Confirmed back hold → B is suplex.
            decisions.add(Supplex(actor_slot=actor.slot, target_slot=target_slot))
            continue

        if base == 0x60:
            if rear:
                # Throw the held body into the rear threat (B+back).
                decisions.add(ThrowHeldEnemy(actor_slot=actor.slot, target_slot=target_slot))
                # Also offer flip→suplex as alternate (priority decides).
                decisions.add(FlipHold(actor_slot=actor.slot, target_slot=target_slot))
            else:
                # Standard: knee damage, or flip for a suplex finish.
                decisions.add(AttackHeldEnemy(actor_slot=actor.slot, target_slot=target_slot))
                decisions.add(FlipHold(actor_slot=actor.slot, target_slot=target_slot))
            continue

        # Unknown hold-ish state with +$60 non-weapon: still act (knee or release).
        decisions.add(AttackHeldEnemy(actor_slot=actor.slot, target_slot=target_slot))
        if nearest is not None:
            decisions.add(ReleaseGrab(actor_slot=actor.slot, target_slot=target_slot))
    return decisions


def _ahead_in_stage_direction(actor_world_x: int, enemy_world_x: int, direction: str) -> bool:
    if direction == "right":
        return enemy_world_x >= actor_world_x
    if direction == "left":
        return enemy_world_x <= actor_world_x
    return False


def could_walk_to_near_enemy(context: Context) -> Context:
    decisions: set[Token] = set()
    on_screen = _on_screen_enemies(context)
    stage = find(context, Stage)
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        enemies = on_screen
        if not enemies and stage is not None:
            # Nothing on-screen to chase: fall back to the nearest live
            # enemy ahead in the stage's own scroll direction (e.g. the
            # next wave, tracked on the world map but not yet in camera).
            # Never chase one that's behind -- that's the "off-screen
            # leftover" this decision must not walk backward for. Without
            # this fallback, a live off-screen enemy still correctly holds
            # back could_walk_to_advance_stage, but nothing ever moves the
            # camera to bring it into view, and the AI is stuck producing no
            # decision at all.
            enemies = [
                e
                for e in _live_enemies(context)
                if _ahead_in_stage_direction(actor.world_x, e.world_x, stage.direction)
            ]
        if not enemies:
            continue
        if any(_in_punch_band(actor, e) or _in_rear_band(actor, e) for e in enemies):
            continue
        # One candidate per reachable enemy -- determine_priority_decision
        # (priority.py's distance-scored emergency) picks the closest one,
        # per AI.md's own target-selection principle: this function only
        # says what's possible, never which possibility is best.
        for enemy in enemies:
            decisions.add(WalkToNearEnemy(actor_slot=actor.slot, target_slot=enemy.slot))
    return decisions


def _advance_blocking_enemies(context: Context) -> list[Enemy]:
    """Live enemies that should hold back stage advance.

    Almost every live enemy counts, on-screen or not (see
    ``could_walk_to_advance_stage``) -- except an off-screen enemy already
    at exactly 0 health. Per ``world_map.MapEntity.is_defeated``'s own note,
    zero health is not yet ``is_defeated`` -- the ROM still counts it alive
    and wants one more "finishing" hit -- but ``could_walk_to_near_enemy``
    never chases an off-screen target, so nothing in this pipeline will ever
    deliver that hit. Without this carve-out such a straggler blocks stage
    advance forever, which contradicts ``could_walk_to_near_enemy``'s own
    on-screen-only design intent ("so off-screen leftovers don't block
    stage advance forever").
    """

    camera = find(context, CameraRange)
    blocking = []
    for enemy in _live_enemies(context):
        if (
            camera is not None
            and not _in_camera(camera, enemy.world_x, enemy.world_y)
            and enemy.health == 0
        ):
            continue
        blocking.append(enemy)
    return blocking


def could_walk_to_advance_stage(context: Context) -> Context:
    """Scroll the stage only once every spawned enemy is gone.

    Gated on every live Enemy token, not just on-screen ones: an enemy that
    has already spawned off-screen (about to walk/scroll into view) is still
    a reason to hold position, not a "next wave cue" to push past. The one
    exception is an off-screen enemy already at 0 health -- see
    ``_advance_blocking_enemies``.
    """

    decisions: set[Token] = set()
    stage = find(context, Stage)
    if stage is None or stage.direction == "none":
        return decisions
    if _advance_blocking_enemies(context):
        return decisions
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        decisions.add(WalkToAdvanceStage(actor_slot=actor.slot, direction=stage.direction))
    return decisions


def could_call_police(context: Context) -> Context:
    decisions: set[Token] = set()
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.specials <= 0:
            continue
        threshold = (
            POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE
            if actor.lives <= 1
            else POLICE_HEALTH_PERCENT_THRESHOLD
        )
        if actor.health_percent >= threshold:
            continue
        decisions.add(CallPolice(actor_slot=actor.slot))
    return decisions


def could_jump_attack(context: Context) -> Context:
    """Jump-kick only when a horizontal approach is useful — never hop in place."""

    decisions: set[Token] = set()
    enemies = _on_screen_enemies(context)
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
            dx = abs(enemy.world_x - actor.world_x)
            dy = abs(enemy.world_y - actor.world_y)
            if dy > JUMP_ATTACK_RANGE_Y:
                continue
            # Must need the air approach: outside punch outer, with real ΔX.
            if dx < max(JUMP_ATTACK_MIN_DX, punch_outer_x(actor.character_id)):
                continue
            if dx > _jump_attack_max_dx(actor.character_id):
                continue
            # Only kick forward — jump-in-place facing wrong way is useless.
            if not _enemy_in_front(actor, enemy):
                continue
            decisions.add(JumpAttack(actor_slot=actor.slot, target_slot=enemy.slot))
    return decisions


def _could_throw_ranged_weapon(context: Context, *, weapon_type: int, decision_cls) -> Context:
    """Shared body for ``could_throw_knife`` / ``could_throw_pepper``: one
    candidate per on-screen enemy beyond melee but within throw range --
    never just the nearest. determine_priority_decision (priority.py's
    distance-scored emergency) picks which one actually gets thrown at."""

    decisions: set[Token] = set()
    enemies = _on_screen_enemies(context)
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        if actor.held_weapon_type != weapon_type:
            continue
        for enemy in enemies:
            in_melee_range = (
                abs(enemy.world_x - actor.world_x) <= KNIFE_MELEE_X
                and abs(enemy.world_y - actor.world_y) <= KNIFE_RANGE_Y
            )
            if in_melee_range:
                continue
            if (
                abs(enemy.world_x - actor.world_x) <= KNIFE_RANGE_X
                and abs(enemy.world_y - actor.world_y) <= KNIFE_RANGE_Y
            ):
                decisions.add(decision_cls(actor_slot=actor.slot, target_slot=enemy.slot))
    return decisions


def could_throw_knife(context: Context) -> Context:
    return _could_throw_ranged_weapon(context, weapon_type=0x08, decision_cls=ThrowKnife)


def could_throw_pepper(context: Context) -> Context:
    """Mirrors ``could_throw_knife``'s range gating: items-and-weapons.md
    confirms pepper spray is also attack-thrown (``$21E6``, command 3), but
    its own effective throw range has not been separately measured, so this
    reuses ``KNIFE_MELEE_X``/``KNIFE_RANGE_X``/``KNIFE_RANGE_Y`` as the
    closest available evidence."""

    return _could_throw_ranged_weapon(context, weapon_type=PEPPER_SPRAY_TYPE, decision_cls=ThrowPepper)


def could_walk_to_weapon(context: Context) -> Context:
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
        if _is_holding_enemy(actor):
            continue
        held_rank = weapon_rank(actor.held_weapon_type)
        upgrades = [w for w in weapons if weapon_rank(w.weapon_type) > held_rank]
        # One candidate per upgrade -- priority.py's rank-scaled emergency
        # favors the better upgrade, not a min/max pick made here.
        for weapon in upgrades:
            decisions.add(WalkToWeapon(actor_slot=actor.slot, target_slot=weapon.slot))
    return decisions


def _pickup_is_useful(actor: PlayableCharacter, pickup: Pickup) -> bool:
    if isinstance(pickup, HealthPickup):
        missing = PLAYER_MAX_HEALTH - actor.health
        if missing <= 0:
            return False
        if actor.health_percent < HEALTH_CRITICAL_PERCENT:
            return True
        return missing >= min(HEALTH_PICKUP_MISSING_MIN, pickup.health_delta)
    if isinstance(pickup, LifePickup):
        return True
    if isinstance(pickup, SpecialPickup):
        return actor.specials < 3
    if isinstance(pickup, ScorePickup):
        return True
    return False


def could_walk_to_pickup(context: Context) -> Context:
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
        if _is_holding_enemy(actor):
            continue
        useful = [p for p in pickups if _pickup_is_useful(actor, p)]
        # One candidate per useful pickup -- priority.py's per-target
        # _emergency_walk_to_pickup already ranks by type/urgency, so no
        # selection belongs here.
        for pickup in useful:
            decisions.add(WalkToPickup(actor_slot=actor.slot, target_slot=pickup.slot))
    return decisions


def could_smash_breakable(context: Context) -> Context:
    decisions: set[Token] = set()
    camera = find(context, CameraRange)
    breakables = find_all(context, Breakable)
    if camera is not None:
        breakables = [b for b in breakables if _in_camera(camera, b.world_x, b.world_y)]
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        for prop in breakables:
            if (
                abs(prop.world_x - actor.world_x) <= BREAKABLE_PUNCH_X
                and abs(prop.world_y - actor.world_y) <= BREAKABLE_PUNCH_Y
            ):
                decisions.add(SmashBreakable(actor_slot=actor.slot, target_slot=prop.slot))
    return decisions


def could_walk_to_breakable(context: Context) -> Context:
    """Approach breakables that block forward stage progress."""

    decisions: set[Token] = set()
    stage = find(context, Stage)
    camera = find(context, CameraRange)
    breakables = find_all(context, Breakable)
    if camera is not None:
        breakables = [b for b in breakables if _in_camera(camera, b.world_x, b.world_y)]
    if not breakables:
        return decisions
    for actor in _actors(context):
        if _blocked(context, actor):
            continue
        if actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
            continue
        if _is_holding_enemy(actor):
            continue
        # Prefer props ahead on the stage path.
        ahead = breakables
        if stage is not None and stage.direction == "right":
            ahead = [b for b in breakables if b.world_x >= actor.world_x - 8]
        elif stage is not None and stage.direction == "left":
            ahead = [b for b in breakables if b.world_x <= actor.world_x + 8]
        if not ahead:
            ahead = breakables
        # Skip if already in smash range (SmashBreakable owns that).
        candidates = [
            b
            for b in ahead
            if not (
                abs(b.world_x - actor.world_x) <= BREAKABLE_PUNCH_X
                and abs(b.world_y - actor.world_y) <= BREAKABLE_PUNCH_Y
            )
        ]
        # One candidate per reachable breakable -- priority.py's distance-
        # bucketed emergency picks the closest one.
        for prop in candidates:
            decisions.add(WalkToBreakable(actor_slot=actor.slot, target_slot=prop.slot))
    return decisions


def generate_decision_tokens(context: Context) -> Context:
    """Returns context | every could_* candidate that applies."""

    return (
        context
        | could_counter_grab(context)
        | could_tech_recover(context)
        | could_hold_actions(context)
        | could_walk_to_near_enemy(context)
        | could_walk_to_advance_stage(context)
        | could_punch(context)
        | could_swing_bat_or_pipe(context)
        | could_stab_with_knife_or_bottle(context)
        | could_spray_pepper(context)
        | could_rear_attack(context)
        | could_call_police(context)
        | could_jump_attack(context)
        | could_throw_knife(context)
        | could_throw_pepper(context)
        | could_walk_to_weapon(context)
        | could_walk_to_pickup(context)
        | could_smash_breakable(context)
        | could_walk_to_breakable(context)
    )
