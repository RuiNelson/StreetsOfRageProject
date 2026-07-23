"""Memory-efficient Perceiver-style feature extractor for 64 KiB RAM."""

from __future__ import annotations

import torch
from gymnasium import spaces
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from torch import nn

from .event_detector import WORK_RAM_SIZE


class _LatentBlock(nn.Module):
    def __init__(self, latent_dim: int, heads: int) -> None:
        super().__init__()
        self.attention_norm = nn.LayerNorm(latent_dim)
        self.attention = nn.MultiheadAttention(
            latent_dim,
            heads,
            batch_first=True,
        )
        self.feed_forward_norm = nn.LayerNorm(latent_dim)
        self.feed_forward = nn.Sequential(
            nn.Linear(latent_dim, latent_dim * 4),
            nn.GELU(),
            nn.Linear(latent_dim * 4, latent_dim),
        )

    def forward(self, latents: torch.Tensor) -> torch.Tensor:
        normalized = self.attention_norm(latents)
        attended, _ = self.attention(
            normalized,
            normalized,
            normalized,
            need_weights=False,
        )
        latents = latents + attended
        return latents + self.feed_forward(self.feed_forward_norm(latents))


class PerceiverLiteExtractor(BaseFeaturesExtractor):
    """Embed RAM bytes, reduce them to 4096 tokens, then cross-attend."""

    def __init__(
        self,
        observation_space: spaces.Box,
        features_dim: int = 256,
        input_dim: int = 16,
        latent_dim: int = 64,
        num_latents: int = 128,
        heads: int = 4,
        self_attention_blocks: int = 2,
        reduction: int = 16,
    ) -> None:
        if observation_space.shape != (WORK_RAM_SIZE,):
            raise ValueError(
                f"expected a ({WORK_RAM_SIZE},) RAM observation, "
                f"received {observation_space.shape}"
            )
        if WORK_RAM_SIZE % reduction:
            raise ValueError("reduction must divide the Work RAM size")
        super().__init__(observation_space, features_dim)

        self.byte_embedding = nn.Embedding(256, input_dim)
        self.position_embedding = nn.Embedding(WORK_RAM_SIZE, input_dim)
        self.register_buffer(
            "_addresses",
            torch.arange(WORK_RAM_SIZE, dtype=torch.long),
            persistent=False,
        )
        self.input_reduction = nn.Conv1d(
            input_dim,
            latent_dim,
            kernel_size=reduction,
            stride=reduction,
        )

        self.latents = nn.Parameter(torch.empty(num_latents, latent_dim))
        nn.init.normal_(self.latents, mean=0.0, std=0.02)

        self.cross_query_norm = nn.LayerNorm(latent_dim)
        self.cross_input_norm = nn.LayerNorm(latent_dim)
        self.cross_attention = nn.MultiheadAttention(
            latent_dim,
            heads,
            batch_first=True,
        )
        self.cross_feed_forward_norm = nn.LayerNorm(latent_dim)
        self.cross_feed_forward = nn.Sequential(
            nn.Linear(latent_dim, latent_dim * 4),
            nn.GELU(),
            nn.Linear(latent_dim * 4, latent_dim),
        )
        self.latent_blocks = nn.ModuleList(
            _LatentBlock(latent_dim, heads)
            for _ in range(self_attention_blocks)
        )
        self.output = nn.Sequential(
            nn.LayerNorm(latent_dim),
            nn.Linear(latent_dim, features_dim),
            nn.GELU(),
        )

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        byte_values = observations.long().clamp_(0, 255)
        tokens = self.byte_embedding(byte_values)
        tokens = tokens + self.position_embedding(self._addresses).unsqueeze(0)
        tokens = self.input_reduction(tokens.transpose(1, 2)).transpose(1, 2)

        batch_size = observations.shape[0]
        latents = self.latents.unsqueeze(0).expand(batch_size, -1, -1)
        normalized_tokens = self.cross_input_norm(tokens)
        attended, _ = self.cross_attention(
            self.cross_query_norm(latents),
            normalized_tokens,
            normalized_tokens,
            need_weights=False,
        )
        latents = latents + attended
        latents = latents + self.cross_feed_forward(
            self.cross_feed_forward_norm(latents)
        )
        for block in self.latent_blocks:
            latents = block(latents)

        return self.output(latents.mean(dim=1))
