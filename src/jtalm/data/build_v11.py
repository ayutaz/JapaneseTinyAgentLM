# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Assemble data v1.1 (data v1.0 plus the LED top-up) and the LED regression evaluation set.

    uv run python -m jtalm.data.build_v11 --raw artifacts/gen_action_v11

1. Data v1.0 train/val are kept unchanged.
2. The LED evaluation set (llm-jp writes, Qwen3 verifies, jtalm.data.specs_v11): kept when Qwen3's
   parse equals the spec label, and when the sentence is not already in data v1.0.
3. New training sentences (ABEJA, Mistral-Nemo-JA, Qwen3 write): same rule, and not in any
   evaluation set (eval v3, Stack-chan v1, the relabeled older sets, the LED set). 5% go to val.
"""

import argparse
import hashlib
import json
import random
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from jtalm.data.build import _case, _filter, _load
from jtalm.data.build_v1 import VAL_FRACTION
from jtalm.data.checks import dedup_key
from jtalm.eval.cases import EvalCase, load_cases, write_cases

V11_WRITER_NAMES = ("qwen", "abeja", "nemoja")  # configs/action_v11_<name>.json
BASE = Path("datasets/action/v1.0")
EVAL_SETS = [
    Path("datasets/action/eval_v3/eval.jsonl"),
    Path("datasets/action/stackchan_v1/eval.jsonl"),
    *(
        p
        for p in sorted(Path("datasets/action/relabel_v1").glob("*.jsonl"))
        if p.name != "overrides.jsonl"
    ),  # fmt: skip
]


def _keys(cases: list[EvalCase]) -> set[str]:
    return {dedup_key(c.prompt) for c in cases}


def build(
    raw: Path, base: Path, eval_sets: list[Path], seed: int
) -> tuple[list[EvalCase], list[EvalCase], list[EvalCase], dict]:
    """Return (train, val, LED eval set, stats)."""
    train, val = load_cases(base / "train.jsonl"), load_cases(base / "val.jsonl")
    stats: dict = {"base": {"train": len(train), "val": len(val)}}

    ev_stats: Counter = Counter()
    seen = _keys(train) | _keys(val)
    led_eval = [
        _case(r, "ev11")
        for r in _filter(_load([raw / "raw11_eval"], "eval_raw.jsonl"), seen, ev_stats)
    ]
    stats["eval_v11_led"] = {"n": len(led_eval), **ev_stats}

    seen = _keys(train) | _keys(val) | _keys(led_eval)
    for path in eval_sets:
        seen |= _keys(load_cases(path))
    new_stats: Counter = Counter()
    dirs = [raw / f"raw11_{w}" for w in V11_WRITER_NAMES if (raw / f"raw11_{w}").is_dir()]
    new_rows = _filter(_load(dirs, "train_raw.jsonl"), seen, new_stats)
    random.Random(seed).shuffle(new_rows)
    n_val = round(len(new_rows) * VAL_FRACTION)
    val += [_case(r, "val") for r in new_rows[:n_val]]
    train += [_case(r, "train") for r in new_rows[n_val:]]
    stats["new"] = {
        "n": len(new_rows),
        "writers": [d.name for d in dirs],
        "by_generator": dict(Counter(r["generator"] for r in new_rows)),
        **new_stats,
    }
    return train, val, led_eval, stats


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--base", type=Path, default=BASE)
    p.add_argument("--out", type=Path, default=Path("datasets/action/v1.1"))
    p.add_argument("--eval-out", type=Path, default=Path("datasets/action/eval_v11_led"))
    p.add_argument("--manifest", type=Path, default=Path("datasets/manifests/action_v1.1.json"))
    p.add_argument("--seed", type=int, default=20261201)
    args = p.parse_args()

    train, val, led_eval, stats = build(args.raw, args.base, EVAL_SETS, args.seed)
    stats = {"created": datetime.now(UTC).isoformat(timespec="seconds"), **stats}
    args.eval_out.mkdir(parents=True, exist_ok=True)
    write_cases(args.eval_out / "eval.jsonl", led_eval)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, cases in (("train", train), ("val", val)):
        write_cases(args.out / f"{name}.jsonl", cases)
        stats[name] = {
            "n": len(cases),
            "by_category": dict(Counter(c.category for c in cases)),
            "sha256": hashlib.sha256((args.out / f"{name}.jsonl").read_bytes()).hexdigest(),
        }
    args.manifest.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: stats[k] for k in ("train", "val", "new", "eval_v11_led")},
                     ensure_ascii=False))  # fmt: skip


if __name__ == "__main__":
    main()
