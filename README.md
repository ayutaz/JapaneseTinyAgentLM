# JapaneseTinyAgentLM

ESP32-S3 / M5Stack CoreS3 上で動作する、日本語向けの超小型 Language Model 群を研究・実装するプロジェクトです。

本プロジェクトは、共通の日本語 Base LM、Tokenizer、学習基盤、量子化形式、ESP32-S3 推論 Runtime を共有し、初期段階では次の2種類の checkpoint を個別に開発します。

- **Japanese Tiny Chat LM**: 日本語テキストから短い日本語テキストを生成する。
- **Japanese Action LM**: 日本語テキストから Stack-chan 等が実行できる JSON / action 列を生成する。

最初は評価原因を切り分けるため Chat と Action を分離し、十分な性能が得られた後に `<chat>` / `<action>` モードを持つ Unified Model を実験します。音声認識は別プロジェクトの `ayutaz/Ralomi`、音声合成は `sanoTTS-jp` 等が担当し、本プロジェクトの基本入出力はテキストです。

> [!IMPORTANT]
> 2026-09-29 時点では調査・設計段階です。モデル性能、Flash/PSRAM 使用量、速度、電力、Ralomi との同居可否、市場優位性は未検証です。文書中の「目標値」と「確認済み事実」を区別してください。

## 文書

- [`docs/README.md`](docs/README.md): プロジェクト全体像、決定事項、用語、文書索引
- [`docs/architecture.md`](docs/architecture.md): モデル、Runtime、Action schema、メモリ設計、公開構成案
- [`docs/research_notes.md`](docs/research_notes.md): 先行例比較、差別化仮説、確認済み事項と未検証事項
- [`docs/roadmap.md`](docs/roadmap.md): 開発フェーズ、評価指標、各フェーズの完了条件、追加調査

## 現時点の短い結論

1. 対象は Vision を入力しないため VLA ではなく、**Tiny LM + Language-to-Action / Tool-Calling LM** である。
2. Chat と Action は完全な別プロジェクトにせず、**共通 Base から分岐する別 checkpoint** とする。
3. Action は 3M / 5M / 10M、Chat は 10M / 20M を主な比較点とする。
4. CoreS3 の 16MB Flash / 8MB PSRAM ではモデル単体でなく、Firmware・ASR・TTS・画面・音声バッファを含む全体予算が支配的である。
5. ASR → LM → TTS は原則として同時実行せず、PSRAM workspace を時分割で再利用する。
6. Action 出力は grammar-constrained decoding と実行側 validation の両方で制約する。

## 想定ライセンスと公開状態

本リポジトリのソースコードと文書は [Apache License 2.0](LICENSE) で提供します（Copyright 2026 ayutaz）。学習データ、モデル重み、モデルカード、第三者コードの採用可否とそれぞれのライセンスはまだ決定していません。GitHub/Hugging Face への公開は、データ provenance、ライセンス、再現性、実機評価、安全性の gate を通過した artifact だけを対象にします。`ayutaz/Ralomi` は別プロジェクトかつ非公開・実験段階として扱い、本リポジトリの公開と連動させません。
