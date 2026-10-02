# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jtalm.eval.cases import EvalCase, load_cases
from jtalm.eval.metrics import evaluate
from jtalm.infra.env import PROJECT_ROOT
from jtalm.model.data import Codec
from jtalm.model.evaluate import load_model, predict, select_gate
from jtalm.model.grammar import ActionGrammar
from jtalm.model.train import pick_device
from jtalm.model.transformer import set_kv_int8

DEFAULT_SETS = {
    "Stack-chan v1": "datasets/action/stackchan_v1/eval.jsonl",
    "eval v3 (LLM)": "datasets/action/eval_v3/eval.jsonl",
    "v0 eval (LLM)": "datasets/action/relabel_v1/v0_eval.jsonl",
    "human v1": "datasets/action/relabel_v1/human_v1.jsonl",
}
EV2_DIR = "datasets/action/relabel_v1"  # eval_v2_<slice>.jsonl, relabeled under schema v1
STACKCHAN_SET = "Stack-chan v1"
NUMERIC_ARGS = ("degrees", "level", "by")


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
        "false_actions": false_actions,
        "n_empty": n_empty,
        "false_action_rate": false_actions / n_empty if n_empty else None,
        "critical_error_rate": report["critical_error_rate"],
    }


def _has_numeric(case: EvalCase) -> bool:
    return any(any(k in (c.get("arguments") or {}) for k in NUMERIC_ARGS) for c in case.expected)


def numeric_gated_rate(
    cases: list[EvalCase], raw_rows: list[dict[str, Any]], gated_rows: list[dict[str, Any]]
) -> float | None:
    """Share of numeric-argument cases that the gate turned into ``[]``.

    Counts a case when its expected calls carry degrees/level/by, the un-gated output is not
    ``[]`` and the gated output is ``[]``. None when no case has a numeric expected call.
    """
    raw = {r["id"]: r["output"] for r in raw_rows}
    gated = {r["id"]: r["output"] for r in gated_rows}
    numeric = [c for c in cases if _has_numeric(c)]
    if not numeric:
        return None
    hit = sum(1 for c in numeric if raw[c.id].strip() != "[]" and gated[c.id].strip() == "[]")
    return hit / len(numeric)


def source_kind(source: str | None) -> str:
    """verbatim / user / paraphrase from ``EvalCase.source`` (anything else is ``other``)."""
    if source is None:
        return "other"
    for kind in ("verbatim", "paraphrase"):
        if source.startswith(f"{kind}:"):
            return kind
    return "user" if source.startswith("user") else "other"


def _group_exact(groups: dict[str, list[bool]]) -> dict[str, dict[str, Any]]:
    return {k: {"n": len(v), "exact": sum(v) / len(v)} for k, v in groups.items() if v}


def stackchan_breakdown(cases: list[EvalCase], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Exact-match rate by source kind and by tool family (look / turn)."""
    exact = {r["id"]: bool(r["exact"]) for r in rows}
    by_source: dict[str, list[bool]] = {"user": [], "verbatim": [], "paraphrase": []}
    by_tool: dict[str, list[bool]] = {"look": [], "turn": []}
    for c in cases:
        by_source.setdefault(source_kind(c.source), []).append(exact[c.id])
        for tool in by_tool:
            if any(call.get("name") == tool for call in c.expected):
                by_tool[tool].append(exact[c.id])
    return {"by_source": _group_exact(by_source), "by_tool": _group_exact(by_tool)}


def _pct(v: Any) -> str:
    return "—" if v is None else f"{100 * v:.1f}"


def suite_sets() -> dict[str, Path]:
    """Display name -> case file for every evaluation set that exists."""
    sets = {k: PROJECT_ROOT / v for k, v in DEFAULT_SETS.items()}
    for path in sorted((PROJECT_ROOT / EV2_DIR).glob("eval_v2_*.jsonl")):
        sets[f"v2/{path.stem.removeprefix('eval_v2_')}"] = path
    for name, path in sets.items():
        if not path.exists():
            print(f"warning: evaluation set '{name}' not found, skipped: {path}", file=sys.stderr)
    return {k: v for k, v in sets.items() if v.exists()}


def write_suite(
    out: Path,
    predict_set: Callable[[list[EvalCase], bool], list[dict[str, Any]]],
    gate_info: dict[str, Any],
    meta: dict[str, Any],
) -> str:
    """Run ``predict_set(cases, gated)`` on every set; write predictions and suite.json/.md."""
    out.mkdir(parents=True, exist_ok=True)
    table: dict[str, Any] = {}
    for name, path in suite_sets().items():
        cases = load_cases(path)
        rows = predict_set(cases, True)
        raw_rows = predict_set(cases, False)
        report = evaluate(cases, {r["id"]: r["output"] for r in rows})
        slug = name.replace("/", "_").replace(" ", "_").replace("(", "").replace(")", "")
        with (out / f"{slug}_predictions.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        table[name] = row(report)
        table[name]["numeric_gated_rate"] = numeric_gated_rate(cases, raw_rows, rows)
        if name == STACKCHAN_SET:
            table[name].update(stackchan_breakdown(cases, rows))
    result = {**meta, "gate": gate_info, "sets": table}
    (out / "suite.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        f"gate threshold {gate_info['threshold']}",
        "",
        "| set | n | exact | requests exact | false action rate | false actions | critical "
        "| numeric gated |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, r in table.items():
        lines.append(
            f"| {name} | {r['n']} | {_pct(r['exact'])} | {_pct(r['requests_exact'])} | "
            f"{_pct(r['false_action_rate'])} | {r['false_actions']}/{r['n_empty']} | "
            f"{_pct(r['critical_error_rate'])} | {_pct(r['numeric_gated_rate'])} |"
        )
    for name, r in table.items():
        for key, label in (("by_source", "source"), ("by_tool", "tool")):
            for k, v in r.get(key, {}).items():
                lines.append(f"\n{name} {label}={k}: n={v['n']} exact={_pct(v['exact'])}")
    md = "\n".join(lines) + "\n"
    (out / "suite.md").write_text(md, encoding="utf-8")
    return md


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--val", type=Path, default=PROJECT_ROOT / "datasets/action/v1.0/val.jsonl")
    parser.add_argument("--gate", type=float, default=None, help="fixed threshold (skip val)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--kv-int8", action="store_true", help="INT8 KV cache (C runtime with JTLM_KV_INT8)"
    )
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    device = pick_device(args.device)
    codec = Codec(args.tokenizer)
    grammar = ActionGrammar(codec)
    model, state = load_model(args.ckpt, device)
    if state["tokenizer_sha256"] != codec.sha256:
        raise SystemExit("tokenizer sha256 mismatch")
    set_kv_int8(model, args.kv_int8)
    gate_info: dict[str, Any] = {"threshold": args.gate}
    if args.gate is None:
        val = load_cases(args.val)
        gate_info = select_gate(predict(model, codec, val, grammar), val)

    md = write_suite(
        args.out,
        lambda cases, gated: predict(
            model, codec, cases, grammar, gate_info["threshold"] if gated else None
        ),
        gate_info,
        {"ckpt": str(args.ckpt), "kv_int8": args.kv_int8},
    )
    print(md)


if __name__ == "__main__":
    main()
