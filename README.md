# JapaneseTinyAgentLM

[![CI](https://github.com/ayutaz/JapaneseTinyAgentLM/actions/workflows/ci.yml/badge.svg)](https://github.com/ayutaz/JapaneseTinyAgentLM/actions/workflows/ci.yml)
[![Code: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue.svg)](LICENSE)
[![Model: CC BY-SA 4.0](https://img.shields.io/badge/model-CC%20BY--SA%204.0-lightgrey.svg)](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M)
[![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97-Action--3M-yellow.svg)](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M)

[English](README.en.md)

マイコン（ESP32-S3）の上だけで動く、日本語の超小型言語モデルです。最初のモデル **Action LM**（315万パラメータ）は、日本語の短い依頼を、ロボットの動作の呼び出し（JSON）に変えます。M5Stack のスタックチャン（K151、CoreS3）の本体だけで、NPU もネットワークも使わずに、首を動かし、表情を変えます。

```text
入力: 左を見て、真ん中に戻ってきて。
出力: [{"name":"look","arguments":{"direction":"left","amount":"normal"}},
       {"name":"look","arguments":{"direction":"center","amount":"normal"}}]
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

出力は、次の3種類の動作を最大2個まで並べた JSON です。動作の依頼でない文、否定された依頼（「笑わないでね」）、このロボットにはできない依頼（「右に曲がってください」）には `[]`（何もしない）を返します。

| 動作 | 引数 |
|---|---|
| `look`（首を向ける） | `direction`: left / right / up / down / center、`amount`: slight / normal / large |
| `set_expression`（表情） | `expression`: happy / sad / surprised / neutral |
| `nod`（うなずく） | `count`: 1〜3 |

- **必ず正しい形の JSON を出します。** 生成の各 step で schema に合う token だけを選びます（文法による制約）。
- **自信がないときは動きません。** 生成した token の確率の最小値が閾値（0.868）より低いと、`[]` にします。これを確信度の gate（confidence gate）と呼びます。
- **小さい:** 実機に書き込む `.jtlm` ファイル（INT4 の重みと tokenizer）は 2.0MB（1,971,456 B）で、重みだけなら 1.68MB です。実機での応答は1文あたり中央値 1.3 秒です。

## 結果

実機と同じ INT4、文法による制約、gate 0.868 での値です。学習の seed を変えて5回学習した平均 ± 標準偏差です（公開したのは seed 0）。

| 評価 | 件数 | 結果 |
|---|---:|---|
| 人が書いた依頼文（公開コーパスから選んだ文） | 62 | **85.2 ± 6.4%**（seed 0 は 91.9%） |
| 人が書いた、動作の依頼でない文で誤って動いた割合 | 1,097 | **0.0 ± 0.0%** |
| LLM が書いた評価セット（完全一致） | 1,189 | **94.0 ± 0.6%** |
| できない依頼で誤って動いた割合 | 286 | 0.3 ± 0.3% |
| 実機（ESP32-S3）と PC（PyTorch）の出力の一致 | 300 | 300 / 300 |

- 英語には対応していません（英語の依頼の正解は約5%）。表記の揺れ（ひらがなだけ、カタカナ、打ち間違い、方言）の文は 83.3%、言い直しの文は 85.5% で、やや苦手です（どちらも 5 seed の平均の完全一致）。
- 評価セットごとの結果、誤差の範囲、版ごとの改善は [`docs/evaluation.md`](docs/evaluation.md) にあります。実機の計測は [`results/v051_action/device/`](results/v051_action/device/README.md) にあります。

## すぐに試す

### Python（PC）

GPU は要りません。

```bash
pip install torch numpy sentencepiece safetensors huggingface_hub
hf download ayousanz/JapaneseTinyAgentLM-Action-3M --local-dir JapaneseTinyAgentLM-Action-3M
python JapaneseTinyAgentLM-Action-3M/inference.py 右を向いて 笑わないでね
```

```text
{"input": "右を向いて", "actions": [{"name": "look", "arguments": {"direction": "right", "amount": "normal"}}], "confidence": 0.9989, ...}
{"input": "笑わないでね", "actions": [], "confidence": 0.9999, ...}
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
- C の runtime（PC 用、PyTorch と同じ出力）: [`runtime/host/README.md`](runtime/host/README.md)
- データ生成と学習の再現: [`docs/training.md`](docs/training.md)

## 対応ハードウェアと安全

| 項目 | 内容 |
|---|---|
| 対象 | スタックチャン K151（CoreS3 = ESP32-S3、Flash 16MB、PSRAM 8MB、servo は Feetech SCS0009 ×2） |
| 使うもの | CPU の2コア、Flash（重みを直接読む）、PSRAM、画面、touch、servo。Wi-Fi と NPU は使わない |
| 入力 | USB serial で送る日本語のテキスト（音声認識はこのリポジトリの範囲外） |

- 起動したときは servo が off で、首は動きません。`!servo on`（または `stackchan_chat.py --servo`）で動きます。
- **画面に触れる、`!stop` を送る、のどちらかですぐに止まり、servo の電源が切れます。** 角度は firmware が制限します（左右 ±30°、上下 −10〜+15°）。
- 首が動くときは、指やケーブルを近づけないでください。

詳しくは [`docs/hardware.md`](docs/hardware.md) を見てください。

## リポジトリの構成

| Directory | 内容 |
|---|---|
| [`src/jtalm/`](src/jtalm) | Python: データ生成（`data`）、学習・量子化・書き出し（`model`）、評価（`eval`）、Action の schema と servo への変換（`action`）、GPU を借りて実行する runner（`infra`、任意） |
| [`runtime/host/`](runtime/host) | C の推論 runtime（PC 用。firmware と同じコード） |
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
