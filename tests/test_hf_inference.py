# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import random

import pytest

pytest.importorskip("torch")
pytest.importorskip("sentencepiece")

from jtalm.model import hf_inference, tokenizer  # noqa: E402
from jtalm.model.data import Codec  # noqa: E402
from jtalm.model.format import all_call_pieces, target_json  # noqa: E402
from jtalm.model.grammar import ActionGrammar  # noqa: E402


def test_call_pieces_equal_the_project_table() -> None:
    assert hf_inference.call_pieces() == all_call_pieces()


def test_standalone_grammar_equals_the_project_grammar(tmp_path) -> None:
    lines = [target_json([{"name": "bow", "arguments": {}}])] * 20 + ["右を向いて"] * 20
    codec = Codec(tokenizer.train(lines, 400, tmp_path / "t"))
    ours, theirs = ActionGrammar(codec), hf_inference.Grammar(codec.sp)
    rng = random.Random(1)
    for _ in range(500):
        ids: list[int] = []
        while True:
            options = ours.allowed(ids)
            assert theirs.allowed(ids) == options, ids
            nxt = rng.choice(options)
            if nxt == ours.eos:
                break
            ids.append(nxt)
