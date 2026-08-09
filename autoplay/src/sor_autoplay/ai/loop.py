"""``AgentLoop`` — one player's iteration of ``AI.md``'s process loop.

``tick`` never fetches RAM itself; it consumes an already-polled
``GameSnapshot`` (see ``sor_autoplay.state.read_snapshot``), matching the
observer's existing single-poll-per-tick discipline.

``inform_hud`` implements AI.md's UI step: it copies the surviving
``Decision`` (and every candidate that preceded it) into a thread-safe
``DecisionState`` that the observer's Tk thread reads for the HUD.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from sor_autoplay.state import GameSnapshot

from .decide import generate_decision_tokens
from .execute import execute_decision, press_no_button
from .gamepad import VirtualGamepad
from .inference import generate_inference_tokens
from .observe import generate_direct_observation_tokens
from .priority import determine_priority_decision
from .tokens import Context, Decision, find_all


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionState:
    """Thread-safe snapshot of one player's last tick, for the HUD.

    ``winning`` is the ``Decision`` that survived
    ``determine_priority_decision`` and that ``execute_decision`` is (about
    to be) carrying out. ``pending`` holds every candidate ``Decision`` the
    tick considered before that collapse, so the HUD can also show what the
    AI was choosing between.
    """

    winning: Decision | None
    pending: tuple[Decision, ...]


class AgentLoop:
    def __init__(self, gamepad: VirtualGamepad) -> None:
        self._gamepad = gamepad
        self._decision_state = DecisionState(winning=None, pending=())
        self._state_lock = threading.Lock()

    def inform_hud(self, context: Context, *, pending: tuple[Decision, ...] = ()) -> None:
        """Copy the current tick's decisions into the thread-safe HUD state.

        ``context`` is the post-collapse context (at most one ``Decision``);
        ``pending`` carries the pre-collapse candidate list so the HUD can
        also show what the AI was choosing between. Callers may also pass an
        empty context (e.g. right after disabling the agent) to clear it.
        """

        decisions = tuple(find_all(context, Decision))
        winning = decisions[0] if decisions else None
        with self._state_lock:
            self._decision_state = DecisionState(winning=winning, pending=pending)

    def decision_state(self) -> DecisionState:
        with self._state_lock:
            return self._decision_state

    def tick(self, snapshot: GameSnapshot, *, player_index: int) -> Decision | None:
        """Run one iteration and return the winning ``Decision``, if any.

        The return value is purely informational (e.g. for a HUD to show
        what the AI is doing) — callers must not feed it back into the
        pipeline; ``execute_decision`` has already run by the time it comes
        back. The HUD's canonical source is ``decision_state()``, which
        ``inform_hud`` fills every tick.
        """

        if (
            snapshot.paused
            or not snapshot.timer_valid
            or not snapshot.players[player_index - 1].is_playable
        ):
            self._gamepad.release()
            self.inform_hud(set())
            return None

        context = generate_direct_observation_tokens(snapshot, player_index=player_index)
        context |= generate_inference_tokens(context)
        context |= generate_decision_tokens(context)
        pending = tuple(find_all(context, Decision))
        context = determine_priority_decision(context)
        self.inform_hud(context, pending=pending)

        decisions = find_all(context, Decision)
        if not decisions:
            press_no_button(self._gamepad)
            return None

        decision = decisions[0]
        execute_decision(decision, context, self._gamepad)
        return decision
