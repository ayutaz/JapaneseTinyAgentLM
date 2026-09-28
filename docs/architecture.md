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

- 入力: 日本語 command または状態文
- 出力: JSON / action 列、または no-op
- 目標規模: 3M / 5M / 10M を中心に比較
- 目標 context: 64〜128 tokens。schema を prompt に含める方式では 256 も比較
- 自由生成は不要。構文妥当性、slot 値、no-op、安全性を優先
- Grammar 制約を基本機能とする

### Unified（後期実験）

```text
<chat>
きょうつかれた
→ おつかれさま。ゆっくりやすもう。

<action>
みぎをむいて
→ {"actions":[{"type":"look","yaw":20,"pitch":0}]}
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
| Action / ひらがな入力 | 2,048 / 4,096 | 語彙表と LM head を小さくしやすい |
| Chat / 一般日本語 | 4,096 / 8,192 | 漢字・頻出 subword と系列長の折衷 |
| Unified | 4,096 を基準、8,192 と比較 | 共通化と日本語圧縮率のバランス |

例として vocab 4,096、hidden 256 の embedding は約1.05M parametersです。入力 embedding と出力 LM head は weight tying し、重複を避けます。

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
- 実行不能・無関係・危険・曖昧な要求は `{"actions":[]}` を返せること。
- 数値は schema と実行側で範囲制限する。
- 未知の action type、未知の field、NaN、過大な配列を拒否する。
- Grammar が構文を保証しても、意味的安全性は実行側 validator が保証する。
- Action 実行前に、デバイス状態、速度制限、可動域、衝突条件を確認する。

### 概念 schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["actions"],
  "properties": {
    "actions": {
      "type": "array",
      "maxItems": 4,
      "items": {
        "oneOf": [
          {
            "type": "object",
            "additionalProperties": false,
            "required": ["type", "yaw", "pitch"],
            "properties": {
              "type": {"const": "look"},
              "yaw": {"type": "integer", "minimum": -30, "maximum": 30},
              "pitch": {"type": "integer", "minimum": -15, "maximum": 15}
            }
          },
          {
            "type": "object",
            "additionalProperties": false,
            "required": ["type", "value"],
            "properties": {
              "type": {"const": "emotion"},
              "value": {"enum": ["neutral", "happy", "sad", "sleepy", "surprised"]}
            }
          },
          {
            "type": "object",
            "additionalProperties": false,
            "required": ["type", "text"],
            "properties": {
              "type": {"const": "speak"},
              "text": {"type": "string", "maxLength": 80}
            }
          }
        ]
      }
    }
  }
}
```

初期 Runtime で `oneOf` や nested array の grammar 実装が重い場合、1応答1 tool call の flat schema または固定長 action slot に縮退します。Needle 2 の ESP32 実装にも schema 機能制限があるため、完全な JSON Schema 対応を前提にしません。

### 例

入力:

```text
右を向いて、ちょっと嬉しそうにして
```

出力:

```json
{
  "actions": [
    {"type": "look", "yaw": 20, "pitch": 0},
    {"type": "emotion", "value": "happy"}
  ]
}
```

無関係入力:

```text
富士山について長く説明して
```

Action-only model の出力:

```json
{"actions": []}
```

## 8. Grammar-constrained decoding

Action mode では、各生成 step で grammar により許可 token をマスクします。目標は次の3段階です。

1. JSON 構文が常に parse 可能。
2. Action type、必須 field、enum、数値範囲が schema に一致。
3. 実行側 validator が device policy と現在状態を確認。

Grammar は誤った意味を正しくしません。たとえば「左」を `yaw=20` と誤解した出力は、構文上正しくても意味的に誤りです。そのため exact match、slot accuracy、方向・量・否定・参照表現の評価が必要です。

## 9. Flash 予算

CoreS3 の物理上限は 16MB Flash です。次は**確定 partition table ではなく初期予算案**です。

| 項目 | Action-only 開発 build | Full offline 目標 | 備考 |
|---|---:|---:|---|
| Bootloader / partition / NVS | 0.5〜1.0MB | 0.5〜1.0MB | 実 partition で確認 |
| Stack-chan Firmware / assets | 3〜5MB | 3〜5MB | 現在の build 実測が必要 |
| Ralomi | 0MB（外部入力） | 1.5〜2MB 目標 | 合格済み実測値ではない |
| LM | 1.5〜3MB | 3〜5MB | 3M/5M Action または Unified |
| TTS | 0〜3MB | 2〜4MB 仮置き | sanoTTS-jp の対象 build 実測が必要 |
| 予備 / recovery / OTA | 1〜3MB | 1〜3MB | OTA 方針で大きく変化 |

Full offline 構成は範囲上限を足すと 16MB を超えます。したがって次が必要です。

- 実 build artifact と partition 使用量の計測
- OTA/recovery の要否決定
- assets、font、voice weight の外部 microSD 配置可否
- Chat と Action の Unified 化
- Model weight の mmap / streaming
- TTS/ASR の profile 縮小
- 機能別 Firmware build の採用

20M INT4 の約10MBはモデル単体でも支配的で、Full offline の標準構成には現実的でない可能性が高いです。20M は品質上限を測る研究用比較、または外部 storage 前提とします。

## 10. PSRAM / SRAM と時分割 workspace

CoreS3 の PSRAM 8MB は、LM だけが使える容量ではありません。KV cache、activation、audio buffer、display、network、ASR/TTS arena が競合します。

原則として pipeline を状態機械にし、大きな arena を共有します。

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
├── docs/
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
└── tests/
```

GitHub はコードと再現手順を1 repository にまとめ、Hugging Face は artifact を用途・サイズ・量子化ごとに分離します。

```text
ayutaz/JapaneseTinyAgentLM                  # GitHub 候補

ayutaz/JapaneseTinyAgentLM-5M-Base         # HF 候補
ayutaz/JapaneseTinyAgentLM-5M-Action
ayutaz/JapaneseTinyAgentLM-10M-Base
ayutaz/JapaneseTinyAgentLM-10M-Chat
ayutaz/JapaneseTinyAgentLM-10M-Action
ayutaz/JapaneseTinyAgentLM-10M-Unified
```

各 model card には architecture、Tokenizer、training data、license、quantization、Host/ESP32 評価、既知の限界、推奨用途、禁止用途を記載します。命名と公開先は未確定であり、既存名称・商標・repository との衝突を公開前に再確認します。
