# アーキテクチャ

Action LM の構成を、モデル、tokenizer、出力の形式、decoding、量子化、配布ファイル、C の runtime、ESP32-S3 での配置の順に説明します。プロジェクトの目的と範囲は [`overview.md`](overview.md)、評価の結果は [`evaluation.md`](evaluation.md)、実機の詳細は [`hardware.md`](hardware.md) にあります。

## 全体像

```text
             M5Stack のスタックチャン（K151）: CoreS3 / ESP32-S3

 日本語テキスト（実機は USB serial、PC は UTF-8 のファイルか stdin）
                           │
                           ▼
                  Action LM（3M、INT4）
                           │
                           ▼
            grammar で制約した greedy decoding
                           │
                           ▼
  確信度の gate（confidence gate。確信度が低ければ []）
                           │
                           ▼
          validator（schema、重複、可動域）
                           │
                           ▼
          dispatcher（カテゴリ → 角度 → servo）
                ┌──────────┴──────────┐
                ▼                     ▼
       Servo（SCS0009 ×2）        表情（画面）
```

- 入力はテキストだけです。音声をつなぐ場合は、音声認識の結果のテキストをこの入力に渡します（音声認識と音声合成はこのリポジトリの範囲外です）。
- LM は servo の raw 値を出力しません。出力はカテゴリ（方向、量、表情、回数）だけで、角度への変換と安全の確認は firmware が行います。
- すべて ESP32-S3 の CPU だけで動きます。Wi-Fi、NPU、外部モジュールは使いません。

## モデル

decoder-only Transformer です（`src/jtalm/model/transformer.py`）。

- RMSNorm（pre-norm）、RoPE、grouped-query attention（GQA）、SwiGLU の MLP
- 入力の embedding と出力 head の weight tying
- bias なし（C の runtime にそのまま写せるようにするため）
- context は 128 token

### 検討したサイズ

語彙は 2,048 で共通です（`jtalm.model.transformer.SIZES`）。

| 名前 | d_model | 層 | head（KV head） | FFN | parameter 数 | 位置づけ |
|---|---:|---:|---:|---:|---:|---|
| **3M** | 192 | 7 | 6（2） | 512 | 3,148,608 | **採用** |
| 5M | 256 | 6 | 8（2） | 768 | 5.05M | 評価して不採用 |
| 20M | 384 | 12 | 6（2） | 1,024 | 19.67M | PC だけの上限参照。実機には載らない |

サイズは data v0.4 で比べて決めました。

| model | 評価セット v0 の完全一致（2 seed の平均） | 重み（INT4、group 64） | `.jtlm` | 実機の1回の依頼（中央値、当時の計測） |
|---|---:|---:|---:|---:|
| **3M INT4** | **94.3%** | 1.68MB | 約 2.0MB | 1.08〜1.15 秒 |
| 5M INT4 | 93.3% | 2.69MB | 約 3.0MB | 1.79 秒 |
| 20M（FP、PC のみ） | 95.0%（1 seed） | 10.5MB | — | 実機に載らない |

- 実機の速度は、data v0.4 のモデルで比べたときの計測です。採用した v0.5.1 の 3M は、中央値 1,276 ms です（[`results/v051_action/device/`](../results/v051_action/device/README.md)。評価に使った文の長さが違います）。
- 3M は 5M より精度が高く、実機でも速い。20M との差は +0.7 point で、20M は INT4 でも LM の容量の目安（1.5〜5MB）を超える。
- data v0 のモデルでは 20M も 3M とほぼ同じ精度（83.9% と 84.4%）だった。精度が足りない原因は capacity ではなくデータの側と判断し、データの書き手を増やした（[`data.md`](data.md)）。

採用したモデルは、data v0.5.1（train 66,809 件 / validation 3,515 件）で、seed 0、12 epoch、lr 1e-3 で学習しました。手順は [`training.md`](training.md) にあります。

## Tokenizer と系列の形式

| 項目 | 内容 |
|---|---|
| 形式 | SentencePiece unigram、語彙 **2,048**、byte fallback あり、`nmt_nfkc` 正規化、数字は1文字ずつ、先頭の `▁` は付けない |
| 特殊 token | `<unk>` 0、`<s>` 1、`</s>` 2、`<pad>` 3、制御用の `<act>` と `<out>` |
| 1 token にまとめる断片 | 出力の JSON の固定の断片（`[]`、`{"name":"look","arguments":{"direction":"`、`","amount":"`、`"}}` など）と enum の値（`left`、`slight`、`happy` など）。user-defined symbol として登録する（`jtalm.model.format.JSON_PIECES`、`ENUM_VALUES`） |
| 学習に使った文 | data v0 の学習データと validation の入力文と出力、MASSIVE ja-JP の train の発話。評価セットは使わない |
| 語彙を選んだ理由 | 出力の token 数は語彙によらず同じなので、入力側で比べた。2k は未知の日本語（MASSIVE の dev）での byte fallback が 4k / 8k より少なく（1.3%。4k は 2.0%、8k は 2.2%）、embedding が最も小さい（d192 で 0.39M） |

1件の系列は次の形です（`jtalm.model.format`）。

```text
<s> <act> 入力文 <out> 出力 </s>
```

- loss は `出力 </s>` の部分だけにかけます。
- 出力は、正規化した call を compact な JSON にしたもので、`name` を先に、引数を schema の順（`direction`、`amount`）に並べます（`target_json()`）。モデルが tool を決めてから引数を出せるようにするためです。parse すると、比較に使う正規形（`jtalm.action.to_json()`、key を並べ替えた形）と同じ call になります。
- JSON の断片を1 token にまとめたので、`look` 1個は 7 token、no-action の `[]` は 1 token です。data v0 では入力が平均 約 8〜11 token、出力が平均 4.7 token、系列の最大が 52 token で、context 128 で足ります。
- 実機の応答時間は出力の token 数にほぼ比例するので、この tokenizer の設計がそのまま速さに効いています。

Tokenizer はモデルの学習より先に固定しました（sha256 `61482f90…`）。後から変えると、学習済みのモデルがすべて使えなくなるためです。この tokenizer は Action LM 専用で、Chat LM では一般的な日本語の corpus で作り直します。

## Action schema v0

### 方針

- 出力は `{"name": ..., "arguments": {...}}` の配列だけで、説明文を含めません。形式は TinyLM-Bench の16件（[`prior_art.md`](prior_art.md)）と同じにして、既存モデルと同じ評価器で比べられるようにしています。
- 1回の出力は **0〜2個**の call です。空配列 `[]` が no-action で、実行できない・無関係・危険・曖昧な入力には `[]` を返します。No-action は正式な出力として学習させます。
- 方向や量は数値ではなく**カテゴリ**（enum）で出力します。小さなモデルが数値を誤るのを避けるためで、角度への変換は firmware が行います。
- 未知の action、未知の field、enum 外の値、必須引数の欠落、JSON の前後の説明文、**同じ call の重複**を拒否します。
- tool の範囲外の要求（例:「部屋の電気を消して」）には `[]` を返します。

action は `look`、`set_expression`、`nod` の3種類です。`look` の `direction` は、ベンチの `left` / `right` / `center` に、pitch を使う `up` / `down` を加えた上位集合です。

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

- schema の本体は `src/jtalm/action/action_schema_v0.json` です。`jtalm.action.validate()` が schema の検査に加えて重複の禁止を確かめます。
- `center` のとき `amount` は意味を持たず、正規化では `normal` にそろえます。
- このプロジェクトの規則（最大2個、重複の禁止）は TinyLM-Bench より厳しいので、同じ出力でも schema 妥当の数はベンチより少なくなることがあります。厳格一致の数は変わりません。

### 例

```text
右を向いて、ちょっと嬉しそうにして
→ [{"name":"look","arguments":{"direction":"right","amount":"normal"}},
   {"name":"set_expression","arguments":{"expression":"happy"}}]

少し右を向いて
→ [{"name":"look","arguments":{"direction":"right","amount":"slight"}}]

右ではなく左を向いて
→ [{"name":"look","arguments":{"direction":"left","amount":"normal"}}]

右を向かないで
→ []

2回うなずいて
→ [{"name":"nod","arguments":{"count":2}}]

富士山について長く説明して
→ []
```

## Grammar-constrained decoding

出力の token はすべて JSON の断片か enum の値なので、schema は token id の上の小さな状態機械で表せます（`src/jtalm/model/grammar.py`、C 版は `runtime/host/grammar.c`）。

```text
[] </s>
[ CALL ] </s>
[ CALL , CALL ] </s>        （2個目は1個目と同じ call にしない）

CALL = LOOK direction ","amount":" amount "}}     （direction が center なら amount は normal）
     | EXPRESSION expression "}}
     | NOD count }}                                 （count は 1〜3）
```

各 step で、状態機械が許す token の中から確率が最大のものを選びます（greedy）。この grammar の下で生成した出力は、必ず parse でき、schema を満たし、重複を含みません。

grammar が保証するのは構造だけです。「左を向いて」に `"direction":"right"` を返す誤りは、構文上は正しいので防げません。意味の誤りは、評価（完全一致、方向・量・否定などのカテゴリ別の集計）と、次の gate で扱います。

## Confidence gate

意味の誤りで誤って動くことを減らすため、生成の確信度が低い出力を実行しません。

- 指標は、生成した各 token の確率の**最小値**（`min_prob`）です。確率は grammar で制約する**前**の softmax で求めるので、grammar が強制した token は確信度を下げます（`jtalm.model.decode`）。
- `min_prob` が閾値を下回ったら、call 単位ではなく**出力全体**を `[]` にします。確信度の低い出力で動かないほうを安全側とします。
- 閾値は **validation だけ**で選びます。評価セットでは選びません。規則は「validation の完全一致の低下が 0.5 point 以内に収まる最大の閾値」です（`jtalm.model.evaluate --modes gate`）。
- 採用したモデルの閾値は **0.868** です（data v0.5.1 の validation 3,515 件で選んだ値は 0.86808。validation の完全一致は gate なし 98.2%、gate あり 97.8%）。閾値はモデルごとに選び直します。
- firmware では標準で有効です。build 時の `CONFIG_JTALM_GATE_PERMILLE`（千分率、既定 868）と、実行中の serial command `!gate <閾値>`（0 で無効）で変えられます。
- validation の書き手が1つしかないと、閾値がほぼ 1 に選ばれて gate が逆効果になりました（data v0）。書き手の多い validation を使うことが、閾値の選び方に効きます。

gate の効果（誤って動く割合の変化など）は [`evaluation.md`](evaluation.md) にあります。

## 量子化

重みだけを量子化します（`src/jtalm/model/quantize.py`）。

- 2次元の重み（attention、MLP、embedding = 出力 head）を、行ごとに **64 個ずつの group** で、対称の round-to-nearest で INT8 / INT4 にします。scale は group ごとに1つで、**fp16** で保存します。
- RMSNorm の重みは f32 のままです。activation と KV cache も f32 です。
- 採用したのは **INT4 group 64** です。精度は FP32 と変わりません（data v0.4 の 3M: FP32 94.2% → INT4 94.3%。3M / 5M のどの組み合わせでも ±0.4 point 以内）。
- 量子化で挙動そのものが変わる例があるので（[`prior_art.md`](prior_art.md)）、量子化の後は評価セット全体をカテゴリ別に評価し直します。

## `.jtlm` ファイル形式

設定、tokenizer、RoPE の表、重みを1つにまとめた、little-endian のバイナリです（`jtalm.model.export` が書き出します。正確な仕様は `src/jtalm/model/export.py` の docstring にあります）。

| 区画 | 内容 |
|---|---|
| header（128 byte） | magic `JTLM`、format version 1、モデルの設定（vocab、d_model、層数、head 数、KV head 数、FFN、max_seq_len、rope_theta、norm_eps）、量子化の bit 数（0 = fp32、8、4）と group、各区画の offset と大きさ、SentencePiece model の sha256 |
| tokenizer | piece、score、type、先頭 byte ごとの索引、byte fallback 用の表、`nmt_nfkc` の正規化表（precompiled charsmap、約 0.24MB をそのまま格納） |
| RoPE の表 | PyTorch が計算した f32 の cos / sin（C で計算すると最後の bit がずれることがあるため） |
| 重み | embedding、層ごとに attn_norm、wq、wk、wv、wo、mlp_norm、w1（gate）、w3（up）、w2（down）、最後に norm |

- 各区画と各 tensor は 32 byte 境界にそろえます。
- 量子化した行列は、整数の値（INT4 は1 byte に2個。偶数番目が下位 4 bit、2の補数）のあとに、group ごとの fp16 の scale を並べます。
- 整数の値は `quantize_tensor` と完全に同じです（`torch.round` なので、ちょうど 0.5 は偶数に丸める）。復元した重み（整数 × fp16 の scale）は f32 で誤差なく表せるので、C と Python で同じ値になります。
- 3M の大きさは、FP32 で 12.9MB、INT8 で 3.5MB、**INT4 で 1,971,456 B**（どれも tokenizer の約 0.27MB を含む）です。

## C の runtime（`runtime/host/`）

外部ライブラリに依存しない C11 の推論コードです。同じ `model.c`、`tokenizer.c`、`grammar.c` を、PC の host 版と ESP32 の firmware（`firmware/jtalm_action/`）の両方が copy せずに build します。build と使い方は [`../runtime/host/README.md`](../runtime/host/README.md) にあります。

- `.jtlm` を読み、モデルの構造体はファイルの中を指すだけで、何も複製しません（ESP32 では flash を mmap した領域をそのまま渡す）。
- Tokenizer は SentencePiece の処理（`nmt_nfkc` の正規化、user-defined symbol、unigram の Viterbi、byte fallback）を C に移したものです。
- KV cache を使った greedy 生成、grammar による制約、`min_prob` の出力（gate 用）を持ちます。
- 書き換える状態は、`jtlm_state_bytes()` の大きさの arena 1つにまとめます。token ごとの malloc はありません。
- 入力は UTF-8 のファイルか stdin で渡します（Windows の console の code page に左右されないよう、argv では渡しません）。

### PyTorch との一致

C の tokenizer と生成は、PyTorch / SentencePiece と token 単位で一致します（評価セット 1,189 件、3M / 5M × FP32 / INT8 / INT4）。実機の出力も一致し、採用したモデルでは 300 / 300 件でした（[`results/v051_action/device/`](../results/v051_action/device/README.md)）。確かめ方と結果の詳細は [`../runtime/host/README.md`](../runtime/host/README.md) の「Python との一致の確認」にあります。

## ESP32-S3 での配置

対象はスタックチャン（K151。CoreS3、ESP32-S3、16MB Flash、8MB PSRAM）です。

### Flash

| partition | offset | 大きさ | 内容 |
|---|---:|---:|---|
| nvs | 0x9000 | 0x6000 | |
| phy_init | 0xF000 | 0x1000 | |
| factory（app） | 0x10000 | 0x1F0000（1,984KiB） | firmware。実際の大きさは約 494KB |
| model（data、subtype 0x40） | **0x200000** | 0xE00000（14MB） | `.jtlm` |

- 重みは `esp_partition_mmap` で model partition 全体を1回で map し、そのまま読みます。heap は使いません。
- Hugging Face で配布している書き込み用のイメージは、firmware とモデルを1つにしたもので、0x0 に書きます（[`../firmware/README.md`](../firmware/README.md)）。

### RAM

| 領域 | 大きさ（3M） | 置き場所 |
|---|---:|---|
| 重み（`.jtlm`） | 1,971,456 B | Flash から mmap |
| KV cache（f32、context 128） | 458,752 B | PSRAM |
| activation（16 token 分）、attention の score、logits | 125,952 B | 内部 SRAM |
| tokenizer の作業領域 | 32KB | 内部 SRAM |

- firmware は状態全体（3M で 584,704 B）を内部 SRAM に置こうとし、入らなければ KV cache だけを PSRAM に置きます（3M ではこの形になる）。
- 画面と dispatcher を載せた状態で、読み込み後の内部 SRAM の空きは 116,831 B、200 件の依頼の後は 99,039 B でした。
- INT8 の KV cache は未実装です（今後の課題）。

### 速くするための工夫

prompt をまとめて処理する prefill（最大 16 token）と、行列積を2つの core に分ける並列化を使います。どちらも計算の値を変えません。実機では1回の依頼が中央値 1,276 ms、p90 1,860 ms です（[`results/v051_action/device/`](../results/v051_action/device/README.md)）。工夫の内容と効果は [`hardware.md`](hardware.md) の「速くするために行ったこと」にあります。

## Action から servo へ

firmware の dispatcher が、検証した Action を角度に変え、可動域（yaw ±30°、pitch −10〜+15°）に制限してから servo を動かし、`set_expression` は画面に顔を描きます（Python の参照実装は `jtalm.action.mapping`）。量ごとの角度、座標の規約、うなずきの動き、停止と watchdog は [`hardware.md`](hardware.md) の「Dispatcher」にあります。起動直後の servo は off です。首が動くので、servo を有効にするときは指やケーブルを近づけないでください。

## Chat LM（予定）

次に作る Chat LM は、短い日本語の応答を返すモデルです。実機に載せる候補は約 10M で、context は 128〜256 token、生成は 16〜64 token 程度を想定しています。世界知識より、短く自然な応答と、知らないことを作らないことを優先します。

Chat LM には一般的な日本語での事前学習が必要で、その corpus はまだ決めていません（corpus のライセンスが重みのライセンスに直結するため）。tokenizer も Chat 用に作り直します。`.jtlm` の形式と C の runtime は共通にする予定で、Chat 用の sampler は未実装です。Chat と Action を1つのモデルにまとめるか（Unified）は、mode の混ざりと精度の低下を測ってから決めます。
