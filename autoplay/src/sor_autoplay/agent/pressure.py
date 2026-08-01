"""Police-special pressure scoring.

Call the police when the local situation is dangerous: many live enemies,
low health, or a boss while already hurt. Round 8 zeros special counters in
the ROM, so pressure may score high but the agent still needs a remaining
special stock.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..phases import CombatPhase, is_dangerous
from ..state import GameSnapshot, PlayerSnapshot
from ..world_map import SCREEN_WIDTH, MapEntity
from .fuzzy import FuzzyInference, FuzzyRule, falling, rising
from .knowledge import Relation, TacticalKnowledgeGraph


@dataclass(frozen=True, slots=True)
class PressureReport:
    score: float
    enemy_count: int
    boss_present: bool
    reason: str
    hunters: int = 0
    charging: int = 0
    urgency: float = 0.0
    fired_rules: tuple[str, ...] = ()


_PRESSURE_ENGINE = FuzzyInference(
    (
        FuzzyRule("baseline", (), 0.0, weight=0.35),
        FuzzyRule("crowd", ("crowd",), 0.85),
        FuzzyRule("hunters", ("hunters",), 0.60),
        FuzzyRule("active-attacks", ("active_attacks",), 0.60),
        FuzzyRule("boss", ("boss",), 0.55),
        FuzzyRule("surrounded", ("surrounded",), 0.80),
        FuzzyRule(
            "critical-health",
            ("critical_health", "any_threat"),
            0.85,
        ),
        FuzzyRule("crowd-while-hurt", ("crowd", "low_health"), 1.0),
        FuzzyRule("attack-while-hurt", ("active_attacks", "low_health"), 1.0),
        FuzzyRule("boss-while-hurt", ("boss", "low_health"), 0.95),
    )
)


def nearby_threats(
    player: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    x_radius: float = 200.0,
    lane_radius: float = 48.0,
    graph: TacticalKnowledgeGraph | None = None,
) -> tuple[list[MapEntity], list[MapEntity]]:
    """Return (enemies, bosses) near the player in map space."""

    enemies: list[MapEntity] = []
    bosses: list[MapEntity] = []
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if graph is not None and not graph.entity_has(entity, Relation.REACHABLE):
            continue
        if (
            entity.health is not None
            and entity.health >= 0x8000
            and not is_dangerous(entity.combat_phase)
        ):
            continue
        if entity.combat_phase in (CombatPhase.DEATH, CombatPhase.SCRIPTED):
            continue
        if not 0.0 <= entity.map_x <= float(SCREEN_WIDTH):
            continue
        if abs(entity.map_x - player.map_x) > x_radius:
            continue
        if abs(entity.map_y - player.map_y) > lane_radius:
            continue
        if entity.kind == "boss":
            bosses.append(entity)
        else:
            enemies.append(entity)
    return enemies, bosses


def compute_pressure(
    snapshot: GameSnapshot,
    player_snap: PlayerSnapshot,
    player_entity: MapEntity | None,
    *,
    graph: TacticalKnowledgeGraph | None = None,
) -> PressureReport:
    """Fuzzy danger pressure on a stable 0..10 scale."""

    if player_entity is None or not player_snap.is_playable:
        return PressureReport(0.0, 0, False, "no player")

    enemies, bosses = nearby_threats(
        player_entity,
        snapshot.world_map.entities,
        graph=graph,
    )
    all_near = enemies + bosses
    enemy_count = len(enemies)
    boss_present = bool(bosses)
    seat = player_snap.index
    hunters = sum(1 for e in all_near if e.targets_player == seat)
    charging = sum(1 for e in all_near if is_dangerous(e.combat_phase))

    hp = player_snap.health_percent if player_snap.health_percent is not None else 100.0
    left = sum(1 for e in enemies if e.map_x < player_entity.map_x - 8)
    right = sum(1 for e in enemies if e.map_x > player_entity.map_x + 8)
    facts = {
        "crowd": rising(float(enemy_count), 2.0, 6.0),
        "hunters": rising(float(hunters), 0.5, 3.0),
        "active_attacks": rising(float(charging), 0.0, 2.0),
        "boss": 1.0 if boss_present else 0.0,
        "surrounded": 1.0 if left and right and enemy_count >= 3 else 0.0,
        "low_health": falling(hp, 30.0, 75.0),
        "critical_health": falling(hp, 12.0, 35.0),
        "any_threat": 1.0 if all_near else 0.0,
    }
    inferred = _PRESSURE_ENGINE.infer(facts)
    fired = tuple(
        name
        for name, activation in inferred.activations
        if name != "baseline" and activation >= 0.15
    )
    reasons = list(fired)
    if enemy_count:
        reasons.append(f"{enemy_count} enemies")
    if hp < 75.0:
        reasons.append(f"hp {hp:.0f}%")

    return PressureReport(
        score=inferred.value * 10.0,
        enemy_count=enemy_count,
        boss_present=boss_present,
        reason=", ".join(reasons) if reasons else "calm",
        hunters=hunters,
        charging=charging,
        urgency=inferred.value,
        fired_rules=fired,
    )


def should_call_police(
    pressure: PressureReport,
    specials: int,
    *,
    threshold: float = 4.5,
    level_index: int = 0,
) -> bool:
    """Decide whether to spend a police special this tick.

    Round 8 (level index 7) normally has no usable specials; still gate on stock.
    """

    if specials <= 0:
        return False
    if level_index >= 7:
        return False
    return pressure.score >= threshold
