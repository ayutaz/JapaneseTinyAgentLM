# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json

from jtalm.eval.cases import EvalCase
from jtalm.infra.jobs import JOBS, TRAIN_ACTION_V051, train_action_steps
from jtalm.model import eval_suite as es


def _call(name, **args):
    return {"name": name, "arguments": args}


LOOK45 = [_call("look", direction="right", degrees=45)]


def _case(id_, expected, source=None, category="single"):
    return EvalCase(id=id_, prompt="p", expected=expected, category=category, source=source)


def _row(id_, output):
    return {"id": id_, "output": output}


def test_numeric_gated_rate_all_gated():
    cases = [_case("a", LOOK45)]
    raw = [_row("a", json.dumps(LOOK45))]
    gated = [_row("a", "[]")]
    assert es.numeric_gated_rate(cases, raw, gated) == 1.0


def test_numeric_gated_rate_ignores_non_numeric_and_empty_raw():
    cases = [
        _case("a", LOOK45),
        _case("b", LOOK45),
        _case("c", [_call("look", direction="left", amount="normal")]),
        _case("d", []),
    ]
    raw = [_row("a", "x"), _row("b", "[]"), _row("c", "x"), _row("d", "x")]
    gated = [_row("a", "x"), _row("b", "[]"), _row("c", "[]"), _row("d", "[]")]
    # only a and b have numeric expected; b was already [] without the gate
    assert es.numeric_gated_rate(cases, raw, gated) == 0.0
    gated[0] = _row("a", "[]")
    assert es.numeric_gated_rate(cases, raw, gated) == 0.5


def test_numeric_gated_rate_none_without_numeric_cases():
    assert es.numeric_gated_rate([_case("d", [])], [_row("d", "[]")], [_row("d", "[]")]) is None


def test_source_kind():
    assert es.source_kind("verbatim:https://x") == "verbatim"
    assert es.source_kind("user") == "user"
    assert es.source_kind("paraphrase:gpt") == "paraphrase"
    assert es.source_kind(None) == "other"


def test_stackchan_breakdown():
    turn = [_call("turn", direction="left", degrees=30)]
    cases = [
        _case("a", LOOK45, source="user"),
        _case("b", turn, source="verbatim:u"),
        _case("c", LOOK45 + turn, source="paraphrase:g"),
    ]
    rows = [
        {"id": "a", "exact": True},
        {"id": "b", "exact": False},
        {"id": "c", "exact": True},
    ]
    b = es.stackchan_breakdown(cases, rows)
    assert b["by_source"] == {
        "user": {"n": 1, "exact": 1.0},
        "verbatim": {"n": 1, "exact": 0.0},
        "paraphrase": {"n": 1, "exact": 1.0},
    }
    assert b["by_tool"]["look"] == {"n": 2, "exact": 1.0}
    assert b["by_tool"]["turn"] == {"n": 2, "exact": 0.5}


def test_existing_job_steps_unchanged():
    assert TRAIN_ACTION_V051.steps[-1].endswith(
        "--tokenizer tokenizer/out/action_v0_sp2048.model --cases datasets/action/v0/eval.jsonl "
        "--out artifacts/v051/eval"
    )
    runs = [("3m", "3m", "--seed 0")]
    assert train_action_steps(runs, "t") == train_action_steps(
        runs,
        "t",
        tokenizer="tokenizer/out/action_v0_sp2048.model",
        cases="datasets/action/v0/eval.jsonl",
    )


def test_train_action_v1_job():
    job = JOBS["train_action_v1"]
    text = "\n".join(job.steps)
    assert all(f"--seed {i}" in text for i in range(5))
    assert "action_v1_sp2048.model" in text
    assert "datasets/action/v1.0/val.jsonl" in job.steps[-1]
    assert "eval.jsonl" not in text
    assert "datasets/action/v1.0/train.jsonl" in job.uploads
    assert not any("eval" in u for u in job.uploads)


def test_suite_skips_missing_sets(capsys):
    sets = es.suite_sets()
    assert all(p.exists() for p in sets.values())
    err = capsys.readouterr().err
    for name, path in es.DEFAULT_SETS.items():
        if not (es.PROJECT_ROOT / path).exists():
            assert name in err
