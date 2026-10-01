# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Assemble evaluation set v2: one file per phrasing slice (jtalm.data.focus).

    uv run python -m jtalm.data.eval_v2 --raw <run>/artifacts/raw_eval_v2

Sentences written by llm-jp-3.1 (eval-only writer) are kept when they pass the light checks and
Qwen3's temperature-0 parse equals the spec label (same rule as jtalm.data.build). Anything that
duplicates the training data (v0.4 and, when present, v0.5), the v0 evaluation set, or the
human-written set is dropped. The files are frozen once written; the manifest records sha256s.
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jtalm.action.schema import canonicalize
from jtalm.data.build import _keep
from jtalm.data.checks import dedup_key, normalize
from jtalm.eval.cases import EvalCase, load_cases, write_cases
from jtalm.infra.env import PROJECT_ROOT

EXCLUDE = [
    "datasets/action/v0.4/train.jsonl",
    "datasets/action/v0.4/val.jsonl",
    "datasets/action/v0.5/train.jsonl",
    "datasets/action/v0.5/val.jsonl",
    "datasets/action/v0/eval.jsonl",
    "datasets/action/human_v1/eval.jsonl",
]


def exclusion_keys(paths: list[str]) -> set[str]:
    keys: set[str] = set()
    for rel in paths:
        path = PROJECT_ROOT / rel
        if path.exists():
            keys |= {dedup_key(c.prompt) for c in load_cases(path)}
    return keys


def build(raw_dir: Path, out_dir: Path, exclude: set[str]) -> dict[str, Any]:
    rows = [json.loads(x) for x in (raw_dir / "eval_raw.jsonl").open(encoding="utf-8")]
    stats: dict[str, Counter] = defaultdict(Counter)
    seen = set(exclude)
    by_slice: dict[str, list[EvalCase]] = defaultdict(list)
    for r in rows:
        slice_ = r.get("slice", "unknown")
        ok, reason = _keep(r)
        key = dedup_key(r["text"])
        if ok and key in seen:
            ok, reason = False, "duplicate_or_leak"
        stats[slice_][reason] += 1
        if not ok:
            continue
        seen.add(key)
        text = normalize(r["text"])
        digest = hashlib.sha1(f"{slice_}:{text}".encode()).hexdigest()[:12]
        by_slice[slice_].append(
            EvalCase(
                id=f"ev2-{slice_}-{digest}",
                prompt=text,
                expected=canonicalize(r["label"]),
                category=r["category"],
                language=r["language"],
                source=f"synthetic:{r['generator']}",
            )
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for slice_, cases in sorted(by_slice.items()):
        path = out_dir / f"{slice_}.jsonl"
        write_cases(path, cases)
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "counts": {s: len(c) for s, c in sorted(by_slice.items())},
        "by_category": {
            s: dict(Counter(c.category for c in cases)) for s, cases in sorted(by_slice.items())
        },
        "filter_stats": {s: dict(v) for s, v in sorted(stats.items())},
        "files": files,
        "excluded_against": EXCLUDE,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "datasets/action/eval_v2")
    parser.add_argument(
        "--manifest", type=Path, default=PROJECT_ROOT / "datasets/manifests/action_eval_v2.json"
    )
    args = parser.parse_args()
    report = build(args.raw, args.out, exclusion_keys(EXCLUDE))
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["counts"], indent=1))


if __name__ == "__main__":
    main()
