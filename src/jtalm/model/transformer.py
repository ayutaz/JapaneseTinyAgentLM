# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Decoder-only Transformer for the Action LM (docs/architecture.md).

RMSNorm (pre-norm), RoPE, grouped-query attention, SwiGLU MLP, and tied input/output embeddings.
No biases, so the weights map directly onto a small C runtime later (M6).
"""

import math
from dataclasses import asdict, dataclass

import torch
import torch.nn.functional as F
from torch import nn


@dataclass(frozen=True)
class ModelConfig:
    vocab_size: int
    d_model: int
    n_layers: int
    n_heads: int
    n_kv_heads: int
    d_ff: int
    max_seq_len: int = 128
    dropout: float = 0.0
    rope_theta: float = 10000.0
    norm_eps: float = 1e-5

    @property
    def head_dim(self) -> int:
        return self.d_model // self.n_heads

    def to_dict(self) -> dict:
        return asdict(self)


# Sizes count every parameter including the (tied) embedding; see ``count_params``.
SIZES: dict[str, dict] = {
    "3m": dict(d_model=192, n_layers=7, n_heads=6, n_kv_heads=2, d_ff=512),
    "5m": dict(d_model=256, n_layers=6, n_heads=8, n_kv_heads=2, d_ff=768),
    "20m": dict(d_model=384, n_layers=12, n_heads=6, n_kv_heads=2, d_ff=1024),
}


def make_config(size: str, vocab_size: int, dropout: float = 0.0) -> ModelConfig:
    return ModelConfig(vocab_size=vocab_size, dropout=dropout, **SIZES[size])


class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float) -> None:
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x32 = x.float()
        x32 = x32 * torch.rsqrt(x32.pow(2).mean(-1, keepdim=True) + self.eps)
        return x32.type_as(x) * self.weight


def rope_tables(cfg: ModelConfig) -> tuple[torch.Tensor, torch.Tensor]:
    inv = 1.0 / (cfg.rope_theta ** (torch.arange(0, cfg.head_dim, 2).float() / cfg.head_dim))
    angles = torch.outer(torch.arange(cfg.max_seq_len).float(), inv)  # (T, head_dim/2)
    return angles.cos(), angles.sin()


def apply_rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    """Rotate pairs (x[2i], x[2i+1]); x is (B, H, T, D)."""
    x1, x2 = x[..., 0::2].float(), x[..., 1::2].float()
    out = torch.stack((x1 * cos - x2 * sin, x1 * sin + x2 * cos), dim=-1)
    return out.flatten(-2).type_as(x)


def fake_quant_kv(x: torch.Tensor) -> torch.Tensor:
    """INT8 KV cache as in the C runtime built with JTLM_KV_INT8: each head vector (last dim)
    gets one f32 scale = max|x| / 127 and int8 codes rounded half to even; returns q * scale."""
    scale = x.abs().amax(-1, keepdim=True) / 127
    q = torch.where(scale > 0, torch.round(x / scale), torch.zeros_like(x)).clamp(-127, 127)
    return q * scale


class Attention(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.kv_int8 = False  # inference only: see set_kv_int8
        hd = cfg.head_dim
        self.wq = nn.Linear(cfg.d_model, cfg.n_heads * hd, bias=False)
        self.wk = nn.Linear(cfg.d_model, cfg.n_kv_heads * hd, bias=False)
        self.wv = nn.Linear(cfg.d_model, cfg.n_kv_heads * hd, bias=False)
        self.wo = nn.Linear(cfg.n_heads * hd, cfg.d_model, bias=False)

    def forward(self, x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
        b, t, _ = x.shape
        c = self.cfg
        q = self.wq(x).view(b, t, c.n_heads, c.head_dim).transpose(1, 2)
        k = self.wk(x).view(b, t, c.n_kv_heads, c.head_dim).transpose(1, 2)
        v = self.wv(x).view(b, t, c.n_kv_heads, c.head_dim).transpose(1, 2)
        q, k = apply_rope(q, cos, sin), apply_rope(k, cos, sin)
        if self.kv_int8:
            k, v = fake_quant_kv(k), fake_quant_kv(v)
        rep = c.n_heads // c.n_kv_heads
        k, v = k.repeat_interleave(rep, dim=1), v.repeat_interleave(rep, dim=1)
        p = c.dropout if self.training else 0.0
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True, dropout_p=p)
        return self.wo(y.transpose(1, 2).reshape(b, t, -1))


class MLP(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.w1 = nn.Linear(cfg.d_model, cfg.d_ff, bias=False)  # gate
        self.w3 = nn.Linear(cfg.d_model, cfg.d_ff, bias=False)  # up
        self.w2 = nn.Linear(cfg.d_ff, cfg.d_model, bias=False)  # down

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.w2(F.silu(self.w1(x)) * self.w3(x))


class Block(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.attn_norm = RMSNorm(cfg.d_model, cfg.norm_eps)
        self.attn = Attention(cfg)
        self.mlp_norm = RMSNorm(cfg.d_model, cfg.norm_eps)
        self.mlp = MLP(cfg)
        self.drop = nn.Dropout(cfg.dropout)

    def forward(self, x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
        x = x + self.drop(self.attn(self.attn_norm(x), cos, sin))
        return x + self.drop(self.mlp(self.mlp_norm(x)))


class ActionLM(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        assert cfg.d_model % cfg.n_heads == 0 and cfg.n_heads % cfg.n_kv_heads == 0
        self.cfg = cfg
        self.embed = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.drop = nn.Dropout(cfg.dropout)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layers))
        self.norm = RMSNorm(cfg.d_model, cfg.norm_eps)
        cos, sin = rope_tables(cfg)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.apply(self._init)
        # Scale residual output projections by depth (GPT-2 style).
        for name, p in self.named_parameters():
            if name.endswith(("wo.weight", "w2.weight")):
                nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * cfg.n_layers))

    @staticmethod
    def _init(m: nn.Module) -> None:
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward(self, idx: torch.Tensor) -> torch.Tensor:
        """Return logits (B, T, vocab) for token ids (B, T)."""
        t = idx.shape[1]
        if t > self.cfg.max_seq_len:
            raise ValueError(f"sequence length {t} > max_seq_len {self.cfg.max_seq_len}")
        cos, sin = self.rope_cos[:t], self.rope_sin[:t]
        x = self.drop(self.embed(idx))
        for block in self.blocks:
            x = block(x, cos, sin)
        return F.linear(self.norm(x), self.embed.weight)  # tied output head


def set_kv_int8(model: ActionLM, on: bool = True) -> None:
    """Quantize the keys (after RoPE) and values like the C runtime's INT8 KV cache."""
    for block in model.blocks:
        block.attn.kv_int8 = on


def count_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
