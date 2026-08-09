"""``determine_priority_decision`` — rank ``Decision`` tokens by emergency.

Per ``AI.md``: this also performs target selection, since ranking by
emergency and keeping only the highest-ranked ``Decision`` is what collapses
several same-type candidates (e.g. a ``Punch`` against each of two nearby
enemies) down to one.
"""

from __future__ import annotations

import logging
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
from .character import Myself, Partner
from .enemy import Enemy
from .pickup_tokens import (
    HealthPickup,
    LifePickup,
    Pickup,
    ScorePickup,
    SpecialPickup,
)
from .police_decision import CallPolice
from .tokens import Context, Decision, find, find_all
from .walk_decisions import (
    WalkToAdvanceStage,
    WalkToBreakable,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)
from ..phases import is_dangerous, is_punishable

logger = logging.getLogger(__name__)

# 0-100 emergency scale.
_EMERGENCY_COUNTER_GRAB = 100  # already held — only useful action
_EMERGENCY_CALL_POLICE = 88
_EMERGENCY_REAR_ATTACK = 55  # escape when boxed in / punch dead-zone
_EMERGENCY_REAR_ATTACK_DANGEROUS = 60  # escape a commit from behind
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
_EMERGENCY_SMASH_BREAKABLE = 16
_EMERGENCY_WALK_TO_BREAKABLE = 14
_EMERGENCY_WALK_TO_WEAPON = 8
_EMERGENCY_WALK_TO_PICKUP_CRITICAL_HEALTH = 50
_EMERGENCY_WALK_TO_PICKUP_HEALTH = 15
_EMERGENCY_WALK_TO_PICKUP_LIFE = 12
_EMERGENCY_WALK_TO_PICKUP_SPECIAL = 9
_EMERGENCY_WALK_TO_PICKUP_SCORE = 3
_EMERGENCY_WALK_TO_NEAR_ENEMY = 14
# No live enemy left anywhere (on-screen or not) → push stage (was 5).
_EMERGENCY_WALK_TO_ADVANCE_STAGE = 12
_EMERGENCY_DEFAULT = 0


def _find_actor(context: Context, slot: str) -> Myself | Partner | None:
    for actor in (find(context, Myself), find(context, Partner)):
        if actor is not None and actor.slot == slot:
            return actor
    return None


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
    if isinstance(decision, CallPolice):
        return _EMERGENCY_CALL_POLICE
    if isinstance(decision, RearAttack):
        target = find(context, Enemy, slot=decision.target_slot)
        if target is not None and is_dangerous(target.combat_phase):
            return _EMERGENCY_REAR_ATTACK_DANGEROUS
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
