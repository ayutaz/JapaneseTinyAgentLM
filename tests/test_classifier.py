# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import pytest

pytest.importorskip("torch")

from jtalm.eval.cases import EvalCase  # noqa: E402
from jtalm.model.classifier import ngram_ids, predict_rows, train  # noqa: E402

RIGHT = [{"name": "look", "arguments": {"direction": "right", "amount": "normal"}}]
SMILE = [{"name": "set_expression", "arguments": {"expression": "happy"}}]


def case(i: int, prompt: str, expected: list) -> EvalCase:
    category = "single" if expected else "no_action"
    return EvalCase(id=f"c{i}", prompt=prompt, expected=expected, category=category)


def test_ngram_ids_are_deterministic_and_normalized() -> None:
    assert ngram_ids("右を見て", 1024) == ngram_ids("右を見て", 1024)
    assert ngram_ids("ＡＢＣ", 1024) == ngram_ids("abc", 1024)  # NFKC + lowercase
    assert len(ngram_ids("ab", 1024)) == 4 + 3 + 2  # with start and end marks
    assert all(0 <= i < 1024 for i in ngram_ids("右を見て", 1024))


def test_learns_a_tiny_set() -> None:
    data = [("右を見て", RIGHT), ("右を向いて", RIGHT), ("笑って", SMILE), ("笑顔にして", SMILE),
            ("今日は晴れ", []), ("おはよう", [])] * 8  # fmt: skip
    cases = [case(i, p, e) for i, (p, e) in enumerate(data)]
    model, labels, log = train(cases, cases[:6], 4096, 16, 30, 0.05, 8, 0)
    assert len(labels) == 3 and log[-1]["val_exact"] == 1.0
    rows = predict_rows(model, labels, cases[:6], gate=None)
    assert all(r["exact"] for r in rows)
    gated = predict_rows(model, labels, cases[:6], gate=1.01)
    assert all(r["output"] == "[]" for r in gated)
