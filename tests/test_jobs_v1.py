# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json
import re
from pathlib import Path

from jtalm.infra.jobs import JOBS, STACKCHAN_SOURCES, V1_REVERIFY_INPUTS

ROOT = Path(__file__).resolve().parents[1]
JOB = JOBS["gen_action_v1"]
STEPS = "\n".join(JOB.steps)


def _configs() -> list[str]:
    return sorted(set(re.findall(r"configs/[\w.]+\.json", STEPS)))


def test_job_registered_with_configs():
    assert JOB.name == "gen_action_v1"
    names = {Path(c).name for c in _configs()}
    assert names == {
        "action_v1_abeja.json", "action_v1_calm3.json", "action_v1_elyza.json",
        "action_v1_nemoja.json", "action_v1_qwen.json", "eval_v3.json",
        "stackchan_v1_paraphrase.json",
    }  # fmt: skip
    for c in _configs():
        json.loads((ROOT / c).read_text(encoding="utf-8"))


def test_served_names_match_started_servers():
    served = re.findall(r"--served-model-name (\w+)", STEPS)
    assert set(served) == {"llmjp", "abeja", "calm3", "elyza", "nemoja", "qwen"}
    for c in _configs():
        cfg = json.loads((ROOT / c).read_text(encoding="utf-8"))
        for key in ("train_generator", "eval_generator", "verifier"):
            assert cfg[key]["served_name"] in served
        if "action_v1_" in c:
            assert cfg["train_generator"]["served_name"] == Path(c).stem.removeprefix("action_v1_")


def test_reverify_inputs():
    step = next(s for s in JOB.steps if "--phase reverify" in s)
    inputs = step.split(" --input ")[1].split()
    assert inputs == [*V1_REVERIFY_INPUTS, STACKCHAN_SOURCES]
    assert JOB.uploads == inputs
