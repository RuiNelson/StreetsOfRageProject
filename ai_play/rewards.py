"""Convert semantic detector events into PPO rewards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .event_detector import BOSS_TYPES, Event
from .weights import DEFAULT_WEIGHTS, RewardWeights


@dataclass(frozen=True)
class RewardResult:
    """Total reward plus diagnostics used in Gymnasium ``info``."""

    total: float
    components: dict[str, float]
    lives_lost: int
    game_completed: bool


def _add(components: dict[str, float], name: str, value: float) -> None:
    if value:
        components[name] = components.get(name, 0.0) + value


def reward_events(
    events: Iterable[Event],
    *,
    start_pressed: bool = False,
    weights: RewardWeights = DEFAULT_WEIGHTS,
) -> RewardResult:
    """Score events observed after one atomic action interval."""

    components: dict[str, float] = {}
    lives_lost = 0
    game_completed = False

    for event in events:
        data = event.data
        if event.kind == "frames_elapsed":
            _add(
                components,
                "frames_elapsed",
                int(data.get("intervals", 0)) * weights.per_60_frames,
            )
        elif event.kind == "player_energy_lost":
            _add(
                components,
                "player_energy_lost",
                int(data.get("amount", 0)) * weights.per_energy_lost,
            )
        elif event.kind == "player_life_lost":
            amount = int(data.get("amount", 0))
            lives_lost += amount
            _add(
                components,
                "player_life_lost",
                amount * weights.per_life_lost,
            )
        elif event.kind == "enemy_defeated":
            regular = 0
            bosses = 0
            for enemy in data.get("enemies", []):
                if not isinstance(enemy, dict):
                    continue
                try:
                    enemy_type = int(str(enemy.get("type", "")), 16)
                except ValueError:
                    continue
                if enemy_type in BOSS_TYPES:
                    bosses += 1
                else:
                    regular += 1
            _add(
                components,
                "regular_enemy_defeated",
                regular * weights.per_regular_enemy_defeated,
            )
            _add(
                components,
                "boss_defeated",
                bosses * weights.per_boss_defeated,
            )
        elif event.kind == "level_completed":
            _add(components, "level_completed", weights.per_level_completed)
        elif event.kind == "level_increased":
            _add(
                components,
                "level_increased",
                int(data.get("amount", 1)) * weights.per_level_increased,
            )
        elif event.kind == "level_decreased":
            _add(
                components,
                "level_decreased",
                int(data.get("amount", 1)) * weights.per_level_decreased,
            )
        elif event.kind == "game_completed":
            game_completed = True
            ending = data.get("ending")
            _add(
                components,
                "game_completed",
                weights.good_ending if ending == "good" else weights.bad_ending,
            )

    if start_pressed:
        _add(components, "start_activation", weights.per_start_activation)

    return RewardResult(
        total=float(sum(components.values())),
        components=components,
        lives_lost=lives_lost,
        game_completed=game_completed,
    )
