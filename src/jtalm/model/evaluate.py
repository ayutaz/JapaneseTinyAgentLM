"""Evaluate Action LM checkpoints and compare them with the rule baseline and existing models.

    uv run --group train python -m jtalm.model.evaluate \
        --ckpt runs/m4/3m/best.pt runs/m4/5m/best.pt \
        --tokenizer tokenizer/out/action_v0_sp2048.model \
        --out runs/m4/eval

Decoding is greedy with the fixed prompt format of ``jtalm.model.format`` (no grammar, no gate).
Existing models are compared on the 16 TinyLM-Bench cases, whose outputs are in the fixtures.
"""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch

from jtalm.eval.cases import EvalCase, load_cases
from jtalm.eval.metrics import evaluate, score_case
from jtalm.eval.rule_baseline import predict_json
from jtalm.infra.env import PROJECT_ROOT
from jtalm.model.data import Codec
from jtalm.model.decode import greedy
from jtalm.model.train import pick_device
from jtalm.model.transformer import ActionLM, ModelConfig, count_params

BENCH_DIR = PROJECT_ROOT / "tests/fixtures/tinylm_bench"
CATEGORIES = ("single", "multi_action", "negation", "no_action", "correction")


def load_model(ckpt: Path, device: torch.device) -> tuple[ActionLM, dict[str, Any]]:
    state = torch.load(ckpt, map_location="cpu", weights_only=False)
    model = ActionLM(ModelConfig(**state["config"]))
    model.load_state_dict(state["state_dict"])
    return model.to(device).eval(), state


def predict(model: ActionLM, codec: Codec, cases: list[EvalCase]) -> list[dict[str, Any]]:
    preds = greedy(model, codec, [c.prompt for c in cases])
    rows = []
    for c, p in zip(cases, preds, strict=True):
        rows.append(
            {
                "id": c.id,
                "category": c.category,
                "language": c.language,
                "prompt": c.prompt,
                "expected": c.expected,
                "output": p.text,
                "min_prob": round(p.min_prob, 5),
                "exact": score_case(c, p.text).exact,
            }
        )
    return rows


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    """The comparison row: overall and per-category exact, no-action, critical errors, pairs."""
    return {
        "exact_rate": report["exact_rate"],
        **{c: report["by_category"].get(c, {}).get("exact_rate") for c in CATEGORIES},
        "en": report["by_language"].get("en", {}).get("exact_rate"),
        "no_action_precision": report["no_action"]["precision"],
        "no_action_recall": report["no_action"]["recall"],
        "critical_error_rate": report["critical_error_rate"],
        "pair_accuracy": report["contrastive_pair_accuracy"],
    }


def _fmt(v: Any) -> str:
    return "—" if v is None else f"{100 * v:.1f}"


def markdown(rows: dict[str, dict[str, Any]], keys: list[str]) -> str:
    head = "| model | " + " | ".join(keys) + " |"
    sep = "|---|" + "---:|" * len(keys)
    body = [
        f"| {name} | " + " | ".join(_fmt(r.get(k)) for k in keys) + " |" for name, r in rows.items()
    ]
    return "\n".join([head, sep, *body])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ckpt", type=Path, nargs="+", required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument(
        "--cases", type=Path, default=PROJECT_ROOT / "datasets/action/v0/eval.jsonl"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args(argv)

    device = pick_device(args.device)
    codec = Codec(args.tokenizer)
    cases = load_cases(args.cases)
    bench = load_cases(BENCH_DIR / "action_cases.json")
    args.out.mkdir(parents=True, exist_ok=True)

    eval_rows: dict[str, dict[str, Any]] = {}
    bench_rows: dict[str, dict[str, Any]] = {}
    eval_rows["rule baseline"] = summarize(
        evaluate(cases, {c.id: predict_json(c.prompt) for c in cases})
    )
    bench_rows["rule baseline"] = summarize(
        evaluate(bench, {c.id: predict_json(c.prompt) for c in bench})
    )
    outputs = json.loads((BENCH_DIR / "action_outputs.json").read_text(encoding="utf-8"))
    by_model: dict[str, dict[str, str]] = defaultdict(dict)
    for row in outputs:
        by_model[row["model"]][row["id"]] = row["actual_json"]
    for name, preds in by_model.items():
        bench_rows[name] = summarize(evaluate(bench, preds))

    models: dict[str, Any] = {}
    for ckpt in args.ckpt:
        model, state = load_model(ckpt, device)
        if state["tokenizer_sha256"] != codec.sha256:
            raise SystemExit(f"{ckpt}: tokenizer sha256 does not match {args.tokenizer}")
        slug = ckpt.parent.name
        name = f"{slug} ({count_params(model) / 1e6:.2f}M)"
        for label, cs, table in (("eval", cases, eval_rows), ("bench", bench, bench_rows)):
            rows = predict(model, codec, cs)
            report = evaluate(cs, {r["id"]: r["output"] for r in rows})
            with (args.out / f"{slug}_{label}_predictions.jsonl").open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            (args.out / f"{slug}_{label}_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            table[name] = summarize(report)
        models[name] = {"ckpt": str(ckpt), "epoch": state.get("epoch"), "step": state.get("step")}

    keys = ["exact_rate", *CATEGORIES, "en", "no_action_precision", "no_action_recall",
            "critical_error_rate", "pair_accuracy"]  # fmt: skip
    result = {
        "conditions": {
            "decoding": "greedy, no grammar, no confidence gate",
            "prompt_format": "<s> <act> prompt <out>",
            "eval_cases": str(args.cases.name),
            "eval_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
            "tokenizer_sha256": codec.sha256,
            "device": str(device),
        },
        "models": models,
        "eval": eval_rows,
        "bench16": bench_rows,
    }
    (args.out / "comparison.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = (
        f"## Evaluation set ({len(cases)} cases, exact match %)\n\n{markdown(eval_rows, keys)}\n\n"
        f"## TinyLM-Bench 16 cases (exact match %)\n\n"
        f"{markdown(bench_rows, ['exact_rate', 'no_action_precision', 'critical_error_rate'])}\n"
    )
    (args.out / "comparison.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
