# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Export an Action LM checkpoint and its tokenizer to one binary for the C runtime (M6).

    uv run --group train python -m jtalm.model.export \
        --ckpt runs/.../3m/best.pt --tokenizer tokenizer/out/action_v0_sp2048.model \
        --bits 0 8 4 --out runs/local/export

writes ``<slug>_fp32.jtlm``, ``<slug>_q8_g64.jtlm``, ``<slug>_q4_g64.jtlm``. ``runtime/host``
loads them; ``jtalm.model.parity`` compares the C runtime with ``jtalm.model.decode``.

File layout (little-endian; every section and tensor starts on a 32-byte boundary, padded with
zeros):

    header (128 bytes)
      0  char[4]  magic "JTLM"
      4  u32      format version (1)
      8  u32 x7   vocab_size, d_model, n_layers, n_heads, n_kv_heads, d_ff, max_seq_len
     36  f32 x2   rope_theta, norm_eps
     44  u32 x2   quant bits (0 = fp32, 8, 4), group size (0 for fp32)
     52  u32 x4   tokenizer offset, tokenizer bytes, weights offset, weights bytes
     68  u32 x2   rope table offset (cos then sin, f32 [max_seq_len][head_dim/2] each), bytes
     76  u8[32]   sha256 of the SentencePiece model file
    108  u8[20]   reserved (zero)

    tokenizer section
      u32 x6   n_pieces, unk, bos, eos, pad, act id; then u32 x2 out id, flags
               (flags: 1 add_dummy_prefix, 2 remove_extra_whitespaces, 4 escape_whitespaces,
               8 byte_fallback)
      u32 x6   offsets (from the section start) of scores, types, piece offsets, piece bytes,
               sorted ids, charsmap; then u32 x2 piece bytes size, charsmap size
      u16[257] first-byte buckets into sorted ids (ids of pieces starting with byte b are
               sorted_ids[bucket[b]:bucket[b+1]]); u16 pad; u16[256] byte-piece ids (<0xXX>)
      f32[n] scores, u8[n] types (SentencePiece enum: 1 normal, 2 unknown, 3 control,
               4 user-defined, 5 unused, 6 byte), u32[n+1] piece offsets, piece bytes,
               u16[n] ids sorted by piece bytes, precompiled charsmap (verbatim from the model's
               normalizer_spec: u32 trie size, Darts-clone double array, NUL-separated strings)

    weights section, in this order (tied: the embedding is also the output head):
      embed [vocab, d_model]
      per layer: attn_norm [d], wq, wk, wv, wo, mlp_norm [d], w1 (gate), w3 (up), w2 (down)
      norm [d]

A matrix [rows, cols] is f32 row-major when bits is 0. Otherwise it is the integer codes
(int8, or int4 two per byte: element 2i in the low nibble, 2i+1 in the high nibble, two's
complement) followed by one fp16 scale per group of ``group`` consecutive values of a row
(rows * cols / group scales, row-major), each part 32-byte aligned. RMSNorm weights stay f32.

Codes are exactly those of ``jtalm.model.quantize.quantize_tensor``: symmetric, scale =
max|w| / qmax in f32, code = clamp(round(w / scale), -qmax - 1, qmax) with ``torch.round``
(round half to even). Only the stored scale is rounded to fp16, so a dequantized weight is
code * f32(fp16 scale), which is exact in f32 (an 8-bit code times an 11-bit mantissa).
"""

import argparse
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch

from jtalm.model.transformer import ModelConfig, rope_tables

MAGIC = b"JTLM"
VERSION = 1
HEADER_BYTES = 128
ALIGN = 32
HEADER = struct.Struct("<4sI7I2f2I4I2I32s20x")
TOK_HEAD = struct.Struct("<8I6I2I")
FLAG_DUMMY_PREFIX, FLAG_REMOVE_WS, FLAG_ESCAPE_WS, FLAG_BYTE_FALLBACK = 1, 2, 4, 8
NORMAL, UNKNOWN, CONTROL, USER_DEFINED, UNUSED, BYTE = 1, 2, 3, 4, 5, 6
UNK_SURFACE = " \N{DOUBLE QUESTION MARK} ".encode()  # SentencePiece's default unk_surface
LAYER_TENSORS = ("attn_norm", "attn.wq", "attn.wk", "attn.wv", "attn.wo",
                 "mlp_norm", "mlp.w1", "mlp.w3", "mlp.w2")  # fmt: skip


def _align(n: int) -> int:
    return (n + ALIGN - 1) // ALIGN * ALIGN


def _pad(buf: bytearray) -> None:
    buf.extend(b"\0" * (_align(len(buf)) - len(buf)))


# -- SentencePiece model proto (read without protobuf) --------------------------------------------


def _varint(b: bytes, i: int) -> tuple[int, int]:
    r = shift = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << shift
        shift += 7
        if c < 0x80:
            return r, i


def _fields(b: bytes) -> list[tuple[int, Any]]:
    out, i = [], 0
    while i < len(b):
        key, i = _varint(b, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            v, i = _varint(b, i)
        elif wire == 1:
            v, i = b[i : i + 8], i + 8
        elif wire == 5:
            v, i = b[i : i + 4], i + 4
        elif wire == 2:
            n, i = _varint(b, i)
            v, i = b[i : i + n], i + n
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        out.append((field, v))
    return out


@dataclass
class SpModel:
    pieces: list[bytes]
    scores: list[float]
    types: list[int]
    model_type: int
    byte_fallback: bool
    add_dummy_prefix: bool
    remove_extra_whitespaces: bool
    escape_whitespaces: bool
    charsmap: bytes
    unk_surface: bytes
    has_denormalizer: bool


def read_sp_model(path: Path) -> SpModel:
    """The fields of ``sentencepiece_model.proto`` that encoding and decoding depend on."""
    pieces, scores, types = [], [], []
    trainer: dict[int, Any] = {}
    norm: dict[int, Any] = {}
    denorm: dict[int, Any] = {}
    for field, v in _fields(path.read_bytes()):
        if field == 1:
            d = dict(_fields(v))
            pieces.append(d[1])
            scores.append(struct.unpack("<f", d[2])[0] if 2 in d else 0.0)
            types.append(d.get(3, NORMAL))
        elif field == 2:
            trainer = dict(_fields(v))
        elif field == 3:
            norm = dict(_fields(v))
        elif field == 5:
            denorm = dict(_fields(v))
    return SpModel(
        pieces=pieces,
        scores=scores,
        types=types,
        model_type=trainer.get(3, 1),
        byte_fallback=bool(trainer.get(35, 0)),
        add_dummy_prefix=bool(norm.get(3, 1)),
        remove_extra_whitespaces=bool(norm.get(4, 1)),
        escape_whitespaces=bool(norm.get(5, 1)),
        charsmap=norm.get(2, b""),
        unk_surface=trainer.get(44, UNK_SURFACE),
        has_denormalizer=bool(denorm.get(2, b"")),
    )


def tokenizer_section(path: Path) -> bytes:
    sp = read_sp_model(path)
    if sp.model_type != 1:
        raise ValueError(f"{path.name}: only unigram models are supported")
    if sp.has_denormalizer:
        raise ValueError(f"{path.name}: denormalizer rules are not supported")
    if sp.unk_surface != UNK_SURFACE:
        raise ValueError(f"{path.name}: a custom unk_surface is not supported")
    n = len(sp.pieces)
    if n >= 1 << 16:
        raise ValueError("vocabulary too large for u16 ids")

    def one(kind: int) -> int:
        ids = [i for i, t in enumerate(sp.types) if t == kind]
        if len(ids) != 1:
            raise ValueError(f"expected one piece of type {kind}, found {len(ids)}")
        return ids[0]

    def by_piece(piece: str) -> int:
        return sp.pieces.index(piece.encode())

    unk = one(UNKNOWN)
    bos, eos, pad = by_piece("<s>"), by_piece("</s>"), by_piece("<pad>")
    act, out = by_piece("<act>"), by_piece("<out>")
    flags = (
        FLAG_DUMMY_PREFIX * sp.add_dummy_prefix
        | FLAG_REMOVE_WS * sp.remove_extra_whitespaces
        | FLAG_ESCAPE_WS * sp.escape_whitespaces
        | FLAG_BYTE_FALLBACK * sp.byte_fallback
    )
    byte_ids = [0xFFFF] * 256
    for i, (p, t) in enumerate(zip(sp.pieces, sp.types, strict=True)):
        if t == BYTE:
            byte_ids[int(p[3:5], 16)] = i
    if sp.byte_fallback and 0xFFFF in byte_ids:
        raise ValueError("byte_fallback is set but some <0xXX> pieces are missing")

    order = sorted(range(n), key=lambda i: sp.pieces[i])
    buckets = [0] * 257
    for i in order:
        if sp.pieces[i]:
            buckets[sp.pieces[i][0] + 1] += 1
    empty = sum(1 for p in sp.pieces if not p)
    buckets[0] = empty  # empty pieces sort first and belong to no bucket
    for b in range(256):
        buckets[b + 1] += buckets[b]

    blob = b"".join(sp.pieces)
    offsets = np.cumsum([0] + [len(p) for p in sp.pieces]).astype("<u4")
    parts = [
        np.asarray(sp.scores, dtype="<f4").tobytes(),
        bytes(sp.types),
        offsets.tobytes(),
        blob,
        np.asarray(order, dtype="<u2").tobytes(),
        sp.charsmap,
    ]
    fixed = TOK_HEAD.size + 2 * 257 + 2 + 2 * 256
    pos, starts = _align(fixed), []
    for part in parts:
        starts.append(pos)
        pos = _align(pos + len(part))
    buf = bytearray(
        TOK_HEAD.pack(n, unk, bos, eos, pad, act, out, flags, *starts, len(blob), len(sp.charsmap))
    )
    buf += np.asarray(buckets, dtype="<u2").tobytes() + b"\0\0"
    buf += np.asarray(byte_ids, dtype="<u2").tobytes()
    for start, part in zip(starts, parts, strict=True):
        buf.extend(b"\0" * (start - len(buf)))
        buf += part
    _pad(buf)
    return bytes(buf)


# -- weights --------------------------------------------------------------------------------------


def quantize_codes(w: torch.Tensor, bits: int, group: int) -> tuple[np.ndarray, np.ndarray]:
    """Integer codes and fp16 scales; the codes equal ``quantize.quantize_tensor``'s."""
    rows, cols = w.shape
    if cols % group:
        raise ValueError(f"last dimension {cols} is not a multiple of group {group}")
    qmax = 2 ** (bits - 1) - 1
    g = w.float().reshape(rows, cols // group, group)
    scale = g.abs().amax(dim=-1, keepdim=True).clamp(min=1e-12) / qmax
    q = torch.clamp(torch.round(g / scale), -qmax - 1, qmax)
    scale16 = scale.squeeze(-1).to(torch.float16)
    if not torch.isfinite(scale16).all():
        raise ValueError("a group scale does not fit in fp16")
    return q.reshape(rows, cols).to(torch.int8).numpy(), scale16.numpy()


def pack_int4(q: np.ndarray) -> np.ndarray:
    u = (q.astype(np.int16) & 0xF).astype(np.uint8).reshape(-1, 2)
    return u[:, 0] | (u[:, 1] << 4)


def unpack_int4(b: np.ndarray, n: int) -> np.ndarray:
    lo, hi = (b & 0xF).astype(np.int8), (b >> 4).astype(np.int8)
    q = np.stack([lo, hi], axis=-1).reshape(-1)[:n]
    return np.where(q > 7, q - 16, q).astype(np.int8)


def _matrix_bytes(w: torch.Tensor, bits: int, group: int) -> bytes:
    if bits == 0:
        return w.float().contiguous().numpy().astype("<f4").tobytes()
    q, scale = quantize_codes(w, bits, group)
    codes = q.tobytes() if bits == 8 else pack_int4(q).tobytes()
    buf = bytearray(codes)
    _pad(buf)
    buf += scale.astype("<f2").tobytes()
    return bytes(buf)


def tensor_order(cfg: ModelConfig) -> list[str]:
    names = ["embed.weight"]
    for i in range(cfg.n_layers):
        names += [f"blocks.{i}.{t}.weight" for t in LAYER_TENSORS]
    return [*names, "norm.weight"]


def weights_section(state: dict[str, torch.Tensor], cfg: ModelConfig, bits: int, group: int):
    buf = bytearray()
    for name in tensor_order(cfg):
        w = state[name]
        buf += _matrix_bytes(w, bits, group) if w.dim() == 2 else w.float().numpy().tobytes()
        _pad(buf)
    return bytes(buf)


def rope_section(cfg: ModelConfig) -> bytes:
    """The f32 cos / sin tables of ``transformer.rope_tables``, so C needs no pow/cos/sin."""
    cos, sin = rope_tables(cfg)
    return cos.numpy().astype("<f4").tobytes() + sin.numpy().astype("<f4").tobytes()


def export(
    state: dict[str, torch.Tensor],
    cfg: ModelConfig,
    tokenizer: Path,
    out: Path,
    bits: int = 0,
    group: int = 64,
) -> dict[str, Any]:
    if bits not in (0, 8, 4):
        raise ValueError(f"bits must be 0, 8, or 4, not {bits}")
    group = group if bits else 0
    tok = tokenizer_section(tokenizer)
    rope = rope_section(cfg)
    weights = weights_section(state, cfg, bits, group)
    tok_off = HEADER_BYTES
    rope_off = _align(tok_off + len(tok))
    w_off = _align(rope_off + len(rope))
    sha = hashlib.sha256(tokenizer.read_bytes()).digest()
    header = HEADER.pack(
        MAGIC, VERSION,
        cfg.vocab_size, cfg.d_model, cfg.n_layers, cfg.n_heads, cfg.n_kv_heads, cfg.d_ff,
        cfg.max_seq_len, cfg.rope_theta, cfg.norm_eps, bits, group,
        tok_off, len(tok), w_off, len(weights), rope_off, len(rope), sha,
    )  # fmt: skip
    buf = bytearray(header)
    for off, part in ((tok_off, tok), (rope_off, rope), (w_off, weights)):
        buf.extend(b"\0" * (off - len(buf)))
        buf += part
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(buf))
    return {"file": str(out), "bytes": len(buf), "bits": bits, "group": group,
            "tokenizer_bytes": len(tok), "weights_bytes": len(weights)}  # fmt: skip


# -- reading back (tests and the parity reference) ------------------------------------------------


@dataclass
class Exported:
    cfg: ModelConfig
    bits: int
    group: int
    tokenizer_sha256: str
    state: dict[str, torch.Tensor]  # dequantized f32 weights
    raw: bytes


def read_export(path: Path) -> Exported:
    raw = path.read_bytes()
    h = HEADER.unpack_from(raw, 0)
    magic, version = h[0], h[1]
    if magic != MAGIC or version != VERSION:
        raise ValueError(f"{path}: not a JTLM v{VERSION} file")
    vocab, d, n_layers, n_heads, n_kv, d_ff, max_seq = h[2:9]
    theta, eps, bits, group = h[9:13]
    _tok_off, _tok_len, w_off, _w_len = h[13:17]
    cfg = ModelConfig(vocab_size=vocab, d_model=d, n_layers=n_layers, n_heads=n_heads,
                      n_kv_heads=n_kv, d_ff=d_ff, max_seq_len=max_seq,
                      rope_theta=theta, norm_eps=eps)  # fmt: skip
    hd = cfg.head_dim
    shapes = {"attn.wq": (n_heads * hd, d), "attn.wk": (n_kv * hd, d), "attn.wv": (n_kv * hd, d),
              "attn.wo": (d, n_heads * hd), "mlp.w1": (d_ff, d), "mlp.w3": (d_ff, d),
              "mlp.w2": (d, d_ff)}  # fmt: skip
    state: dict[str, torch.Tensor] = {}
    pos = w_off
    for name in tensor_order(cfg):
        key = name.split(".", 2)[-1].removesuffix(".weight") if name.startswith("blocks") else ""
        if name == "embed.weight":
            shape: tuple[int, ...] = (vocab, d)
        elif key in shapes:
            shape = shapes[key]
        else:
            shape = (d,)
        n = int(np.prod(shape))
        if len(shape) == 1 or bits == 0:
            w = np.frombuffer(raw, "<f4", n, pos).copy()
            pos = _align(pos + 4 * n)
        else:
            if bits == 8:
                q = np.frombuffer(raw, np.int8, n, pos)
                pos = _align(pos + n)
            else:
                q = unpack_int4(np.frombuffer(raw, np.uint8, n // 2, pos), n)
                pos = _align(pos + n // 2)
            scale = np.frombuffer(raw, "<f2", n // group, pos).astype(np.float32)
            pos = _align(pos + 2 * (n // group))
            w = q.astype(np.float32).reshape(-1, group) * scale[:, None]
        state[name] = torch.from_numpy(np.ascontiguousarray(w, dtype=np.float32).reshape(shape))
    return Exported(cfg, bits, group, h[19].hex(), state, raw)


def export_name(ckpt: Path, bits: int, group: int) -> str:
    slug = ckpt.parent.name if ckpt.stem == "best" else f"{ckpt.parent.name}-{ckpt.stem}"
    return f"{slug}_fp32.jtlm" if bits == 0 else f"{slug}_q{bits}_g{group}.jtlm"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--bits", type=int, nargs="+", default=[0, 8, 4])
    parser.add_argument("--group", type=int, default=64)
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    args = parser.parse_args(argv)

    from jtalm.model.evaluate import load_model

    model, state = load_model(args.ckpt, torch.device("cpu"))
    if state["tokenizer_sha256"] != hashlib.sha256(args.tokenizer.read_bytes()).hexdigest():
        raise SystemExit(f"{args.ckpt}: tokenizer sha256 does not match {args.tokenizer}")
    for bits in args.bits:
        out = args.out / export_name(args.ckpt, bits, args.group)
        info = export(state["state_dict"], model.cfg, args.tokenizer, out, bits, args.group)
        print(json.dumps(info))


if __name__ == "__main__":
    main()
