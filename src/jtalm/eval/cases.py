# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Evaluation cases for the Action LM.

Accepted formats:
- TinyLM-Bench style JSON: ``{"cases": [{"id", "language", "prompt", "expected", "category"}]}``
- JSON Lines with one case object per line (the project's dataset format).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jtalm.action.schema import Call

CATEGORIES = ("single", "multi_action", "negation", "no_action", "correction")


@dataclass(frozen=True)
class EvalCase:
    id: str
    prompt: str
    expected: list[Call]
    category: str
    language: str = "ja"
    pair_id: str | None = None
    source: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvalCase":
        return cls(
            id=d["id"],
            prompt=d["prompt"],
            expected=d["expected"],
            category=d["category"],
            language=d.get("language", "ja"),
            pair_id=d.get("pair_id"),
            source=d.get("source"),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "language": self.language,
            "category": self.category,
            "prompt": self.prompt,
            "expected": self.expected,
        }
        if self.pair_id is not None:
            d["pair_id"] = self.pair_id
        if self.source is not None:
            d["source"] = self.source
        return d


def load_cases(path: str | Path) -> list[EvalCase]:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".jsonl":
        return [EvalCase.from_dict(json.loads(line)) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    items = data["cases"] if isinstance(data, dict) else data
    return [EvalCase.from_dict(item) for item in items]


def write_cases(path: str | Path, cases: list[EvalCase]) -> None:
    lines = (json.dumps(c.to_dict(), ensure_ascii=False) for c in cases)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
