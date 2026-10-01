# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json

from jtalm.eval.consistency import consistency


def look(direction: str) -> dict:
    return {"name": "look", "arguments": {"direction": direction, "amount": "normal"}}


def row(id_: str, expected: list) -> dict:
    return {"id": id_, "prompt": id_, "language": "ja", "expected": expected}


def test_pairs_within_groups_only() -> None:
    rows = [
        row("a", [look("right")]),
        row("b", [look("right")]),
        row("c", [look("right")]),
        row("d", [look("left")]),
        row("e", [look("left")]),
        row("n1", []),
        row("n2", []),
        row("solo", [look("up")]),
    ]
    right = json.dumps([look("right")])
    outputs = {
        "a": right,
        "b": right,
        "c": "[]",  # disagrees with a and b
        "d": right,  # wrong but consistent with e
        "e": right,
        "n1": "[]",
        "n2": right,
        "solo": "[]",
    }
    r = consistency(rows, outputs)
    assert r["groups"] == 2 and r["cases"] == 5
    assert r["pairs"] == 3 + 1
    assert r["pair_agreement"] == (1 + 1) / 4
    assert r["groups_all_same"] == 1 / 2


def test_canonical_comparison_and_invalid_text() -> None:
    rows = [row("a", [look("right")]), row("b", [look("right")]), row("c", [look("right")])]
    outputs = {
        "a": '[{"name":"look","arguments":{"direction":"right","amount":"normal"}}]',
        "b": '[{"arguments":{"amount":"normal","direction":"right"},"name":"look"}]',
        "c": "not json",
    }
    r = consistency(rows, outputs)
    assert r["pairs"] == 3 and r["pair_agreement"] == 1 / 3
