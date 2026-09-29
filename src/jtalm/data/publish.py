"""Prepare and publish the synthetic Action dataset to Hugging Face (public, manual gate).

``prepare`` writes the Hugging Face files (MASSIVE rows excluded: they are not redistributed).
``publish`` creates the repo as private, uploads, enables manual gating, then makes it public, so
there is no moment where the files are public without the gate. Publishing requires --confirm.

    uv run python -m jtalm.data.publish prepare
    uv run python -m jtalm.data.publish publish --confirm
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from huggingface_hub import HfApi

from jtalm.action.schema import to_json
from jtalm.data.prompts import PROMPT_VERSION, VERIFY_SYSTEM
from jtalm.eval.cases import load_cases
from jtalm.infra.env import read_secret

REPO_ID = "japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth"
SPLITS = {"train": "train", "val": "validation", "eval": "test"}


def _rows(path: Path) -> list[dict]:
    rows = []
    for case in load_cases(path):
        if (case.source or "").startswith("massive"):
            continue
        rows.append(
            {
                "id": case.id,
                "input": case.prompt,
                "output": to_json(case.expected) if case.expected else "[]",
                "category": case.category,
                "language": case.language,
                "pair_id": case.pair_id,
                "generator": (case.source or "").removeprefix("synthetic:"),
            }
        )
    return rows


def prepare(data_dir: Path, hf_dir: Path, manifest: dict) -> dict[str, int]:
    hf_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    by_cat: dict[str, Counter] = {}
    for src, split in SPLITS.items():
        rows = _rows(data_dir / f"{src}.jsonl")
        (hf_dir / f"{split}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
        counts[split] = len(rows)
        by_cat[split] = Counter(r["category"] for r in rows)
    (hf_dir / "README.md").write_text(dataset_card(counts, by_cat, manifest), encoding="utf-8")
    return counts


def dataset_card(counts: dict[str, int], by_cat: dict[str, Counter], manifest: dict) -> str:
    cfg = manifest["config"]
    train_gen, eval_gen = cfg["train_generator"], cfg["eval_generator"]
    train_verifier = cfg[cfg.get("train_verifier", "eval_generator")]
    cats = sorted({c for v in by_cat.values() for c in v})
    table = "\n".join(
        f"| {c} | " + " | ".join(str(by_cat[s][c]) for s in SPLITS.values()) + " |" for c in cats
    )
    total = sum(counts.values())
    size = "1K<n<10K" if total < 10_000 else "10K<n<100K"
    return f"""---
license: cc-by-sa-4.0
language:
- ja
- en
pretty_name: JapaneseTinyAgentLM Action Synth
size_categories:
- {size}
task_categories:
- text-generation
tags:
- robotics
- function-calling
- tool-use
- japanese
- synthetic
- stackchan
configs:
- config_name: default
  data_files:
  - split: train
    path: train.jsonl
  - split: validation
    path: validation.jsonl
  - split: test
    path: test.jsonl
---

# JapaneseTinyAgentLM Action Synth ({cfg["dataset_version"]})

小さな卓上ロボット（M5Stack StackChan K151）への日本語の発話を、ロボットの動作の JSON に変換する
**Japanese Action LM** のための合成データセットです。
Synthetic Japanese utterances paired with robot action calls, for training a tiny on-device
Action LM (ESP32-S3). Project: JapaneseTinyAgentLM.

## 形式

| field | 内容 |
|---|---|
| `input` | 発話（日本語。test には英語も少し含む） |
| `output` | 正解の動作。JSON 配列（0〜2個）。`[]` は何もしない（no-action） |
| `category` | single / multi_action / negation / correction / no_action |
| `language` | ja / en |
| `pair_id` | 否定の有無だけが違う対比ペアの ID（test のみ） |
| `generator` | 文を書いたモデル |

動作は `look(direction: left/right/up/down/center, amount: slight/normal/large)`、
`set_expression(expression: happy/sad/surprised/neutral)`、`nod(count: 1-3)` の3種類です。

## 件数

| category | train | validation | test |
|---|---:|---:|---:|
{table}
| **合計** | {counts["train"]} | {counts["validation"]} | {counts["test"]} |

## 作り方

1. 正解（動作の JSON）を先にプログラムで決める（単一の動作、2つの動作の順序、否定、訂正、no-action）。
2. オープンモデルに、その意味の日本語の文を様々な言い方で書かせる。
   - train / validation: `{train_gen["hf_id"]}`（{train_gen["license"]}）
   - test: `{eval_gen["hf_id"]}`（{eval_gen["license"]}）と別の prompt。生成元を分け、生成のくせの暗記を評価で見抜けるようにしている
3. モデルが各文を温度 0 で動作の JSON に変換し、1. の正解と一致した文だけを残す（train は `{train_verifier["hf_id"]}` による検証。train の文を書いたのと同じモデルなので、意図した正解と一致するかの一貫性の検査として働く。test は、文を書いていない `{train_gen["hf_id"]}` が検証）。
4. 長さ・文字化け・否定との矛盾を検査し、重複と train/test の重なりを除く。

prompt version: `{PROMPT_VERSION}`

## ライセンスと出典

- 本データセット: **CC BY-SA 4.0**
- 文の生成に使ったモデルは、いずれも Apache-2.0 のオープンモデルです。
- プロジェクトの学習では、このほかに [Amazon MASSIVE](https://github.com/alexa/massive)（ja-JP、CC BY 4.0）の発話を no-action の負例として使っていますが、本データセットには含めていません（再配布しない）。
- データの文章と正解は、上記のオープンモデルとプログラムが作成しました。Claude Code は生成・検査・分割のコードの作成と実行だけを担当し、データの文章や正解は書いていません。

## 既知の限界

- 合成データのため、実際の利用者の話し方の分布とは異なります。
- 検証に使ったモデルが正しく解釈できた文だけが残るため、解釈の難しい言い回しは少なめです。
- 動作は v0 の3種類だけです。

## 検証に使った指示（抜粋）

```text
{VERIFY_SYSTEM}
```
"""


def publish(hf_dir: Path, repo_id: str) -> str:
    api = HfApi(token=read_secret("HF_TOKEN"))
    api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)
    api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=hf_dir,
        commit_message="Add JapaneseTinyAgentLM Action synthetic dataset",
    )
    api.update_repo_settings(repo_id, repo_type="dataset", gated="manual")
    api.update_repo_settings(repo_id, repo_type="dataset", private=False)
    info = api.dataset_info(repo_id)
    return f"https://huggingface.co/datasets/{repo_id} (private={info.private}, gated={info.gated})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "publish"])
    parser.add_argument("--data", type=Path, default=Path("datasets/action/v0"))
    parser.add_argument("--hf-dir", type=Path, default=Path("datasets/action/v0/hf"))
    parser.add_argument("--manifest", type=Path, default=Path("datasets/manifests/action_v0.json"))
    parser.add_argument("--repo", default=REPO_ID)
    parser.add_argument("--confirm", action="store_true", help="required to publish")
    args = parser.parse_args()
    if args.action == "prepare":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        print(prepare(args.data, args.hf_dir, manifest))
    elif not args.confirm:
        parser.error("publishing is public; pass --confirm after reviewing the dataset card")
    else:
        print(publish(args.hf_dir, args.repo))


if __name__ == "__main__":
    main()
