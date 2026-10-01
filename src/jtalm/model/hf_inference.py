# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Standalone inference for JapaneseTinyAgentLM Action 3M (published as ``inference.py``).

Needs only torch (with numpy), sentencepiece and safetensors. Place it next to the model files
(``config.json``, ``model.safetensors``, ``tokenizer.model``) and run:

    python inference.py 右を向いて 笑わないでね
    python inference.py              # one request per line from stdin

or from Python:

    from inference import ActionModel
    model = ActionModel(".")
    model("右を向いて")  # -> [{"name": "look", "arguments": {...}}]

Decoding is greedy with the Action schema grammar, then the confidence gate: if the smallest
probability of a generated token (before the grammar mask) is below ``gate_threshold`` in
config.json, the result is ``[]`` (do nothing). The published evaluation uses exactly this.

This file is a self-contained copy of the project's PyTorch code (Apache-2.0).
"""

import json
import sys
from pathlib import Path

import sentencepiece as spm
import torch
import torch.nn.functional as F
from safetensors.torch import load_file
from torch import nn

MAX_TARGET_TOKENS = 24
DIRECTIONS = ("left", "right", "up", "down", "center")
AMOUNTS = ("slight", "normal", "large")
EXPRESSIONS = ("happy", "sad", "surprised", "neutral")
COUNTS = ("1", "2", "3")
LOOK = '{"name":"look","arguments":{"direction":"'
AMOUNT_KEY = '","amount":"'
EXPR = '{"name":"set_expression","arguments":{"expression":"'
NOD = '{"name":"nod","arguments":{"count":'


# -- model ---------------------------------------------------------------------------------------


class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float) -> None:
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x32 = x.float()
        x32 = x32 * torch.rsqrt(x32.pow(2).mean(-1, keepdim=True) + self.eps)
        return x32.type_as(x) * self.weight


def apply_rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    x1, x2 = x[..., 0::2].float(), x[..., 1::2].float()
    out = torch.stack((x1 * cos - x2 * sin, x1 * sin + x2 * cos), dim=-1)
    return out.flatten(-2).type_as(x)


class Attention(nn.Module):
    def __init__(self, c: dict) -> None:
        super().__init__()
        self.c = c
        hd = c["d_model"] // c["n_heads"]
        self.hd = hd
        self.wq = nn.Linear(c["d_model"], c["n_heads"] * hd, bias=False)
        self.wk = nn.Linear(c["d_model"], c["n_kv_heads"] * hd, bias=False)
        self.wv = nn.Linear(c["d_model"], c["n_kv_heads"] * hd, bias=False)
        self.wo = nn.Linear(c["n_heads"] * hd, c["d_model"], bias=False)

    def forward(self, x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
        b, t, _ = x.shape
        nh, nkv = self.c["n_heads"], self.c["n_kv_heads"]
        q = self.wq(x).view(b, t, nh, self.hd).transpose(1, 2)
        k = self.wk(x).view(b, t, nkv, self.hd).transpose(1, 2)
        v = self.wv(x).view(b, t, nkv, self.hd).transpose(1, 2)
        q, k = apply_rope(q, cos, sin), apply_rope(k, cos, sin)
        k, v = k.repeat_interleave(nh // nkv, dim=1), v.repeat_interleave(nh // nkv, dim=1)
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        return self.wo(y.transpose(1, 2).reshape(b, t, -1))


class MLP(nn.Module):
    def __init__(self, c: dict) -> None:
        super().__init__()
        self.w1 = nn.Linear(c["d_model"], c["d_ff"], bias=False)
        self.w3 = nn.Linear(c["d_model"], c["d_ff"], bias=False)
        self.w2 = nn.Linear(c["d_ff"], c["d_model"], bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.w2(F.silu(self.w1(x)) * self.w3(x))


class Block(nn.Module):
    def __init__(self, c: dict) -> None:
        super().__init__()
        self.attn_norm = RMSNorm(c["d_model"], c["norm_eps"])
        self.attn = Attention(c)
        self.mlp_norm = RMSNorm(c["d_model"], c["norm_eps"])
        self.mlp = MLP(c)

    def forward(self, x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.attn_norm(x), cos, sin)
        return x + self.mlp(self.mlp_norm(x))


class Transformer(nn.Module):
    """Decoder-only: RMSNorm, RoPE, GQA, SwiGLU, tied input/output embeddings, no biases."""

    def __init__(self, c: dict) -> None:
        super().__init__()
        self.embed = nn.Embedding(c["vocab_size"], c["d_model"])
        self.blocks = nn.ModuleList(Block(c) for _ in range(c["n_layers"]))
        self.norm = RMSNorm(c["d_model"], c["norm_eps"])
        hd = c["d_model"] // c["n_heads"]
        inv = 1.0 / (c["rope_theta"] ** (torch.arange(0, hd, 2).float() / hd))
        angles = torch.outer(torch.arange(c["max_seq_len"]).float(), inv)
        self.register_buffer("rope_cos", angles.cos(), persistent=False)
        self.register_buffer("rope_sin", angles.sin(), persistent=False)

    def forward(self, idx: torch.Tensor) -> torch.Tensor:
        t = idx.shape[1]
        cos, sin = self.rope_cos[:t], self.rope_sin[:t]
        x = self.embed(idx)
        for block in self.blocks:
            x = block(x, cos, sin)
        return F.linear(self.norm(x), self.embed.weight)


# -- grammar -------------------------------------------------------------------------------------


class Grammar:
    """Allowed next tokens so that the output is always valid Action JSON:

    [] | [ CALL ] | [ CALL , CALL ]  (the second call differs from the first)
    CALL = LOOK direction ","amount":" amount "}}  (amount is normal when direction is center)
         | EXPR expression "}} | NOD count }}       (count is 1..3)
    """

    def __init__(self, sp: spm.SentencePieceProcessor) -> None:
        def tid(piece: str) -> int:
            ids = sp.encode(piece)
            assert len(ids) == 1, piece
            return ids[0]

        pieces = ("[]", "[", "]", ",", LOOK, AMOUNT_KEY, EXPR, NOD, '"}}', "}}")
        self.id = {p: tid(p) for p in pieces}
        self.values = {v: tid(v) for v in (*DIRECTIONS, *AMOUNTS, *EXPRESSIONS, *COUNTS)}
        self.piece = {i: p for p, i in {**self.id, **self.values}.items()}
        self.eos = sp.eos_id()

    def _state(self, generated: list[int]) -> tuple[str, list[tuple], list[str]]:
        step, calls, current = "start", [], []
        for token in generated:
            piece = self.piece.get(token)
            if step == "start":
                step = "empty" if piece == "[]" else "call"
            elif step == "call":
                name = {LOOK: "look", EXPR: "set_expression", NOD: "nod"}[piece]
                current = [name]
                step = {"look": "direction", "set_expression": "expression", "nod": "count"}[name]
            elif step == "direction":
                current.append(piece)
                step = "amount_key"
            elif step == "amount_key":
                step = "amount"
            elif step in ("amount", "expression", "count"):
                current.append(piece)
                step = "close"
            elif step == "close":
                calls.append(tuple(current))
                current = []
                step = "after_call"
            elif step == "after_call":
                step = "call" if piece == "," else "end"
            elif step in ("empty", "end"):
                step = "done"
        return step, calls, current

    def allowed(self, generated: list[int]) -> list[int]:
        step, calls, current = self._state(generated)
        first = calls[0] if calls else None

        def not_duplicate(options: list[str]) -> list[int]:
            if first is not None and first[:-1] == tuple(current):
                options = [o for o in options if o != first[-1]]
            return [self.values[o] for o in options]

        if step == "start":
            return [self.id["[]"], self.id["["]]
        if step == "call":
            return [self.id[LOOK], self.id[EXPR], self.id[NOD]]
        if step == "direction":
            dirs = list(DIRECTIONS)
            if first == ("look", "center", "normal"):
                dirs.remove("center")  # the only amount would duplicate the first call
            return [self.values[d] for d in dirs]
        if step == "amount_key":
            return [self.id[AMOUNT_KEY]]
        if step == "amount":
            return not_duplicate(["normal"] if current[1] == "center" else list(AMOUNTS))
        if step == "expression":
            return not_duplicate(list(EXPRESSIONS))
        if step == "count":
            return not_duplicate(list(COUNTS))
        if step == "close":
            return [self.id["}}"] if current[0] == "nod" else self.id['"}}']]
        if step == "after_call":
            return [self.id[","], self.id["]"]] if len(calls) == 1 else [self.id["]"]]
        return [self.eos]


# -- public API ----------------------------------------------------------------------------------


class ActionModel:
    def __init__(self, folder: str | Path = Path(__file__).parent, device: str = "cpu") -> None:
        folder = Path(folder)
        self.config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        self.sp = spm.SentencePieceProcessor(model_file=str(folder / self.config["tokenizer"]))
        self.model = Transformer(self.config)
        self.model.load_state_dict(load_file(str(folder / "model.safetensors")))
        self.model.to(device).eval()
        self.device = device
        self.grammar = Grammar(self.sp)
        self.gate = self.config["gate_threshold"]

    @torch.no_grad()
    def predict(self, text: str) -> dict:
        """Return the actions, the confidence (smallest token probability) and the raw output."""
        sp, max_len = self.sp, self.config["max_seq_len"]
        body = sp.encode(text)[: max_len - MAX_TARGET_TOKENS - 3]
        ids = [sp.bos_id(), sp.piece_to_id("<act>"), *body, sp.piece_to_id("<out>")]
        x = torch.tensor([ids], device=self.device)
        generated: list[int] = []
        min_prob = 1.0
        for _ in range(min(MAX_TARGET_TOKENS, max_len - len(ids))):
            probs = self.model(x)[0, -1].float().softmax(-1)
            allowed = self.grammar.allowed(generated)
            nxt = allowed[int(probs[allowed].argmax())]
            min_prob = min(min_prob, float(probs[nxt]))
            if nxt == sp.eos_id():
                break
            generated.append(nxt)
            x = torch.cat([x, torch.tensor([[nxt]], device=self.device)], dim=1)
        raw = sp.decode(generated)
        actions = [] if min_prob < self.gate else json.loads(raw)
        return {"actions": actions, "confidence": round(min_prob, 4), "raw": raw}

    def __call__(self, text: str) -> list[dict]:
        return self.predict(text)["actions"]


def main() -> None:
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    model = ActionModel()
    texts = sys.argv[1:] or (line.strip() for line in sys.stdin)
    for text in texts:
        if text:
            result = model.predict(text)
            print(json.dumps({"input": text, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
