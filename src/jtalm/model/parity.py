# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Check the C reference runtime (runtime/host) against the Python implementation (M6).

    uv run --group train python -m jtalm.model.parity \
        --ckpt runs/.../3m/best.pt --tokenizer tokenizer/out/action_v0_sp2048.model \
        --out runs/local/m6/parity --docker espressif/idf:v5.5.5

1. Exports the checkpoint (``jtalm.model.export``) as FP32 / INT8 / INT4.
2. Tokenization: ``jtalm --tokenize`` against ``sentencepiece`` on every prompt of the given
   JSONL files plus random strings that exercise normalization; ``jtalm --decode`` against
   ``sp.decode`` on random id sequences.
3. Generation: ``jtalm`` (with and without ``--grammar``) against ``jtalm.model.decode.greedy``
   on the model read back from the exported file (for INT8 / INT4 that is the dequantized
   weights with fp16 scales). Reports token-sequence and output-string match, ``jtalm.eval``
   exact match of both, the largest min_prob and first-step logit differences, and for every
   mismatch the Python probabilities of the two competing tokens. For INT8 / INT4 it also scores
   the fake-quantized weights of ``jtalm.model.quantize`` (f32 scales) to show the fp16 scales
   cost nothing.
4. Writes ``golden.jsonl`` (prompt ids, generated ids, top first-step logits) for device ports.

The C binary runs natively (``--jtalm``) or inside a Docker image with the repository mounted
at /w (``--docker``); files are exchanged under ``--out``, which must be inside the repository
in the Docker case.
"""

import argparse
import json
import random
import subprocess
import time
from pathlib import Path
from typing import Any

import sentencepiece as spm
import torch

from jtalm.eval.cases import EvalCase, load_cases
from jtalm.eval.metrics import evaluate
from jtalm.infra.env import PROJECT_ROOT
from jtalm.model.data import Codec
from jtalm.model.decode import greedy
from jtalm.model.evaluate import load_model
from jtalm.model.export import export, export_name, read_export
from jtalm.model.grammar import ActionGrammar
from jtalm.model.quantize import quantize_state
from jtalm.model.transformer import ActionLM, ModelConfig

DATA = PROJECT_ROOT / "datasets/action/v0"


class Runner:
    def __init__(self, binary: Path, docker: str | None) -> None:
        self.binary, self.docker = binary, docker

    def _path(self, p: Path) -> str:
        if not self.docker:
            return str(p)
        return "/w/" + p.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()

    def _cmd(self, program: str, args: list[str]) -> list[str]:
        if not self.docker:
            return [program, *args]
        mount = f"{PROJECT_ROOT.resolve().as_posix()}:/w"
        return ["docker", "run", "--rm", "-v", mount, "-w", "/w", "--entrypoint", program,
                self.docker, *args]  # fmt: skip

    def build(self) -> None:
        make = self._cmd("make", ["-C", self._path(self.binary.parent.parent)])
        subprocess.run(make, check=True, capture_output=True)

    def run(self, model: Path, flags: list[str], lines: list[str], work: Path) -> tuple[list, str]:
        """JSON values printed for ``lines`` and the stderr summary."""
        for line in lines:
            if "\n" in line or "\r" in line:
                raise ValueError(f"input line contains a line break: {line!r}")
        work.mkdir(parents=True, exist_ok=True)
        inp = work / "input.txt"
        inp.write_bytes(("\n".join(lines) + "\n").encode())
        args = [self._path(self.binary), "-m", self._path(model), "-i", self._path(inp), *flags]
        proc = subprocess.run(self._cmd(args[0], args[1:]), capture_output=True, check=True)
        text = proc.stdout.decode()  # split on LF only: outputs may contain U+2028 etc.
        out = [json.loads(x) for x in text.split(chr(10)) if x.strip()]
        if len(out) != len(lines):
            raise RuntimeError(f"{len(lines)} lines in, {len(out)} out: {proc.stderr.decode()}")
        return out, proc.stderr.decode().strip()


# -- tokenization ---------------------------------------------------------------------------------

FUZZ_RANGES = [
    (0x20, 0x7E), (0xA0, 0xFF), (0x2000, 0x206F), (0x2150, 0x218F), (0x2460, 0x24FF),
    (0x3000, 0x30FF), (0x3099, 0x309C), (0x3200, 0x33FF), (0x4E00, 0x4E80), (0xFF00, 0xFFEF),
    (0x0300, 0x036F), (0x1F600, 0x1F64F), (0xFE10, 0xFE6F), (0x09, 0x09),
]  # fmt: skip
# Pieces and characters that exercise user-defined symbols, whitespace (incl. U+3000 and U+2581),
# half-width kana, a combining sound mark (U+3099), and NFKC expansions (U+2460, U+337B, U+FDFA).
FUZZ_WORDS = ["left", "right", "up", "[]", "[", "}}", '"}}', ",", "  ", chr(0x3000), chr(0x2581),
              "ｶﾞ", "か" + chr(0x3099), chr(0x2460), chr(0x337B), chr(0xFDFA), "ＡＢＣ",
              "１２３"]  # fmt: skip


def fuzz_texts(n: int, seed: int = 0) -> list[str]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        parts = []
        for _ in range(rng.randint(1, 12)):
            if rng.random() < 0.2:
                parts.append(rng.choice(FUZZ_WORDS))
            else:
                lo, hi = rng.choice(FUZZ_RANGES)
                parts.append(chr(rng.randint(lo, hi)))
        out.append("".join(parts))
    return out


def tokenization(runner: Runner, model: Path, sp: spm.SentencePieceProcessor,
                 texts: list[str], work: Path) -> dict[str, Any]:  # fmt: skip
    c_ids, _ = runner.run(model, ["--tokenize"], texts, work)
    bad = [
        {"text": t, "python": sp.encode(t), "c": c}
        for t, c in zip(texts, c_ids, strict=True)
        if sp.encode(t) != c
    ]
    return {"n": len(texts), "match": len(texts) - len(bad), "mismatches": bad[:20]}


def decoding(runner: Runner, model: Path, sp: spm.SentencePieceProcessor, n: int,
             work: Path) -> dict[str, Any]:  # fmt: skip
    rng = random.Random(1)
    vocab = sp.get_piece_size()
    special = [0, 1, 2, 3, 4, 5, sp.piece_to_id("▁"), *range(28, 284)]
    seqs = [
        [rng.choice(special) if rng.random() < 0.4 else rng.randrange(vocab)
         for _ in range(rng.randint(0, 12))]
        for _ in range(n)
    ]  # fmt: skip
    c_text, _ = runner.run(model, ["--decode"], [" ".join(map(str, s)) for s in seqs], work)
    bad = [
        {"ids": s, "python": sp.decode(s), "c": c}
        for s, c in zip(seqs, c_text, strict=True)
        if sp.decode(s) != c
    ]
    return {"n": n, "match": n - len(bad), "mismatches": bad[:20]}


# -- generation -----------------------------------------------------------------------------------


@torch.no_grad()
def first_logits(model: ActionLM, codec: Codec, prompts: list[str]) -> list[torch.Tensor]:
    out: list[torch.Tensor] = [torch.empty(0)] * len(prompts)
    by_len: dict[int, list[int]] = {}
    encoded = [codec.prompt_ids(p) for p in prompts]
    for i, ids in enumerate(encoded):
        by_len.setdefault(len(ids), []).append(i)
    for idxs in by_len.values():
        x = torch.tensor([encoded[i] for i in idxs])
        logits = model(x)[:, -1].float()
        for row, i in enumerate(idxs):
            out[i] = logits[row]
    return out


@torch.no_grad()
def explain(model: ActionLM, codec: Codec, grammar: ActionGrammar | None, prompt: str,
            py: list[int], c: list[int]) -> dict[str, Any]:  # fmt: skip
    """Python probabilities of the Python and C choices at the first differing step."""
    common = min(len(py), len(c))
    k = next((i for i in range(common) if py[i] != c[i]), common)
    if k >= len(py) or k >= len(c):
        return {"step": k, "note": "one sequence is a prefix of the other"}
    x = torch.tensor([codec.prompt_ids(prompt) + py[:k]])
    probs = model(x)[0, -1].float().softmax(-1)
    return {
        "step": k,
        "python_token": py[k],
        "c_token": c[k],
        "p_python_token": float(probs[py[k]]),
        "p_c_token": float(probs[c[k]]),
        "allowed": grammar.allowed(py[:k]) if grammar else None,
    }


def generation(runner: Runner, model_file: Path, model: ActionLM, codec: Codec,
               cases: list[EvalCase], grammar: ActionGrammar | None, work: Path,
               fake_quant: ActionLM | None = None) -> dict[str, Any]:  # fmt: skip
    prompts = [c.prompt for c in cases]
    flags = ["--grammar"] if grammar else []
    t0 = time.perf_counter()
    py = greedy(model, codec, prompts, grammar=grammar)
    py_seconds = time.perf_counter() - t0
    c_rows, summary = runner.run(model_file, flags, prompts, work)
    same_ids = [list(p.ids) == r["ids"] for p, r in zip(py, c_rows, strict=True)]
    same_text = [p.text == r["output"] for p, r in zip(py, c_rows, strict=True)]
    py_report = evaluate(cases, {c.id: p.text for c, p in zip(cases, py, strict=True)})
    c_report = evaluate(cases, {c.id: r["output"] for c, r in zip(cases, c_rows, strict=True)})
    diffs = [abs(p.min_prob - r["min_prob"]) for p, r in zip(py, c_rows, strict=True)]
    mismatches = [
        {
            "id": case.id,
            "prompt": case.prompt,
            "python": p.text,
            "c": r["output"],
            **explain(model, codec, grammar, case.prompt, list(p.ids), r["ids"]),
        }
        for case, p, r, ok in zip(cases, py, c_rows, same_ids, strict=True)
        if not ok
    ]
    result = {
        "n": len(cases),
        "token_match": sum(same_ids),
        "output_match": sum(same_text),
        "exact_python": py_report["exact_rate"],
        "exact_c": c_report["exact_rate"],
        "min_prob_max_abs_diff": max(diffs),
        "c_summary": summary,
        "python_seconds": round(py_seconds, 2),
        "mismatches": mismatches,
    }
    if fake_quant is not None:
        fq = greedy(fake_quant, codec, prompts, grammar=grammar)
        fq_report = evaluate(cases, {c.id: p.text for c, p in zip(cases, fq, strict=True)})
        result["exact_fake_quant_f32_scale"] = fq_report["exact_rate"]
        result["fake_quant_output_match"] = sum(
            a.text == b.text for a, b in zip(py, fq, strict=True)
        )
    return result


def logit_diff(runner: Runner, model_file: Path, model: ActionLM, codec: Codec,
               prompts: list[str], work: Path) -> dict[str, Any]:  # fmt: skip
    c_rows, _ = runner.run(model_file, ["--first-logits"], prompts, work)
    py = first_logits(model, codec, prompts)
    diff = max(
        float((torch.tensor(r["logits0"]) - p).abs().max()) for r, p in zip(c_rows, py, strict=True)
    )
    scale = max(float(p.abs().max()) for p in py)
    return {"n": len(prompts), "max_abs_diff": diff, "max_abs_logit": scale}


def golden(model: ActionLM, codec: Codec, cases: list[EvalCase], path: Path) -> None:
    rows = []
    preds = greedy(model, codec, [c.prompt for c in cases])
    logits = first_logits(model, codec, [c.prompt for c in cases])
    for c, p, lg in zip(cases, preds, logits, strict=True):
        values, indices = lg.topk(5)
        rows.append({
            "prompt": c.prompt,
            "prompt_ids": codec.prompt_ids(c.prompt),
            "ids": list(p.ids),
            "output": p.text,
            "min_prob": p.min_prob,
            "top_logits": [[int(i), float(v)] for v, i in zip(values, indices, strict=True)],
        })  # fmt: skip
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DATA / "eval.jsonl")
    parser.add_argument(
        "--token-sets",
        type=Path,
        nargs="*",
        default=[DATA / "train.jsonl", DATA / "val.jsonl", DATA / "eval.jsonl"],
    )
    parser.add_argument("--bits", type=int, nargs="+", default=[0, 8, 4])
    parser.add_argument("--group", type=int, default=64)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jtalm", type=Path, default=PROJECT_ROOT / "runtime/host/build/jtalm")
    parser.add_argument("--docker", default=None, help="run the binary in this Docker image")
    parser.add_argument("--build", action="store_true", help="run make first")
    parser.add_argument("--fuzz", type=int, default=5000)
    parser.add_argument("--limit", type=int, default=0, help="only the first N cases (smoke)")
    args = parser.parse_args(argv)  # fmt: skip

    runner = Runner(args.jtalm, args.docker)
    if args.build:
        runner.build()
    ckpt_model, state = load_model(args.ckpt, torch.device("cpu"))
    codec = Codec(args.tokenizer)
    if state["tokenizer_sha256"] != codec.sha256:
        raise SystemExit(f"{args.ckpt}: tokenizer sha256 does not match {args.tokenizer}")
    grammar = ActionGrammar(codec)
    cases = load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    work = args.out / "work"
    report: dict[str, Any] = {"ckpt": str(args.ckpt), "cases": str(args.cases)}

    files = {}
    for bits in args.bits:
        files[bits] = args.out / export_name(args.ckpt, bits, args.group)
        export(state["state_dict"], ckpt_model.cfg, args.tokenizer, files[bits], bits, args.group)
    probe = files[args.bits[0]]

    tok: dict[str, Any] = {}
    for path in args.token_sets:
        texts = [c.prompt for c in load_cases(path)]
        tok[path.name] = tokenization(runner, probe, codec.sp, texts, work)
    if args.fuzz:
        tok["fuzz"] = tokenization(runner, probe, codec.sp, fuzz_texts(args.fuzz), work)
        tok["decode_fuzz"] = decoding(runner, probe, codec.sp, args.fuzz, work)
    report["tokenization"] = tok
    for name, r in tok.items():
        print(f"tokenization {name}: {r['match']}/{r['n']}")

    report["generation"] = {}
    for bits in args.bits:
        ex = read_export(files[bits])
        model = ActionLM(ModelConfig(**{**ex.cfg.to_dict(), "dropout": 0.0}))
        model.load_state_dict(ex.state)
        model.eval()
        fake = None
        if bits == 0:
            same = all(torch.equal(ex.state[k], v) for k, v in state["state_dict"].items())
            report.setdefault("fp32_roundtrip_exact", same)
        else:
            q_state, _ = quantize_state(state["state_dict"], bits, args.group)
            fake = ActionLM(ckpt_model.cfg)
            fake.load_state_dict(q_state)
            fake.eval()
        label = "fp32" if bits == 0 else f"int{bits}"
        entry: dict[str, Any] = {"file": files[bits].name, "bytes": files[bits].stat().st_size}
        entry["first_logits"] = logit_diff(
            runner, files[bits], model, codec, [c.prompt for c in cases], work
        )
        for mode, g in (("plain", None), ("grammar", grammar)):
            r = generation(runner, files[bits], model, codec, cases, g, work, fake)
            entry[mode] = r
            print(
                f"{label} {mode}: tokens {r['token_match']}/{r['n']}, "
                f"outputs {r['output_match']}/{r['n']}, exact python {r['exact_python']:.4f} "
                f"c {r['exact_c']:.4f}, min_prob diff {r['min_prob_max_abs_diff']:.2e} | "
                f"{r['c_summary']}"
            )
        report["generation"][label] = entry
        if bits == 0:
            golden(model, codec, cases[:32], args.out / "golden.jsonl")

    (args.out / "parity.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {args.out / 'parity.json'}")


if __name__ == "__main__":
    main()
