# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json
from pathlib import Path

from jtalm.data.build import build
from jtalm.data.publish import prepare
from jtalm.eval.cases import load_cases

LOOK_R = [{"name": "look", "arguments": {"direction": "right", "amount": "normal"}}]
CONFIG = {
    "dataset_version": "action-test",
    "seed": 1,
    "train_generator": {"hf_id": "gen/train", "license": "Apache-2.0"},
    "eval_generator": {"hf_id": "gen/eval", "license": "Apache-2.0"},
    "massive": {"train_negatives": 2, "eval_negatives": 1},
}


def row(text: str, label: list, verified: object, category: str = "single", **kw) -> dict:
    return {
        "text": text,
        "label": label,
        "verified": verified,
        "category": category,
        "language": "ja",
        "generator": kw.pop("generator", "gen/train"),
        **kw,
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def fake_massive(dir_: Path) -> None:
    dir_.mkdir(parents=True)
    rows = [
        {"id": str(i), "partition": p, "intent": "alarm_set", "utt": f"アラームを{i}時にかけて"}
        for i, p in enumerate(["train", "train", "train", "test", "test"])
    ]
    write_jsonl(dir_ / "ja-JP.jsonl", rows)


def test_build_filters_dedups_removes_leaks_and_adds_massive(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_jsonl(
        raw / "train_raw.jsonl",
        [
            row("右を向いて", LOOK_R, LOOK_R),
            row("右を向いて！", LOOK_R, LOOK_R),  # duplicate after normalization
            row("右向いてね", LOOK_R, []),  # verifier disagrees
            row("右を向かないで", LOOK_R, LOOK_R),  # negation in a positive command
            row("左を向かないで", [], [], category="negation"),
        ],
    )
    write_jsonl(
        raw / "eval_raw.jsonl",
        [
            row("右を向いて。", LOOK_R, LOOK_R, generator="gen/eval"),  # leak from train
            row("みぎをむいてください", LOOK_R, LOOK_R, generator="gen/eval", pair_id="p1"),
            row("みぎをむかないでください", [], [], "negation", generator="gen/eval", pair_id="p1"),
            row("ひだりむいて", [], [], "negation", generator="gen/eval", pair_id="p2"),
        ],
    )
    fake_massive(tmp_path / "massive")
    out = tmp_path / "out"
    report = build([raw], out, CONFIG, tmp_path / "massive")

    train = load_cases(out / "train.jsonl") + load_cases(out / "val.jsonl")
    evals = load_cases(out / "eval.jsonl")
    assert sorted(c.prompt for c in train if not c.source.startswith("massive")) == [
        "右を向いて",
        "左を向かないで",
    ]
    assert sum(c.source.startswith("massive") for c in train) == 2
    eval_prompts = {c.prompt for c in evals}
    assert "右を向いて。" not in eval_prompts  # leak removed
    assert "ひだりむいて" not in eval_prompts  # negation without a negation word
    assert {c.pair_id for c in evals if c.pair_id} == {"p1"}
    assert sum(c.source.startswith("massive") for c in evals) == 1
    assert report["counts"]["eval"]["contrastive_pairs"] == 1
    assert report["rule_baseline_on_eval"]["n"] == len(evals)

    manifest = {"config": CONFIG}
    hf = tmp_path / "hf"
    counts = prepare(out, hf, manifest)
    assert counts["test"] == 2  # MASSIVE rows are not redistributed
    first = json.loads((hf / "test.jsonl").read_text("utf-8").splitlines()[0])
    assert set(first) == {"id", "input", "output", "category", "language", "pair_id", "generator"}
    card = (hf / "README.md").read_text("utf-8")
    assert card.startswith("---\nlicense: cc-by-sa-4.0")


def test_extend_keeps_base_and_eval_and_skips_anything_already_present(tmp_path: Path) -> None:
    from jtalm.data.build import extend

    raw = tmp_path / "raw"
    raw.mkdir()
    write_jsonl(
        raw / "train_raw.jsonl",
        [row("右を向いて", LOOK_R, LOOK_R)] * 2
        + [row("左を向かないで", [], [], category="negation")],
    )
    write_jsonl(raw / "eval_raw.jsonl", [row("みぎをむいて", LOOK_R, LOOK_R, generator="gen/eval")])
    fake_massive(tmp_path / "massive")
    base = tmp_path / "base"
    build([raw], base, CONFIG, tmp_path / "massive")
    base_eval = (base / "eval.jsonl").read_text(encoding="utf-8")

    new = tmp_path / "new"
    new.mkdir()
    write_jsonl(
        new / "train_raw.jsonl",
        [
            row("右を向いて", LOOK_R, LOOK_R, generator="gen/new"),  # already in base train
            row("みぎをむいて", LOOK_R, LOOK_R, generator="gen/new"),  # in base eval (leak)
            row("右のほう見てくれる?", LOOK_R, LOOK_R, generator="gen/new"),
            row("右むいて", LOOK_R, [], generator="gen/new"),  # verifier disagrees
        ],
    )
    out = tmp_path / "out"
    report = extend(base, [new], out, seed=1)

    assert (out / "eval.jsonl").read_text(encoding="utf-8") == base_eval
    added = load_cases(out / "train.jsonl") + load_cases(out / "val.jsonl")
    base_all = load_cases(base / "train.jsonl") + load_cases(base / "val.jsonl")
    assert len(added) == len(base_all) + 1
    assert "右のほう見てくれる?" in {c.prompt for c in added}
    assert report["keep_rate_by_generator"] == {"gen/new": 0.25}


def test_massive_load_drops_volume_intents(tmp_path: Path) -> None:
    from jtalm.data import massive

    rows = [
        {"id": "1", "partition": "train", "intent": "audio_volume_up", "utt": "音量を上げて"},
        {"id": "2", "partition": "train", "intent": "alarm_set", "utt": "アラームをかけて"},
    ]
    write_jsonl(tmp_path / "ja-JP.jsonl", rows)
    assert [r["id"] for r in massive.load(tmp_path / "ja-JP.jsonl")] == ["2"]
