# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""The Stack-chan everyday-phrasing evaluation set v1 (spec 5.3).

    uv run python -m jtalm.data.stackchan_eval --raw artifacts/raw1

Verbatim utterances from public Stack-chan projects and the user's own requests
(``sources.jsonl``) are labeled by Qwen3 under schema v1 (the ``reverify`` phase); paraphrases
of head moves (sparse on the web) are written by llm-jp and kept when Qwen3 agrees with their
spec. The user reviews every label in ``review.md``; corrections go to ``overrides.jsonl``.
Never used for training or model selection.
"""

import argparse
import hashlib
import json
import random
from pathlib import Path

from jtalm.action.schema import canonicalize, to_json
from jtalm.data.build import _keep
from jtalm.data.checks import normalize
from jtalm.eval.cases import EvalCase, write_cases


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]


def _category(expected: list) -> str:
    if not expected:
        return "no_action"
    return "single" if len(expected) == 1 else "multi_action"


def build(sources: Path, reverified: Path, paraphrase_raw: Path, overrides: Path, out_dir: Path,
          n_paraphrase: int = 40, seed: int = 0) -> dict:  # fmt: skip
    labels = {r["id"]: r.get("verified") for r in _read(reverified)
              if Path(r["file"]).resolve() == sources.resolve()}  # fmt: skip
    fixed = {r["id"]: r["expected"] for r in _read(overrides)}
    cases: list[EvalCase] = []
    stats = {"verbatim": 0, "user": 0, "paraphrase": 0, "overridden": 0}
    for row in _read(sources):
        expected = fixed.get(row["id"], labels.get(row["id"]))
        if not isinstance(expected, list):
            raise ValueError(f"no label for {row['id']}; add it to {overrides}")
        stats["overridden"] += row["id"] in fixed
        stats[row["kind"]] += 1
        source = "user" if row["kind"] == "user" else f"verbatim:{row['source_url']}"
        cases.append(EvalCase(id=row["id"], prompt=row["text"], expected=canonicalize(expected),
                              category=_category(expected), source=source))  # fmt: skip
    kept = [r for r in _read(paraphrase_raw) if _keep(r)[0]]
    random.Random(seed).shuffle(kept)
    for r in kept[:n_paraphrase]:
        text = normalize(r["text"])
        digest = hashlib.sha1(f"stackchan:{text}".encode()).hexdigest()[:12]
        expected = canonicalize(r["label"])
        cases.append(
            EvalCase(
                id=f"sc-p-{digest}",
                prompt=text,
                expected=expected,
                category=_category(expected),
                source=f"paraphrase:{r['generator']}",
            )
        )
        stats["paraphrase"] += 1
    out_dir.mkdir(parents=True, exist_ok=True)
    write_cases(out_dir / "eval.jsonl", cases)
    lines = ["| id | 入力 | 正解 | 出典 |", "|---|---|---|---|"]
    lines += [f"| {c.id} | {c.prompt} | `{to_json(c.expected)}` | {c.source} |" for c in cases]
    (out_dir / "review.md").write_text("\n".join(lines) + "\n", "utf-8")
    return stats


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", type=Path, required=True, help="the job's artifacts directory")
    p.add_argument("--out", type=Path, default=Path("datasets/action/stackchan_v1"))
    args = p.parse_args()
    stats = build(args.out / "sources.jsonl", args.raw / "reverify1/reverify_raw.jsonl",
                  args.raw / "raw1_paraphrase/eval_raw.jsonl", args.out / "overrides.jsonl",
                  args.out)  # fmt: skip
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
