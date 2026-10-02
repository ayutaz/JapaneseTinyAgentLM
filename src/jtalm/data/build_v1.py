# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Assemble data v1.0, evaluation set v3, and the v1 labels of the older evaluation sets.

    uv run python -m jtalm.data.build_v1 --raw artifacts/gen_action_v1

1. Inherited rows (data v0.5.1 train/val, re-parsed by Qwen3 under schema v1, ``reverify``):
   kept with their label when Qwen3 agrees; relabeled when Qwen3's answer needs schema v1
   (degrees, turn, a new tool...) and the prompt has a word for every v1-only element of that
   answer (checks.v1_evidence); dropped otherwise.
2. New sentences of the v1 writers: kept when Qwen3's parse equals the spec label (as in v0).
3. Evaluation set v3 (llm-jp writes, Qwen3 verifies): same rule as 2.
4. v0 eval, human v1 and eval v2: relabeled by rule 1 into datasets/action/relabel_v1/, with a
   list of every change for the user's review (changes.md).
Duplicates and any overlap with an evaluation set are removed from the training data.
"""

import argparse
import hashlib
import json
import random
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from jtalm.action.schema import canonicalize, to_json, uses_v1_only, validate
from jtalm.data.build import _case, _filter, _load
from jtalm.data.checks import dedup_key, v1_evidence
from jtalm.eval.cases import EvalCase, load_cases, write_cases

VAL_FRACTION = 0.05
V1_WRITER_NAMES = ("qwen", "abeja", "calm3", "elyza", "nemoja")  # configs/action_v1_<name>.json
INHERITED = ("datasets/action/v0.5.1/train.jsonl", "datasets/action/v0.5.1/val.jsonl")
OLD_EVAL = {
    "v0_eval": "datasets/action/v0/eval.jsonl",
    "human_v1": "datasets/action/human_v1/eval.jsonl",
    **{
        f"eval_v2_{p.stem}": p.as_posix()
        for p in sorted(Path("datasets/action/eval_v2").glob("*.jsonl"))
    },
}


def _category(expected: list, old: str) -> str:
    """Single vs multi_action follows the call count; correction keeps its category."""
    if expected and old in ("single", "multi_action", "no_action", "negation"):
        return "single" if len(expected) == 1 else "multi_action"
    return old


def relabel(rows: list[dict]) -> tuple[list[EvalCase], list[dict], Counter]:
    cases, changed, dropped = [], [], Counter()
    for r in rows:
        verified = r.get("verified")
        if not isinstance(verified, list):
            dropped["verify_failed"] += 1
            continue
        try:
            old, new = canonicalize(r["expected"]), canonicalize(verified)
            if validate(new):
                dropped["verified_invalid"] += 1
                continue
            v1_only = uses_v1_only(new)
        except (AttributeError, TypeError, KeyError, ValueError):
            dropped["verify_failed"] += 1
            continue
        source = r.get("source") or ""
        if new != old:
            if not v1_only:
                dropped["verifier_disagrees_v0"] += 1
                continue
            if v1_evidence(r["text"], new):  # R15: the verifier is noisy with 11 tools
                dropped["relabel_no_evidence"] += 1
                continue
            changed.append({**r, "old": old, "new": new})
            source += "+relabel:v1"
        cases.append(
            EvalCase(
                id=r["id"],
                prompt=r["text"],
                expected=new,
                category=_category(new, r["category"]),
                language=r.get("language", "ja"),
                source=source,
            )
        )
    return cases, changed, dropped


def _read_overrides(path: Path) -> dict[str, list]:
    if not path.exists():
        return {}
    out: dict[str, list] = {}
    for line in path.read_text("utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            expected = canonicalize(o["expected"])
            if errors := validate(expected):
                raise ValueError(f"override {o['id']!r} is not a valid label: {errors}")
            out[o["id"]] = expected
    return out


def relabel_old_eval(
    rev: dict[str, list[dict]], old_eval: dict[str, str], relabel_out: Path, stats: dict
) -> set[str]:
    """Write relabel_v1/<set>.jsonl and changes.md, apply overrides.jsonl; return dedup keys."""
    overrides = _read_overrides(relabel_out / "overrides.jsonl")
    sets: dict[str, list[EvalCase]] = {}
    review = ["| set | id | 入力 | v0 の正解 | v1 の正解 |", "|---|---|---|---|---|"]
    over_review = ["| set | id | 入力 | v1 検証役の正解 | 上書き後 |", "|---|---|---|---|---|"]
    matched: set[str] = set()
    for name, path in old_eval.items():
        cases, changed, dropped = relabel(rev.get(path, []))
        originals = {c.id: c for c in load_cases(path)}
        # keep fields relabel does not rebuild (pair_id, ...) from the original case
        cases = [
            replace(
                c,
                pair_id=originals[c.id].pair_id if c.id in originals else c.pair_id,
                source=c.source or (originals[c.id].source if c.id in originals else None),
            )
            for c in cases
        ]
        kept_ids = {c.id for c in cases}
        # keep the v0 label of rows whose v1 parse was dropped: they stay comparable with v0
        cases += [c for i, c in originals.items() if i not in kept_ids]
        n_over = 0
        for i, c in enumerate(cases):
            if c.id in overrides:
                over_review.append(
                    f"| {name} | {c.id} | {c.prompt} | `{to_json(c.expected)}` "
                    f"| `{to_json(overrides[c.id])}` |"
                )
                cases[i] = replace(
                    c, expected=overrides[c.id], category=_category(overrides[c.id], c.category)
                )
                matched.add(c.id)
                n_over += 1
        sets[name] = cases
        review += [
            f"| {name} | {r['id']} | {r['text']} | `{to_json(r['old'])}` | `{to_json(r['new'])}` |"
            for r in changed
        ]
        stats[f"relabel_{name}"] = {
            "n": len(cases),
            "reverify_rows": len(rev.get(path, [])),
            "changed": len(changed),
            "overridden": n_over,
            **dropped,
        }
    if unknown := sorted(set(overrides) - matched):
        raise ValueError(f"overrides.jsonl ids match no case in any relabeled set: {unknown}")
    relabel_out.mkdir(parents=True, exist_ok=True)
    eval_keys: set[str] = set()
    for name, cases in sets.items():
        write_cases(relabel_out / f"{name}.jsonl", cases)
        eval_keys |= {dedup_key(c.prompt) for c in cases}
    lines = review
    if len(over_review) > 2:
        lines = [*review, "", "## 上書き（overrides.jsonl）", "", *over_review]
    (relabel_out / "changes.md").write_text("\n".join(lines) + "\n", "utf-8")
    return eval_keys


def _by_file(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(Path(r["file"]).as_posix(), []).append(r)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("datasets/action/v1.0"))
    p.add_argument("--eval-out", type=Path, default=Path("datasets/action/eval_v3"))
    p.add_argument("--relabel-out", type=Path, default=Path("datasets/action/relabel_v1"))
    p.add_argument("--manifest", type=Path, default=Path("datasets/manifests/action_v1.0.json"))
    p.add_argument("--seed", type=int, default=20261002)
    args = p.parse_args()

    rev = _by_file(
        [
            json.loads(x)
            for x in (args.raw / "reverify1/reverify_raw.jsonl").read_text("utf-8").splitlines()
            if x
        ]
    )
    stats: dict = {"created": datetime.now(UTC).isoformat(timespec="seconds")}
    for path in INHERITED:
        if not rev.get(path):
            raise ValueError(f"no reverify rows for {path} (path mismatch with --input?)")

    # 4. older evaluation sets (labels for the v1 evaluation; the user reviews changes.md)
    eval_keys = relabel_old_eval(rev, OLD_EVAL, args.relabel_out, stats)

    # 3. evaluation set v3
    seen_eval: set[str] = set()
    ev_stats: Counter = Counter()
    ev_rows = _filter(
        _load(sorted(args.raw.glob("raw1_eval")), "eval_raw.jsonl"), seen_eval, ev_stats
    )
    ev3 = [_case(r, "ev3") for r in ev_rows]
    args.eval_out.mkdir(parents=True, exist_ok=True)
    write_cases(args.eval_out / "eval.jsonl", ev3)
    stats["eval_v3"] = {"n": len(ev3), **ev_stats}
    sc = Path("datasets/action/stackchan_v1/eval.jsonl")
    eval_keys |= {dedup_key(c.prompt) for c in ev3}
    stats["stackchan_eval_included"] = sc.exists()
    if sc.exists():
        eval_keys |= {dedup_key(c.prompt) for c in load_cases(sc)}

    # 1. inherited train/val and 2. new sentences
    train, val = [], []
    seen: set[str] = set(eval_keys)
    for path, split in zip(INHERITED, (train, val), strict=True):
        cases, changed, dropped = relabel(rev.get(path, []))
        kept = [c for c in cases if dedup_key(c.prompt) not in seen]
        seen |= {dedup_key(c.prompt) for c in kept}
        split.extend(kept)
        stats[f"inherited_{Path(path).stem}"] = {
            "n": len(kept),
            "reverify_rows": len(rev[path]),
            "relabeled": len(changed),
            "overlap_or_dup": len(cases) - len(kept),
            **dropped,
        }
    new_stats: Counter = Counter()
    writer_dirs = [
        args.raw / f"raw1_{w}" for w in V1_WRITER_NAMES if (args.raw / f"raw1_{w}").is_dir()
    ]
    new_rows = _filter(_load(writer_dirs, "train_raw.jsonl"), seen, new_stats)
    rng = random.Random(args.seed)
    rng.shuffle(new_rows)
    n_val = round(len(new_rows) * VAL_FRACTION)
    val += [_case(r, "val") for r in new_rows[:n_val]]
    train += [_case(r, "train") for r in new_rows[n_val:]]
    stats["new"] = {"n": len(new_rows), **new_stats}

    args.out.mkdir(parents=True, exist_ok=True)
    write_cases(args.out / "train.jsonl", train)
    write_cases(args.out / "val.jsonl", val)
    for name, cases in (("train", train), ("val", val)):
        stats[name] = {
            "n": len(cases),
            "by_category": dict(Counter(c.category for c in cases)),
            "sha256": hashlib.sha256((args.out / f"{name}.jsonl").read_bytes()).hexdigest(),
        }
    args.manifest.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(
        json.dumps(
            {k: v for k, v in stats.items() if k in ("train", "val", "new", "eval_v3")},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
