"""Virtual gamepad over the remote link's sticky button latch.

``MegaDriveClient`` can hold, press, and release controller buttons but
cannot report which buttons are currently pressed (see
``MegaDriveEnvironment/docs/remote-access-protocol.md``), so this module is
the single source of truth for "what are we currently holding" per player.
It only ever calls ``hold_buttons`` / ``press_buttons`` / ``release_buttons``
on the client — never ``write_memory`` / ``write_value``.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from megadrive_remote import Buttons

# Buttons.NONE without importing the enum at runtime (see module docstring
# on the codebase's convention of deferring the megadrive_remote import).
NONE_MASK = 0


class ButtonClient(Protocol):
    """The subset of ``MegaDriveClient`` the virtual gamepad needs."""

    def hold_buttons(
        self, *, player1: "Buttons | int" = 0, player2: "Buttons | int" = 0
    ) -> None: ...

    def press_buttons(
        self,
        *,
        player1: "Buttons | int" = 0,
        player2: "Buttons | int" = 0,
        frames: int = 1,
    ) -> None: ...


def _validate_player_index(player_index: int) -> None:
    if player_index not in (1, 2):
        raise ValueError("player_index must be 1 or 2")


class SharedGamepadState:
    """Coordinates both players' held masks over one ``hold_buttons`` link.

    ``HOLD_BUTTONS`` always latches *both* player masks in a single remote
    call — a per-player caller that only names its own mask would silently
    reset the other player's held mask to none (``PRESS_BUTTONS`` masks the
    unnamed player independently, but the sticky hold latch does not). When
    both players are AI-controlled, their two :class:`VirtualGamepad` views
    must share one instance of this so neither call clobbers the other's
    latch.
    """

    def __init__(self, client: ButtonClient) -> None:
        self._client = client
        self._held: dict[int, int] = {1: NONE_MASK, 2: NONE_MASK}
        # ObserverApp drives this from both the background poll thread (AI
        # ticks) and the Tk UI thread (HUD toggle clicks); RLock because
        # release() re-enters hold() on the same thread.
        self._lock = threading.RLock()

    def held(self, player_index: int) -> int:
        _validate_player_index(player_index)
        with self._lock:
            return self._held[player_index]

    def hold(self, player_index: int, mask: "Buttons | int") -> None:
        _validate_player_index(player_index)
        mask = int(mask)
        with self._lock:
            if self._held[player_index] == mask:
                return
            self._held[player_index] = mask
            self._client.hold_buttons(player1=self._held[1], player2=self._held[2])

    def release(self, player_index: int) -> None:
        self.hold(player_index, NONE_MASK)

    def press(self, player_index: int, mask: "Buttons | int", *, frames: int = 1) -> None:
        _validate_player_index(player_index)
        with self._lock:
            if player_index == 1:
                self._client.press_buttons(player1=mask, frames=frames)
            else:
                self._client.press_buttons(player2=mask, frames=frames)

    def reset(self) -> None:
        """Resync cached masks to none, without sending a command.

        Call this after establishing a fresh remote connection: the new
        connection's remote latch already starts empty, so re-sending a
        stale cached mask is unnecessary, and treating an unchanged mask as
        a no-op (the normal ``hold`` behavior) would otherwise skip
        re-arming it after a reconnect.
        """

        with self._lock:
            self._held = {1: NONE_MASK, 2: NONE_MASK}


class VirtualGamepad:
    """One player's view over a shared :class:`SharedGamepadState`."""

    def __init__(self, state: SharedGamepadState, *, player_index: int) -> None:
        _validate_player_index(player_index)
        self._state = state
        self._player_index = player_index

    @property
    def player_index(self) -> int:
        return self._player_index

    @property
    def held(self) -> int:
        return self._state.held(self._player_index)

    def hold(self, mask: "Buttons | int") -> None:
        self._state.hold(self._player_index, mask)

    def release(self) -> None:
        self._state.release(self._player_index)

    def press(self, mask: "Buttons | int", *, frames: int = 1) -> None:
        self._state.press(self._player_index, mask, frames=frames)
