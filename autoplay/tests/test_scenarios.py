"""Controlled live-scenario setup tests."""

from __future__ import annotations

import unittest

from sor_autoplay.scenarios import (
    DEFAULT_RNG_SEED,
    FRAME_PHASE,
    GAME_STATE,
    P1_CHARACTER_ID,
    P1_CHARACTER_ID_INGAME,
    P1_HEALTH,
    P1_OBJECT,
    RNG_STATE,
    reach_round1_start,
)


class _ScenarioClient:
    def __init__(self) -> None:
        self.restarted = False
        self.presses: list[int] = []
        self.lockstep: list[bool] = []
        self.writes: list[tuple[int, bytes]] = []

    def ping(self) -> None:
        pass

    def restart_game(self, *, timeout_ms: int) -> None:
        self.restarted = timeout_ms > 0

    def wait_memory_equals(
        self,
        address: int,
        expected: int,
        *,
        width: int,
        timeout_ms: int,
    ) -> int:
        del address, width, timeout_ms
        return expected

    def press_buttons(
        self,
        *,
        player1: int,
        frames: int,
        timeout_ms: int,
    ) -> None:
        assert frames == 2 and timeout_ms > 0
        self.presses.append(player1)

    def wait_vsync(self, frames: int, *, timeout_ms: int) -> None:
        assert frames == 2 and timeout_ms > 0

    def read_value(self, address: int, *, width: int) -> int:
        del width
        return {
            GAME_STATE: 0x16,
            P1_CHARACTER_ID: 2,
            P1_CHARACTER_ID_INGAME: 2,
            P1_HEALTH: 80,
            P1_OBJECT: 1,
        }[address]

    def read_memory(self, address: int, length: int) -> bytes:
        assert address == 0xFF0000 and length == 0x10000
        return bytes(length)

    def write_memory(self, address: int, data: bytes) -> None:
        self.writes.append((address, data))

    def set_lockstep(self, enabled: bool) -> None:
        self.lockstep.append(enabled)


class ScenarioTests(unittest.TestCase):
    def test_round1_setup_freezes_same_connection_after_verification(self) -> None:
        client = _ScenarioClient()
        observed = reach_round1_start(client, "blaze")
        self.assertTrue(client.restarted)
        self.assertEqual(client.presses, [0x80, 0x80, 0x20, 0x04, 0x20])
        self.assertEqual(client.lockstep, [True])
        self.assertEqual(
            client.writes,
            [
                (RNG_STATE, DEFAULT_RNG_SEED.to_bytes(4, "big")),
                (FRAME_PHASE, b"\x00\x00"),
            ],
        )
        self.assertEqual(observed["character"], "blaze")
        self.assertEqual(observed["health"], 80)
        self.assertEqual(observed["rng_seed"], DEFAULT_RNG_SEED)
        self.assertEqual(
            observed["work_ram_sha256"],
            "de2f256064a0af797747c2b97505dc0b9f3df0de4f489eac731c23ae9ca9cc31",
        )


if __name__ == "__main__":
    unittest.main()
