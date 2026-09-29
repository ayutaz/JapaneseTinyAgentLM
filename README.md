# JapaneseTinyAgentLM

ESP32-S3 / M5Stack CoreS3 上で動作する、日本語向けの超小型 Language Model 群を研究・実装するプロジェクトです。

本プロジェクトは、共通の日本語 Base LM、Tokenizer、学習基盤、量子化形式、ESP32-S3 推論 Runtime を共有し、初期段階では次の2種類の checkpoint を個別に開発します。

- **Japanese Tiny Chat LM**: 日本語テキストから短い日本語テキストを生成する。
- **Japanese Action LM**: 日本語テキストから Stack-chan 等が実行できる JSON / action 列を生成する。

最初は評価原因を切り分けるため Chat と Action を分離し、十分な性能が得られた後に `<chat>` / `<action>` モードを持つ Unified Model を実験します。音声認識は別プロジェクトの `ayutaz/Ralomi`、音声合成は `sanoTTS-jp` 等が担当し、本プロジェクトの基本入出力はテキストです。

> [!IMPORTANT]
> 2026-09-29 時点では調査・設計段階です。実機（M5 スタックチャン K151）の初回調査だけ完了しています。LM の性能、LM を含めた Flash/PSRAM 使用量、速度、電力、Ralomi との同居可否、市場優位性は未検証です。文書中の「目標値」「実測値」「確認済み事実」を区別してください。

## 文書

- [`docs/README.md`](docs/README.md): プロジェクト全体像、決定事項の記録、用語、文書索引
- [`docs/architecture.md`](docs/architecture.md): モデル、Runtime、Action schema、メモリ設計、公開構成案
- [`docs/hardware.md`](docs/hardware.md): 対象の実機（K151）の構成、実機調査の計測値、Flash のバックアップ
- [`docs/development.md`](docs/development.md): uv、vast.ai での学習、認証情報、実機操作の運用ルール
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

## 想定ライセンスと公開状態

本リポジトリのソースコードと文書は [Apache License 2.0](LICENSE) で提供します（Copyright 2026 ayutaz）。学習データ、モデル重み、モデルカード、第三者コードの採用可否とそれぞれのライセンスはまだ決定していません。GitHub/Hugging Face への公開は、データ provenance、ライセンス、再現性、実機評価、安全性の gate を通過した artifact だけを対象にします。`ayutaz/Ralomi` は別プロジェクトかつ非公開・実験段階として扱い、本リポジトリの公開と連動させません。
