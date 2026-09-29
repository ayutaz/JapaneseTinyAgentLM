# JapaneseTinyAgentLM 設計資料

最終更新: 2026-09-29

## 1. 目的

本プロジェクトの目的は、ESP32-S3、特に M5Stack CoreS3 のような **16MB Flash / 8MB PSRAM** クラスのマイコン上で、ネットワークに依存せず日本語テキストを処理できる超小型モデルを研究・実装することです。

開発と評価に使う実機は、M5Stack 公式の **M5 スタックチャン（SKU K151）** です。本体は CoreS3 で、servo は Feetech SCS0009 を2個使います。詳細は [`hardware.md`](hardware.md) を参照してください。

狙いは「大規模な汎用チャットモデルを無理に縮小すること」ではありません。対象タスクを次の2つに絞り、限られた計算資源に対して実用価値を最大化します。

| 派生モデル | 入力 | 出力 | 主用途 |
|---|---|---|---|
| Japanese Tiny Chat LM | 日本語 text | 短い日本語 text | 短い応答、簡単な会話、状態に応じた発話文生成 |
| Japanese Action LM | 日本語 text | JSON / structured actions | サーボ（視線、うなずき）と表情の制御。対象外や曖昧な入力には no-action を返す |

本プロジェクトの中心的な研究問いは次のとおりです。

- 日本語の短い命令理解と Action 生成は何百万 parameter まで小型化できるか。
- 日本語の短い会話に最低限必要なモデル規模はどの程度か。
- 共通 Base / Tokenizer / Runtime により、Chat と Action の重複をどこまで減らせるか。
- Ralomi のモーラ・正規化ひらがな出力を直接受けることで、日本語の表記変換コストを削減できるか。
- 16MB Flash / 8MB PSRAM の CoreS3 で、LM に割り当てた予算（[`architecture.md`](architecture.md) §9–10）の中で、どこまでの品質と速度を出せるか。

## 2. スコープ

### 含むもの

- 日本語 Base LM の学習
- Chat SFT と Action SFT
- 日本語向け小語彙 Tokenizer
- 3M / 5M / 10M / 20M 規模の比較
- INT8 / INT4、および必要に応じた 2〜3bit 量子化実験
- ESP32-S3 向け推論 Runtime
- KV cache と workspace の省メモリ化
- JSON / Action grammar-constrained decoding
- Host と実機での再現可能な評価
- 将来の Unified Chat + Action Model

### 含まないもの

- 音声波形を直接入力する end-to-end 音声言語モデル
- Vision encoder や画像・映像理解
- ASR 自体の開発（`ayutaz/Ralomi` が担当）
- TTS 自体の開発（`sanoTTS-jp` 等が担当）
- ASR / TTS との同居の検証と統合（将来の別計画。2026-09-29 決定）
- Stack-chan の Servo / Face / Audio driver の再実装
- ChatGPT 相当の世界知識、長文生成、汎用推論
- 現時点での製品化・安全認証・市場性の断定

## 3. プロジェクト構造に関する決定

Chat と Action は、重みと評価目的が異なるため、最初は別 checkpoint とします。ただし、次は共通化します。

- 学習用の Base architecture
- Tokenizer と vocabulary
- 日本語事前学習 corpus pipeline
- checkpoint / quantization / export 形式
- Host reference inference
- ESP32-S3 Runtime、演算 kernel、KV cache
- 品質・速度・メモリ計測 framework

```text
Japanese Base LM
       │
       ├── Chat SFT ─── Japanese Tiny Chat LM
       │
       └── Action SFT ─ Japanese Action LM
                              │
                              └── grammar-constrained decoding

検証後:

Japanese Unified LM
       ├── <chat>   → Japanese text
       └── <action> → JSON / actions
```

この順序にする理由は、最初から multitask 化すると、性能不足の原因が Base、Tokenizer、Chat data、Action data、model size、multitask interference のどれか判別しにくくなるためです。

## 4. VLA ではない理由

VLA は通常 **Vision-Language-Action** を指し、画像または映像をモデル入力として直接処理する構成です。本プロジェクトのモデル入力は日本語テキストだけで、カメラ画像を入力しません。

したがって、現時点での適切な分類は次のいずれかです。

- Japanese Tiny Language Model
- Language-to-Action Model
- Action LM
- Tool-Calling LM
- Task-oriented Semantic Parser
- MCU-oriented Japanese Agent LM（プロジェクト全体の説明として使用）

Stack-chan がカメラを搭載していても、カメラが model graph に接続されていない限り VLA とは呼びません。将来 Vision encoder を追加した場合は別途 VLA branch として再定義します。

## 5. Ralomi との役割分担

`ayutaz/Ralomi` は、ESP32-S3 向け日本語 ASR を目指す別プロジェクトです。本プロジェクトとは repository、学習目的、artifact、評価指標を分離します。

```text
音声波形
  ↓
Ralomi（ASR、別プロジェクト）
  ↓  日本語 text / 正規化ひらがな / モーラ列
JapaneseTinyAgentLM
  ├─ Chat   → 日本語 text → TTS
  └─ Action → JSON         → Servo / Face / Sensor
```

会話で確認した Ralomi の現状は以下です。ただし、Ralomi repository は非公開・実験段階であり、2026-09-29 の匿名 Web 参照では 404 でした。公開済み・完成済み・性能保証済みとは扱いません。

- 40次元 log-Mel を入力とする小型音響モデルを検討中。
- CTC / RNN-T 系を候補とし、モーラ token から正規化ひらがなを返す契約を検討中。
- release architecture は未確定。
- INT8 M6 は精度 gate で停止中という会話時点の情報がある。
- Artifact 予算案は Tiny 約2MB以下、Standard 約8MB以下、Large 約16MB以下。ただし合格済みモデルの実測サイズではない。
- Stack-chan では Tiny 相当、最大発話 5〜8秒、W8A8、PSRAM peak 2.5MB 以下を初期目標候補とする。

最初の LM 実験は ASR を PC / 固定テキスト入力に置き換えて独立に進めます。Ralomi の仕様変更を LM 開発の blocker にしません。

## 6. 文書の読み方

- [`architecture.md`](architecture.md): モデル構成、Action schema、Runtime、Flash/PSRAM 設計
- [`hardware.md`](hardware.md): 対象の実機（K151）の構成、Phase 0 の初回調査の計測値、Flash のバックアップ
- [`development.md`](development.md): uv、vast.ai、認証情報、実機操作の運用ルール
- [`research_notes.md`](research_notes.md): 先行例、比較、差別化、市場・新規性の仮説
- [`roadmap.md`](roadmap.md): 実装順、マイルストーン、評価、gate、今後の調査項目

## 7. 記述の確度

本文では情報を次の5段階で扱います。

| ラベル | 意味 |
|---|---|
| 確認済み | 公式仕様または一次ソースで再確認した事項 |
| 実測 | 実機で読み取り・計測した値。計測条件（firmware、設定など）を必ず併記する |
| 会話時点 | 参照会話で調査されたが、この文書作成時に独立再検証していない事項 |
| 設計目標 | 今後の実装・評価で達成を目指す値 |
| 仮説 | 実験、市場調査、先行研究調査が必要な主張 |

数値が「目標」または「仮説」の場合、実測値として引用してはいけません。「実測」の値も、併記した条件以外に一般化してはいけません。

## 8. 決定事項の記録

| 日付 | 決定 | 詳細 |
|---|---|---|
| 2026-09-29 | ソースコードと文書のライセンスを Apache License 2.0（Copyright 2026 ayutaz）とする。データと重みは別途決める | [`../LICENSE`](../LICENSE) |
| 2026-09-29 | GitHub の private repository `ayutaz/JapaneseTinyAgentLM` で管理する | — |
| 2026-09-29 | 学習は vast.ai で行う。API key は `.env` の `VAST_API_KEY` から読む | [`development.md`](development.md) §3–4 |
| 2026-09-29 | Python は uv で管理し、依存の追加は `uv add` だけを使う（`uv pip` は使わない） | [`development.md`](development.md) §2 |
| 2026-09-29 | 対象の実機を M5 スタックチャン K151 とする | [`hardware.md`](hardware.md) |
| 2026-09-29 | Action の yaw は正の値を右とする（公式 firmware の規約。実機での確認は未実施） | [`hardware.md`](hardware.md) §3 |
| 2026-09-29 | PC 上の実験（Track A）と実機での計測（Track B）を並行して進める。最初の1周は Action 専用のスクラッチ学習とし、Base の事前学習は corpus のライセンスが決まってから行う | [`roadmap.md`](roadmap.md) §12 |
| 2026-09-29 | 本計画の範囲は **LLM を作ること**に限る。TTS / ASR の調査と同居の検証は行わない。LM は LM 用の Flash / PSRAM 予算だけを前提に開発する | [`roadmap.md`](roadmap.md) §1、[`architecture.md`](architecture.md) §9–10 |
| 2026-09-29 | 実機の build は ESP-IDF v5.5.5（Docker image `espressif/idf:v5.5.5`）に固定する。LM の評価には自前の最小 firmware を使う | [`development.md`](development.md) §7 |
| 2026-09-29 | Action schema v0 は TinyLM-Bench と同じ `{"name","arguments"}` の配列にする。方向と量はカテゴリで表し、1回の出力は 0〜2個、`[]` を no-action とする。Action は `look` / `set_expression` / `nod` の3種類で、`speak` は外す。角度への変換は firmware 側で行う | [`architecture.md`](architecture.md) §7 |
| 2026-09-29 | 日本語を主とし、英語の命令は評価用に少量だけ扱う | [`architecture.md`](architecture.md) §2 |
| 2026-09-29 | 量子化後の LM の容量は 1.5〜5MB とする（TinyLM-Bench の検証メモにあった 4〜8MB は採らない）。語彙サイズは 2k〜16k を実測で比べて決める | [`architecture.md`](architecture.md) §3–4 |
| 2026-09-29 | Grammar に加えて confidence gate を入れ、確信度の低い出力は no-action にする | [`architecture.md`](architecture.md) §8 |
| 2026-09-29 | Action の目標値は、TinyLM-Bench の検証メモの値（完全一致 90%以上、no-action 95%以上など）を暫定で採用し、既存モデルを baseline に加える | [`roadmap.md`](roadmap.md) §4 |
| 2026-09-29 | TinyLM-Bench の検証全体（00 / 02 / 90 / 91 / 92）を反映する。主な内容は次のとおり。Action の契約（入力は1〜2文、出力は0〜2個、tool は v1 で 8〜16 種類）。学習データは 2,000〜10,000件で、否定と no-action を各20%以上とし、対比ペアを入れる。Tokenizer を先に固定する。PC 上だけの上限参照（20M）を置く。評価条件（prompt、greedy、grammar の実装）を固定して記録する。量子化後はカテゴリ別に評価し直す。既存 runtime（esp32-llm stories3M INT8）で実機の基準値を取る（B2.5） | [`roadmap.md`](roadmap.md) §4、§10、§12、[`architecture.md`](architecture.md) §2–7 |
