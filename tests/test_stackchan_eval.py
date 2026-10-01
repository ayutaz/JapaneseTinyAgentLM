# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json

from jtalm.data.stackchan_eval import build
from jtalm.eval.cases import load_cases


def write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def test_build_merges_sources_paraphrases_and_overrides(tmp_path) -> None:
    src = tmp_path / "sources.jsonl"
    write(src, [{"id": "sc-001", "text": "左に頭を回して。", "source_url": "u", "license": "MIT",
                 "kind": "verbatim"},
                {"id": "sc-002", "text": "寝室のライトをつけて。", "source_url": "u", "license": "MIT",  # noqa: E501
                 "kind": "verbatim"}])  # fmt: skip
    look = [{"name": "look", "arguments": {"direction": "left", "amount": "normal"}}]
    rev = tmp_path / "rev.jsonl"
    write(rev, [{"id": "sc-001", "file": str(src), "verified": look},
                {"id": "sc-002", "file": str(src), "verified": look}])  # fmt: skip
    para = tmp_path / "para.jsonl"
    write(
        para,
        [
            {
                "spec_id": "v1.single.turn.right.slight",
                "category": "single",
                "label": [
                    {"name": "turn", "arguments": {"direction": "right", "amount": "slight"}}
                ],
                "text": "もうちょい右",
                "language": "ja",
                "generator": "llm-jp/x",
                "verified": [
                    {"name": "turn", "arguments": {"direction": "right", "amount": "slight"}}
                ],
            }
        ],
    )
    over = tmp_path / "over.jsonl"
    write(over, [{"id": "sc-002", "expected": []}])
    out = tmp_path / "out"
    stats = build(src, rev, para, over, out, n_paraphrase=40, seed=0)
    cases = {c.id: c for c in load_cases(out / "eval.jsonl")}
    assert cases["sc-001"].expected == look and cases["sc-001"].source == "verbatim:u"
    assert cases["sc-002"].expected == [] and cases["sc-002"].category == "no_action"
    assert len([c for c in cases.values() if c.source.startswith("paraphrase:")]) == 1
    assert stats == {"verbatim": 2, "user": 0, "paraphrase": 1, "overridden": 1}
    assert "寝室のライトをつけて。" in (out / "review.md").read_text("utf-8")
