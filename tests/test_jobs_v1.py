# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from jtalm.infra.jobs import JOBS, STACKCHAN_SOURCES, V1_REVERIFY_INPUTS, _drop_weights

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


V1B = JOBS["gen_action_v1b"]
V1B_DONE_FILES = [
    "artifacts/gen_action_v1/raw1_eval/eval_gen.jsonl",
    "artifacts/gen_action_v1/raw1_paraphrase/eval_gen.jsonl",
    "artifacts/gen_action_v1/raw1_abeja/train_gen.jsonl",
    "artifacts/gen_action_v1/raw1_nemoja/train_gen.jsonl",
    "artifacts/gen_action_v1/raw1_elyza/train_gen.jsonl",
]


def test_v1b_registered_and_uploads():
    assert V1B.name == "gen_action_v1b"
    assert (V1B.disk_gb, V1B.max_hours, V1B.query) == (200, 4.0, JOB.query)
    assert V1B.uploads == [*V1B_DONE_FILES, *V1_REVERIFY_INPUTS, STACKCHAN_SOURCES]


def test_v1b_starts_only_calm3_and_qwen():
    started = re.findall(r"\$VLLM serve (\S+) --port", "\n".join(V1B.steps))
    assert started == ["cyberagent/calm3-22b-chat", "Qwen/Qwen3-30B-A3B-Instruct-2507"]
    served = re.findall(r"--served-model-name (\w+)", "\n".join(V1B.steps))
    assert served == ["calm3", "qwen"]


def test_v1b_verify_after_qwen_start_and_same_tail_as_v1():
    qwen = next(i for i, s in enumerate(V1B.steps) if "serve Qwen/" in s)
    late = [i for i, s in enumerate(V1B.steps) if re.search(r"--phase (train-|eval-|re)verify", s)]
    assert len(late) == 5 + 2 + 1 and min(late) > qwen
    for w in ("abeja", "nemoja", "elyza", "calm3", "qwen"):
        assert any(
            f"--phase train-verify --config configs/action_v1_{w}.json" in s
            and f"if [ -s artifacts/gen_action_v1/raw1_{w}/train_gen.jsonl ]" in s
            for s in V1B.steps
        )
    v1_qwen = next(i for i, s in enumerate(JOB.steps) if "serve Qwen/" in s)
    assert V1B.steps[qwen - 1 :] == JOB.steps[v1_qwen - 1 :]  # disk log, Qwen3 and the tail


def test_disk_logged_before_every_model_start():
    for job in (JOB, V1B):
        for i, s in enumerate(job.steps):
            if "$VLLM serve" in s:
                assert job.steps[i - 1] == "df -h /"


def test_drop_weights_finds_the_cache_and_cannot_fail():
    drop = _drop_weights("cyberagent/calm3-22b-chat")
    assert "from huggingface_hub import constants" in drop and "HF_HUB_CACHE" in drop
    assert "HF_XET_CACHE" in drop
    assert r"find / -xdev -maxdepth 6 \( -path /proc -o -path /sys \) -prune" in drop
    assert '-name "$M" -prune -exec rm -rf {} +' in drop
    assert drop.startswith("M=models--cyberagent--calm3-22b-chat;")
    assert "/proc/[0-9]*/maps" in drop and "kill -9" in drop
    assert "df -h /" in drop and 'du -sh "$HUB" "$XET"' in drop
    assert drop.endswith("; true")
    for job in (JOB, V1B):
        drops = [s for s in job.steps if "rm -rf" in s]
        assert drops and all(s.endswith("; true") for s in drops)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
@pytest.mark.parametrize("job", [JOB, V1B], ids=lambda j: j.name)
def test_steps_parse_with_bash(job, tmp_path):
    # Each step as the runner writes it (one line, prefixed with cd); fed on stdin so that any
    # bash (Git Bash, WSL) can read it regardless of how it maps Windows paths.
    script = tmp_path / f"{job.name}.sh"
    script.write_bytes("".join(f"cd /root/work && {s}\n" for s in job.steps).encode())
    with script.open("rb") as f:
        r = subprocess.run([shutil.which("bash"), "-n"], stdin=f, capture_output=True)
    assert r.returncode == 0, r.stderr.decode(errors="replace")
