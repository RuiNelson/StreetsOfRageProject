"""Repeatable live-game setup for autoplay evaluation scenarios."""

from __future__ import annotations

import hashlib
from typing import Protocol


GAME_STATE = 0xFFFF00
LEVEL = 0xFFFF02
P1_CHARACTER_ID = 0xFFFF1E
P1_OBJECT = 0xFFB800
P1_HEALTH = 0xFFB832
SELECT_MENU_CURSOR = 0xFFB840
P1_CHARACTER_ID_INGAME = 0xFFB850
P1_CHAR_SLOT = 0xFFB858
LEVEL_INTRO_ACTIVE = 0xFFFA1F
SELECT_SCREEN_SUBSTATE = 0xFFFB0E
CHAR_SELECT_SUBSTATE = 0xFFF904
PLAY_SE = 0xFFF00A
# The 68000 assembly sign-extends these as $FFFFFF40/$FFFFFB08. The remote
# protocol accepts 24-bit system-bus addresses.
RNG_STATE = 0xFFFF40
FRAME_PHASE = 0xFFFB08

STORY_UPDATE = 0x0006
TITLE_UPDATE = 0x000A
MENU_UPDATE = 0x0012
CHARACTER_SELECT_UPDATE = 0x0022
LEVEL_INTRO_UPDATE = 0x002A
GAMEPLAY_UPDATE = 0x0016
MENU_INPUT_SUBSTATE = 0x0002
CHARACTER_INPUT_SUBSTATE = 0x0004
FULL_HEALTH = 0x0050
SPAWN_COMPLETE_SOUND_ID = 0x00A1
DEFAULT_RNG_SEED = 0x2A6D365A
DEFAULT_FRAME_PHASE = 0

CHARACTERS = {
    "adam": {"slot": 0, "id": 1, "direction": 0},
    "axel": {"slot": 1, "id": 0, "direction": 0x08},
    "blaze": {"slot": 2, "id": 2, "direction": 0x04},
}


class ScenarioClient(Protocol):
    def ping(self) -> object: ...

    def restart_game(self, *, timeout_ms: int) -> object: ...

    def wait_memory_equals(
        self,
        address: int,
        expected: int,
        *,
        width: int,
        timeout_ms: int,
    ) -> int: ...

    def press_buttons(
        self,
        *,
        player1: int,
        frames: int,
        timeout_ms: int,
    ) -> object: ...

    def wait_vsync(self, frames: int, *, timeout_ms: int) -> object: ...

    def read_value(self, address: int, *, width: int) -> int: ...

    def read_memory(self, address: int, length: int) -> bytes: ...

    def write_memory(self, address: int, data: bytes) -> None: ...

    def set_lockstep(self, enabled: bool) -> object: ...

    def trigger_option_hotkey(self, key: str) -> object: ...


def _wait(
    game: ScenarioClient,
    address: int,
    expected: int,
    *,
    width: int,
    timeout_ms: int,
) -> None:
    game.wait_memory_equals(
        address,
        expected,
        width=width,
        timeout_ms=timeout_ms,
    )


def _tap(
    game: ScenarioClient,
    button: int,
    *,
    timeout_ms: int,
) -> None:
    # Two held frames are reliable on the local host; two released frames make
    # the next press a fresh ROM +$55 edge.
    game.press_buttons(player1=button, frames=2, timeout_ms=timeout_ms)
    game.wait_vsync(2, timeout_ms=timeout_ms)


def reach_round1_start(
    game: ScenarioClient,
    character: str,
    *,
    timeout_ms: int = 30_000,
    rng_seed: int = DEFAULT_RNG_SEED,
    frame_phase: int = DEFAULT_FRAME_PHASE,
) -> dict[str, object]:
    """Restart, navigate menus, then freeze at a verified Round-1 start."""

    choice = CHARACTERS[character]
    game.ping()
    game.restart_game(timeout_ms=timeout_ms)

    _wait(game, GAME_STATE, STORY_UPDATE, width=2, timeout_ms=timeout_ms)
    _tap(game, 0x80, timeout_ms=timeout_ms)  # Start
    _wait(game, GAME_STATE, TITLE_UPDATE, width=2, timeout_ms=timeout_ms)
    _tap(game, 0x80, timeout_ms=timeout_ms)
    _wait(game, GAME_STATE, MENU_UPDATE, width=2, timeout_ms=timeout_ms)
    _wait(
        game,
        SELECT_SCREEN_SUBSTATE,
        MENU_INPUT_SUBSTATE,
        width=2,
        timeout_ms=timeout_ms,
    )
    _wait(game, SELECT_MENU_CURSOR, 0, width=2, timeout_ms=timeout_ms)
    _tap(game, 0x20, timeout_ms=timeout_ms)  # B confirms in standard scheme

    _wait(
        game,
        GAME_STATE,
        CHARACTER_SELECT_UPDATE,
        width=2,
        timeout_ms=timeout_ms,
    )
    _wait(
        game,
        CHAR_SELECT_SUBSTATE,
        CHARACTER_INPUT_SUBSTATE,
        width=2,
        timeout_ms=timeout_ms,
    )
    direction = int(choice["direction"])
    if direction:
        _tap(game, direction, timeout_ms=timeout_ms)
    _wait(game, P1_CHAR_SLOT, int(choice["slot"]), width=2, timeout_ms=timeout_ms)
    _tap(game, 0x20, timeout_ms=timeout_ms)

    _wait(game, GAME_STATE, LEVEL_INTRO_UPDATE, width=2, timeout_ms=timeout_ms)
    _wait(game, GAME_STATE, GAMEPLAY_UPDATE, width=2, timeout_ms=timeout_ms)
    _wait(game, LEVEL_INTRO_ACTIVE, 0, width=1, timeout_ms=timeout_ms)
    _wait(game, PLAY_SE, SPAWN_COMPLETE_SOUND_ID, width=1, timeout_ms=timeout_ms)
    game.wait_vsync(2, timeout_ms=timeout_ms)

    observed = {
        "name": "round1-start",
        "character": character,
        "character_id": game.read_value(P1_CHARACTER_ID_INGAME, width=1),
        "health": game.read_value(P1_HEALTH, width=2),
        "game_state": game.read_value(GAME_STATE, width=2),
        "player_object_type": game.read_value(P1_OBJECT, width=1),
    }
    persistent_character = game.read_value(P1_CHARACTER_ID, width=1)
    expected_id = int(choice["id"])
    if (
        observed["game_state"] != GAMEPLAY_UPDATE
        or observed["character_id"] != expected_id
        or persistent_character != expected_id
        or observed["health"] != FULL_HEALTH
        or observed["player_object_type"] != 1
    ):
        raise RuntimeError(f"Round-1 scenario verification failed: {observed}")

    # Freeze before seeding the two ROM values whose menu-time history affects
    # enemy decisions. The AI itself still uses ordinary controller input.
    game.set_lockstep(True)
    game.write_memory(RNG_STATE, rng_seed.to_bytes(4, "big"))
    game.write_memory(FRAME_PHASE, frame_phase.to_bytes(2, "big"))
    observed["rng_seed"] = rng_seed
    observed["frame_phase"] = frame_phase
    observed["work_ram_sha256"] = hashlib.sha256(
        game.read_memory(0xFF0000, 0x10000)
    ).hexdigest()
    return observed


def reach_level_start(
    game: ScenarioClient,
    character: str,
    level_number: int,
    *,
    timeout_ms: int = 30_000,
    rng_seed: int = DEFAULT_RNG_SEED,
    frame_phase: int = DEFAULT_FRAME_PHASE,
) -> dict[str, object]:
    """Reach a deterministic level start through the host's debug hotkey.

    Character selection still follows the real menus. Levels 2–8 then use the
    same Alt/Option digit action exposed by ``--debugUtils`` and the remote
    client, wait for the complete level-intro/gameplay transition, and freeze
    on the same connection used by the evaluator.
    """

    if not 1 <= level_number <= 8:
        raise ValueError("level_number must be in 1..8")
    if level_number == 1:
        return reach_round1_start(
            game,
            character,
            timeout_ms=timeout_ms,
            rng_seed=rng_seed,
            frame_phase=frame_phase,
        )

    observed = reach_round1_start(
        game,
        character,
        timeout_ms=timeout_ms,
        rng_seed=rng_seed,
        frame_phase=frame_phase,
    )
    game.set_lockstep(False)
    game.trigger_option_hotkey(str(level_number))
    _wait(game, GAME_STATE, LEVEL_INTRO_UPDATE, width=2, timeout_ms=timeout_ms)
    _wait(game, GAME_STATE, GAMEPLAY_UPDATE, width=2, timeout_ms=timeout_ms)
    _wait(game, LEVEL_INTRO_ACTIVE, 0, width=1, timeout_ms=timeout_ms)
    _wait(game, PLAY_SE, SPAWN_COMPLETE_SOUND_ID, width=1, timeout_ms=timeout_ms)
    game.wait_vsync(2, timeout_ms=timeout_ms)

    level_index = game.read_value(LEVEL, width=2)
    if level_index != level_number - 1:
        raise RuntimeError(
            f"Round-{level_number} scenario verification failed: "
            f"level index is {level_index}"
        )

    game.set_lockstep(True)
    game.write_memory(RNG_STATE, rng_seed.to_bytes(4, "big"))
    game.write_memory(FRAME_PHASE, frame_phase.to_bytes(2, "big"))
    observed.update(
        {
            "name": f"round{level_number}-start",
            "level_number": level_number,
            "level_index": level_index,
            "rng_seed": rng_seed,
            "frame_phase": frame_phase,
            "work_ram_sha256": hashlib.sha256(
                game.read_memory(0xFF0000, 0x10000)
            ).hexdigest(),
        }
    )
    return observed
