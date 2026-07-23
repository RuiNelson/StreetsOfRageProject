from __future__ import annotations

import unittest

from ai_play.event_detector import Event
from ai_play.rewards import reward_events


class RewardTests(unittest.TestCase):
    def test_combines_damage_kills_progress_and_time(self) -> None:
        events = (
            Event("frames_elapsed", 60, {"frames": 60, "intervals": 1}),
            Event("player_energy_lost", 60, {"amount": 8}),
            Event("player_forward_progress", 60, {"pixels": 12}),
            Event(
                "enemy_defeated",
                60,
                {
                    "count": 2,
                    "enemies": [
                        {"type": "0x20"},
                        {"type": "0x56"},
                    ],
                },
            ),
            Event("level_increased", 60, {"amount": 1}),
        )
        result = reward_events(events)
        self.assertAlmostEqual(
            result.total,
            -0.001 - 0.8 + 0.12 + 1.0 + 10.0 + 50.0,
        )
        self.assertEqual(result.components["player_forward_progress"], 0.12)
        self.assertEqual(result.lives_lost, 0)
        self.assertFalse(result.game_completed)

    def test_counts_lost_lives_without_a_game_over_penalty(self) -> None:
        result = reward_events(
            (Event("player_life_lost", 12, {"amount": 2}),)
        )
        self.assertEqual(result.total, -20.0)
        self.assertEqual(result.lives_lost, 2)
        self.assertNotIn("game_over", result.components)

    def test_scores_endings_and_marks_completion(self) -> None:
        result = reward_events(
            (Event("game_completed", 100, {"ending": "good"}),)
        )
        self.assertEqual(result.total, 500.0)
        self.assertTrue(result.game_completed)


if __name__ == "__main__":
    unittest.main()
