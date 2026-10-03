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
   dispatcher（量・角度 → 可動域の制限 → 動きの計画）
        ┌─────────────┬──────┴──────┬──────────────┐
        ▼             ▼             ▼              ▼
 Servo（SCS0009 ×2） 表情（画面）  台座の LED   音量（speaker）・画面の明るさ
```

- 入力はテキストだけです。音声をつなぐ場合は、音声認識の結果のテキストをこの入力に渡します（音声認識と音声合成はこのリポジトリの範囲外です）。
- LM は servo の raw 値を出力しません。出力は方向、量（カテゴリ）か角度（度）、表情、回数、色、音量などの値で、raw 値への変換、可動域の制限、安全の確認は firmware が行います。
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

- 実機の速度は、data v0.4 のモデルで比べたときの計測です。採用した schema v1 の 3M は、中央値 1,042 ms です（[`results/v1_action/device/`](../results/v1_action/device/README.md)。評価に使った文と、出力の token 数が違います）。
- 3M は 5M より精度が高く、実機でも速い。20M との差は +0.7 point で、20M は INT4 でも LM の容量の目安（1.5〜5MB）を超える。
- data v0 のモデルでは 20M も 3M とほぼ同じ精度（83.9% と 84.4%）だった。精度が足りない原因は capacity ではなくデータの側と判断し、データの書き手を増やした（[`data.md`](data.md)）。

採用したモデルは、Action schema v1 の data v1.0（train 88,720 件 / validation 4,678 件）で、seed 0、12 epoch、lr 1e-3 で学習しました（前の版は data v0.5.1 の train 66,809 件）。手順は [`training.md`](training.md) にあります。

## Tokenizer と系列の形式

| 項目 | 内容 |
|---|---|
| 形式 | SentencePiece unigram、語彙 **2,048**、byte fallback あり、`nmt_nfkc` 正規化、数字は1文字ずつ、先頭の `▁` は付けない |
| 特殊 token | `<unk>` 0、`<s>` 1、`</s>` 2、`<pad>` 3、制御用の `<act>` と `<out>` |
| 1 token にまとめる断片 | 出力の JSON の固定の断片（`[]`、call の頭 `{"name":"look","arguments":{"direction":"`、引数の間の `","degrees":`、閉じ `"}}`、引数のない call `{"name":"bow","arguments":{}}` など）、enum の値（`left`、`up_left`、`slight`、`sleepy`、`light_blue` など）、**数字 `0`〜`9`**。user-defined symbol として登録する（`jtalm.model.format.JSON_PIECES`、`ENUM_VALUES`、`DIGITS`）。v0 では `0`、`4`、`6`〜`9` が語彙になく byte に分かれていたので、v1 で数字をすべて1 token にした |
| 学習に使った文 | data v1.0 の学習データと validation の入力文と出力、MASSIVE ja-JP の train の発話（合わせて 198,005行）。評価セットは使わない |
| 語彙を選んだ理由 | 出力の token 数は語彙によらず同じなので、入力側で比べた。v0 のとき、2k は未知の日本語（MASSIVE の dev）での byte fallback が 4k / 8k より少なく（1.3%。4k は 2.0%、8k は 2.2%）、embedding が最も小さい（d192 で 0.39M）。v1 も 2k にした（MASSIVE の dev の byte fallback は 1.0%） |

1件の系列は次の形です（`jtalm.model.format`）。

```text
<s> <act> 入力文 <out> 出力 </s>
```

- loss は `出力 </s>` の部分だけにかけます。
- 出力は、正規化した call を compact な JSON にしたもので、`name` を先に、引数を schema の順（`direction`、`amount`）に並べます（`target_json()`）。モデルが tool を決めてから引数を出せるようにするためです。parse すると、比較に使う正規形（`jtalm.action.to_json()`、key を並べ替えた形）と同じ call になります。
- JSON の断片を1 token にまとめたので、`look`（`amount`）1個は `[`、call の頭、方向、`","amount":"`、量、`"}}`、`]` の 7 token、角度の `look` は数字が1桁ずつなので 45° で 8 token（`","degrees":`、`4`、`5`、`}}`）、no-action の `[]` は 1 token です。data v1.0 では入力が平均 約 12 token、出力が平均 5.6 token（最大 14）、系列の最大が 71 token で、context 128 と出力の上限 24 token に収まります。
- 実機の応答時間は出力の token 数にほぼ比例するので、この tokenizer の設計がそのまま速さに効いています。

Tokenizer はモデルの学習より先に固定しました（v1 の `action_v1_sp2048`、sha256 `80eae3c8…`。v0 は `action_v0_sp2048`、sha256 `61482f90…`）。後から変えると、学習済みのモデルがすべて使えなくなるためです。v1 は新しい tool と値の断片を1 token にするために作り直したので、v0 と v1 の `.jtlm` は互いの firmware で動きません。この tokenizer は Action LM 専用で、Chat LM では一般的な日本語の corpus で作り直します。

## Action schema v1

### 方針

- 出力は `{"name": ..., "arguments": {...}}` の配列だけで、説明文を含めません。形式は TinyLM-Bench の16件（[`prior_art.md`](prior_art.md)）と同じにして、既存モデルと同じ評価器で比べられるようにしています。
- 1回の出力は **0〜2個**の call です。空配列 `[]` が no-action で、実行できない・無関係・危険・曖昧な入力、このロボットにない機器（部屋の照明、エアコンなど）への依頼には `[]` を返します。No-action は正式な出力として学習させます。
- 量はカテゴリ（slight / normal / large）でも、**数値**（`degrees` 1〜180、`level` 0〜100、`by` 1〜100、`count` 1〜5）でも出せます。数値は1桁ずつ生成し、grammar で桁ごとに範囲を制約します。角度の上限で制限するのは firmware です。
- 未知の action、未知の field、enum 外の値、範囲外の数値、必須引数の欠落、JSON の前後の説明文、**同じ call の重複**を拒否します。
- schema v0 の正しい出力は、v1 でもそのまま正しい出力です（v0 の tool と値はすべて v1 に含まれる）。

| tool | 引数（この順に出力） | 値 |
|---|---|---|
| `look` | `direction`、`amount` か `degrees` の一方 | 正面（yaw 0、pitch 0）を基準にした向き（絶対） |
| `turn` | `direction`、`amount` か `degrees` の一方 | 今の向きからの移動（相対） |
| `nod` | `count` | 1〜5 |
| `shake` | `count` | 1〜5（首を横に振る） |
| `bow` | なし（`"arguments":{}`） | お辞儀 |
| `set_expression` | `expression` | happy / sad / surprised / neutral / angry / sleepy / doubt |
| `set_led` | `color` | red / orange / yellow / green / light_blue / blue / purple / pink / white / off |
| `set_volume` | `level` | 0〜100 |
| `adjust_volume` | `direction`、`amount` か `by` の一方 | `direction` は up / down、`by` は 1〜100 |
| `set_brightness` | `level` | 0〜100 |
| `adjust_brightness` | `direction`、`amount` か `by` の一方 | `adjust_volume` と同じ |

- `direction`（`look` と `turn`）は left / right / up / down / up_left / up_right / down_left / down_right。`look` だけ center も使えます。`degrees` は斜めの方向では、左右と上下の両方をその角度にします。
- `look` の center は `amount` が `normal` のときだけ許します（`degrees` は付けられません。正規化では、center の `amount` を `normal` にそろえます）。
- 数値は JSON の整数（引用符なし）で、先頭の 0 は許しません（`0` そのものは `level` でだけ使える）。
- 言い方と出力の対応（データと評価で守る規則）: 「もう」「さらに」「もっと」「そこから」のように今の向きを基準にする語がある文は `turn`、それ以外は `look`。「45」「４５」「四十五」「45°」「45%」は同じ値。「半分」は 50、「最大」は 100、「消音」「ミュート」は `set_volume 0`。「LED」「内蔵ライト」「ライト」だけの文は `set_led`、「部屋の」「照明」「電気」がある文は `[]`。「エアコンを25度に」のように角度・音量でない「度」「%」は `[]`。
- schema の本体は `src/jtalm/action/action_schema_v1.json`（`jtalm.action.schema.TOOLS` の表から生成）です。`jtalm.action.validate()` が schema の検査に加えて重複の禁止を確かめます。設計の詳細は [`superpowers/specs/2026-10-02-action-schema-v1-design.md`](superpowers/specs/2026-10-02-action-schema-v1-design.md) にあります。
- このプロジェクトの規則（最大2個、重複の禁止）は TinyLM-Bench より厳しいので、同じ出力でも schema 妥当の数はベンチより少なくなることがあります。厳格一致の数は変わりません。

### 例

```text
顔を右に45度向いて
→ [{"name":"look","arguments":{"direction":"right","degrees":45}}]

もう少し右
→ [{"name":"turn","arguments":{"direction":"right","amount":"slight"}}]

音量を10下げて
→ [{"name":"adjust_volume","arguments":{"direction":"down","by":10}}]

右を向いて、ちょっと嬉しそうにして
→ [{"name":"look","arguments":{"direction":"right","amount":"normal"}},
   {"name":"set_expression","arguments":{"expression":"happy"}}]

お辞儀して
→ [{"name":"bow","arguments":{}}]

寝室のライトをつけて
→ []
```

### 前の版（schema v0）

v0（`src/jtalm/action/action_schema_v0.json`）は、`look`（`direction` は left / right / up / down / center、`amount` は slight / normal / large）、`set_expression`（happy / sad / surprised / neutral）、`nod`（`count` 1〜3）の3つだけで、角度の数値はありませんでした。v0.5.1 までのモデルはこの schema で学習しています。

## Grammar-constrained decoding

出力の token はすべて JSON の断片か enum の値なので、schema は token id の上の小さな状態機械で表せます（`src/jtalm/model/grammar.py`、C 版は `runtime/host/grammar.c`）。

```text
[] </s>
[ CALL ] </s>
[ CALL , CALL ] </s>        （2個目は1個目と同じ call にしない）

CALL = HEAD first [ KEY second ] CLOSE    （look / turn / adjust_* は2つ目の引数を持つ）
     | BOW                                （{"name":"bow","arguments":{}} の1 token）

例: LOOK direction ","degrees": 数字 数字 }}     （direction が center なら ","amount":" normal "}} だけ）
    NOD 数字 }}                                   （count は 1〜5）
    SET_VOLUME 数字 [数字 [数字]] }}              （level は 0〜100、先頭の 0 はなし）
```

enum の値は1 token、数値は1桁ずつで、桁ごとに「先頭の 0 を許さない」「範囲の外に出ない」ように許す数字を絞ります。Python 版は、すべての call を並べた trie をたどり、各 prefix の下に1個目と違う call が残る token だけを許すので、行き止まりにならず、重複も通しません。C 版は同じ規則を直接適用し、すべての1 call、重複しやすい2 call の組、ランダムな walk で Python 版と同じ許可集合になることを test で確かめています。

各 step で、状態機械が許す token の中から確率が最大のものを選びます（greedy）。この grammar の下で生成した出力は、必ず parse でき、schema を満たし、重複を含みません。

grammar が保証するのは構造と値の範囲だけです。「左を向いて」に `"direction":"right"` を返す誤りや、「18度」に 180 を返す誤りは、構文上は正しいので防げません。意味の誤りは、評価（完全一致、方向・量・否定などのカテゴリ別の集計）と、次の gate で扱います。

## Confidence gate

意味の誤りで誤って動くことを減らすため、生成の確信度が低い出力を実行しません。

- 指標は、生成した各 token の確率の**最小値**（`min_prob`）です。確率は grammar で制約する**前**の softmax で求めるので、grammar が強制した token は確信度を下げます（`jtalm.model.decode`）。
- `min_prob` が閾値を下回ったら、call 単位ではなく**出力全体**を `[]` にします。確信度の低い出力で動かないほうを安全側とします。
- 閾値は **validation だけ**で選びます。評価セットでは選びません。規則は「validation の完全一致の低下が 0.5 point 以内に収まる最大の閾値」です（`jtalm.model.evaluate --modes gate`）。
- 採用したモデル（schema v1、seed 0）の閾値は **0.88506** です（data v1.0 の validation 4,678 件で選んだ値。validation の完全一致は gate なし 98.3%、gate あり 97.8%）。閾値はモデルごとに選び直します（前の版の v0.5.1 は 0.86808）。
- 数値は桁ごとに確率が割れやすいので、数値のある文は gate で止まりやすくなります（Stack-chan v1 で数値のある文の 7.3 ± 4.1%。[`evaluation.md`](evaluation.md) の「弱いところ」）。
- firmware では標準で有効です。build 時の `CONFIG_JTALM_GATE_PPM`（100万分率。v1 の firmware の既定は 885060 = 0.88506）と、実行中の serial command `!gate <閾値>`（0 で無効）で変えられます。
- validation の書き手が1つしかないと、閾値がほぼ 1 に選ばれて gate が逆効果になりました（data v0）。書き手の多い validation を使うことが、閾値の選び方に効きます。

gate の効果（誤って動く割合の変化など）は [`evaluation.md`](evaluation.md) にあります。

## 量子化

重みだけを量子化します（`src/jtalm/model/quantize.py`）。

- 2次元の重み（attention、MLP、embedding = 出力 head）を、行ごとに **64 個ずつの group** で、対称の round-to-nearest で INT8 / INT4 にします。scale は group ごとに1つで、**fp16** で保存します。
- RMSNorm の重みは f32 のままです。activation と KV cache も f32 です（KV cache は build の設定で INT8 にもできます。下の「RAM」）。
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
- 3M の大きさは、FP32 で 12.9MB、INT8 で 3.5MB、**INT4 で 1,970,720 B**（schema v1 の採用モデル。v0.5.1 は 1,971,456 B。どれも tokenizer の約 0.27MB を含む）です。

## C の runtime（`runtime/host/`）

外部ライブラリに依存しない C11 の推論コードです。同じ `model.c`、`tokenizer.c`、`grammar.c` を、PC の host 版と ESP32 の firmware（`firmware/jtalm_action/`）の両方が copy せずに build します。ESP-IDF の component（`runtime/host/idf_component.yml`）として、ほかの ESP-IDF プロジェクトからも使えます。build と使い方は [`../runtime/host/README.md`](../runtime/host/README.md) にあります。

- `.jtlm` を読み、モデルの構造体はファイルの中を指すだけで、何も複製しません（ESP32 では flash を mmap した領域をそのまま渡す）。
- Tokenizer は SentencePiece の処理（`nmt_nfkc` の正規化、user-defined symbol、unigram の Viterbi、byte fallback）を C に移したものです。
- KV cache を使った greedy 生成、grammar による制約、`min_prob` の出力（gate 用）を持ちます。
- 書き換える状態は、`jtlm_state_bytes()` の大きさの arena 1つにまとめます。token ごとの malloc はありません。
- 入力は UTF-8 のファイルか stdin で渡します（Windows の console の code page に左右されないよう、argv では渡しません）。

### PyTorch との一致

C の tokenizer と生成は、PyTorch / SentencePiece と token 単位で一致します（評価セット 1,189 件、3M / 5M × FP32 / INT8 / INT4）。schema v1 の採用モデル（INT4）では、v1 の評価セットと validation の 11,426 件で、`double` と `float` の累積、grammar あり・なしのどれも一致し、WebAssembly 版も一致しました（[`results/v1_action/parity/`](../results/v1_action/parity/README.md)）。実機の出力も 300 / 300 件一致しました（[`results/v1_action/device/`](../results/v1_action/device/README.md)）。確かめ方と結果の詳細は [`../runtime/host/README.md`](../runtime/host/README.md) の「Python との一致の確認」にあります。

## ESP32-S3 での配置

対象はスタックチャン（K151。CoreS3、ESP32-S3、16MB Flash、8MB PSRAM）です。

### Flash

| partition | offset | 大きさ | 内容 |
|---|---:|---:|---|
| nvs | 0x9000 | 0x6000 | |
| phy_init | 0xF000 | 0x1000 | |
| factory（app） | 0x10000 | 0x1F0000（1,984KiB） | firmware。schema v1 の firmware は 536,192 B（約 524KiB） |
| model（data、subtype 0x40） | **0x200000** | 0xE00000（14MB） | `.jtlm` |

- 重みは `esp_partition_mmap` で model partition 全体を1回で map し、そのまま読みます。heap は使いません。
- Hugging Face で配布している書き込み用のイメージは、firmware とモデルを1つにしたもので、0x0 に書きます（[`../firmware/README.md`](../firmware/README.md)）。

### RAM

| 領域 | 大きさ（3M） | 置き場所 |
|---|---:|---|
| 重み（`.jtlm`） | 1,970,720 B | Flash から mmap |
| KV cache（f32、context 128） | 458,752 B | PSRAM |
| activation（16 token 分）、attention の score、logits | 125,952 B | 内部 SRAM |
| tokenizer の作業領域 | 32KB | 内部 SRAM |

- firmware は状態全体（3M で 584,704 B）を内部 SRAM に置こうとし、入らなければ KV cache だけを PSRAM に置きます（3M ではこの形になる）。
- 画面と dispatcher を載せた状態で、読み込み後の内部 SRAM の空きは 116,831 B、200 件の依頼の後は 99,039 B でした（v0.4 の firmware）。speaker、LED、NVS を加えた schema v1 の firmware では、初期化の後が 89,891 B、1,500 件の連続実行の後が 85,783 B です（[`results/v1_action/device/`](../results/v1_action/device/README.md)）。
- **INT8 の KV cache**（`-DJTLM_KV_INT8=1`、firmware では `CONFIG_JTLM_KV_INT8=y`）にすると、KV cache は 129,024 B になり、PSRAM を 330KB 減らせます。位置と KV head ごとに f32 の scale を1つ持ちます。3M では評価セット 4,794 件の gate 後の出力が f32 と同じで、実機の応答は約 2% 遅くなりました。PSRAM には余裕があるので、公開している firmware は f32 のままです（[`results/v051_action/kv_int8/`](../results/v051_action/kv_int8/README.md)）。

### 速くするための工夫

prompt をまとめて処理する prefill（最大 16 token）と、行列積を2つの core に分ける並列化を使います。どちらも計算の値を変えません。実機では1回の依頼が中央値 1,042 ms、p90 1,746 ms です（schema v1 の採用モデル、300件。[`results/v1_action/device/`](../results/v1_action/device/README.md)）。工夫の内容と効果は [`hardware.md`](hardware.md) の「速くするために行ったこと」にあります。

## Action から servo へ

firmware の dispatcher が、検証した Action を角度に変え、可動域（yaw ±45°、pitch 0〜+85°。下は頭が床に当たるので水平まで）に制限してから servo を動かし、`set_expression` は画面に顔を描き、`set_led`、音量、明るさの tool は台座の LED、speaker、画面の backlight を変えます（Python の参照実装は `jtalm.action.mapping.plan_v1`）。量ごとの角度、座標の規約、うなずき・首振り・お辞儀の動き、設定の保存、停止と watchdog は [`hardware.md`](hardware.md) の「Dispatcher」にあります。起動直後の servo は off です。首が動くので、servo を有効にするときは指やケーブルを近づけないでください。

## Chat LM（予定）

次に作る Chat LM は、短い日本語の応答を返すモデルです。実機に載せる候補は約 10M で、context は 128〜256 token、生成は 16〜64 token 程度を想定しています。世界知識より、短く自然な応答と、知らないことを作らないことを優先します。

Chat LM には一般的な日本語での事前学習が必要で、その corpus はまだ決めていません（corpus のライセンスが重みのライセンスに直結するため）。tokenizer も Chat 用に作り直します。`.jtlm` の形式と C の runtime は共通にする予定で、Chat 用の sampler は未実装です。Chat と Action を1つのモデルにまとめるか（Unified）は、mode の混ざりと精度の低下を測ってから決めます。
