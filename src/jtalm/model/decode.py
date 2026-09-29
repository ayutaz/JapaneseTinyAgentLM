"""Greedy decoding for the Action LM.

Prompts are grouped by token length so a batch needs no padding (RoPE positions stay exact).
Each prediction also carries the minimum probability of its generated tokens, which M5 uses as
the confidence gate.
"""

from collections import defaultdict
from dataclasses import dataclass

import torch

from jtalm.model.data import MAX_TARGET_TOKENS, Codec
from jtalm.model.transformer import ActionLM


@dataclass(frozen=True)
class Prediction:
    text: str
    min_prob: float
    tokens: int


@torch.no_grad()
def greedy(
    model: ActionLM,
    codec: Codec,
    prompts: list[str],
    batch_size: int = 256,
    max_new_tokens: int = MAX_TARGET_TOKENS,
) -> list[Prediction]:
    was_training = model.training
    model.eval()
    device = next(model.parameters()).device
    by_len: dict[int, list[int]] = defaultdict(list)
    encoded = [codec.prompt_ids(p) for p in prompts]
    for i, ids in enumerate(encoded):
        by_len[len(ids)].append(i)

    results: list[Prediction | None] = [None] * len(prompts)
    for length, idxs in sorted(by_len.items()):
        steps = min(max_new_tokens, model.cfg.max_seq_len - length)
        for s in range(0, len(idxs), batch_size):
            chunk = idxs[s : s + batch_size]
            x = torch.tensor([encoded[i] for i in chunk], dtype=torch.long, device=device)
            done = torch.zeros(len(chunk), dtype=torch.bool, device=device)
            min_prob = torch.ones(len(chunk), device=device)
            for _ in range(steps):
                probs = model(x)[:, -1].float().softmax(-1)
                p, nxt = probs.max(-1)
                min_prob = torch.where(done, min_prob, torch.minimum(min_prob, p))
                nxt = torch.where(done, torch.full_like(nxt, codec.eos), nxt)
                x = torch.cat([x, nxt[:, None]], dim=1)
                done |= nxt == codec.eos
                if bool(done.all()):
                    break
            for row, i in enumerate(chunk):
                gen = x[row, length:].tolist()
                n = gen.index(codec.eos) + 1 if codec.eos in gen else len(gen)
                results[i] = Prediction(
                    text=codec.decode_target(gen), min_prob=float(min_prob[row]), tokens=n
                )
    model.train(was_training)
    return [r for r in results if r is not None]
