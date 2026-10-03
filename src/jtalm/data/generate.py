# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Generate and cross-verify synthetic Action sentences with vLLM servers (runs on vast.ai).

Runs in phases so only one model needs to be on the GPU at a time:

1. ``eval-gen``      eval generator (llm-jp) writes eval sentences, contrastive pairs, English
2. ``train-gen``     train generator (Qwen3) writes train sentences
3. ``eval-verify``   train generator (Qwen3) parses the eval sentences
4. ``train-verify``  the config's ``train_verifier`` (Qwen3 since v0.2) parses the train sentences

``jtalm.data.build`` later keeps a sentence only if the parse equals the spec label.
"""

import argparse
import json
import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from openai import OpenAI

from jtalm.data import prompts
from jtalm.data.focus import english_pool, focus_specs, sample_by_slice, slice_of
from jtalm.data.specs import Spec, all_specs, sample_requests
from jtalm.data.specs_v1 import all_specs_v1, paraphrase_specs

PHASES = ("eval-gen", "train-gen", "eval-verify", "train-verify", "reverify")
PAIR_N = 4
EN_N = 4


class Generator:
    def __init__(self, base_url: str, model: str, cfg: dict) -> None:
        self.client = OpenAI(base_url=base_url, api_key="EMPTY", timeout=300)
        self.model = model
        self.cfg = cfg

    def chat_json(self, messages: list[dict], fmt: dict, seed: int, temperature: float) -> Any:
        for attempt in range(3):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    top_p=self.cfg["top_p"] if temperature > 0 else 1.0,
                    max_tokens=self.cfg["max_tokens"],
                    seed=seed,
                    response_format=fmt,
                )
                return json.loads(resp.choices[0].message.content or "null")
            except Exception:  # retried; persistent failures are counted by the caller
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        return None


def _parallel(fn: Callable[[Any], list[dict]], items: list, workers: int) -> tuple[list[dict], int]:
    def safe(item: Any) -> list[dict] | None:
        try:
            return fn(item)
        except Exception:
            return None

    rows: list[dict] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(safe, items):
            if result is None:
                failures += 1
            else:
                rows.extend(result)
    return rows, failures


def _row(spec: Spec, text: str, split: str, generator: str, **extra: Any) -> dict:
    extra.setdefault("prompt_version", prompts.PROMPT_VERSION)
    if slice_of(spec.id):
        extra.setdefault("slice", slice_of(spec.id))
    return {
        "split": split,
        "spec_id": spec.id,
        "category": spec.category,
        "label": list(spec.label),
        "text": text.strip(),
        "language": "ja",
        "generator": generator,
        **extra,
    }


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def _specs_for(cfg: dict, quota: dict, rng: random.Random) -> list[Spec]:
    n = cfg["per_request"]
    spec_set = cfg.get("spec_set")
    if spec_set == "focus":
        return sample_by_slice(focus_specs(), cfg["slice_quota"], n, rng)
    if spec_set == "v1":
        return sample_requests(all_specs_v1(), quota, n, rng)
    if spec_set == "v1_paraphrase":
        return sample_requests(paraphrase_specs(), quota, n, rng)
    return sample_requests(all_specs(), quota, n, rng)


def generate_sentences(gen: Generator, name: str, split: str, quota: dict, cfg: dict, seed0: int):
    n = cfg["per_request"]
    rng = random.Random(seed0)
    specs = _specs_for(cfg, quota, rng)
    requests = list(enumerate(specs))

    style_set = cfg.get("train_styles", "v0.2") if split == "train" else "v0.2"
    version = cfg.get("prompt_version", prompts.PROMPT_VERSION)

    def fn(item: tuple[int, Spec]) -> list[dict]:
        i, spec = item
        styles = None
        if style_set == "v0.3":
            styles = prompts.pick_styles(random.Random(seed0 + i))
        data = gen.chat_json(
            prompts.generation_messages(spec, n, split, styles),
            prompts.json_response_format("sentences", prompts.sentence_schema(n)),
            seed=seed0 + i,
            temperature=cfg["temperature"],
        )
        return [
            _row(spec, t, split, name, seed=seed0 + i, prompt_version=version)
            for t in data["sentences"]
        ]

    return fn, requests


def phase_eval_gen(gen: Generator, cfg: dict, workers: int) -> tuple[list[dict], dict]:
    name = cfg["eval_generator"]["hf_id"]
    seed0 = cfg["seed"] + 100_000
    fn, requests = generate_sentences(gen, name, "eval", cfg["eval_quota"], cfg, seed0)
    rows, failures = _parallel(fn, requests, workers)
    stats = {"eval_gen_failures": failures}

    singles = [s for s in all_specs() if s.category == "single"]

    def gen_pairs(item: tuple[int, Spec]) -> list[dict]:
        i, spec = item
        data = gen.chat_json(
            prompts.pair_messages(spec, PAIR_N),
            prompts.json_response_format("pairs", prompts.pair_schema(PAIR_N)),
            seed=seed0 + 10_000 + i,
            temperature=cfg["temperature"],
        )
        out = []
        for j, pair in enumerate(data["pairs"]):
            pair_id = f"pair.{spec.id}.{i}.{j}"
            out.append(_row(spec, pair["positive"], "eval", name, pair_id=pair_id))
            neg = Spec(f"negation.of.{spec.id}", "negation", (), spec.meaning)
            out.append(_row(neg, pair["negative"], "eval", name, pair_id=pair_id))
        return out

    n_pair_requests = -(-cfg["eval_pairs"] // PAIR_N)
    pair_specs = [singles[i % len(singles)] for i in range(n_pair_requests)]
    pair_rows, stats["eval_pair_failures"] = _parallel(
        gen_pairs, list(enumerate(pair_specs)), workers
    )

    if cfg.get("spec_set") == "focus":
        en_pool = english_pool()
    else:
        en_pool = [s for s in all_specs() if s.category in ("single", "negation", "no_action")]

    def gen_english(item: tuple[int, Spec]) -> list[dict]:
        i, spec = item
        data = gen.chat_json(
            prompts.english_messages(spec, EN_N),
            prompts.json_response_format("sentences", prompts.sentence_schema(EN_N)),
            seed=seed0 + 20_000 + i,
            temperature=cfg["temperature"],
        )
        extra = {"slice": "english"} if cfg.get("spec_set") == "focus" else {}
        return [_row(spec, t, "eval", name, language="en", **extra) for t in data["sentences"]]

    rng = random.Random(seed0)
    en_specs = rng.sample(en_pool, k=min(len(en_pool), -(-cfg["eval_english"] // EN_N)))
    en_rows, stats["eval_english_failures"] = _parallel(
        gen_english, list(enumerate(en_specs)), workers
    )
    return rows + pair_rows + en_rows, stats


def phase_train_gen(gen: Generator, cfg: dict, workers: int) -> tuple[list[dict], dict]:
    name = cfg["train_generator"]["hf_id"]
    fn, requests = generate_sentences(gen, name, "train", cfg["train_quota"], cfg, cfg["seed"])
    rows, failures = _parallel(fn, requests, workers)
    return rows, {"train_gen_failures": failures}


def phase_verify(gen: Generator, name: str, rows: list[dict], workers: int):
    def fn(row: dict) -> list[dict]:
        parsed = gen.chat_json(
            prompts.verify_messages(row["text"]),
            prompts.action_response_format(),
            seed=0,
            temperature=0.0,
        )
        return [{**row, "verifier": name, "verified": parsed}]

    return _parallel(fn, rows, workers)


def _load_cases(inputs: list[str]) -> list[dict]:
    rows = []
    for path in inputs:
        for lineno, line in enumerate(Path(path).read_text("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            where = f"{path}:{lineno}"
            try:
                case = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{where}: not valid JSON ({e})") from e
            if not isinstance(case, dict) or not case.get("id"):
                raise ValueError(f"{where}: missing id")
            # EvalCase files have "prompt"; the Stack-chan sources files have "text" only.
            text = case.get("prompt", case.get("text"))
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"{where}: missing prompt/text")
            rows.append({"id": case["id"], "text": text,
                         "expected": case.get("expected", []),
                         "category": case.get("category", "unknown"),
                         "language": case.get("language", "ja"),
                         "source": case.get("source"), "file": path})  # fmt: skip
    return rows


def phase_reverify(gen: Generator, name: str, rows: list[dict], workers: int):
    return phase_verify(gen, name, rows, workers)


def run(args: argparse.Namespace) -> dict:
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    train_cfg, eval_cfg = cfg["train_generator"], cfg["eval_generator"]
    t0 = time.time()
    if args.phase == "eval-gen":
        gen = Generator(args.base_url, eval_cfg["served_name"], cfg)
        rows, stats = phase_eval_gen(gen, cfg, args.workers)
        _write(out / "eval_gen.jsonl", rows)
    elif args.phase == "train-gen":
        gen = Generator(args.base_url, train_cfg["served_name"], cfg)
        rows, stats = phase_train_gen(gen, cfg, args.workers)
        _write(out / "train_gen.jsonl", rows)
    elif args.phase == "eval-verify":
        gen = Generator(args.base_url, train_cfg["served_name"], cfg)
        rows, failures = phase_verify(
            gen, train_cfg["hf_id"], _read(out / "eval_gen.jsonl"), args.workers
        )
        stats = {"eval_verify_failures": failures}
        _write(out / "eval_raw.jsonl", rows)
    elif args.phase == "reverify":
        if not args.input:
            raise ValueError("reverify needs --input")
        cases = _load_cases(args.input)
        verifier_cfg = cfg["verifier"]
        gen = Generator(args.base_url, verifier_cfg["served_name"], cfg)
        rows, failures = phase_reverify(gen, verifier_cfg["hf_id"], cases, args.workers)
        stats = {"input_rows": len(cases), "reverify_failures": failures}
        _write(out / "reverify_raw.jsonl", rows)
    else:
        # v0.1 used llm-jp here, but llm-jp-3.1-13b could not parse reliably (it returned actions
        # for chit-chat); v0.2 verifies train sentences with the train generator at temperature 0.
        verifier_cfg = cfg[cfg.get("train_verifier", "eval_generator")]
        gen = Generator(args.base_url, verifier_cfg["served_name"], cfg)
        rows, failures = phase_verify(
            gen, verifier_cfg["hf_id"], _read(out / "train_gen.jsonl"), args.workers
        )
        stats = {"train_verify_failures": failures}
        _write(out / "train_raw.jsonl", rows)
    summary = {
        "phase": args.phase,
        "prompt_version": cfg.get("prompt_version", prompts.PROMPT_VERSION),
        "rows": len(rows),
        "sec": round(time.time() - t0),
        **stats,
    }
    (out / f"summary_{args.phase}.json").write_text(json.dumps(summary, indent=2), "utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--config", default="configs/action_v0.json")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--workers", type=int, default=64)
    parser.add_argument("--out", default="artifacts/raw")
    parser.add_argument("--input", nargs="*", default=[], help="case files for reverify")
    print(json.dumps(run(parser.parse_args()), indent=2))


if __name__ == "__main__":
    main()
