"""``AgentLoop`` — one player's iteration of ``AI.md``'s process loop.

``tick`` never fetches RAM itself; it consumes an already-polled
``GameSnapshot`` (see ``sor_autoplay.state.read_snapshot``), matching the
observer's existing single-poll-per-tick discipline.
"""

from __future__ import annotations

from sor_autoplay.state import GameSnapshot

from .decide import generate_decision_tokens
from .execute import execute_decision, press_no_button
from .gamepad import VirtualGamepad
from .inference import generate_inference_tokens
from .observe import generate_direct_observation_tokens
from .priority import determine_priority_decision
from .tokens import Decision, find_all


class AgentLoop:
    def __init__(self, gamepad: VirtualGamepad) -> None:
        self._gamepad = gamepad

    def tick(self, snapshot: GameSnapshot, *, player_index: int) -> None:
        if (
            snapshot.paused
            or not snapshot.timer_valid
            or not snapshot.players[player_index - 1].is_playable
        ):
            self._gamepad.release()
            return

        context = generate_direct_observation_tokens(snapshot, player_index=player_index)
        context |= generate_inference_tokens(context)
        context |= generate_decision_tokens(context)
        context = determine_priority_decision(context)

        decisions = find_all(context, Decision)
        if not decisions:
            press_no_button(self._gamepad)
        else:
            execute_decision(decisions[0], context, self._gamepad)
