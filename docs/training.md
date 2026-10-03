# 再現手順（データ生成・学習・評価・公開）

公開している Action LM 3M を、データの生成から学習、量子化、`.jtlm` の書き出し、評価、公開用のパッケージまで作り直す手順です。データの方針と各版の内容は [`data.md`](data.md)、モデルと `.jtlm` 形式は [`architecture.md`](architecture.md)、結果は [`evaluation.md`](evaluation.md) を参照してください。

学習済みの重み、tokenizer、`.jtlm` は [Hugging Face のモデル](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M) にあります。モデルを使うだけなら、この手順は必要ありません。

コマンドは bash 用です（Windows では Git Bash か WSL で実行してください）。

## 全体の流れ

各段階が作るファイル（`datasets/action/`、`datasets/raw/`、`tokenizer/out/`、`runs/` の下）は Git の管理外です。

| 順 | 段階 | 主な module | 作るもの |
|---|---|---|---|
| 1 | 外部データの取得 | `jtalm.data.massive`（自動）、手動の download | `datasets/downloads/` |
| 2 | 合成データの生成（GPU と vLLM が必要。各版と評価セットの文） | `jtalm.data.generate` | `datasets/raw/` |
| 3 | データ v0 の組み立て | `jtalm.data.build` | `datasets/action/v0` |
| 4 | Tokenizer の学習 | `jtalm.model.tokenizer` | `tokenizer/out/action_v0_sp2048.model` |
| 5 | データ v0.3 / v0.4 と、v0.4 の 3M の学習（間違えやすい例の収集に使う） | `jtalm.data.build --base`、`jtalm.model.train` | `datasets/action/v0.3`、`v0.4`、v0.4 の `best.pt` |
| 6 | 人が書いた評価セット human v1 | `jtalm.data.human_eval` | `datasets/action/human_v1` |
| 7 | 評価セット eval v2 | `jtalm.data.generate`、`jtalm.data.eval_v2` | `datasets/action/eval_v2` |
| 8 | 間違えやすい例の収集とデータ v0.5 / v0.5.1 | `jtalm.model.mine`、`jtalm.data.build --exclude` | `datasets/action/v0.5`、`v0.5.1` |
| 9 | 採用したモデルの学習 | `jtalm.model.train` | `best.pt` |
| 10 | 量子化、`.jtlm` の書き出し、C runtime との一致の確認 | `jtalm.model.quantize`、`export`、`parity` | `best_q4_g64.pt`、`3m_q4_g64.jtlm` |
| 11 | 評価と誤差の範囲 | `jtalm.model.evaluate`、`eval_suite`、`jtalm.eval.bootstrap`、`jtalm.eval.consistency` | 評価の表 |
| 12 | 公開用のパッケージ | `jtalm.model.release` | 公開用のディレクトリ |

表の番号は、下の見出しの番号と同じです。

## 必要な環境

### Python（uv）

- Python の環境と依存関係は [uv](https://docs.astral.sh/uv/) で管理しています。Python は **3.13** です（`.python-version`、`requires-python = ">=3.13,<3.14"`）。
- 依存を追加するときは `uv add` を使います。`uv pip` は使いません。

| グループ | 内容 | 入れ方 |
|---|---|---|
| 本体 | jsonschema、huggingface-hub、openai（vLLM の OpenAI 互換 API の client） | `uv sync --locked` |
| `dev` | pytest、ruff | 既定で入る |
| `train` | torch、sentencepiece、numpy、safetensors | `uv sync --locked --group train` |

```sh
uv sync --locked --group train     # 学習・評価をする場合
uv sync --locked --all-groups      # すべて入れる場合
uv run ruff check src tests firmware/tools          # CI と同じ lint
uv run ruff format --check src tests firmware/tools
uv run --group train pytest
```

- `uv sync` は、指定していないグループのパッケージを削除します。学習や評価の module を動かす前は `--group train` か `--all-groups` を付けてください。以下のコマンドは `uv run --group train` で実行します。
- PyTorch の取得元は `pyproject.toml` で指定しています。Linux と Windows は CUDA 12.6 版（cu126）、macOS は CPU 版です。

### GPU と CPU

- **学習:** CUDA の GPU があれば bf16 の autocast で学習します。cu126 版の torch には Blackwell（sm_120）の kernel がないので、学習には compute capability 8.0〜9.0（Ampere〜Hopper）の GPU を使いました。3M〜20M のモデルは batch 64 でも VRAM を 1GB も使いません。CPU でも動きますが、時間がかかります。
- **評価、量子化、書き出し:** CPU で動きます。
- **データの生成:** vLLM の OpenAI 互換サーバーが必要です。vLLM は本プロジェクトの依存には入っていません。生成には Docker image `vllm/vllm-openai:v0.30.0`（CUDA 13.0。host の driver が CUDA 13.0 に対応している必要があります）を使いました。bf16 で 61〜65GB ある書き手（Qwen3、ABEJA、ELYZA）は、80GB 級の GPU 1枚で動かしました。
- **C runtime との一致の確認:** Docker と image `espressif/idf:v5.5.5` を使います。

### GPU がない場合にできること

学習データと評価セット（v0 eval、human v1、eval v2）を作り直すには、vLLM で Qwen3-30B-A3B-Instruct-2507 などの書き手と検証役を動かす GPU が要ります。v0.3 以降の学習データ、human v1、eval v2 は配布していません。[Hugging Face のデータセット](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth) の test は、v0 eval から MASSIVE の行を除いた合成の文（1,039件）だけで、項目名も評価の module が読むファイル（`prompt`、`expected`）とは違います（`input`、`output`）。GPU がなければ、[`results/`](../results/README.md) の結果を確かめることと、公開モデルでの推論（[README](../README.md) の「すぐに試す」）ができます。

### Windows で日本語を扱うとき

- Windows のコンソールは既定で UTF-8 ではないため、日本語が文字化けすることがあります。`PYTHONIOENCODING=utf-8` を設定するか、結果を UTF-8 のファイルに書いて確認してください。
- C の host runtime には、日本語を argv で渡さず、UTF-8 のファイルか stdin で渡してください。

### 秘密情報（`.env`）

ローカルでの生成、学習、評価には秘密情報は要りません。次の2つは任意の手順でだけ使います。`.env.example` を `.env` にコピーして値を入れてください（`.env` は Git の管理外です）。環境変数に同じ名前で設定しても読み込みます。

| 変数 | 使う場面 |
|---|---|
| `HF_TOKEN` | Hugging Face への公開（`jtalm.model.release publish`、`jtalm.data.publish publish`） |
| `VAST_API_KEY` | vast.ai での実行（下の「vast.ai での実行」） |

## 1. 外部データの取得

MASSIVE ja-JP は、使う module（`jtalm.data.build`、`jtalm.model.tokenizer`、`jtalm.data.human_eval`）が初回に自動で取得し、`datasets/downloads/massive/` に置きます。

human v1 と間違えやすい例の収集に使うコーパスは、各配布元から手動で取得し、次の場所に置いてください（`jtalm.data.human_eval --root` で場所を変えられます）。

| コーパス | 置き場所（`datasets/downloads/human_eval/` の下） |
|---|---|
| [Tatoeba](https://tatoeba.org/en/downloads) の日本語文 | `jpn_sentences.tsv` |
| [JESC](https://nlp.stanford.edu/projects/jesc/) | `raw/raw` |
| [YJ_AmbigDialogue](https://github.com/yahoojapan/YJ_AmbigDialogue) | `YJ_AmbigDialogue/data.txt` |
| [J-CRe3](https://github.com/riken-grp/J-CRe3) | `J-CRe3/transcriptions/*/*.txt` |
| [DSLC3](https://dialog-system-live-competition.github.io/dslc3/data.html) | `dslc3/` の下の `*.log.json` |

## 2. 合成データの生成（vLLM）

### 生成の仕組み

`jtalm.data.generate` は vLLM のサーバー（既定は `http://localhost:8000/v1`）に依頼を送ります。GPU に載せるモデルは一度に1つで済むように、4つの phase に分かれています。

| phase | 動かすモデル（config の項目） | 入力 → 出力（`--out` の下） |
|---|---|---|
| `eval-gen` | `eval_generator`（llm-jp） | → `eval_gen.jsonl` |
| `train-gen` | `train_generator`（書き手） | → `train_gen.jsonl` |
| `eval-verify` | `train_generator`（Qwen3） | `eval_gen.jsonl` → `eval_raw.jsonl` |
| `train-verify` | config の `train_verifier` が指すモデル（Qwen3） | `train_gen.jsonl` → `train_raw.jsonl` |

vLLM には、config の `served_name`（`qwen`、`llmjp`、`calm3`、`sarashina`、`abeja`、`nemoja`、`granite`、`elyza`）を `--served-model-name` として渡します。

```sh
# 例: calm3 に v0.4 の学習データを書かせ、Qwen3 で検証する
vllm serve cyberagent/calm3-22b-chat --served-model-name calm3 --max-model-len 4096
uv run python -m jtalm.data.generate --phase train-gen \
    --config configs/action_v04_calm3.json --out datasets/raw/v04/raw04_calm3 --workers 256
# （calm3 のサーバーを止めてから）
vllm serve Qwen/Qwen3-30B-A3B-Instruct-2507 --served-model-name qwen --max-model-len 4096
uv run python -m jtalm.data.generate --phase train-verify \
    --config configs/action_v04_calm3.json --out datasets/raw/v04/raw04_calm3 --workers 256
```

各 phase は `--out` の下に `summary_<phase>.json` を書き、`jtalm.data.build` はそれを manifest に記録します。

### 版ごとの生成

| 版 | config | phase |
|---|---|---|
| v0 | `configs/action_v0.json` | llm-jp で `eval-gen`、Qwen3 で `train-gen`・`eval-verify`・`train-verify`（`--out datasets/raw/v0/raw`） |
| v0（否定の追加） | `configs/action_v0_negation_topup.json` | Qwen3 で `train-gen`・`train-verify`（`--out datasets/raw/v0/raw_negation`） |
| v0.3 | `configs/action_v03_{calm3,sarashina,qwen}.json` | 各書き手で `train-gen`、Qwen3 で `train-verify` |
| v0.4 | `configs/action_v04_{abeja,nemoja,granite,elyza,calm3,sarashina,qwen}.json` | 同上 |
| v0.5 | `configs/action_v05_{abeja,nemoja,elyza,calm3,sarashina,qwen}.json` | 同上（`granite` の config もありますが、v0.5 には入っていません） |
| v0.5（間違えやすい例） | `configs/action_v05_mined.json` | Qwen3 で `train-verify` だけ（下の「8. 間違えやすい例の収集とデータ v0.5 / v0.5.1」） |
| v0.5.1 | `configs/action_v051_{abeja,calm3,qwen}.json` | 各書き手で `train-gen`、Qwen3 で `train-verify` |
| human v1 | `configs/human_eval_v1.json` | Qwen3 で `train-verify` だけ（下の「6. 人が書いた評価セット（human v1）」） |
| eval v2 | `configs/eval_v2.json` | llm-jp で `eval-gen`、Qwen3 で `eval-verify` |

`--out` の既定値は `artifacts/raw` です。v0 の2つの `--out` は、次の「3. データ v0 の組み立て」の `--raw` に合わせています。ほかの版も、組み立てのコマンドの `--raw` と同じ場所（`datasets/raw/v03/raw_calm3` など）に書いてください。

生成は seed を固定していますが、再生成した文が元のファイルと同じになる保証はありません。元のファイルとの一致は、manifest の sha256 で確かめられます。

## 3. データ v0 の組み立て

```sh
uv run python -m jtalm.data.build \
    --raw datasets/raw/v0/raw datasets/raw/v0/raw_negation \
    --extra-config configs/action_v0_negation_topup.json
```

既定で `configs/action_v0.json` を読み、`datasets/action/v0`（`train.jsonl`、`val.jsonl`、`eval.jsonl`）と `datasets/manifests/action_v0.json` を書きます。検証の不一致、否定との矛盾、重複を除き、MASSIVE の負例を加え、validation を分け、ルールベースの baseline を評価します。

## 4. Tokenizer の学習

```sh
uv run --group train python -m jtalm.model.tokenizer --vocab 2048 4096 8192
```

- `datasets/action/v0` の train と validation の入力文と出力、MASSIVE ja-JP の train の発話で学習し、`tokenizer/out/action_v0_sp<語彙>.model` と比較の表（`report.json`）を書きます。評価セットは使いません。
- 採用したのは語彙 2,048 の `action_v0_sp2048.model` です（sha256 `61482f90…`、`datasets/manifests/tokenizer_action_v0.json`）。決め方は [`architecture.md`](architecture.md) を参照してください。
- checkpoint は tokenizer の sha256 を持っており、評価と書き出しの module は、違う tokenizer を渡すと止まります。公開しているモデルと同じ tokenizer で作り直すときは、[Hugging Face のモデル](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M) の `tokenizer.model`（`action_v0_sp2048.model` と同じファイル）を `tokenizer/out/action_v0_sp2048.model` に置いてください。

以下では、`TOK=tokenizer/out/action_v0_sp2048.model` とします。

## 5. データ v0.3 / v0.4 と、v0.4 のモデル

前の版のファイルを残したまま、学習データだけを追加します（`--base`）。

```sh
uv run python -m jtalm.data.build --base datasets/action/v0 \
    --raw datasets/raw/v03/raw_calm3 datasets/raw/v03/raw_sarashina datasets/raw/v03/raw_qwen \
    --config configs/action_v03_qwen.json \
    --extra-config configs/action_v03_calm3.json configs/action_v03_sarashina.json \
    --out datasets/action/v0.3 --manifest datasets/manifests/action_v0.3.json

uv run python -m jtalm.data.build --base datasets/action/v0.3 \
    --raw datasets/raw/v04/raw04_{abeja,nemoja,granite,elyza,calm3,sarashina,qwen} \
    --config configs/action_v04_qwen.json \
    --extra-config configs/action_v04_{abeja,nemoja,granite,elyza,calm3,sarashina}.json \
    --out datasets/action/v0.4 --manifest datasets/manifests/action_v0.4.json
```

v0.5 の間違えやすい例の収集には、v0.4 で学習した 3M を使います（seed 0、15 epoch）。

```sh
uv run --group train python -m jtalm.model.train --size 3m --tokenizer $TOK \
    --data datasets/action/v0.4 --lr 1e-3 --epochs 15 --seed 0 --out runs/local/v04/3m
```

## 6. 人が書いた評価セット（human v1）

```sh
# 候補を抜き出す（v0.4 の train / val / eval と重なる文は除く）
uv run python -m jtalm.data.human_eval candidates      # → datasets/raw/human_v1/train_gen.jsonl
# Qwen3（served name: qwen）で検証する
uv run python -m jtalm.data.generate --phase train-verify \
    --config configs/human_eval_v1.json --out datasets/raw/human_v1 --workers 256
# 規則の正解と一致したものだけを残す
uv run python -m jtalm.data.human_eval build --raw datasets/raw/human_v1
```

`datasets/action/human_v1/eval.jsonl` と `datasets/manifests/action_human_v1.json` を書きます。

## 7. 評価セット v2

```sh
# llm-jp（served name: llmjp）が書く
uv run python -m jtalm.data.generate --phase eval-gen \
    --config configs/eval_v2.json --out datasets/raw/eval_v2 --workers 256
# Qwen3（served name: qwen）が検証する
uv run python -m jtalm.data.generate --phase eval-verify \
    --config configs/eval_v2.json --out datasets/raw/eval_v2 --workers 256
uv run python -m jtalm.data.eval_v2 --raw datasets/raw/eval_v2
```

`datasets/action/eval_v2/<パターン>.jsonl`（12ファイル）と `datasets/manifests/action_eval_v2.json` を書きます。v0.4 の学習データ、v0 eval、human v1 と重なる文は除きます。`datasets/action/v0.5` がすでにあると、それとも重なりを除くので、v0.5 より先に作ってください。

## 8. 間違えやすい例の収集とデータ v0.5 / v0.5.1

```sh
# 人が書いた文の候補（評価用に取り分けた文を除く）→ datasets/raw/mine_pool/pool.jsonl
uv run python -m jtalm.data.human_eval pool
# v0.4 の 3M（grammar + gate 0.97004）が動作を出力した文を集める
uv run --group train python -m jtalm.model.mine --ckpt runs/local/v04/3m/best.pt \
    --tokenizer $TOK --pool datasets/raw/mine_pool/pool.jsonl --out datasets/raw/v05/raw05_mined
# Qwen3 が [] と確かめた文だけを残す
uv run python -m jtalm.data.generate --phase train-verify \
    --config configs/action_v05_mined.json --out datasets/raw/v05/raw05_mined --workers 256
```

v0.5 と v0.5.1 は、評価セットを除外して組み立てます。

```sh
EXCLUDE="datasets/action/human_v1/eval.jsonl datasets/action/eval_v2/*.jsonl"

uv run python -m jtalm.data.build --base datasets/action/v0.4 \
    --raw datasets/raw/v05/raw05_{abeja,nemoja,elyza,calm3,sarashina,qwen,mined} \
    --config configs/action_v05_qwen.json \
    --extra-config configs/action_v05_{abeja,nemoja,elyza,calm3,sarashina,mined}.json \
    --exclude $EXCLUDE \
    --out datasets/action/v0.5 --manifest datasets/manifests/action_v0.5.json

uv run python -m jtalm.data.build --base datasets/action/v0.5 \
    --raw datasets/raw/v051/raw051_{abeja,calm3,qwen} \
    --config configs/action_v051_qwen.json \
    --extra-config configs/action_v051_{abeja,calm3}.json \
    --exclude $EXCLUDE \
    --out datasets/action/v0.5.1 --manifest datasets/manifests/action_v0.5.1.json
```

## 9. 学習

採用したモデルは、データ v0.5.1 で次のように学習しました。

```sh
uv run --group train python -m jtalm.model.train --size 3m --tokenizer $TOK \
    --data datasets/action/v0.5.1 --lr 1e-3 --epochs 12 --seed 0 --out runs/local/v051/3m
```

- `--size` は `3m`（d_model 192、7層、3,148,608 parameter）、`5m`、`20m` から選びます。
- そのほかの設定は既定値です: batch 64、AdamW、warmup 200 step のあと cosine で `--lr` の 0.1 倍まで下げる、weight decay 0.1、dropout 0.1。
- 2 epoch ごとに validation を greedy で生成し、完全一致が最も高い checkpoint を `best.pt` として残します（同点なら validation loss の低いほう）。評価セットは読みません。`--out` には `log.jsonl` と `summary.json` も書きます。
- 誤差の範囲を出すときは、`--seed` を 0〜4 にして5回学習します。
- 動作確認には `--max-steps 20 --device cpu` のように step 数を絞ります。

## 10. 量子化、`.jtlm` の書き出し、一致の確認

```sh
# INT4（64個ずつの group、fp16 の scale）。best.pt の隣に best_q4_g64.pt を書く
uv run --group train python -m jtalm.model.quantize --ckpt runs/local/v051/3m/best.pt --bits 4

# firmware と C runtime が読む .jtlm（→ runs/local/v051/export/3m_q4_g64.jtlm）
uv run --group train python -m jtalm.model.export --ckpt runs/local/v051/3m/best.pt \
    --tokenizer $TOK --bits 4 --out runs/local/v051/export

# C runtime と PyTorch の出力の一致（Docker の中で runtime/host を build して比べる）
uv run --group train python -m jtalm.model.parity --ckpt runs/local/v051/3m/best.pt \
    --tokenizer $TOK --bits 4 --out runs/local/v051/parity \
    --docker espressif/idf:v5.5.5 --build
```

- 採用したモデルの `.jtlm` は 1,971,456 bytes です。形式は [`architecture.md`](architecture.md) を参照してください。
- `parity` は、tokenizer の結果、生成した token 列、出力の文字列を比べ、実機への移植用に `golden.jsonl` を書きます。`--docker` を使うとき、`--out` はリポジトリの中に置いてください。`--limit 50` で件数を絞れます。
- C runtime の build は [`../runtime/host/README.md`](../runtime/host/README.md)、firmware への書き込みは [`../firmware/README.md`](../firmware/README.md) を参照してください。

## 11. 評価

### 評価の表（`jtalm.model.evaluate`）

```sh
uv run --group train python -m jtalm.model.evaluate \
    --ckpt runs/local/v051/3m/best.pt runs/local/v051/3m/best_q4_g64.pt --tokenizer $TOK \
    --cases datasets/action/v0/eval.jsonl --val datasets/action/v0.5.1/val.jsonl \
    --modes plain grammar gate --out runs/local/v051/eval
```

- `plain` は制約なし、`grammar` は grammar で制約した greedy、`gate` は grammar に確信度の gate（confidence gate）を加えたものです。
- ルールベースの baseline と、TinyLM-Bench の16件での既存モデルとの比較も同じ表に出します。

### すべての評価セット（`jtalm.model.eval_suite`）

```sh
uv run --group train python -m jtalm.model.eval_suite \
    --ckpt runs/local/v051/3m/best_q4_g64.pt --tokenizer $TOK \
    --val datasets/action/v0.5.1/val.jsonl --out runs/local/suite_v051_3m_q4
```

- v0 eval、human v1、eval v2 の12パターンを、grammar と gate で評価し、`suite.md` と `suite.json`、評価セットごとの `*_predictions.jsonl` を書きます。
- **gate の閾値は validation だけで選びます。** validation の完全一致の低下が 0.5 point 以内に収まる最大の閾値です。採用したモデルでは 0.86808 になりました（firmware の既定値は千分率で 868）。`--val` の既定値は v0.4 の validation なので、モデルの学習に使った版の validation を渡してください。閾値を固定するときは `--gate 0.86808` を使います。

### 誤差の範囲（`jtalm.eval.bootstrap`）

`eval_suite` の出力ディレクトリを入力にします。

```sh
# 1つのモデル: 評価セットごとの 95% bootstrap 区間
uv run python -m jtalm.eval.bootstrap ci runs/local/suite_v051_3m_q4
# 同じ評価セットでの2つのモデルの差（B − A）の paired bootstrap
uv run python -m jtalm.eval.bootstrap diff runs/local/suite_v04_3m_q4 runs/local/suite_v051_3m_q4
# 複数の seed: 平均と標準偏差
uv run python -m jtalm.eval.bootstrap seeds runs/local/suite_v051_3m_q4 runs/local/suite_v051_3m-s1_q4 ...
```

- 既定は 2,000 回の resample（`--n-boot`）で、`--out` で結果を Markdown に保存できます。
- bootstrap 区間は評価セットの標本のばらつきだけを表し、学習の seed によるばらつきは含みません。両方を見てください。公開している結果は `results/v051_action/`（`ci_3m.md`、`seeds_3m.md`、`diff_v04_v051.md`、`diff_v05_v051.md`）にあります。

### 小さな分類器との比較（`jtalm.model.classifier`）

```sh
# CPU で1 seed あたり約7分。出力は eval_suite と同じ形（bootstrap と consistency でも読める）
uv run --group train python -m jtalm.model.classifier --train datasets/action/v0.5.1/train.jsonl     --val datasets/action/v0.5.1/val.jsonl --seed 0 --out runs/local/classifier_v051_s0
```

### 言い換えへの一貫性（`jtalm.eval.consistency`）

```sh
# seed 0。複数の suite を渡すと平均と標準偏差
uv run python -m jtalm.eval.consistency runs/local/suite_v051_3m_q4 --out paraphrase_3m.md
```

- 評価セットごとに、正解が同じ依頼の組の中で出力がそろった割合（pair agreement）と、ルールベースの同じ値を出します。定義は [evaluation.md](evaluation.md) の「言い換えへの一貫性」にあります。結果は `results/v051_action/`（`paraphrase_3m.md`、`paraphrase_seeds_3m.md`）にあります。

## 12. 公開用のパッケージ（`jtalm.model.release`）

```sh
# 公開するファイルとモデルカードを用意する
uv run --group train python -m jtalm.model.release prepare \
    --ckpt runs/local/v051/3m/best.pt --ckpt-q4 runs/local/v051/3m/best_q4_g64.pt \
    --jtlm runs/local/v051/export/3m_q4_g64.jtlm --suite runs/local/suite_v051_3m_q4 \
    --gate 0.86808 --out runs/release/action_3m
# 用意したディレクトリのモデルを動かして確かめる
uv run --group train python -m jtalm.model.release run runs/release/action_3m 右を向いて
# 公開する（--confirm と HF_TOKEN が必要）
uv run python -m jtalm.model.release publish runs/release/action_3m --repo <user>/<repo> --confirm
```

- `prepare` は、評価したとおりの INT4 の重み（safetensors）、量子化前の fp32 の重み、tokenizer、Action schema、`.jtlm`、評価の表、モデルカード、firmware の書き込み用イメージ（firmware と `.jtlm` を 0x0 から書く1ファイル）を書きます。firmware の build ディレクトリ（既定は `firmware/jtalm_action/build_release`）が必要です。[`../firmware/README.md`](../firmware/README.md) の手順で、build 先を `build_release` にして build するか（下）、`--firmware-build firmware/jtalm_action/build` を渡してください。

  ```sh
  # リポジトリの root で（Windows の Git Bash では firmware/README.md の書き方に合わせる）
  docker run --rm -e IDF_COMPONENT_MANAGER=0 -v "$PWD:/w" -w /w/firmware/jtalm_action \
    espressif/idf:v5.5.5 idf.py -B build_release build
  ```

- `publish` は `--confirm` がないと止まります。リポジトリを private で作ってアップロードし、Community contributions（Discussions と Pull Requests）を off にしたことを確かめてから public にします。`--repo` の既定値は公開済みのモデルのリポジトリなので、自分のリポジトリを指定してください。

## vast.ai での実行（任意）

上の生成と学習は、GPU があれば手元で実行できます。GPU を借りて実行する場合のために、[vast.ai](https://vast.ai/) で job を実行する runner（`src/jtalm/infra/`）があります。vast.ai の CLI（`vastai`）はプロジェクトの依存に入れていません（古い版の pillow と cryptography を固定するため）。PATH にあればそれを使い、なければ `uv tool run --from vastai==1.8.2 vastai` で実行します。

```sh
uv run python -m jtalm.infra.job <job> --approve-dph <price>
```

- `--approve-dph` は必須で、1時間あたりの料金（USD）の上限です。job の条件（GPU のメモリ、CUDA の版、disk など）に合い、この上限以下の offer の中から最も安いものを選びます（`--pick` で何番目かを選べます）。上限以下の offer がなければ、instance を作らずにエラーで終わります。
- 動き: instance を作る → 起動を待つ（30分以内に起動しなければ削除して次の offer を試す。最大3回）→ commit 済みの `HEAD` を `git archive` で送る → `JobSpec.uploads` のファイル（Git の管理外のデータなど）を送り、sha256 を照合する → 各手順を SSH から切り離して順に実行する → `artifacts/` を回収する → instance を削除し、削除を確かめる。失敗しても、`artifacts/` の回収と instance の削除を試みます。job ごとに実行時間の上限があります。
- 結果は `runs/vast/<job>-<時刻>/` に置き、`run.json` に commit、offer、driver の版、各手順の終了コードと秒数、削除の確認を記録します。
- 必要なもの: `.env` か環境変数の `VAST_API_KEY`、vast.ai のアカウントに登録した SSH 鍵 `~/.ssh/id_ed25519_vast`。`.env` と commit していない変更は送りません。
- instance 上では `uv sync --locked --no-dev`（学習では `--group train` を追加）で環境を作ります。image は `vllm/vllm-openai:v0.30.0` で、CUDA 13.0 に対応した host だけを選びます。学習の job は compute capability 8.0〜9.0 の GPU に限ります。

job の名前は、`smoke`（動作確認）、`gen_action_<版>`（データの生成と検証。例: `gen_action_v04`）、`train_action_<版>`（学習と評価。例: `train_action_v051`、seed を変える `train_action_v051_seeds`、データ量を変える `train_action_v0_scaling`）、`verify_human_v1`、`gen_eval_v2` の形です（一覧は `src/jtalm/infra/jobs.py`）。

- job の手順は `src/jtalm/infra/jobs.py` にあり、上の手元の手順と同じ module を呼びます。生成の job は書き手ごとに vLLM を起動し、終わると重みを消してから次の書き手に進みます。
- `gen_action_v05` は、v0.4 の 3M の checkpoint と収集用の候補を `jobs.py` の `V04_CKPT`、`MINE_POOL` のパスから送ります。自分で学習した checkpoint を使うときは、パスを書き換えてください。
- 学習の job は、同じ GPU で複数の学習を並列に走らせます（設定は変えません）。
