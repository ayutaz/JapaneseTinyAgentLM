"""Train and compare SentencePiece tokenizers for the Action LM (M4 step 2).

    uv run --group train python -m jtalm.model.tokenizer --vocab 2048 4096 8192

Training text: train + validation prompts, their targets (``jtalm.model.format.target_json``),
and the MASSIVE ja-JP ``train`` partition (CC BY 4.0). The evaluation set is not used.
Selection metrics use the validation prompts and the MASSIVE ``dev`` partition, which no other
step uses, so they approximate unseen human-written Japanese.
"""

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

import sentencepiece as spm

from jtalm.data import massive
from jtalm.eval.cases import load_cases
from jtalm.infra.env import PROJECT_ROOT
from jtalm.model.format import ACT, ENUM_VALUES, JSON_PIECES, OUT, target_json

UNK_ID, BOS_ID, EOS_ID, PAD_ID = 0, 1, 2, 3
EMBED_DIMS = (192, 256, 384)


def train_text(data_dir: Path, massive_rows: list[dict]) -> list[str]:
    cases = load_cases(data_dir / "train.jsonl") + load_cases(data_dir / "val.jsonl")
    lines = [c.prompt for c in cases] + [target_json(c.expected) for c in cases]
    lines += [r["utt"] for r in massive_rows if r["partition"] == "train"]
    return lines


def train(lines: list[str], vocab_size: int, prefix: Path) -> Path:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    spm.SentencePieceTrainer.train(
        sentence_iterator=iter(lines),
        model_prefix=str(prefix),
        model_type="unigram",
        vocab_size=vocab_size,
        hard_vocab_limit=False,
        character_coverage=0.9995,
        byte_fallback=True,
        split_digits=True,
        normalization_rule_name="nmt_nfkc",
        unk_id=UNK_ID,
        bos_id=BOS_ID,
        eos_id=EOS_ID,
        pad_id=PAD_ID,
        control_symbols=[ACT, OUT],
        user_defined_symbols=[*JSON_PIECES, *ENUM_VALUES],
        add_dummy_prefix=False,  # prompts and targets are encoded separately; no leading "▁"
        num_threads=4,
        minloglevel=2,
    )
    return prefix.with_suffix(".model")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_stats(sp: spm.SentencePieceProcessor, texts: list[str]) -> dict[str, Any]:
    ids = [sp.encode(t) for t in texts]
    total = sum(len(x) for x in ids)
    byte = sum(sp.is_byte(i) for x in ids for i in x)
    unk = sum(i == UNK_ID for x in ids for i in x)
    return {
        "n": len(texts),
        "tokens_mean": round(total / len(texts), 2),
        "tokens_max": max(len(x) for x in ids),
        "byte_fallback_rate": round(byte / total, 5),
        "unk_rate": round(unk / total, 5),
        "texts_with_byte_fallback": sum(any(sp.is_byte(i) for i in x) for x in ids),
    }


def report(model: Path, data_dir: Path, massive_rows: list[dict]) -> dict[str, Any]:
    sp = spm.SentencePieceProcessor(model_file=str(model))
    train_cases = load_cases(data_dir / "train.jsonl") + load_cases(data_dir / "val.jsonl")
    val = load_cases(data_dir / "val.jsonl")
    dev = [r["utt"] for r in massive_rows if r["partition"] == "dev"]
    targets = [len(sp.encode(target_json(c.expected))) for c in train_cases]
    roundtrip = all(
        sp.decode(sp.encode(t)) == t for t in {target_json(c.expected) for c in train_cases}
    )
    seq = [
        len(sp.encode(c.prompt)) + len(sp.encode(target_json(c.expected))) + 4 for c in train_cases
    ]
    return {
        "file": model.name,
        "sha256": sha256(model),
        "vocab_size": sp.get_piece_size(),
        "val_prompts": _text_stats(sp, [c.prompt for c in val]),
        "massive_dev": _text_stats(sp, dev),
        "target_tokens_mean": round(statistics.mean(targets), 2),
        "target_tokens_max": max(targets),
        "target_roundtrip_ok": roundtrip,
        "sequence_tokens_max": max(seq),
        "embedding_params": {str(d): sp.get_piece_size() * d for d in EMBED_DIMS},
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=PROJECT_ROOT / "datasets/action/v0")
    parser.add_argument(
        "--massive-dir", type=Path, default=PROJECT_ROOT / "datasets/downloads/massive"
    )
    parser.add_argument("--vocab", type=int, nargs="+", default=[2048, 4096, 8192])
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "tokenizer/out")
    parser.add_argument("--record", type=Path, default=None, help="also write the report here")
    args = parser.parse_args(argv)

    rows = massive.load(massive.download(args.massive_dir))
    lines = train_text(args.data, rows)
    results = []
    for v in args.vocab:
        model = train(lines, v, args.out / f"action_v0_sp{v}")
        results.append(report(model, args.data, rows))
        print(json.dumps(results[-1], ensure_ascii=False))
    out = {
        "training_text": {
            "lines": len(lines),
            "sources": [
                "datasets/action/v0 train+val prompts and targets",
                "MASSIVE ja-JP train utterances (CC BY 4.0)",
            ],
        },
        "tokenizers": results,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    (args.out / "report.json").write_text(text, encoding="utf-8")
    if args.record:
        args.record.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
