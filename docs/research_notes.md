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

開発に使う実機は、M5Stack 公式の M5 スタックチャン（SKU K151）です。2026-09-29 に実機から次を読み取りました。

- ESP32-S3（QFN56）rev v0.2
- 16MB quad Flash
- 外付け PSRAM 約 8MB

胴体（servo は SCS0009 ×2、IO expander、NFC、タッチなど）の構成と、受領時の firmware の計測値は [`hardware.md`](hardware.md) にまとめています。

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
- Needle 2 の対象 board は Octal PSRAM、CoreS3 は Quad PSRAM で、PSRAM の帯域が異なる。KV cache や重みを PSRAM に置く場合、tok/s を直接比較しない。
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

規模は TinyLM-Bench で確認しました（§3.7）。

- `xiao-model-v1` は 11,509,632 parameter、int4（group 128）、export 後 5,969,116 B。
- 公開 `model.bin` と golden が一致することも検証済み。

### 3.4 doryiii/esp32-llm

規模は TinyLM-Bench で確認しました（§3.7）。

| モデル | Parameter 数 | 形式 | Size |
|---|---:|---|---:|
| stories260K | 260,032 | FP32 | 1,056,540 B |
| stories3M | 3,148,224 | INT8（group 64） | 3,352,576 B |

- Windows host では、float32 engine を上流のソースを変えずに動かせた（外部 shim を使用）。
- Xtensa PIE の INT8 kernel は実機でしか動かない。
- 約 12 tok/s という速度は上流の値で、CoreS3 での実測はまだない。
- stories3M INT8 は、規模も量子化も本プロジェクトの 3M / 5M Action に近い。そのため、CoreS3 での速度と PSRAM 帯域の基準値を取る対象として最適である（[`roadmap.md`](roadmap.md) §12 の B2.5）。
- Fork 候補にする前に、commit、license、training code を確認する。

### 3.5 stackchan-idf

一次ソースで確認済み（2026-09-29 再確認）:

- ESP-IDF 5.5 系、C++20 の Stack-chan firmware。README によると 5.5.5 で検証しており、CI も `espressif/idf:v5.5.5` に固定している。
- License は BSL-1.0。最終更新は 2026-09-23。
- **K151 の胴体に対応している。** README に、PY32 IO expander（`0x6F`）の Pin 0 で servo の VM 電源を入れ、200ms 待ってから bus を使う手順が記載されている。SCS0009 ×2 を UART1（TX `G6` / RX `G7`、1Mbps、8N1）で動かす。
- `components/scs_servo/` に SCS0009 のドライバがあり、台形速度の path generator と host test が付いている。

本プロジェクトへの示唆:

- Servo の座標の確認（[`roadmap.md`](roadmap.md) §12 の B2）に、そのまま使える。
- LM 評価用の最小 firmware では、`scs_servo` component の流用を候補にする。License（BSL-1.0）と第三者 notice は、採用時に確認する。

### 3.6 m5stack/StackChan（K151 の公式 firmware）

一次ソースで確認済み:

- M5Stack 公式の M5 スタックチャン（K151）用の firmware、app、server をまとめた repository。
- `firmware/` は ESP-IDF v5.5.4 系で、MIT License（Copyright 2026 M5Stack Technology）。
- Servo は Feetech 製 servo のドライバ（`FTServo_Arduino`）の `SCSCL` で動かす。UART1、1Mbps、TX=`G6` / RX=`G7`。
- Yaw は ID 1、±128°。Pitch は ID 2、3°〜87°。
- Zero position を NVS に保存して較正する。
- Pitch には、引っかかりを検知して止める stall protection がある。
- Motion API では、yaw の正の値が右、pitch の値が大きいほど上（コードのコメントによる）。

本プロジェクトへの示唆:

- K151 の servo、電源、センサーの driver を再実装しなくて済む。
- Action LM の出力は、この Motion API（`move` / `moveWithSpeed`、0.1° 単位）に写像できる。

### 3.7 TinyLM-Bench（既存モデルの Windows host 検証、2026-09-29）

別 workspace の `TinyLM-Bench` で、既存の小型モデルを Windows host 上の共通評価にかけました。

- 結論は `docs/94_model_validation_and_advantage_ja.md`、生データは `results/` にある。
- 94 の数値は `results/*.csv` と一致することを確認した。
- 評価セットは16件（英語 8件、日本語 8件）。内訳は single 6、multi_action 4、no_action 4、negation 2。
- Tool は `look(direction, amount)`、`set_expression(expression)`、`nod(count)` の3種類。

**Action モデルの結果**

| モデル | 厳格一致 | 日本語の厳格一致 | JSON 妥当 | Schema 妥当 | multi-action | 否定 | No-action | Decode | Peak RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FunctionGemma 270M | 6/16 | 4/8 | 16/16 | 11/16 | 0/4 | 0/2 | 2/4 | 4.76 tok/s | 約 2,026 MiB |
| Needle 2 | 3/16 | 1/8 | 16/16 | 16/16 | 0/4 | 0/2 | 1/4 | 146.61 tok/s | 約 84 MiB |
| MimiModel | 1/16 | 0/8 | 16/16 | 14/16 | 0/4 | 0/2 | 1/4 | 54.15 tok/s | 約 23 MiB |

- FunctionGemma は「Do nothing.」に `nod` を返し、`amount` に enum 外の `right` や `left` を入れていた。
- Needle 2 は schema 妥当率が 16/16 でも、厳格一致は 3/16 だった。構造の制約と意味の理解は別の問題である。

**本プロジェクトの評価器による再評価**（M2、2026-09-29）

同じ出力を、本プロジェクトの評価器（`jtalm.eval`）で評価し直しました。厳格一致はベンチと完全に一致しています。

| モデル | 厳格一致 | schema 妥当 | tool 名の正解率 | 引数の正解率 | No-action の recall | 致命的な誤りの率 | 主な致命的な誤り |
|---|---:|---:|---:|---:|---:|---:|---|
| Needle 2 | 3/16 | 16/16 | 0.38 | 0.27 | 0.17 | 0.50 | 誤作動 5、**逆方向 3** |
| FunctionGemma 270M | 6/16 | 10/16 | 0.56 | 0.50 | 0.33 | 0.50 | 範囲外の出力 6、誤作動 4、重複 1 |
| MimiModel | 1/16 | 12/16 | 0.31 | 0.32 | 0.17 | 0.69 | 誤作動 5、範囲外の出力 4、重複 2 |

- schema 妥当の数がベンチより少ないのは、本プロジェクトの規則（最大2個、重複の禁止）がベンチより厳しいため。
- Needle 2 は、左右を逆に向く誤りを3件起こしていた。実機では最も危険な誤りなので、評価では逆方向を独立に数える。

**Chat モデルの結果**

- 英語の小型モデル（TinyTalk 2 / cardputer-ai、esp32-mind、esp32-ai、esp32-llm）は、日本語の入力に対して、何も返さないか英語の物語を続けるだけだった。
- 日本語を生成できたのは LLM-jp-3-150M-instruct3 だけだったが、約 1.25GB の RSS を使い、指示への追従も不安定だった。

**本プロジェクトへの示唆**

- 既存の3モデルは、どれも multi-action、否定、no-action で全滅している。差をつけるならここで、評価でもこの3カテゴリを独立に集計する。
- Action の出力形式をこのベンチと同じにすれば、既存モデルを外部の比較対象にできる（[`architecture.md`](architecture.md) §7）。
- 16件は、傾向を見るには足りるが、統計的な結論には足りない。M3 で、評価セットを 1,189件（multi-action 192、否定 270、no-action 337）に拡張した（[`roadmap.md`](roadmap.md) §12 の「M3 の結果」）。

**検証から得た教訓**（TinyLM-Bench の 00 / 02 / 90 / 91 / 92 から）

- **評価条件で結果が変わる:** MimiModel は Needle 2 と同じ重みなのに、厳格一致が 1/16 だった（Needle 2 は 3/16）。原因は、tool の絞り込み、prompt の組み立て、reasoning の上限、grammar の実装の違い。本プロジェクトでも、prompt template、decoding の設定（greedy）、grammar の実装を固定して記録し、Python と C runtime を同じ評価セットで比べる。
- **量子化で挙動が変わる:** TinyTalk 2 は、FP32 では「天気は分からない」と答えたのに、組込み用の Q4 では晴れだと捏造した。量子化後は loss や logit の誤差だけでなく、カテゴリ別の評価をやり直す。
- **語彙の embedding が大きい:** TinyTalk 2 は「8M」と表記されているが、実際は 19.7M parameter あり、差の大部分は 50,257 語の embedding である。日本語の小型モデルでは語彙サイズが parameter 数を左右する。
- **Grammar で防げない誤り:** 構造の破損は防げても、誤った tool の選択、誤った引数、否定の無視、余分な呼び出しは防げない。FunctionGemma は、話題外の入力に同じ `look` を何度も返した。
- **Windows で日本語を渡すとき:** needle-2-esp32 の C host では、日本語を argv で渡すと制限があった。Host runtime では、UTF-8 のファイルか stdin で入力する。
- **Host の測定値の限界:** Windows の RSS は ESP32 の SRAM / PSRAM の必要量を示さない。実機の memory は別の gate で測る。
- **CoreS3 に載るかどうか:** Needle 2 は重みが 13.74MB で、上流の説明では PSRAM を約 7.7MB 使う。FunctionGemma 270M と LLM-jp 150M は PC 上の baseline にとどまり、CoreS3 に直接載せる候補から外れた。

**Chat の baseline**

- 日本語の生成: LLM-jp-3-150M-instruct3（PC のみ）
- 小型の英語 Chat: TinyTalk 2 / cardputer-ai

## 4. 先行例比較

| 実装 | 用途 | 規模 | Model / 量子化 | 速度 | 本プロジェクトとの差 | 確度 |
|---|---|---:|---|---:|---|---|
| Needle 2 ESP32 | English tool calling | 45M | 約13.1〜13.7MB、CQ2系 | 1.87 tok/s | 日本語、より小型、Stack-chan action 特化 | 一次ソース確認済み |
| slvDev/esp32-ai | TinyStories text generation | 28.9M stored | 14.9MB、4-bit PLE | 9.88 tok/s | instruction/action 向けでない | 一次ソース確認済み |
| esp32-mind | TinyStories text generation | 11.5M | int4（group 128）、5.97MB | 14.22 tok/s | 日本語・action ではない | 速度は一次ソース、規模は TinyLM-Bench で確認 |
| doryiii/esp32-llm | Tiny Llama experiment | 3.1M（stories3M） | INT8（group 64）、3.35MB | 約12 tok/s（上流の値） | 3M / 5M 規模の実機速度の基準に使える | 規模は TinyLM-Bench で確認、速度は未確認 |
| JapaneseTinyAgentLM | 日本語 Chat + Action | 3M〜10M（実機の候補。20M は PC だけの上限参照） | INT8/INT4候補、1.5〜5MB | 未計測 | 日本語、共有 Base、K151 向けの Action（multi-action、否定、no-action を重視） | 設計目標 |

数値比較では prompt length、prefill、decode、CPU clock、PSRAM mode、出力長、temperature を固定した共通 benchmark が必要です。

## 5. 日本語対応の差別化仮説

### 仮説A: 日本語 Action 専用なら、英語汎用 tool model より小さくできる

世界知識と長文生成を捨て、Stack-chan が実行可能な action、値域、表現に絞れば 3M〜10M で有用な精度を得られる可能性があります。これは未検証です。

### 仮説B: Ralomi の正規化ひらがなを直接使うと小型化に有利

```text
音声 → みぎをむいて → [{"name":"look","arguments":{"direction":"right","amount":"normal"}}]
```

漢字復元を挟まず、ひらがな / モーラ列から直接意味・action を学習すれば、Tokenizer vocabulary と表記ゆれを削減できる可能性があります。一方で同音異義語、分かち書き、長音、数字、固有名詞の曖昧性が増えるため、必ず mixed Japanese baseline と比較します。

> [!NOTE]
> 2026-09-29 に、入力はテキストのみと決まりました。主な入力は漢字仮名交じり文なので、この仮説は本計画の中心から外します。ひらがなだけの入力は、頑健性を確かめるためのデータとして一部だけ扱います。

### 仮説C: 共通 Base から Chat / Action を派生させると開発効率が高い

日本語理解は共有しつつ、Chat の自由生成と Action の決定的出力を SFT で分けられます。最終的な Unified 化により Flash を節約できる可能性がありますが、mode leakage と capacity competition の危険があります。

### 仮説D: Embodied command に限定するとユーザー価値を作りやすい

「右を向く」「うなずく」「嬉しそうな表情にする」のような身体性のある command は、単なる TinyStories 生成より用途が明確です。ただし、実際の需要、誤動作許容度、応答速度要求はユーザー調査が必要です。

## 6. 市場優位性・新規性の現時点の見立て

現時点で主張できるのは「有望な組み合わせ仮説」であり、「世界初」「競合なし」「市場優位」は主張できません。

候補となる新規性:

- ESP32-S3 上の日本語特化 Language-to-Action。
- 3M / 5M / 10M / 20M を同一条件で比較し、日本語 Action に必要な最小規模を示す。
- （対象外）ASR の正規化ひらがな / モーラ列を直接入力する end-to-end pipeline 設計。入力をテキストのみとしたため、本計画では扱わない。
- Chat と Action を共通 Base から派生し、後から Unified 化する比較研究。
- ASR / LM / TTS の PSRAM workspace 時分割による CoreS3 完全オフライン統合（将来の統合計画。本計画の対象外）。
- K151 の Servo と表情に特化した、安全な no-action、grammar 制約、confidence gate。

未検証事項:

- 同様の日本語 MCU action model、製品、論文、特許の網羅調査。
- 3M〜10M で日本語の否定、相対表現、複合命令が十分理解できるか。
- 入力ミス、変換ミス、表記ゆれを含む入力での action accuracy。
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

重みのライセンスは **CC BY-SA 4.0**（商用利用可）です（2026-09-29 決定）。学習データのライセンス条件は [`development.md`](development.md) §6 にまとめています。最初に公開するのは Action LM で、Chat LM は後から追加します。

`ayutaz/Ralomi` は別 repository、別 release gate のまま維持します。現時点では private / experimental であり、本プロジェクトの README から公開済み依存関係として宣伝しません。

## 8. 参考一次ソース

- M5Stack CoreS3: https://docs.m5stack.com/en/core/CoreS3
- Needle 2 ESP32: https://github.com/andrisgauracs/needle-2-esp32
- stackchan-idf: https://github.com/ciniml/stackchan-idf
- slvDev/esp32-ai: https://github.com/slvDev/esp32-ai
- esp32-mind: https://github.com/kortexa-ai/esp32-mind
- doryiii/esp32-llm: https://github.com/doryiii/esp32-llm
- Ralomi: `ayutaz/Ralomi`（private / experimental。アクセス権がある環境でのみ確認）
- M5Stack StackChan（K151）公式資料: https://docs.m5stack.com/en/StackChan
- m5stack/StackChan（公式 firmware）: https://github.com/m5stack/StackChan
- M5 スタックチャン販売開始（スイッチサイエンス）: https://prtimes.jp/main/html/rd/p/000000244.000064534.html
- M5Stack Technology の FCC grantee code（2AN3W）: https://fccid.io/2AN3W
- ESP-IDF releases: https://github.com/espressif/esp-idf/releases
- TinyLM-Bench: 別 workspace（`../TinyLM-Bench`。Git 管理外）。`docs/94_model_validation_and_advantage_ja.md`、`eval/action_cases.json`、`eval/action_tools.json`、`results/`

参照日は 2026-09-29。公開前・実装採用前に、対象 commit と license を固定して再確認します。
