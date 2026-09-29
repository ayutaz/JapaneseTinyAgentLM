# アーキテクチャ設計

最終更新: 2026-09-29

## 1. システム境界

本プロジェクトのモデルは text-in / text-out または text-in / action-out です。音声 I/O やデバイス driver は統合先の責務です。

```text
                        CoreS3 / ESP32-S3

 Mic ──> Ralomi ──> normalized Japanese text
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
      Japanese Tiny Chat LM      Japanese Action LM
              │                         │
              ▼                         ▼
        response text              validated JSON
              │                         │
              ▼                   ┌─────┴─────┐
        sanoTTS-jp                 ▼           ▼
                               Servo         Face/Sensor
```

初期実装では Chat と Action の同時常駐を要求しません。評価用 Firmware は用途別の build profile を持ち、最終段階で Unified Model を検討します。

対象の実機は M5 スタックチャン K151 です（[`hardware.md`](hardware.md)）。

- 図中の Servo は Feetech SCS0009 ×2 で、UART1（`G6` / `G7`、1Mbps）の SCS protocol で動かす。
- Servo の電源（`VM_EN`）は IO expander（PY32L020）が制御する。
- 検証済みの JSON を servo の命令に変換するのは firmware 側の dispatcher であり、LM は servo の raw 値を直接出力しない。

## 2. 共通 Base と派生モデル

### Base

日本語 next-token prediction を学習します。Tokenizer、embedding、Transformer block、LM head を Chat / Action で共有できる形にします。

### Chat

- 入力: 短い日本語指示・発話・状態文
- 出力: 短い日本語応答
- 目標規模: 10M / 20M を中心に比較
- 目標 context: 128〜256 tokens
- 生成長: 原則 16〜64 tokens
- 世界知識より、短い自然な応答、キャラクター一貫性、不要な断定の抑制を優先

### Action

- 入力: 日本語の command または状態文。英語の命令は、評価用に少量だけ扱う。
- 出力: action call の JSON 配列（0〜2個）。空配列 `[]` が no-action。形式は §7。
- 目標規模: 3M / 5M / 10M を中心に比較する。量子化後の容量は §9 の LM 予算（1.5〜5MB）に収める。
- 目標 context: 64〜128 tokens。schema を prompt に含める方式では 256 も比較
- 自由生成は不要。構文妥当性、slot 値、no-op、安全性を優先
- Grammar 制約と confidence gate（§8）を基本機能とする

### Unified（後期実験）

```text
<chat>
きょうつかれた
→ おつかれさま。ゆっくりやすもう。

<action>
みぎをむいて
→ [{"name":"look","arguments":{"direction":"right","amount":"normal"}}]
```

Unified 化は Flash 節約に有効な可能性がありますが、negative transfer と mode leakage を測定したうえで採否を決めます。

## 3. モデルサイズ候補

INT4 の理論的な重み本体は、1 parameter あたり約0.5 byteです。ただし実 artifact には scale、zero point、alignment、Tokenizer、metadata が加わるため、単純計算より大きくなります。

| 規模 | INT4 重み理論値 | 主用途候補 | 現時点の見立て |
|---:|---:|---|---|
| 3M | 約1.5MB | Action 最小構成 | 限定語彙・限定 schema なら検証価値あり |
| 5M | 約2.5MB | Action 主候補、Chat 下限実験 | Action の第一候補。Chat はかなり厳しい可能性 |
| 10M | 約5MB | Action 高精度、Chat 主候補 | CoreS3 全体予算では境界領域 |
| 20M | 約10MB | Chat 品質比較 | 他 component と同居しにくく、外部 storage や強い量子化が必要 |

設計上は 3M / 5M / 10M / 20M を同じ training code で比較可能にします。最初から全サイズを完走させず、5M Action と 10M Chat の feasibility を優先します。

TinyLM-Bench の検証メモ（`94_model_validation_and_advantage_ja.md`）では、量子化後の容量を 4〜8MB とする案が出ていました。本計画では、LM 予算（§9）の 1.5〜5MB を優先します。8MB は INT4 で約 16M parameter に相当し、Action 専用のモデルとしては大きすぎるためです。

## 4. Tokenizer と vocabulary

### 候補

- SentencePiece Unigram または BPE
- Byte fallback を有効化し OOV をなくす
- NFC 正規化
- Chat 用の漢字仮名交じり corpus と、Ralomi 接続用の正規化ひらがな corpus を明示的に分離
- `<chat>`, `<action>`, `<eos>`, `<no_action>` 等の special token を予約

### 比較する vocabulary

| 用途 | 候補 vocab | 理由 |
|---|---:|---|
| Action / ひらがな入力 | 2,048 / 4,096 / 8,192 | 語彙表と LM head を小さくしやすい |
| Chat / 一般日本語 | 4,096 / 8,192 / 16,384 | 漢字・頻出 subword と系列長の折衷 |
| Unified | 4,096 を基準、8,192 と比較 | 共通化と日本語圧縮率のバランス |

例として vocab 4,096、hidden 256 の embedding は約1.05M parametersです。入力 embedding と出力 LM head は weight tying し、重複を避けます。

TinyLM-Bench の検証メモは 8k〜16k から始めることを提案していました。ただし、vocab 16,384、hidden 256 の embedding は約 4.2M parameter で、5M のモデルではほぼ全体を占めてしまいます。そこで語彙サイズは、2k〜16k の範囲を実測で比べて決めます。比べる指標は、coverage、byte fallback 率、平均 token 長、量子化後の精度です。

Tokenizer 評価では vocabulary 数だけでなく、次も測ります。

- 文字あたり token 数、モーラあたり token 数
- Action command の P50 / P95 token 長
- 固有名詞、英数字、記号、JSON key の分割
- 漢字仮名交じりとひらがなの圧縮率差
- Ralomi 誤認識を模した入力に対する安定性

## 5. Transformer と推論方式

初期候補は decoder-only Transformer とし、実装を単純化します。

- hidden: 128〜384
- layers: 4〜12
- attention: MQA または GQA
- positional encoding: RoPE を第一候補
- normalization: RMSNorm を第一候補
- activation: SwiGLU 系と単純 FFN のサイズ・速度を比較
- weight tying: 必須候補
- context: 64 / 128 / 256
- KV cache: INT8 を基準とし、必要なら K/V の bit 幅を個別検討
- sampling: Chat は greedy / top-k / temperature、Action は grammar 下で greedy を第一候補

KV cache の概算は、一般には次で見積もります。

```text
bytes ≈ layers × context × 2(K,V) × kv_heads × head_dim × bytes_per_element
```

GQA/MQA、短い context、INT8 KV は PSRAM 削減に大きく効きます。実際の allocator overhead、alignment、temporary buffer を含め、実機 peak を別途測定します。

## 6. Quantization と artifact

開発順は次を推奨します。

1. FP32/FP16 Host reference
2. PTQ INT8 で精度と export 経路を確立
3. weight-only INT4 または W4A8
4. 必要なら QAT
5. 2〜3bit は kernel と品質が成立した場合のみ

量子化は「Flash に入るか」だけでなく、次を同時に評価します。

- Host reference との logit error
- Action exact match の劣化
- Chat 品質の劣化
- dequantization を含む tok/s
- peak SRAM / PSRAM
- artifact size と alignment overhead
- 対応 kernel の保守性

## 7. Action schema

### 基本方針

- 出力は説明文を含めず machine-readable な action のみ。
- 形式は TinyLM-Bench の共通評価（`eval/action_tools.json`）と同じ、`{"name": ..., "arguments": {...}}` の配列にする。既存モデルと同じ評価器で直接比較できるようにするため。
- 実行不能・無関係・危険・曖昧な要求には、空配列 `[]`（no-action）を返す。No-action は正式な出力として学習させる。
- 1回の出力は **0〜2個**の action に限る。
- 方向や量は数値ではなく**カテゴリ**（enum）で出力させる。小さなモデルが数値を誤るのを避けるためで、角度への変換は firmware 側の dispatcher が行う。
- 未知の action、未知の field、enum 外の値、必須引数の欠落、JSON 前後の説明文を拒否する。
- Grammar が構文を保証しても、意味的安全性は confidence gate（§8）と実行側 validator が保証する。
- Action 実行前に、デバイス状態、速度制限、可動域、衝突条件を確認する。

### Action schema v0

v0 の action は `look`、`set_expression`、`nod` の3種類です。

- 音声を伴う `speak` は、本計画の範囲外なので v0 から外しました。
- `set_expression` の enum はベンチに合わせています。
- `look` の `direction` は、ベンチの `left` / `right` / `center` に、K151 の pitch を使う `up` / `down` を加えた上位集合です。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "array",
  "maxItems": 2,
  "items": {
    "oneOf": [
      {
        "type": "object",
        "additionalProperties": false,
        "required": ["name", "arguments"],
        "properties": {
          "name": {"const": "look"},
          "arguments": {
            "type": "object",
            "additionalProperties": false,
            "required": ["direction", "amount"],
            "properties": {
              "direction": {"enum": ["left", "right", "up", "down", "center"]},
              "amount": {"enum": ["slight", "normal", "large"]}
            }
          }
        }
      },
      {
        "type": "object",
        "additionalProperties": false,
        "required": ["name", "arguments"],
        "properties": {
          "name": {"const": "set_expression"},
          "arguments": {
            "type": "object",
            "additionalProperties": false,
            "required": ["expression"],
            "properties": {
              "expression": {"enum": ["happy", "sad", "surprised", "neutral"]}
            }
          }
        }
      },
      {
        "type": "object",
        "additionalProperties": false,
        "required": ["name", "arguments"],
        "properties": {
          "name": {"const": "nod"},
          "arguments": {
            "type": "object",
            "additionalProperties": false,
            "required": ["count"],
            "properties": {
              "count": {"type": "integer", "minimum": 1, "maximum": 3}
            }
          }
        }
      }
    ]
  }
}
```

- `center` のとき、`amount` は無視する。正規化では `normal` にそろえる。
- TinyLM-Bench で既存モデルと比べるときは、ベンチの enum の範囲（`up` / `down` を含まないケース）で評価する。

初期 Runtime で `oneOf` や nested array の grammar 実装が重い場合、1応答1 tool call の flat schema または固定長 action slot に縮退します。Needle 2 の ESP32 実装にも schema 機能制限があるため、完全な JSON Schema 対応を前提にしません。

### 座標の規約と角度への変換（K151）

Action LM はカテゴリだけを出力し、firmware の dispatcher が K151 の servo の角度に変換します。規約は公式 firmware（[`hardware.md`](hardware.md) §3）に合わせます。

- **yaw:** 0 が正面で、**正の値が右**。公式 firmware には 0.1° 単位で渡す（制限は ±128°）。
- **pitch:** 中立位置からの相対値で、**正の値が上**。公式 firmware の pitch は 3°〜87° の絶対角で、値が大きいほど上を向く。中立角度は実機で確認してから決める。

| `amount` | `left` / `right` の yaw | `up` / `down` の pitch |
|---|---:|---:|
| `slight` | ∓10° / ±10° | ±5° |
| `normal` | ∓20° / ±20° | ±10° |
| `large` | ∓30° / ±30° | ±15° |

- 上の角度は初期値（設計目標）で、実機で見え方を確認してから確定する。
- 最大値は yaw ±30°、pitch ±15° とし、公式の可動域より狭く保つ。安全上の上限は、実行側の validator で再確認する。
- `nod` は pitch を小さく往復させ、回数は `count` に従う。
- 連続回転（PWM mode）や raw position は、Action LM から指定させない。

符号の規約は、実機を動かして確認してから確定します（[`roadmap.md`](roadmap.md) Phase 0）。

### 例

```text
右を向いて、ちょっと嬉しそうにして
→ [{"name":"look","arguments":{"direction":"right","amount":"normal"}},
   {"name":"set_expression","arguments":{"expression":"happy"}}]

少し右を向いて
→ [{"name":"look","arguments":{"direction":"right","amount":"slight"}}]

笑ってから左を向いて
→ [{"name":"set_expression","arguments":{"expression":"happy"}},
   {"name":"look","arguments":{"direction":"left","amount":"normal"}}]

右ではなく左を向いて
→ [{"name":"look","arguments":{"direction":"left","amount":"normal"}}]

右を向かないで
→ []

2回うなずいて
→ [{"name":"nod","arguments":{"count":2}}]

富士山について長く説明して
→ []
```

## 8. Grammar-constrained decoding

Action mode では、各生成 step で grammar により許可 token をマスクします。目標は次の3段階です。

1. JSON 構文が常に parse 可能。
2. Action type、必須 field、enum、数値範囲が schema に一致。
3. 実行側 validator が device policy と現在状態を確認。

Grammar は誤った意味を正しくしません。たとえば「左を向いて」に `"direction":"right"` を返した出力は、構文上正しくても意味的に誤りです。そのため exact match、slot accuracy、方向・量・否定・参照表現の評価が必要です。

TinyLM-Bench でも、Needle 2 は schema 妥当率が 16/16 でしたが、厳格一致は 3/16 でした（[`research_notes.md`](research_notes.md) §3.7）。

### Confidence gate

意味の誤りを実行前に止めるため、生成の確信度で出力を絞ります。

- 各 action について、生成した token の確率から確信度を求める。指標は、最小確率と平均 log 確率を比べて選ぶ。
- 閾値を下回る action は捨て、全体を no-action（`[]`）にする。
- 確信度の低い出力は、ロボットの誤作動につながるので、実行しないほうを安全側とする。
- 閾値は held-out の評価セットで決める。no-action の recall を優先し、誤った動作の率とのバランスを見る。
- 曖昧な入力に対して「確認を求める」出力は、Chat と組み合わせる必要があるため v1 以降で検討する。

## 9. Flash 予算

CoreS3 の物理上限は 16MB Flash です。

### 本計画での LM 予算

本計画の範囲は LLM を作ることです（[`roadmap.md`](roadmap.md) §1）。LM は次の予算だけを前提に開発します。TTS / ASR との同居は前提にしません。

| 対象 | Flash の予算（設計目標） |
|---|---:|
| 3M / 5M Action（INT4） | 1.5〜3MB |
| 10M Chat / Action / Unified（INT4） | 3〜5MB |

確定値は、Phase 0 で自前の最小 firmware（LM runtime と servo 制御）を測ってから決めます。

### 参考: 統合時の全体予算

次は将来の統合（本計画の対象外）を想定した**初期予算案**で、確定した partition table ではありません。

| 項目 | Action-only 開発 build | Full offline 目標 | 備考 |
|---|---:|---:|---|
| Bootloader / partition / NVS | 0.5〜1.0MB | 0.5〜1.0MB | 実 partition で確認 |
| Stack-chan Firmware / assets | 3〜5MB | 3〜5MB | 現在の build 実測が必要 |
| Ralomi | 0MB（外部入力） | 1.5〜2MB 目標 | 合格済み実測値ではない |
| LM | 1.5〜3MB | 3〜5MB | 3M/5M Action または Unified |
| TTS | 0〜3MB | 2〜4MB 仮置き | 統合時に TTS 側で決める（本計画の対象外） |
| 予備 / recovery / OTA | 1〜3MB | 1〜3MB | OTA 方針で大きく変化 |

Full offline 構成は範囲上限を足すと 16MB を超えます。統合するときには次の検討が必要になります。

- 実 build artifact と partition 使用量の計測
- OTA/recovery の要否決定
- assets、font、voice weight の外部 microSD 配置可否
- Chat と Action の Unified 化
- Model weight の mmap / streaming
- TTS/ASR の profile 縮小
- 機能別 Firmware build の採用

20M INT4 の約10MBはモデル単体でも支配的で、Full offline の標準構成には現実的でない可能性が高いです。20M は品質上限を測る研究用比較、または外部 storage 前提とします。

## 10. PSRAM / SRAM と時分割 workspace

### 本計画での LM の memory 予算

| 領域 | 予算（設計目標） | 置き場所 |
|---|---:|---|
| LM workspace（KV cache、activation、sampler、grammar mask） | ≤4.0MB | PSRAM |
| 常駐 runtime、metadata、小さな buffer | ≤1.5MB | PSRAM |
| GEMV の scratch などの高速 buffer | 数十 KB 以下 | 内部 SRAM |

- 重みは Flash から mmap して読む。
- 内部 SRAM の目安は、受領時の firmware での値で、起動直後の空きが約 155KB、最大連続ブロックが約 98KB でした（[`hardware.md`](hardware.md) §4）。
- 確定値は、Phase 0 で自前の最小 firmware を測ってから決めます。

### 参考: 統合時の時分割 workspace（本計画の対象外）

CoreS3 の PSRAM 8MB は、統合すると LM だけが使える容量ではなくなります。KV cache、activation、audio buffer、display、network、ASR/TTS arena が競合します。

統合時は、原則として pipeline を状態機械にし、大きな arena を共有します。

```text
LISTENING
  Ralomi workspace active
  ↓ recognition complete

THINKING
  shared workspace reused by LM
  ↓ text/action complete

SPEAKING
  shared workspace reused by TTS
  ↓ playback complete

IDLE
```

概念上は次の構造です。

```cpp
union AiWorkspace {
    RalomiArena asr;
    LmArena lm;
    TtsArena tts;
};
```

実際には constructor/destructor、alignment、DMA-capable memory、internal SRAM 必須 buffer、task lifecycle を考慮し、単純な C++ union に限定しません。重要なのは「同時最大の合計」ではなく「各 phase の最大値 + 常駐領域」にすることです。

初期 PSRAM 目標案:

| 領域 | 目標 | 状態 |
|---|---:|---|
| 常駐 runtime / metadata / small buffers | ≤1.5MB | 設計目標 |
| 共有 AI workspace | ≤4.0MB | 設計目標 |
| display / audio / network / fragmentation reserve | ≥2.0MB | 安全余白 |
| 未割当 reserve | ≥0.5MB | 安全余白 |

実測は `heap_caps_get_free_size`、largest free block、phase ごとの high-water mark、internal SRAM と PSRAM の別計測で行います。平均値ではなく peak と fragmentation を記録します。

## 11. Runtime の責務

共通 Runtime は次を提供します。

- Model artifact loader と version check
- Tokenizer
- Embedding / RMSNorm / Attention / FFN
- RoPE
- Quantized GEMV kernel
- KV cache
- Chat sampler
- Grammar-constrained Action sampler
- JSON parser と semantic validator
- Host reference との一致テスト
- latency / memory telemetry
- watchdog、timeout、cancel

Host と ESP32 の双方で同じ golden vector を読み、Tokenizer、1-layer、full forward、KV incremental decode、grammar mask を段階的に照合します。

## 12. Ralomi 接続 interface 案

LM が ASR 内部実装へ依存しないよう、最低限次の契約を定義します。

```json
{
  "text": "みぎをむいて",
  "text_form": "normalized_hiragana",
  "is_final": true,
  "confidence": null,
  "utterance_ms": 1640,
  "truncated": false
}
```

- `text` は UTF-8。
- `text_form` は `normalized_hiragana`、`mixed_japanese` 等を明示。
- partial result を使う場合も Action は final 確定前に実行しない。
- confidence が無い場合を許容し、閾値ロジックを固定しない。
- timeout、空文字、切断、過長発話を明示的に扱う。
- ASR 誤認識時に危険 action を発火させないため、否定・方向・数値を含む action は保守的に扱う。

## 13. Repository / 公開構成案

```text
JapaneseTinyAgentLM/
├── README.md
├── LICENSE                 # Apache-2.0
├── .gitignore
├── pyproject.toml          # uv 管理（依存は uv add のみ）
├── uv.lock
├── docs/
├── infra/
│   └── vast/               # vast.ai の検索・起動・転送・回収・削除
├── tokenizer/
│   ├── train_tokenizer.py
│   └── eval_tokenizer.py
├── model/
│   ├── architecture.py
│   └── config.py
├── training/
│   ├── pretrain.py
│   ├── sft_chat.py
│   └── sft_action.py
├── datasets/
│   ├── manifests/
│   ├── chat/
│   └── action/
├── grammar/
│   ├── action.schema.json
│   └── compile_grammar.py
├── export/
│   ├── quantize.py
│   └── export_model.py
├── runtime/
│   ├── host/
│   └── esp32/
├── eval/
│   ├── chat/
│   ├── action/
│   └── device/
├── configs/
│   ├── base_3m.yaml
│   ├── base_5m.yaml
│   ├── base_10m.yaml
│   └── base_20m.yaml
├── tests/
└── backups/                # 実機 Flash のバックアップ（Git 管理外）
```

`LICENSE`、`.gitignore`、`docs/` は作成済みです。その他は計画段階です。

GitHub はコードと再現手順を1 repository にまとめ、Hugging Face は artifact を用途・サイズ・量子化ごとに分離します。

```text
ayutaz/JapaneseTinyAgentLM                  # GitHub（private で作成済み）

ayutaz/JapaneseTinyAgentLM-5M-Base         # HF 候補
ayutaz/JapaneseTinyAgentLM-5M-Action
ayutaz/JapaneseTinyAgentLM-10M-Base
ayutaz/JapaneseTinyAgentLM-10M-Chat
ayutaz/JapaneseTinyAgentLM-10M-Action
ayutaz/JapaneseTinyAgentLM-10M-Unified
```

各 model card には architecture、Tokenizer、training data、license、quantization、Host/ESP32 評価、既知の限界、推奨用途、禁止用途を記載します。命名と公開先は未確定であり、既存名称・商標・repository との衝突を公開前に再確認します。
