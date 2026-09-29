import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("sentencepiece")
np = pytest.importorskip("numpy")

from jtalm.model import tokenizer  # noqa: E402
from jtalm.model.data import Codec  # noqa: E402
from jtalm.model.decode import greedy  # noqa: E402
from jtalm.model.export import (  # noqa: E402
    HEADER,
    TOK_HEAD,
    export,
    pack_int4,
    quantize_codes,
    read_export,
    read_sp_model,
    tokenizer_section,
    unpack_int4,
)
from jtalm.model.format import target_json  # noqa: E402
from jtalm.model.grammar import ActionGrammar  # noqa: E402
from jtalm.model.quantize import quantize_tensor  # noqa: E402
from jtalm.model.transformer import ActionLM, ModelConfig  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ["右を少し見て", "うなずいてから笑って", "今日はいい天気だね", "正面を向いて",
           "ＡＢＣ　１２３ look up", "  左を　見て  "]  # fmt: skip
LOOK = [{"name": "look", "arguments": {"direction": "right", "amount": "slight"}}]


@pytest.fixture(scope="module")
def sp_model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    lines = PROMPTS[:4] * 20 + [target_json(LOOK), target_json([])] * 20
    return tokenizer.train(lines, 400, tmp_path_factory.mktemp("sp") / "tiny")


@pytest.fixture(scope="module")
def model(sp_model: Path) -> ActionLM:
    torch.manual_seed(0)
    codec = Codec(sp_model)
    cfg = ModelConfig(vocab_size=codec.vocab_size, d_model=64, n_layers=2, n_heads=4,
                      n_kv_heads=2, d_ff=128, max_seq_len=64)  # fmt: skip
    return ActionLM(cfg).eval()


def test_sp_model_reader_matches_sentencepiece(sp_model: Path) -> None:
    sp = Codec(sp_model).sp
    m = read_sp_model(sp_model)
    assert len(m.pieces) == sp.get_piece_size()
    for i, (piece, score, kind) in enumerate(zip(m.pieces, m.scores, m.types, strict=True)):
        assert piece.decode() == sp.id_to_piece(i)
        assert score == pytest.approx(sp.get_score(i))
        assert (kind == 3) == sp.is_control(i)
        assert (kind == 6) == sp.is_byte(i)
        assert (kind == 2) == sp.is_unknown(i)
    assert m.byte_fallback and not m.add_dummy_prefix and m.remove_extra_whitespaces
    assert len(m.charsmap) > 1000  # nmt_nfkc precompiled charsmap


def test_tokenizer_section_buckets_cover_every_piece(sp_model: Path) -> None:
    sec = tokenizer_section(sp_model)
    head = TOK_HEAD.unpack_from(sec, 0)
    n, off_bytes, off_sorted = head[0], head[11], head[12]
    buckets = np.frombuffer(sec, "<u2", 257, TOK_HEAD.size)
    offsets = np.frombuffer(sec, "<u4", n + 1, head[10])
    order = np.frombuffer(sec, "<u2", n, off_sorted)
    assert sorted(order.tolist()) == list(range(n))
    for i in range(n):
        piece = sec[off_bytes + offsets[i] : off_bytes + offsets[i + 1]]
        b = piece[0]
        assert i in order[buckets[b] : buckets[b + 1]].tolist()


def test_int4_packing_round_trips() -> None:
    q = np.array([-8, 7, 0, -1, 3, -5, 1, 6], dtype=np.int8)
    assert unpack_int4(pack_int4(q), len(q)).tolist() == q.tolist()
    assert pack_int4(np.array([1, -1], dtype=np.int8)).tolist() == [0xF1]  # low nibble first


@pytest.mark.parametrize("bits", [8, 4])
def test_codes_equal_fake_quantization(bits: int) -> None:
    torch.manual_seed(1)
    w = torch.randn(8, 128) * 0.05
    q, scale16 = quantize_codes(w, bits, 64)
    fake = quantize_tensor(w, bits, 64)
    qmax = 2 ** (bits - 1) - 1
    scale32 = w.reshape(8, 2, 64).abs().amax(-1).clamp(min=1e-12) / qmax
    expected = torch.from_numpy(q.astype(np.float32)).reshape(8, 2, 64) * scale32[..., None]
    assert torch.equal(expected.reshape(8, 128), fake)  # same integer codes as quantize.py
    assert q.min() >= -qmax - 1 and q.max() <= qmax
    assert np.allclose(scale16.astype(np.float32), scale32.numpy(), rtol=2**-10)


def test_fp32_export_round_trips(tmp_path: Path, sp_model: Path, model: ActionLM) -> None:
    out = tmp_path / "m.jtlm"
    info = export(model.state_dict(), model.cfg, sp_model, out)
    assert info["bytes"] == out.stat().st_size
    header = HEADER.unpack_from(out.read_bytes(), 0)
    assert header[0] == b"JTLM" and header[1] == 1 and header[11] == 0
    ex = read_export(out)
    assert ex.cfg.to_dict() == {**model.cfg.to_dict(), "norm_eps": ex.cfg.norm_eps}
    assert ex.cfg.norm_eps == pytest.approx(model.cfg.norm_eps)
    assert ex.tokenizer_sha256 == Codec(sp_model).sha256
    assert set(ex.state) == set(model.state_dict())
    for k, v in model.state_dict().items():
        assert torch.equal(ex.state[k], v), k


@pytest.mark.parametrize("bits", [8, 4])
def test_quantized_export_matches_codes(tmp_path: Path, sp_model: Path, model: ActionLM,
                                        bits: int) -> None:  # fmt: skip
    out = tmp_path / f"q{bits}.jtlm"
    export(model.state_dict(), model.cfg, sp_model, out, bits=bits, group=64)
    ex = read_export(out)
    assert (ex.bits, ex.group) == (bits, 64)
    for name, w in model.state_dict().items():
        if w.dim() == 1:
            assert torch.equal(ex.state[name], w)
            continue
        q, scale16 = quantize_codes(w, bits, 64)
        deq = q.astype(np.float32).reshape(-1, 64) * scale16.astype(np.float32).reshape(-1, 1)
        assert np.array_equal(ex.state[name].numpy().reshape(-1, 64), deq), name
    sizes = {0: 4.0, 8: 1 + 2 / 64, 4: 0.5 + 2 / 64}
    n2d = sum(w.numel() for w in model.state_dict().values() if w.dim() == 2)
    assert out.stat().st_size < n2d * sizes[bits] + 400_000  # plus tokenizer, norms, rope, padding


def _compiler() -> str | None:
    return shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")


@pytest.mark.skipif(_compiler() is None, reason="no C compiler on PATH")
def test_c_runtime_matches_python(tmp_path: Path, sp_model: Path, model: ActionLM) -> None:
    exe = tmp_path / "jtalm"
    src = ROOT / "runtime/host"
    subprocess.run(
        [_compiler(), "-O1", "-std=c11", "-ffp-contract=off", "-o", str(exe),
         *[str(src / f) for f in ("model.c", "tokenizer.c", "grammar.c", "main.c")], "-lm"],
        check=True,
    )  # fmt: skip
    codec = Codec(sp_model)
    out = tmp_path / "m.jtlm"
    export(model.state_dict(), model.cfg, sp_model, out)
    inp = tmp_path / "prompts.txt"
    inp.write_bytes(("\n".join(PROMPTS) + "\n").encode())

    def run(*flags: str) -> list:
        proc = subprocess.run([str(exe), "-m", str(out), "-i", str(inp), *flags],
                              check=True, capture_output=True)  # fmt: skip
        return [json.loads(x) for x in proc.stdout.decode().split("\n") if x.strip()]

    assert run("--tokenize") == [codec.sp.encode(p) for p in PROMPTS]
    for flags, grammar in (((), None), (("--grammar",), ActionGrammar(codec))):
        py = greedy(model, codec, PROMPTS, grammar=grammar)
        c = run(*flags)
        assert [r["ids"] for r in c] == [list(p.ids) for p in py]
        assert [r["output"] for r in c] == [p.text for p in py]
        for r, p in zip(c, py, strict=True):
            assert r["min_prob"] == pytest.approx(p.min_prob, abs=1e-4)


def test_header_layout_is_128_bytes() -> None:
    assert HEADER.size == 128
    assert struct.calcsize("<8I6I2I") == TOK_HEAD.size == 64
