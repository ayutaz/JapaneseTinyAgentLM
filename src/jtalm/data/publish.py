# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Prepare and publish the synthetic Action dataset (data v1.0) to Hugging Face (manual gate).

``prepare`` writes the Hugging Face files: only sentences written by the open models. MASSIVE rows
are not redistributed, and the mined hard negatives (Tatoeba, JESC, MASSIVE sentences) are left
out too. ``publish`` creates the repo as private, uploads (removing split files of an earlier
version that the new one does not have), enables manual gating, turns Community contributions
off, then makes it public, so there is no moment where the files are public without the gate.
Publishing requires --confirm and the user's approval.

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
from jtalm.infra.hf import community_disabled, disable_community

REPO_ID = "japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth"
DATASET_VERSION = "action-v1.0"
# Data split file -> Hugging Face split. A version without an evaluation file (v1.0) has no test.
SPLITS = {"train": "train", "val": "validation", "eval": "test"}
RELABEL = "+relabel:v1"  # source suffix of a row whose label is the verifier's schema v1 reading
# Every writer of a published sentence must be listed here with its license.
WRITERS = {
    "Qwen/Qwen3-30B-A3B-Instruct-2507": "Apache-2.0",
    "cyberagent/calm3-22b-chat": "Apache-2.0",
    "abeja/ABEJA-Qwen2.5-32b-Japanese-v1.0": "Apache-2.0",
    "cyberagent/Mistral-Nemo-Japanese-Instruct-2408": "Apache-2.0",
    "elyza/ELYZA-Shortcut-1.0-Qwen-32B": "Apache-2.0",
    "sbintuitions/sarashina2.2-3b-instruct-v0.1": "MIT",
    "ibm-granite/granite-3.3-8b-instruct": "Apache-2.0",
    "llm-jp/llm-jp-3.1-13b-instruct4": "Apache-2.0",
}


def _rows(path: Path) -> tuple[list[dict], Counter]:
    rows, skipped = [], Counter()
    for case in load_cases(path):
        source = case.source or ""
        if source.startswith("massive"):
            skipped["massive"] += 1
            continue
        generator = source.removeprefix("synthetic:").removesuffix(RELABEL)
        if generator.startswith("human:"):  # mined hard negatives: third-party corpus sentences
            skipped[generator] += 1
            continue
        rows.append(
            {
                "id": case.id,
                "input": case.prompt,
                "output": to_json(case.expected) if case.expected else "[]",
                "category": case.category,
                "language": case.language,
                "pair_id": case.pair_id,
                "generator": generator,
                "relabeled": source.endswith(RELABEL),
            }
        )
    return rows, skipped


def prepare(
    data_dir: Path, hf_dir: Path, manifest: dict, writers: dict[str, str] = WRITERS
) -> dict[str, int]:
    hf_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    by_cat: dict[str, Counter] = {}
    by_writer: dict[str, Counter] = {}
    relabeled: dict[str, int] = {}
    skipped: dict[str, Counter] = {}
    languages: set[str] = set()
    for src, split in SPLITS.items():
        path = data_dir / f"{src}.jsonl"
        if not path.exists():
            continue
        rows, skipped[split] = _rows(path)
        unknown = sorted({r["generator"] for r in rows} - set(writers))
        if unknown:
            raise ValueError(f"no license recorded for the writers {unknown}")
        (hf_dir / f"{split}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
        counts[split] = len(rows)
        by_cat[split] = Counter(r["category"] for r in rows)
        by_writer[split] = Counter(r["generator"] for r in rows)
        relabeled[split] = sum(r["relabeled"] for r in rows)
        languages |= {r["language"] for r in rows}
    card = dataset_card(
        counts, by_cat, by_writer, relabeled, skipped, sorted(languages), manifest, writers
    )
    (hf_dir / "README.md").write_text(card, encoding="utf-8")
    return counts


def _n(x: int) -> str:
    return f"{x:,}"


def dataset_card(
    counts: dict[str, int],
    by_cat: dict[str, Counter],
    by_writer: dict[str, Counter],
    relabeled: dict[str, int],
    skipped: dict[str, Counter],
    languages: list[str],
    manifest: dict,
    writers: dict[str, str],
) -> str:
    splits = list(counts)
    head = "| | " + " | ".join(splits) + " |\n|---|" + "---:|" * len(splits)

    def cells(f) -> str:
        return " | ".join(_n(f(s)) for s in splits)

    cats = sorted({c for v in by_cat.values() for c in v})
    cat_table = "\n".join(f"| {c} | {cells(lambda s, c=c: by_cat[s][c])} |" for c in cats)
    used = sorted({w for v in by_writer.values() for w in v}, key=lambda w: -sum(
        by_writer[s][w] for s in splits))  # fmt: skip
    writer_table = "\n".join(
        f"| `{w}` | {writers[w]} | {cells(lambda s, w=w: by_writer[s][w])} |" for w in used
    )

    def skip(s: str, key: str) -> int:
        return skipped[s][key]

    total = sum(counts.values())
    size = "1K<n<10K" if total < 10_000 else "10K<n<100K" if total < 100_000 else "100K<n<1M"
    lang_yaml = "\n".join(f"- {lang}" for lang in languages)
    split_yaml = "\n".join(
        f"  - split: {s}\n    path: {s}.jsonl" for s in splits
    )  # the configs list only the splits of this version
    built = " / ".join(
        f"{s} {_n(manifest[k]['n'])}" for k, s in (("train", "train"), ("val", "validation"))
    )
    inherited = f"{_n(manifest['inherited_train']['n'])} / {_n(manifest['inherited_val']['n'])}"
    relabel_kept = (
        f"{manifest['inherited_train']['relabeled_kept']} / "
        f"{manifest['inherited_val']['relabeled_kept']}"
    )
    no_test = (
        ""
        if "test" in counts
        else "\n評価セット（eval v3、Stack-chan v1、schema v1 で付け直した前の評価セット）は"
        "含めていません。学習データ（train / validation）は、これらの評価セットの文と重なる文を"
        "除いて作りました。\n"
    )
    return f"""---
license: cc-by-sa-4.0
language:
{lang_yaml}
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
{split_yaml}
---

# JapaneseTinyAgentLM Action Synth ({DATASET_VERSION})

小さな卓上ロボット（M5Stack StackChan K151）への日本語の発話を、ロボットの動作の JSON に変換する
**Japanese Action LM** のための合成データセットです。この版（データ v1.0）は **Action schema v1**
（11 の動作）のものです。前の版（v0、3つの動作）は、このリポジトリの以前の commit にあります。
Synthetic Japanese utterances paired with robot action calls (Action schema v1, 11 tools), for
training a tiny on-device Action LM (ESP32-S3). Project: JapaneseTinyAgentLM.

## 形式

| field | 内容 |
|---|---|
| `input` | 発話（日本語） |
| `output` | 正解の動作。JSON 配列（0〜2個）。`[]` は何もしない（no-action） |
| `category` | single / multi_action / negation / correction / no_action |
| `language` | ja |
| `pair_id` | 否定の有無だけが違う対比ペアの ID（評価セットだけで使う。この版の train / validation では空） |
| `generator` | 文を書いたモデル |
| `relabeled` | `true` は、v0 の正解を schema v1 で付け直した行（正解は検証役の Qwen3 の答え。下の「作り方」の 2.） |

## 動作（Action schema v1）

- `look`（正面を基準に首を向ける）/ `turn`（今の向きから動かす）: `direction`（left / right / up / down /
  up_left / up_right / down_left / down_right。`look` だけ center も）と、`amount`（slight / normal / large）か
  `degrees`（1〜180）のどちらか一方。`look` の center は `amount` が normal のときだけ
- `nod`（うなずく）/ `shake`（首を横に振る）: `count`（1〜5）。`bow`（お辞儀）: 引数なし
- `set_expression`: happy / sad / surprised / neutral / angry / sleepy / doubt
- `set_led`: red / orange / yellow / green / light_blue / blue / purple / pink / white / off
- `set_volume` / `set_brightness`: `level`（0〜100）
- `adjust_volume` / `adjust_brightness`: `direction`（up / down）と、`amount` か `by`（1〜100）のどちらか一方

数値は JSON の整数です。2つの call が完全に同じ出力はありません。

## 件数

| category | {" | ".join(splits)} |
|---|{"---:|" * len(splits)}
{cat_table}
| **合計** | {" | ".join(f"**{_n(counts[s])}**" for s in splits)} |

組み立てたデータ v1.0 は {built} 件です。このうち、次の行は含めていません。

{head}
| MASSIVE ja-JP の発話（負例） | {cells(lambda s: skip(s, "massive") + skip(s, "human:massive"))} |
| 間違えやすい例として集めた Tatoeba の文（負例） | {cells(lambda s: skip(s, "human:tatoeba"))} |
| 間違えやすい例として集めた JESC の文（負例） | {cells(lambda s: skip(s, "human:jesc"))} |
{no_test}
## 書き手（文を書いたモデル）

| モデル | ライセンス | {" | ".join(splits)} |
|---|---|{"---:|" * len(splits)}
{writer_table}

検証役は、すべての文で `Qwen/Qwen3-30B-A3B-Instruct-2507`（Apache-2.0、温度 0）です。

## 作り方

1. **前の版を引き継ぐ:** データ v0.5.1（schema v0）の train と validation の文を、Qwen3 が温度 0 で
   schema v1 の JSON に読み直し、その答えが v0 の正解と同じ文をそのまま残しました（引き継いだのは
   train / validation {inherited} 件。MASSIVE の行と集めた負例を含む）。v0 の正解は、正解を先にプログラムで
   決め（label-first）、オープンモデルに書かせ、Qwen3 が一致を確かめたものです。
2. **付け直しは、はっきりした文だけ:** 11 の動作では Qwen3 の答えが揺れやすく、最初の組み立てでは
   付け直しの候補の多くが誤りでした（引き継いだ train の 5,978件が候補になり、`turn` を含む 4,976件のうち、
   今の向きを基準にする語があったのは 190件だけ）。v1 だけの要素（`turn`、`degrees`、斜めなど）に文の中の
   根拠を求める規則でも誤りが残ったため、付け直しを次のように絞りました。
   - v0 の正解が動作の文は付け直さない。Qwen3 の答えが違えば、その文を除く。
   - 言い直し（correction）の文は付け直さない（どの部分が否定されたかを語の規則で判断できないため）。
   - v0 の正解が `[]` の文は、LED、音量、明るさの tool の1つの call にだけ付け直す。それも、文にその機器の語
     （LED、ライト、ランプ、音量、ボリューム、ミュート、消音、静かに、画面、明るさなど）があり、否定の検査を
     通り、ほかの機器（テレビ、エアコン、照明、電気など）の名前、ミュートの解除、上げ下げの語のない
     「調節」「調整」、`by` の数値がない場合だけ。
   - それ以外で Qwen3 の答えが v0 の正解と違う文は除く。

   これらの規則は Qwen3 の答えを受け入れるかを決める検査で、正解を作るものではありません。付け直した行の
   正解は Qwen3 の答えです（v1.0 全体で train / validation {relabel_kept} 件、このデータセットに入っているのは
   {" / ".join(_n(relabeled[s]) for s in splits)} 件。`relabeled` が true）。誤った付け直しを入れないために、
   本当は v1 の動作として読める文も一部捨てています。
3. **新しい動作の文を足す:** 正解を先にプログラムで決め（single 329、multi_action 204、negation 40、
   correction 25 の spec と、no_action の 14 の話題）、5つの書き手（Qwen3、calm3、ABEJA、Mistral-Nemo-JA、
   ELYZA）にその意味の文を様々な言い方で書かせました。重点は、角度と値の数値（算用数字、漢数字、全角の数字、
   「%」）、絶対（`look`）と相対（`turn`）の言い分け、斜め、首振り、お辞儀、新しい表情、LED、音量、明るさ、
   紛らわしい `[]`（部屋の照明、エアコンの温度、「度」や「%」が角度でない文、命令でない文）です。Qwen3 が
   温度 0 で各文を JSON に変換し、正解と一致した {_n(manifest["new"]["n"])} 件（train と validation の合計）を
   残しました。新しい文の 5% を validation に分けました。
4. **検査:** 長さ、文字化け、否定との矛盾を調べ、重複と、評価セットと重なる文を除きました。

prompt version: 新しい文の生成と、すべての文の検証（読み直し）は `{PROMPT_VERSION}` です。引き継いだ文は、
以前の版の prompt（`action-v0.2`〜`action-v0.5.1`）で書かれました。

## ライセンスと出典

- 本データセット: **CC BY-SA 4.0**
- 文を書いたモデルは、上の表のとおり Apache-2.0 か MIT のオープンモデルです。
- プロジェクトの学習では、このほかに [Amazon MASSIVE](https://github.com/alexa/massive)（ja-JP、CC BY 4.0）の
  発話と、間違えやすい例として集めた Tatoeba（CC BY 2.0 FR）、JESC（CC BY-SA 4.0）、MASSIVE の文を負例
  （`[]`）として使っていますが、本データセットには含めていません。元のコーパスから取得してください。
- データの文章と正解は、上記のオープンモデルとプログラムが作成しました。Claude Code は生成・検査・組み立ての
  コードの作成と実行だけを担当し、データの文章や正解は書いていません。

## 既知の限界

- 合成データのため、実際の利用者の話し方の分布とは異なります。
- 検証役が正しく解釈できた文だけが残るため、解釈の難しい言い回しは少なめです。
- 付け直した行（`relabeled`）の中には、値や量がやや不正確なものが少し残っています（例: 「ちょっと音量あげて」が
  `amount` normal）。
- 引き継いだ文には `turn` や `degrees` などの新しい動作の例がほとんどなく、それらは主に 3. の新しい文にあります。

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
        commit_message=f"JapaneseTinyAgentLM Action synthetic dataset {DATASET_VERSION}",
        delete_patterns=["*.jsonl"],  # a split of an earlier version (v0 test) must not remain
    )
    api.update_repo_settings(repo_id, repo_type="dataset", gated="manual")
    disable_community(api, repo_id, "dataset")  # before it becomes public
    api.update_repo_settings(repo_id, repo_type="dataset", private=False)
    info = api.dataset_info(repo_id)
    community = "off" if community_disabled(api, repo_id, "dataset") else "ON"
    return (
        f"https://huggingface.co/datasets/{repo_id} "
        f"(private={info.private}, gated={info.gated}, community={community})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "publish"])
    parser.add_argument("--data", type=Path, default=Path("datasets/action/v1.0"))
    parser.add_argument("--hf-dir", type=Path, default=Path("datasets/action/v1.0/hf"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("datasets/manifests/action_v1.0.json")
    )
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
