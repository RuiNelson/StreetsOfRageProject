import unittest
from dataclasses import FrozenInstanceError

from ai_play.weights import DEFAULT_WEIGHTS, RewardWeights


class RewardWeightsTests(unittest.TestCase):
    def test_default_reward_weights(self) -> None:
        self.assertEqual(DEFAULT_WEIGHTS.per_60_frames, -0.001)
        self.assertEqual(DEFAULT_WEIGHTS.per_energy_lost, -0.10)
        self.assertEqual(DEFAULT_WEIGHTS.per_life_lost, -10.0)
        self.assertEqual(DEFAULT_WEIGHTS.per_regular_enemy_defeated, 1.0)
        self.assertEqual(DEFAULT_WEIGHTS.per_boss_defeated, 10.0)
        self.assertEqual(DEFAULT_WEIGHTS.per_wave_increased, 5.0)
        self.assertEqual(DEFAULT_WEIGHTS.per_level_completed, 0.0)
        self.assertEqual(DEFAULT_WEIGHTS.per_level_increased, 50.0)
        self.assertEqual(DEFAULT_WEIGHTS.per_level_decreased, -50.0)
        self.assertEqual(DEFAULT_WEIGHTS.good_ending, 500.0)
        self.assertEqual(DEFAULT_WEIGHTS.bad_ending, -100.0)
        self.assertEqual(DEFAULT_WEIGHTS.game_over, -100.0)

    def test_weights_are_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            DEFAULT_WEIGHTS.per_energy_lost = 0.0  # type: ignore[misc]

    def test_custom_weight_set_can_be_created(self) -> None:
        custom = RewardWeights(per_energy_lost=-0.25)
        self.assertEqual(custom.per_energy_lost, -0.25)
        self.assertEqual(custom.per_level_increased, 50.0)


if __name__ == "__main__":
    unittest.main()
