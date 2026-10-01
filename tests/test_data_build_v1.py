# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json
from pathlib import Path

import pytest

from jtalm.data.build_v1 import relabel, relabel_old_eval
from jtalm.eval.cases import EvalCase, load_cases, write_cases

LOOK = [{"name": "look", "arguments": {"direction": "left", "amount": "large"}}]
DEG = [{"name": "look", "arguments": {"direction": "left", "degrees": 90}}]
TURN = [{"name": "turn", "arguments": {"direction": "right", "amount": "slight"}}]


def row(i: str, text: str, expected: list, verified: list, category: str = "single") -> dict:
    return {
        "id": i,
        "text": text,
        "expected": expected,
        "verified": verified,
        "category": category,
        "language": "ja",
        "source": "synthetic:x",
        "file": "train.jsonl",
    }


def test_relabel_keeps_agreeing_rows_and_relabels_only_into_v1() -> None:
    rows = [
        row("a", "左を大きく向いて", LOOK, LOOK),
        row("b", "左に90度ターンして", LOOK, DEG),
        row(
            "c",
            "もう少し右",
            [{"name": "look", "arguments": {"direction": "right", "amount": "slight"}}],
            TURN,
        ),
        row("d", "今日は晴れ", [], LOOK, "no_action"),
        row(
            "e",
            "音量を上げて",
            [],
            [{"name": "adjust_volume", "arguments": {"direction": "up", "amount": "normal"}}],
            "no_action",
        ),
        row("f", "壊れた行", LOOK, None),
    ]
    cases, changed, dropped = relabel(rows)
    by_id = {c.id: c for c in cases}
    assert by_id["a"].expected == LOOK and by_id["a"].source == "synthetic:x"
    assert by_id["b"].expected == DEG and by_id["b"].source.endswith("+relabel:v1")
    assert by_id["c"].expected == TURN
    assert by_id["e"].category == "single"
    assert "d" not in by_id and "f" not in by_id
    assert [r["id"] for r in changed] == ["b", "c", "e"]
    assert dropped == {"verifier_disagrees_v0": 1, "verify_failed": 1}


def _setup(tmp_path: Path) -> tuple[dict, dict, Path]:
    src = tmp_path / "old.jsonl"
    write_cases(
        src,
        [
            EvalCase(id="b", prompt="左に90度ターンして", expected=LOOK, category="single"),
            EvalCase(id="z", prompt="右を向いて", expected=LOOK, category="single"),
        ],
    )
    rev = {src.as_posix(): [row("b", "左に90度ターンして", LOOK, DEG)]}
    return rev, {"s": src.as_posix()}, tmp_path / "out"


def test_old_eval_relabel_applies_overrides(tmp_path: Path) -> None:
    rev, old, out = _setup(tmp_path)
    out.mkdir()
    (out / "overrides.jsonl").write_text(json.dumps({"id": "z", "expected": TURN}) + "\n", "utf-8")
    stats: dict = {}
    relabel_old_eval(rev, old, out, stats)
    by_id = {c.id: c for c in load_cases(out / "s.jsonl")}
    assert by_id["b"].expected == DEG and by_id["z"].expected == TURN
    assert stats["relabel_s"]["overridden"] == 1 and stats["relabel_s"]["changed"] == 1


def test_old_eval_relabel_unknown_override_id_raises(tmp_path: Path) -> None:
    rev, old, out = _setup(tmp_path)
    out.mkdir()
    (out / "overrides.jsonl").write_text(json.dumps({"id": "nope", "expected": []}) + "\n", "utf-8")
    with pytest.raises(ValueError, match="nope"):
        relabel_old_eval(rev, old, out, {})
