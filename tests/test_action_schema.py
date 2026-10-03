# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json
from pathlib import Path

import pytest

from jtalm.action import canonicalize, parse_output, to_json, validate
from jtalm.action.schema import TOOLS, build_schema, load_schema, uses_v1_only
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
        ([{"name": "nod", "arguments": {"count": 6}}], "count range"),
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


def call(name: str, **arguments: object) -> dict:
    return {"name": name, "arguments": arguments}


@pytest.mark.parametrize(
    "calls",
    [
        [call("look", direction="right", degrees=45)],
        [call("look", direction="up_left", amount="slight")],
        [call("turn", direction="down_right", degrees=180)],
        [call("nod", count=5), call("shake", count=1)],
        [call("bow")],
        [call("set_expression", expression="doubt")],
        [call("set_led", color="light_blue"), call("set_led", color="off")],
        [call("set_volume", level=0), call("set_brightness", level=100)],
        [call("adjust_volume", direction="up", by=10)],
        [call("adjust_brightness", direction="down", amount="large")],
    ],
)
def test_v1_valid_outputs(calls: list) -> None:
    assert validate(calls) == []


@pytest.mark.parametrize(
    ("calls", "reason"),
    [
        ([call("look", direction="right", degrees=0)], "degrees below 1"),
        ([call("look", direction="right", degrees=181)], "degrees above 180"),
        ([call("look", direction="right", amount="normal", degrees=45)], "both magnitudes"),
        ([call("turn", direction="center", amount="normal")], "turn has no center"),
        ([call("look", direction="center", degrees=10)], "center takes no degrees"),
        ([call("nod", count=6)], "count above 5"),
        ([call("bow", count=1)], "bow takes no arguments"),
        ([call("set_led", color="black")], "color enum"),
        ([call("set_volume", level=101)], "level above 100"),
        ([call("adjust_volume", direction="left", by=10)], "adjust direction"),
        ([call("adjust_volume", direction="up", by=0)], "by below 1"),
        ([call("adjust_volume", direction="up")], "missing amount or by"),
    ],
)
def test_v1_invalid_outputs(calls: list, reason: str) -> None:
    assert validate(calls) != [], reason


def test_schema_file_is_generated_from_tools() -> None:
    assert load_schema() == build_schema()
    assert list(TOOLS) == [
        "look",
        "turn",
        "nod",
        "shake",
        "bow",
        "set_expression",
        "set_led",
        "set_volume",
        "adjust_volume",
        "set_brightness",
        "adjust_brightness",
    ]


def test_uses_v1_only_separates_v0_outputs() -> None:
    assert not uses_v1_only([look("right", "large"), call("nod", count=3)])
    assert not uses_v1_only([call("set_expression", expression="neutral")])
    assert uses_v1_only([call("look", direction="right", degrees=90)])
    assert uses_v1_only([call("look", direction="up_left", amount="normal")])
    assert uses_v1_only([call("nod", count=4)])
    assert uses_v1_only([call("set_expression", expression="angry")])
    assert uses_v1_only([call("turn", direction="right", amount="slight")])
    assert uses_v1_only([call("set_volume", level=50)])
