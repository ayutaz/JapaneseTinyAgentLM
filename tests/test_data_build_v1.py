# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json
from pathlib import Path

import pytest

from jtalm.data.build_v1 import dedup, relabel, relabel_old_eval
from jtalm.data.checks import dedup_key
from jtalm.eval.cases import EvalCase, load_cases, write_cases

LOOK = [{"name": "look", "arguments": {"direction": "left", "amount": "large"}}]
DEG = [{"name": "look", "arguments": {"direction": "left", "degrees": 90}}]
TURN = [{"name": "turn", "arguments": {"direction": "right", "amount": "slight"}}]
VOL50 = [{"name": "set_volume", "arguments": {"level": 50}}]


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


def test_relabel_keeps_agreeing_rows_and_relabels_only_empty_rows_into_v1() -> None:
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
    assert by_id["e"].category == "single" and by_id["e"].source.endswith("+relabel:v1")
    assert set(by_id) == {"a", "e"}
    assert [r["id"] for r in changed] == ["e"]
    assert dropped == {"relabel_from_action": 2, "verifier_disagrees_v0": 1, "verify_failed": 1}


def test_rows_with_a_v0_action_are_never_relabeled() -> None:
    nod = [{"name": "nod", "arguments": {"count": 1}}]
    shake = [{"name": "shake", "arguments": {"count": 1}}]
    bright = [{"name": "set_brightness", "arguments": {"level": 80}}]
    rows = [
        row("a", "首を振って", nod, shake),  # v1-only answer
        row("b", "画面を明るくして", nod, bright),
        row("c", "うなずいて", nod, LOOK),  # a v0 answer that differs
        row("d", "うなずいて", nod, nod),
    ]
    cases, changed, dropped = relabel(rows)
    assert [(c.id, c.expected) for c in cases] == [("d", nod)] and changed == []
    assert dropped == {"relabel_from_action": 2, "verifier_disagrees_v0": 1}


def test_empty_rows_relabel_only_when_the_prompt_names_the_device() -> None:
    led = [{"name": "set_led", "arguments": {"color": "off"}}]
    darker = [{"name": "adjust_brightness", "arguments": {"direction": "down", "amount": "normal"}}]
    brighter = [{"name": "adjust_brightness", "arguments": {"direction": "up", "amount": "normal"}}]
    rows = [
        row("a", "音楽、かけてくれる?", [], VOL50, "no_action"),
        row("b", "画面を暗くして", [], darker, "no_action"),
        row("c", "部屋を明るくして", [], brighter, "no_action"),
        row("d", "光が消えた", [], led, "no_action"),
        row("e", "ランプを消して", [], led, "no_action"),
        row("f", "音を小さくして", [], VOL50, "no_action"),
    ]
    cases, changed, dropped = relabel(rows)
    assert [c.id for c in cases] == ["b", "e", "f"] == [r["id"] for r in changed]
    assert dropped == {"relabel_no_evidence": 3}


def test_relabel_must_pass_the_negation_check_for_the_new_category() -> None:
    rows = [
        row("a", "もうちょっと右に向けないで", [], TURN, "negation"),
        row("b", "音量を50にしないで", [], VOL50, "negation"),
        row("c", "音量を50にして", [], VOL50, "no_action"),
    ]
    cases, _, dropped = relabel(rows)
    assert [c.id for c in cases] == ["c"]
    assert dropped == {"relabel_from_empty": 1, "relabel_negation": 1}


def test_empty_rows_relabel_only_to_device_commands() -> None:
    angry = [{"name": "set_expression", "arguments": {"expression": "angry"}}]
    led = [{"name": "set_led", "arguments": {"color": "red"}}]
    volume = [{"name": "set_volume", "arguments": {"level": 0}}]
    rows = [
        row("a", "彼は怒っていた", [], angry, "no_action"),
        row("b", "LEDを赤にして", [], led, "no_action"),
        row("c", "静かにして", [], volume, "no_action"),
        row("d", "LEDを赤にして怒って", [], [*led, *angry], "no_action"),
    ]
    cases, _, dropped = relabel(rows)
    assert [c.id for c in cases] == ["b", "c"]
    assert {c.category for c in cases} == {"single"}
    assert dropped == {"relabel_from_empty": 2}


def test_correction_rows_are_never_relabeled() -> None:
    nod = [{"name": "nod", "arguments": {"count": 2}}]
    rows = [
        row("a", "やっぱり音量を50にして", [], VOL50, "correction"),
        row("b", "首振りはやめて、2回うなずいてよ", nod, nod, "correction"),
    ]
    cases, changed, dropped = relabel(rows)
    assert [(c.id, c.expected, c.category) for c in cases] == [("b", nod, "correction")]
    assert changed == [] and dropped == {"relabel_correction": 1}


def test_old_eval_keeps_v0_label_when_relabel_is_dropped(tmp_path: Path) -> None:
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
    assert stats["relabel_s"]["relabel_from_action"] == 1


def _setup(tmp_path: Path) -> tuple[dict, dict, Path]:
    src = tmp_path / "old.jsonl"
    write_cases(
        src,
        [
            EvalCase(id="b", prompt="音量を50にして", expected=[], category="no_action"),
            EvalCase(id="z", prompt="右を向いて", expected=LOOK, category="single"),
        ],
    )
    rev = {src.as_posix(): [row("b", "音量を50にして", [], VOL50, "no_action")]}
    return rev, {"s": src.as_posix()}, tmp_path / "out"


def test_old_eval_relabel_applies_overrides(tmp_path: Path) -> None:
    rev, old, out = _setup(tmp_path)
    out.mkdir()
    (out / "overrides.jsonl").write_text(json.dumps({"id": "z", "expected": TURN}) + "\n", "utf-8")
    stats: dict = {}
    relabel_old_eval(rev, old, out, stats)
    by_id = {c.id: c for c in load_cases(out / "s.jsonl")}
    assert by_id["b"].expected == VOL50 and by_id["z"].expected == TURN
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
        src, [EvalCase(id="b", prompt="音量50", expected=[], category="no_action", pair_id="P1")]
    )
    rev = {src.as_posix(): [row("b", "音量50", [], VOL50, "no_action")]}
    out = tmp_path / "out"
    relabel_old_eval(rev, {"s": src.as_posix()}, out, {})
    case = load_cases(out / "s.jsonl")[0]
    assert case.pair_id == "P1" and case.expected == VOL50
    out2 = tmp_path / "out2"
    out2.mkdir()
    (out2 / "overrides.jsonl").write_text(
        json.dumps({"id": "nope", "expected": []}) + "\n", "utf-8"
    )
    with pytest.raises(ValueError):
        relabel_old_eval(rev, {"s": src.as_posix()}, out2, {})
    assert not (out2 / "s.jsonl").exists()


def test_dedup_drops_repeats_within_a_split_and_seen_prompts() -> None:
    cases = [
        EvalCase(id="a", prompt="右を向いて", expected=LOOK, category="single"),
        EvalCase(id="b", prompt="右を向いて。", expected=LOOK, category="single"),
        EvalCase(id="c", prompt="左を向いて", expected=LOOK, category="single"),
        EvalCase(id="d", prompt="うなずいて", expected=[], category="no_action"),
    ]
    seen = {dedup_key("うなずいて")}
    assert [c.id for c in dedup(cases, seen)] == ["a", "c"]
    assert seen == {dedup_key(t) for t in ("うなずいて", "右を向いて", "左を向いて")}
