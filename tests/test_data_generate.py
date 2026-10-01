# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Exercise the generation phases with a fake generator (no network, no GPU)."""

import json
from argparse import Namespace
from pathlib import Path

import pytest

from jtalm.data import generate

CFG = {
    "seed": 7,
    "per_request": 2,
    "temperature": 0.9,
    "top_p": 0.95,
    "max_tokens": 64,
    "train_generator": {"served_name": "qwen", "hf_id": "gen/train"},
    "eval_generator": {"served_name": "llmjp", "hf_id": "gen/eval"},
    "train_verifier": "train_generator",
    "train_quota": {"single": 4, "negation": 2},
    "eval_quota": {"single": 2, "no_action": 2},
    "eval_pairs": 4,
    "eval_english": 4,
}


class FakeGenerator:
    def __init__(self, base_url: str, model: str, cfg: dict) -> None:
        self.model = model

    def chat_json(self, messages: list[dict], fmt: dict, seed: int, temperature: float):
        name = fmt["json_schema"]["name"]
        if name == "sentences":
            n = fmt["json_schema"]["schema"]["properties"]["sentences"]["minItems"]
            return {"sentences": [f"文{seed}-{i}" for i in range(n)]}
        if name == "pairs":
            n = fmt["json_schema"]["schema"]["properties"]["pairs"]["minItems"]
            return {
                "pairs": [
                    {"positive": f"正{seed}-{i}", "negative": f"否{seed}-{i}"} for i in range(n)
                ]
            }
        return []  # verifier: always no-action


@pytest.fixture
def run_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(CFG), encoding="utf-8")
    monkeypatch.setattr(generate, "Generator", FakeGenerator)

    def run(phase: str) -> dict:
        args = Namespace(
            phase=phase, config=str(cfg_path), base_url="x", workers=4, out=str(tmp_path)
        )
        return generate.run(args)

    return run, tmp_path


def test_phases_produce_raw_files_with_labels(run_phase) -> None:
    run, out = run_phase
    assert run("eval-gen")["rows"] > 0
    assert run("train-gen")["rows"] == 6  # single 2 requests + negation 1 request, 2 sentences each
    run("eval-verify")
    run("train-verify")

    train = [json.loads(x) for x in (out / "train_raw.jsonl").read_text("utf-8").splitlines()]
    evals = [json.loads(x) for x in (out / "eval_raw.jsonl").read_text("utf-8").splitlines()]
    assert all(r["generator"] == "gen/train" and r["verifier"] == "gen/train" for r in train)
    assert all(r["generator"] == "gen/eval" and r["verifier"] == "gen/train" for r in evals)
    assert all(r["verified"] == [] for r in train + evals)
    pairs = [r for r in evals if r.get("pair_id")]
    assert len(pairs) == CFG["eval_pairs"] * 2
    assert {r["category"] for r in pairs} == {"single", "negation"}
    assert sum(r["language"] == "en" for r in evals) == CFG["eval_english"]
    assert all(isinstance(r["label"], list) for r in train + evals)


def test_v03_writer_config_uses_style_subsets_and_the_separate_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    class Recording(FakeGenerator):
        def chat_json(self, messages, fmt, seed, temperature):
            seen.append(messages[-1]["content"])
            return super().chat_json(messages, fmt, seed, temperature)

    cfg = {
        **CFG,
        "prompt_version": "action-v0.3",
        "train_styles": "v0.3",
        "train_generator": {"served_name": "calm3", "hf_id": "gen/writer"},
        "verifier": {"served_name": "qwen", "hf_id": "gen/verifier"},
        "train_verifier": "verifier",
    }
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(generate, "Generator", Recording)
    for phase in ("train-gen", "train-verify"):
        generate.run(
            Namespace(phase=phase, config=str(cfg_path), base_url="x", workers=1, out=str(tmp_path))
        )
    rows = [json.loads(x) for x in (tmp_path / "train_raw.jsonl").read_text("utf-8").splitlines()]
    assert {r["generator"] for r in rows} == {"gen/writer"}
    assert {r["verifier"] for r in rows} == {"gen/verifier"}
    assert {r["prompt_version"] for r in rows} == {"action-v0.3"}
    gen_prompts = [p for p in seen if "意味:" in p]
    assert len({p.split("例: ")[1].split("）")[0] for p in gen_prompts}) > 1  # styles vary


def test_focus_eval_generation_tags_slices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from jtalm.data.focus import SLICES

    cfg = {
        **CFG,
        "spec_set": "focus",
        "slice_quota": {s: 2 for s in SLICES if s != "english"},
        "eval_pairs": 0,
        "eval_english": 4,
    }
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(generate, "Generator", FakeGenerator)
    generate.run(
        Namespace(
            phase="eval-gen", config=str(cfg_path), base_url="x", workers=2, out=str(tmp_path)
        )
    )
    rows = [json.loads(x) for x in (tmp_path / "eval_gen.jsonl").read_text("utf-8").splitlines()]
    assert {r["slice"] for r in rows} == set(SLICES)
    assert all(r["language"] == "en" for r in rows if r["slice"] == "english")


class BowGenerator:
    def __init__(self, base_url: str, model: str, cfg: dict) -> None:
        self.model = model

    def chat_json(self, messages: list[dict], fmt: dict, seed: int, temperature: float):
        return [{"name": "bow", "arguments": {}}]


def _reverify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, src: Path) -> tuple[dict, list]:
    monkeypatch.setattr(generate, "Generator", BowGenerator)
    cfg = tmp_path / "c.json"
    cfg.write_text(
        json.dumps({**CFG, "verifier": {"served_name": "q", "hf_id": "Qwen/x"}}), "utf-8"
    )
    args = Namespace(
        phase="reverify",
        config=str(cfg),
        base_url="x",
        workers=1,
        out=str(tmp_path / "o"),
        input=[str(src)],
    )
    summary = generate.run(args)
    rows = [
        json.loads(x) for x in (tmp_path / "o/reverify_raw.jsonl").read_text("utf-8").splitlines()
    ]
    return summary, rows


def test_reverify_reads_cases_and_keeps_their_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "train.jsonl"
    src.write_text(
        '{"id": "t-1", "category": "single", "prompt": "お辞儀して", '
        '"expected": [], "language": "ja"}\n',
        encoding="utf-8",
    )
    summary, rows = _reverify(tmp_path, monkeypatch, src)
    assert summary["rows"] == 1
    assert rows[0]["id"] == "t-1" and rows[0]["expected"] == []
    assert rows[0]["verified"] == [{"name": "bow", "arguments": {}}]
    assert rows[0]["file"] == str(src)


def test_reverify_reads_the_stackchan_sources_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "sources.jsonl"
    src.write_text(
        '{"id": "sc-001", "text": "左に頭を回して。", "source_url": "u", '
        '"license": "MIT", "kind": "verbatim"}\n',
        encoding="utf-8",
    )
    _, rows = _reverify(tmp_path, monkeypatch, src)
    assert rows[0]["text"] == "左に頭を回して。"
    assert rows[0]["expected"] == [] and rows[0]["category"] == "unknown"
    assert rows[0]["file"] == str(src)


def test_spec_set_v1_uses_the_v1_specs() -> None:
    import random

    specs = generate._specs_for(
        {"spec_set": "v1", "per_request": 8}, {"single": 16}, random.Random(0)
    )
    assert all(s.id.startswith("v1.single.") for s in specs) and len(specs) == 2


@pytest.mark.parametrize(
    "line", ["{not json", '{"id": "x"}', '{"id": "x", "text": ""}', '{"id": "x", "prompt": null}']
)
def test_reverify_fails_fast_on_bad_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line: str
) -> None:
    src = tmp_path / "bad.jsonl"
    src.write_text('{"id": "ok", "text": "a"}\n' + line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.jsonl:2"):
        _reverify(tmp_path, monkeypatch, src)
    assert not (tmp_path / "o/reverify_raw.jsonl").exists()


def test_reverify_requires_input_and_reports_input_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generate, "Generator", BowGenerator)
    cfg = tmp_path / "c.json"
    cfg.write_text(
        json.dumps({**CFG, "verifier": {"served_name": "q", "hf_id": "Qwen/x"}}), "utf-8"
    )
    args = Namespace(
        phase="reverify",
        config=str(cfg),
        base_url="x",
        workers=1,
        out=str(tmp_path / "o"),
        input=[],
    )
    with pytest.raises(ValueError, match="reverify needs --input"):
        generate.run(args)
    src = tmp_path / "s.jsonl"
    src.write_text('{"id": "a", "text": "x"}\n', encoding="utf-8")
    summary, _ = _reverify(tmp_path, monkeypatch, src)
    assert summary["input_rows"] == 1 and summary["rows"] == 1
