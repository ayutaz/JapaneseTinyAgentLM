"""Assemble the Action dataset from raw generations (runs locally after the vast.ai job).

Keeps a generated sentence only if it is well formed, consistent with its negation category, and
the cross-model verifier's parse equals the spec label. Adds MASSIVE ja-JP no-action negatives,
removes duplicates and eval/train overlap, splits train/val, evaluates the rule baseline, and
writes a manifest (docs/data.md section 5).
"""

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jtalm.action.schema import canonicalize
from jtalm.data import massive
from jtalm.data.checks import dedup_key, negation_consistent, normalize, well_formed
from jtalm.eval.cases import EvalCase, load_cases, write_cases
from jtalm.eval.metrics import evaluate
from jtalm.eval.rule_baseline import predict_json

VAL_FRACTION = 0.05


def _keep(row: dict) -> tuple[bool, str]:
    if not well_formed(row["text"], row["language"]):
        return False, "malformed"
    if not negation_consistent(row["text"], row["category"], row["language"]):
        return False, "negation_mismatch"
    verified = row.get("verified")
    if not isinstance(verified, list):
        return False, "verify_failed"
    try:
        agree = canonicalize(verified) == canonicalize(row["label"])
    except (AttributeError, TypeError):
        agree = False
    return (True, "kept") if agree else (False, "verifier_disagrees")


def _case(row: dict, split: str) -> EvalCase:
    text = normalize(row["text"])
    digest = hashlib.sha1(f"{split}:{text}".encode()).hexdigest()[:12]
    return EvalCase(
        id=f"{split}-{digest}",
        prompt=text,
        expected=canonicalize(row["label"]),
        category=row["category"],
        language=row["language"],
        pair_id=row.get("pair_id"),
        source=row.get("source", f"synthetic:{row['generator']}"),
    )


def _filter(rows: list[dict], seen: set[str], stats: Counter) -> list[dict]:
    kept = []
    for row in rows:
        ok, reason = _keep(row)
        key = dedup_key(row["text"])
        if ok and key in seen:
            ok, reason = False, "duplicate"
        stats[f"{row['category']}:{reason}"] += 1
        if ok:
            seen.add(key)
            kept.append(row)
    return kept


def _drop_broken_pairs(rows: list[dict]) -> list[dict]:
    by_pair: dict[str, int] = Counter(r["pair_id"] for r in rows if r.get("pair_id"))
    return [
        {**r, "pair_id": r["pair_id"] if by_pair.get(r.get("pair_id") or "", 0) >= 2 else None}
        for r in rows
    ]


def _massive_rows(rows: list[dict], split: str) -> list[dict]:
    return [
        {
            "text": r["utt"],
            "label": [],
            "category": "no_action",
            "language": "ja",
            "source": f"massive:{r['partition']}:{r['id']}",
            "generator": "human (MASSIVE)",
        }
        for r in rows
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(raw_dirs: list[Path], name: str) -> list[dict]:
    rows: list[dict] = []
    for raw_dir in raw_dirs:
        path = raw_dir / name
        if path.exists():
            rows += [json.loads(x) for x in path.open(encoding="utf-8")]
    return rows


def build(raw_dirs: list[Path], out_dir: Path, config: dict, massive_dir: Path) -> dict[str, Any]:
    """Build from one or more generation runs (e.g. the main run plus a negation top-up)."""
    rng = random.Random(config["seed"])
    train_raw = _load(raw_dirs, "train_raw.jsonl")
    eval_raw = _load(raw_dirs, "eval_raw.jsonl")

    stats: dict[str, Counter] = {"train": Counter(), "eval": Counter()}
    train_seen: set[str] = set()
    train_rows = _filter(train_raw, train_seen, stats["train"])
    eval_seen = set(train_seen)  # anything already in train counts as a duplicate (leak)
    eval_rows = _drop_broken_pairs(_filter(eval_raw, eval_seen, stats["eval"]))

    ja = massive.load(massive.download(massive_dir))
    m_cfg = config["massive"]
    train_rows += _massive_rows(massive.sample(ja, "train", m_cfg["train_negatives"], rng), "train")
    eval_rows += _massive_rows(massive.sample(ja, "test", m_cfg["eval_negatives"], rng), "eval")

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for row in train_rows:
        by_cat[row["category"]].append(row)
    train_cases, val_cases = [], []
    for rows in by_cat.values():
        rng.shuffle(rows)
        n_val = max(1, round(len(rows) * VAL_FRACTION))
        val_cases += [_case(r, "val") for r in rows[:n_val]]
        train_cases += [_case(r, "train") for r in rows[n_val:]]
    eval_cases = [_case(r, "eval") for r in eval_rows]

    out_dir.mkdir(parents=True, exist_ok=True)
    files = {"train": train_cases, "val": val_cases, "eval": eval_cases}
    for name, cases in files.items():
        write_cases(out_dir / f"{name}.jsonl", cases)

    baseline = evaluate(eval_cases, {c.id: predict_json(c.prompt) for c in eval_cases})
    counts = {
        name: {
            "total": len(cases),
            "by_category": dict(sorted(Counter(c.category for c in cases).items())),
            "by_language": dict(sorted(Counter(c.language for c in cases).items())),
            "by_source": dict(sorted(Counter(c.source.split(":")[0] for c in cases).items())),
            "contrastive_pairs": len({c.pair_id for c in cases if c.pair_id}),
        }
        for name, cases in files.items()
    }
    return {
        "dataset_version": config["dataset_version"],
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": counts,
        "filter_stats": {k: dict(sorted(v.items())) for k, v in stats.items()},
        "files": {f"{n}.jsonl": _sha256(out_dir / f"{n}.jsonl") for n in files},
        "rule_baseline_on_eval": baseline,
    }


def extend(
    base_dir: Path, raw_dirs: list[Path], out_dir: Path, seed: int, exclude: list[Path] = ()
) -> dict[str, Any]:
    """Add newly generated train sentences to an existing dataset (v0.3 on top of v0).

    The base train / val / eval files are kept as they are, so the evaluation set stays identical
    and results stay comparable. New rows pass the same filters, must not duplicate anything in
    the base (train, val, or eval), and are split into train / val per category.
    """
    rng = random.Random(seed)
    base = {n: load_cases(base_dir / f"{n}.jsonl") for n in ("train", "val", "eval")}
    seen = {dedup_key(c.prompt) for cases in base.values() for c in cases}
    for path in exclude:  # other evaluation sets (human-written, v2 slices) must not leak
        seen |= {dedup_key(c.prompt) for c in load_cases(path)}
    stats: Counter = Counter()
    new_rows = _filter(_load(raw_dirs, "train_raw.jsonl"), seen, stats)

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for row in new_rows:
        by_cat[row["category"]].append(row)
    new_train, new_val = [], []
    for _, rows in sorted(by_cat.items()):
        rng.shuffle(rows)
        n_val = max(1, round(len(rows) * VAL_FRACTION))
        new_val += [_case(r, "val") for r in rows[:n_val]]
        new_train += [_case(r, "train") for r in rows[n_val:]]

    files = {
        "train": base["train"] + new_train,
        "val": base["val"] + new_val,
        "eval": base["eval"],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, cases in files.items():
        write_cases(out_dir / f"{name}.jsonl", cases)

    def counts(cases: list[EvalCase]) -> dict[str, Any]:
        return {
            "total": len(cases),
            "by_category": dict(sorted(Counter(c.category for c in cases).items())),
            "by_source": dict(sorted(Counter(c.source for c in cases).items())),
            "empty_label_share": round(sum(not c.expected for c in cases) / len(cases), 4),
        }

    kept_by_generator = Counter(r["generator"] for r in new_rows)
    raw_by_generator = Counter(r["generator"] for r in _load(raw_dirs, "train_raw.jsonl"))
    return {
        "base": str(base_dir.as_posix()),
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {name: counts(cases) for name, cases in files.items()},
        "added": {"train": len(new_train), "val": len(new_val)},
        "keep_rate_by_generator": {
            g: round(kept_by_generator[g] / n, 4) for g, n in sorted(raw_by_generator.items())
        },
        "filter_stats": dict(sorted(stats.items())),
        "files": {f"{n}.jsonl": _sha256(out_dir / f"{n}.jsonl") for n in files},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw", type=Path, nargs="+", required=True, help="artifacts/raw dirs of vast.ai runs"
    )
    parser.add_argument("--config", type=Path, default=Path("configs/action_v0.json"))
    parser.add_argument(
        "--extra-config", type=Path, nargs="*", default=[], help="configs of top-up runs"
    )
    parser.add_argument("--out", type=Path, default=Path("datasets/action/v0"))
    parser.add_argument("--massive-dir", type=Path, default=Path("datasets/downloads/massive"))
    parser.add_argument("--manifest", type=Path, default=Path("datasets/manifests/action_v0.json"))
    parser.add_argument(
        "--base", type=Path, default=None, help="extend this dataset instead of building anew"
    )
    parser.add_argument(
        "--exclude", type=Path, nargs="*", default=[], help="eval files that must not leak (extend)"
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.base is not None:
        report = extend(args.base, args.raw, args.out, config["seed"], args.exclude)
        report["excluded_against"] = [str(p.as_posix()) for p in args.exclude]
        report["configs"] = {
            str(p.as_posix()): json.loads(p.read_text(encoding="utf-8"))
            for p in [args.config, *args.extra_config]
        }
        report["generation_runs"] = {
            f"{raw.parent.parent.name}/{raw.name}/{s.name}": json.loads(s.read_text("utf-8"))
            for raw in args.raw
            for s in sorted(raw.glob("summary_*.json"))
        }
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(report, ensure_ascii=False, indent=2)
        args.manifest.write_text(text, encoding="utf-8")
        print(json.dumps(report["counts"], ensure_ascii=False, indent=2))
        return
    report = build(args.raw, args.out, config, args.massive_dir)
    generation = {
        f"{raw.parent.parent.name}/{s.name}": json.loads(s.read_text(encoding="utf-8"))
        for raw in args.raw
        for s in sorted(raw.glob("summary_*.json"))
    }
    manifest = {
        **report,
        "config": config,
        "extra_configs": {
            str(p.as_posix()): json.loads(p.read_text(encoding="utf-8")) for p in args.extra_config
        },
        "generation_runs": generation,
        "sources": {
            "synthetic_train": config["train_generator"],
            "synthetic_eval": config["eval_generator"],
            "massive": {"url": massive.MASSIVE_URL, "license": massive.MASSIVE_LICENSE},
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
