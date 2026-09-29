"""Generate and cross-verify synthetic Action sentences against two vLLM servers (runs on vast.ai).

- Train sentences: written by the train generator (Qwen3), verified by the eval generator (llm-jp).
- Eval sentences, contrastive pairs, and English cases: written by the eval generator (llm-jp),
  verified by the train generator (Qwen3).
A sentence is kept later (jtalm.data.build) only if the verifier's parse equals the spec label.
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
from jtalm.data.specs import Spec, all_specs, sample_requests


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
    rows: list[dict] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(_safe(fn), items):
            if result is None:
                failures += 1
            else:
                rows.extend(result)
    return rows, failures


def _safe(fn: Callable[[Any], list[dict]]) -> Callable[[Any], list[dict] | None]:
    def wrapper(item: Any) -> list[dict] | None:
        try:
            return fn(item)
        except Exception:
            return None

    return wrapper


def _row(spec: Spec, text: str, split: str, generator: str, **extra: Any) -> dict:
    return {
        "split": split,
        "spec_id": spec.id,
        "category": spec.category,
        "label": list(spec.label),
        "text": text.strip(),
        "language": "ja",
        "generator": generator,
        "prompt_version": prompts.PROMPT_VERSION,
        **extra,
    }


def run(args: argparse.Namespace) -> dict:
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    rng = random.Random(cfg["seed"])
    n = cfg["per_request"]
    train_gen = Generator(args.train_url, cfg["train_generator"]["served_name"], cfg)
    eval_gen = Generator(args.eval_url, cfg["eval_generator"]["served_name"], cfg)
    train_name, eval_name = cfg["train_generator"]["hf_id"], cfg["eval_generator"]["hf_id"]
    specs = all_specs()
    summary: dict[str, Any] = {"prompt_version": prompts.PROMPT_VERSION, "failures": {}}

    def gen_sentences(gen: Generator, split: str, name: str) -> Callable[[tuple], list[dict]]:
        def fn(item: tuple[int, Spec]) -> list[dict]:
            i, spec = item
            data = gen.chat_json(
                prompts.generation_messages(spec, n, split),
                prompts.json_response_format("sentences", prompts.sentence_schema(n)),
                seed=cfg["seed"] + i,
                temperature=cfg["temperature"],
            )
            return [_row(spec, t, split, name, seed=cfg["seed"] + i) for t in data["sentences"]]

        return fn

    t0 = time.time()
    train_requests = list(enumerate(sample_requests(specs, cfg["train_quota"], n, rng)))
    train_rows, summary["failures"]["train_gen"] = _parallel(
        gen_sentences(train_gen, "train", train_name), train_requests, args.workers
    )
    eval_requests = list(enumerate(sample_requests(specs, cfg["eval_quota"], n, rng)))
    eval_rows, summary["failures"]["eval_gen"] = _parallel(
        gen_sentences(eval_gen, "eval", eval_name), eval_requests, args.workers
    )

    singles = [s for s in specs if s.category == "single"]
    pair_n = 4

    def gen_pairs(item: tuple[int, Spec]) -> list[dict]:
        i, spec = item
        data = eval_gen.chat_json(
            prompts.pair_messages(spec, pair_n),
            prompts.json_response_format("pairs", prompts.pair_schema(pair_n)),
            seed=cfg["seed"] + 10_000 + i,
            temperature=cfg["temperature"],
        )
        rows = []
        for j, pair in enumerate(data["pairs"]):
            pair_id = f"pair.{spec.id}.{i}.{j}"
            rows.append(_row(spec, pair["positive"], "eval", eval_name, pair_id=pair_id))
            neg = Spec(f"negation.of.{spec.id}", "negation", (), spec.meaning)
            rows.append(_row(neg, pair["negative"], "eval", eval_name, pair_id=pair_id))
        return rows

    pair_specs = [singles[i % len(singles)] for i in range(-(-cfg["eval_pairs"] // pair_n))]
    pair_rows, summary["failures"]["eval_pairs"] = _parallel(
        gen_pairs, list(enumerate(pair_specs)), args.workers
    )

    en_pool = [s for s in specs if s.category in ("single", "negation", "no_action")]

    def gen_english(item: tuple[int, Spec]) -> list[dict]:
        i, spec = item
        data = eval_gen.chat_json(
            prompts.english_messages(spec, 4),
            prompts.json_response_format("sentences", prompts.sentence_schema(4)),
            seed=cfg["seed"] + 20_000 + i,
            temperature=cfg["temperature"],
        )
        return [_row(spec, t, "eval", eval_name, language="en") for t in data["sentences"]]

    en_specs = rng.sample(en_pool, k=min(len(en_pool), -(-cfg["eval_english"] // 4)))
    en_rows, summary["failures"]["eval_english"] = _parallel(
        gen_english, list(enumerate(en_specs)), args.workers
    )
    eval_rows += pair_rows + en_rows
    summary["generation_sec"] = round(time.time() - t0)

    def verifier(gen: Generator, name: str) -> Callable[[dict], list[dict]]:
        def fn(row: dict) -> list[dict]:
            parsed = gen.chat_json(
                prompts.verify_messages(row["text"]),
                prompts.action_response_format(),
                seed=0,
                temperature=0.0,
            )
            return [{**row, "verifier": name, "verified": parsed}]

        return fn

    t1 = time.time()
    train_rows, summary["failures"]["train_verify"] = _parallel(
        verifier(eval_gen, eval_name), train_rows, args.workers
    )
    eval_rows, summary["failures"]["eval_verify"] = _parallel(
        verifier(train_gen, train_name), eval_rows, args.workers
    )
    summary["verify_sec"] = round(time.time() - t1)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train_raw.jsonl", train_rows), ("eval_raw.jsonl", eval_rows)):
        (out / name).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
    summary["counts"] = {"train_raw": len(train_rows), "eval_raw": len(eval_rows)}
    (out / "generation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/action_v0.json")
    parser.add_argument("--train-url", default="http://localhost:8000/v1")
    parser.add_argument("--eval-url", default="http://localhost:8001/v1")
    parser.add_argument("--workers", type=int, default=48)
    parser.add_argument("--out", default="artifacts/raw")
    print(json.dumps(run(parser.parse_args()), indent=2))


if __name__ == "__main__":
    main()
