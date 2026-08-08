"""Navigate real Streets of Rage menus to playable gameplay, joypad-only.

Drives the same Start/A/direction taps a human would use, observed through
bounded ``wait_memory_equals`` calls -- never writes RAM. This is a native
reimplementation (not an import) of the same approach as
``StreetsOfRageRecompilation/tools/reach_gameplay.py``, kept in this package
so ``sor_autoplay``'s ``--reach-gameplay`` flag has no cross-repository
runtime dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from . import memory_map as mm

START_MASK = 0x0080
A_MASK = 0x0010
LEFT_MASK = 0x0004
RIGHT_MASK = 0x0008

STORY_UPDATE = 0x0006
TITLE_UPDATE = 0x000A
MENU_UPDATE = 0x0012
CHARACTER_SELECT_UPDATE = 0x0022
LEVEL_INTRO_UPDATE = 0x002A
GAMEPLAY_UPDATE = 0x0016
MENU_INPUT_SUBSTATE = 0x0002
CHARACTER_INPUT_SUBSTATE = 0x0004
SPAWN_COMPLETE_SOUND_ID = 0x00A1
TAP_FRAMES = 3
# Settle window after a character-select cursor move before confirming, so
# the confirm press doesn't land during the cursor/preview's own transition.
CHARACTER_CONFIRM_SETTLE_VSYNCS = 6

# Character-select screen order is Adam, Axel, Blaze; persistent character
# IDs use the game's Axel/Adam/Blaze order (see memory_map.CHARACTER_NAMES).
CHARACTERS = {
    "adam": {"slot": 0, "id": 1, "direction": None},
    "axel": {"slot": 1, "id": 0, "direction": RIGHT_MASK},
    "blaze": {"slot": 2, "id": 2, "direction": LEFT_MASK},
}


class NavigationClient(Protocol):
    """The subset of ``MegaDriveClient`` menu navigation needs."""

    def ping(self) -> None: ...

    def restart_game(self, *, timeout_ms: int) -> None: ...

    def press_buttons(
        self, *, player1: int = 0, player2: int = 0, frames: int = 1, timeout_ms: int | None = None
    ) -> None: ...

    def wait_vsync(self, count: int = 1, *, timeout_ms: int | None = None) -> None: ...

    def wait_memory_equals(
        self,
        address: int,
        expected: int,
        *,
        width: int = 1,
        mask: int | None = None,
        timeout_ms: int = 1_000,
    ) -> int: ...

    def read_value(self, address: int, width: int = 1) -> int: ...


@dataclass(frozen=True, slots=True)
class ReachGameplayResult:
    character: str
    character_id: int
    game_state: int
    health: int
    player_object_type: int


class ReachGameplayError(RuntimeError):
    """Raised when navigation completes but the game is not in the expected state."""


def _tap(client: NavigationClient, button: int, *, timeout_ms: int) -> None:
    """Press one P1 button for one frame, then observe one released frame."""

    # A 1-frame press raced the ROM's per-frame press-edge sampling under
    # real (non-lockstep) wall-clock timing and occasionally missed the
    # character-select confirm entirely; a few frames is still a "tap" (the
    # edge only fires once) but no longer frame-perfect.
    client.press_buttons(player1=button, frames=TAP_FRAMES, timeout_ms=timeout_ms)
    client.wait_vsync(1, timeout_ms=timeout_ms)


def _wait(client: NavigationClient, address: int, expected: int, *, width: int, timeout_ms: int) -> None:
    client.wait_memory_equals(address, expected, width=width, timeout_ms=timeout_ms)


def reach_gameplay(
    client: NavigationClient, character: str, *, timeout_ms: int = 30_000
) -> ReachGameplayResult:
    """Restart and navigate the real menus to one-player gameplay as ``character``.

    Uses only joypad input (Start/A/direction taps) and bounded RAM waits --
    the same path a human would take -- and never writes RAM.
    """

    character = character.lower()
    if character not in CHARACTERS:
        raise ValueError(f"unknown character {character!r}; choose from {sorted(CHARACTERS)}")
    choice = CHARACTERS[character]

    client.ping()
    client.restart_game(timeout_ms=timeout_ms)

    # The Sega logo has no Start skip; the first observable state is story.
    _wait(client, mm.ADDR_GAME_STATE, STORY_UPDATE, width=2, timeout_ms=timeout_ms)
    _tap(client, START_MASK, timeout_ms=timeout_ms)

    _wait(client, mm.ADDR_GAME_STATE, TITLE_UPDATE, width=2, timeout_ms=timeout_ms)
    _tap(client, START_MASK, timeout_ms=timeout_ms)

    _wait(client, mm.ADDR_GAME_STATE, MENU_UPDATE, width=2, timeout_ms=timeout_ms)
    _wait(client, mm.ADDR_SELECT_SCREEN_SUBSTATE, MENU_INPUT_SUBSTATE, width=2, timeout_ms=timeout_ms)
    _wait(client, mm.ADDR_SELECT_MENU_CURSOR, 0, width=2, timeout_ms=timeout_ms)
    _tap(client, A_MASK, timeout_ms=timeout_ms)

    _wait(client, mm.ADDR_GAME_STATE, CHARACTER_SELECT_UPDATE, width=2, timeout_ms=timeout_ms)
    _wait(client, mm.ADDR_CHAR_SELECT_SUBSTATE, CHARACTER_INPUT_SUBSTATE, width=2, timeout_ms=timeout_ms)

    direction = choice["direction"]
    if direction is not None:
        _tap(client, direction, timeout_ms=timeout_ms)
    _wait(client, mm.ADDR_CHAR_SELECT_SLOT, int(choice["slot"]), width=2, timeout_ms=timeout_ms)
    client.wait_vsync(CHARACTER_CONFIRM_SETTLE_VSYNCS, timeout_ms=timeout_ms)
    _tap(client, A_MASK, timeout_ms=timeout_ms)

    # Do not skip the level intro: it performs the normal music/campaign setup.
    _wait(client, mm.ADDR_GAME_STATE, LEVEL_INTRO_UPDATE, width=2, timeout_ms=timeout_ms)
    _wait(client, mm.ADDR_GAME_STATE, GAMEPLAY_UPDATE, width=2, timeout_ms=timeout_ms)
    _wait(client, mm.ADDR_LEVEL_INTRO_ACTIVE, 0, width=1, timeout_ms=timeout_ms)

    # The player can exist in gameplay RAM before the entrance animation has
    # finished; its landing queues sound $A1.
    _wait(client, mm.ADDR_PLAY_SE, SPAWN_COMPLETE_SOUND_ID, width=1, timeout_ms=timeout_ms)
    client.wait_vsync(2, timeout_ms=timeout_ms)

    observed_character = client.read_value(mm.ADDR_P1_OBJECT + mm.OBJ_CHARACTER_ID, width=1)
    persistent_character = client.read_value(mm.ADDR_P1_CHARACTER_ID, width=1)
    observed_health = client.read_value(mm.ADDR_P1_OBJECT + mm.OBJ_HEALTH, width=2)
    observed_object = client.read_value(mm.ADDR_P1_OBJECT + mm.OBJ_TYPE, width=1)
    observed_state = client.read_value(mm.ADDR_GAME_STATE, width=2)
    music_voice_bank = client.read_value(mm.ADDR_SOUND_MUSIC_VOICE_BANK, width=4)

    expected_id = int(choice["id"])
    if observed_state != GAMEPLAY_UPDATE:
        raise ReachGameplayError(f"game left gameplay state: 0x{observed_state:04X}")
    if persistent_character != expected_id or observed_character != expected_id:
        raise ReachGameplayError(
            f"expected {character} id {expected_id}, observed "
            f"persistent={persistent_character}, in_game={observed_character}"
        )
    if observed_object != mm.OBJ_TYPE_ACTIVE_PLAYER or observed_health != mm.MAX_HEALTH:
        raise ReachGameplayError(
            "player was not fully initialized: "
            f"object={observed_object}, health=0x{observed_health:04X}"
        )
    if music_voice_bank == 0:
        raise ReachGameplayError("gameplay music did not initialize a voice bank")

    return ReachGameplayResult(
        character=character,
        character_id=observed_character,
        game_state=observed_state,
        health=observed_health,
        player_object_type=observed_object,
    )
