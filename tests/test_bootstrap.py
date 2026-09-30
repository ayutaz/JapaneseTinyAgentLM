import random

from jtalm.eval.bootstrap import ci, metric_values, paired_diff

LOOK = [{"name": "look", "arguments": {"direction": "left", "amount": "normal"}}]


def row(i: int, expected: list, output: str, exact: bool) -> dict:
    return {"id": f"c{i}", "expected": expected, "output": output, "exact": exact}


def test_metric_values_split_requests_and_non_requests() -> None:
    rows = [row(0, LOOK, "[]", False), row(1, LOOK, "x", True), row(2, [], "x", False)]
    vals = metric_values(rows)
    assert vals["exact"] == [0.0, 1.0, 0.0]
    assert vals["requests_exact"] == [0.0, 1.0]
    assert vals["false_action_rate"] == [1.0]


def test_ci_contains_the_mean_and_is_degenerate_for_constant_values() -> None:
    mean, lo, hi = ci([1.0] * 50 + [0.0] * 50, random.Random(0), 1000)
    assert lo < mean == 0.5 < hi
    assert ci([1.0] * 20, random.Random(0), 200) == (1.0, 1.0, 1.0)


def test_paired_diff_uses_matching_ids() -> None:
    a = [row(i, LOOK, "[]", False) for i in range(10)]
    b = [row(i, LOOK, "x", True) for i in range(10)]
    mean, lo, hi, p_better = paired_diff(a, b, "exact", random.Random(0), 200)
    assert (mean, lo, hi, p_better) == (1.0, 1.0, 1.0, 1.0)
