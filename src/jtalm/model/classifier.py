# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""A small classifier baseline: character n-grams -> one of the call sequences seen in training.

    uv run --group train python -m jtalm.model.classifier \
        --train datasets/action/v0.5.1/train.jsonl --val datasets/action/v0.5.1/val.jsonl \
        --seed 0 --out runs/local/classifier_v051_s0

fastText-style: the prompt is NFKC-normalized and lowercased, its character 1- to 3-grams (with
start and end marks) are hashed (CRC-32) into ``--buckets`` embeddings of ``--dim`` values, the
mean goes through one linear layer, and the class is a whole canonical call sequence (``[]``
included). It can only output sequences that occur in the training data, so its output is always
valid. The confidence (largest softmax probability) plays the role of the LM's min_prob: the gate
threshold is chosen on the validation set with jtalm.model.evaluate.select_gate. The output
directory has the same layout as jtalm.model.eval_suite (``*_predictions.jsonl``, ``suite.md``),
so jtalm.eval.bootstrap and jtalm.eval.consistency read it as well.
"""

import argparse
import random
import sys
import unicodedata
import zlib
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from torch import nn

from jtalm.action.schema import to_json
from jtalm.eval.cases import EvalCase, load_cases
from jtalm.eval.metrics import score_case
from jtalm.model.eval_suite import write_suite
from jtalm.model.evaluate import select_gate


def ngram_ids(text: str, buckets: int, n_max: int = 3) -> list[int]:
    s = "\x02" + unicodedata.normalize("NFKC", text).lower() + "\x03"
    grams = [s[i : i + n] for n in range(1, n_max + 1) for i in range(len(s) - n + 1)]
    return [zlib.crc32(g.encode("utf-8")) % buckets for g in grams]


class NgramClassifier(nn.Module):
    def __init__(self, buckets: int, dim: int, n_classes: int) -> None:
        super().__init__()
        self.buckets = buckets
        self.embed = nn.EmbeddingBag(buckets, dim, mode="mean")
        self.out = nn.Linear(dim, n_classes)

    def forward(self, ids: torch.Tensor, offsets: torch.Tensor) -> torch.Tensor:
        return self.out(self.embed(ids, offsets))


def batch(texts: list[str], buckets: int) -> tuple[torch.Tensor, torch.Tensor]:
    grams = [ngram_ids(t, buckets) for t in texts]
    offsets = torch.tensor([0] + [len(g) for g in grams[:-1]]).cumsum(0)
    return torch.tensor([i for g in grams for i in g]), offsets


@torch.no_grad()
def probabilities(model: NgramClassifier, texts: list[str], size: int = 1024) -> torch.Tensor:
    model.eval()
    parts = [
        model(*batch(texts[i : i + size], model.buckets)).softmax(-1)
        for i in range(0, len(texts), size)
    ]
    return torch.cat(parts)


def predict_rows(
    model: NgramClassifier, labels: list[str], cases: list[EvalCase], gate: float | None
) -> list[dict[str, Any]]:
    probs = probabilities(model, [c.prompt for c in cases])
    conf, idx = probs.max(-1)
    rows = []
    for c, p, i in zip(cases, conf.tolist(), idx.tolist(), strict=True):
        raw = labels[i]
        text = "[]" if gate is not None and p < gate else raw
        rows.append(
            {
                "id": c.id,
                "category": c.category,
                "language": c.language,
                "prompt": c.prompt,
                "expected": c.expected,
                "output": text,
                "raw_output": raw,
                "min_prob": round(p, 5),
                "exact": score_case(c, text).exact,
            }
        )
    return rows


def val_exact(model: NgramClassifier, labels: list[str], val: list[EvalCase]) -> float:
    rows = predict_rows(model, labels, val, None)
    return sum(r["exact"] for r in rows) / len(rows)


def train(
    train_cases: list[EvalCase],
    val: list[EvalCase],
    buckets: int,
    dim: int,
    epochs: int,
    lr: float,
    batch_size: int,
    seed: int,
) -> tuple[NgramClassifier, list[str], list[dict[str, Any]]]:
    random.seed(seed)
    torch.manual_seed(seed)
    labels = sorted({to_json(c.expected) for c in train_cases})
    index = {lab: i for i, lab in enumerate(labels)}
    texts = [c.prompt for c in train_cases]
    y = torch.tensor([index[to_json(c.expected)] for c in train_cases])
    model = NgramClassifier(buckets, dim, len(labels))
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    best, best_state, log = -1.0, None, []
    order = list(range(len(texts)))
    for epoch in range(1, epochs + 1):
        model.train()
        random.shuffle(order)
        total = 0.0
        for i in range(0, len(order), batch_size):
            part = order[i : i + batch_size]
            loss = F.cross_entropy(model(*batch([texts[j] for j in part], buckets)), y[part])
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item() * len(part)
        acc = val_exact(model, labels, val)
        log.append({"epoch": epoch, "train_loss": total / len(order), "val_exact": acc})
        print(f"epoch {epoch}: loss {total / len(order):.4f} val exact {acc:.4f}")
        if acc > best:
            best, best_state = acc, {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    return model, labels, log


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--val", type=Path, required=True)
    parser.add_argument("--buckets", type=int, default=65536)
    parser.add_argument("--dim", type=int, default=40)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--lr", type=float, default=0.01)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    val = load_cases(args.val)
    model, labels, log = train(
        load_cases(args.train), val, args.buckets, args.dim, args.epochs, args.lr,
        args.batch_size, args.seed,
    )  # fmt: skip
    gate_info = select_gate(predict_rows(model, labels, val, None), val)
    params = sum(p.numel() for p in model.parameters())
    meta = {
        "model": "char 1-3-gram classifier",
        "params": params,
        "classes": len(labels),
        "config": {k: v for k, v in vars(args).items() if k != "out"} | {
            "train": str(args.train), "val": str(args.val)
        },
        "training_log": log,
    }  # fmt: skip
    md = write_suite(
        args.out, lambda cases: predict_rows(model, labels, cases, gate_info["threshold"]),
        gate_info, meta,
    )  # fmt: skip
    print(f"{params:,} params, {len(labels)} classes")
    print(md)


if __name__ == "__main__":
    main()
