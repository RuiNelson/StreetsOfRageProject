from __future__ import annotations

import unittest
from typing import Dict, Iterable

from ai_play.event_detector import (
    END_OF_LEVEL_FLAG,
    GAME_STATE,
    LEVEL,
    OBJECT_TABLE,
    P1_HEALTH,
    P1_LIVES,
    P1_WORLD_X,
    PLAYER_MODE,
    ROUND_CLEAR_SUBSTATE,
    WORK_RAM_BASE,
    WORK_RAM_SIZE,
    EnemySnapshot,
    EventDetector,
    Snapshot,
    WorkRamSnapshotReader,
    _parser,
)


def enemies(overrides: Dict[int, EnemySnapshot] | None = None) -> tuple[EnemySnapshot, ...]:
    values = [EnemySnapshot(slot, 0, 0, 0) for slot in range(32)]
    for slot, enemy in (overrides or {}).items():
        values[slot] = enemy
    return tuple(values)


def snapshot(
    frame: int,
    *,
    game_state: int = 0x16,
    level: int = 0,
    player_mode: int = 1,
    health: int = 80,
    lives_bcd: int = 0x03,
    end_of_level: int = 0,
    player_x: int = 0,
    enemy_values: tuple[EnemySnapshot, ...] | None = None,
) -> Snapshot:
    return Snapshot(
        frame=frame,
        game_state=game_state,
        level=level,
        player_mode=player_mode,
        health=health,
        lives_bcd=lives_bcd,
        end_of_level=end_of_level,
        enemies=enemy_values or enemies(),
        player_x=player_x,
    )


def event_map(events: Iterable[object]) -> Dict[str, object]:
    return {event.kind: event for event in events}  # type: ignore[attr-defined]


class EventDetectorTests(unittest.TestCase):
    def test_blaze_is_the_default_starting_character(self) -> None:
        args = _parser().parse_args([])
        self.assertEqual(args.character, "blaze")
        self.assertEqual(args.poll_hz, 5.0)
        self.assertFalse(args.observe_current_game)

    def test_training_defaults_to_one_real_speed_environment(self) -> None:
        args = _parser().parse_args(["--train"])
        self.assertEqual(args.n_envs, 1)
        self.assertFalse(args.launch_games)
        self.assertEqual(args.step_timeout_ms, 30_000)
        self.assertNotIn("turbo", vars(args))

    def test_aggregates_elapsed_frame_intervals(self) -> None:
        detector = EventDetector()
        self.assertEqual(detector.consume(snapshot(100)), [])
        events = event_map(detector.consume(snapshot(221)))
        event = events["frames_elapsed"]
        self.assertEqual(event.data, {"frames": 120, "intervals": 2})  # type: ignore[attr-defined]

    def test_detects_energy_and_bcd_life_loss(self) -> None:
        detector = EventDetector()
        detector.consume(snapshot(10, health=80, lives_bcd=0x10))
        events = event_map(detector.consume(snapshot(25, health=57, lives_bcd=0x09)))
        self.assertEqual(events["player_energy_lost"].data["amount"], 23)  # type: ignore[attr-defined]
        self.assertEqual(events["player_life_lost"].data["amount"], 1)  # type: ignore[attr-defined]

    def test_rewards_only_new_forward_progress_in_each_level_direction(self) -> None:
        detector = EventDetector()
        detector.consume(snapshot(10, level=0, player_x=100))

        right = event_map(detector.consume(snapshot(20, level=0, player_x=112)))
        self.assertEqual(
            right["player_forward_progress"].data,  # type: ignore[attr-defined]
            {"pixels": 12, "direction": "right", "level": 1},
        )

        self.assertNotIn(
            "player_forward_progress",
            event_map(detector.consume(snapshot(30, level=0, player_x=90))),
        )
        self.assertNotIn(
            "player_forward_progress",
            event_map(detector.consume(snapshot(40, level=0, player_x=110))),
        )
        new_frontier = event_map(
            detector.consume(snapshot(50, level=0, player_x=115))
        )
        self.assertEqual(
            new_frontier["player_forward_progress"].data["pixels"],  # type: ignore[attr-defined]
            3,
        )

        detector.consume(snapshot(60, level=6, player_x=500))
        elevator = event_map(detector.consume(snapshot(70, level=6, player_x=550)))
        self.assertNotIn("player_forward_progress", elevator)

        detector.consume(snapshot(80, level=7, player_x=500))
        left = event_map(detector.consume(snapshot(90, level=7, player_x=480)))
        self.assertEqual(
            left["player_forward_progress"].data,  # type: ignore[attr-defined]
            {"pixels": 20, "direction": "left", "level": 8},
        )

    def test_does_not_report_player_changes_outside_gameplay(self) -> None:
        detector = EventDetector()
        detector.consume(snapshot(10, game_state=0x12, health=80, lives_bcd=0x03))
        events = detector.consume(snapshot(20, game_state=0x12, health=0, lives_bcd=0x00))
        self.assertEqual(events, [])

    def test_detects_multiple_enemies_in_one_poll(self) -> None:
        detector = EventDetector()
        alive = enemies(
            {
                2: EnemySnapshot(2, 0x20, 0x0100, 20),
                7: EnemySnapshot(7, 0x56, 0x0100, 24),
            }
        )
        defeated = enemies(
            {
                # +$31 gains flags on the first death update, so the observed
                # state is not normally the exact word $0600.
                2: EnemySnapshot(2, 0x20, 0x0601, 0),
                7: EnemySnapshot(7, 0x56, 0x0900, 0),
            }
        )
        detector.consume(snapshot(10, enemy_values=alive))
        events = event_map(detector.consume(snapshot(20, enemy_values=defeated)))
        self.assertEqual(events["enemy_defeated"].data["count"], 2)  # type: ignore[attr-defined]
        self.assertNotIn(
            "enemy_defeated",
            event_map(detector.consume(snapshot(30, enemy_values=defeated))),
        )

    def test_police_preparation_is_not_yet_a_defeat(self) -> None:
        detector = EventDetector()
        alive = enemies({1: EnemySnapshot(1, 0x20, 0x0100, 20)})
        prepared = enemies({1: EnemySnapshot(1, 0x20, 0x0405, -1)})
        lethal = enemies({1: EnemySnapshot(1, 0x20, 0x0305, -1)})
        detector.consume(snapshot(10, enemy_values=alive))
        self.assertEqual(detector.consume(snapshot(20, enemy_values=prepared)), [])
        events = event_map(detector.consume(snapshot(30, enemy_values=lethal)))
        self.assertEqual(events["enemy_defeated"].data["count"], 1)  # type: ignore[attr-defined]

    def test_detects_death_with_low_byte_reaction_flags(self) -> None:
        detector = EventDetector()
        alive = enemies({4: EnemySnapshot(4, 0x24, 0x0308, 3)})
        dying = enemies({4: EnemySnapshot(4, 0x24, 0x067D, 3)})
        detector.consume(snapshot(10, enemy_values=alive))
        events = event_map(detector.consume(snapshot(25, enemy_values=dying)))
        self.assertEqual(events["enemy_defeated"].data["count"], 1)  # type: ignore[attr-defined]

    def test_detects_level_events_and_game_completion(self) -> None:
        detector = EventDetector()
        detector.consume(snapshot(10, level=0, end_of_level=0))
        completed = event_map(
            detector.consume(snapshot(20, level=0, end_of_level=1, game_state=0x1A))
        )
        self.assertEqual(completed["level_completed"].data["level"], 1)  # type: ignore[attr-defined]

        increased = event_map(
            detector.consume(snapshot(30, level=1, end_of_level=0, game_state=0x28))
        )
        self.assertEqual(
            increased["level_increased"].data,
            {"from_level": 1, "to_level": 2, "amount": 1},
        )  # type: ignore[attr-defined]

        decreased = event_map(detector.consume(snapshot(40, level=0, game_state=0x28)))
        self.assertEqual(decreased["level_decreased"].data["to_level"], 1)  # type: ignore[attr-defined]

        finished = event_map(detector.consume(snapshot(50, level=7, game_state=0x24)))
        self.assertEqual(finished["game_completed"].data["ending"], "good")  # type: ignore[attr-defined]

    def test_does_not_report_level_changes_from_the_options_menu(self) -> None:
        detector = EventDetector()
        detector.consume(snapshot(10, level=0, game_state=0x12))
        events = event_map(detector.consume(snapshot(20, level=4, game_state=0x12)))
        self.assertNotIn("level_increased", events)
        self.assertNotIn("level_decreased", events)

    def test_game_restart_rebaselines_without_false_events(self) -> None:
        detector = EventDetector()
        detector.consume(snapshot(500, health=80, lives_bcd=0x03))
        self.assertEqual(detector.consume(snapshot(2, health=0, lives_bcd=0x00)), [])


class FakeGame:
    def __init__(self, ram: bytes, frame: int) -> None:
        self.ram = ram
        self.frame = frame
        self.reads = []

    def read_memory(self, address: int, length: int) -> bytes:
        self.reads.append((address, length))
        return self.ram

    def get_game_uptime_frames(self) -> int:
        return self.frame


def write_value(ram: bytearray, address: int, value: int, width: int) -> None:
    offset = address - WORK_RAM_BASE
    ram[offset : offset + width] = value.to_bytes(width, "big")


class WorkRamSnapshotReaderTests(unittest.TestCase):
    def test_fetches_all_work_ram_in_one_memory_read(self) -> None:
        ram = bytearray(WORK_RAM_SIZE)
        write_value(ram, GAME_STATE, 0x16, 2)
        write_value(ram, LEVEL, 2, 2)
        write_value(ram, PLAYER_MODE, 1, 1)
        write_value(ram, P1_HEALTH, 65, 2)
        write_value(ram, P1_LIVES, 0x03, 1)
        write_value(ram, P1_WORLD_X, 0x0234, 2)
        write_value(ram, END_OF_LEVEL_FLAG, 1, 1)
        write_value(ram, ROUND_CLEAR_SUBSTATE, 0x20, 2)
        write_value(ram, OBJECT_TABLE, 0x20, 1)
        write_value(ram, OBJECT_TABLE + 0x30, 0x0100, 2)
        write_value(ram, OBJECT_TABLE + 0x32, 20, 2)
        game = FakeGame(bytes(ram), 123)

        observed = WorkRamSnapshotReader(game).read()

        self.assertEqual(game.reads, [(WORK_RAM_BASE, WORK_RAM_SIZE)])
        self.assertEqual(observed.frame, 123)
        self.assertEqual(observed.ram, bytes(ram))
        self.assertEqual(observed.level, 2)
        self.assertEqual(observed.health, 65)
        self.assertEqual(observed.player_x, 0x0234)
        self.assertEqual(observed.round_clear_substate, 0x20)
        self.assertEqual(observed.enemies[0].object_type, 0x20)

    def test_decodes_ram_already_collected_by_lockstep(self) -> None:
        ram = bytearray(WORK_RAM_SIZE)
        write_value(ram, GAME_STATE, 0x16, 2)
        write_value(ram, PLAYER_MODE, 1, 1)
        write_value(ram, P1_HEALTH, 80, 2)
        observed = WorkRamSnapshotReader.decode(bytes(ram), 77)
        self.assertEqual(observed.frame, 77)
        self.assertEqual(observed.health, 80)
        self.assertEqual(observed.ram, bytes(ram))


if __name__ == "__main__":
    unittest.main()
