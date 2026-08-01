"""Scripted Streets of Rage agents (standard controls only).

Standard layout (OPTIONS control scheme 0, no host ``--altControls``):

- physical **B** → attack / pickup
- physical **C** → jump
- physical **A** → police special
- D-pad → move
- Start → pause (agents never press Start)

Agents may be toggled per player from the HUD at any time.
"""

from .controls import STANDARD_CONTROLS, Buttons, mask_from_intent
from .enemies import CounterPlan, plan_for
from .policy import AgentConfig, AgentDecision, AgentState, decide_actions

__all__ = [
    "STANDARD_CONTROLS",
    "AgentConfig",
    "AgentDecision",
    "AgentState",
    "Buttons",
    "CounterPlan",
    "decide_actions",
    "mask_from_intent",
    "plan_for",
]
