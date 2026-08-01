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
from ..world_map import MapEntity


@dataclass(frozen=True, slots=True)
class PressureReport:
    score: float
    enemy_count: int
    boss_present: bool
    reason: str
    hunters: int = 0
    charging: int = 0


def nearby_threats(
    player: MapEntity,
    entities: tuple[MapEntity, ...],
    *,
    x_radius: float = 200.0,
    lane_radius: float = 48.0,
) -> tuple[list[MapEntity], list[MapEntity]]:
    """Return (enemies, bosses) near the player in map space."""

    enemies: list[MapEntity] = []
    bosses: list[MapEntity] = []
    for entity in entities:
        if entity.kind not in ("enemy", "boss"):
            continue
        if entity.combat_phase in (CombatPhase.DEATH, CombatPhase.SCRIPTED):
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
) -> PressureReport:
    """Scalar pressure in roughly 0..10+; call special when score ≥ threshold."""

    if player_entity is None or not player_snap.is_playable:
        return PressureReport(0.0, 0, False, "no player")

    enemies, bosses = nearby_threats(player_entity, snapshot.world_map.entities)
    all_near = enemies + bosses
    enemy_count = len(enemies)
    boss_present = bool(bosses)
    seat = player_snap.index
    hunters = sum(1 for e in all_near if e.targets_player == seat)
    charging = sum(1 for e in all_near if is_dangerous(e.combat_phase))

    hp = player_snap.health_percent if player_snap.health_percent is not None else 100.0
    score = 0.0
    reasons: list[str] = []

    if enemy_count >= 5:
        score += 4.0 + 0.5 * (enemy_count - 5)
        reasons.append(f"{enemy_count} enemies")
    elif enemy_count >= 3:
        score += 2.0 + 0.5 * (enemy_count - 3)
        reasons.append(f"{enemy_count} enemies")
    elif enemy_count >= 1:
        score += 0.4 * enemy_count

    if boss_present:
        score += 2.5
        reasons.append("boss")

    if hunters >= 3:
        score += 2.0
        reasons.append(f"{hunters} hunting me")
    elif hunters >= 2:
        score += 1.0
        reasons.append(f"{hunters} hunting")

    if charging >= 2:
        score += 2.0
        reasons.append(f"{charging} charging")
    elif charging == 1 and hp <= 50:
        score += 1.2
        reasons.append("charge + mid hp")

    if hp <= 25.0:
        score += 3.5
        reasons.append(f"hp {hp:.0f}%")
    elif hp <= 45.0:
        score += 2.0
        reasons.append(f"hp {hp:.0f}%")
    elif hp <= 60.0 and enemy_count >= 2:
        score += 1.0
        reasons.append("mid hp + pack")

    left = sum(1 for e in enemies if e.map_x < player_entity.map_x - 8)
    right = sum(1 for e in enemies if e.map_x > player_entity.map_x + 8)
    if left >= 1 and right >= 1 and enemy_count >= 3:
        score += 1.5
        reasons.append("surrounded")

    return PressureReport(
        score=score,
        enemy_count=enemy_count,
        boss_present=boss_present,
        reason=", ".join(reasons) if reasons else "calm",
        hunters=hunters,
        charging=charging,
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
