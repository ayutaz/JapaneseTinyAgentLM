"""Evaluate one checkpoint on every evaluation set at once and print one table.

    uv run --group train python -m jtalm.model.eval_suite --ckpt <best_q4_g64.pt> \
        --tokenizer tokenizer/out/action_v0_sp2048.model --out runs/local/suite_v04

Sets: the v0 evaluation set (LLM-written), the human-written set (human v1), and every slice
file of evaluation set v2. Decoding uses the grammar and the confidence gate; the gate threshold
is chosen once on ``--val`` (never on an evaluation set), as in jtalm.model.evaluate.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jtalm.eval.cases import load_cases
from jtalm.eval.metrics import evaluate
from jtalm.infra.env import PROJECT_ROOT
from jtalm.model.data import Codec
from jtalm.model.evaluate import load_model, predict, select_gate
from jtalm.model.grammar import ActionGrammar
from jtalm.model.train import pick_device

DEFAULT_SETS = {
    "v0 eval (LLM)": "datasets/action/v0/eval.jsonl",
    "human v1": "datasets/action/human_v1/eval.jsonl",
}
EV2_DIR = "datasets/action/eval_v2"


def row(report: dict[str, Any]) -> dict[str, Any]:
    cats = report["by_category"]
    n_empty = sum(v["n"] for k, v in cats.items() if k in ("no_action", "negation"))
    n_pos = report["n"] - n_empty
    pos_exact = sum(v["exact"] for k, v in cats.items() if k not in ("no_action", "negation"))
    false_actions = report["critical_counts"].get("false_action", 0)
    return {
        "n": report["n"],
        "exact": report["exact_rate"],
        "requests_exact": pos_exact / n_pos if n_pos else None,
        "false_action_rate": false_actions / n_empty if n_empty else None,
        "critical_error_rate": report["critical_error_rate"],
    }


def _pct(v: Any) -> str:
    return "—" if v is None else f"{100 * v:.1f}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--val", type=Path, default=PROJECT_ROOT / "datasets/action/v0.4/val.jsonl")
    parser.add_argument("--gate", type=float, default=None, help="fixed threshold (skip val)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    device = pick_device(args.device)
    codec = Codec(args.tokenizer)
    grammar = ActionGrammar(codec)
    model, state = load_model(args.ckpt, device)
    if state["tokenizer_sha256"] != codec.sha256:
        raise SystemExit("tokenizer sha256 mismatch")
    gate_info: dict[str, Any] = {"threshold": args.gate}
    if args.gate is None:
        val = load_cases(args.val)
        gate_info = select_gate(predict(model, codec, val, grammar), val)

    sets = {k: PROJECT_ROOT / v for k, v in DEFAULT_SETS.items()}
    for path in sorted((PROJECT_ROOT / EV2_DIR).glob("*.jsonl")):
        sets[f"v2/{path.stem}"] = path
    args.out.mkdir(parents=True, exist_ok=True)
    table: dict[str, Any] = {}
    for name, path in sets.items():
        if not path.exists():
            continue
        cases = load_cases(path)
        rows = predict(model, codec, cases, grammar, gate_info["threshold"])
        report = evaluate(cases, {r["id"]: r["output"] for r in rows})
        slug = name.replace("/", "_").replace(" ", "_").replace("(", "").replace(")", "")
        with (args.out / f"{slug}_predictions.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        table[name] = row(report)
    result = {"ckpt": str(args.ckpt), "gate": gate_info, "sets": table}
    (args.out / "suite.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        f"gate threshold {gate_info['threshold']}",
        "",
        "| set | n | exact | requests exact | false actions | critical |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, r in table.items():
        lines.append(
            f"| {name} | {r['n']} | {_pct(r['exact'])} | {_pct(r['requests_exact'])} | "
            f"{_pct(r['false_action_rate'])} | {_pct(r['critical_error_rate'])} |"
        )
    md = "\n".join(lines) + "\n"
    (args.out / "suite.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
