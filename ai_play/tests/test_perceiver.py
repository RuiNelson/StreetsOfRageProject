from __future__ import annotations

import unittest

try:
    import gymnasium as gym
    import numpy as np
    import torch

    from ai_play.event_detector import WORK_RAM_SIZE
    from ai_play.perceiver import PerceiverLiteExtractor

    TRAINING_AVAILABLE = True
except ModuleNotFoundError:
    TRAINING_AVAILABLE = False


@unittest.skipUnless(TRAINING_AVAILABLE, "training dependencies are not installed")
class PerceiverTests(unittest.TestCase):
    def test_cpu_forward_shape(self) -> None:
        observation_space = gym.spaces.Box(
            low=0,
            high=255,
            shape=(WORK_RAM_SIZE,),
            dtype=np.uint8,
        )
        extractor = PerceiverLiteExtractor(
            observation_space,
            features_dim=32,
            num_latents=8,
            self_attention_blocks=1,
        )
        observations = torch.zeros((1, WORK_RAM_SIZE), dtype=torch.uint8)
        result = extractor(observations)
        self.assertEqual(tuple(result.shape), (1, 32))
        self.assertTrue(bool(torch.isfinite(result).all()))


if __name__ == "__main__":
    unittest.main()
