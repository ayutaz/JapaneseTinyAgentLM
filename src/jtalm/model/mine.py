# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Hard-negative mining for training data v0.5.

    uv run --group train python -m jtalm.model.mine --ckpt <best.pt> \
        --tokenizer tokenizer/out/action_v0_sp2048.model \
        --pool datasets/raw/mine_pool/pool.jsonl --out artifacts/raw_mined

Runs the current Action LM (grammar + confidence gate, as deployed) over human-written sentences
that are not requests (jtalm.data.human_eval.mining_pool) and keeps every sentence where it still
outputs an action. Those are written as ``train_gen.jsonl`` candidates labelled ``[]`` so that
``jtalm.data.generate --phase train-verify`` (Qwen3, temperature 0) can confirm them; only
sentences Qwen3 also maps to ``[]`` enter the training data.
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from jtalm.model.data import Codec
from jtalm.model.decode import greedy
from jtalm.model.evaluate import load_model
from jtalm.model.grammar import ActionGrammar
from jtalm.model.train import pick_device


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gate", type=float, default=0.97004)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args(argv)

    device = pick_device(args.device)
    codec = Codec(args.tokenizer)
    model, _ = load_model(args.ckpt, device)
    pool = [json.loads(x) for x in args.pool.open(encoding="utf-8")]
    t0 = time.time()
    preds = greedy(
        model, codec, [r["text"] for r in pool], batch_size=args.batch_size,
        grammar=ActionGrammar(codec),
    )  # fmt: skip
    mined = []
    for r, p in zip(pool, preds, strict=True):
        if p.text != "[]" and p.min_prob >= args.gate:
            mined.append(
                {
                    "split": "train",
                    "spec_id": "mined.no_action",
                    "category": "no_action",
                    "label": [],
                    "text": r["text"],
                    "language": "ja",
                    "generator": f"human:{r['source']}",
                    "prompt_version": "mined-v1",
                    "model_output": p.text,
                    "model_min_prob": round(p.min_prob, 5),
                }
            )
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "train_gen.jsonl").open("w", encoding="utf-8") as f:
        for r in mined:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {
        "pool": len(pool),
        "mined": len(mined),
        "by_source": dict(Counter(r["generator"] for r in mined)),
        "sec": round(time.time() - t0),
        "ckpt": str(args.ckpt),
        "gate": args.gate,
    }
    (args.out / "summary_mine.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
