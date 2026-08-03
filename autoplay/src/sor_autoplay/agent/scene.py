"""Scene composition facade.

Twin-specific logic lives in ``twins.py`` (ROM-backed Onihime/Yasha AI).
This module re-exports composition helpers so older imports keep working.
"""

from __future__ import annotations

from .twins import (
    TWIN_FAMILY,
    TWIN_NEAR_X,
    TWIN_NEAR_Y,
    TWIN_TYPE,
    TwinComposition,
    TwinFocusMemory,
    TwinRoutine,
    decode_routine,
    is_twin,
    live_twins,
    nearby_twins,
    plan_for_twin,
    twin_composition,
    twin_focus_bonus,
    twin_scene_plan,
    twins_bracket_player,
    update_focus,
)

__all__ = [
    "TWIN_FAMILY",
    "TWIN_NEAR_X",
    "TWIN_NEAR_Y",
    "TWIN_TYPE",
    "TwinComposition",
    "TwinFocusMemory",
    "TwinRoutine",
    "decode_routine",
    "is_twin",
    "live_twins",
    "nearby_twins",
    "plan_for_twin",
    "twin_composition",
    "twin_focus_bonus",
    "twin_scene_plan",
    "twins_bracket_player",
    "update_focus",
]
