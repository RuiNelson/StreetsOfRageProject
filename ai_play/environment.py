"""Gymnasium environment backed by one remote Streets of Rage process."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO, Optional

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .actions import (
    ACTION_HIGH,
    ACTION_LOW,
    ACTION_SIZE,
    FRAMES_PER_ACTION,
    START,
    DecodedAction,
    decode_action,
)
from .event_detector import (
    EventDetector,
    Snapshot,
    WORK_RAM_SIZE,
    WorkRamSnapshotReader,
    _load_reach_gameplay,
    _load_remote_client,
)
from .rewards import reward_events


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAME_ROOT = PROJECT_ROOT / "StreetsOfRageRecompilation"
DEFAULT_EXECUTABLE = DEFAULT_GAME_ROOT / "build" / "sor"
DEFAULT_ROM = DEFAULT_GAME_ROOT / "rom" / "SOR.bin"
ROUND_CLEAR_UPDATE = 0x1A
FINAL_LEVEL_INDEX = 7
ROUND_CLEAR_SKIP_FIRST_SUBSTATE = 0x14
ROUND_CLEAR_SKIP_END_SUBSTATE = 0x52
DETERMINISTIC_START_HELD_FRAMES = 2


class LaunchPortUnavailableError(RuntimeError):
    """A local game instance cannot bind its configured remote port."""


def ensure_launch_port_available(port: int) -> None:
    """Fail early if a local game process could not bind ``port``."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
    except OSError as error:
        raise LaunchPortUnavailableError(
            f"TCP port {port} is already in use; choose another --port "
            f"(inspect it with: lsof -nP -iTCP:{port})"
        ) from error


def should_skip_round_clear(snapshot: Snapshot) -> bool:
    """Match the game's exact non-final-round Start-to-skip window."""

    return (
        snapshot.game_state == ROUND_CLEAR_UPDATE
        and snapshot.level != FINAL_LEVEL_INDEX
        and ROUND_CLEAR_SKIP_FIRST_SUBSTATE
        <= snapshot.round_clear_substate
        < ROUND_CLEAR_SKIP_END_SUBSTATE
    )


@dataclass(frozen=True)
class EnvironmentConfig:
    host: str = "127.0.0.1"
    port: int = 6969
    character: str = "blaze"
    startup_timeout_ms: int = 30_000
    step_timeout_ms: int = 5_000
    max_episode_steps: int = 18_000
    launch_game: bool = False
    executable: str = str(DEFAULT_EXECUTABLE)
    rom: str = str(DEFAULT_ROM)
    process_timeout_seconds: int = 86_400
    seed: int = 0


class _GameProcess:
    """Own an optional real-speed ``sor`` instance for one environment."""

    def __init__(self, config: EnvironmentConfig) -> None:
        self._config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._output: BinaryIO | None = None

    def start(self) -> None:
        if not self._config.launch_game or self._process is not None:
            return
        executable = Path(self._config.executable).expanduser().resolve()
        rom = Path(self._config.rom).expanduser().resolve()
        if not executable.is_file():
            raise FileNotFoundError(f"game executable not found: {executable}")
        if not rom.is_file():
            raise FileNotFoundError(f"ROM not found: {rom}")
        ensure_launch_port_available(self._config.port)

        timeout = Path("/opt/homebrew/bin/timeout")
        timeout_command = str(timeout) if timeout.is_file() else "timeout"
        command = [
            timeout_command,
            "-k",
            "3",
            str(self._config.process_timeout_seconds),
            str(executable),
            "--runSor",
            "--silent",
            "--hz",
            "60",
            "--vsync",
            "0",
            "--port",
            str(self._config.port),
            "--rom",
            str(rom),
        ]
        output = tempfile.TemporaryFile(mode="w+b")
        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(executable.parent.parent),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self._output = output
        except BaseException:
            output.close()
            raise

    def _output_tail(self) -> str:
        if self._output is None:
            return ""
        self._output.flush()
        self._output.seek(0, os.SEEK_END)
        size = self._output.tell()
        self._output.seek(max(0, size - 8_192))
        return self._output.read().decode("utf-8", errors="replace").strip()

    def check(self) -> None:
        if self._process is not None and self._process.poll() is not None:
            message = (
                f"game process on port {self._config.port} exited with "
                f"status {self._process.returncode}"
            )
            output = self._output_tail()
            if output:
                message += f"\nGame output:\n{output}"
            raise RuntimeError(message)

    def stop(self) -> None:
        process, self._process = self._process, None
        try:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=5)
        finally:
            output, self._output = self._output, None
            if output is not None:
                output.close()


class StreetsOfRageEnv(gym.Env[np.ndarray, np.ndarray]):
    """Five-policy-step-per-second environment with exact 12-frame steps."""

    metadata = {"render_modes": []}

    def __init__(self, config: EnvironmentConfig) -> None:
        super().__init__()
        self.config = config
        self.observation_space = spaces.Box(
            low=0,
            high=255,
            shape=(WORK_RAM_SIZE,),
            dtype=np.uint8,
        )
        self.action_space = spaces.Box(
            low=np.asarray(ACTION_LOW, dtype=np.float32),
            high=np.asarray(ACTION_HIGH, dtype=np.float32),
            shape=(ACTION_SIZE,),
            dtype=np.float32,
        )
        self._process = _GameProcess(config)
        self._game: Any | None = None
        self._detector = EventDetector()
        self._lives_lost = 0
        self._episode_steps = 0
        self._lockstep_enabled = False
        self._current_snapshot: Snapshot | None = None

    def _connect(self) -> Any:
        if self._game is not None:
            return self._game
        self._process.start()
        remote = _load_remote_client()
        deadline = time.monotonic() + self.config.startup_timeout_ms / 1000.0
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            self._process.check()
            game = remote.MegaDriveClient(
                self.config.host,
                self.config.port,
                connect_timeout=1.0,
                io_timeout=max(10.0, self.config.step_timeout_ms / 1000.0 + 1.0),
            )
            try:
                game.connect()
                game.ping()
                self._game = game
                return game
            except (ConnectionError, OSError) as error:
                last_error = error
                game.close()
                time.sleep(0.1)
        raise ConnectionError(
            f"could not connect to game at {self.config.host}:{self.config.port}"
        ) from last_error

    @staticmethod
    def _observation(ram: bytes) -> np.ndarray:
        if len(ram) != WORK_RAM_SIZE:
            raise RuntimeError(
                f"lockstep returned {len(ram)} RAM bytes, expected {WORK_RAM_SIZE}"
            )
        return np.frombuffer(ram, dtype=np.uint8).copy()

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[dict[str, Any]] = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        del options
        super().reset(seed=seed)
        game = self._connect()
        if self._lockstep_enabled:
            game.set_lockstep(False)
            self._lockstep_enabled = False

        ready = _load_reach_gameplay()(
            game,
            self.config.character,
            timeout_ms=self.config.startup_timeout_ms,
        )
        game.set_lockstep(True)
        self._lockstep_enabled = True

        # Lockstep is now holding a frame boundary, so these two reads describe
        # the same stable game state. Every later observation comes directly
        # from the atomic step response.
        baseline = WorkRamSnapshotReader(game).read()
        self._detector = EventDetector()
        self._detector.consume(baseline)
        self._lives_lost = 0
        self._episode_steps = 0
        self._current_snapshot = baseline
        return self._observation(baseline.ram), {
            "frame": baseline.frame,
            "character": ready["character"],
            "lives_lost": 0,
        }

    def step(
        self,
        action: np.ndarray,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if (
            self._game is None
            or not self._lockstep_enabled
            or self._current_snapshot is None
        ):
            raise RuntimeError("reset() must be called before step()")

        if should_skip_round_clear(self._current_snapshot):
            decoded = DecodedAction(
                buttons=START,
                held_frames=DETERMINISTIC_START_HELD_FRAMES,
                total_frames=FRAMES_PER_ACTION,
                direction=None,
            )
            action_source = "deterministic_round_clear_skip"
        else:
            decoded = decode_action(action)
            action_source = "policy"
        stepped = self._game.step_input(
            player1=decoded.buttons,
            player2=0,
            held_frames=decoded.held_frames,
            total_frames=decoded.total_frames,
            timeout_ms=self.config.step_timeout_ms,
        )
        snapshot = WorkRamSnapshotReader.decode(
            stepped.work_ram,
            stepped.frame,
        )
        events = self._detector.consume(snapshot)
        reward = reward_events(events)
        self._current_snapshot = snapshot

        self._episode_steps += 1
        self._lives_lost += reward.lives_lost
        terminated = reward.game_completed or self._lives_lost >= 3
        truncated = self._episode_steps >= self.config.max_episode_steps
        info = {
            "frame": snapshot.frame,
            "events": [event.as_dict() for event in events],
            "reward_components": reward.components,
            "lives_lost": self._lives_lost,
            "action": asdict(decoded),
            "action_source": action_source,
        }
        if self._lives_lost >= 3:
            info["episode_end"] = "three_lives_lost"
        elif reward.game_completed:
            info["episode_end"] = "game_completed"
        elif truncated:
            info["episode_end"] = "time_limit"
        return (
            self._observation(snapshot.ram),
            reward.total,
            terminated,
            truncated,
            info,
        )

    def close(self) -> None:
        game, self._game = self._game, None
        if game is not None:
            if self._lockstep_enabled:
                try:
                    game.set_lockstep(False)
                except Exception:
                    pass
            game.close()
        self._lockstep_enabled = False
        self._current_snapshot = None
        self._process.stop()
        super().close()


def make_environment(config: EnvironmentConfig) -> StreetsOfRageEnv:
    """Top-level factory kept picklable for ``SubprocVecEnv(spawn)``."""

    return StreetsOfRageEnv(config)
