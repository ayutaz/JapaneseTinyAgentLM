# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("sentencepiece")

from jtalm.action.schema import canonicalize, parse_output  # noqa: E402
from jtalm.model import tokenizer  # noqa: E402
from jtalm.model.data import IGNORE, Codec, collate  # noqa: E402
from jtalm.model.decode import greedy  # noqa: E402
from jtalm.model.format import ENUM_VALUES, JSON_PIECES, all_call_pieces, target_json  # noqa: E402
from jtalm.model.transformer import (  # noqa: E402
    SIZES,
    ActionLM,
    ModelConfig,
    count_params,
    make_config,
)

LOOK = [{"name": "look", "arguments": {"amount": "slight", "direction": "right"}}]
MULTI = [
    {"name": "nod", "arguments": {"count": 2}},
    {"name": "set_expression", "arguments": {"expression": "happy"}},
]
EXAMPLES = [
    ("右を少し見て", LOOK),
    ("うなずいてから笑って", MULTI),
    ("今日はいい天気だね", []),
    ("正面を向いて", [{"name": "look", "arguments": {"direction": "center", "amount": "large"}}]),
]


def test_target_json_puts_name_first_and_parses_to_the_same_calls() -> None:
    text = target_json(LOOK)
    assert text == '[{"name":"look","arguments":{"direction":"right","amount":"slight"}}]'
    assert parse_output(text).calls == canonicalize(LOOK)
    assert target_json([]) == "[]"
    center = target_json(EXAMPLES[3][1])
    assert '"amount":"normal"' in center  # canonicalized


@pytest.fixture(scope="module")
def codec(tmp_path_factory: pytest.TempPathFactory) -> Codec:
    lines = [p for p, _ in EXAMPLES] * 20 + [target_json(c) for _, c in EXAMPLES] * 20
    model = tokenizer.train(lines, 400, tmp_path_factory.mktemp("sp") / "tiny")
    return Codec(model)


def test_tokenizer_keeps_json_fragments_whole(codec: Codec) -> None:
    for _, calls in EXAMPLES:
        text = target_json(calls)
        assert codec.sp.decode(codec.sp.encode(text)) == text
    assert len(codec.sp.encode(target_json(LOOK))) == 7
    assert codec.sp.encode("[]") == [codec.sp.piece_to_id("[]")]


def test_collate_masks_the_prompt(codec: Codec) -> None:
    ids, n_prompt = codec.example(*EXAMPLES[0])
    x, y = collate([(ids, n_prompt), codec.example(*EXAMPLES[2])], codec.pad)
    assert x.shape == y.shape
    assert (y[0, : n_prompt - 1] == IGNORE).all()
    assert y[0, n_prompt - 1 : len(ids) - 1].tolist() == ids[n_prompt:]
    assert ids[-1] == codec.eos


@pytest.mark.parametrize(("size", "nominal"), [("3m", 3e6), ("5m", 5e6), ("20m", 20e6)])
def test_model_sizes_match_their_names(size: str, nominal: float) -> None:
    n = count_params(ActionLM(make_config(size, 2048)))
    assert abs(n - nominal) / nominal < 0.05
    assert size in SIZES


def test_tiny_model_overfits_and_greedy_decodes_the_targets(codec: Codec) -> None:
    torch.manual_seed(0)
    cfg = ModelConfig(vocab_size=codec.vocab_size, d_model=64, n_layers=2, n_heads=4,
                      n_kv_heads=2, d_ff=128)  # fmt: skip
    model = ActionLM(cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-3)
    x, y = collate([codec.example(p, c) for p, c in EXAMPLES], codec.pad)
    for _ in range(200):
        logits = model(x)
        loss = torch.nn.functional.cross_entropy(
            logits.flatten(0, 1), y.flatten(), ignore_index=IGNORE
        )
        opt.zero_grad()
        loss.backward()
        opt.step()
    preds = greedy(model, codec, [p for p, _ in EXAMPLES])
    for pred, (_, calls) in zip(preds, EXAMPLES, strict=True):
        assert parse_output(pred.text).calls == canonicalize(calls)
        assert 0.0 < pred.min_prob <= 1.0


def test_uploads_are_checked_before_renting(tmp_path: Path) -> None:
    from jtalm.infra.job import local_uploads
    from jtalm.infra.spec import JobSpec
    from jtalm.infra.vast import VastError

    spec = JobSpec("t", "d", "q", "img", 10, 0.1, [], uploads=["does/not/exist.jsonl"])
    with pytest.raises(VastError):
        local_uploads(spec)
    ok = JobSpec("t", "d", "q", "img", 10, 0.1, [], uploads=["pyproject.toml"])
    digest = local_uploads(ok)["pyproject.toml"]
    assert len(digest) == 64 and json.dumps(digest)


def _enumerate(grammar, codec: Codec) -> list[list[int]]:
    """All complete target token sequences the grammar allows (depth-first)."""
    done, stack = [], [[]]
    while stack:
        seq = stack.pop()
        for token in grammar.allowed(seq):
            if token == codec.eos:
                done.append(seq)
            else:
                stack.append(seq + [token])
    return done


def test_grammar_allows_exactly_the_valid_canonical_outputs(codec: Codec) -> None:
    from jtalm.action.schema import validate
    from jtalm.data.specs import all_specs
    from jtalm.model.grammar import ActionGrammar

    grammar = ActionGrammar(codec)
    outputs = [codec.sp.decode(seq) for seq in _enumerate(grammar, codec)]
    parsed = [json.loads(o) for o in outputs]
    assert all(validate(calls) == [] for calls in parsed)  # schema + no duplicates
    assert all(calls == canonicalize(calls) for calls in parsed)  # center -> normal
    singles = 5 * 3 - 2 + 4 + 3  # look (center only normal) + expressions + nod counts
    assert len(outputs) == 1 + singles + singles * (singles - 1)
    texts = set(outputs)
    for spec in all_specs():  # every label the dataset uses is reachable
        assert target_json(list(spec.label)) in texts


def test_greedy_with_grammar_always_returns_valid_json(codec: Codec) -> None:
    from jtalm.action.schema import validate
    from jtalm.model.grammar import ActionGrammar

    torch.manual_seed(0)
    cfg = ModelConfig(vocab_size=codec.vocab_size, d_model=32, n_layers=1, n_heads=2,
                      n_kv_heads=1, d_ff=64)  # fmt: skip
    model = ActionLM(cfg)  # untrained: without grammar it produces garbage
    preds = greedy(model, codec, [p for p, _ in EXAMPLES], grammar=ActionGrammar(codec))
    for pred in preds:
        calls = parse_output(pred.text).calls
        assert calls is not None and validate(calls) == []


def test_quantization_error_is_bounded_and_int4_is_coarser_than_int8() -> None:
    from jtalm.model.quantize import quantize_state, quantize_tensor

    torch.manual_seed(0)
    w = torch.randn(8, 128)
    e8 = (quantize_tensor(w, 8, 64) - w).abs()
    e4 = (quantize_tensor(w, 4, 64) - w).abs()
    step8 = w.abs().reshape(8, 2, 64).amax(-1) / 127
    assert (e8.reshape(8, 2, 64) <= step8[..., None] / 2 + 1e-6).all()  # half a step at most
    assert e4.mean() > e8.mean()
    state = {"a.weight": w, "norm.weight": torch.ones(128)}
    q, info = quantize_state(state, 4, 64)
    assert torch.equal(q["norm.weight"], state["norm.weight"])  # 1-D stays float
    assert info["artifact_bytes_estimate"] == 8 * 128 // 2 + (8 * 128 // 64) * 2 + 128 * 4


V1_TARGETS = [
    [{"name": "look", "arguments": {"direction": "right", "degrees": 45}}],
    [{"name": "turn", "arguments": {"direction": "up_left", "degrees": 180}},
     {"name": "adjust_volume", "arguments": {"direction": "down", "by": 100}}],
    [{"name": "bow", "arguments": {}}, {"name": "set_led", "arguments": {"color": "light_blue"}}],
    [{"name": "set_volume", "arguments": {"level": 0}}],
]  # fmt: skip


def test_every_call_piece_sequence_is_its_target_json() -> None:
    calls = all_call_pieces()
    assert len(calls) == len(set(calls))
    for pieces in calls:
        text = "[" + "".join(pieces) + "]"
        parsed = parse_output(text)
        assert parsed.schema_valid, text
        assert target_json(parsed.calls) == text


def test_v1_targets_keep_pieces_whole_and_fit_the_target_limit(tmp_path: Path) -> None:
    lines = [target_json(c) for c in V1_TARGETS] * 20 + ["右を向いて", "音量を上げて"] * 20
    sp = tokenizer.train(lines, 400, tmp_path / "v1").as_posix()
    codec = Codec(sp)
    for piece in (*JSON_PIECES, *ENUM_VALUES):
        assert len(codec.sp.encode(piece)) == 1, piece
    longest = target_json(V1_TARGETS[1])
    assert codec.sp.decode(codec.sp.encode(longest)) == longest
    assert len(codec.sp.encode(longest)) + 1 <= 24  # + </s>
