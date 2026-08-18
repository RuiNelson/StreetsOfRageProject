"""``AgentLoop`` — one player's iteration of ``AI.md``'s process loop.

``tick`` never fetches RAM itself; it consumes an already-polled
``GameSnapshot`` (see ``sor_autoplay.state.read_snapshot``), matching the
observer's existing single-poll-per-tick discipline.

``inform_hud`` implements AI.md's UI step: it copies the surviving
``Verb`` (and every candidate that preceded it) into a thread-safe
``VerbState`` that the observer's Tk thread reads for the HUD.

``_nora_tracker`` and ``_hold_tracker`` are the pieces of state that survive
across ticks besides the virtual gamepad's own sticky hold -- see
``observe.NoraAttackTracker`` and ``observe.HoldTracker``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from sor_autoplay.state import GameSnapshot

from .decide import generate_verb_tokens
from .execute import execute_tick
from .gamepad import VirtualGamepad
from .inference import generate_inference_tokens
from .observe import HoldTracker, NoraAttackTracker, generate_direct_observation_tokens
from .pathfind import Path
from .priority import determine_priority_verb
from .tokens import Context, Myself, Verb, find, find_all


@dataclass(frozen=True, slots=True, kw_only=True)
class VerbState:
    """Thread-safe snapshot of one player's last tick, for the HUD.

    ``winning`` is the ``Verb`` that survived
    ``determine_priority_verb`` and that ``execute_verb`` is (about
    to be) carrying out. ``pending`` holds every candidate ``Verb`` the
    tick considered before that collapse, so the HUD can also show what the
    AI was choosing between.

    ``route`` is the path finder's own plan for this tick, when ``winning``
    was a verb that routes (``WalkToNearEnemy``, ``OpenBreakable`` today) --
    ``None`` for every other verb, not an empty path, so the HUD can tell
    "nothing to route" from "routed and found no way through".
    """

    winning: Verb | None
    pending: tuple[Verb, ...]
    route: Path | None = None


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
        # Cross-tick memory for PlayableCharacter.hold_ticks -- see
        # observe.HoldTracker. Same per-AgentLoop granularity as above.
        self._hold_tracker = HoldTracker()

    def inform_hud(
        self,
        context: Context,
        *,
        pending: tuple[Verb, ...] = (),
        route: Path | None = None,
    ) -> None:
        """Copy the current tick's verbs into the thread-safe HUD state.

        ``context`` is the post-collapse context (at most one ``Verb``);
        ``pending`` carries the pre-collapse candidate list so the HUD can
        also show what the AI was choosing between. Callers may also pass an
        empty context (e.g. right after disabling the agent) to clear it --
        which clears ``route`` too, since an empty context has no actor for
        one to belong to.

        ``route`` is the path finder's plan for this tick (``execute_tick``'s
        own ``route_trace``, already filtered down to this actor's slot) --
        ``None`` unless ``winning`` was a verb that actually routes.
        """

        verbs = tuple(find_all(context, Verb))
        winning = verbs[0] if verbs else None
        with self._state_lock:
            self._verb_state = VerbState(winning=winning, pending=pending, route=route)

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

        player = snapshot.players[player_index - 1]
        # Continue / name-entry replaces the playable object with type $0F,
        # so is_playable is false -- but the pipeline still has to answer
        # Yes and type the initials. Mr. X's offer keeps the player playable.
        in_continue_ui = player.is_continue_ui
        if snapshot.paused:
            self._gamepad.release()
            self.inform_hud(set())
            return None
        if not in_continue_ui and (not snapshot.timer_valid or not player.is_playable):
            self._gamepad.release()
            self.inform_hud(set())
            return None

        context = generate_direct_observation_tokens(
            snapshot,
            player_index=player_index,
            nora_tracker=self._nora_tracker,
            hold_tracker=self._hold_tracker,
        )
        context |= generate_inference_tokens(context)
        context |= generate_verb_tokens(context)
        pending = tuple(find_all(context, Verb))
        context = determine_priority_verb(context)

        verbs = find_all(context, Verb)
        verb = verbs[0] if verbs else None

        # A route only exists once execute_tick has actually planned one, so
        # inform_hud waits until after this call -- the HUD reads verb_state()
        # from a different thread under its own lock, so the brief delay
        # within one tick is invisible to it.
        route_trace: dict[str, Path] = {}
        execute_tick(verb, context, self._gamepad, route_trace=route_trace)

        myself = find(context, Myself)
        route = route_trace.get(myself.slot) if myself is not None else None
        self.inform_hud(context, pending=pending, route=route)
        return verb
