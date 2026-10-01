# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Greedy decoding for the Action LM.

Prompts are grouped by token length so a batch needs no padding (RoPE positions stay exact).
Each prediction also carries the minimum probability of its generated tokens, which M5 uses as
the confidence gate. With ``grammar`` (``jtalm.model.grammar.ActionGrammar``) each step picks the
most likely token among those the schema allows; ``min_prob`` still uses the unconstrained
probability of the chosen token, so a forced token lowers the confidence.
"""

from collections import defaultdict
from dataclasses import dataclass

import torch

from jtalm.model.data import MAX_TARGET_TOKENS, Codec
from jtalm.model.grammar import ActionGrammar
from jtalm.model.transformer import ActionLM


@dataclass(frozen=True)
class Prediction:
    text: str
    min_prob: float
    tokens: int
    ids: tuple[int, ...] = ()  # generated ids up to and including </s>


@torch.no_grad()
def greedy(
    model: ActionLM,
    codec: Codec,
    prompts: list[str],
    batch_size: int = 256,
    max_new_tokens: int = MAX_TARGET_TOKENS,
    grammar: ActionGrammar | None = None,
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
                if grammar is None:
                    p, nxt = probs.max(-1)
                else:
                    mask = torch.full_like(probs, -1.0)
                    for row in range(len(chunk)):
                        if not done[row]:
                            ids = grammar.allowed(x[row, length:].tolist())
                            mask[row, ids] = probs[row, ids]
                    nxt = mask.argmax(-1)
                    p = probs.gather(1, nxt[:, None]).squeeze(1)
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
                    text=codec.decode_target(gen),
                    min_prob=float(min_prob[row]),
                    tokens=n,
                    ids=tuple(gen[:n]),
                )
    model.train(was_training)
    return [r for r in results if r is not None]
