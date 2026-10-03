# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json
from collections import defaultdict
from pathlib import Path

import pytest

from jtalm.eval import EvalCase, evaluate, load_cases, score_case

BENCH = Path(__file__).parent / "fixtures" / "tinylm_bench"


def look(direction: str, amount: str = "normal") -> dict:
    return {"name": "look", "arguments": {"direction": direction, "amount": amount}}


def case(case_id: str, expected: list, category: str = "single", pair_id: str | None = None):
    return EvalCase(id=case_id, prompt="p", expected=expected, category=category, pair_id=pair_id)


def test_perfect_predictions_score_100_percent() -> None:
    cases = load_cases(BENCH / "action_cases.json")
    report = evaluate(cases, {c.id: json.dumps(c.expected) for c in cases})
    assert report["exact"] == report["schema_valid"] == report["json_valid"] == 16
    assert report["name_accuracy"] == report["slot_accuracy"] == 1.0
    assert report["no_action"]["precision"] == report["no_action"]["recall"] == 1.0
    assert report["critical_error_rate"] == 0.0
    assert report["by_category"]["negation"]["n"] == 2


@pytest.mark.parametrize(
    ("model", "expected_exact"),
    [("Needle 2 official", 3), ("FunctionGemma 270M", 6), ("MimiModel C", 1)],
)
def test_reproduces_tinylm_bench_strict_match(model: str, expected_exact: int) -> None:
    cases = load_cases(BENCH / "action_cases.json")
    outputs = json.loads((BENCH / "action_outputs.json").read_text(encoding="utf-8"))
    by_model: dict[str, dict[str, str]] = defaultdict(dict)
    for row in outputs:
        by_model[row["model"]][row["id"]] = row["actual_json"]
    report = evaluate(cases, by_model[model])
    assert report["exact"] == expected_exact
    # Every model failed multi-action and negation in the benchmark.
    assert report["by_category"]["multi_action"]["exact"] == 0
    assert report["by_category"]["negation"]["exact"] == 0


def test_false_action_and_reverse_direction_are_critical() -> None:
    no_action = score_case(case("a", [], "negation"), json.dumps([look("left")]))
    assert "false_action" in no_action.critical and not no_action.exact
    reverse = score_case(case("b", [look("left")]), json.dumps([look("right")]))
    assert "reverse_direction" in reverse.critical
    assert reverse.name_match and reverse.slots_correct == 1 and reverse.slots_total == 2


def test_invalid_and_missing_outputs() -> None:
    cases = [case("a", [look("right")]), case("b", [])]
    report = evaluate(cases, {"a": "右を向きます"})
    assert report["json_valid"] == 0
    assert report["critical_counts"]["invalid_output"] == 2
    assert report["no_action"]["fn"] == 1


def test_order_matters_for_exact_match() -> None:
    expected = [{"name": "set_expression", "arguments": {"expression": "happy"}}, look("left")]
    result = score_case(case("a", expected, "multi_action"), json.dumps(expected[::-1]))
    assert not result.exact and not result.name_match


def test_contrastive_pair_needs_both_cases_correct() -> None:
    cases = [
        case("pos", [look("right")], "single", pair_id="p1"),
        case("neg", [], "negation", pair_id="p1"),
    ]
    both = evaluate(cases, {"pos": json.dumps([look("right")]), "neg": "[]"})
    one = evaluate(cases, {"pos": json.dumps([look("right")]), "neg": json.dumps([look("right")])})
    assert both["contrastive_pair_accuracy"] == 1.0
    assert one["contrastive_pair_accuracy"] == 0.0


def test_v1_reverse_direction_and_numeric_error() -> None:
    case = EvalCase(
        id="a",
        prompt="p",
        category="single",
        expected=[{"name": "turn", "arguments": {"direction": "up_left", "degrees": 30}}],
    )
    raw = '[{"name":"turn","arguments":{"direction":"down_right","degrees":30}}]'
    assert "reverse_direction" in score_case(case, raw).critical
    vol = EvalCase(
        id="b",
        prompt="p",
        category="single",
        expected=[{"name": "set_volume", "arguments": {"level": 50}}],
    )
    report = evaluate([vol], {"b": '[{"name":"set_volume","arguments":{"level":40}}]'})
    assert report["numeric"] == {"n": 1, "exact": 0, "mean_abs_error": 10.0}


def test_numeric_ignores_bool_and_empty() -> None:
    case = EvalCase(
        id="c",
        prompt="p",
        category="single",
        expected=[{"name": "set_volume", "arguments": {"level": 50}}],
    )
    report = evaluate([case], {"c": '[{"name":"set_volume","arguments":{"level":true}}]'})
    assert report["numeric"] == {"n": 0, "exact": 0, "mean_abs_error": None}
