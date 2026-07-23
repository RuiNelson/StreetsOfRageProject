from __future__ import annotations

import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    import numpy as np

    from ai_play.actions import A, RIGHT
    from ai_play.environment import (
        EnvironmentConfig,
        LaunchPortUnavailableError,
        StreetsOfRageEnv,
        ensure_launch_port_available,
    )
    from ai_play.event_detector import (
        GAME_STATE,
        P1_HEALTH,
        P1_LIVES,
        PLAYER_MODE,
        WORK_RAM_BASE,
        WORK_RAM_SIZE,
    )

    TRAINING_AVAILABLE = True
except ModuleNotFoundError:
    TRAINING_AVAILABLE = False


def _write(ram: bytearray, address: int, value: int, width: int) -> None:
    offset = address - WORK_RAM_BASE
    ram[offset : offset + width] = value.to_bytes(width, "big")


def _ram(lives: int) -> bytes:
    ram = bytearray(WORK_RAM_SIZE)
    _write(ram, GAME_STATE, 0x16, 2)
    _write(ram, PLAYER_MODE, 1, 1)
    _write(ram, P1_HEALTH, 80, 2)
    _write(ram, P1_LIVES, lives, 1)
    return bytes(ram)


class _FakeGame:
    def __init__(self) -> None:
        self.frame = 0
        self.ram = _ram(0x03)
        self.lockstep: list[bool] = []
        self.step_calls: list[dict[str, int]] = []
        self.closed = False

    def set_lockstep(self, enabled: bool) -> None:
        self.lockstep.append(enabled)

    def read_memory(self, address: int, length: int) -> bytes:
        assert (address, length) == (WORK_RAM_BASE, WORK_RAM_SIZE)
        return self.ram

    def get_game_uptime_frames(self) -> int:
        return self.frame

    def step_input(self, **arguments: int) -> SimpleNamespace:
        self.step_calls.append(arguments)
        self.frame += arguments["total_frames"]
        self.ram = _ram(0x00)
        return SimpleNamespace(frame=self.frame, work_ram=self.ram)

    def close(self) -> None:
        self.closed = True


@unittest.skipUnless(TRAINING_AVAILABLE, "training dependencies are not installed")
class EnvironmentTests(unittest.TestCase):
    def test_rejects_an_occupied_launch_port_before_starting(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(
                LaunchPortUnavailableError,
                rf"TCP port {port} is already in use",
            ):
                ensure_launch_port_available(port)

    def test_atomic_step_reuses_ram_and_ends_after_three_lives(self) -> None:
        game = _FakeGame()
        env = StreetsOfRageEnv(EnvironmentConfig(max_episode_steps=100))
        env._game = game
        ready = {
            "character": "blaze",
            "character_id": 2,
            "game_state": 0x16,
            "health": 80,
        }
        with patch("ai_play.environment._load_reach_gameplay", return_value=lambda *_a, **_k: ready):
            observation, info = env.reset()

        self.assertEqual(observation.dtype, np.uint8)
        self.assertEqual(observation.shape, (WORK_RAM_SIZE,))
        self.assertEqual(info["character"], "blaze")
        self.assertEqual(game.lockstep, [True])

        action = np.asarray((1, 0, 1, 0.75, 0, 0, 0), dtype=np.float32)
        observation, reward, terminated, truncated, info = env.step(action)
        self.assertEqual(
            game.step_calls,
            [
                {
                    "player1": RIGHT | A,
                    "player2": 0,
                    "held_frames": 12,
                    "total_frames": 12,
                    "timeout_ms": 5_000,
                }
            ],
        )
        self.assertEqual(observation.shape, (WORK_RAM_SIZE,))
        self.assertEqual(reward, -30.0)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["episode_end"], "three_lives_lost")
        self.assertEqual(info["lives_lost"], 3)

        env.close()
        self.assertEqual(game.lockstep, [True, False])
        self.assertTrue(game.closed)


if __name__ == "__main__":
    unittest.main()
