"""Debug-only scenario setup: start on a chosen level, keep one enemy family.

**Not part of the AI.** The AI reaches the game exclusively through
``ai/gamepad.py``'s controller input and never writes RAM; nothing here is
visible to the token pipeline. This module drives the *host's own* debug
hotkeys -- the ones a human presses with Alt/Option while ``sor`` runs with
``--debugUtils`` -- through ``MegaDriveClient.trigger_option_hotkey``, so the
cheat logic itself stays in the C++ host where it already lives
(``StreetsOfRage::handleOptionHotkey``).

It exists to make one enemy testable in isolation: an enemy that only spawns
from level 2 onward, mixed into waves with three other families, cannot be
measured against without first getting there and then removing the noise.
Both halves are needed together -- jumping to the level puts the AI in front
of the right waves, and the repeated family sweep keeps everything else off
the screen for as long as the session lasts, since each wave respawns.
"""

from __future__ import annotations

import time
from typing import Protocol

# The host's per-family kill cheats (StreetsOfRage.cpp's handleOptionHotkey).
# Keys are this module's own family names, values the letter the host binds.
ENEMY_FAMILY_HOTKEYS: dict[str, str] = {
    "garcia": "G",   # types $20-$23
    "hakuro": "N",   # types $25/$2A, the ninja
    "signal": "B",   # type $24
    "jack": "J",     # type $27
    "nora": "U",     # type $26
}

# Levels are the host's own top-row number keys, 1-8.
LEVEL_COUNT = 8

# How often the family sweep runs. Each wave spawns its enemies fresh, so the
# sweep has to keep running for the whole session rather than once at startup;
# twice a second is far below the poll rate and still removes an unwanted
# spawn well before it can reach the actor.
DEFAULT_SWEEP_MS = 500


class HotkeyClient(Protocol):
    """The one remote call this module needs."""

    def trigger_option_hotkey(self, key: str) -> None: ...


def resolve_family(name: str) -> str:
    """Normalize a user-supplied family name, or raise ``ValueError``."""

    key = name.strip().lower().replace("-", "").replace("_", "")
    if key in ("hakuro", "ninja", "hokoru"):
        key = "hakuro"
    if key not in ENEMY_FAMILY_HOTKEYS:
        raise ValueError(
            f"unknown enemy family {name!r}; choose from "
            f"{sorted(ENEMY_FAMILY_HOTKEYS)}"
        )
    return key


class DebugScenario:
    """Applies ``--start-level`` once and ``--only-enemy`` continuously.

    Stateful on purpose: the level jump must happen exactly once (it resets
    the level and would otherwise restart it forever), and the family sweep is
    rate-limited rather than run every poll.
    """

    def __init__(
        self,
        *,
        start_level: int | None = None,
        only_enemy: str | None = None,
        kill_street_enemies: bool = False,
        sweep_ms: int = DEFAULT_SWEEP_MS,
    ) -> None:
        if start_level is not None and not 1 <= start_level <= LEVEL_COUNT:
            raise ValueError(f"start level must be 1..{LEVEL_COUNT}, got {start_level}")
        self.start_level = start_level
        self.only_enemy = resolve_family(only_enemy) if only_enemy else None
        self.kill_street_enemies = kill_street_enemies
        if self.kill_street_enemies and self.only_enemy is not None:
            raise ValueError("--kill-street-enemies cannot be combined with --only-enemy")
        self.sweep_ms = max(0, sweep_ms)
        self._level_jump_done = start_level is None
        self._last_sweep = 0.0

    @property
    def active(self) -> bool:
        return (
            self.start_level is not None
            or self.only_enemy is not None
            or self.kill_street_enemies
        )

    @property
    def level_jump_pending(self) -> bool:
        """True until the level jump has been requested.

        Callers should hold the AI off while this is pending: the jump throws
        away the level the actor is standing in, so any verb decided just
        before it is aimed at a scene that no longer exists.
        """

        return not self._level_jump_done

    def apply_start_level(self, client: HotkeyClient) -> bool:
        """Trigger the level jump once; returns True when it was sent now."""

        if self._level_jump_done or self.start_level is None:
            return False
        client.trigger_option_hotkey(str(self.start_level))
        self._level_jump_done = True
        return True

    def sweep_other_families(self, client: HotkeyClient, *, force: bool = False) -> bool:
        """Kill every family except the kept one, at most once per sweep window.

        Returns True when a sweep was actually sent. The kept family is never
        swept, and with no ``--only-enemy`` this does nothing at all.
        """

        if self.only_enemy is None and not self.kill_street_enemies:
            return False
        now = time.monotonic()
        if not force and (now - self._last_sweep) * 1000.0 < self.sweep_ms:
            return False
        self._last_sweep = now
        for family, key in ENEMY_FAMILY_HOTKEYS.items():
            if family == self.only_enemy:
                continue
            client.trigger_option_hotkey(key)
        return True
