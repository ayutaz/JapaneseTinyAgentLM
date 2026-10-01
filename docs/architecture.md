# アーキテクチャ設計

最終更新: 2026-09-29

## 1. システム境界

本プロジェクトのモデルは text-in / action-out（Action LM）または text-in / text-out（Chat LM）です。入力はテキストのみで、音声の入出力は本計画の範囲外です。

```text
                     CoreS3 / ESP32-S3（M5 スタックチャン K151）

 日本語テキスト（serial、PC では UTF-8 のファイルか stdin）
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
      Japanese Action LM         Japanese Tiny Chat LM
     （最初に完成させる）        （Action の完成後）
              │                         │
              ▼                         ▼
  grammar + confidence gate        短い日本語の応答
              │                    （テキストとして返す）
              ▼
   validator（schema、可動域）
              │
              ▼
   dispatcher（カテゴリ → 角度）
        ┌─────┴─────┐
        ▼           ▼
  Servo（SCS0009）   表情（画面）
```

初期実装では Chat と Action の同時常駐を要求しません。評価用 Firmware は用途別の build profile を持ち、最終段階で Unified Model を検討します。

将来 ASR や TTS と統合する場合は、入力の前段に音声認識を、Chat の出力の後段に音声合成をつなぎます。これは本計画の対象外です（[`README.md`](README.md) §5）。

対象の実機は M5 スタックチャン K151 です（[`hardware.md`](hardware.md)）。

- 図中の Servo は Feetech SCS0009 ×2 で、UART1（`G6` / `G7`、1Mbps）の SCS protocol で動かす。
- Servo の電源（`VM_EN`）は IO expander（PY32L020）が制御する。
- 検証済みの JSON を servo の命令に変換するのは firmware 側の dispatcher であり、LM は servo の raw 値を直接出力しない。
- **実装の状況（2026-09-30）:** 実機の firmware（`firmware/jtalm_action/`）は、LM、grammar、confidence gate に加えて、図の validator と dispatcher、表情の表示（M5GFX）、servo の制御（自前の SCS driver）を持ちます（A1〜A3、[`hardware.md`](hardware.md) §12）。servo の出力は標準で off（dry-run）で、実際に首を動かす確認はユーザーの立ち会いのもとで行います。

## 2. 共通 Base と派生モデル

### Base

日本語 next-token prediction を学習します。Tokenizer、embedding、Transformer block、LM head を Chat / Action で共有できる形にします。

### Chat

- 入力: 短い日本語指示・発話・状態文
- 出力: 短い日本語応答
- 目標規模: 実機の候補は 10M。20M は PC での品質比較（2-bit 量子化で 5MB に収まる可能性はあるが、kernel と品質が成立した場合のみ。§6）
- 目標 context: 128〜256 tokens
- 生成長: 原則 16〜64 tokens
- 世界知識より、短い自然な応答、キャラクター一貫性、不要な断定の抑制を優先

### Action

- 入力: 1〜2文の日本語の command または状態文。英語の命令は、評価用に少量だけ扱う。
- 出力: action call の JSON 配列（0〜2個）。空配列 `[]` が no-action。形式は §7。
- Tool: v0 は3種類（ベンチ互換）。v1 で 8〜16 種類に広げる。引数は enum と小さな整数だけにする。
- 目標規模: 3M / 5M / 10M を中心に比較する。量子化後の容量は §9 の LM 予算（1.5〜5MB）に収める。→ **3M（INT4）に決定**（2026-09-29、§3）。
- 目標 context: 64〜128 tokens。schema を prompt に含める方式では 256 も比較
- 自由生成は不要。構文妥当性、slot 値、no-action、安全性を優先
- Grammar 制約と confidence gate（§8）を基本機能とする

この狭い契約は、TinyLM-Bench の検証（[`research_notes.md`](research_notes.md) §3.7）に基づいています。28.9M の TinyStories モデルは速くても Action を扱えず、270M の FunctionGemma でもロボット固有の schema を誤りました。

### Unified（後期実験）

```text
<chat>
今日は疲れた
→ お疲れさま。ゆっくり休もう。

<action>
右を向いて
→ [{"name":"look","arguments":{"direction":"right","amount":"normal"}}]
```

Unified 化は Flash 節約に有効な可能性がありますが、negative transfer と mode leakage を測定したうえで採否を決めます。

## 3. モデルサイズ候補

INT4 の理論的な重み本体は、1 parameter あたり約0.5 byteです。ただし実 artifact には scale、zero point、alignment、Tokenizer、metadata が加わるため、単純計算より大きくなります。

| 規模 | INT4 重み理論値 | 主用途候補 | 現時点の見立て |
|---:|---:|---|---|
| 3M | 約1.5MB | Action 最小構成 | **Action LM に採用**（2026-09-29。下の「サイズの決定」） |
| 5M | 約2.5MB | Chat 下限実験 | Action では 3M を上回らなかった。Chat はかなり厳しい可能性 |
| 10M | 約5MB | Action 高精度、Chat 主候補 | LM 予算（§9）の上限 |
| 20M | 約10MB | Action の上限参照、Chat の品質比較 | **PC のみ。実機には載せない**（INT4 では LM 予算を超える） |

M4 で学習した構成（語彙 2,048、`jtalm.model.transformer.SIZES`）:

| 名前 | d_model | 層 | head（KV） | FFN | parameter 数 |
|---|---:|---:|---:|---:|---:|
| 3M | 192 | 7 | 6（2） | 512 | 3.15M |
| 5M | 256 | 6 | 8（2） | 768 | 5.05M |
| 20M | 384 | 12 | 6（2） | 1,024 | 19.67M |

### サイズの決定（2026-09-29）

Action LM は **3M（INT4）** に決めました。学習データ v0.4（書き手7つ、47,450件）での比較です（[`roadmap.md`](roadmap.md) §12）。

| model | 評価セットの完全一致（2 seed の平均） | 重み（INT4、group 64） | `.jtlm`（tokenizer 0.27MB を含む） | 実機の1回の依頼（中央値） |
|---|---:|---:|---:|---:|
| **3M INT4** | **94.3%** | 1.68MB | 約 2.0MB | 1.08〜1.15 秒 |
| 5M INT4 | 93.3% | 2.69MB | 約 3.0MB | 1.79 秒 |
| 20M（FP、PC のみ） | 95.0%（1 seed） | 10.5MB | — | 実機に載らない |

- 3M は 5M より精度が高く、実機でも速い。20M との差は +0.7 point で、容量の面で実機に載らない。
- INT4 にしても精度は落ちない（3M: FP32 94.2% → INT4 94.3%）。

設計上は 3M / 5M / 10M / 20M を同じ training code で比較可能にします。最初から全サイズを完走させず、最初の1周は 3M / 5M の Action と、PC だけの 20M 上限参照に限ります。10M Chat は、Action LM の完成後に取り組みます。

TinyLM-Bench の検証メモ（`94_model_validation_and_advantage_ja.md`）では、量子化後の容量を 4〜8MB とする案が出ていました。本計画では、LM 予算（§9）の 1.5〜5MB を優先します。8MB は INT4 で約 16M parameter に相当し、Action 専用のモデルとしては大きすぎるためです。

### 上限参照のモデル（PC のみ）

TinyLM-Bench の 91 は、Action 専用のモデルを 10M〜50M で学習することを勧めていました。本計画では、実機に載せる候補は 10M までにします。ただし、**実機には載せない上限参照**として、Action の 20M（必要なら 50M）も学習します（学習は vast.ai、評価は PC 上の host だけで行う）。

- 3M / 5M の精度が低いとき、原因が capacity なのか、data や tokenizer なのかを切り分けるため。
- 上限参照のモデルは実機に載せない。Needle 2（45M、13.7MB、PSRAM 約 7.7MB）でも、CoreS3 では周辺機能と同居する余裕が小さい。

## 4. Tokenizer と vocabulary

### 候補

- SentencePiece Unigram または BPE
- Byte fallback を有効化し OOV をなくす
- NFC 正規化（→ Action LM v0 では `nmt_nfkc` を採用。下の「固定した tokenizer」）
- 入力はテキストのみ。漢字仮名交じり文を主な対象とし、ひらがなだけの入力は頑健性の確認用に一部だけ扱う
- `<chat>`, `<action>`, `<eos>`, `<no_action>` 等の special token を予約（→ Action LM v0 では `<act>` と `<out>` を使い、no-action は専用の token ではなく `[]` を1 token にした）

### 比較する vocabulary

| 用途 | 候補 vocab | 理由 |
|---|---:|---|
| Action | 2,048 / 4,096 / 8,192 | 語彙表と LM head を小さくしやすい |
| Chat / 一般日本語 | 4,096 / 8,192 / 12,288 / 16,384 | 漢字・頻出 subword と系列長の折衷 |
| Unified | 4,096 を基準、8,192 と比較 | 共通化と日本語圧縮率のバランス |

例として vocab 4,096、hidden 256 の embedding は約1.05M parametersです。入力 embedding と出力 LM head は weight tying し、重複を避けます。

TinyLM-Bench の検証メモは 8k〜16k から始めることを提案していました。ただし、vocab 16,384、hidden 256 の embedding は約 4.2M parameter で、5M のモデルではほぼ全体を占めてしまいます。そこで語彙サイズは、2k〜16k の範囲を実測で比べて決めます。比べる指標は、coverage、byte fallback 率、平均 token 長、量子化後の精度です。

語彙の embedding が parameter 数を左右することは、既存モデルでも確認できます。TinyTalk 2 は「8M」と表記されていますが、実際は 19.7M parameter あり、その多くが 50,257 語の embedding です（[`research_notes.md`](research_notes.md) §3.7）。

**Tokenizer はモデルの本学習より先に固定します**（[`roadmap.md`](roadmap.md) §12 の M4）。Tokenizer を後から変えると、学習済みのモデルがすべて無駄になるためです。

### Action LM v0 で固定した tokenizer（M4、2026-09-29）

| 項目 | 内容 |
|---|---|
| 形式 | SentencePiece unigram、語彙 **2,048**、byte fallback あり、`nmt_nfkc` 正規化、数字は1文字ずつ、先頭の `▁` は付けない |
| 特殊 token | `<unk>` 0、`<s>` 1、`</s>` 2、`<pad>` 3、制御用の `<act>` と `<out>` |
| 1 token にまとめる断片 | 出力の JSON の固定の断片（`[]`、`{"name":"look","arguments":{"direction":"`、`","amount":"`、`"}}` など）と、enum の値（`left`、`slight`、`happy` など） |
| 学習に使った文 | 学習データと validation の入力文と出力、MASSIVE ja-JP の train の発話（CC BY 4.0）。評価セットは使わない |
| 系列の形 | `<s> <act> 入力文 <out> 出力 </s>`。入力は平均 約 8〜11 token、出力は平均 4.7 token（`look` 1個で 7 token、`[]` は 1 token）。系列の最大は 52 token なので、context は 128 で足りる |
| 選んだ理由 | 出力の token 数は語彙によらず同じなので、入力側で比べた。2k は、未知の日本語（MASSIVE の dev）での byte fallback が 4k / 8k より少なく（1.3%、4k は 2.0%、8k は 2.2%）、embedding が最も小さい（d192 で 0.39M） |
| 記録 | `datasets/manifests/tokenizer_action_v0.json`（3案の指標と sha256）。model ファイルは `tokenizer/out/`（Git の管理外） |

Chat LM や Unified では、一般的な日本語の corpus で tokenizer を作り直すので、この tokenizer は Action LM v0 専用です。

C の runtime（M6、`runtime/host/`）は、この tokenizer を SentencePiece と同じ結果になるように移植しています。`nmt_nfkc` の正規化表（precompiled charsmap、0.24MB）はそのまま `.jtlm` ファイルに入れ、C で直接引きます。書き出しは `jtalm.model.export`、一致の確認は `jtalm.model.parity` です。

Tokenizer 評価では vocabulary 数だけでなく、次も測ります。

- 文字あたり token 数、モーラあたり token 数
- Action command の P50 / P95 token 長
- 固有名詞、英数字、記号、JSON key の分割
- 漢字仮名交じりとひらがなの圧縮率差
- 入力ミス、変換ミス、全角・半角の表記ゆれに対する安定性

## 5. Transformer と推論方式

初期候補は decoder-only Transformer とし、実装を単純化します。

- hidden: 128〜384
- layers: 4〜12
- attention: MQA または GQA
- positional encoding: RoPE（M4 で採用）
- normalization: RMSNorm（M4 で採用）
- activation: SwiGLU 系と単純 FFN のサイズ・速度を比較
- weight tying: 必須候補
- context: 64 / 128 / 256
- KV cache: INT8 を基準とし、必要なら K/V の bit 幅を個別検討（→ M6 / B4 の実装は **f32 で PSRAM に置く**。INT8 の KV cache は未実装。3M で 458,752 B）
- sampling: Chat は greedy / top-k / temperature、Action は grammar 下で greedy（M5 で採用）

KV cache の概算は、一般には次で見積もります。

```text
bytes ≈ layers × context × 2(K,V) × kv_heads × head_dim × bytes_per_element
```

GQA/MQA、短い context、INT8 KV は PSRAM 削減に大きく効きます。実際の allocator overhead、alignment、temporary buffer を含め、実機 peak を別途測定します（→ B4 で測定済み。§10）。

採用した構成（M4）は、RMSNorm（pre-norm）、RoPE、GQA、SwiGLU、weight tying、bias なしの decoder-only Transformer です（`jtalm.model.transformer`）。Action の decode は grammar 下の greedy です。

## 6. Quantization と artifact

開発順は次を推奨します。

1. FP32/FP16 Host reference
2. PTQ INT8 で精度と export 経路を確立
3. weight-only INT4 または W4A8
4. 必要なら QAT
5. 2〜3bit は kernel と品質が成立した場合のみ

量子化は「Flash に入るか」だけでなく、次を同時に評価します。

- Host reference との logit error
- Action exact match の劣化（カテゴリ別。特に否定と no-action）
- Chat 品質の劣化
- dequantization を含む tok/s
- peak SRAM / PSRAM
- artifact size と alignment overhead
- 対応 kernel の保守性

**実施した方式と結果（M5〜M6）:** 重みだけを INT8 / INT4（行ごとに 64個ずつの group、対称、round-to-nearest）にし、scale は fp16 で持ちます（`jtalm.model.quantize`）。RMSNorm の重みは f32 のままです。3M / 5M のどちらでも、評価セットの精度は FP32 と ±0.4 point 以内で、INT4 でも落ちません。配布形式は、設定、tokenizer、RoPE の表、重みを1つにまとめた `.jtlm` ファイルです（`jtalm.model.export`）。整数の値は `quantize.py` と同じで、C の runtime は PyTorch と同じ出力になります（M6）。

量子化で挙動そのものが変わることがあります。TinyTalk 2 は、FP32 では「天気は分からない」と答えたのに、Q4 では晴れだと捏造しました（[`research_notes.md`](research_notes.md) §3.7）。そのため、量子化後は logit の誤差だけでなく、評価セット全体をカテゴリ別に評価し直します。

## 7. Action schema

### 基本方針

- 出力は説明文を含めず machine-readable な action のみ。
- 形式は TinyLM-Bench の共通評価（`eval/action_tools.json`）と同じ、`{"name": ..., "arguments": {...}}` の配列にする。既存モデルと同じ評価器で直接比較できるようにするため。
- 実行不能・無関係・危険・曖昧な要求には、空配列 `[]`（no-action）を返す。No-action は正式な出力として学習させる。
- 1回の出力は **0〜2個**の action に限る。
- 方向や量は数値ではなく**カテゴリ**（enum）で出力させる。小さなモデルが数値を誤るのを避けるためで、角度への変換は firmware 側の dispatcher が行う。
- 未知の action、未知の field、enum 外の値、必須引数の欠落、JSON 前後の説明文を拒否する。
- 同じ action call の重複を拒否する。FunctionGemma は、話題外の入力に同じ `look` を何度も返していた。
- Tool の範囲外の要求（例:「部屋の電気を消して」）には no-action を返す。

- Grammar が構文を保証しても、意味的安全性は confidence gate（§8）と実行側 validator が保証する。
- Action 実行前に、デバイス状態、速度制限、可動域、衝突条件を確認する。

v1 では tool を 8〜16 種類に広げます。候補は、K151 の周辺機器を使う `shake_head`（首を横に振る）、`look_around`、`set_led`（RGB LED）、`stop`（動作の停止）などです。追加する前に、TinyLM-Bench 互換の部分（v0 の3種類）の評価が崩れないことを確認します。

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
- 実装は `src/jtalm/action/`（M2 で実装済み）。schema の本体は `action_schema_v0.json` で、`jtalm.action.validate()` が schema の検査に加えて重複の禁止を確認する。比較と記録には `jtalm.action.to_json()` の compact な正規形（key を並べ替え、空白なし）を使う。
- 学習の教師データ（M4）には、`jtalm.model.format.target_json()` の形を使う。compact で、`name` を先に、引数を schema の順（`direction`、`amount`）に並べる。モデルが tool を決めてから引数を出せるようにするためで、parse すると正規形と同じ call になる。JSON の固定の断片（`{"name":"look","arguments":{"direction":"` など）と enum の値は tokenizer で1 token にまとめるので、`look` 1個は 7 token、no-action（`[]`）は 1 token になる。
- 本プロジェクトの規則は TinyLM-Bench より厳しい（最大2個、重複の禁止）。そのため、同じ出力でも schema 妥当の数はベンチより少なくなる（例: FunctionGemma はベンチでは 11/16、本プロジェクトでは 10/16）。厳格一致の数は変わらない。

初期 Runtime で `oneOf` や nested array の grammar 実装が重い場合は、固定長の 2 slot（各 slot は action または空）に縮退します。出力を 1 call に減らす縮退は、multi-action を扱えなくなるので採りません。Needle 2 の ESP32 実装にも schema 機能制限があるため、完全な JSON Schema 対応を前提にしません。

### 座標の規約と角度への変換（K151）

Action LM はカテゴリだけを出力し、firmware の dispatcher が K151 の servo の角度に変換します。規約は公式 firmware（[`hardware.md`](hardware.md) §3）に合わせます。

- **yaw:** 0 が正面で、**正の値が右**。公式 firmware には 0.1° 単位で渡す（制限は ±128°）。
- **pitch:** 中立位置からの相対値で、**正の値が上**。公式 firmware の pitch は 3°〜87° の絶対角で、値が大きいほど上を向く。K151 の実機では、中立（正面・水平）は yaw raw 460 / pitch raw 620 で、首をロボット自身の右へ回すと yaw の raw が減り、上を向くと pitch の raw が増える（[`hardware.md`](hardware.md) §10、2026-09-29 に確認）。dispatcher は yaw の符号を反転して raw に変換する。

| `amount` | `left` / `right` の yaw | `up` / `down` の pitch |
|---|---:|---:|
| `slight` | ∓10° / ±10° | ±5° |
| `normal` | ∓20° / ±20° | ±10° |
| `large` | ∓30° / ±30° | ±15° |

- 上の角度は初期値（設計目標）で、実機で首を動かす確認（[`hardware.md`](hardware.md) §12）で見え方を確かめてから確定する。実機の可動域は、この上限と stackchan-idf の soft limit の重なり（yaw −30〜+30°、pitch −10〜+15°）で、「下を大きく」（−15°）は −10° に制限される。
- うなずき（`nod`）は、今の pitch を中心に 8° 下げて戻す動きを `count` 回くり返す（上を向いたままでもうなずける）。`jtalm.action.mapping.nod_targets` と firmware は同じ動き。
- 最大値は yaw ±30°、pitch ±15° とし、公式の可動域より狭く保つ。安全上の上限は、実行側の validator で再確認する。
- `nod` は pitch を小さく往復させ、回数は `count` に従う。
- 連続回転（PWM mode）や raw position は、Action LM から指定させない。

符号の規約と中立位置は、2026-09-29 に B2 で確定しました（ユーザーの立ち会いのもとで実機を動かして確認。[`hardware.md`](hardware.md) §10）。1 step は 0.3125° なので、dispatcher は次の式で raw に変換します。

- yaw（右が正）: `raw = 460 − deg × 16 / 5`
- pitch（上が正）: `raw = 620 + deg × 16 / 5`

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
2. Action の `name`、必須 field、enum、値の範囲が schema に一致。
3. 実行側 validator が device policy と現在状態を確認。

Grammar は誤った意味を正しくしません。たとえば「左を向いて」に `"direction":"right"` を返した出力は、構文上正しくても意味的に誤りです。そのため exact match、slot accuracy、方向・量・否定・参照表現の評価が必要です。

TinyLM-Bench でも、Needle 2 は schema 妥当率が 16/16 でしたが、厳格一致は 3/16 でした（[`research_notes.md`](research_notes.md) §3.7）。

### Confidence gate

意味の誤りを実行前に止めるため、生成の確信度で出力を絞ります。

- 指標は、生成した各 token の確率の**最小値**（`min_prob`）。確率は grammar で制約する**前**の softmax で求めるので、grammar が強制した token は確信度を下げる（`jtalm.model.decode`）。
- `min_prob` が閾値を下回ったら、action 単位ではなく**出力全体**を no-action（`[]`）にする。
- 確信度の低い出力は、ロボットの誤作動につながるので、実行しないほうを安全側とする。
- 閾値は **validation** で決め、評価セットでは選ばない（`jtalm.model.evaluate --modes gate`。validation の完全一致の低下が 0.5 point 以内に収まる最大の閾値）。
- **現在の設定（2026-10-01）:** データ v0.5.1 の 3M では、v0.5.1 の validation（3,515件）で選んだ **0.868** を実機の標準にした（[`roadmap.md`](roadmap.md) §12）。閾値はモデルごとに validation で選び直す。
- **採用した設定（2026-09-29）:** 書き手7つの validation（v0.4、2,497件）で選んだ **0.970**。3M INT4 + grammar で、評価セットの完全一致は 94.3% → 94.4% のまま、致命的な誤りは 2.0% → 0.6% に減った。実機（`firmware/jtalm_action/`）では標準で有効で、閾値は build 時の `CONFIG_JTALM_GATE_PERMILLE`（千分率、既定 970）と、実行中の serial command `!gate <閾値>`（0 で無効）で変えられる。
- M4（validation の書き手が1つ）では、閾値がほぼ 1 に選ばれて gate は逆効果だった。validation の書き手の多様さが、閾値の選び方に効く。
- 曖昧な入力に対して「確認を求める」出力は、Chat と組み合わせる必要があるため v1 以降で検討する。

## 9. Flash 予算

CoreS3 の物理上限は 16MB Flash です。

### 本計画での LM 予算

本計画の範囲は LLM を作ることです（[`roadmap.md`](roadmap.md) §1）。LM は次の予算だけを前提に開発します。TTS / ASR との同居は前提にしません。

| 対象 | Flash の予算（設計目標） | 実測（2026-09-29） |
|---|---:|---:|
| 3M / 5M Action（INT4） | 1.5〜3MB | 採用した 3M INT4 の `.jtlm` は約 2.0MB（1,971,456 B、tokenizer 0.27MB を含む）。5M INT4 は約 3.0MB |
| 10M Chat / Action / Unified（INT4） | 3〜5MB | — |

- 自前の最小 firmware（B3 の `jtalm_eval`、B4 の `jtalm_action`）では、`model` partition（subtype 0x40）を `0x200000` に 14MB 取り、`.jtlm` を置きます。1回の `esp_partition_mmap` で全体を map できます（[`hardware.md`](hardware.md) §8、§11）。App は 0x10000 から 1,984KiB（`jtalm_action` の app は約 250〜270KB）。
- Servo 制御や画面を載せた状態の Flash と memory は、まだ測っていません。

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

20M INT4 の約10MBはモデル単体でも支配的で、LM 予算（1.5〜5MB）を超えます。本計画では、20M は PC だけで学習する上限参照と品質比較に使い、実機には載せません（§3）。

## 10. PSRAM / SRAM と時分割 workspace

### 本計画での LM の memory 予算

| 領域 | 予算（設計目標） | 置き場所 |
|---|---:|---|
| LM workspace（KV cache、activation、sampler、grammar mask） | ≤4.0MB | PSRAM |
| 常駐 runtime、metadata、小さな buffer | ≤1.5MB | PSRAM |
| GEMV の scratch などの高速 buffer | 数十 KB 以下 | 内部 SRAM |

**実装した配置と実測（B4、3M INT4、[`hardware.md`](hardware.md) §11）:**

| 領域 | 大きさ | 置き場所 |
|---|---:|---|
| 重み（`.jtlm`） | 約 2.0MB | Flash から mmap（heap を使わない） |
| KV cache（f32、context 128） | 458,752 B | PSRAM |
| activation（16 token 分）、attention の score、logits | 125,952 B | 内部 SRAM |
| tokenizer の作業領域 | 32KB | 内部 SRAM |

- 書き換える状態は1つの arena（`jtlm_state_bytes()`、3M で 584,704 B）にまとめ、token ごとの malloc はありません。
- 入力はまとめて処理し（batch prefill、最大 16 token ずつ）、行列の計算は2つの core で行を分けます（LM の task は core 1、行列の worker は core 0）。どちらも計算の値を変えません。
- 読み込み後の内部 SRAM の空きは 3M で約 140KB（最大連続ブロック 90KB）、5M で約 90KB。PSRAM の空きは約 7.9MB です。
- 上の設計目標の「activation を PSRAM に置く」案は、速さのために変えました（activation は内部 SRAM）。
- 内部 SRAM の参考値: 受領時の firmware では起動直後の空きが約 155KB でした（[`hardware.md`](hardware.md) §4）。自前の最小 firmware（B3）では 335,663 B です（§8）。
- 画面、servo、M5Unified を載せた状態の memory は、まだ測っていません。

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

**実装の状況（2026-09-29）:** `runtime/host/`（M6）と `firmware/jtalm_action/`（B4）で、loader、tokenizer、Transformer の各層、RoPE、量子化した行列の計算、KV cache、grammar 付きの Action sampler、confidence gate、latency と memory の telemetry（`JTALM {json}` の行）、host との一致の確認（golden vector は `results/m6_parity/*/golden.jsonl`）を実装しました。実機側の JSON validator、dispatcher、watchdog、停止（画面への touch、`!stop`）も実装しました（A1〜A3）。Chat の sampler は未実装です。

Host と ESP32 の双方で同じ golden vector を読み、Tokenizer、1-layer、full forward、KV incremental decode、grammar mask を段階的に照合します。

Windows の host runtime では、日本語の入力を UTF-8 のファイルか stdin から読みます。argv では渡しません。TinyLM-Bench では、needle-2-esp32 の C host に argv で日本語を渡すと制限がありました。

## 12. 入力の interface

入力はテキストのみです（2026-09-29 決定）。LM への入力は、UTF-8 の日本語テキストとして受け取ります。実機では serial、PC では UTF-8 のファイルか stdin から渡します。

### 参考: 将来の ASR 接続の案（本計画の対象外）

将来 ASR（Ralomi など）と統合する場合に、LM が ASR の内部実装へ依存しないための最低限の契約です。

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
├── .python-version         # 3.13
├── pyproject.toml          # uv 管理（依存は uv add のみ）
├── uv.lock
├── docs/
├── src/jtalm/              # Python パッケージ（import 名は jtalm）
│   ├── action/             # Action schema v0（action_schema_v0.json）、validator、正規化、角度への変換（M2）
│   ├── eval/               # 評価指標、評価セットの読み込み、baseline（M2〜M3）
│   ├── data/               # 合成データの生成・検査・分割・manifest（M3）
│   ├── infra/              # vast.ai の job runner、vastai と SSH の wrapper、job の定義（M2.5）
│   └── model/              # 系列の形式、tokenizer、Transformer、学習、greedy decode、評価（M4）、grammar と量子化（M5）、.jtlm の書き出しと C との一致の確認（M6）
├── datasets/
│   ├── manifests/          # データの出典・ライセンス・hash（commit する）
│   ├── action/             # 生成したデータ本体 v0 / v0.3 / v0.4（Git 管理外。Hugging Face で公開したのは v0 だけ）
│   └── downloads/          # MASSIVE などの取得物（Git 管理外）
├── tokenizer/out/          # 学習した tokenizer の出力（Git 管理外。M4）
├── runs/vast/              # vast.ai の実行記録と回収物、checkpoint（Git 管理外）
├── results/                # 評価の比較表と学習の記録（commit する。例: m4_action_v0/）
├── configs/                # 生成と学習の設定
├── runtime/host/           # Host C reference runtime（M6）。ESP32 の firmware もこの source を build する
├── firmware/
│   ├── jtalm_eval/         # memory と帯域を測る最小 firmware（B3）
│   ├── jtalm_action/       # Action LM を動かす firmware（B4）
│   ├── baselines/          # esp32-llm、stackchan-idf 用の overlay / patch / shim（B2、B2.5）
│   ├── tools/              # serial の取得、LM の一致と速度の計測
│   └── third_party/        # 第三者の clone（Git 管理外）
├── tests/                  # fixtures/tinylm_bench/ に TinyLM-Bench の16件と既存モデルの出力
└── backups/                # 実機 Flash のバックアップ（Git 管理外）
```

上の構成はすべて作成済みです（2026-09-29、M6 と B4 の完了時点）。学習は `src/jtalm/model/train.py` で行い、独立した `training/` は作っていません。

GitHub はコードと再現手順を1 repository にまとめ、Hugging Face は artifact を用途・サイズ・量子化ごとに分離します。

```text
ayutaz/JapaneseTinyAgentLM                                    # GitHub（private で作成済み）

ayousanz/JapaneseTinyAgentLM-Action-3M                        # HF のモデル（3M、v0.5.1 seed 0、INT4。2026-10-01 公開）
ayousanz/JapaneseTinyAgentLM-10M-Base
ayousanz/JapaneseTinyAgentLM-10M-Chat
ayousanz/JapaneseTinyAgentLM-10M-Unified
japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth       # HF の dataset（public、manual gate。M3 で公開済み）
```

Hugging Face の公開先は、**モデルはユーザーのアカウント [`ayousanz`](https://huggingface.co/ayousanz)**、データセットは organization の [`japanese-data-analyze`](https://huggingface.co/japanese-data-analyze) です（2026-09-29 決定）。モデルを公開する前には、必ずユーザーの確認を取ります。Action LM の 3M は、ユーザーの確認を取って 2026-10-01 に [`ayousanz/JapaneseTinyAgentLM-Action-3M`](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M) で公開しました（`jtalm.model.release`）。5M は採用しなかったので、5M の Action の repository は作りません。どの repository も Community contributions は off にします。各 model card には architecture、Tokenizer、training data、license（CC BY-SA 4.0）、quantization、Host/ESP32 評価、既知の限界、推奨用途、禁止用途を記載します。**モデルの** repository の名前は未確定で（データセットは `JapaneseTinyAgentLM-Action-Synth` で公開済み）、既存の名称、商標、repository との衝突を公開前に確認します。
