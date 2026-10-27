"""Host mode flags the running ``sor`` publishes through ``GET_FLAGS``.

``MegaDriveEnvironment`` keeps 1024 game-defined flags (128 bytes, flag *n* is
bit ``n % 8`` of byte ``n // 8``); what each one means belongs to the game. The
indices below must match ``StreetsOfRageRecompilation/main.cpp``.
"""

from __future__ import annotations

from dataclasses import dataclass

FLAG_WIDESCREEN = 0  # --widescreen: Mode 48, 384 px wide
FLAG_SIX_BUTTON = 1  # --altControls: the 6-button layout

FLAG_BYTES = 128


@dataclass(frozen=True)
class HostModes:
    widescreen: bool = False
    six_button: bool = False


def flag_set(flags: bytes, index: int) -> bool:
    return bool(flags[index // 8] >> (index % 8) & 1)


def decode_host_modes(flags: bytes) -> HostModes:
    if len(flags) != FLAG_BYTES:
        raise ValueError(f"flags must be {FLAG_BYTES} bytes, got {len(flags)}")
    return HostModes(
        widescreen=flag_set(flags, FLAG_WIDESCREEN),
        six_button=flag_set(flags, FLAG_SIX_BUTTON),
    )
