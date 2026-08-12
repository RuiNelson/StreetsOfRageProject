"""``AgentLoop`` — one player's iteration of ``AI.md``'s process loop.

``tick`` never fetches RAM itself; it consumes an already-polled
``GameSnapshot`` (see ``sor_autoplay.state.read_snapshot``), matching the
observer's existing single-poll-per-tick discipline.

``inform_hud`` implements AI.md's UI step: it copies the surviving
``Verb`` (and every candidate that preceded it) into a thread-safe
``VerbState`` that the observer's Tk thread reads for the HUD.

``_nora_tracker`` is the one piece of state that survives across ticks
besides the virtual gamepad's own sticky hold -- see
``observe.NoraAttackTracker``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from sor_autoplay.state import GameSnapshot

from .decide import generate_verb_tokens
from .execute import execute_tick
from .gamepad import VirtualGamepad
from .inference import generate_inference_tokens
from .observe import NoraAttackTracker, generate_direct_observation_tokens
from .priority import determine_priority_verb
from .tokens import Context, Verb, find_all


@dataclass(frozen=True, slots=True, kw_only=True)
class VerbState:
    """Thread-safe snapshot of one player's last tick, for the HUD.

    ``winning`` is the ``Verb`` that survived
    ``determine_priority_verb`` and that ``execute_verb`` is (about
    to be) carrying out. ``pending`` holds every candidate ``Verb`` the
    tick considered before that collapse, so the HUD can also show what the
    AI was choosing between.
    """

    winning: Verb | None
    pending: tuple[Verb, ...]


class AgentLoop:
    def __init__(self, gamepad: VirtualGamepad) -> None:
        self._gamepad = gamepad
        self._verb_state = VerbState(winning=None, pending=())
        self._state_lock = threading.Lock()
        # Cross-tick memory for Nora.ticks_since_last_attack -- see
        # observe.NoraAttackTracker. One per AgentLoop, matching the
        # per-player granularity every other piece of per-tick state here
        # already uses (e.g. VirtualGamepad's own steer_x).
        self._nora_tracker = NoraAttackTracker()

    def inform_hud(self, context: Context, *, pending: tuple[Verb, ...] = ()) -> None:
        """Copy the current tick's verbs into the thread-safe HUD state.

        ``context`` is the post-collapse context (at most one ``Verb``);
        ``pending`` carries the pre-collapse candidate list so the HUD can
        also show what the AI was choosing between. Callers may also pass an
        empty context (e.g. right after disabling the agent) to clear it.
        """

        verbs = tuple(find_all(context, Verb))
        winning = verbs[0] if verbs else None
        with self._state_lock:
            self._verb_state = VerbState(winning=winning, pending=pending)

    def verb_state(self) -> VerbState:
        with self._state_lock:
            return self._verb_state

    def tick(self, snapshot: GameSnapshot, *, player_index: int) -> Verb | None:
        """Run one iteration and return the winning ``Verb``, if any.

        The return value is purely informational (e.g. for a HUD to show
        what the AI is doing) — callers must not feed it back into the
        pipeline; ``execute_tick`` has already run by the time it comes
        back, and may have overridden the returned ``Verb`` with a pit
        escape (``execute.execute_tick``'s own docstring). The HUD's
        canonical source is ``verb_state()``, which ``inform_hud`` fills
        every tick.
        """

        if (
            snapshot.paused
            or not snapshot.timer_valid
            or not snapshot.players[player_index - 1].is_playable
        ):
            self._gamepad.release()
            self.inform_hud(set())
            return None

        context = generate_direct_observation_tokens(
            snapshot, player_index=player_index, nora_tracker=self._nora_tracker
        )
        context |= generate_inference_tokens(context)
        context |= generate_verb_tokens(context)
        pending = tuple(find_all(context, Verb))
        context = determine_priority_verb(context)
        self.inform_hud(context, pending=pending)

        verbs = find_all(context, Verb)
        verb = verbs[0] if verbs else None
        execute_tick(verb, context, self._gamepad)
        return verb
