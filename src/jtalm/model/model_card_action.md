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
入力: 左を見て、真ん中に戻ってきて。
出力: [{"name":"look","arguments":{"direction":"left","amount":"normal"}},
       {"name":"look","arguments":{"direction":"center","amount":"normal"}}]
```

*English summary at the end.*

## できること

出力は、次の3種類の動作を最大2個まで並べた JSON の配列です（[`action_schema_v0.json`](action_schema_v0.json)）。動作の依頼でない文、否定された依頼、このロボットにはできない依頼には `[]`（何もしない）を返します。

| 動作 | 引数 |
|---|---|
| `look`（首を向ける） | `direction`: left / right / up / down / center、`amount`: slight / normal / large |
| `set_expression`（表情） | `expression`: happy / sad / surprised / neutral |
| `nod`（うなずく） | `count`: 1〜3 |

評価セットでの実際の出力の例です（いずれも正解）。

| 入力 | 出力 |
|---|---|
| ほら 笑顔を見せて | `set_expression(happy)` |
| ほんの少し左を向いてくれる? | `look(left, slight)` |
| 右向いて、一回うなずきな。 | `look(right, normal)`, `nod(1)` |
| いや、下は見なくて大丈夫。上を向いてみて! | `look(up, normal)` |
| 右むかないで、ちょっとやめといてくれる? | `[]` |
| まっすぐ行って、右に曲がってください。 | `[]` |

## ファイル

| ファイル | 内容 |
|---|---|
| `model.safetensors` | 評価した重み。INT4（group 64）で量子化した値を fp32 で保存したもので、ESP32 が計算する値と同じです |
| `model_fp32.safetensors` | 量子化する前の fp32 の重み（追加学習用） |
| `{{JTLM}}` | スタックチャンの firmware が読む形式（{{JTLM_BYTES}} bytes、sha256 `{{JTLM_SHA256}}`） |
| `tokenizer.model` | SentencePiece（unigram、2,048語）。JSON の部品を1語として持ちます |
| `config.json` | 構造、tokenizer の hash、確信度の閾値（gate） |
| `action_schema_v0.json` | 出力の JSON Schema |
| `eval/` | 評価の表と、誤差の範囲 |

## 使い方

**出力の決め方（重要）:** 本モデルの数値は、次の2つを使ったときのものです。

1. **文法による制約:** 各 step で、schema に合う token だけから最も確率の高いものを選びます。出力は必ず schema に合う JSON になります。
2. **確信度の gate:** 生成した token の確率（制約をかける前の確率）の最小値が {{GATE}} 未満なら、出力を `[]` にします。閾値は validation だけで決めました。

**Python:** 推論のコードは [GitHub のリポジトリ](https://github.com/ayutaz/JapaneseTinyAgentLM) にあります。

```bash
uv run --group train python -m jtalm.model.release run <このリポジトリを置いた folder> 右を向いて
# {"input": "右を向いて", "output": [{"name": "look", "arguments": {"direction": "right", "amount": "normal"}}], "confidence": 0.9999}
```

**スタックチャン（ESP32-S3）:** `{{JTLM}}` を flash の 0x200000 に書き込み、リポジトリの `firmware/jtalm_action` を使います。USB serial で文を送ると、動作の JSON が返り、首の servo と画面の顔が動きます。

- 1文の応答時間の中央値は約 1.3 秒でした（CoreS3、2コア）。300文で、PC の PyTorch と出力が完全に一致しました。
- servo は Feetech SCS0009 ×2（K151）です。首の角度は firmware 側で制限します（左右 ±30°、上下 −10〜+15°）。

## 評価

INT4、文法による制約、gate {{GATE}} での結果です（%）。exact は出力の完全一致、requests exact は動作を求める文の完全一致、false actions は何もしないのが正解の文で動いてしまった割合です。

{{SUITE}}

| 評価セット | 書いたもの |
|---|---|
| v0 eval (LLM) | llm-jp-3.1-13b-instruct4（学習データを書いたモデルとは別）。Qwen3 が正解を確かめた |
| human v1 | 人が書いた公開コーパスの文（JESC、Tatoeba、YJ AmbigDialogue、J-CRe3、対話システムライブコンペ 3、MASSIVE）。依頼はルールで確実に判定できる文だけを選び、Qwen3 と答えが一致したものを残した（依頼 62件、依頼でない文 1,097件）。学習には使っていない |
| v2/* | 苦手になりやすい12の型（言い回し、量、数、否定、言い直し、順序、断片、できない依頼、表記、疑問形、前置き、英語）。llm-jp-3.1-13b-instruct4 が書き、Qwen3 が確かめた |

### 誤差の範囲

数値のぶれには2つの原因があります。

- **評価セットの大きさ:** 下の1つ目の表は、公開したモデルについて、評価の文を復元抽出し直して求めた 95% の区間です（2,000回）。人が書いた依頼文は 62件しかないので、区間が広くなります。
- **学習の seed:** 同じデータと設定で seed だけを変えて5回学習し、それぞれを同じ方法（INT4、文法、validation で決めた gate）で評価しました。下の2つ目の表は、5回の平均 ± 標準偏差です。

**公開したのは seed 0 です。** seed 0 は、ほかの seed を学習する前に実機への搭載と実機での検証（300文で PC と完全一致）を済ませていたモデルです。人が書いた依頼文では、5つの seed の中で最も高い値でした（seed ごとに 91.9 / 75.8 / 83.9 / 90.3 / 83.9%）。そのため、この評価セットでの実力は、5回の平均（約 85%）で見るのが妥当です。LLM が書いた評価セット（v0 eval）の依頼文は 88.1 ± 1.2% で、seed による差は小さいです。

{{EXTRA}}

## 学習

- **構造:** decoder-only の Transformer（d_model 192、7層、GQA 6/2 head、SwiGLU 512、RoPE、RMSNorm、入出力の埋め込みを共有）。最大 128 token。
- **学習:** 66,809文（action v0.5.1）、12 epoch、lr 1e-3、1 GPU で約12分。validation の完全一致が最も高い epoch を採用しました。
- **量子化:** 2次元の重みを INT4（group 64、scale は fp16）。評価の数値は量子化した後のものです。

## 学習データ

| 出典 | 件数 | ライセンス |
|---|---:|---|
| オープンモデルが書いた合成文（正解を先に決め、Qwen3-30B-A3B-Instruct-2507 が温度 0 で確かめたものだけを残した） | 約 6.1万 | 書いたモデルはすべて Apache-2.0 または MIT |
| Tatoeba の日本語文（何もしない例） | 1,524 | CC BY 2.0 FR |
| JESC（映画・ドラマの字幕、何もしない例） | 3,518 | CC BY-SA 4.0 |
| Amazon MASSIVE（ja-JP、何もしない例） | 1,169 | CC BY 4.0 |

- 合成文を書いたモデル: Qwen/Qwen3-30B-A3B-Instruct-2507、cyberagent/calm3-22b-chat、abeja/ABEJA-Qwen2.5-32b-Japanese-v1.0、cyberagent/Mistral-Nemo-Japanese-Instruct-2408、elyza/ELYZA-Shortcut-1.0-Qwen-32B、ibm-granite/granite-3.3-8b-instruct（以上 Apache-2.0）、sbintuitions/sarashina2.2-3b-instruct-v0.1（MIT）。
- 人が書いた文のうち「何もしない」例の一部は、前の版のモデルが誤って動いた文を集め、Qwen3 が「何もしない」と確かめたものです。
- Tatoeba と JESC は、hash で固定した約2割と評価セットの文を評価用に取り分け、学習には使っていません。評価セットの文と重なる文は学習データから除きました。
- 合成データの最初の版は [japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth) で公開しています。

## 限界と用途

- **英語は扱えません。** 英語の依頼の正解率は約5%です。
- **ひらがなだけの文や、言い直しの文は弱めです**（表記 約83%、言い直し 約84%）。
- **学習の乱数（seed）による差があります。** 同じデータと設定でも、人が書いた依頼文の正解率は seed によって 75.8〜91.9% と変わりました（上の「誤差の範囲」）。
- 決まった3種類の動作しか選べません。会話や質問への答えはしません。
- 文字の入力を前提にしています。音声認識の誤りへの強さは評価していません。
- **用途:** 小型ロボットや玩具で、日本語の短い指示から安全な範囲の動作を選ぶこと。人の安全にかかわる機械の制御、医療、監視などには使わないでください。出力は必ず schema と角度の上限で検証してから動かしてください（firmware はそうしています）。

## 先行例との関係

マイコンで動く言語モデルや、マイコンで動く tool calling のモデル（英語と欧州の言語）、外付けの NPU で動くスタックチャンの function calling には先行例があります。日本語の発話からロボットの動作呼び出し（JSON）を決める言語モデルを、ESP32-S3 単体（NPU・外部モジュール・ネットワークなし）で動かした公開事例は、2026年10月1日時点の私たちの調査では見つかりませんでした。詳しくはリポジトリの `docs/research_notes.md` §6.1 を見てください。

## ライセンスと帰属

- 重み: **CC BY-SA 4.0**。コード（GitHub）: Apache-2.0。
- 学習データに次のものを含みます: [Tatoeba](https://tatoeba.org/)（CC BY 2.0 FR）、[JESC](https://nlp.stanford.edu/projects/jesc/)（Pryzant et al., 2018、CC BY-SA 4.0）、[Amazon MASSIVE](https://github.com/alexa/massive)（FitzGerald et al., 2022、CC BY 4.0）。
- 実装、データの生成と検査、学習、評価、firmware は Claude Code（Anthropic）が行いました。学習データと評価データの文章と正解は、上記のオープンモデル、人が書いた公開コーパス、プログラムによるもので、Claude の出力は含みません。

## English summary

A {{PARAMS}}-parameter decoder-only Transformer, trained from scratch, that maps short Japanese requests to robot action calls (JSON: `look`, `set_expression`, `nod`; up to two per request) or `[]` for non-requests, negated requests and requests the robot cannot perform. It runs entirely on an ESP32-S3 (M5Stack Stack-chan, CoreS3) in INT4 with a median latency of about 1.3 s, bit-exact with the PyTorch reference on 300 prompts. Decoding uses a schema grammar plus a confidence gate ({{GATE}}); the reported numbers use both. Japanese only (English requests are about 5% correct). Results vary across training seeds: on the 62 human-written requests the five seeds scored 75.8–91.9% (mean 85.2%); the released seed 0 was deployed and verified on the device before the other seeds were trained, and is the highest of the five on that set. See the error-bar tables above. Weights are CC BY-SA 4.0; training data includes Tatoeba (CC BY 2.0 FR), JESC (CC BY-SA 4.0) and MASSIVE (CC BY 4.0) plus sentences written by Apache-2.0/MIT open models. Built by Claude Code.
