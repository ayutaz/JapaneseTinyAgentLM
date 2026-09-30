"""Error bars for evaluation results: bootstrap confidence intervals and seed spread.

    # one model: 95% intervals per evaluation set
    uv run python -m jtalm.eval.bootstrap ci runs/local/suite_v051_3m_q4
    # two models on the same cases: paired bootstrap of the difference (B - A)
    uv run python -m jtalm.eval.bootstrap diff runs/local/suite_v05_3m_q4 \
        runs/local/suite_v051_3m_q4
    # several seeds: mean and standard deviation across runs
    uv run python -m jtalm.eval.bootstrap seeds runs/local/suite_v051_3m_q4 runs/local/suite_...

Input directories are ``jtalm.model.eval_suite`` outputs (``*_predictions.jsonl`` with ``exact``,
``expected`` and ``output`` per case). Cases are resampled with replacement (percentile interval).
The interval covers evaluation-set sampling only; seed spread is a separate source of variance.
"""

import argparse
import json
import random
import statistics
from pathlib import Path
from typing import Any

METRICS = ("exact", "requests_exact", "false_action_rate")


def load(suite_dir: Path) -> dict[str, list[dict[str, Any]]]:
    sets = {}
    for path in sorted(suite_dir.glob("*_predictions.jsonl")):
        name = path.name.removesuffix("_predictions.jsonl")
        sets[name] = [json.loads(x) for x in path.open(encoding="utf-8")]
    return sets


def metric_values(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    """Per-case 0/1 values for each metric (a case contributes only to the metrics it defines)."""
    out: dict[str, list[float]] = {m: [] for m in METRICS}
    for r in rows:
        out["exact"].append(float(r["exact"]))
        if r["expected"]:
            out["requests_exact"].append(float(r["exact"]))
        else:
            out["false_action_rate"].append(float(r["output"] != "[]"))
    return out


def ci(values: list[float], rng: random.Random, n_boot: int) -> tuple[float, float, float] | None:
    if not values:
        return None
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(n_boot))
    return sum(values) / n, means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def paired_diff(
    a: list[dict[str, Any]], b: list[dict[str, Any]], metric: str, rng: random.Random, n_boot: int
) -> tuple[float, float, float, float] | None:
    """Mean difference B - A over the same cases, its 95% interval, and P(B > A)."""
    by_id = {r["id"]: r for r in a}
    pairs = []
    for rb in b:
        ra = by_id.get(rb["id"])
        if ra is None:
            continue
        va, vb = metric_values([ra])[metric], metric_values([rb])[metric]
        if va and vb:
            pairs.append(vb[0] - va[0])
    if not pairs:
        return None
    n = len(pairs)
    diffs = sorted(sum(rng.choices(pairs, k=n)) / n for _ in range(n_boot))
    p_better = sum(d > 0 for d in diffs) / n_boot
    return sum(pairs) / n, diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot) - 1], p_better


def _pct(v: float) -> str:
    return f"{100 * v:.1f}"


def cmd_ci(suite: Path, n_boot: int, seed: int) -> str:
    rng = random.Random(seed)
    lines = [
        f"95% bootstrap intervals ({n_boot} resamples) for {suite.name}",
        "",
        "| set | exact | requests exact | false actions |",
        "|---|---|---|---|",
    ]
    for name, rows in load(suite).items():
        vals = metric_values(rows)
        cells = []
        for m in METRICS:
            r = ci(vals[m], rng, n_boot)
            cells.append("—" if r is None else f"{_pct(r[0])} [{_pct(r[1])}, {_pct(r[2])}]")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def cmd_diff(a: Path, b: Path, n_boot: int, seed: int) -> str:
    rng = random.Random(seed)
    sa, sb = load(a), load(b)
    lines = [
        f"Paired bootstrap, B - A (A = {a.name}, B = {b.name}); P = probability that B is higher",
        "",
        "| set | exact | requests exact | false actions |",
        "|---|---|---|---|",
    ]
    for name in sb:
        if name not in sa:
            continue
        cells = []
        for m in METRICS:
            r = paired_diff(sa[name], sb[name], m, rng, n_boot)
            cells.append(
                "—" if r is None
                else f"{100 * r[0]:+.1f} [{100 * r[1]:+.1f}, {100 * r[2]:+.1f}] P={r[3]:.2f}"
            )  # fmt: skip
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def cmd_seeds(suites: list[Path]) -> str:
    loaded = [load(s) for s in suites]
    names = [n for n in loaded[0] if all(n in s for s in loaded)]
    lines = [
        f"Mean ± standard deviation over {len(suites)} runs: " + ", ".join(s.name for s in suites),
        "",
        "| set | exact | requests exact | false actions |",
        "|---|---|---|---|",
    ]
    for name in names:
        cells = []
        for m in METRICS:
            per_run = [metric_values(s[name])[m] for s in loaded]
            if not per_run[0]:
                cells.append("—")
                continue
            means = [sum(v) / len(v) for v in per_run]
            sd = statistics.stdev(means) if len(means) > 1 else 0.0
            cells.append(f"{_pct(statistics.mean(means))} ± {_pct(sd)}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("ci", "diff", "seeds"):
        p = sub.add_parser(name)
        p.add_argument("suites", type=Path, nargs="+")
        p.add_argument("--n-boot", type=int, default=2000)
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.cmd == "ci":
        text = "\n".join(cmd_ci(s, args.n_boot, args.seed) for s in args.suites)
    elif args.cmd == "diff":
        if len(args.suites) != 2:
            raise SystemExit("diff takes exactly two suite directories (A B)")
        text = cmd_diff(args.suites[0], args.suites[1], args.n_boot, args.seed)
    else:
        text = cmd_seeds(args.suites)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
