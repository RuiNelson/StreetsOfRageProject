"""Stable-Baselines3 PPO training entry point."""

from __future__ import annotations

import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any

import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv, VecMonitor
from torch import nn

from .environment import (
    EnvironmentConfig,
    ensure_launch_port_available,
    make_environment,
)
from .perceiver import PerceiverLiteExtractor


def perceiver_policy_kwargs() -> dict[str, Any]:
    """Return the agreed compact Perceiver/PPO policy configuration."""

    return {
        "features_extractor_class": PerceiverLiteExtractor,
        "features_extractor_kwargs": {
            "features_dim": 256,
            "input_dim": 16,
            "latent_dim": 64,
            "num_latents": 128,
            "heads": 4,
            "self_attention_blocks": 2,
            "reduction": 16,
        },
        "net_arch": {"pi": [128], "vf": [128]},
        "activation_fn": nn.GELU,
        "log_std_init": -1.0,
        "normalize_images": False,
    }


def _require_mps() -> torch.device:
    if not torch.backends.mps.is_built():
        raise RuntimeError("this PyTorch build does not include MPS support")
    if not torch.backends.mps.is_available():
        raise RuntimeError(
            "PyTorch MPS is unavailable; training deliberately refuses a CPU fallback"
        )
    return torch.device("mps")


def train_from_args(args: Any) -> int:
    """Construct vector environments and train or resume PPO on MPS."""

    base_config = EnvironmentConfig(
        host=args.host,
        port=args.port,
        character=args.character,
        startup_timeout_ms=args.startup_timeout_ms,
        step_timeout_ms=args.step_timeout_ms,
        max_episode_steps=args.max_episode_steps,
        launch_game=args.launch_games,
        executable=args.game_executable,
        rom=args.rom,
        process_timeout_seconds=args.process_timeout_seconds,
        seed=args.seed,
    )
    if base_config.launch_game:
        for worker in range(args.n_envs):
            ensure_launch_port_available(base_config.port + worker)
    device = _require_mps()

    env_factories = [
        (
            lambda worker=worker: make_environment(
                replace(
                    base_config,
                    port=base_config.port + worker,
                    seed=base_config.seed + worker,
                )
            )
        )
        for worker in range(args.n_envs)
    ]
    if args.n_envs == 1:
        raw_env = DummyVecEnv(env_factories)
    else:
        raw_env = SubprocVecEnv(env_factories, start_method="spawn")
    env = VecMonitor(raw_env)

    output = Path(args.model_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output.parent / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    tensorboard_dir = output.parent / "tensorboard"
    tensorboard_dir.mkdir(parents=True, exist_ok=True)

    try:
        # SB3 warns solely because the outer class is named MlpPolicy; it
        # cannot see that our custom extractor is attention/Conv1D-heavy.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="You are trying to run PPO on the GPU.*",
                category=UserWarning,
            )
            if args.resume:
                model = PPO.load(
                    Path(args.resume).expanduser().resolve(),
                    env=env,
                    device=device,
                )
                reset_num_timesteps = False
            else:
                model = PPO(
                    "MlpPolicy",
                    env,
                    device=device,
                    policy_kwargs=perceiver_policy_kwargs(),
                    learning_rate=3e-4,
                    n_steps=args.n_steps,
                    batch_size=args.batch_size,
                    n_epochs=4,
                    gamma=0.99,
                    gae_lambda=0.95,
                    clip_range=0.2,
                    ent_coef=0.01,
                    target_kl=0.03,
                    tensorboard_log=str(tensorboard_dir),
                    seed=args.seed,
                    verbose=1,
                )
                reset_num_timesteps = True

        callback = CheckpointCallback(
            save_freq=max(args.checkpoint_frequency // args.n_envs, 1),
            save_path=str(checkpoint_dir),
            name_prefix="ppo_sor",
        )
        model.learn(
            total_timesteps=args.total_timesteps,
            callback=callback,
            reset_num_timesteps=reset_num_timesteps,
            progress_bar=args.progress_bar,
        )
        model.save(str(output))
    finally:
        env.close()
    return 0
