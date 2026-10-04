# JapaneseTinyAgentLM

[![CI](https://github.com/ayutaz/JapaneseTinyAgentLM/actions/workflows/ci.yml/badge.svg)](https://github.com/ayutaz/JapaneseTinyAgentLM/actions/workflows/ci.yml)
[![Code: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue.svg)](LICENSE)
[![Model: CC BY-SA 4.0](https://img.shields.io/badge/model-CC%20BY--SA%204.0-lightgrey.svg)](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M)
[![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97-Action--3M-yellow.svg)](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M)
[![Demo](https://img.shields.io/badge/%F0%9F%A4%97-demo-orange.svg)](https://huggingface.co/spaces/ayousanz/JapaneseTinyAgentLM-Action-3M-demo)

[English](README.en.md)

マイコン（ESP32-S3）の上だけで動く、日本語の超小型言語モデルです。最初のモデル **Action LM**（315万パラメータ）は、日本語の短い依頼を、ロボットの動作の呼び出し（JSON）に変えます。M5Stack のスタックチャン（K151、CoreS3）の本体だけで、NPU もネットワークも使わずに、首を動かし、表情、LED の色、音量、画面の明るさを変えます。

```text
入力: 顔を右に45度向いて
出力: [{"name":"look","arguments":{"direction":"right","degrees":45}}]

入力: LEDライトの色を青にして
出力: [{"name":"set_led","arguments":{"color":"blue"}}]
```

## 目次

- [何ができるか](#何ができるか)
- [結果](#結果)
- [すぐに試す](#すぐに試す)
- [対応ハードウェアと安全](#対応ハードウェアと安全)
- [リポジトリの構成](#リポジトリの構成)
- [ドキュメント](#ドキュメント)
- [開発](#開発)
- [データとライセンス](#データとライセンス)
- [ロードマップ](#ロードマップ)
- [先行例との関係](#先行例との関係)
- [引用](#引用)

## 何ができるか

出力は、次の 11 の動作（Action schema v1）を最大2個まで並べた JSON です。動作の依頼でない文、否定された依頼（「笑わないでね」）、このロボットにない機器への依頼（「寝室のライトをつけて」「エアコンを25度に」）、このロボットにはできない依頼（「右に曲がってください」）には `[]`（何もしない）を返します。

| 動作 | 引数 |
|---|---|
| `look`（正面を基準に首を向ける） | `direction`: left / right / up / down / up_left / up_right / down_left / down_right / center。`amount`（slight / normal / large）か `degrees`（1〜180）のどちらか |
| `turn`（今の向きから首を動かす） | `look` と同じ（center はなし）。「もう少し右」のように今の向きを基準にする言い方 |
| `nod` / `shake`（うなずく / 首を横に振る） | `count`: 1〜5 |
| `bow`（お辞儀） | なし |
| `set_expression`（表情） | `expression`: happy / sad / surprised / neutral / angry / sleepy / doubt |
| `set_led`（台座の LED の色） | `color`: red / orange / yellow / green / light_blue / blue / purple / pink / white / off |
| `set_volume` / `set_brightness`（音量 / 画面の明るさ） | `level`: 0〜100 |
| `adjust_volume` / `adjust_brightness`（上げる / 下げる） | `direction`: up / down。`amount`（slight / normal / large）か `by`（1〜100）のどちらか |

- **必ず正しい形の JSON を出します。** 生成の各 step で schema に合う token だけを選びます（文法による制約）。
- **自信がないときは動きません。** 生成した token の確率の最小値が閾値（0.83673）より低いと、`[]` にします。これを確信度の gate（confidence gate）と呼びます。
- **小さい:** 実機に書き込む `.jtlm` ファイル（INT4 の重みと tokenizer）は 2.0MB（1,970,720 B）で、重みだけなら 1.68MB です。実機での応答は1文あたり中央値 1.07 秒です。
- **今の版はデータ v1.1 です。** 色を言わずに LED を点ける依頼（「ライトをつけて」「LEDを点灯して」など）を白で点けるようにしました。データ v1.0 のモデルは、これを何もしないか、消灯と読んでいました。
- 前の版（Action schema v0。`look`、`set_expression`、`nod` の3つだけ）の結果と文書は、Git の履歴と [`results/v051_action/`](results/v051_action/) に残っています。

## 結果

実機と同じ INT4、文法による制約、gate での値です（gate の閾値は seed ごとに validation で選ぶ。seed 1 は 0.83673）。学習の seed を変えて5回学習した平均 ± 標準偏差です（採用したのは seed 1。seed は5つの評価の結果を見比べて選んだので、seed 1 の値は少し楽観的です）。

| 評価 | 件数 | 結果 |
|---|---:|---|
| 利用者が普段スタックチャンに使う4文（「LEDライトの色を青にして」など） | 4 | **4 / 4**（5 seed とも） |
| スタックチャンで使われている言い方（公開されている例と言い換え。完全一致） | 140 | **93.1 ± 0.8%**（seed 1 は 92.9%） |
| 同じセットの紛らわしい `[]`（部屋の照明、エアコンの温度など）で誤って動いた件数 | 65 | **0**（5 seed とも） |
| 人が書いた依頼文（公開コーパスから選んだ文） | 65 | **91.7 ± 1.8%**（seed 1 は 93.8%） |
| 人が書いた、動作の依頼でない文で誤って動いた割合 | 1,092 | **0.1 ± 0.2%** |
| LLM が書いた評価セット eval v3（完全一致） | 1,816 | **95.2 ± 0.5%** |
| LED の点灯、色、消灯（LLM が書いた LED v1.1。完全一致） | 437 | **90.7 ± 0.9%**（データ v1.0 は 41.6%） |
| できない依頼で誤って動いた割合 | 285 | 0.6 ± 0.4% |
| 実機（ESP32-S3）と PC（PyTorch）の出力の一致 | 400 | 400 / 400（動きの計画も 400 / 400） |

- 弱いところ: `turn`（今の向きからの移動）は `look` より弱く（eval v3 の1動作の文で 85.3% と 97.3%）、角度や数値のある文は gate で止まりやすいです（スタックチャンの言い方のセットで、数値のある文の 10.9 ± 7.6%）。「首を振って」はうなずきと首振りのどちらにも読めます。LED は、ひらがなの色（「あかにして」）や「けして」が弱めです。英語には対応していません（英語の依頼の正解は約4%）。表記の揺れ（ひらがなだけ、カタカナ、打ち間違い、方言）は 83.7%、言い直しは 83.6% で、やや苦手です（5 seed の平均の完全一致）。
- データ v1.0（seed 0。seed は評価の前に決めていました）の 5 seed の平均は、スタックチャンの言い方 94.4 ± 0.9%、人が書いた依頼 91.7 ± 2.1%、eval v3 95.3 ± 0.5% でした。
- 評価セットごとの結果、誤差の範囲、版ごとの改善は [`docs/evaluation.md`](docs/evaluation.md) にあります。表の数値は [`results/v11_action/seeds_3m.md`](results/v11_action/seeds_3m.md)、実機の計測は [`results/v11_action/device/`](results/v11_action/device/) にあります。

## すぐに試す

**ブラウザで試す:** [デモ（Hugging Face Space）](https://huggingface.co/spaces/ayousanz/JapaneseTinyAgentLM-Action-3M-demo)。インストール不要で、実機と同じ C の runtime（WebAssembly）と INT4 の重みがブラウザの中で動きます。

デモでは、実行した入力文と推論結果をモデルの品質評価・改善のため非公開の R2 に毎回保存します。保存に失敗したときは結果を表示しません。保存期間は90日です。個人情報を入力しないでください。実装と運用手順は [`runtime/feedback-worker/`](runtime/feedback-worker/README.md) を参照してください。

### Python（PC）

GPU は要りません。

```bash
pip install torch numpy sentencepiece safetensors huggingface_hub
hf download ayousanz/JapaneseTinyAgentLM-Action-3M --local-dir JapaneseTinyAgentLM-Action-3M
python JapaneseTinyAgentLM-Action-3M/inference.py 右を向いて 笑わないでね
```

```text
{"input": "右を向いて", "actions": [{"name": "look", "arguments": {"direction": "right", "amount": "normal"}}], "confidence": ..., ...}
{"input": "笑わないでね", "actions": [], "confidence": 1.0, ...}
```

Python から使う方法は [モデルカード](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M) を見てください。

### スタックチャン（K151）

ビルド済みの firmware とモデルを1つにしたイメージを書き込みます。**今入っている firmware は消えます。**

```bash
pip install esptool pyserial huggingface_hub
hf download ayousanz/JapaneseTinyAgentLM-Action-3M --local-dir JapaneseTinyAgentLM-Action-3M
esptool --chip esp32s3 -p <PORT> -b 921600 write-flash 0x0 JapaneseTinyAgentLM-Action-3M/firmware/stackchan_k151_jtalm_action.bin
python JapaneseTinyAgentLM-Action-3M/firmware/stackchan_chat.py <PORT>           # 首は動かない
python JapaneseTinyAgentLM-Action-3M/firmware/stackchan_chat.py <PORT> --servo   # 首も動く
```

`<PORT>` は Windows なら `COM3` など、Linux なら `/dev/ttyACM0` です。バックアップの取り方と注意は [`firmware/README.md`](firmware/README.md) にあります。

### source から build する

- firmware: [`firmware/README.md`](firmware/README.md)（ESP-IDF v5.5.5）
- C の runtime（PC 用、PyTorch と同じ出力。ESP-IDF の component としても使える）: [`runtime/host/README.md`](runtime/host/README.md)
- ブラウザで動かす（同じ C の runtime の WebAssembly 版）: [`runtime/web/README.md`](runtime/web/README.md)
- データ生成と学習の再現: [`docs/training.md`](docs/training.md)

## 対応ハードウェアと安全

| 項目 | 内容 |
|---|---|
| 対象 | スタックチャン K151（CoreS3 = ESP32-S3、Flash 16MB、PSRAM 8MB、servo は Feetech SCS0009 ×2） |
| 使うもの | CPU の2コア、Flash（重みを直接読む）、PSRAM、画面、touch、servo、台座の RGB LED、speaker（音量の確認音）、NVS（音量、明るさ、LED の色を保存）。Wi-Fi と NPU は使わない |
| 入力 | USB serial で送る日本語のテキスト（音声認識はこのリポジトリの範囲外） |

- 起動したときは servo が off で、首は動きません。`!servo on`（または `stackchan_chat.py --servo`）で動きます。
- **画面に触れる、`!stop` を送る、のどちらかですぐに止まり、servo の電源が切れます。** 角度は firmware が制限します（左右 ±45°、上下 0〜+85°。下は頭が床に当たるので水平まで）。
- 首が動くときは、指やケーブルを近づけないでください。

詳しくは [`docs/hardware.md`](docs/hardware.md) を見てください。

## リポジトリの構成

| Directory | 内容 |
|---|---|
| [`src/jtalm/`](src/jtalm) | Python: データ生成（`data`）、学習・量子化・書き出し（`model`）、評価（`eval`）、Action の schema と servo への変換（`action`）、GPU を借りて実行する runner（`infra`、任意） |
| [`runtime/host/`](runtime/host) | C の推論 runtime（PC 用。firmware と同じコードで、ESP-IDF の component としても使える） |
| [`runtime/web/`](runtime/web) | 同じ C の runtime を WebAssembly にした、ブラウザ用のデモ |
| [`firmware/`](firmware) | ESP32-S3 の firmware（`jtalm_action`）と、実機用のツール |
| [`configs/`](configs) | データ生成の設定 |
| [`datasets/manifests/`](datasets/manifests) | 各データの出典、件数、hash（データ本体は git に入れない） |
| [`results/`](results) | 評価と学習の結果（[`results/README.md`](results/README.md)） |
| [`tests/`](tests) | テスト |
| [`docs/`](docs) | ドキュメント |

## ドキュメント

| 文書 | 内容 |
|---|---|
| [`docs/overview.md`](docs/overview.md) | 目的、設計の目標、範囲 |
| [`docs/architecture.md`](docs/architecture.md) | モデル、tokenizer、Action の schema、文法による制約と gate、`.jtlm`、実機でのメモリ配置 |
| [`docs/data.md`](docs/data.md) | 学習・評価データの作り方と出典 |
| [`docs/training.md`](docs/training.md) | 再現の手順（データ生成、学習、量子化、評価、公開） |
| [`docs/evaluation.md`](docs/evaluation.md) | 評価の方法と結果 |
| [`docs/hardware.md`](docs/hardware.md) | 実機、servo、dispatcher、性能 |
| [`docs/prior_art.md`](docs/prior_art.md) | 関連研究と先行例 |
| [`docs/roadmap.md`](docs/roadmap.md) | 現状と今後の予定 |

## 開発

```bash
uv sync --group train
uv run --group train pytest -q
uv run ruff check src tests firmware/tools
```

Issue と Pull Request を歓迎します。[`CONTRIBUTING.md`](CONTRIBUTING.md) を見てください。

## データとライセンス

| 対象 | ライセンス |
|---|---|
| コード（このリポジトリ） | [Apache-2.0](LICENSE)（[`NOTICE`](NOTICE)） |
| モデルの重み（[Hugging Face](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M)） | CC BY-SA 4.0 |
| 合成データセット（[Hugging Face](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth)） | CC BY-SA 4.0 |
| firmware の binary に含まれる第三者のコード | 各ライセンス（[`firmware/jtalm_action/licenses/`](firmware/jtalm_action/licenses/README.md)） |

- 学習データの文章は、ライセンス上問題のないオープンなモデル（Apache-2.0 / MIT）が書き、別のモデルが確かめたものと、人が書いた公開コーパス（Tatoeba、JESC、MASSIVE）です。利用規約で出力の利用が制限されるサービスの出力は使っていません。詳しくは [`docs/data.md`](docs/data.md)。
- 実装、データの生成と検査、学習、評価は、Claude Code（Anthropic）を使って行いました。

## ロードマップ

- **Action LM**: 完成（このリポジトリと Hugging Face で公開）。
- **Chat LM**（約1,000万パラメータ、短い日本語の会話）: 次に取り組みます。
- そのほかの課題（消費電力の計測、人が書いた評価用の依頼文を増やすことなど）は [`docs/roadmap.md`](docs/roadmap.md) にあります。

## 先行例との関係

マイコンで動く言語モデル、マイコンで動く tool calling のモデル（英語と欧州の言語）、外付けの NPU で動くスタックチャンの function calling には先行例があります。日本語の発話からロボットの動作呼び出し（JSON）を決める言語モデルを、ESP32-S3 単体（NPU・外部モジュール・ネットワークなし）で動かした公開事例は、2026年10月1日時点の私たちの調査では見つかりませんでした。詳しくは [`docs/prior_art.md`](docs/prior_art.md)。

## 引用

[`CITATION.cff`](CITATION.cff) を使ってください（GitHub の「Cite this repository」からも取得できます）。
