#!/usr/bin/env python3
"""Observe a one-player Streets of Rage session and print semantic events."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


WORK_RAM_BASE = 0xFF0000
WORK_RAM_SIZE = 0x10000

# Canonical addresses and widths come from
# StreetsOfRageRecompilation/code-analysis/addresses.csv.
P1_HEALTH = 0xFFB832  # W
OBJECT_TABLE = 0xFFB900  # 32 objects, $80 bytes each
OBJECT_COUNT = 32
OBJECT_SIZE = 0x80
END_OF_LEVEL_FLAG = 0xFFFA73  # B
GAME_STATE = 0xFFFF00  # W
LEVEL = 0xFFFF02  # W, zero-based round index
PLAYER_MODE = 0xFFFF18  # B, 1=P1 and 3=P1+P2
P1_LIVES = 0xFFFF20  # B, packed BCD

FRAMES_PER_EVENT = 60
ONE_PLAYER = 1

GAMEPLAY_STATES = frozenset((0x14, 0x16))
CAMPAIGN_STATES = frozenset((0x14, 0x16, 0x18, 0x1A, 0x1C, 0x1E, 0x24, 0x26, 0x28, 0x2A))

ORDINARY_ENEMY_TYPES = frozenset((*range(0x20, 0x28), 0x2A))
BOSS_TYPES = frozenset((0x30, 0x35, 0x55, 0x56, 0x57, 0x58))
ENEMY_TYPES = ORDINARY_ENEMY_TYPES | BOSS_TYPES
ENEMY_NAMES = {
    0x20: "Garcia",
    0x21: "Garcia",
    0x22: "Garcia",
    0x23: "Garcia",
    0x24: "Signal",
    0x25: "Haku-Ro",
    0x26: "Nora",
    0x27: "Jack",
    0x2A: "Haku-Ro",
    0x30: "Abadede",
    0x35: "Mr. X",
    0x55: "Souther",
    0x56: "Antonio",
    0x57: "Bongo",
    0x58: "Onihime/Yasha",
}


def _ram_offset(address: int) -> int:
    if not WORK_RAM_BASE <= address < WORK_RAM_BASE + WORK_RAM_SIZE:
        raise ValueError(f"address 0x{address:06X} is outside Work RAM")
    return address - WORK_RAM_BASE


def _u8(ram: bytes, address: int) -> int:
    return ram[_ram_offset(address)]


def _u16(ram: bytes, address: int) -> int:
    offset = _ram_offset(address)
    return int.from_bytes(ram[offset : offset + 2], "big")


def _s16(ram: bytes, address: int) -> int:
    offset = _ram_offset(address)
    return int.from_bytes(ram[offset : offset + 2], "big", signed=True)


def _decode_bcd(value: int) -> Optional[int]:
    high, low = value >> 4, value & 0x0F
    if high > 9 or low > 9:
        return None
    return high * 10 + low


@dataclass(frozen=True)
class EnemySnapshot:
    """The fields needed to follow one combatant object slot."""

    slot: int
    object_type: int
    state: int
    health: int


@dataclass(frozen=True)
class Snapshot:
    """Semantic values decoded from one complete Work RAM fetch."""

    frame: int
    game_state: int
    level: int
    player_mode: int
    health: int
    lives_bcd: int
    end_of_level: int
    enemies: Tuple[EnemySnapshot, ...]
    ram: bytes = b""


@dataclass(frozen=True)
class Event:
    """One console event, suitable for JSON-lines output."""

    kind: str
    frame: int
    data: Dict[str, object]

    def as_dict(self) -> Dict[str, object]:
        return {"event": self.kind, "frame": self.frame, **self.data}


class WorkRamSnapshotReader:
    """Fetch all 64 KiB of Work RAM once and decode every observed value."""

    def __init__(self, game: Any) -> None:
        self._game = game

    @staticmethod
    def decode(ram: bytes, frame: int) -> Snapshot:
        """Decode a complete Work RAM image already collected by the caller."""

        if len(ram) != WORK_RAM_SIZE:
            raise RuntimeError(
                f"expected {WORK_RAM_SIZE} Work RAM bytes, received {len(ram)}"
            )

        enemies: List[EnemySnapshot] = []
        for slot in range(OBJECT_COUNT):
            base = OBJECT_TABLE + slot * OBJECT_SIZE
            enemies.append(
                EnemySnapshot(
                    slot=slot,
                    object_type=_u8(ram, base),
                    state=_u16(ram, base + 0x30),
                    health=_s16(ram, base + 0x32),
                )
            )

        return Snapshot(
            frame=frame,
            game_state=_u16(ram, GAME_STATE),
            level=_u16(ram, LEVEL),
            player_mode=_u8(ram, PLAYER_MODE),
            health=_u16(ram, P1_HEALTH),
            lives_bcd=_u8(ram, P1_LIVES),
            end_of_level=_u8(ram, END_OF_LEVEL_FLAG),
            enemies=tuple(enemies),
            ram=ram,
        )

    def read(self) -> Snapshot:
        # Keep this as one READ_MEMORY request. Future detectors and the agent
        # consume this same local byte snapshot instead of adding remote reads.
        ram = self._game.read_memory(WORK_RAM_BASE, WORK_RAM_SIZE)

        # The uptime counter is not a Work RAM value. Reading it after RAM makes
        # the frame number an approximate upper timestamp for this snapshot.
        frame = self._game.get_game_uptime_frames()
        return self.decode(ram, frame)


class EventDetector:
    """Turn successive snapshots into one-player gameplay events."""

    def __init__(self) -> None:
        self._previous: Optional[Snapshot] = None
        self._next_frame_event: Optional[int] = None
        self._defeated_slots: set[int] = set()

    @staticmethod
    def _is_one_player(snapshot: Snapshot) -> bool:
        return snapshot.player_mode == ONE_PLAYER

    @staticmethod
    def _is_gameplay(snapshot: Snapshot) -> bool:
        return snapshot.game_state in GAMEPLAY_STATES

    @staticmethod
    def _is_campaign(snapshot: Snapshot) -> bool:
        return snapshot.game_state in CAMPAIGN_STATES

    @staticmethod
    def _is_defeated(enemy: EnemySnapshot) -> bool:
        if enemy.object_type in ORDINARY_ENEMY_TYPES:
            # The primary state is the high byte at +$30. The low byte at +$31
            # contains reaction/physics flags, so death normally appears as
            # $0601 (and later flag combinations), not exact word $0600.
            primary_state = enemy.state & 0xFF00
            # $04xx/$FFFF is police-special preparation, not yet the credited
            # lethal reaction. $03xx with non-positive health and $06xx are the
            # ordinary-enemy lethal/death paths.
            return primary_state == 0x0600 or (
                primary_state == 0x0300 and enemy.health <= 0
            )
        return enemy.object_type in BOSS_TYPES and enemy.health <= 0

    @staticmethod
    def _ending(game_state: int) -> Optional[str]:
        if game_state in (0x1C, 0x1E):
            return "bad"
        if game_state in (0x24, 0x26):
            return "good"
        return None

    def _reset(self, snapshot: Snapshot) -> None:
        self._previous = snapshot
        self._next_frame_event = snapshot.frame + FRAMES_PER_EVENT
        self._defeated_slots.clear()

    def consume(self, snapshot: Snapshot) -> List[Event]:
        previous = self._previous
        if previous is None or snapshot.frame < previous.frame:
            # A decreasing uptime means the remote game restarted. Establish a
            # fresh baseline and do not turn reset RAM into gameplay events.
            self._reset(snapshot)
            return []

        events: List[Event] = []
        assert self._next_frame_event is not None

        if snapshot.frame >= self._next_frame_event:
            intervals = 1 + (snapshot.frame - self._next_frame_event) // FRAMES_PER_EVENT
            events.append(
                Event(
                    "frames_elapsed",
                    snapshot.frame,
                    {
                        "frames": intervals * FRAMES_PER_EVENT,
                        "intervals": intervals,
                    },
                )
            )
            self._next_frame_event += intervals * FRAMES_PER_EVENT

        in_one_player_gameplay = (
            self._is_one_player(previous)
            and self._is_one_player(snapshot)
            and self._is_gameplay(previous)
            and self._is_gameplay(snapshot)
        )

        if in_one_player_gameplay and snapshot.health < previous.health:
            events.append(
                Event(
                    "player_energy_lost",
                    snapshot.frame,
                    {
                        "amount": previous.health - snapshot.health,
                        "before": previous.health,
                        "after": snapshot.health,
                    },
                )
            )

        previous_lives = _decode_bcd(previous.lives_bcd)
        current_lives = _decode_bcd(snapshot.lives_bcd)
        if (
            in_one_player_gameplay
            and previous_lives is not None
            and current_lives is not None
            and current_lives < previous_lives
        ):
            events.append(
                Event(
                    "player_life_lost",
                    snapshot.frame,
                    {
                        "amount": previous_lives - current_lives,
                        "before": previous_lives,
                        "after": current_lives,
                    },
                )
            )

        defeated: List[Dict[str, object]] = []
        for old_enemy, enemy in zip(previous.enemies, snapshot.enemies):
            if enemy.object_type not in ENEMY_TYPES:
                self._defeated_slots.discard(enemy.slot)
                continue

            is_defeated = self._is_defeated(enemy)
            if not is_defeated:
                self._defeated_slots.discard(enemy.slot)
                continue

            if (
                in_one_player_gameplay
                and enemy.slot not in self._defeated_slots
                and old_enemy.object_type == enemy.object_type
                and not self._is_defeated(old_enemy)
            ):
                defeated.append(
                    {
                        "slot": enemy.slot,
                        "type": f"0x{enemy.object_type:02X}",
                        "name": ENEMY_NAMES[enemy.object_type],
                        "health_before": old_enemy.health,
                        "health_after": enemy.health,
                    }
                )
            self._defeated_slots.add(enemy.slot)

        if defeated:
            events.append(
                Event(
                    "enemy_defeated",
                    snapshot.frame,
                    {"count": len(defeated), "enemies": defeated},
                )
            )

        in_one_player_campaign = (
            self._is_one_player(previous)
            and self._is_one_player(snapshot)
            and self._is_campaign(previous)
            and self._is_campaign(snapshot)
        )
        if (
            in_one_player_campaign
            and previous.end_of_level == 0
            and snapshot.end_of_level != 0
        ):
            events.append(
                Event(
                    "level_completed",
                    snapshot.frame,
                    {"level": snapshot.level + 1},
                )
            )

        if in_one_player_campaign and snapshot.level > previous.level:
            events.append(
                Event(
                    "level_increased",
                    snapshot.frame,
                    {
                        "from_level": previous.level + 1,
                        "to_level": snapshot.level + 1,
                        "amount": snapshot.level - previous.level,
                    },
                )
            )

        if in_one_player_campaign and snapshot.level < previous.level:
            events.append(
                Event(
                    "level_decreased",
                    snapshot.frame,
                    {
                        "from_level": previous.level + 1,
                        "to_level": snapshot.level + 1,
                        "amount": previous.level - snapshot.level,
                    },
                )
            )

        old_ending = self._ending(previous.game_state)
        ending = self._ending(snapshot.game_state)
        if self._is_one_player(snapshot) and ending is not None and old_ending != ending:
            events.append(
                Event(
                    "game_completed",
                    snapshot.frame,
                    {"ending": ending, "level": snapshot.level + 1},
                )
            )

        self._previous = snapshot
        return events


def _load_remote_client() -> Any:
    """Import an installed client or the sibling source checkout."""

    try:
        import megadrive_remote
    except ModuleNotFoundError:
        source = Path(__file__).resolve().parents[1] / "MegaDriveEnvironment" / "python" / "src"
        if not source.is_dir():
            raise SystemExit(
                "megadrive_remote is not installed and the sibling client "
                f"was not found at {source}"
            )
        sys.path.insert(0, str(source))
        import megadrive_remote
    return megadrive_remote


def _load_reach_gameplay() -> Any:
    """Load the repository's existing menu-navigation helper."""

    old_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        from StreetsOfRageRecompilation.tools.reach_gameplay import reach_gameplay
    except ModuleNotFoundError as error:
        raise SystemExit(
            "the gameplay navigation helper was not found at "
            "StreetsOfRageRecompilation/tools/reach_gameplay.py"
        ) from error
    finally:
        # Importing a helper from the submodule must not dirty that submodule
        # with a tools/__pycache__ directory.
        sys.dont_write_bytecode = old_dont_write_bytecode
    return reach_gameplay


def monitor(game: Any, poll_hz: float) -> None:
    """Print JSON events until interrupted."""

    reader = WorkRamSnapshotReader(game)
    detector = EventDetector()
    period = 1.0 / poll_hz
    deadline = time.monotonic()

    while True:
        for event in detector.consume(reader.read()):
            print(json.dumps(event.as_dict(), sort_keys=True), flush=True)

        deadline += period
        delay = deadline - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            # Do not issue catch-up polls back-to-back when a request is slow.
            deadline = time.monotonic()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Observe a one-player Streets of Rage session and print JSON events. "
            "Each poll fetches all 64 KiB of Work RAM in one request."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="remote server host")
    parser.add_argument("--port", type=int, default=6969, help="remote server port")
    parser.add_argument(
        "--poll-hz",
        type=float,
        default=5.0,
        help="Work RAM snapshots per second (default: 5)",
    )
    parser.add_argument(
        "--character",
        choices=("axel", "adam", "blaze"),
        default="blaze",
        help="character selected before observation (default: blaze)",
    )
    parser.add_argument(
        "--startup-timeout-ms",
        type=int,
        default=30_000,
        help="timeout for each startup transition (default: 30000)",
    )
    parser.add_argument(
        "--observe-current-game",
        action="store_true",
        help="do not restart/navigate; observe the current session as-is",
    )
    parser.add_argument(
        "--train",
        action="store_true",
        help="train a PPO agent instead of printing events",
    )
    parser.add_argument(
        "--n-envs",
        type=int,
        default=1,
        help="parallel emulator environments; ports are --port + worker (default: 1)",
    )
    parser.add_argument(
        "--total-timesteps",
        type=int,
        default=100_000,
        help="PPO environment timesteps to collect (default: 100000)",
    )
    parser.add_argument(
        "--n-steps",
        type=int,
        default=256,
        help="rollout steps per environment and PPO update (default: 256)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="PPO minibatch size (default: 16)",
    )
    parser.add_argument(
        "--max-episode-steps",
        type=int,
        default=18_000,
        help="truncate an episode after this many 12-frame actions (default: 18000)",
    )
    parser.add_argument(
        "--step-timeout-ms",
        type=int,
        default=5_000,
        help="timeout for one atomic 12-frame training step (default: 5000)",
    )
    parser.add_argument(
        "--launch-games",
        action="store_true",
        help="launch one real-speed sor process per environment",
    )
    parser.add_argument(
        "--game-executable",
        default=str(
            Path(__file__).resolve().parents[1]
            / "StreetsOfRageRecompilation"
            / "build"
            / "sor"
        ),
        help="sor executable used by --launch-games",
    )
    parser.add_argument(
        "--rom",
        default=str(
            Path(__file__).resolve().parents[1]
            / "StreetsOfRageRecompilation"
            / "rom"
            / "SOR.bin"
        ),
        help="ROM used by --launch-games",
    )
    parser.add_argument(
        "--process-timeout-seconds",
        type=int,
        default=86_400,
        help="hard timeout for each launched game process (default: 86400)",
    )
    parser.add_argument(
        "--model-path",
        default="ai_play/models/ppo_sor",
        help="final PPO model path (default: ai_play/models/ppo_sor)",
    )
    parser.add_argument("--resume", help="resume an existing PPO .zip model")
    parser.add_argument("--seed", type=int, default=0, help="training seed")
    parser.add_argument(
        "--checkpoint-frequency",
        type=int,
        default=10_000,
        help="aggregate environment steps between checkpoints (default: 10000)",
    )
    parser.add_argument(
        "--progress-bar",
        action="store_true",
        help="show the Stable-Baselines3 progress bar",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.poll_hz <= 0:
        parser.error("--poll-hz must be positive")
    if args.startup_timeout_ms <= 0:
        parser.error("--startup-timeout-ms must be positive")
    if args.train:
        positive_training_values = {
            "--n-envs": args.n_envs,
            "--total-timesteps": args.total_timesteps,
            "--n-steps": args.n_steps,
            "--batch-size": args.batch_size,
            "--max-episode-steps": args.max_episode_steps,
            "--step-timeout-ms": args.step_timeout_ms,
            "--process-timeout-seconds": args.process_timeout_seconds,
            "--checkpoint-frequency": args.checkpoint_frequency,
        }
        for option, value in positive_training_values.items():
            if value <= 0:
                parser.error(f"{option} must be positive")
        rollout_size = args.n_steps * args.n_envs
        if rollout_size % args.batch_size:
            parser.error("--batch-size must divide --n-steps * --n-envs")
        try:
            from .environment import LaunchPortUnavailableError
            from .training import train_from_args
        except ModuleNotFoundError as error:
            if error.name in {
                "gymnasium",
                "numpy",
                "stable_baselines3",
                "torch",
            }:
                parser.error(
                    "training dependencies are missing; install "
                    "ai_play/requirements-train.txt with Python 3.13"
                )
            raise
        try:
            return train_from_args(args)
        except LaunchPortUnavailableError as error:
            parser.error(str(error))

    remote = _load_remote_client()
    try:
        with remote.MegaDriveClient(args.host, args.port) as game:
            game.ping()
            print(
                json.dumps(
                    {
                        "status": "connected",
                        "host": args.host,
                        "port": args.port,
                        "poll_hz": args.poll_hz,
                        "work_ram_bytes_per_poll": WORK_RAM_SIZE,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            if not args.observe_current_game:
                print(
                    json.dumps(
                        {"status": "reaching_gameplay", "character": args.character},
                        sort_keys=True,
                    ),
                    flush=True,
                )
                reach_gameplay = _load_reach_gameplay()
                ready = reach_gameplay(
                    game,
                    args.character,
                    timeout_ms=args.startup_timeout_ms,
                )
                print(
                    json.dumps(
                        {
                            "status": "gameplay_ready",
                            "character": ready["character"],
                            "character_id": ready["character_id"],
                            "game_state": ready["game_state"],
                            "health": ready["health"],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            monitor(game, args.poll_hz)
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopped"}), flush=True)
        return 0
    except (
        ConnectionError,
        OSError,
        TimeoutError,
        RuntimeError,
        ValueError,
        remote.MegaDriveRemoteError,
    ) as error:
        print(f"event detector failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
