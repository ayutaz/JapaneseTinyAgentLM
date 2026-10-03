# Action schema v1 の設計

- 日付: 2026-10-02
- 状態: 設計（ユーザーと合意済みの内容をまとめたもの。実装計画は別の文書）
- 対象: Action LM（`src/jtalm/`、`runtime/`）と firmware（`firmware/jtalm_action/`）

## 1. 背景

利用者が普段スタックチャンに使っている次の4文が、採用モデル（v0.5.1 3M INT4、gate 0.868）ではほとんど動きませんでした。

| 入力 | v0 の出力 | 原因 |
|---|---|---|
| LEDライトの色を青にして | `[]` | schema v0 に LED の tool がない。学習データでも LED 系の文は `[]` と教えている |
| 音声の音量を50にして | `[]` | 同上（音量） |
| 頭を90度上に向けて | `[]`（gate 前は `look up normal`、確信度 0.587） | 角度の数値をほぼ学習していない（`look` に「N度」が付いた学習文は 66,809 文のうち 3 文）。`amount` が normal 0.587 と large 0.389 に割れ、gate で止まる |
| 顔を右に45度向いて | `look right normal`（0.997） | 動くが、45° ではなく 20° になる |

この4文は、M5Stack 公式の K151 firmware のドキュメントにある例文（「音量を 80% に設定して」「左に頭を回して」「内蔵ライトを青色にして」）とほぼ同じ形をしています。公式 firmware は、首の角度（yaw −128〜128、pitch 0〜90）、LED の RGB、音量と画面の明るさ（0〜100）を tool として持っています。

## 2. 目的と完了の条件

**目的:** スタックチャンで日常的に使われる言い方が、なるべくすべて通るようにする。自由度はなるべく高くする（角度は任意の整数、絶対と相対の両方）。

**完了の条件:**

1. 上の4文が、すべて 5 章の期待どおりの出力になる。
2. スタックチャン実例セット（4.4 節）の完全一致率が 90% 以上。紛らわしい `[]` の文（部屋の照明、エアコンの温度、命令でない文など）で誤って動いた件数が 0。
3. 人が書いた、動作の依頼でない文（human v1 の陰性 1,097 件）で誤って動いた割合が 0.5% 以下。
4. 人が書いた依頼文（human v1 の陽性 62 件）の正解率が、v0.5.1 の 5 seed 平均（85.2 ± 6.4%）より下がらない。
5. 実機（INT4、ESP32-S3）と PyTorch の出力が一致する。
6. 実機の応答時間の中央値が 2 秒以内。

## 3. 方針

- **schema v1 を定義し、tokenizer とモデルを作り直す。** 新しい tool と値の JSON の部品は1 token でなければならない（grammar の前提）ので、tokenizer を学習し直し、3M を最初から学習します。v0 のモデルへの token の継ぎ足しと fine-tune は、手順がなく、必要なデータ量も変わらないので採りません。
- **数値をルールの前処理で扱う案は採りません。** 自由度と「普段の言い方がすべて通る」の目的に合わないためです。
- **2つの sub-project に分けます。** 両者のつなぎ目は schema v1 だけです。
  - LM 側: schema、tokenizer、grammar（Python、C、Web）、データ、学習、評価、公開
  - firmware 側: 新しい動作を実機で実行する部分
- 1文の動作は、v0 と同じく最大2個です。
- v0 の正しい出力は、v1 でもそのまま正しい出力です（v0 の tool と値はすべて v1 に含まれる）。

## 4. schema v1

### 4.1 tool

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

- `direction`（`look` と `turn`）: left / right / up / down / up_left / up_right / down_left / down_right。`look` だけ center も使える。
- `amount`: slight / normal / large（v0 と同じ）。
- `degrees`: 1〜180 の整数。斜めの方向では、左右と上下の両方をその角度にする。
- `look` の center は、v0 と同じく `amount` が `normal` のときだけ許す（`degrees` は付けられない）。
- 数値は JSON の整数（引用符なし）。先頭の 0 は許さない（`0` そのものは `level` でだけ許す）。
- 2つの call が完全に同じ出力は許さない（v0 と同じ）。

### 4.2 言い方と出力の対応（データと評価で守る規則）

- **絶対と相対:** 「もう」「さらに」「もっと」「今から」「そこから」のように今の向きを基準にする語がある文は `turn`、それ以外は `look`。
- **数値の表記:** 「45」「４５」「四十五」「45°」「45%」は同じ値。「半分」は 50、「最大」は 100、「消音」「ミュート」は `set_volume 0`。
- **LED と部屋の照明:** 「LED」「内蔵ライト」「ライト」「光らせて」だけの文は `set_led`。「部屋の」「寝室の」「照明」「電気」がある文は `[]`（ロボットにない機器）。
- **「度」と「%」が角度・音量でない文:** 「エアコンを25度に」「温度は何度？」「0〜100の数字から選んで」は `[]`。
- **命令でない文:** 「左に鍵を置きました」「悲しい顔の絵について教えて」は `[]`（v0 と同じ考え方）。
- 否定、動作の依頼でない文、ロボットにできない依頼は、v0 と同じく `[]`。

### 4.3 tokenizer と出力の長さ

- JSON の部品（例: `{"name":"turn","arguments":{"direction":"`、`","degrees":`、`","by":`、`{"name":"bow","arguments":{}}`）と、新しい列挙値を、すべて SentencePiece の user-defined symbols にする。
- 数字 `0`〜`9` も user-defined symbols にする。v0 では `0`、`4`、`6`〜`9` が語彙になく、byte に分解されていた。
- 最長の出力は約 18 token（2 call、3 桁の数値を含む）で、`MAX_TARGET_TOKENS = 24` に収まる。

### 4.4 例

| 入力 | 出力 |
|---|---|
| LEDライトの色を青にして | `[{"name":"set_led","arguments":{"color":"blue"}}]` |
| 音声の音量を50にして | `[{"name":"set_volume","arguments":{"level":50}}]` |
| 頭を90度上に向けて | `[{"name":"look","arguments":{"direction":"up","degrees":90}}]` |
| 顔を右に45度向いて | `[{"name":"look","arguments":{"direction":"right","degrees":45}}]` |
| もう少し右 | `[{"name":"turn","arguments":{"direction":"right","amount":"slight"}}]` |
| 音量を10下げて | `[{"name":"adjust_volume","arguments":{"direction":"down","by":10}}]` |
| 少し暗くして | `[{"name":"adjust_brightness","arguments":{"direction":"down","amount":"slight"}}]` |
| 首を横に振って | `[{"name":"shake","arguments":{"count":1}}]` |
| お辞儀して | `[{"name":"bow","arguments":{}}]` |
| 寝室のライトをつけて | `[]` |

## 5. LM 側

### 5.1 コードの変更箇所

| 場所 | 変更 |
|---|---|
| `src/jtalm/action/action_schema_v1.json`（新規）、`schema.py`、`mapping.py` | schema v1、canonicalize、角度と段階の対応表 |
| `src/jtalm/model/format.py`、`grammar.py`、`data.py` | JSON の部品、引数の順、数値の sub-grammar（桁ごとに範囲を制約） |
| `src/jtalm/model/tokenizer.py` | v1 の user-defined symbols で tokenizer を学習 |
| `src/jtalm/eval/metrics.py`、`cases.py` | 新しい tool。数値は完全一致で評価し、誤差の分布も別に出す |
| `src/jtalm/eval/rule_baseline.py` | 変更なし（v0 の出力は v1 でも正しいので、基準としてそのまま使う） |
| `src/jtalm/data/specs.py`、`prompts.py`、`focus.py`、`massive.py`、`human_eval.py` | 新しい動作の spec、生成と検証の prompt（ロボットの説明、tool の説明、4.2 節の規則） |
| `src/jtalm/model/hf_inference.py`、`release.py` | v1 の grammar、schema v1 を同梱 |
| `src/jtalm/model/classifier.py` | 変更なし（v0 の出力は v1 でも正しいので、基準としてそのまま使う） |
| `runtime/host/grammar.c`、`jtalm.h`、`model.c` | v1 の状態機械。固定長の配列を広げる（候補 8 → 16 以上、1 call の token 数 3 → 6 以上） |
| `runtime/web/`（`web.c`、`index.html`） | v1 の grammar と表示 |
| `tests/` | 上の各変更の test。Python と C の grammar の一致を、v1 の全評価セットで確かめる |

### 5.2 学習データ v1.0

1. **v0.5.1 を引き継ぐ:** look、表情、うなずきの文は、v1 でも正解がそのまま正しいので残す。
2. **`[]` の文を付け直す:** v0.5.1 の `[]` の文のうち、v1 で動作になる文（音量、LED、明るさなど。MASSIVE 由来を含め数百文）を、Qwen3（温度 0、v1 の schema で制約）で付け直す。部屋の照明などは `[]` のまま。
3. **新しい動作の文を足す:** v0 と同じ流れ（正解を先に決めた spec → 複数の open model が書く → Qwen3 が温度 0 で検証し、正解と一致した文だけ残す）。重点は次の3つ。
   - 数値の表記ゆれ（4.2 節）と、値の範囲全体
   - 絶対と相対の言い分け
   - 紛らわしい `[]`（4.2 節）
4. 方針は v0 と同じ。文と正解の中身は、Apache-2.0 / MIT の open model（vast.ai で動かす）とライセンスの合う既存データから作り、Claude は pipeline のコードだけを書く。

### 5.3 評価セット

| セット | 作り方 | 用途 |
|---|---|---|
| スタックチャン実例セット v1（新規） | 公開されているスタックチャンの例（M5Stack 公式ドキュメント、StackChan-Pocket-Core2、stackchan-live、AI_StackChan_Ex など。約60文）と、利用者の4文。出典の URL とライセンスを1文ずつ記録する。実例が少ない部分（数値の角度、「少し右」、相対の指定）は llm-jp に言い換えを書かせて補い、「実例」と「言い換え」を分けて集計する。正解は Qwen3 が v1 の schema で付け、利用者が全件を確認する | 完了の条件 2 |
| eval v3（新規） | eval v2 と同じく、llm-jp が書き、Qwen3 が検証する。新しい動作と 4.2 節の規則を含める | 新しい動作の網羅的な評価 |
| v0 eval、human v1、eval v2 | v1 で正解が変わる文（音量、LED など）だけを付け直す | 退行の確認（完了の条件 3、4） |

どの評価セットも、学習にもモデルの選択（gate の閾値、checkpoint）にも使わない。

### 5.4 学習と量子化

- まず 3M（v0 と同じ構成）。足りなければ 5M と比べる。
- 誤差の範囲を出すため、seed を変えて5回学習する。
- INT4（group 64、fp16 scale）。gate の閾値は validation で選び直す。
- vast.ai を使う。借りる前に毎回利用者に確認し、終わったら破棄する。

### 5.5 公開

- モデルは、HF の同じ repo（`ayousanz/JapaneseTinyAgentLM-Action-3M`）を v1 で上書きする。v0 は HF の commit 履歴に残る。
- 学習データ v1.0 は `japanese-data-analyze` に出す。
- どちらも公開の直前に、利用者の確認を取る。

## 6. firmware 側

firmware は v1 の出力を受け付ける。v0 の出力も v1 の正しい出力なので、そのまま動く。

| 動作 | 実装 |
|---|---|
| `look` / `turn` | いまの計画（cosine の加減速、20ms ごとの目標、制限）を使う。`turn` は今の姿勢を基準にする。斜めは2軸を同時に動かす。`amount` の角度は v0 と同じ（yaw 10/20/30°、pitch 5/10/15°） |
| 可動域 | 公式 firmware の推奨範囲に合わせ、目標は yaw −45〜+45°、pitch −10〜+85°（上は公式の推奨の上限、下は v0 のまま）とした。公式の pitch は水平が 0、上が正で、v0 の座標と同じ向き。実機で少しずつ広げ、利用者が動きを見て確かめた結果（F2、2026-10-02）は **yaw −45〜+45°、pitch 0〜+85°**。yaw ±45° と pitch +85° にはどこでも届いた。水平より下は、頭が床に当たって +2.5° ほど（raw 628 前後）で止まるため、下の限界は 0° にした。範囲を超える指示は、v0 と同じく制限して `clamped` を付ける。`amount` による移動は v0 の角度のままなので、範囲を広げても変わらない |
| `shake` | 今の向きを中心に ±15° の往復を `count` 回。速さと加速度は `nod` と同じ |
| `bow` | 今の pitch が 20° より下なら、まず 20° まで上げる（床からだと下げる余地がないため）。そこから下の限界（0°、床）まで下げ、0.5 秒止めてから元の pitch に戻す（元が床なら戻る動きはない）。`nod` より遅い |
| 表情 | angry、sleepy、doubt の顔を、いまの4つと同じ描き方（`board.cpp` の `draw_face`）で足す |
| `set_led` | 台座の RGB LED 12個（PY32L020、I2C 0x6F）を同じ色で点ける。公式 firmware（m5stack/StackChan、MIT）と stack-chan 本家（Apache-2.0）の PY32 LED ドライバを参考にする。**最初に、実機で点くかを単独で確かめる。** 点かなければ、そこで止めて利用者と相談する |
| 音量 | スピーカーを有効にし、音量を変えたら短い確認音を鳴らす。`adjust` の段階は slight ±10 / normal ±20 / large ±30 |
| 画面の明るさ | `M5.Display.setBrightness`。下限は 5（0 だと顔が見えない）。touch による停止は、画面が暗くても効く |
| 設定の保存 | 音量、明るさ、LED の色を NVS に保存し、再起動後も残す |
| 検査（validator） | `action.c` の `js_call` を v1 に広げ、`jtalm.action.parse_output(...).schema_valid` と同じものだけを通す |

**確認の方法:**

- `firmware/tools/dispatch_check.py` を v1 に広げ、計画が `mapping.py` と一致することを確かめる。
- 実機では、次を確かめる。
  - PyTorch との出力の一致（数百件）
  - 長時間の連続動作（heap と温度）
  - 新しい動作それぞれの見た目（利用者の立ち会いが必要）
- `stackchan_chat.py` と Web デモの表示を v1 にする。

## 7. 進める順番

| 段階 | 内容 | 利用者の確認 |
|---|---|---|
| F1 | LED が実機で点くかを単独で確かめる（危険が最も大きいので最初に） | LED の点灯を見る |
| L1 | schema v1、Python の grammar と format、mapping、評価のコード、test | — |
| L2 | スタックチャン実例セット v1（実例の収集、llm-jp の言い換え、Qwen3 の正解付け） | 全件の正解を確認 |
| L3 | 学習データ v1.0 の生成と付け直し、eval v3 | vast.ai の利用 |
| L4 | tokenizer v1、3M の学習（5 seed）、gate の選択、必要なら 5M との比較 | vast.ai の利用 |
| L5 | C と Web の grammar、`inference.py`、PyTorch との一致 | — |
| F2 | 可動域を広げる | 首の動きを見る |
| F3 | dispatcher v1（`turn`、斜め、`shake`、`bow`、顔、LED、音量、明るさ、NVS） | 新しい動作を見る |
| F4 | 実機での一致、長時間の動作、応答時間 | — |
| L6 | 文書の更新、HF の上書き、データの公開 | 公開の直前に確認 |

L1 と F1 は並行できる。L2 は L1（schema）の後。F3 は L1 の後に始められ、モデルの完成（L4）を待たずに、PC で作った v1 の出力で試せる。

## 8. 危険と対策

| 危険 | 対策 |
|---|---|
| 台座の LED が点かない（stackchan-idf では失敗の記録がある） | F1 で最初に確かめる。点かなければ相談する（`set_led` を schema に残して firmware で無視する、などの選択肢） |
| 数値の桁は確率が割れやすく、gate で止まる率が上がる | validation で gate の閾値を選び直し、数値の文だけの止まり率を別に測る。止まり率が高ければ、数値の桁の扱い（gate の計算から外すなど）を validation で比べて決める |
| tool が増えて 3M では精度が足りない | 5M と比べる。v0 では原因が容量ではなくデータだったので、まずデータを見直す |
| `look` と `turn` の言い分けを、書き手の LLM が守らない | Qwen3 の検証で落とす。実例セットで、絶対と相対を分けて集計する |
| 可動域を広げると、配線や部品に負担がかかる | 少しずつ広げ、利用者が見て決める。速度と加速度の上限は v0 のまま |
| K151 の頭は水平より下を向けない（床に当たる、F2 で確認） | pitch の下限を 0° にする。`down` の指示は水平で止まり `clamped` が付く。`bow` は 20° まで上げてから下げ、`nod` は床からなら上へ振る |
| 実例が少なく、実例セットの偏りが大きい | 「実例」と「言い換え」を分けて集計する。結果は件数とともに示す |

## 9. 範囲外

- 音声認識（ASR）と音声合成（TTS）。音量は、確認音と将来の TTS のための設定として扱う。
- LED の明るさ、点滅などの演出、12個を個別に点ける指定。
- 時刻、天気、タイマーなど、ロボットの外の情報や機能（`[]` を返す）。
- 1文で3個以上の動作。
