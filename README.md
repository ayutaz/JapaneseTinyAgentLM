# JapaneseTinyAgentLM

ESP32-S3 / M5Stack CoreS3 上でネットワークなしに動く、**実用のための**日本語の超小型言語モデルを作るプロジェクトです。完成したモデルは、Hugging Face でオープンモデルとして公開します。

## ゴール

| 項目 | 内容 |
|---|---|
| 位置づけ | 研究のためではなく、**実用**のためのモデル |
| 利用者 | Stack-chan などに組み込んで使う**開発者** |
| 入力と出力 | 入力は**テキストのみ**（漢字仮名交じりの日本語）。出力は Action の JSON、または短い日本語の応答 |
| 作る順序 | ① **Japanese Action LM** を K151 の実機で完成させる → ② **Japanese Tiny Chat LM** に取り組む |
| 対象の実機 | M5 スタックチャン K151（CoreS3、Flash 16MB、PSRAM 8MB） |
| 公開 | モデルを Hugging Face で公開する（**CC BY-SA 4.0**、商用利用可） |
| 期限 | 決まっていない。できるだけ早く作る |
| 進め方 | 実装と学習は、すべて Claude Code が実行する |

**Action LM の完了条件（暫定）:**

- 完全一致 90%以上、否定と multi-action それぞれ 90%以上、no-action 95%以上、schema 妥当 100%
- 既存の小型モデル（Needle 2、FunctionGemma 270M、MimiModel）に、厳格一致率で勝つ
- 量子化後も精度を保ち、K151 の実機で容量、速度、安定性の基準を満たす

詳しくは [`docs/README.md`](docs/README.md) §1 と [`docs/roadmap.md`](docs/roadmap.md) を参照してください。

## 構成

共通の日本語 Tokenizer、学習基盤、量子化形式、ESP32-S3 推論 Runtime を共有し、次の2種類の checkpoint を開発します。

- **Japanese Action LM**: 日本語テキストから、Stack-chan が実行できる Action の JSON を生成する。
- **Japanese Tiny Chat LM**: 日本語テキストから、短い日本語テキストを生成する。

Chat と Action は、評価で原因を切り分けやすいように最初は分けます。十分な性能が得られた後に、`<chat>` / `<action>` モードを持つ Unified Model を実験します。音声認識と音声合成は本プロジェクトの範囲外です。

> [!IMPORTANT]
> 2026-09-29 時点では調査・設計段階です。完了しているのは、実機（M5 スタックチャン K151）の初回調査と、既存モデルの検証（TinyLM-Bench）だけです。LM の性能、LM を含めた Flash/PSRAM 使用量、速度、電力はまだ検証していません。文書中の「目標値」「実測値」「確認済み事実」を区別してください。

## 文書

- [`docs/README.md`](docs/README.md): プロジェクト全体像、決定事項の記録、用語、文書索引
- [`docs/architecture.md`](docs/architecture.md): モデル、Runtime、Action schema、メモリ設計、公開構成案
- [`docs/hardware.md`](docs/hardware.md): 対象の実機（K151）の構成、実機調査の計測値、Flash のバックアップ
- [`docs/development.md`](docs/development.md): uv、vast.ai での学習、認証情報、実機操作の運用ルール
- [`docs/data.md`](docs/data.md): 学習データの方針（オープンモデルと既存データで作る）、合成データの公開方法
- [`docs/research_notes.md`](docs/research_notes.md): 先行例比較、差別化仮説、確認済み事項と未検証事項
- [`docs/roadmap.md`](docs/roadmap.md): 開発フェーズ、実装マイルストーン、評価指標、各フェーズの完了条件、追加調査

## 現時点の短い結論

1. 対象は Vision を入力しないため VLA ではなく、**Tiny LM + Language-to-Action / Tool-Calling LM** である。
2. Chat と Action は完全な別プロジェクトにせず、**共通 Base から分岐する別 checkpoint** とする。
3. Action は 3M / 5M / 10M、Chat は 10M / 20M を主な比較点とする。
4. **本計画の範囲は LLM を作ること**に限る。LM は、Flash 1.5〜5MB と PSRAM workspace 4MB 以下という LM 用の予算だけを前提に開発する。ASR / TTS との同居と統合は、将来の別計画とする。
5. 学習は vast.ai（GPU）で行い、実機では LM の runtime と、Action による servo 制御を評価する。
6. Action 出力は、TinyLM-Bench と同じ形式の action call の配列（0〜2個、`[]` が no-action）にする。grammar-constrained decoding、confidence gate、実行側 validation の3段で制約する。既存の小型モデルがすべて失敗した **multi-action、否定、no-action** を重点的に学習し、既存モデルに厳格一致率で勝つことを最初の目標にする。
7. 対象の実機は **M5 スタックチャン K151** で、servo は Feetech SCS0009 ×2 を使う。Action の yaw は正の値を右とする（公式 firmware の規約）。実機の build は ESP-IDF v5.5.5 に固定する。
8. 最初の1周は、3M / 5M の **Action 専用のスクラッチ学習**で「日本語 Action LM は小型化しても成立するか」を検証する。次の作業は M1（uv によるリポジトリ基盤）と M2（Action schema v0）である（[`docs/roadmap.md`](docs/roadmap.md) §12）。

## 開発環境

- Python は uv で管理し、依存の追加は `uv add` だけを使う。
- 学習は vast.ai で行い、API key は `.env` の `VAST_API_KEY` に置く。
- 詳しくは [`docs/development.md`](docs/development.md) を参照。

## ライセンスと公開

| 対象 | ライセンス |
|---|---|
| ソースコードと文書（本リポジトリ） | [Apache License 2.0](LICENSE)（Copyright 2026 ayutaz） |
| モデルの重み（Hugging Face で公開） | **CC BY-SA 4.0**（商用利用可。利用時の表示が必要で、改変したモデルも同じライセンスで公開する必要がある） |
| 学習データ | CC BY-SA 4.0 と両立するものだけを使う（[`docs/development.md`](docs/development.md) §6） |

公開するのは、データの出典、ライセンス、再現性、実機での評価、安全性の審査をすべて通過した artifact だけです。
