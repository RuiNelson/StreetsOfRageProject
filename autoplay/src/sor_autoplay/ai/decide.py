"""``generate_decision_tokens`` and its ``should_*`` candidate generators.

Per ``AI.md``, each ``should_*`` function is concerned only with whether a
decision is possible and sensible — never with relative importance across
decisions, which is ``determine_priority_decision``'s job (someone else's
``priority.py``). Multiple qualifying candidates of the same decision type
(e.g. two ``Punch`` candidates against two different enemies) are all
emitted; nothing here picks a "best" one.
"""

from __future__ import annotations

import math

from ..phases import CombatPhase, is_dangerous, should_ignore_as_target
from .attack_decisions import Punch
from .character import Myself, Partner, PlayableCharacter
from .enemy import Enemy
from .essential import AnimationInProgress
from .hazard_tokens import DangerZone
from .police_decision import CallPolice
from .tokens import Context, Token, find, find_all
from .walk_decisions import Sidestep, WalkToNearEnemy

# Placeholder heuristic thresholds, subject to future tuning against real
# gameplay.
PUNCH_RANGE_X = 24
PUNCH_RANGE_Y = 16
CAUTION_RANGE_X = 40
CAUTION_RANGE_Y = 24
POLICE_HEALTH_PERCENT_THRESHOLD = 25.0
POLICE_DANGER_THRESHOLD = 3
POLICE_LOW_HEALTH_DANGER_THRESHOLD = 1


def _actors(context: Context) -> list[PlayableCharacter]:
    return [actor for actor in (find(context, Myself), find(context, Partner)) if actor is not None]


def _is_facing(enemy: Enemy, target_world_x: int) -> bool:
    return target_world_x <= enemy.world_x if enemy.facing_left else target_world_x >= enemy.world_x


def _is_close_and_facing_caution(enemy: Enemy, actor: PlayableCharacter) -> bool:
    return (
        enemy.combat_phase is CombatPhase.UNKNOWN
        and abs(enemy.world_x - actor.world_x) <= CAUTION_RANGE_X
        and abs(enemy.world_y - actor.world_y) <= CAUTION_RANGE_Y
        and _is_facing(enemy, actor.world_x)
    )


def should_punch(context: Context) -> Context:
    decisions: set[Token] = set()
    enemies = [e for e in find_all(context, Enemy) if not should_ignore_as_target(e.combat_phase)]
    for actor in _actors(context):
        if find(context, AnimationInProgress, slot=actor.slot) is not None:
            continue
        for enemy in enemies:
            if abs(enemy.world_x - actor.world_x) <= PUNCH_RANGE_X and abs(enemy.world_y - actor.world_y) <= PUNCH_RANGE_Y:
                decisions.add(Punch(actor_slot=actor.slot, target_slot=enemy.slot))
    return decisions


def should_walk_to_near_enemy(context: Context) -> Context:
    decisions: set[Token] = set()
    enemies = [e for e in find_all(context, Enemy) if not should_ignore_as_target(e.combat_phase)]
    for actor in _actors(context):
        if find(context, AnimationInProgress, slot=actor.slot) is not None:
            continue
        if not enemies:
            continue
        nearest = min(
            enemies,
            key=lambda e: math.hypot(e.world_x - actor.world_x, e.world_y - actor.world_y),
        )
        decisions.add(WalkToNearEnemy(actor_slot=actor.slot, target_slot=nearest.slot))
    return decisions


def should_sidestep(context: Context) -> Context:
    decisions: set[Token] = set()
    enemies = find_all(context, Enemy)
    for actor in _actors(context):
        if find(context, AnimationInProgress, slot=actor.slot) is not None:
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
        if find(context, AnimationInProgress, slot=actor.slot) is not None:
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


def generate_decision_tokens(context: Context) -> Context:
    """Returns context | every should_* candidate that applies."""

    return (
        context
        | should_walk_to_near_enemy(context)
        | should_sidestep(context)
        | should_punch(context)
        | should_call_police(context)
    )
