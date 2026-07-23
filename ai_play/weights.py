"""Reward weights for the Streets of Rage agent."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RewardWeights:
    """Scalar rewards applied to semantic gameplay events."""

    per_60_frames: float = -0.001
    per_energy_lost: float = -0.10
    per_life_lost: float = -10.0
    per_regular_enemy_defeated: float = 1.0
    per_boss_defeated: float = 10.0
    per_level_completed: float = 0.0
    per_level_increased: float = 50.0
    per_level_decreased: float = -50.0
    good_ending: float = 500.0
    bad_ending: float = -100.0


DEFAULT_WEIGHTS = RewardWeights()
