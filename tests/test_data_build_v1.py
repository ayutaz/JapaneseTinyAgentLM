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


def test_relabel_drops_v1_labels_without_lexical_evidence() -> None:
    slight_up = [{"name": "look", "arguments": {"direction": "up", "amount": "slight"}}]
    turn_up = [{"name": "turn", "arguments": {"direction": "up", "amount": "slight"}}]
    led = [{"name": "set_led", "arguments": {"color": "off"}}]
    rows = [
        row("a", "ちょこっと上向いてくれる?", slight_up, turn_up),
        row("b", "笑いはやめて、ちょっと待って", [], led, "no_action"),
        row("c", "もう少し上", slight_up, turn_up),
    ]
    cases, changed, dropped = relabel(rows)
    assert [c.id for c in cases] == ["c"] and [r["id"] for r in changed] == ["c"]
    assert dropped == {"relabel_no_evidence": 2}


def test_old_eval_keeps_v0_label_when_relabel_lacks_evidence(tmp_path: Path) -> None:
    src = tmp_path / "old.jsonl"
    slight_up = [{"name": "look", "arguments": {"direction": "up", "amount": "slight"}}]
    turn_up = [{"name": "turn", "arguments": {"direction": "up", "amount": "slight"}}]
    write_cases(
        src, [EvalCase(id="a", prompt="ちょこっと上", expected=slight_up, category="single")]
    )
    rev = {src.as_posix(): [row("a", "ちょこっと上", slight_up, turn_up)]}
    stats: dict = {}
    relabel_old_eval(rev, {"s": src.as_posix()}, tmp_path / "out", stats)
    assert load_cases(tmp_path / "out" / "s.jsonl")[0].expected == slight_up
    assert stats["relabel_s"]["changed"] == 0
    assert stats["relabel_s"]["relabel_no_evidence"] == 1


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


def test_relabel_drops_schema_invalid_verified_labels() -> None:
    center_deg = [{"name": "look", "arguments": {"direction": "center", "degrees": 30}}]
    bows = [{"name": "bow", "arguments": {}}] * 2
    broken = [{"name": "nod", "arguments": {"count": "x"}}]
    rows = [
        row("a", "x", [], center_deg, "no_action"),
        row("b", "y", [], bows, "no_action"),
        row("c", "z", [], broken, "no_action"),
    ]
    cases, _, dropped = relabel(rows)
    assert cases == []
    assert dropped["verified_invalid"] >= 2
    assert dropped["verify_failed"] + dropped["verified_invalid"] == 3


def test_category_follows_call_count() -> None:
    two = [*LOOK, *TURN]
    cases, _, _ = relabel(
        [
            row("a", "x", two, two, "single"),
            row("b", "y", LOOK, LOOK, "multi_action"),
            row("c", "z", LOOK, LOOK, "correction"),
        ]
    )
    assert {c.id: c.category for c in cases} == {
        "a": "multi_action",
        "b": "single",
        "c": "correction",
    }


def test_invalid_override_raises(tmp_path: Path) -> None:
    rev, old, out = _setup(tmp_path)
    out.mkdir()
    bad = [{"name": "bow", "arguments": {}}] * 2
    (out / "overrides.jsonl").write_text(json.dumps({"id": "z", "expected": bad}) + "\n", "utf-8")
    with pytest.raises(ValueError, match="z"):
        relabel_old_eval(rev, old, out, {})


def test_old_eval_keeps_pair_id_and_checks_overrides_before_writing(tmp_path: Path) -> None:
    src = tmp_path / "old.jsonl"
    write_cases(
        src, [EvalCase(id="b", prompt="左に90度", expected=LOOK, category="single", pair_id="P1")]
    )
    rev = {src.as_posix(): [row("b", "左に90度", LOOK, DEG)]}
    out = tmp_path / "out"
    relabel_old_eval(rev, {"s": src.as_posix()}, out, {})
    case = load_cases(out / "s.jsonl")[0]
    assert case.pair_id == "P1" and case.expected == DEG
    out2 = tmp_path / "out2"
    out2.mkdir()
    (out2 / "overrides.jsonl").write_text(
        json.dumps({"id": "nope", "expected": []}) + "\n", "utf-8"
    )
    with pytest.raises(ValueError):
        relabel_old_eval(rev, {"s": src.as_posix()}, out2, {})
    assert not (out2 / "s.jsonl").exists()
