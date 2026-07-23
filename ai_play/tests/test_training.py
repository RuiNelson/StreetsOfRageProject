from __future__ import annotations

import unittest

try:
    import gymnasium as gym
    import numpy as np
    from stable_baselines3 import PPO

    from ai_play.actions import ACTION_HIGH, ACTION_LOW, ACTION_SIZE
    from ai_play.event_detector import WORK_RAM_SIZE
    from ai_play.training import perceiver_policy_kwargs

    TRAINING_AVAILABLE = True
except ModuleNotFoundError:
    TRAINING_AVAILABLE = False


class ZeroRamEnv(gym.Env if TRAINING_AVAILABLE else object):  # type: ignore[misc]
    """Dependency-light fake used for PPO construction and MPS smoke tests."""

    if TRAINING_AVAILABLE:
        observation_space = gym.spaces.Box(
            0,
            255,
            shape=(WORK_RAM_SIZE,),
            dtype=np.uint8,
        )
        action_space = gym.spaces.Box(
            np.asarray(ACTION_LOW, dtype=np.float32),
            np.asarray(ACTION_HIGH, dtype=np.float32),
            shape=(ACTION_SIZE,),
            dtype=np.float32,
        )

    def reset(self, *, seed=None, options=None):  # type: ignore[no-untyped-def]
        del options
        super().reset(seed=seed)
        return np.zeros(WORK_RAM_SIZE, dtype=np.uint8), {}

    def step(self, action):  # type: ignore[no-untyped-def]
        del action
        return np.zeros(WORK_RAM_SIZE, dtype=np.uint8), 0.0, False, False, {}


@unittest.skipUnless(TRAINING_AVAILABLE, "training dependencies are not installed")
class TrainingTests(unittest.TestCase):
    def test_ppo_policy_uses_the_perceiver_configuration(self) -> None:
        model = PPO(
            "MlpPolicy",
            ZeroRamEnv(),
            device="cpu",
            policy_kwargs=perceiver_policy_kwargs(),
            n_steps=2,
            batch_size=2,
            n_epochs=1,
            verbose=0,
        )
        observation = model.get_env().reset()
        action, _ = model.predict(observation, deterministic=True)
        self.assertEqual(action.shape, (1, ACTION_SIZE))
        self.assertEqual(model.policy.log_std.detach().cpu().tolist(), [-1.0] * ACTION_SIZE)


if __name__ == "__main__":
    unittest.main()
