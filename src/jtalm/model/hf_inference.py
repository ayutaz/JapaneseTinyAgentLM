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
from collections import defaultdict
from pathlib import Path

import sentencepiece as spm
import torch
import torch.nn.functional as F
from safetensors.torch import load_file
from torch import nn

MAX_TARGET_TOKENS = 24
DIRECTIONS = ("left", "right", "up", "down", "up_left", "up_right", "down_left", "down_right",
              "center")  # fmt: skip
AMOUNTS = ("slight", "normal", "large")
# Action schema v1 (action_schema_v1.json): tool -> (first argument, its values or range,
# {second argument: its values or range}). A range is a Python range of integers.
TOOLS = {
    "look": ("direction", DIRECTIONS, {"amount": AMOUNTS, "degrees": range(1, 181)}),
    "turn": ("direction", DIRECTIONS[:-1], {"amount": AMOUNTS, "degrees": range(1, 181)}),
    "nod": ("count", range(1, 6), {}),
    "shake": ("count", range(1, 6), {}),
    "bow": (None, (), {}),
    "set_expression": ("expression", ("happy", "sad", "surprised", "neutral", "angry",
                                      "sleepy", "doubt"), {}),
    "set_led": ("color", ("red", "orange", "yellow", "green", "light_blue", "blue", "purple",
                          "pink", "white", "off"), {}),
    "set_volume": ("level", range(0, 101), {}),
    "adjust_volume": ("direction", ("up", "down"), {"amount": AMOUNTS, "by": range(1, 101)}),
    "set_brightness": ("level", range(0, 101), {}),
    "adjust_brightness": ("direction", ("up", "down"), {"amount": AMOUNTS, "by": range(1, 101)}),
}  # fmt: skip


def _options(values) -> list[tuple[str, ...]]:
    if isinstance(values, range):
        return [tuple(str(n)) for n in values]
    return [(v,) for v in values]


def _q(values) -> str:
    return "" if isinstance(values, range) else '"'


def call_pieces() -> list[tuple[str, ...]]:
    """Every valid call as its token pieces (look toward center takes only amount normal)."""
    calls = []
    for name, (key, first, seconds) in TOOLS.items():
        if key is None:
            calls.append((f'{{"name":"{name}","arguments":{{}}}}',))
            continue
        head = f'{{"name":"{name}","arguments":{{"{key}":{_q(first)}'
        for value in _options(first):
            if not seconds:
                calls.append((head, *value, '"}}' if _q(first) else "}}"))
                continue
            for skey, svalues in seconds.items():
                options = _options(svalues)
                if name == "look" and value == ("center",):
                    if skey != "amount":
                        continue
                    options = [("normal",)]
                for w in options:
                    calls.append((head, *value, f'","{skey}":{_q(svalues)}', *w,
                                  '"}}' if _q(svalues) else "}}"))  # fmt: skip
    return calls


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

    Calls form a trie over ``call_pieces()``; a piece is allowed when some call below it differs
    from the first call. The ids are returned in ascending order.
    """

    def __init__(self, sp: spm.SentencePieceProcessor) -> None:
        def tid(piece: str) -> int:
            ids = sp.encode(piece)
            if len(ids) != 1:
                raise ValueError(f"the tokenizer lacks the Action grammar piece {piece!r}")
            return ids[0]

        calls = call_pieces()
        pieces = {"[]", "[", "]", ","} | {p for c in calls for p in c}
        self.id = {p: tid(p) for p in sorted(pieces)}
        self.piece = {i: p for p, i in self.id.items()}
        self.eos = sp.eos_id()
        self._complete = set(calls)
        self._below: dict[tuple[str, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for c in calls:
            for k in range(len(c)):
                self._below[c[:k]][c[k]] += 1

    def _parse(self, generated: list[int]) -> tuple[str, list[tuple[str, ...]], tuple[str, ...]]:
        """Outer step, completed calls, and the pieces of the call being built."""
        step, calls, current = "start", [], ()
        for token in generated:
            piece = self.piece.get(token)
            if step == "start":
                step = "empty" if piece == "[]" else "call"
            elif step == "call":
                current = (*current, piece)
                if current in self._complete:
                    calls.append(current)
                    current = ()
                    step = "after_call"
            elif step == "after_call":
                step = "call" if piece == "," else "end"
            else:  # empty / end
                step = "done"
        return step, calls, current

    def allowed(self, generated: list[int]) -> list[int]:
        step, calls, current = self._parse(generated)
        if step == "start":
            return sorted([self.id["[]"], self.id["["]])
        if step == "call":
            first = calls[0] if calls else None
            out = []
            for piece, n in self._below[current].items():
                if first is not None and first[: len(current) + 1] == (*current, piece):
                    n -= 1  # the first call itself is one of the calls below this piece
                if n > 0:
                    out.append(self.id[piece])
            return sorted(out)
        if step == "after_call":
            return sorted([self.id[","], self.id["]"]]) if len(calls) == 1 else [self.id["]"]]
        return [self.eos]  # "empty" / "end" / "done"


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
