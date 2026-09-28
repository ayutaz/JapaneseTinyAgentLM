# 調査ノートと新規性仮説

最終更新: 2026-09-29

## 1. 調査上の注意

この文書は参照会話の調査内容を設計へ引き継ぐための初期ノートです。一次ソースを再確認できた項目と、会話時点の数値を分けています。性能値は board、clock、memory mode、context、prompt、量子化、計測方法が異なるため、単純な横並び順位として扱いません。

## 2. Hardware の確認済み事項

M5Stack 公式資料による CoreS3 の主要仕様:

- ESP32-S3、dual-core Xtensa LX7、240MHz
- 16MB Flash
- 8MB Quad PSRAM
- 320×240 touch LCD
- camera、dual microphone、speaker、IMU 等を搭載

これらの peripheral もメモリ・Flash・CPU・DMA を使うため、8MB PSRAM を丸ごと LM に割り当てることはできません。

## 3. 先行例

### 3.1 Needle 2 ESP32

一次ソースで確認済み:

- 45M parameter の tool-calling language model。
- ESP32-S3、16MB Flash、8MB Octal PSRAM の特定 board を対象。
- Model は Flash から memory-map される。
- README は model 単体約13.1MB、setup の download を13.7MBと記載しており、表記単位・artifact 内訳は比較時に再確認が必要。
- 240MHz で 534ms/token、約1.87 tok/s。
- KV cache 約3.5MB。
- JSON schema から byte-level grammar を生成し、schema-valid な tool call に制約。
- Dispatcher であり chatbot ではない。出力は tool call または empty call。
- Context は256 tokens。ESP32 port の schema 対応には nested object / array 等の制限がある。

本プロジェクトへの示唆:

- MCU 上の grammar-constrained tool calling は実現可能。
- 13MB 級 model は CoreS3 の全機能同居には大きすぎる。
- Schema token が context を消費するため、tool 数を増やすだけでは拡張しにくい。
- Grammar は構文を保証するが、日本語理解や slot correctness は別評価が必要。

### 3.2 slvDev/esp32-ai

一次ソースで確認済み:

- 28.9M stored parameters、うち25Mは Flash lookup table。
- 4-bit artifact 14.9MB。
- ESP32-S3、512KB SRAM、8MB PSRAM、16MB Flash。
- 9.88 tok/s と記載。
- Per-Layer Embeddings により、多数の parameter を Flash table に置き、token ごとに必要な row だけ読む。
- TinyStories 用であり、質問応答、instruction following、coding、事実知識を目的としない。

本プロジェクトへの示唆:

- Parameter 数だけでは能力も常駐メモリも評価できない。
- 日本語で embedding / output head が肥大化する問題に対し、PLE は研究候補。
- ただし Action 理解への転用可能性は未検証で、architecture の採用を前提にしない。

### 3.3 esp32-mind

一次ソースで確認済み:

- XIAO ESP32-S3 向け Tiny on-device language model。
- 4-bit PLE runtime、training / quantization / export code を含む。
- 実機例は40 tokens / 2.81秒、14.22 tok/s。
- Model staging と scratch allocation 後に PSRAM 約5,294KiB free と記載。
- slvDev/esp32-ai を基に8MB board target と USB prompt/response path を追加。

参照会話では 11.5M parameter と整理されていたが、今回取得できた README 該当箇所では直接確認できなかったため、再確認対象とします。

### 3.4 doryiii/esp32-llm

参照会話では 3.3M parameter、約12 tok/s の Llama 型実装として比較されました。今回の簡易再確認では該当数値を一次ソースから抽出できなかったため、現時点では**会話時点情報**としてのみ扱います。Fork 候補にする前に commit、model config、測定条件、license、training code を確認します。

### 3.5 stackchan-idf

一次ソースで、ESP-IDF based Stack-chan Firmware、CoreS3 用 default config、16MB 用 partition 設定、component 構成が存在することを確認しました。参照会話では ESP-IDF 5.5 / C++20、CoreS3、Servo、Face、Mic/Speaker、local Japanese TTS、sanoTTS-jp 連携等が整理されています。

ただし本プロジェクトへ統合する前に、対象 commit で次を実測します。

- Firmware binary / partition 使用量
- sanoTTS-jp weight と arena の実サイズ
- LCD / audio / Wi-Fi 有効時の internal SRAM / PSRAM peak
- License と第三者 notice
- 既存 component API と LLM task の scheduling

## 4. 先行例比較

| 実装 | 用途 | 規模 | Model / 量子化 | 速度 | 本プロジェクトとの差 | 確度 |
|---|---|---:|---|---:|---|---|
| Needle 2 ESP32 | English tool calling | 45M | 約13.1〜13.7MB、CQ2系 | 1.87 tok/s | 日本語、より小型、Stack-chan action 特化 | 一次ソース確認済み |
| slvDev/esp32-ai | TinyStories text generation | 28.9M stored | 14.9MB、4-bit PLE | 9.88 tok/s | instruction/action 向けでない | 一次ソース確認済み |
| esp32-mind | TinyStories text generation | 11.5M と会話で整理 | 4-bit PLE | 14.22 tok/s | 日本語・action ではない | 速度等は一次ソース、規模は再確認 |
| doryiii/esp32-llm | Tiny Llama experiment | 3.3M と会話で整理 | 要再確認 | 約12 tok/s と会話で整理 | 改造容易性を要評価 | 再確認必要 |
| JapaneseTinyAgentLM | 日本語 Chat + Action | 3M〜20M 候補 | INT8/INT4候補 | 未計測 | 日本語、共有Base、Ralomi/Stack-chan連携 | 設計目標 |

数値比較では prompt length、prefill、decode、CPU clock、PSRAM mode、出力長、temperature を固定した共通 benchmark が必要です。

## 5. 日本語対応の差別化仮説

### 仮説A: 日本語 Action 専用なら、英語汎用 tool model より小さくできる

世界知識と長文生成を捨て、Stack-chan が実行可能な action、値域、表現に絞れば 3M〜10M で有用な精度を得られる可能性があります。これは未検証です。

### 仮説B: Ralomi の正規化ひらがなを直接使うと小型化に有利

```text
音声 → でんきをけして → {"actions":[...]}
```

漢字復元を挟まず、ひらがな / モーラ列から直接意味・action を学習すれば、Tokenizer vocabulary と表記ゆれを削減できる可能性があります。一方で同音異義語、分かち書き、長音、数字、固有名詞の曖昧性が増えるため、必ず mixed Japanese baseline と比較します。

### 仮説C: 共通 Base から Chat / Action を派生させると開発効率が高い

日本語理解は共有しつつ、Chat の自由生成と Action の決定的出力を SFT で分けられます。最終的な Unified 化により Flash を節約できる可能性がありますが、mode leakage と capacity competition の危険があります。

### 仮説D: Embodied command に限定するとユーザー価値を作りやすい

「右を向く」「うなずく」「嬉しそうに話す」「温度を読む」のような身体性のある command は、単なる TinyStories 生成より用途が明確です。ただし、実際の需要、誤動作許容度、応答速度要求はユーザー調査が必要です。

## 6. 市場優位性・新規性の現時点の見立て

現時点で主張できるのは「有望な組み合わせ仮説」であり、「世界初」「競合なし」「市場優位」は主張できません。

候補となる新規性:

- ESP32-S3 上の日本語特化 Language-to-Action。
- 3M / 5M / 10M / 20M を同一条件で比較し、日本語 Action に必要な最小規模を示す。
- ASR の正規化ひらがな / モーラ列を直接入力する end-to-end pipeline 設計。
- Chat と Action を共通 Base から派生し、後から Unified 化する比較研究。
- ASR / LM / TTS の PSRAM workspace 時分割による CoreS3 完全オフライン統合。
- Stack-chan の Servo / Face / Speech に特化した安全な no-op と grammar 制約。

未検証事項:

- 同様の日本語 MCU action model、製品、論文、特許の網羅調査。
- 3M〜10M で日本語の否定、相対表現、複合命令が十分理解できるか。
- Ralomi 誤認識を含む end-to-end action accuracy。
- Chat 品質が利用価値を持つ水準に達するか。
- CoreS3 単体で Flash / PSRAM / latency / battery が成立するか。
- ユーザーが cloud model より local model を選ぶ条件。
- データ・モデル・第三者 Runtime の再配布権。

## 7. GitHub / Hugging Face 公開方針

### GitHub

1 repository に training、export、Host Runtime、ESP32 Runtime、evaluation、schema をまとめます。Chat と Action を別 repository にしません。

公開前 gate:

- 学習データの出典、利用条件、除外手順を記録。
- Tokenizer corpus の再配布可否を確認。
- Third-party code と model の license compatibility を確認。
- Reproducible config と checksum を提供。
- 実機結果は board revision、clock、commit、artifact hash とともに記録。
- 危険 action や過大な Servo movement を防ぐ validator を実装。

### Hugging Face

Base / Chat / Action / Unified と model size ごとに repository を分けます。各 repository で FP artifact、quantized artifact、ESP32 artifact を明確に区別し、互換性のない形式に同じ曖昧な名前を付けません。

`ayutaz/Ralomi` は別 repository、別 release gate のまま維持します。現時点では private / experimental であり、本プロジェクトの README から公開済み依存関係として宣伝しません。

## 8. 参考一次ソース

- M5Stack CoreS3: https://docs.m5stack.com/en/core/CoreS3
- Needle 2 ESP32: https://github.com/andrisgauracs/needle-2-esp32
- stackchan-idf: https://github.com/ciniml/stackchan-idf
- slvDev/esp32-ai: https://github.com/slvDev/esp32-ai
- esp32-mind: https://github.com/kortexa-ai/esp32-mind
- doryiii/esp32-llm: https://github.com/doryiii/esp32-llm
- Ralomi: `ayutaz/Ralomi`（private / experimental。アクセス権がある環境でのみ確認）

参照日は 2026-09-29。公開前・実装採用前に、対象 commit と license を固定して再確認します。
