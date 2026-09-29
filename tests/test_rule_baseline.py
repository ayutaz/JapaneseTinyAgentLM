import json

import pytest

from jtalm.eval.rule_baseline import predict, predict_json


def look(direction: str, amount: str = "normal") -> dict:
    return {"name": "look", "arguments": {"direction": direction, "amount": amount}}


HAPPY = {"name": "set_expression", "arguments": {"expression": "happy"}}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("右を向いて。", [look("right")]),
        ("少し右を向いて。", [look("right", "slight")]),
        ("右を向いて笑って。", [look("right"), HAPPY]),
        ("笑ってから左を向いて。", [HAPPY, look("left")]),
        ("左を向かないで。", []),
        ("右ではなく左を向いて", [look("left")]),
        ("2回うなずいて。", [{"name": "nod", "arguments": {"count": 2}}]),
        ("富士山について教えて。", []),
        ("Look right.", [look("right")]),
    ],
)
def test_rule_baseline_examples(text: str, expected: list) -> None:
    assert predict(text) == expected


def test_predict_json_is_parseable() -> None:
    assert json.loads(predict_json("何もしないで")) == []
    assert json.loads(predict_json("上を向いて"))[0]["arguments"]["direction"] == "up"
