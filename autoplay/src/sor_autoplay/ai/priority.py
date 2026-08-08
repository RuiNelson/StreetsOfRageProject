"""``determine_priority_decision`` — rank ``Decision`` tokens by emergency.

Per ``AI.md``: this also performs target selection, since ranking by
emergency and keeping only the highest-ranked ``Decision`` is what collapses
several same-type candidates (e.g. a ``Punch`` against each of two nearby
enemies) down to one.
"""

from __future__ import annotations

import logging
import math
import random

from .attack_decisions import (
    CounterGrab,
    FlipHold,
    JumpAttack,
    KneeStrike,
    Punch,
    RearAttack,
    ReleaseGrab,
    SmashBreakable,
    Supplex,
    ThrowHeldEnemy,
    ThrowKnife,
)
from .character import Myself, Partner, PlayableCharacter
from .enemy import Enemy, Jack
from .hazard_tokens import IncomingProjectile
from .pickup_tokens import (
    HealthPickup,
    LifePickup,
    Pickup,
    ScorePickup,
    SpecialPickup,
    is_weapon_type,
    weapon_rank,
)
from .police_decision import CallPolice
from .tokens import Context, Decision, find, find_all
from .walk_decisions import (
    Sidestep,
    WalkToAdvanceStage,
    WalkToBreakable,
    WalkToCoordinate,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from ..phases import is_dangerous, is_punishable

logger = logging.getLogger(__name__)

# 0-100 emergency scale. Sidestep scores are *graded* inside their band so
# two Sidesteps almost never share the same integer (distance, rear, type…).
# Cap at 99 so CounterGrab (100) always outranks pure evasion.
_EMERGENCY_COUNTER_GRAB = 100  # already held — only useful action
# Sidestep bases are low enough that proximity/rear/type bonuses still
# differentiate under the 99 cap (CounterGrab stays strictly above).
_EMERGENCY_SIDESTEP_DANGEROUS_BASE = 72
_EMERGENCY_SIDESTEP_CAUTION_BASE = 58
_EMERGENCY_SIDESTEP_PROJECTILE_BASE = 80
_EMERGENCY_SIDESTEP_UNRESOLVED = 55
_EMERGENCY_SIDESTEP_MAX = 99
# Police only after graded sidesteps would already have fired; keep high but
# decide.py gates emission tightly so this rarely appears.
_EMERGENCY_CALL_POLICE = 88
_EMERGENCY_REAR_ATTACK = 55  # escape when boxed in / punch dead-zone
_EMERGENCY_PUNCH_PUNISHABLE = 60
_EMERGENCY_PUNCH_DEFAULT = 20
_EMERGENCY_HOLD_THROW = 70  # throw held body into rear threat
_EMERGENCY_HOLD_SUPPLEX = 68
_EMERGENCY_HOLD_FLIP = 66
_EMERGENCY_HOLD_KNEE = 64
_EMERGENCY_HOLD_RELEASE = 50
_EMERGENCY_JUMP_ATTACK_PUNISHABLE = 28  # below punch; never prefer hop over strike
_EMERGENCY_JUMP_ATTACK_DEFAULT = 18
_EMERGENCY_THROW_KNIFE = 25
_EMERGENCY_RETREAT_FROM_DANGER = 45
_EMERGENCY_SMASH_BREAKABLE = 16
_EMERGENCY_WALK_TO_BREAKABLE = 14
_EMERGENCY_WALK_TO_WEAPON = 8
_EMERGENCY_WALK_TO_PICKUP_CRITICAL_HEALTH = 50
_EMERGENCY_WALK_TO_PICKUP_HEALTH = 15
_EMERGENCY_WALK_TO_PICKUP_LIFE = 12
_EMERGENCY_WALK_TO_PICKUP_SPECIAL = 9
_EMERGENCY_WALK_TO_PICKUP_SCORE = 3
_EMERGENCY_WALK_TO_NEAR_ENEMY = 14
# Clear camera → push stage (was 5; only emitted when no on-screen enemies).
_EMERGENCY_WALK_TO_ADVANCE_STAGE = 12
_EMERGENCY_DEFAULT = 0

# enemy-ai.md combat-table flavour: bosses / Jack / Signal hit harder or grab.
_ENEMY_TYPE_URGENCY: dict[int, int] = {
    0x20: 1,
    0x21: 1,
    0x22: 1,
    0x23: 2,
    0x24: 3,  # Signal — slides, throws from behind
    0x25: 2,
    0x2A: 2,
    0x26: 2,  # Nora whip
    0x27: 3,  # Jack
    0x30: 5,
    0x35: 5,
    0x55: 5,
    0x56: 5,
    0x57: 5,
    0x58: 5,
}


def _find_actor(context: Context, slot: str) -> Myself | Partner | None:
    for actor in (find(context, Myself), find(context, Partner)):
        if actor is not None and actor.slot == slot:
            return actor
    return None


def _enemy_behind_actor(actor: PlayableCharacter, enemy: Enemy) -> bool:
    """True when the threat sits on the player's back side (facing bit 0)."""

    if actor.facing_left:
        return enemy.world_x > actor.world_x
    return enemy.world_x < actor.world_x


def _enemy_facing_actor(enemy: Enemy, actor: PlayableCharacter) -> bool:
    return (
        actor.world_x <= enemy.world_x
        if enemy.facing_left
        else actor.world_x >= enemy.world_x
    )


def _proximity_bonus(distance: float, *, max_bonus: int = 12, step_px: float = 6.0) -> int:
    """Higher when closer. Full bonus inside ``step_px``; zero past ``max_bonus * step_px``."""

    if distance <= 0:
        return max_bonus
    return max(0, max_bonus - int(distance // step_px))


def _player_weapon_vulnerability(actor: PlayableCharacter) -> int:
    """Unarmed players need the dodge more; long melee still wants space."""

    held = actor.held_weapon_type & 0xFF
    if held == 0 or not is_weapon_type(held):
        # Unarmed, or holding an enemy (shouldn't sidestep mid-hold often).
        return 2 if held == 0 else 0
    rank = weapon_rank(held)
    # Knife/pepper (rank 5/2) have a throw option — slightly less dodge urgency.
    if held in (0x08, 0x0C):
        return 0
    # Bat/pipe/bottle: still want lane space before the swing.
    return 1 if rank >= 3 else 1


def _sidestep_emergency(decision: Sidestep, context: Context) -> int:
    """Grade a Sidestep so two threats almost never share an emergency value.

    Contributors (enemy threats):
    - base band from combat phase (dangerous vs caution vs unresolved)
    - proximity (closer → higher)
    - rear of player (strong boost — cannot answer with a forward punch)
    - enemy facing the player
    - type urgency (Jack / Signal / bosses)
    - enemy-held weapon (Jack axe attached)
    - player weapon state (unarmed needs the step more)
    """

    actor = _find_actor(context, decision.actor_slot)
    enemy = find(context, Enemy, slot=decision.threat_slot)
    if enemy is None:
        projectile = find(context, IncomingProjectile, slot=decision.threat_slot)
        if projectile is None:
            return _EMERGENCY_SIDESTEP_UNRESOLVED
        return _projectile_sidestep_emergency(decision, actor, projectile)

    if is_dangerous(enemy.combat_phase):
        score = _EMERGENCY_SIDESTEP_DANGEROUS_BASE
    else:
        score = _EMERGENCY_SIDESTEP_CAUTION_BASE

    if actor is not None:
        dist = math.hypot(enemy.world_x - actor.world_x, enemy.world_y - actor.world_y)
        score += _proximity_bonus(dist, max_bonus=8, step_px=8.0)
        # Rear threats outrank same-distance frontal ones (primary user request).
        if _enemy_behind_actor(actor, enemy):
            score += 6
        if _enemy_facing_actor(enemy, actor):
            score += 2
        score += _player_weapon_vulnerability(actor)
        # Micro-break near-identical geometry: prefer the foe slightly closer on X.
        score += max(0, 1 - min(1, abs(enemy.world_x - actor.world_x) // 48))
    else:
        score += 3  # no actor — still treat as mid urgency

    score += _ENEMY_TYPE_URGENCY.get(enemy.type_id & 0xFF, 1)
    if isinstance(enemy, Jack) and enemy.has_projectile:
        score += 3

    return min(_EMERGENCY_SIDESTEP_MAX, score)


def _projectile_sidestep_emergency(
    decision: Sidestep,
    actor: PlayableCharacter | None,
    projectile: IncomingProjectile,
) -> int:
    score = _EMERGENCY_SIDESTEP_PROJECTILE_BASE
    if actor is None:
        return min(_EMERGENCY_SIDESTEP_MAX, score + 4)

    dx = abs(projectile.world_x - actor.world_x)
    dy = abs(projectile.world_y - actor.world_y)
    dist = math.hypot(dx, dy)
    score += _proximity_bonus(dist, max_bonus=10, step_px=8.0)
    if projectile.vel_x != 0:
        ticks = dx / abs(projectile.vel_x)
        # Imminent impact (≤5 ticks) → +5; far → 0.
        score += max(0, 5 - int(ticks // 2))
    score += _player_weapon_vulnerability(actor)
    return min(_EMERGENCY_SIDESTEP_MAX, score)


def _pickup_emergency(decision: WalkToPickup, context: Context) -> int:
    pickup = find(context, Pickup, slot=decision.target_slot)
    actor = _find_actor(context, decision.actor_slot)
    if pickup is None:
        return _EMERGENCY_WALK_TO_PICKUP_SCORE
    if isinstance(pickup, HealthPickup):
        if actor is not None and actor.health_percent < 40.0:
            return _EMERGENCY_WALK_TO_PICKUP_CRITICAL_HEALTH
        return _EMERGENCY_WALK_TO_PICKUP_HEALTH
    if isinstance(pickup, LifePickup):
        return _EMERGENCY_WALK_TO_PICKUP_LIFE
    if isinstance(pickup, SpecialPickup):
        return _EMERGENCY_WALK_TO_PICKUP_SPECIAL
    if isinstance(pickup, ScorePickup):
        return _EMERGENCY_WALK_TO_PICKUP_SCORE
    return _EMERGENCY_WALK_TO_PICKUP_SCORE


def _emergency(decision: Decision, context: Context) -> int:
    if isinstance(decision, CounterGrab):
        return _EMERGENCY_COUNTER_GRAB
    if isinstance(decision, Sidestep):
        return _sidestep_emergency(decision, context)
    if isinstance(decision, CallPolice):
        return _EMERGENCY_CALL_POLICE
    if isinstance(decision, RearAttack):
        target = find(context, Enemy, slot=decision.target_slot)
        if target is not None and is_dangerous(target.combat_phase):
            return _EMERGENCY_SIDESTEP_CAUTION_BASE + 5  # escape a commit from behind
        return _EMERGENCY_REAR_ATTACK
    if isinstance(decision, Punch):
        target = find(context, Enemy, slot=decision.target_slot)
        if target is not None and is_punishable(target.combat_phase):
            return _EMERGENCY_PUNCH_PUNISHABLE
        return _EMERGENCY_PUNCH_DEFAULT
    if isinstance(decision, SmashBreakable):
        return _EMERGENCY_SMASH_BREAKABLE
    if isinstance(decision, ThrowHeldEnemy):
        return _EMERGENCY_HOLD_THROW
    if isinstance(decision, Supplex):
        return _EMERGENCY_HOLD_SUPPLEX
    if isinstance(decision, FlipHold):
        return _EMERGENCY_HOLD_FLIP
    if isinstance(decision, KneeStrike):
        return _EMERGENCY_HOLD_KNEE
    if isinstance(decision, ReleaseGrab):
        return _EMERGENCY_HOLD_RELEASE
    if isinstance(decision, JumpAttack):
        target = find(context, Enemy, slot=decision.target_slot)
        if target is not None and is_punishable(target.combat_phase):
            return _EMERGENCY_JUMP_ATTACK_PUNISHABLE
        return _EMERGENCY_JUMP_ATTACK_DEFAULT
    if isinstance(decision, ThrowKnife):
        return _EMERGENCY_THROW_KNIFE
    if isinstance(decision, WalkToCoordinate):
        return _EMERGENCY_RETREAT_FROM_DANGER
    if isinstance(decision, WalkToBreakable):
        return _EMERGENCY_WALK_TO_BREAKABLE
    if isinstance(decision, WalkToWeapon):
        return _EMERGENCY_WALK_TO_WEAPON
    if isinstance(decision, WalkToPickup):
        return _pickup_emergency(decision, context)
    if isinstance(decision, WalkToNearEnemy):
        return _EMERGENCY_WALK_TO_NEAR_ENEMY
    if isinstance(decision, WalkToAdvanceStage):
        return _EMERGENCY_WALK_TO_ADVANCE_STAGE
    return _EMERGENCY_DEFAULT


def _sidestep_tiebreak_key(decision: Sidestep, context: Context) -> tuple:
    """Deterministic Sidestep ranking when emergency integers still collide."""

    actor = _find_actor(context, decision.actor_slot)
    enemy = find(context, Enemy, slot=decision.threat_slot)
    if actor is not None and enemy is not None:
        dist = math.hypot(enemy.world_x - actor.world_x, enemy.world_y - actor.world_y)
        rear = 1 if _enemy_behind_actor(actor, enemy) else 0
        armed = (
            1
            if isinstance(enemy, Jack) and enemy.has_projectile
            else 0
        )
        # Max-sort: rear first, armed, closer, then stable slot id.
        return (rear, armed, -dist, enemy.slot)
    projectile = find(context, IncomingProjectile, slot=decision.threat_slot)
    if actor is not None and projectile is not None:
        dist = math.hypot(
            projectile.world_x - actor.world_x, projectile.world_y - actor.world_y
        )
        return (1, -dist, projectile.slot)
    return (0, 0, decision.threat_slot)


def determine_priority_decision(context: Context) -> Context:
    """Keep every ``Information`` token; collapse ``Decision`` tokens to one."""

    decisions = find_all(context, Decision)
    if not decisions:
        return context

    scored = [(_emergency(decision, context), decision) for decision in decisions]
    max_emergency = max(score for score, _ in scored)
    top_emergency = [decision for score, decision in scored if score == max_emergency]

    max_priority = max(decision.priority for decision in top_emergency)
    tied = [decision for decision in top_emergency if decision.priority == max_priority]

    if len(tied) == 1:
        winner = tied[0]
    elif all(isinstance(d, Sidestep) for d in tied):
        # Graded emergency should usually already differ; if not, break on
        # rear/closer without the random-warning path.
        winner = max(tied, key=lambda d: _sidestep_tiebreak_key(d, context))
    else:
        names = ", ".join(sorted(type(decision).__name__ for decision in tied))
        logger.warning(
            "determine_priority_decision: %d decisions tied at emergency=%d "
            "priority=%d (%s); picking one at random. Assign distinct "
            "priorities to break this deterministically.",
            len(tied),
            max_emergency,
            max_priority,
            names,
        )
        winner = random.choice(tied)

    return {token for token in context if not isinstance(token, Decision)} | {winner}
