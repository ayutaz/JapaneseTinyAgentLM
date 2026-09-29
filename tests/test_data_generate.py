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
