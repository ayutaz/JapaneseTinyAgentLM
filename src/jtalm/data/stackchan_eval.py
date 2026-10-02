# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""The Stack-chan everyday-phrasing evaluation set v1 (spec 5.3).

    uv run python -m jtalm.data.stackchan_eval --raw artifacts/raw1

Verbatim utterances from public Stack-chan projects and the user's own requests
(``sources.jsonl``) are labeled by Qwen3 under schema v1 (the ``reverify`` phase); paraphrases
of head moves (sparse on the web) are written by llm-jp and kept when Qwen3 agrees with their
spec. The user reviews every label in ``review.md``; corrections go to ``overrides.jsonl``
(``{"id": ..., "expected": [...]}``, or ``{"id": ..., "exclude": true}`` to drop a case).
Never used for training or model selection.
"""

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from jtalm.action.schema import canonicalize, to_json, validate
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
    over = _read(overrides)
    fixed = {r["id"]: canonicalize(r["expected"]) for r in over if not r.get("exclude")}
    excluded = {r["id"] for r in over if r.get("exclude")}
    for i, expected in fixed.items():
        if errors := validate(expected):
            raise ValueError(f"override {i!r} is not a valid label: {errors}")
    stats = {"verbatim": 0, "user": 0, "paraphrase": 0, "overridden": 0, "excluded": 0}
    rows: list[tuple[str, str, str, list | None, str]] = []  # kind, id, prompt, label, source
    for row in _read(sources):
        source = "user" if row["kind"] == "user" else f"verbatim:{row['source_url']}"
        rows.append((row["kind"], row["id"], row["text"], labels.get(row["id"]), source))
    kept = [r for r in _read(paraphrase_raw) if _keep(r)[0]]
    random.Random(seed).shuffle(kept)
    for r in kept[:n_paraphrase]:
        text = normalize(r["text"])
        digest = hashlib.sha1(f"stackchan:{text}".encode()).hexdigest()[:12]
        source = f"paraphrase:{r['generator']}"
        rows.append(("paraphrase", f"sc-p-{digest}", text, r["label"], source))
    if unknown := sorted((set(fixed) | excluded) - {i for _, i, *_ in rows}):
        raise ValueError(f"ids in {overrides} match no case: {unknown}")
    cases: list[EvalCase] = []
    for kind, i, prompt, label, source in rows:
        if i in excluded:
            stats["excluded"] += 1
            continue
        expected = fixed.get(i, label)
        if not isinstance(expected, list):
            raise ValueError(f"no label for {i}; add it to {overrides}")
        expected = canonicalize(expected)
        stats["overridden"] += i in fixed
        stats[kind] += 1
        cases.append(EvalCase(id=i, prompt=prompt, expected=expected,
                              category=_category(expected), source=source))  # fmt: skip
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
    p.add_argument(
        "--manifest", type=Path, default=Path("datasets/manifests/action_stackchan_v1.json")
    )
    args = p.parse_args()
    stats = build(args.out / "sources.jsonl", args.raw / "reverify1/reverify_raw.jsonl",
                  args.raw / "raw1_paraphrase/eval_raw.jsonl", args.out / "overrides.jsonl",
                  args.out)  # fmt: skip
    write_manifest(args.out, stats, args.manifest)
    print(json.dumps(stats))


def write_manifest(out_dir: Path, stats: dict, manifest: Path) -> None:
    """sha256 of the sources and of the set, counts by kind and source, and the licenses."""
    sources, over = _read(out_dir / "sources.jsonl"), _read(out_dir / "overrides.jsonl")
    cases = _read(out_dir / "eval.jsonl")
    data = {
        "sources_sha256": hashlib.sha256((out_dir / "sources.jsonl").read_bytes()).hexdigest(),
        "eval_sha256": hashlib.sha256((out_dir / "eval.jsonl").read_bytes()).hexdigest(),
        "n": len(cases),
        "by_kind": {k: stats[k] for k in ("verbatim", "user", "paraphrase")},
        "by_source": dict(Counter(c["source"] for c in cases)),
        "by_category": dict(Counter(c["category"] for c in cases)),
        "licenses": dict(Counter(f"{r['source_url']}: {r['license']}" for r in sources)),
        "overrides": sum(not r.get("exclude") for r in over),
        "overridden": stats["overridden"],
        "excluded": stats["excluded"],
    }
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
