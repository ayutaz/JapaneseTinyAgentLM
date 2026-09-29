"""Action LM evaluation metrics (definitions: docs/roadmap.md section 10).

``evaluate`` takes cases and raw model outputs keyed by case id and returns a JSON-serializable
report. Exact match follows TinyLM-Bench's "strict match": the canonicalized call sequence must
equal the expected one, including order.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from jtalm.action.schema import Call, canonicalize, parse_output
from jtalm.eval.cases import EvalCase

OPPOSITE = {"left": "right", "right": "left", "up": "down", "down": "up"}


@dataclass(frozen=True)
class CaseResult:
    id: str
    category: str
    language: str
    json_valid: bool
    schema_valid: bool
    exact: bool
    name_match: bool
    predicted_no_action: bool | None
    slots_correct: int
    slots_total: int
    critical: tuple[str, ...]


def _names(calls: list[Call]) -> list[Any]:
    return [c.get("name") if isinstance(c, dict) else None for c in calls]


def _safe_canonical(calls: list[Any]) -> list[Call] | None:
    if not all(isinstance(c, dict) and isinstance(c.get("arguments", {}), dict) for c in calls):
        return None
    return canonicalize(calls)


def score_case(case: EvalCase, raw: str | None) -> CaseResult:
    parsed = parse_output(raw if raw is not None else "")
    expected = canonicalize(case.expected)
    pred = _safe_canonical(parsed.calls) if parsed.calls is not None else None

    exact = pred is not None and pred == expected
    name_match = pred is not None and _names(pred) == _names(expected)

    slots_total = sum(len(c["arguments"]) for c in expected)
    slots_correct = 0
    if pred is not None:
        for exp_call, pred_call in zip(expected, pred, strict=False):
            if exp_call["name"] != pred_call["name"]:
                continue
            for key, value in exp_call["arguments"].items():
                slots_correct += int(pred_call["arguments"].get(key) == value)

    critical: list[str] = []
    if not parsed.schema_valid:
        critical.append("invalid_output")
    if any(e.startswith("duplicate call") for e in parsed.errors):
        critical.append("duplicate_call")
    if parsed.calls is not None and not expected and parsed.calls:
        critical.append("false_action")
    if pred is not None:
        for exp_call, pred_call in zip(expected, pred, strict=False):
            if exp_call["name"] == pred_call["name"] == "look":
                exp_dir = exp_call["arguments"].get("direction")
                if OPPOSITE.get(exp_dir) == pred_call["arguments"].get("direction"):
                    critical.append("reverse_direction")

    return CaseResult(
        id=case.id,
        category=case.category,
        language=case.language,
        json_valid=parsed.json_valid,
        schema_valid=parsed.schema_valid,
        exact=exact,
        name_match=name_match,
        predicted_no_action=None if parsed.calls is None else len(parsed.calls) == 0,
        slots_correct=slots_correct,
        slots_total=slots_total,
        critical=tuple(critical),
    )


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def _group(results: Iterable[CaseResult], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        groups[getattr(r, key)].append(r)
    return {
        k: {
            "n": len(v),
            "exact": sum(r.exact for r in v),
            "exact_rate": _rate(sum(r.exact for r in v), len(v)),
        }
        for k, v in sorted(groups.items())
    }


def evaluate(cases: list[EvalCase], predictions: Mapping[str, str | None]) -> dict[str, Any]:
    """Score every case. Missing predictions count as invalid output."""
    results = [score_case(c, predictions.get(c.id)) for c in cases]
    n = len(results)

    expected_no_action = {c.id: not c.expected for c in cases}
    tp = sum(1 for r in results if expected_no_action[r.id] and r.predicted_no_action is True)
    fp = sum(1 for r in results if not expected_no_action[r.id] and r.predicted_no_action is True)
    fn = sum(1 for r in results if expected_no_action[r.id] and r.predicted_no_action is not True)

    critical_counts: dict[str, int] = defaultdict(int)
    for r in results:
        for kind in set(r.critical):
            critical_counts[kind] += 1

    pairs: dict[str, list[CaseResult]] = defaultdict(list)
    case_pair = {c.id: c.pair_id for c in cases}
    for r in results:
        if case_pair[r.id]:
            pairs[case_pair[r.id]].append(r)
    complete_pairs = [v for v in pairs.values() if len(v) >= 2]

    return {
        "n": n,
        "json_valid": sum(r.json_valid for r in results),
        "schema_valid": sum(r.schema_valid for r in results),
        "exact": sum(r.exact for r in results),
        "exact_rate": _rate(sum(r.exact for r in results), n),
        "by_category": _group(results, "category"),
        "by_language": _group(results, "language"),
        "name_accuracy": _rate(sum(r.name_match for r in results), n),
        "slot_accuracy": _rate(
            sum(r.slots_correct for r in results), sum(r.slots_total for r in results)
        ),
        "no_action": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": _rate(tp, tp + fp),
            "recall": _rate(tp, tp + fn),
        },
        "critical_error_rate": _rate(sum(bool(r.critical) for r in results), n),
        "critical_counts": dict(sorted(critical_counts.items())),
        "contrastive_pairs": len(complete_pairs),
        "contrastive_pair_accuracy": _rate(
            sum(all(r.exact for r in v) for v in complete_pairs), len(complete_pairs)
        ),
    }
