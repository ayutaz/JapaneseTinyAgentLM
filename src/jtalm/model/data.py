# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Tokenize Action examples into ``<s> <act> prompt <out> target </s>`` and batch them."""

import hashlib
import random
from collections.abc import Iterator
from pathlib import Path

import sentencepiece as spm
import torch

from jtalm.action.schema import Call
from jtalm.eval.cases import EvalCase
from jtalm.model.format import ACT, OUT, target_json

IGNORE = -100
MAX_TARGET_TOKENS = 24  # longest v1 target is 17 tokens + </s> (two calls with 3-digit numbers)


class Codec:
    def __init__(self, model_file: str | Path, max_seq_len: int = 128) -> None:
        self.path = Path(model_file)
        self.sp = spm.SentencePieceProcessor(model_file=str(model_file))
        self.max_seq_len = max_seq_len
        self.bos, self.eos, self.pad = self.sp.bos_id(), self.sp.eos_id(), self.sp.pad_id()
        self.act, self.out = self.sp.piece_to_id(ACT), self.sp.piece_to_id(OUT)
        assert min(self.bos, self.eos, self.pad, self.act, self.out) >= 0

    @property
    def vocab_size(self) -> int:
        return self.sp.get_piece_size()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def prompt_ids(self, prompt: str) -> list[int]:
        body = self.sp.encode(prompt)[: self.max_seq_len - MAX_TARGET_TOKENS - 3]
        return [self.bos, self.act, *body, self.out]

    def example(self, prompt: str, calls: list[Call]) -> tuple[list[int], int]:
        """Token ids of a full example and the length of its prompt part."""
        head = self.prompt_ids(prompt)
        return head + self.sp.encode(target_json(calls)) + [self.eos], len(head)

    def decode_target(self, ids: list[int]) -> str:
        if self.eos in ids:
            ids = ids[: ids.index(self.eos)]
        return self.sp.decode(ids)


def encode_cases(codec: Codec, cases: list[EvalCase]) -> list[tuple[list[int], int]]:
    return [codec.example(c.prompt, c.expected) for c in cases]


def collate(examples: list[tuple[list[int], int]], pad: int) -> tuple[torch.Tensor, torch.Tensor]:
    """Inputs and next-token labels; labels are IGNORE except for the target and </s>."""
    width = max(len(ids) for ids, _ in examples) - 1
    x = torch.full((len(examples), width), pad, dtype=torch.long)
    y = torch.full((len(examples), width), IGNORE, dtype=torch.long)
    for i, (ids, n_prompt) in enumerate(examples):
        t = torch.tensor(ids, dtype=torch.long)
        x[i, : len(ids) - 1] = t[:-1]
        y[i, n_prompt - 1 : len(ids) - 1] = t[n_prompt:]
    return x, y


def batches(
    examples: list[tuple[list[int], int]], batch_size: int, rng: random.Random
) -> Iterator[list[tuple[list[int], int]]]:
    order = list(range(len(examples)))
    rng.shuffle(order)
    for i in range(0, len(order), batch_size):
        yield [examples[j] for j in order[i : i + batch_size]]
