# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Paraphrase consistency: do requests that mean the same thing get the same output?

    uv run python -m jtalm.eval.consistency runs/local/suite_v051_3m_q4 [more suites ...] \
        --out results/v051_action/paraphrase_3m.md

Within one evaluation set, cases with the same expected (non-empty) call sequence and language
form a paraphrase group. For every pair of cases in a group, the outputs agree when they are the
same canonical call sequence (right or wrong); outputs that do not parse are compared as text.
Reported per set: groups, cases in groups, pair agreement (agreeing pairs / all pairs, pooled
over groups) and the share of groups whose outputs all agree. Non-requests (expected ``[]``) are
left out: they are not paraphrases of each other. The rule baseline is scored on the same cases
for reference. Input directories are ``jtalm.model.eval_suite`` outputs; with several suites
(e.g. seeds) the rates are mean ± standard deviation over suites.
"""

import argparse
import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jtalm.action.schema import canonicalize, parse_output
from jtalm.eval.bootstrap import load
from jtalm.eval.rule_baseline import predict_json


def _key(raw: str) -> str:
    parsed = parse_output(raw)
    if parsed.calls is None or not all(
        isinstance(c, dict) and isinstance(c.get("arguments", {}), dict) for c in parsed.calls
    ):
        return "invalid:" + raw
    return json.dumps(canonicalize(parsed.calls), ensure_ascii=False, sort_keys=True)


def groups(rows: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    by_expected: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["expected"]:
            exp = json.dumps(canonicalize(r["expected"]), ensure_ascii=False, sort_keys=True)
            by_expected[(r.get("language", "ja"), exp)].append(r)
    return [g for _, g in sorted(by_expected.items()) if len(g) >= 2]


def consistency(rows: list[dict[str, Any]], outputs: dict[str, str]) -> dict[str, Any]:
    """Pair agreement and fully consistent groups for outputs keyed by case id."""
    gs = groups(rows)
    pairs = agree = all_same = 0
    for g in gs:
        counts = Counter(_key(outputs[r["id"]]) for r in g)
        pairs += len(g) * (len(g) - 1) // 2
        agree += sum(c * (c - 1) // 2 for c in counts.values())
        all_same += len(counts) == 1
    return {
        "groups": len(gs),
        "cases": sum(len(g) for g in gs),
        "pairs": pairs,
        "pair_agreement": agree / pairs if pairs else None,
        "groups_all_same": all_same / len(gs) if gs else None,
    }


def _fmt(values: list[float | None]) -> str:
    vals = [v for v in values if v is not None]
    if not vals:
        return "—"
    if len(vals) == 1:
        return f"{100 * vals[0]:.1f}"
    return f"{100 * statistics.mean(vals):.1f} ± {100 * statistics.stdev(vals):.1f}"


def report(suites: list[Path]) -> str:
    loaded = [load(s) for s in suites]
    names = [n for n in loaded[0] if all(n in s for s in loaded)]
    runs = ", ".join(s.name for s in suites)
    lines = [
        f"Paraphrase consistency (definition: jtalm.eval.consistency) for {runs}",
        "",
        "| set | groups | cases | pair agreement | groups all same "
        "| rule baseline: pair agreement | rule baseline: groups all same |",
        "|---|---:|---:|---|---|---|---|",
    ]
    for name in names:
        per_run = [consistency(s[name], {r["id"]: r["output"] for r in s[name]}) for s in loaded]
        if not per_run[0]["groups"]:
            continue
        rows = loaded[0][name]
        rule = consistency(rows, {r["id"]: predict_json(r["prompt"]) for r in rows})
        lines.append(
            f"| {name} | {per_run[0]['groups']} | {per_run[0]['cases']} "
            f"| {_fmt([r['pair_agreement'] for r in per_run])} "
            f"| {_fmt([r['groups_all_same'] for r in per_run])} "
            f"| {_fmt([rule['pair_agreement']])} | {_fmt([rule['groups_all_same']])} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suites", type=Path, nargs="+")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    text = report(args.suites)
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    print(text, end="")


if __name__ == "__main__":
    main()
