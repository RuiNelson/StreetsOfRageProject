from __future__ import annotations

import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    import numpy as np

    from ai_play.actions import A, RIGHT, START
    from ai_play.environment import (
        EnvironmentConfig,
        LaunchPortUnavailableError,
        StreetsOfRageEnv,
        ensure_launch_port_available,
        should_skip_round_clear,
    )
    from ai_play.event_detector import (
        GAME_STATE,
        LEVEL,
        P1_HEALTH,
        P1_LIVES,
        PLAYER_MODE,
        ROUND_CLEAR_SUBSTATE,
        WORK_RAM_BASE,
        WORK_RAM_SIZE,
        WorkRamSnapshotReader,
    )

    TRAINING_AVAILABLE = True
except ModuleNotFoundError:
    TRAINING_AVAILABLE = False


def _write(ram: bytearray, address: int, value: int, width: int) -> None:
    offset = address - WORK_RAM_BASE
    ram[offset : offset + width] = value.to_bytes(width, "big")


def _ram(
    lives: int,
    *,
    game_state: int = 0x16,
    level: int = 0,
    round_clear_substate: int = 0,
) -> bytes:
    ram = bytearray(WORK_RAM_SIZE)
    _write(ram, GAME_STATE, game_state, 2)
    _write(ram, LEVEL, level, 2)
    _write(ram, PLAYER_MODE, 1, 1)
    _write(ram, P1_HEALTH, 80, 2)
    _write(ram, P1_LIVES, lives, 1)
    _write(ram, ROUND_CLEAR_SUBSTATE, round_clear_substate, 2)
    return bytes(ram)


class _FakeGame:
    def __init__(
        self,
        *,
        step_lives: tuple[int, ...] = (0x02, 0x01),
        step_timeout: bool = False,
    ) -> None:
        self.frame = 0
        self.ram = _ram(0x03)
        self.step_lives = step_lives
        self.step_timeout = step_timeout
        self.lockstep: list[bool] = []
        self.step_calls: list[dict[str, int]] = []
        self.closed = False

    def set_lockstep(self, enabled: bool, **_arguments: int) -> None:
        self.lockstep.append(enabled)

    def read_memory(self, address: int, length: int) -> bytes:
        assert (address, length) == (WORK_RAM_BASE, WORK_RAM_SIZE)
        return self.ram

    def get_game_uptime_frames(self) -> int:
        return self.frame

    def step_input(self, **arguments: int) -> SimpleNamespace:
        self.step_calls.append(arguments)
        if self.step_timeout:
            raise TimeoutError("timed out during lockstep step")
        self.frame += arguments["total_frames"]
        index = min(len(self.step_calls) - 1, len(self.step_lives) - 1)
        self.ram = _ram(self.step_lives[index])
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

    def test_reset_reconnects_after_a_transient_navigation_timeout(self) -> None:
        first_game = _FakeGame()
        second_game = _FakeGame()
        env = StreetsOfRageEnv(EnvironmentConfig(max_episode_steps=100))
        games = iter((first_game, second_game))

        def connect_next() -> _FakeGame:
            game = next(games)
            env._game = game
            return game

        navigation_attempts = 0

        def navigate(*_arguments, **_keywords):  # type: ignore[no-untyped-def]
            nonlocal navigation_attempts
            navigation_attempts += 1
            if navigation_attempts == 1:
                raise TimeoutError("transient menu timeout")
            return {"character": "blaze"}

        with (
            patch.object(env, "_connect", side_effect=connect_next),
            patch(
                "ai_play.environment._load_reach_gameplay",
                return_value=navigate,
            ),
            patch("builtins.print"),
        ):
            observation, info = env.reset()

        self.assertEqual(observation.shape, (WORK_RAM_SIZE,))
        self.assertEqual(info["character"], "blaze")
        self.assertEqual(navigation_attempts, 2)
        self.assertTrue(first_game.closed)
        self.assertEqual(second_game.lockstep, [True])
        env.close()

    def test_atomic_step_reuses_ram_and_ends_after_two_lives(self) -> None:
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

        action = np.asarray((1, 0, 1, 0.75, 0, 0), dtype=np.float32)
        observation, reward, terminated, truncated, info = env.step(action)
        self.assertEqual(reward, -10.0)
        self.assertFalse(terminated)
        self.assertFalse(truncated)

        observation, reward, terminated, truncated, info = env.step(action)
        self.assertEqual(
            game.step_calls,
            [
                {
                    "player1": RIGHT | A,
                    "player2": 0,
                    "held_frames": 12,
                    "total_frames": 12,
                    "timeout_ms": 30_000,
                },
                {
                    "player1": RIGHT | A,
                    "player2": 0,
                    "held_frames": 12,
                    "total_frames": 12,
                    "timeout_ms": 30_000,
                },
            ],
        )
        self.assertEqual(observation.shape, (WORK_RAM_SIZE,))
        self.assertEqual(reward, -10.0)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["episode_end"], "two_lives_lost")
        self.assertEqual(info["lives_lost"], 2)

        env.close()
        self.assertEqual(game.lockstep, [True, False])
        self.assertTrue(game.closed)

    def test_remote_step_timeout_truncates_instead_of_killing_worker(self) -> None:
        game = _FakeGame(step_timeout=True)
        env = StreetsOfRageEnv(EnvironmentConfig(max_episode_steps=100))
        env._game = game
        ready = {"character": "blaze"}
        with patch(
            "ai_play.environment._load_reach_gameplay",
            return_value=lambda *_a, **_k: ready,
        ):
            observation, _ = env.reset()

        returned, reward, terminated, truncated, info = env.step(
            np.zeros(6, dtype=np.float32)
        )

        np.testing.assert_array_equal(returned, observation)
        self.assertEqual(reward, 0.0)
        self.assertFalse(terminated)
        self.assertTrue(truncated)
        self.assertEqual(info["episode_end"], "remote_step_timeout")
        self.assertIn("timed out", info["remote_error"])
        self.assertEqual(game.lockstep, [True, False])
        self.assertTrue(game.closed)
        self.assertIsNone(env._game)
        env.close()

    def test_start_is_only_used_for_the_exact_round_clear_skip_window(self) -> None:
        game = _FakeGame()
        env = StreetsOfRageEnv(EnvironmentConfig(max_episode_steps=100))
        env._game = game
        ready = {"character": "blaze"}
        with patch(
            "ai_play.environment._load_reach_gameplay",
            return_value=lambda *_a, **_k: ready,
        ):
            env.reset()

        round_clear_ram = _ram(
            0x03,
            game_state=0x1A,
            level=0,
            round_clear_substate=0x20,
        )
        game.ram = round_clear_ram
        env._current_snapshot = WorkRamSnapshotReader.decode(round_clear_ram, 1)
        _, _, _, _, info = env.step(np.zeros(6, dtype=np.float32))

        self.assertEqual(
            game.step_calls[-1],
            {
                "player1": START,
                "player2": 0,
                "held_frames": 2,
                "total_frames": 12,
                "timeout_ms": 30_000,
            },
        )
        self.assertEqual(info["action_source"], "deterministic_round_clear_skip")

        final_round = WorkRamSnapshotReader.decode(
            _ram(
                0x03,
                game_state=0x1A,
                level=7,
                round_clear_substate=0x20,
            ),
            2,
        )
        before_window = WorkRamSnapshotReader.decode(
            _ram(
                0x03,
                game_state=0x1A,
                level=0,
                round_clear_substate=0x12,
            ),
            3,
        )
        after_window = WorkRamSnapshotReader.decode(
            _ram(
                0x03,
                game_state=0x1A,
                level=0,
                round_clear_substate=0x52,
            ),
            4,
        )
        gameplay = WorkRamSnapshotReader.decode(
            _ram(
                0x03,
                game_state=0x16,
                level=0,
                round_clear_substate=0x20,
            ),
            5,
        )
        self.assertFalse(should_skip_round_clear(final_round))
        self.assertFalse(should_skip_round_clear(before_window))
        self.assertFalse(should_skip_round_clear(after_window))
        self.assertFalse(should_skip_round_clear(gameplay))
        env.close()


if __name__ == "__main__":
    unittest.main()
