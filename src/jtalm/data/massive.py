# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Amazon MASSIVE (ja-JP, CC BY 4.0) utterances as no-action negatives.

MASSIVE is a virtual-assistant dataset (alarms, music, IoT, QA, chit-chat); its intents are not
robot actions, so rows are ``[]`` candidates for training/evaluation (not redistributed in our
Hugging Face dataset). Under schema v1 a few kept rows (bare ライト / 明るく / 音量 phrasing) can be
actions, so inherited rows are re-parsed by the v1 verifier in the data v1.0 build and v1 configs
sample no new MASSIVE negatives. Volume intents are dropped: a volume request is an action in v1.
"""

import json
import random
import re
import tarfile
import urllib.request
from pathlib import Path

MASSIVE_URL = (
    "https://amazon-massive-nlu-dataset.s3.amazonaws.com/amazon-massive-dataset-1.1.tar.gz"
)
MASSIVE_LICENSE = "CC BY 4.0"
VOLUME_INTENTS = ("audio_volume_up", "audio_volume_down", "audio_volume_mute", "audio_volume_other")
# Skip the rare utterances that talk about heads/faces so they cannot be read as robot actions.
ROBOT_WORDS = re.compile(r"(向いて|向け|うなず|頷|首を|顔を|表情)")


def download(dest_dir: Path) -> Path:
    """Download and extract only ja-JP.jsonl; returns its path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "ja-JP.jsonl"
    if out.exists():
        return out
    archive = dest_dir / "amazon-massive-dataset-1.1.tar.gz"
    if not archive.exists():
        urllib.request.urlretrieve(MASSIVE_URL, archive)
    with tarfile.open(archive) as tar:
        member = next(m for m in tar.getmembers() if m.name.endswith("/ja-JP.jsonl"))
        extracted = tar.extractfile(member)
        assert extracted is not None
        out.write_bytes(extracted.read())
    return out


def load(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [
        r for r in rows if not ROBOT_WORDS.search(r["utt"]) and r["intent"] not in VOLUME_INTENTS
    ]


def sample(rows: list[dict], partition: str, k: int, rng: random.Random) -> list[dict]:
    pool = [r for r in rows if r["partition"] == partition]
    return rng.sample(pool, k=min(k, len(pool)))
