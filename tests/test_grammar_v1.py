# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import random

import pytest

pytest.importorskip("sentencepiece")

from jtalm.action.schema import parse_output  # noqa: E402
from jtalm.model import tokenizer  # noqa: E402
from jtalm.model.data import Codec  # noqa: E402
from jtalm.model.format import all_call_pieces, target_json  # noqa: E402
from jtalm.model.grammar import ActionGrammar  # noqa: E402

SAMPLE = [[{"name": "look", "arguments": {"direction": "right", "degrees": 45}}],
          [{"name": "bow", "arguments": {}}], []]  # fmt: skip


@pytest.fixture(scope="module")
def grammar(tmp_path_factory: pytest.TempPathFactory) -> ActionGrammar:
    lines = [target_json(c) for c in SAMPLE] * 20 + ["右を向いて", "こんにちは"] * 20
    return ActionGrammar(Codec(tokenizer.train(lines, 400, tmp_path_factory.mktemp("g") / "t")))


def walk(g: ActionGrammar, rng: random.Random) -> list[int]:
    ids: list[int] = []
    while True:
        options = g.allowed(ids)
        assert options, f"dead end after {ids}"
        assert options == sorted(options)
        nxt = rng.choice(options)
        if nxt == g.eos:
            return ids
        ids.append(nxt)


def test_random_walks_always_parse_and_never_duplicate(grammar: ActionGrammar) -> None:
    rng = random.Random(0)
    sp = grammar.codec.sp
    for _ in range(3000):
        text = sp.decode(walk(grammar, rng))
        parsed = parse_output(text)
        assert parsed.schema_valid, (text, parsed.errors)


def test_every_single_call_is_reachable(grammar: ActionGrammar) -> None:
    for pieces in all_call_pieces():
        ids = [grammar.id["["]]
        for piece in pieces:
            assert grammar.id[piece] in grammar.allowed(ids), pieces
            ids.append(grammar.id[piece])
        assert grammar.id["]"] in grammar.allowed(ids)


@pytest.mark.parametrize("pieces", [
    ('{"name":"bow","arguments":{}}',),
    ('{"name":"look","arguments":{"direction":"', "center", '","amount":"', "normal", '"}}'),
    ('{"name":"look","arguments":{"direction":"', "right", '","degrees":', "4", "5", "}}"),
    ('{"name":"set_volume","arguments":{"level":', "1", "0", "0", "}}"),
    ('{"name":"set_volume","arguments":{"level":', "0", "}}"),
    ('{"name":"nod","arguments":{"count":', "5", "}}"),
])  # fmt: skip
def test_second_call_cannot_repeat_the_first(grammar: ActionGrammar, pieces: tuple) -> None:
    ids = [grammar.id["["], *(grammar.id[p] for p in pieces), grammar.id[","]]
    for piece in pieces:
        options = grammar.allowed(ids)
        if grammar.id[piece] not in options:
            return  # the duplicate path was cut before its end
        ids.append(grammar.id[piece])
    pytest.fail(f"the grammar allowed a duplicate of {pieces}")


def test_second_number_avoids_only_the_first_calls_value(grammar: ActionGrammar) -> None:
    head = '{"name":"set_volume","arguments":{"level":'
    first = (head, "1", "0", "}}")  # set_volume level 10
    ids = [grammar.id["["], *(grammar.id[p] for p in first), grammar.id[","], grammar.id[head]]
    ids.append(grammar.id["1"])
    # 1 itself is not a duplicate; after "1" each digit still reaches a level other than 10
    # ("0" via 100, "1".."9" via 11..19).
    expected = sorted([grammar.id[d] for d in "0123456789"] + [grammar.id["}}"]])
    assert grammar.allowed(ids) == expected
    ids.append(grammar.id["0"])
    assert grammar.allowed(ids) == [grammar.id["0"]]  # only 100 remains; "}}" would repeat 10


def test_numbers_have_no_leading_zero_and_stay_in_range(grammar: ActionGrammar) -> None:
    head = grammar.id['{"name":"look","arguments":{"direction":"']
    ids = [grammar.id["["], head, grammar.id["right"], grammar.id['","degrees":']]
    assert grammar.id["0"] not in grammar.allowed(ids)  # degrees start at 1
    ids += [grammar.id["1"], grammar.id["8"]]
    assert grammar.allowed(ids) == sorted([grammar.id["0"], grammar.id["}}"]])  # 180 or 18


def test_training_text_and_decoding_pieces_encode_to_the_same_ids(grammar: ActionGrammar) -> None:
    sp = grammar.codec.sp
    for pieces in all_call_pieces():
        assert sp.encode("".join(pieces)) == [grammar.id[p] for p in pieces], pieces
    first = {"name": "bow", "arguments": {}}
    second = {"name": "look", "arguments": {"direction": "right", "degrees": 45}}
    pieces1 = next(p for p in all_call_pieces() if p == ('{"name":"bow","arguments":{}}',))
    pieces2 = next(
        p for p in all_call_pieces()
        if p[:3] == ('{"name":"look","arguments":{"direction":"', "right", '","degrees":')
        and "".join(p[3:]) == "45}}"
    )  # fmt: skip
    expected = [grammar.id["["], *(grammar.id[p] for p in pieces1), grammar.id[","],
                *(grammar.id[p] for p in pieces2), grammar.id["]"]]  # fmt: skip
    assert grammar.codec.sp.encode(target_json([first, second])) == expected
