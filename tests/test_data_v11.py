# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json
import random
import re
from collections import Counter
from pathlib import Path

from jtalm.action.schema import validate
from jtalm.data import prompts
from jtalm.data.build_v11 import build
from jtalm.data.generate import _specs_for
from jtalm.data.specs_v11 import ON, all_specs_v11
from jtalm.eval.cases import EvalCase, write_cases
from jtalm.infra.jobs import JOBS

ROOT = Path(__file__).resolve().parents[1]
WHITE = [ON]
RED = [{"name": "set_led", "arguments": {"color": "red"}}]


def test_labels_are_valid_and_on_needs_no_color() -> None:
    specs = all_specs_v11()
    for s in specs:
        assert validate(list(s.label)) == [], s.id
    on = [s for s in specs if s.category == "single" and "on_" in s.id]
    assert on and all(s.label == (ON,) and "色の名前" in "".join(prompts.requirements(s))
                      for s in on)  # fmt: skip
    # the on specs are weighted: about half of the single requests
    single = [s for s in specs if s.category == "single"]
    assert 0.4 <= len(on) / len(single) <= 0.6


def test_every_color_is_covered() -> None:
    colors = {s.label[0]["arguments"]["color"] for s in all_specs_v11()
              if s.category == "single"}  # fmt: skip
    assert colors == {"red", "orange", "yellow", "green", "light_blue", "blue", "purple", "pink",
                      "white", "off"}  # fmt: skip


def test_corrections_and_negation_turn_on() -> None:
    specs = {s.id: s for s in all_specs_v11()}
    assert specs["v11.correction.set_led.off->set_led.on"].label == (ON,)
    assert specs["v11.negation.set_led.on"].label == ()


def test_configs_sample_v11_specs() -> None:
    for name in ("qwen", "abeja", "nemoja"):
        cfg = json.loads((ROOT / f"configs/action_v11_{name}.json").read_text("utf-8"))
        assert cfg["train_generator"]["served_name"] == name and cfg["spec_set"] == "v1.1"
        reqs = _specs_for(cfg, cfg["train_quota"], random.Random(0))
        assert all(s.id.startswith("v11.") for s in reqs)
        assert Counter(s.category for s in reqs)["single"] == -(-700 // cfg["per_request"])
    ev = json.loads((ROOT / "configs/eval_v11_led.json").read_text("utf-8"))
    assert ev["spec_set"] == "v1.1" and ev["train_quota"] == {}


def test_job_starts_each_model_once_and_verifies_after_qwen() -> None:
    steps = JOBS["gen_action_v11"].steps
    started = re.findall(r"\$VLLM serve (\S+) --port", "\n".join(steps))
    assert started == ["llm-jp/llm-jp-3.1-13b-instruct4", "abeja/ABEJA-Qwen2.5-32b-Japanese-v1.0",
                       "cyberagent/Mistral-Nemo-Japanese-Instruct-2408",
                       "Qwen/Qwen3-30B-A3B-Instruct-2507"]  # fmt: skip
    qwen = next(i for i, s in enumerate(steps) if "serve Qwen/" in s)
    verify = [i for i, s in enumerate(steps) if re.search(r"--phase (train|eval)-verify", s)]
    assert len(verify) == 4 and min(verify) > qwen
    for i, s in enumerate(steps):
        if "$VLLM serve" in s:
            assert steps[i - 1] == "df -h /"


def _write_raw(path: Path, name: str, rows: list[tuple[str, list, list]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "text": t,
                "label": label,
                "verified": verified,
                "category": "single",
                "language": "ja",
                "generator": "g",
            },
            ensure_ascii=False,
        )  # fmt: skip
        for t, label, verified in rows
    ]
    (path / name).write_text("\n".join(lines) + "\n", "utf-8")


def test_build_keeps_base_and_adds_only_agreeing_new_rows(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    write_cases(base / "train.jsonl", [EvalCase("t1", "LEDを赤にして", RED, "single")])
    write_cases(base / "val.jsonl", [EvalCase("v1", "ライトを赤に", RED, "single")])
    held = tmp_path / "held.jsonl"
    write_cases(held, [EvalCase("e1", "評価の文", WHITE, "single")])
    raw = tmp_path / "raw"
    _write_raw(raw / "raw11_eval", "eval_raw.jsonl",
               [("ライト点灯して", WHITE, WHITE), ("LEDを赤にして", RED, RED)])  # fmt: skip
    _write_raw(raw / "raw11_qwen", "train_raw.jsonl", [
        ("LEDつけて", WHITE, WHITE),  # kept
        ("ライトつけて", WHITE, [{"name": "set_led", "arguments": {"color": "off"}}]),  # disagrees
        ("ライト点灯して", WHITE, WHITE),  # in the LED eval set
        ("評価の文", WHITE, WHITE),  # in a held-out eval set
    ])  # fmt: skip
    train, val, led_eval, stats = build(raw, base, [held], seed=0)
    assert [c.prompt for c in led_eval] == ["ライト点灯して"]  # 「LEDを赤にして」 is in base
    assert [c.prompt for c in train] == ["LEDを赤にして", "LEDつけて"]
    assert [c.prompt for c in val] == ["ライトを赤に"]
    assert stats["new"]["n"] == 1 and stats["new"]["single:verifier_disagrees"] == 1
    assert train[-1].source == "synthetic:g"
