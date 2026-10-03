---
license: cc-by-sa-4.0
language:
- ja
tags:
- robotics
- function-calling
- tiny
- esp32
- microcontroller
- stack-chan
datasets:
- japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth
---

# JapaneseTinyAgentLM Action 3M

日本語の短い依頼文を、ロボットの動作呼び出し（JSON）に変える、パラメータ数 {{PARAMS}} の小さな言語モデルです。M5Stack のスタックチャン（CoreS3、ESP32-S3）の本体だけで動かすために、一から学習しました。NPU、外付けのモジュール、ネットワークは使いません。

```text
入力: 顔を右に45度向いて
出力: [{"name":"look","arguments":{"direction":"right","degrees":45}}]

入力: LEDライトの色を青にして
出力: [{"name":"set_led","arguments":{"color":"blue"}}]
```

コード（学習、評価、C の runtime、firmware）: [GitHub](https://github.com/ayutaz/JapaneseTinyAgentLM)（Apache-2.0）

**ブラウザで試す:** [デモ（Hugging Face Space）](https://huggingface.co/spaces/ayousanz/JapaneseTinyAgentLM-Action-3M-demo)。インストール不要で、実機と同じ C の runtime（WebAssembly）と INT4 の重みがブラウザの中で動きます。

*English summary at the end.*

> **この版は Action schema v1 です（2026年10月）。** 首の向きを角度でも指定でき、相対の移動、斜め、首振り、お辞儀、表情 7種類、LED の色、音量、画面の明るさを扱います。前の版（schema v0。`look`、`set_expression`、`nod` の3つだけ）は、このリポジトリの commit 履歴に残っています。v0 と v1 では tokenizer が違うので、`.jtlm` と firmware は同じ版のものを組み合わせてください（下の「スタックチャンで動かす」）。

## できること

出力は、次の 11 の動作を最大2個まで並べた JSON の配列です（[`action_schema_v1.json`](action_schema_v1.json)）。動作の依頼でない文、否定された依頼、このロボットにない機器への依頼（「寝室のライトをつけて」「エアコンを25度に」など）、このロボットにはできない依頼には `[]`（何もしない）を返します。

| 動作 | 引数 |
|---|---|
| `look`（正面を基準に首を向ける） | `direction`: left / right / up / down / up_left / up_right / down_left / down_right / center。`amount`（slight / normal / large）か `degrees`（1〜180 の整数）のどちらか |
| `turn`（今の向きから首を動かす） | `look` と同じ（center はなし） |
| `nod`（うなずく） | `count`: 1〜5 |
| `shake`（首を横に振る） | `count`: 1〜5 |
| `bow`（お辞儀） | なし |
| `set_expression`（表情） | `expression`: happy / sad / surprised / neutral / angry / sleepy / doubt |
| `set_led`（LED の色） | `color`: red / orange / yellow / green / light_blue / blue / purple / pink / white / off |
| `set_volume` / `set_brightness`（音量 / 画面の明るさ） | `level`: 0〜100 |
| `adjust_volume` / `adjust_brightness`（音量 / 明るさを上げ下げ） | `direction`: up / down。`amount`（slight / normal / large）か `by`（1〜100）のどちらか |

- 「もう」「さらに」「もっと」「そこから」のように今の向きを基準にする言い方は `turn`、それ以外は `look` です。
- `look` の center は `amount` が normal のときだけです（`degrees` は付きません）。同じ call を2つ並べることはありません。

公開したモデルの実際の出力の例です。

| 入力 | 出力 |
|---|---|
| 音声の音量を50にして | `set_volume(level=50)` |
| 頭を90度上に向けて | `look(up, degrees=90)` |
| もう少し右 | `turn(right, slight)` |
| 左上を向いて | `look(up_left, normal)` |
| 音量を10下げて | `adjust_volume(down, by=10)` |
| 少し暗くして | `adjust_brightness(down, slight)` |
| 首を横に振って | `shake(count=1)` |
| お辞儀して | `bow()` |
| 右を向いてから、2回うなずいて | `look(right, normal)`, `nod(count=2)` |
| 寝室のライトをつけて | `[]` |
| エアコンを25度にして | `[]` |
| 笑わないでね | `[]` |

## すぐに試す（Python）

必要なのは Python 3.10 以上と、PyTorch、NumPy、sentencepiece、safetensors だけです。GPU は要りません。

**1. インストール**

```bash
pip install torch numpy sentencepiece safetensors huggingface_hub
```

**2. ダウンロードして実行**

```bash
hf download ayousanz/JapaneseTinyAgentLM-Action-3M --local-dir JapaneseTinyAgentLM-Action-3M
python JapaneseTinyAgentLM-Action-3M/inference.py 顔を右に45度向いて 笑わないでね
```

```text
{"input": "顔を右に45度向いて", "actions": [{"name": "look", "arguments": {"direction": "right", "degrees": 45}}], "confidence": 0.9998, "raw": "..."}
{"input": "笑わないでね", "actions": [], "confidence": 1.0, "raw": "[]"}
```

引数を付けずに `python JapaneseTinyAgentLM-Action-3M/inference.py` と実行すると、標準入力から1行に1文ずつ読みます。

**Python から使う**

```python
import sys
from huggingface_hub import snapshot_download

folder = snapshot_download("ayousanz/JapaneseTinyAgentLM-Action-3M")
sys.path.insert(0, folder)
from inference import ActionModel

model = ActionModel(folder)
print(model("音声の音量を50にして"))
# [{'name': 'set_volume', 'arguments': {'level': 50}}]
print(model.predict("こんにちは"))  # {'actions': [], 'confidence': ..., 'raw': '[]'}
```

uv を使う場合は、インストールせずに `uv run --with torch --with numpy --with sentencepiece --with safetensors JapaneseTinyAgentLM-Action-3M/inference.py 右を向いて` でも動きます。

| 出力の項目 | 意味 |
|---|---|
| `actions` | 実行する動作のリスト。`[]` なら何もしない |
| `confidence` | 生成した token の確率の最小値。{{GATE}} 未満のときは、`actions` を `[]` にしています |
| `raw` | gate をかける前のモデルの出力 |

`inference.py` は、評価に使ったコードと同じ計算をする単体のスクリプト（約 300 行、Apache-2.0）です。評価セット全 6,748 文で、gate の前と後の出力が、評価したときの出力と完全に一致することを確かめています（`confidence` は小数4桁に丸めた値）。

## ロボットにつなぐ

`actions` を順に実行します。スタックチャン（K151）の firmware は次のようにしています。ほかのロボットでは、可動域に合わせて変えてください。

| 動作 | スタックチャンでの動き |
|---|---|
| `look` / `turn` の `amount` | 左右に slight 10°、normal 20°、large 30°。上下に slight 5°、normal 10°、large 15° |
| `look` / `turn` の `degrees` | その角度（斜めは左右と上下の両方をその角度に） |
| `look` | 正面（左右・上下とも 0°）からの向き。`left` / `right` は左右だけ、`up` / `down` は上下だけを決め、もう一方の軸はそのまま。center は正面 |
| `turn` | 今の向きからの移動 |
| `nod` | 今の上下の角度から下へ 14° 振って戻す往復を `count` 回（下に余地がない床の高さからは、上へ振る） |
| `shake` | 今の左右の角度から左右へ 15° の往復を `count` 回 |
| `bow` | 上下の角度が 20° より下なら、まず 20° まで上げる。そこから床（0°）まで下げ、0.5 秒止めてから元の角度に戻す |
| `set_expression` | 画面の顔を変える（首は動かさない） |
| `set_led` | 台座の RGB LED 12個を同じ色にする |
| `set_volume` / `adjust_volume` | speaker の音量（0〜100）。`adjust` の `amount` は slight ±10、normal ±20、large ±30。変えた後に確認音を鳴らす |
| `set_brightness` / `adjust_brightness` | 画面の明るさ（0〜100。下限は 5） |

- **可動域は firmware が必ず制限します。** スタックチャン（K151）では左右 ±45°、上下 0〜+85° です（水平より下は頭が床に当たるため）。`degrees` は 180 まで出るので、ほかのロボットでも、動かす前に必ず角度の上限で制限してください。
- 出力は必ず [`action_schema_v1.json`](action_schema_v1.json) に合います。
- 文字の入力を前提にしています。音声で使う場合は、音声認識の結果を入力してください（音声認識の誤りへの強さは評価していません）。

## スタックチャンで動かす

ビルド済みの firmware で、M5Stack のスタックチャン（K151。CoreS3 と SCS0009 の servo ×2）の本体だけで動きます。Wi-Fi は使いません。

> **書き込むと、今入っている firmware（公式のスタックチャンの firmware など）は消えます。** 元に戻したい場合は、先に手順 1 でバックアップを取ってください。

**0. インストール**（上の「すぐに試す」でダウンロード済みのフォルダを使います）

```bash
pip install esptool pyserial
```

USB-C でパソコンにつなぎ、port の名前を確かめます（Windows は `COM3` など、Linux は `/dev/ttyACM0`、macOS は `/dev/cu.usbmodem…`）。以下の `COM3` は自分の port に置き換えてください。

**1. バックアップ（任意。16MB、数分かかります）**

```bash
esptool --chip esp32s3 -p COM3 -b 921600 read-flash 0 0x1000000 backup_k151.bin
# 元に戻すとき: esptool --chip esp32s3 -p COM3 -b 921600 write-flash 0x0 backup_k151.bin
```

**2. 書き込み**（firmware とモデルが1つのファイルになっています。{{FIRMWARE_BYTES}} bytes）

```bash
esptool --chip esp32s3 -p COM3 -b 921600 write-flash 0x0 JapaneseTinyAgentLM-Action-3M/{{FIRMWARE}}
```

つながらないときは、本体の横のリセットボタンを緑の LED が点くまで約3秒押し続けて、書き込みモードにしてからやり直してください。書き込んだ後は、リセットボタンを1回押します。

**3. 話しかける**

```bash
python JapaneseTinyAgentLM-Action-3M/firmware/stackchan_chat.py COM3
```

```text
準備ができました。依頼を入力してください（終了は Ctrl+C）。
LEDライトの色を青にして
→ LED を青にする  1063 ms
  LED: 青
音声の音量を50にして
→ 音量を50にする  1128 ms
  音量: 50
頭を90度上に向けて
→ 上を向く（正面から90°）  1297 ms
  可動域の端で止めました
```

画面に顔が出て、表情の依頼で顔が変わります。LED の色、音量（確認音が鳴ります）、画面の明るさの依頼もこの段階で効き、再起動しても残ります。**起動したときは servo が off で、首は動きません**（動きの計画だけを作ります）。`--verbose` を付けると、Action の JSON も表示します。

**4. 首を動かす**

```bash
python JapaneseTinyAgentLM-Action-3M/firmware/stackchan_chat.py COM3 --servo
```

servo の電源が入り、首がゆっくり正面に戻ってから、依頼に合わせて首が動きます。首のまわりに指やケーブルを近づけず、本体は平らな机に置いてください。**画面に触れる、Ctrl+C を押す、`!stop` を送る、のどれかで、すぐに止まり servo の電源が切れます。** 角度は firmware が制限します（左右 ±45°、上下 0〜+85°。範囲を超える指示は端で止めます）。

| `!` で始まる command | 動き |
|---|---|
| `!servo on` / `!servo off` | servo の電源を入れる（首が動く）/ 切る |
| `!stop` | 動きを止めて servo の電源を切る |
| `!center` | 正面を向く |
| `!pose <左右> <上下>` | 指定した角度へ動く（例: `!pose 30 20`。右と上が正） |
| `!led <r> <g> <b>` | 台座の LED を指定した色にする（確認用。保存しない） |
| `!gate 0.9` | 確信度の gate の閾値を変える（既定 {{GATE}}。0 で off） |
| `!info` | モデルと firmware の情報 |

- 1文の応答時間は、中央値 1,042 ms、p90 1,746 ms でした（CoreS3、2コア、300文）。この 300文で、gate の前と後の出力が PC の PyTorch と完全に一致し、firmware の動きの計画も Python の参照実装と一致しました。1,500文を続けて処理しても、出力はすべて一致し、メモリの空きは減り続けませんでした。
- firmware は ESP-IDF v5.5.5 で build しました（app の sha256 `{{APP_SHA256}}`）。flash の配置は、bootloader 0x0、partition table 0x8000、app 0x10000、モデル（`{{JTLM}}`）0x200000 です。モデルだけを替えるときは、0x200000 に `.jtlm` を書き込みます。**この firmware は v1 の `.jtlm` だけを読みます。** v0 の `.jtlm` を書くと、起動時に `the tokenizer lacks the Action grammar pieces` の error を出して LM を止めます。
- firmware は Apache-2.0 です。同梱した第三者のコード（ESP-IDF、newlib、FreeRTOS、M5Unified、M5GFX など）のライセンスは [`firmware/licenses/`](firmware/licenses/README.md) にあります。firmware の source と build の手順は [GitHub](https://github.com/ayutaz/JapaneseTinyAgentLM/tree/main/firmware) にあります。

## ファイル

| ファイル | 内容 |
|---|---|
| `inference.py` | 単体の推論スクリプト（上の「すぐに試す」） |
| `{{FIRMWARE}}` | スタックチャン用の firmware とモデルを1つにした書き込み用のイメージ（0x0 に書く） |
| `firmware/stackchan_chat.py` | スタックチャンと USB serial で話すスクリプト |
| `firmware/licenses/` | firmware に含まれる第三者のコードのライセンス |
| `model.safetensors` | 評価した重み。INT4（group 64）で量子化した値を fp32 で保存したもので、ESP32 が計算する値と同じです |
| `model_fp32.safetensors` | 量子化する前の fp32 の重み（追加学習用） |
| `{{JTLM}}` | スタックチャンの firmware が読む形式（{{JTLM_BYTES}} bytes、sha256 `{{JTLM_SHA256}}`） |
| `tokenizer.model` | SentencePiece（unigram、2,048語）。JSON の部品と数字 0〜9 を1語として持ちます |
| `config.json` | 構造、tokenizer の hash、確信度の閾値（gate） |
| `action_schema_v1.json` | 出力の JSON Schema |
| `eval/` | 評価の表と、誤差の範囲 |
| `SHA256SUMS` | 各ファイルの sha256（`sha256sum -c SHA256SUMS` で確認できます） |

## 推論の仕組み

ほかの言語や環境に移すときは、`inference.py` と同じ次の手順にしてください。本モデルの評価の数値は、この手順で出したものです。

1. **入力:** `<s>` `<act>` 文の token 列 `<out>`。文は `tokenizer.model` で分割します（`<act>` と `<out>` は tokenizer にある記号です）。
2. **文法による制約:** `<out>` の後を `</s>` まで greedy に生成します（最大 24 token）。各 step で、schema に合う token だけから最も確率の高いものを選ぶので、出力は必ず schema に合う JSON になります。数値は1桁ずつ生成し、先頭の 0 と範囲の外の値を許しません。
3. **確信度の gate:** 生成した token（`</s>` を含む）の、制約をかける前の確率の最小値が {{GATE}} 未満なら、出力を `[]` にします。閾値は validation だけで決めました。

## 評価

INT4、文法による制約、gate {{GATE}} での結果です（%）。exact は出力の完全一致、requests exact は動作を求める文の完全一致、false actions は何もしないのが正解の文で動いてしまった割合、numeric gated は正解に角度や数値がある文のうち gate で `[]` になった割合です。

{{SUITE}}

| 評価セット | 書いたもの |
|---|---|
| Stack-chan v1 | スタックチャンで実際に使われている言い方の 140件。公開されているスタックチャンの例（M5Stack 公式ドキュメント、StackChan-Pocket-Core2、stackchan-live、AI_StackChan2_FuncCall など。出典とライセンスを1文ずつ記録）の 97件、利用者が普段使う4文、llm-jp-3.1-13b-instruct4 が書いた首の動きの言い換え 39件。正解は Qwen3（v1 の検証役）が付けた。そのうち 6件の正解と、除いた言い換え1件は、Claude が検証役の正解を見直して疑わしいものを挙げ、直し方を提案し、利用者がその提案の表を承認して決めた（全件を利用者が1件ずつ確かめたわけではない）。利用者の4文は利用者自身の文。紛らわしい `[]`（部屋の照明、エアコンの温度、命令でない文など）が 65件 |
| eval v3 (LLM) | 1,816件。llm-jp-3.1-13b-instruct4（学習データを書いたモデルとは別）が書き、Qwen3 が確かめた。新しい動作、数値の表記、絶対と相対、紛らわしい `[]` を含む |
| v0 eval (LLM) | 前の版の評価セット（1,189件）。v1 で正解が変わる文だけを付け直した |
| human v1 | 人が書いた公開コーパスの文（JESC、Tatoeba、YJ AmbigDialogue、J-CRe3、対話システムライブコンペ 3、MASSIVE）。v1 で付け直して、依頼 65件、依頼でない文 1,092件。学習には使っていない |
| v2/* | 苦手になりやすい12の型（言い回し、量、数、否定、言い直し、順序、断片、できない依頼、表記、疑問形、前置き、英語）。llm-jp-3.1-13b-instruct4 が書き、Qwen3 が確かめた。v1 で付け直した |

### 誤差の範囲

数値のぶれには2つの原因があります。

- **評価セットの大きさ:** 下の1つ目の表は、公開したモデルについて、評価の文を復元抽出し直して求めた 95% の区間です（2,000回）。Stack-chan v1 は 140件、人が書いた依頼文は 65件しかないので、区間が広くなります。
- **学習の seed:** 同じデータと設定で seed だけを変えて5回学習し、それぞれを同じ方法（INT4、文法、validation で決めた gate）で評価しました。下の2つ目の表は、5回の平均 ± 標準偏差です。

**公開したのは seed 0 です。** 評価の前に、公開するのは seed 0 と決めていました（評価セットで seed を選んでいません）。seed 0 は、Stack-chan v1 では 5つの中で最も低く（seed ごとに 92.9 / 94.3 / 95.0 / 95.0 / 95.0%）、人が書いた依頼文では seed 1 と並んで最も高い値でした（93.8 / 93.8 / 89.2 / 90.8 / 90.8%）。この版の実力は、5回の平均で見てください。

{{EXTRA}}

## 学習

- **構造:** decoder-only の Transformer（d_model 192、7層、GQA 6/2 head、SwiGLU 512、RoPE、RMSNorm、入出力の埋め込みを共有）。最大 128 token。
- **学習:** 88,720文（action v1.0）、12 epoch、lr 1e-3、1 GPU（RTX 3090）で約13分。validation の完全一致が最も高い epoch を採用しました。
- **量子化:** 2次元の重みを INT4（group 64、scale は fp16）。評価の数値は量子化した後のものです。

## 学習データ

| 出典 | 件数 | ライセンス |
|---|---:|---|
| オープンモデルが書いた合成文（正解を先に決め、Qwen3-30B-A3B-Instruct-2507 が温度 0 で確かめたものだけを残した） | 83,006 | 書いたモデルはすべて Apache-2.0 または MIT |
| JESC（映画・ドラマの字幕、主に何もしない例） | 3,221 | CC BY-SA 4.0 |
| Tatoeba の日本語文（主に何もしない例） | 1,370 | CC BY 2.0 FR |
| Amazon MASSIVE（ja-JP、主に何もしない例） | 1,123 | CC BY 4.0 |

- **前の版のデータ（v0.5.1）を引き継ぎました。** Qwen3 が schema v1 で読み直し、前の正解と一致した文だけを残しました（train 58,418件）。前の版で `[]` だった文のうち、LED、音量、明るさの依頼だとはっきり分かる文（「LED」「音量」「画面」などの語がある文）だけを、新しい正解に付け直しました（train 47件、validation 3件）。v1 の Qwen3 は 11 の tool で答えが揺れやすく、付け直しの候補の多くが誤りだったため、付け直しはこの範囲に絞り、それ以外の不一致の文は除きました。
- **新しい動作の文を足しました**（31,897件。train と validation の合計）。正解を先に決めた spec（角度の数値と表記の揺れ、絶対と相対、斜め、首振り、お辞儀、表情、LED、音量、明るさ、紛らわしい `[]`）を、Qwen3、calm3、ABEJA-Qwen2.5、Mistral-Nemo-Japanese、ELYZA-Shortcut が書き、Qwen3 が温度 0 で確かめて、正解と一致した文だけを残しました。
- 合成文を書いたモデル: Qwen/Qwen3-30B-A3B-Instruct-2507、cyberagent/calm3-22b-chat、abeja/ABEJA-Qwen2.5-32b-Japanese-v1.0、cyberagent/Mistral-Nemo-Japanese-Instruct-2408、elyza/ELYZA-Shortcut-1.0-Qwen-32B、ibm-granite/granite-3.3-8b-instruct（以上 Apache-2.0）、sbintuitions/sarashina2.2-3b-instruct-v0.1（MIT）。
- 人が書いた文のうち「何もしない」例の一部は、前の版のモデルが誤って動いた文を集め、Qwen3 が「何もしない」と確かめたものです。
- 評価セットの文と重なる文は学習データから除きました。Tatoeba と JESC は、hash で固定した約2割と評価セットの文を評価用に取り分け、学習には使っていません。
- 合成データの最初の版（v0）は [japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth) で公開しています。

## 限界と用途

- **`turn`（今の向きからの移動）は `look` より弱めです。** eval v3 の1動作の文で、`look` は 97.4 ± 1.3%、`turn` は 84.3 ± 2.0% でした。`turn` の誤りは、`look` と答えるものと、gate で止まるものがほぼ半分ずつです。Stack-chan v1 には `turn` の文がありません。
- **角度や数値のある文は、gate で止まりやすいです。** Stack-chan v1 で、正解に数値がある文の 7.3 ± 4.1%（seed 0 は 9.1%）が gate で `[]` になりました（eval v3 は 3.3 ± 0.5%）。学習データにない値（例:「18度」を 180 と読みかけて止まる）は、どの評価セットでも測れていません。
- **「首を振って」は、うなずき（`nod`）と首振り（`shake`）のどちらにも読めます。** 前の版の評価セット（v2/numbers）は「首を振って」を `nod` としていて、これがそのセットの依頼の正解率が 62.5 ± 7.6% に下がった主な原因の1つです（依頼 63件のうち「首…振」を含む 21件で、seed ごとの誤りは 7 / 17 / 7 / 13 / 13件。ほかの 42件では 13 / 13 / 11 / 13 / 11件）。
- **eval v3 には、1動作だけの LED、音量、明るさの文と、範囲の外の値（「音量を150%に」など）の文がありません。** これらは validation（モデルの選択に使ったもの）でだけ確かめています。
- **英語は扱えません。** 英語の依頼の正解率は約7%です。
- **ひらがなだけの文や、言い直しの文は弱めです**（表記 約83%、言い直し 約86%）。
- 決まった 11 の動作しか選べません。会話や質問への答えはしません。
- 文字の入力を前提にしています。音声認識の誤りへの強さは評価していません。
- **用途:** 小型ロボットや玩具で、日本語の短い指示から安全な範囲の動作を選ぶこと。人の安全にかかわる機械の制御、医療、監視などには使わないでください。出力は必ず schema と角度の上限で検証してから動かしてください（firmware はそうしています）。

## 先行例との関係

マイコンで動く言語モデルや、マイコンで動く tool calling のモデル（英語と欧州の言語）、外付けの NPU で動くスタックチャンの function calling には先行例があります。日本語の発話からロボットの動作呼び出し（JSON）を決める言語モデルを、ESP32-S3 単体（NPU・外部モジュール・ネットワークなし）で動かした公開事例は、2026年10月1日時点の私たちの調査では見つかりませんでした。調べた範囲と先行例の一覧は [`docs/prior_art.md`](https://github.com/ayutaz/JapaneseTinyAgentLM/blob/main/docs/prior_art.md) にあります。

## ライセンスと帰属

- 重み: **CC BY-SA 4.0**。コード: Apache-2.0（`inference.py`、`firmware/`。firmware の第三者のコードは `firmware/licenses/`。学習、評価、firmware の source は [GitHub](https://github.com/ayutaz/JapaneseTinyAgentLM)）。
- 学習データに次のものを含みます: [Tatoeba](https://tatoeba.org/)（CC BY 2.0 FR）、[JESC](https://nlp.stanford.edu/projects/jesc/)（Pryzant et al., 2018、CC BY-SA 4.0）、[Amazon MASSIVE](https://github.com/alexa/massive)（FitzGerald et al., 2022、CC BY 4.0）。
- 実装、データの生成と検査、学習、評価、firmware は Claude Code（Anthropic）が行いました。学習データの文章と正解は、上記のオープンモデルと人が書いた公開コーパス（MASSIVE など）とプログラムによるもので、Claude の出力は含みません。評価データの文章は、オープンモデル、人が書いた公開コーパス、公開されているスタックチャンの例、利用者の4文です。評価データの正解は、プログラムと Qwen3 が付けたものですが、Stack-chan v1 と前の評価セットを v1 で付け直した正解のうち 19件（Stack-chan v1 の 6件、前の評価セットの 13件）と、除いた言い換え1件は、Claude が検証役の正解を見直して疑わしいものを挙げ、直し方を提案し、利用者がその提案を承認して決めました。

## English summary

A {{PARAMS}}-parameter decoder-only Transformer, trained from scratch, that maps short Japanese requests to robot action calls (JSON, up to two per request) or `[]` for non-requests, negated requests, devices the robot does not have, and requests it cannot perform. This release uses **Action schema v1** (11 tools): `look` (absolute) and `turn` (relative) with a direction (including diagonals) and either an amount or `degrees` (1–180), `nod` / `shake` (count 1–5), `bow`, `set_expression` (7 faces), `set_led` (10 colors), `set_volume` / `set_brightness` (level 0–100) and `adjust_volume` / `adjust_brightness` (up/down by an amount or `by` 1–100). The previous v0 release (`look`, `set_expression`, `nod` only) is in this repository's commit history; v0 and v1 use different tokenizers, so use the `.jtlm` and the firmware of the same version.

It runs entirely on an ESP32-S3 (M5Stack Stack-chan K151, CoreS3) in INT4 with a median latency of 1.04 s per request (p90 1.75 s), identical to the PyTorch reference on 300 prompts (outputs before and after the gate, and the firmware's motion plans). Decoding uses a schema grammar plus a confidence gate ({{GATE}}, chosen on validation only); the reported numbers use both. Mean ± sd over five training seeds: 94.4 ± 0.9% exact on 140 everyday Stack-chan phrasings (no false action on its 65 confusable non-requests), 91.7 ± 2.1% on 65 human-written requests, 0.1 ± 0.1% false actions on 1,092 human-written non-requests, 95.3 ± 0.5% on the LLM-written eval v3 (1,816). Known weaknesses: relative `turn` (84% vs 97% for `look` on eval v3), numeric requests stopped by the gate (about 7% on the Stack-chan set), 「首を振って」 read as nod or shake, and English (about 7% of requests correct). The released seed 0 was fixed before evaluation. Weights are CC BY-SA 4.0; training data includes Tatoeba (CC BY 2.0 FR), JESC (CC BY-SA 4.0) and MASSIVE (CC BY 4.0) plus sentences written by Apache-2.0/MIT open models. Built by Claude Code.

Quick start (CPU is enough):

```bash
pip install torch numpy sentencepiece safetensors huggingface_hub
hf download ayousanz/JapaneseTinyAgentLM-Action-3M --local-dir JapaneseTinyAgentLM-Action-3M
python JapaneseTinyAgentLM-Action-3M/inference.py 顔を右に45度向いて
```

`inference.py` is a self-contained script (Apache-2.0) that reproduces the evaluated outputs exactly (6,748 of 6,748 evaluation prompts, before and after the gate). Training, evaluation and firmware source: [GitHub](https://github.com/ayutaz/JapaneseTinyAgentLM). **Try it in the browser:** [demo (Hugging Face Space)](https://huggingface.co/spaces/ayousanz/JapaneseTinyAgentLM-Action-3M-demo), no install; the same C runtime as the device (WebAssembly) with the INT4 weights runs in the page.
