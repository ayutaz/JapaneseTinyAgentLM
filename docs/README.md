# JapaneseTinyAgentLM 設計資料

最終更新: 2026-09-29

## 1. 目的

本プロジェクトの目的は、ESP32-S3、特に M5Stack CoreS3 のような **16MB Flash / 8MB PSRAM** クラスのマイコン上で、ネットワークに依存せず日本語テキストを処理できる超小型モデルを研究・実装することです。

狙いは「大規模な汎用チャットモデルを無理に縮小すること」ではありません。対象タスクを次の2つに絞り、限られた計算資源に対して実用価値を最大化します。

| 派生モデル | 入力 | 出力 | 主用途 |
|---|---|---|---|
| Japanese Tiny Chat LM | 日本語 text | 短い日本語 text | 短い応答、簡単な会話、状態に応じた発話文生成 |
| Japanese Action LM | 日本語 text | JSON / structured actions | サーボ、表情、センサー、発話等の制御 |

本プロジェクトの中心的な研究問いは次のとおりです。

- 日本語の短い命令理解と Action 生成は何百万 parameter まで小型化できるか。
- 日本語の短い会話に最低限必要なモデル規模はどの程度か。
- 共通 Base / Tokenizer / Runtime により、Chat と Action の重複をどこまで減らせるか。
- Ralomi のモーラ・正規化ひらがな出力を直接受けることで、日本語の表記変換コストを削減できるか。
- 16MB Flash / 8MB PSRAM の中で ASR、LM、TTS、Stack-chan Firmware をどう共存させるか。

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
- [`research_notes.md`](research_notes.md): 先行例、比較、差別化、市場・新規性の仮説
- [`roadmap.md`](roadmap.md): 実装順、評価、gate、今後の調査項目

## 7. 記述の確度

本文では情報を次の4段階で扱います。

| ラベル | 意味 |
|---|---|
| 確認済み | 公式仕様または一次ソースで再確認した事項 |
| 会話時点 | 参照会話で調査されたが、この文書作成時に独立再検証していない事項 |
| 設計目標 | 今後の実装・評価で達成を目指す値 |
| 仮説 | 実験、市場調査、先行研究調査が必要な主張 |

数値が「目標」または「仮説」の場合、実測値として引用してはいけません。
