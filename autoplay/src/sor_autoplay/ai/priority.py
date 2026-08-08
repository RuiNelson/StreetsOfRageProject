"""``determine_priority_decision`` — rank ``Decision`` tokens by emergency.

Per ``AI.md``: this also performs target selection, since ranking by
emergency and keeping only the highest-ranked ``Decision`` is what collapses
several same-type candidates (e.g. a ``Punch`` against each of two nearby
enemies) down to one.
"""

from __future__ import annotations

import logging
import random

from .enemy import Enemy
from .attack_decisions import JumpAttack, Punch, Supplex, ThrowKnife
from .hazard_tokens import IncomingProjectile
from .police_decision import CallPolice
from .tokens import Context, Decision, find, find_all
from .walk_decisions import (
    Sidestep,
    WalkToAdvanceStage,
    WalkToCoordinate,
    WalkToNearEnemy,
    WalkToWeapon,
)
from ..phases import is_dangerous, is_punishable

logger = logging.getLogger(__name__)

# 0-100 emergency scale: dodging a confirmed-dangerous attack must always
# outrank calling police, which in turn always outranks a punish window,
# which always outranks merely approaching. Keeping these as distinct bands
# (rather than a formula) makes the ranking easy to reason about per-class.
_EMERGENCY_SIDESTEP_DANGEROUS = 100
_EMERGENCY_SIDESTEP_CAUTION = 80
_EMERGENCY_SIDESTEP_UNRESOLVED = 70
_EMERGENCY_CALL_POLICE = 90
_EMERGENCY_PUNCH_PUNISHABLE = 60
_EMERGENCY_PUNCH_DEFAULT = 20
_EMERGENCY_SUPPLEX = 65  # already committed to a grab -- finishing it is the only sensible action
_EMERGENCY_JUMP_ATTACK_PUNISHABLE = 60
_EMERGENCY_JUMP_ATTACK_DEFAULT = 22
_EMERGENCY_THROW_KNIFE = 25
_EMERGENCY_RETREAT_FROM_DANGER = 45
_EMERGENCY_WALK_TO_WEAPON = 8
_EMERGENCY_WALK_TO_NEAR_ENEMY = 10
_EMERGENCY_WALK_TO_ADVANCE_STAGE = 5
_EMERGENCY_DEFAULT = 0


def _emergency(decision: Decision, context: Context) -> int:
    if isinstance(decision, Sidestep):
        threat = find(context, Enemy, slot=decision.threat_slot)
        if threat is None:
            projectile = find(context, IncomingProjectile, slot=decision.threat_slot)
            if projectile is not None:
                # A flying projectile is unambiguous danger -- no phase-confidence
                # question the way an Enemy's combat_phase raises one.
                return _EMERGENCY_SIDESTEP_DANGEROUS
            return _EMERGENCY_SIDESTEP_UNRESOLVED
        if is_dangerous(threat.combat_phase):
            return _EMERGENCY_SIDESTEP_DANGEROUS
        return _EMERGENCY_SIDESTEP_CAUTION
    if isinstance(decision, CallPolice):
        return _EMERGENCY_CALL_POLICE
    if isinstance(decision, Punch):
        target = find(context, Enemy, slot=decision.target_slot)
        if target is not None and is_punishable(target.combat_phase):
            return _EMERGENCY_PUNCH_PUNISHABLE
        return _EMERGENCY_PUNCH_DEFAULT
    if isinstance(decision, Supplex):
        # Holding an enemy is itself the justification -- no target-phase lookup
        # needed, matching CallPolice's flat value above.
        return _EMERGENCY_SUPPLEX
    if isinstance(decision, JumpAttack):
        target = find(context, Enemy, slot=decision.target_slot)
        if target is not None and is_punishable(target.combat_phase):
            return _EMERGENCY_JUMP_ATTACK_PUNISHABLE
        return _EMERGENCY_JUMP_ATTACK_DEFAULT
    if isinstance(decision, ThrowKnife):
        # Already gated on the enemy being out of melee range in decide.py --
        # no "already committed" nuance to add here.
        return _EMERGENCY_THROW_KNIFE
    if isinstance(decision, WalkToCoordinate):
        # This decision type is only ever produced for the danger-retreat case
        # in this phase, per the plan.
        return _EMERGENCY_RETREAT_FROM_DANGER
    if isinstance(decision, WalkToWeapon):
        return _EMERGENCY_WALK_TO_WEAPON
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
