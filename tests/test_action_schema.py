import json
from pathlib import Path

import pytest

from jtalm.action import canonicalize, parse_output, to_json, validate
from jtalm.eval import load_cases

BENCH = Path(__file__).parent / "fixtures" / "tinylm_bench"


def look(direction: str, amount: str = "normal") -> dict:
    return {"name": "look", "arguments": {"direction": direction, "amount": amount}}


def test_bench_expected_outputs_are_valid() -> None:
    cases = load_cases(BENCH / "action_cases.json")
    assert len(cases) == 16
    for case in cases:
        assert validate(case.expected) == [], case.id


@pytest.mark.parametrize(
    "calls",
    [
        [],
        [look("right")],
        [look("up", "slight"), {"name": "set_expression", "arguments": {"expression": "happy"}}],
        [{"name": "nod", "arguments": {"count": 3}}],
    ],
)
def test_valid_outputs(calls: list) -> None:
    assert validate(calls) == []


@pytest.mark.parametrize(
    ("calls", "reason"),
    [
        ([look("right"), look("left"), look("up")], "more than 2 calls"),
        ([{"name": "look", "arguments": {"direction": "right", "amount": "right"}}], "amount enum"),
        ([{"name": "look", "arguments": {"direction": "right"}}], "missing amount"),
        ([{"name": "set_expression", "arguments": {"expression": "smile"}}], "expression enum"),
        ([{"name": "nod", "arguments": {}}], "missing count"),
        ([{"name": "nod", "arguments": {"count": 4}}], "count range"),
        ([{"name": "speak", "arguments": {"text": "hi"}}], "unknown tool"),
        (
            [{"name": "look", "arguments": {"direction": "right", "amount": "normal", "x": 1}}],
            "extra",
        ),
        ([look("right"), look("right")], "duplicate call"),
        ({"name": "look"}, "not an array"),
    ],
)
def test_invalid_outputs(calls: object, reason: str) -> None:
    assert validate(calls) != [], reason


def test_parse_output_rejects_non_json_and_non_array() -> None:
    assert not parse_output("右を向きます").json_valid
    assert not parse_output('{"name": "look"}').json_valid
    parsed = parse_output("[]")
    assert parsed.json_valid and parsed.schema_valid and parsed.calls == []


def test_duplicate_is_json_valid_but_schema_invalid() -> None:
    parsed = parse_output(json.dumps([look("left"), look("left")]))
    assert parsed.json_valid and not parsed.schema_valid


def test_canonicalize_center_ignores_amount_and_keeps_order() -> None:
    calls = [look("center", "large"), {"name": "nod", "arguments": {"count": 1}}]
    canonical = canonicalize(calls)
    assert canonical[0]["arguments"]["amount"] == "normal"
    assert [c["name"] for c in canonical] == ["look", "nod"]


def test_to_json_is_compact_and_keeps_japanese_free_output() -> None:
    assert to_json([look("right")]) == (
        '[{"arguments":{"amount":"normal","direction":"right"},"name":"look"}]'
    )
