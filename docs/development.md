# 開発環境と運用ルール

最終更新: 2026-09-29

本文書は、開発環境、学習環境、実機操作の運用ルールを定めます。実装の順序は [`roadmap.md`](roadmap.md) を参照してください。

## 1. 役割分担

| 環境 | 用途 | 用途外 |
|---|---|---|
| ローカルの開発 PC | コード作成、unit test、CPU での短い smoke test、小規模モデルの評価、実機への書き込みと計測 | 本番の学習 |
| vast.ai（GPU instance） | 合成データの生成（オープンモデルの推論）、Tokenizer の学習、Base / SFT の学習、学習時の評価 | 認証情報や private data の保管 |
| 実機（M5 スタックチャン K151） | Flash / memory / 速度 / 電力の計測、end-to-end の評価 | — |

学習と合成データの生成は vast.ai で行うと決めています。ローカルの GPU は、本番の学習にも生成にも使いません。

## 2. Python 環境（uv）

- Python の環境と依存関係は **uv** で管理する。
- 依存の追加は **`uv add` だけ**を使う。`uv pip` の subcommand は一切使わない。
- 依存関係は `pyproject.toml` と `uv.lock` だけで管理する。環境構築は `uv sync --locked`、実行は `uv run` で行う。ローカルでも vast.ai 上でも同じ手順にする。
- Python は **3.13** に固定した（`.python-version`、`requires-python = ">=3.13,<3.14"`）。PyTorch 2.14 と SentencePiece の wheel が、Windows と Linux の両方でそろっている。
- PyTorch の取得元は `pyproject.toml` の `[[tool.uv.index]]` と `[tool.uv.sources]` で指定している。Linux（vast.ai）は **cu126** 版、Windows（ローカル）は CPU 版。cu126 にしたのは、vast.ai の host の driver が古くても動くようにするため（cu130 以降は新しい driver が必要）。場当たり的な install はしない。
- 学習・実行基盤のスクリプトが使う CLI（`vastai`）は、`uv add --dev` で開発用の依存として lock している。
- 実機の読み書きに使う `esptool` のような単発のツールは、`uvx --from <package> <command>` で実行する。

### 依存グループ

| グループ | 内容 | 入れ方 |
|---|---|---|
| 本体 | jsonschema、huggingface-hub、openai（vLLM の OpenAI 互換 API の client） | `uv sync --locked` |
| `dev` | pytest、ruff、vastai | 既定で入る |
| `train` | torch、sentencepiece、numpy | `uv sync --locked --group train`。データ生成用の instance では入れない（torch が数 GB あるため） |

- ローカルで全部入れるときは `uv sync --locked --all-groups`。
- `uv sync` は、指定していないグループのパッケージを削除する。学習のコードを動かす前は `--group train` か `--all-groups` を付ける。
- 確認のコマンド: `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest`。

### Windows で日本語を扱うときの注意

- Windows のコンソールは既定で UTF-8 ではないため、日本語が文字化けすることがある。Python では `PYTHONIOENCODING=utf-8` を設定するか、結果を UTF-8 のファイルに書いて確認する。
- ファイルの読み書きでは、必ず `encoding="utf-8"` を指定する。
- C の host runtime には、日本語を argv で渡さない。UTF-8 のファイルか stdin で渡す。TinyLM-Bench では、needle-2-esp32 の C host に argv で日本語を渡すと制限があった。

### ツールのバージョン（2026-09-29 に確認）

| ツール | 最新版 | 開発 PC の版 | 方針 |
|---|---|---|---|
| uv | 0.12.20 | 0.12.20（M1 で更新） | `uv_build` も 0.12 系 |
| PyTorch | 2.14.0（2026-09-02。Python 3.15 まで wheel あり） | 2.14.0+cpu（lock 済み） | Linux は 2.14.0+cu126 |
| vastai CLI | 1.8.2 | 1.8.2（`uv run vastai`） | 端末に別途入っている 1.5.6 は使わない |
| esptool | 5.4.0 | `uvx` で都度取得 | 5 系 |
| ESP-IDF | 6.1（2026-08-27） | 未導入 | **v5.5.5 に固定**（§7） |

## 3. 認証情報

- API key などの秘密情報は、リポジトリ直下の `.env` に置く。`.env` は `.gitignore` で除外済み。
- 必要な変数名は下表に記載する。雛形の `.env.example` は、権限の設定で Claude Code から作成できなかったため、この表を雛形の代わりとする。

| 変数 | 用途 |
|---|---|
| `VAST_API_KEY` | vast.ai の API key。公式 CLI（`vastai`）がこの環境変数を直接読む |
| `HF_TOKEN` | Hugging Face の access token。organization `japanese-data-analyze` への write 権限が必要。合成データとモデルのアップロードに使う。vast.ai の instance には持ち込まない |

`vastai` CLI は、API key を次の優先順位で決めます。

1. `--api-key` flag
2. 環境変数 `VAST_API_KEY`
3. `~/.config/vastai/vast_api_key`
4. `~/.vast_api_key`

`.env` の key は、端末に保存済みの key より優先されます。別アカウントの key を置くと、そのアカウントに課金されます。

## 4. vast.ai の運用ルール

実行基盤は `src/jtalm/infra/` にあります（[`roadmap.md`](roadmap.md) の M2.5、完了済み）。vast.ai は、学習に加えて合成データの生成にも使います（[`data.md`](data.md) §5）。

```sh
# job の一覧は src/jtalm/infra/jobs.py。--approve-dph は承認した時間単価の上限（これを超える GPU は選ばない）
uv run python -m jtalm.infra.job smoke --approve-dph 0.35
uv run python -m jtalm.infra.job gen_action_v0 --approve-dph 1.10
```

- **動き:** 条件に合う最安の offer を選ぶ → instance を作る → 起動を待つ → `HEAD` を `git archive` で転送 → 各手順を実行 → `artifacts/` を回収する。最後に、成功しても失敗しても必ず削除し、削除を確認する。
- **記録:** 結果は `runs/vast/<job>-<時刻>/`（Git の管理外）に置く。`run.json` には、offer、driver、各手順の終了コードと秒数、時間、費用の見積もり、削除の確認を記録する。失敗したときは、container のログも保存する。
- **SSH:** 手元の `~/.ssh/id_ed25519_vast` を使う（アカウントに登録済み）。vLLM の image は `/root` の権限が緩く、sshd が `authorized_keys` を拒否するので、起動時（onstart）に権限を直している。
- **API key:** `vastai` には、コマンドの引数ではなく環境変数で渡す。process の一覧に key が出ないようにするため。
- **既存の instance:** 同じアカウントに、別のプロジェクトの instance がある。本プロジェクトの実行基盤は、自分で作った instance の ID だけを削除・確認する。
- **依存:** instance 上では `uv sync --locked --no-dev` を使う（学習のときは `--group train` を足す）。

1. **実行前の確認:** 学習ならローカルの CPU で数 step の smoke test、データの生成なら少数の生成と検査を通してから instance を借りる。バグで課金されるのを防ぐため。
2. **作成前の承認:** Instance を作る前に、GPU の種類、時間単価、想定時間、上限費用を提示して承認を得る。
3. **Instance の削除:** 結果を回収したら、ローカル側の orchestrator から必ず instance を削除する。実行時間の上限も設ける。
4. **認証情報を持ち込まない:** vast.ai の host は第三者のマシンなので、`.env`、GitHub の認証情報、Ralomi など private project のデータは転送しない。コードは commit 済みの状態を `git archive` で固めて転送する。
5. **再現性の記録:** 各 run について、commit hash、config、Docker image、GPU の種類、driver、費用、所要時間を記録する。
6. **Instance の種類:** 最初は on-demand を使う。checkpoint からの resume が確実に動くと確認できてから、interruptible に切り替える。
7. **成果物の管理:** Checkpoint や学習済みの重みは Git に入れない（`*.pt`、`*.safetensors`、`checkpoints/` などは除外済み）。公開するものは Hugging Face で管理する。

## 5. 実機操作のルール

対象機の詳細は [`hardware.md`](hardware.md) を参照してください。

1. **書き込み前のバックアップ:** Firmware を書き込む前に、Flash 16MB 全体を `read-flash` でバックアップし、SHA-256 を記録する。保存先は `backups/`（Git の管理外）とする。
2. **Servo を動かすときの制限:** Servo を動かす試験では、公式 firmware の角度制限の内側で動かす。連続回転 mode は使わない。
3. **Serial port の扱い:** Serial port を開くと chip が reset されることがある。計測中に不用意に接続し直さない。
4. **計測値の記録:** 計測値には、board、CPU clock、PSRAM mode、firmware の識別子（commit または ELF の hash）、model hash、prompt / context、生成長、warm / cold の区別を添える。

## 6. ライセンス

| 対象 | ライセンス |
|---|---|
| ソースコードと文書（本リポジトリ） | Apache License 2.0（Copyright 2026 ayutaz） |
| モデルの重み（Hugging Face の `japanese-data-analyze` で公開） | **CC BY-SA 4.0**。商用利用は可能。利用時の表示が必要で、改変したモデルも同じライセンスで公開する必要がある |
| 合成データセット（Hugging Face の `japanese-data-analyze` で公開） | **CC BY-SA 4.0**。public、manual gate（[`data.md`](data.md) §6） |
| 第三者のコード | それぞれの条件に従う（例: 公式 StackChan firmware は MIT、`stackchan-idf` は BSL-1.0）。採用前に確認する |

### 学習データの条件

重みを CC BY-SA 4.0 で公開するため、学習データは次の条件を満たすものだけを使います。

| 使える | 使えない |
|---|---|
| CC BY-SA、CC BY、CC0、パブリックドメイン、MIT / Apache-2.0 などの寛容なライセンスのデータ | 非営利限定（NC）や改変禁止（ND）のデータ |
| Apache-2.0 / MIT のオープンモデルで生成したデータ（学習データは Qwen3 と予備の gpt-oss、評価セットは llm-jp-3.1-13b-instruct4。[`data.md`](data.md) §3） | Claude（Claude Code を含む）、ChatGPT（Codex を含む）、Gemini などの、利用規約で学習への利用を制限しているサービスの出力 |
| — | 出典やライセンスが分からないデータ |

- 具体的な方針、規約の調査結果、使うデータとモデルの一覧は [`data.md`](data.md) にまとめています。
- すべてのデータについて、出典、ライセンス、作り方、件数を manifest（`datasets/manifests/`）に記録する。
- Chat の事前学習の corpus として、日本語版 Wikipedia（CC BY-SA。現行は 4.0 で、Hugging Face 上の既存の dump は 3.0 と GFDL の表記）はライセンス上両立する。
- **Claude Code の役割（2026-09-29 決定）:** Claude Code は、生成、検査、分割を行うコードを作って実行するだけにとどめ、学習データの文章やラベルは書かない。Anthropic の Usage Policy が、事前の許可なく出力を AI モデルの学習に使うことを禁止しているため（[`data.md`](data.md) §2）。
- 重みを組み込んだ firmware を開発者が配布する場合、重みの部分には CC BY-SA 4.0 の表示義務がかかる。重みは独立したファイルとして配布し、firmware のコードとは分けて扱う想定を、モデルカードに明記する。

## 7. 実機の build 環境（ESP-IDF）

- ESP-IDF は **v5.5.5** に固定する。K151 に対応している公式 `m5stack/StackChan`（v5.5.4）と `stackchan-idf`（v5.5.5 で検証、CI も v5.5.5）に合わせるためで、最新の v6.1 は使わない。
- Build は、公式 Docker image の `espressif/idf:v5.5.5` で行う。開発 PC に ESP-IDF を直接導入しなくて済み、CI とも同じ環境にできる。
- 書き込みと serial での計測は、Windows から `esptool`（`uvx`）で行う。
