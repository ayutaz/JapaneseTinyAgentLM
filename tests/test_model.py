import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("sentencepiece")

from jtalm.action.schema import canonicalize, parse_output  # noqa: E402
from jtalm.model import tokenizer  # noqa: E402
from jtalm.model.data import IGNORE, Codec, collate  # noqa: E402
from jtalm.model.decode import greedy  # noqa: E402
from jtalm.model.format import target_json  # noqa: E402
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
