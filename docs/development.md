# 開発環境と運用ルール

最終更新: 2026-09-29

本文書は、開発環境、学習環境、実機操作の運用ルールを定めます。実装の順序は [`roadmap.md`](roadmap.md) を参照してください。

## 1. 役割分担

| 環境 | 用途 | 用途外 |
|---|---|---|
| ローカルの開発 PC | コード作成、unit test、CPU での短い smoke test、小規模モデルの評価、実機への書き込みと計測 | 本番の学習 |
| vast.ai（GPU instance） | Tokenizer の学習、Base / SFT の学習、学習時の評価 | 認証情報や private data の保管 |
| 実機（M5 スタックチャン K151） | Flash / memory / 速度 / 電力の計測、end-to-end の評価 | — |

学習は vast.ai で行うと決めています。ローカルの GPU は本番の学習には使いません。

## 2. Python 環境（uv）

- Python の環境と依存関係は **uv** で管理する。
- 依存の追加は **`uv add` だけ**を使う。`uv pip` の subcommand は一切使わない。
- 依存関係は `pyproject.toml` と `uv.lock` だけで管理する。環境構築は `uv sync --locked`、実行は `uv run` で行う。ローカルでも vast.ai 上でも同じ手順にする。
- Python のバージョンは M1 で固定する。PyTorch 2.14 系と SentencePiece などの wheel がそろう版を選ぶ（第一候補は 3.13）。
- PyTorch の CUDA 版は `pyproject.toml` の `[[tool.uv.index]]` と `[tool.uv.sources]` で指定する。Linux（vast.ai）では CUDA 版、Windows（ローカル）では CPU 版を使う。場当たり的な install はしない。
- 学習・実行基盤のスクリプトが使う CLI（`vastai`）は、`uv add --dev` で開発用の依存として lock する。
- 実機の読み書きに使う `esptool` のような単発のツールは、`uvx --from <package> <command>` で実行する。

### Windows で日本語を扱うときの注意

- Windows のコンソールは既定で UTF-8 ではないため、日本語が文字化けすることがある。Python では `PYTHONIOENCODING=utf-8` を設定するか、結果を UTF-8 のファイルに書いて確認する。
- ファイルの読み書きでは、必ず `encoding="utf-8"` を指定する。
- C の host runtime には、日本語を argv で渡さない。UTF-8 のファイルか stdin で渡す。TinyLM-Bench では、needle-2-esp32 の C host に argv で日本語を渡すと制限があった。

### ツールのバージョン（2026-09-29 に確認）

| ツール | 最新版 | 開発 PC の版 | 方針 |
|---|---|---|---|
| uv | 0.12.19 | 0.11.8 | 0.12 系に更新してから M1 に着手する |
| PyTorch | 2.14.0（2026-09-02。Python 3.15 まで wheel あり） | — | 2.14 系を lock する |
| vastai CLI | 1.8.2 | 1.5.6 | `uv add --dev vastai` で 1.8 系を lock する |
| esptool | 5.4.0 | `uvx` で都度取得 | 5 系 |
| ESP-IDF | 6.1（2026-08-27） | 未導入 | **v5.5.5 に固定**（§7） |

## 3. 認証情報

- API key などの秘密情報は、リポジトリ直下の `.env` に置く。`.env` は `.gitignore` で除外済み。
- 必要な変数名は下表に記載する。雛形の `.env.example` は M1 で追加し、こちらは commit する。

| 変数 | 用途 |
|---|---|
| `VAST_API_KEY` | vast.ai の API key。公式 CLI（`vastai`）がこの環境変数を直接読む |

`vastai` CLI は、API key を次の優先順位で決めます。

1. `--api-key` flag
2. 環境変数 `VAST_API_KEY`
3. `~/.config/vastai/vast_api_key`
4. `~/.vast_api_key`

`.env` の key は、端末に保存済みの key より優先されます。別アカウントの key を置くと、そのアカウントに課金されます。

## 4. vast.ai の運用ルール

実行基盤は `infra/vast/` に置く予定です（[`roadmap.md`](roadmap.md) の M3.5）。

1. **学習前の確認:** ローカルの CPU で数 step の smoke test を通してから instance を借りる。バグで課金されるのを防ぐため。
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

- 本リポジトリのソースコードと文書は Apache License 2.0（Copyright 2026 ayutaz）。
- 学習データ、モデル重み、第三者のコードとデータ（例: 公式 StackChan firmware は MIT、`stackchan-idf` は BSL-1.0）は、それぞれの条件に従う。採用する前に確認する。

## 7. 実機の build 環境（ESP-IDF）

- ESP-IDF は **v5.5.5** に固定する。K151 に対応している公式 `m5stack/StackChan`（v5.5.4）と `stackchan-idf`（v5.5.5 で検証、CI も v5.5.5）に合わせるためで、最新の v6.1 は使わない。
- Build は、公式 Docker image の `espressif/idf:v5.5.5` で行う。開発 PC に ESP-IDF を直接導入しなくて済み、CI とも同じ環境にできる。
- 書き込みと serial での計測は、Windows から `esptool`（`uvx`）で行う。
