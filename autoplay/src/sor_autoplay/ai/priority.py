"""``determine_priority_decision`` — rank ``Decision`` tokens by emergency.

Per ``AI.md``: this also performs target selection, since ranking by
emergency and keeping only the highest-ranked ``Decision`` is what collapses
several same-type candidates (e.g. a ``Punch`` against each of two nearby
enemies) down to one.

Each ``_emergency_*`` function below computes its score from the
``Information`` tokens present in the ``Context`` — per the matching
concrete ``Decision`` class's ``Raises emergency: ...`` docstring line —
never from the decision's type alone. The module constants are named
*contributions* consulted when their token condition holds; they are not
applied unconditionally.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable

from ..phases import CombatPhase, is_dangerous, is_punishable
from .decide import (
    KNIFE_MELEE_X,
    KNIFE_RANGE_X,
    KNIFE_RANGE_Y,
    POLICE_HEALTH_PERCENT_THRESHOLD,
    POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE,
    _advance_blocking_enemies,
)
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
from .tokens import Myself, Partner
from .tokens import Breakable, Enemy, Weapon, weapon_rank
from .tokens import (
    HealthPickup,
    LifePickup,
    Pickup,
    ScorePickup,
    SpecialPickup,
)
from .tokens import CallPolice
from .tokens import Context, Decision, find, find_all
from .tokens import (
    WalkToAdvanceStage,
    WalkToBreakable,
    WalkToNearEnemy,
    WalkToPickup,
    WalkToWeapon,
)

logger = logging.getLogger(__name__)

# 0-100 emergency scale.
_EMERGENCY_COUNTER_GRAB = 100  # already held — only useful action
_EMERGENCY_TECH_RECOVER = 90  # narrow window, free to act at nothing else
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
_EMERGENCY_THROW_PEPPER = 25
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


def _emergency_counter_grab(decision: CounterGrab, context: Context) -> int:
    actor = _find_actor(context, decision.actor_slot)
    if actor is not None and actor.combat_phase is CombatPhase.HELD_BY_ENEMY:
        return _EMERGENCY_COUNTER_GRAB
    return _EMERGENCY_DEFAULT


def _emergency_tech_recover(decision: TechRecover, context: Context) -> int:
    actor = _find_actor(context, decision.actor_slot)
    if actor is not None and actor.throw_tech_ready:
        return _EMERGENCY_TECH_RECOVER
    return _EMERGENCY_DEFAULT


def _emergency_call_police(decision: CallPolice, context: Context) -> int:
    actor = _find_actor(context, decision.actor_slot)
    if actor is None:
        return _EMERGENCY_DEFAULT
    threshold = (
        POLICE_HEALTH_PERCENT_THRESHOLD_LAST_LIFE
        if actor.lives <= 1
        else POLICE_HEALTH_PERCENT_THRESHOLD
    )
    if actor.health_percent < threshold:
        return _EMERGENCY_CALL_POLICE
    return _EMERGENCY_DEFAULT


def _emergency_rear_attack(decision: RearAttack, context: Context) -> int:
    target = find(context, Enemy, slot=decision.target_slot)
    if target is None:
        return _EMERGENCY_DEFAULT
    if is_dangerous(target.combat_phase):
        return _EMERGENCY_REAR_ATTACK_DANGEROUS
    return _EMERGENCY_REAR_ATTACK


def _emergency_melee_strike(decision: Decision, context: Context) -> int:
    """Shared scoring for ``Punch`` / ``SwingBatOrPipe`` /
    ``StabWithKnifeOrBottle`` / ``SprayPepper`` -- same formula regardless
    of held weapon, since none of these has evidence of a different
    punishable-phase payoff."""

    target = find(context, Enemy, slot=getattr(decision, "target_slot", None))
    if target is None:
        return _EMERGENCY_DEFAULT
    if is_punishable(target.combat_phase):
        return _EMERGENCY_PUNCH_PUNISHABLE
    return _EMERGENCY_PUNCH_DEFAULT


def _emergency_jump_attack(decision: JumpAttack, context: Context) -> int:
    target = find(context, Enemy, slot=decision.target_slot)
    if target is None:
        return _EMERGENCY_DEFAULT
    if is_punishable(target.combat_phase):
        return _EMERGENCY_JUMP_ATTACK_PUNISHABLE
    return _EMERGENCY_JUMP_ATTACK_DEFAULT


def _emergency_smash_breakable(decision: SmashBreakable, context: Context) -> int:
    target = find(context, Breakable, slot=decision.target_slot)
    if target is None:
        return _EMERGENCY_DEFAULT
    return _EMERGENCY_SMASH_BREAKABLE


def _emergency_walk_to_breakable(decision: WalkToBreakable, context: Context) -> int:
    target = find(context, Breakable, slot=decision.target_slot)
    if target is None:
        return _EMERGENCY_DEFAULT
    return _EMERGENCY_WALK_TO_BREAKABLE


def _emergency_walk_to_weapon(decision: WalkToWeapon, context: Context) -> int:
    weapon = find(context, Weapon, slot=decision.target_slot)
    actor = _find_actor(context, decision.actor_slot)
    if weapon is None or actor is None:
        return _EMERGENCY_DEFAULT
    if weapon_rank(weapon.weapon_type) > weapon_rank(actor.held_weapon_type):
        return _EMERGENCY_WALK_TO_WEAPON
    return _EMERGENCY_DEFAULT


def _emergency_walk_to_near_enemy(decision: WalkToNearEnemy, context: Context) -> int:
    target = find(context, Enemy, slot=decision.target_slot)
    if target is None:
        return _EMERGENCY_DEFAULT
    return _EMERGENCY_WALK_TO_NEAR_ENEMY


def _emergency_walk_to_advance_stage(decision: WalkToAdvanceStage, context: Context) -> int:
    if _advance_blocking_enemies(context):
        return _EMERGENCY_DEFAULT
    return _EMERGENCY_WALK_TO_ADVANCE_STAGE


def _emergency_thrown_weapon(decision: Decision, context: Context, weight: int) -> int:
    """Shared range check for the two attack-thrown weapons (knife, pepper —
    items-and-weapons.md's ``$21E6``): beyond melee, within throw range."""

    target = find(context, Enemy, slot=getattr(decision, "target_slot", None))
    actor = _find_actor(context, getattr(decision, "actor_slot", None))
    if target is None or actor is None:
        return _EMERGENCY_DEFAULT
    dx = abs(target.world_x - actor.world_x)
    dy = abs(target.world_y - actor.world_y)
    beyond_melee = not (dx <= KNIFE_MELEE_X and dy <= KNIFE_RANGE_Y)
    within_range = dx <= KNIFE_RANGE_X and dy <= KNIFE_RANGE_Y
    if beyond_melee and within_range:
        return weight
    return _EMERGENCY_DEFAULT


def _emergency_throw_knife(decision: ThrowKnife, context: Context) -> int:
    return _emergency_thrown_weapon(decision, context, _EMERGENCY_THROW_KNIFE)


def _emergency_throw_pepper(decision: ThrowPepper, context: Context) -> int:
    return _emergency_thrown_weapon(decision, context, _EMERGENCY_THROW_PEPPER)


def _emergency_walk_to_pickup(decision: WalkToPickup, context: Context) -> int:
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


def _held_enemy_emergency(weight: int) -> Callable[[Decision, Context], int]:
    """Build an ``_emergency_*`` for a hold move: ``weight`` only while its
    target ``Enemy`` is actually held (``CombatPhase.GRABBED``)."""

    def _emergency(decision: Decision, context: Context) -> int:
        target = find(context, Enemy, slot=getattr(decision, "target_slot", None))
        if target is not None and target.combat_phase is CombatPhase.GRABBED:
            return weight
        return _EMERGENCY_DEFAULT

    return _emergency


_EMERGENCY_FUNCS: dict[type[Decision], Callable[[Decision, Context], int]] = {
    CounterGrab: _emergency_counter_grab,
    TechRecover: _emergency_tech_recover,
    CallPolice: _emergency_call_police,
    RearAttack: _emergency_rear_attack,
    Punch: _emergency_melee_strike,
    SwingBatOrPipe: _emergency_melee_strike,
    StabWithKnifeOrBottle: _emergency_melee_strike,
    SprayPepper: _emergency_melee_strike,
    SmashBreakable: _emergency_smash_breakable,
    ThrowHeldEnemy: _held_enemy_emergency(_EMERGENCY_HOLD_THROW),
    Supplex: _held_enemy_emergency(_EMERGENCY_HOLD_SUPPLEX),
    FlipHold: _held_enemy_emergency(_EMERGENCY_HOLD_FLIP),
    AttackHeldEnemy: _held_enemy_emergency(_EMERGENCY_HOLD_KNEE),
    ReleaseGrab: _held_enemy_emergency(_EMERGENCY_HOLD_RELEASE),
    JumpAttack: _emergency_jump_attack,
    ThrowKnife: _emergency_throw_knife,
    ThrowPepper: _emergency_throw_pepper,
    WalkToBreakable: _emergency_walk_to_breakable,
    WalkToWeapon: _emergency_walk_to_weapon,
    WalkToPickup: _emergency_walk_to_pickup,
    WalkToNearEnemy: _emergency_walk_to_near_enemy,
    WalkToAdvanceStage: _emergency_walk_to_advance_stage,
}


def _emergency(decision: Decision, context: Context) -> int:
    func = _EMERGENCY_FUNCS.get(type(decision))
    if func is None:
        return _EMERGENCY_DEFAULT
    return func(decision, context)


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
        # tied entries are never literally the same object here: Context is
        # a set of frozen/hashable Decision dataclasses, so two candidates
        # with identical priority/actor_slot/target_slot would already have
        # deduplicated into one. Log full repr (not just the class name) so
        # that distinguishing field -- almost always a different
        # target_slot/actor_slot -- is visible instead of looking like a
        # duplicate.
        details = ", ".join(sorted(repr(decision) for decision in tied))
        logger.warning(
            "determine_priority_decision: %d decisions tied at emergency=%d "
            "priority=%d (%s); picking one at random. Assign distinct "
            "priorities to break this deterministically.",
            len(tied),
            max_emergency,
            max_priority,
            details,
        )
        winner = random.choice(tied)

    return {token for token in context if not isinstance(token, Decision)} | {winner}
