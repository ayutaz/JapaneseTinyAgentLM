# 評価結果（results/）

学習・評価・実機計測の結果のうち、文書で引用しているものを置いています。数値の読み方と指標の定義は [docs/evaluation.md](../docs/evaluation.md) を参照してください。

## ファイルの種類

| ファイル | 作るコマンド | 内容 |
|---|---|---|
| `comparison.md` / `comparison.json` | `jtalm.model.evaluate` | v0 eval（1,189件）のカテゴリ別の表と TinyLM-Bench の16件。`conditions` に decoding、確信度の gate（confidence gate）の規則、評価セットと tokenizer の sha256 |
| `suite.md` / `suite.json` | `jtalm.model.eval_suite` | 全評価セット（v0 eval、human v1、eval v2 の12パターン）を INT4 + grammar + gate で評価した表と gate の閾値 |
| `ci_*.md` / `seeds_*.md` / `diff_*.md` | `jtalm.eval.bootstrap` | 95% bootstrap 区間、seed の平均 ± SD、paired bootstrap の差 |
| `<model>/summary.json` / `log.jsonl` | `jtalm.model.train` | 学習の設定、params、最良の epoch、validation の推移 |
| `<model>/*_eval_report.json` / `*_bench_report.json` | `jtalm.model.evaluate` | 評価セットと16件の詳細な report |
| `run.json` | GPU での学習 job（`jtalm.infra.job`） | job の定義（実行したコマンドの列）と実行の記録 |
| `parity.json` / `golden.jsonl` | `jtalm.model.parity` | C runtime と PyTorch の一致の確認と、実機の移植に使う golden vector |
| `*.summary.json`（b4_device、v051_action/device） | `firmware/tools/lm_serial.py` | 実機の応答時間、token あたりの時間、メモリ、host との一致 |

JSON の中の checkpoint のパス（`runs/...`）は、学習を実行した環境のものです。リポジトリには含まれません。

## ディレクトリの一覧

名前の先頭の `m4_`、`m5_`、`m6_`、`b4_` は、開発中の段階の名前です（M4 = データ v0 での最初の学習、M5 = そのモデルでの grammar と量子化、M6 = C runtime と PyTorch の一致、B4 = 最初の実機での実行）。

| ディレクトリ | 内容 | 使っている文書 |
|---|---|---|
| [`m4_action_v0/`](m4_action_v0/) | データ v0 で学習した 3M / 5M（seed 0〜2）/ 20M の比較（gate なし）と、ルールベース | [evaluation.md](../docs/evaluation.md)（モデルサイズ） |
| [`data_scaling_v0/`](data_scaling_v0/) | 3M を v0 のデータの 25 / 50 / 100% で学習した比較 | [evaluation.md](../docs/evaluation.md)（データの量） |
| [`m5_grammar_on_m4/`](m5_grammar_on_m4/) | v0 のモデルで grammar なし / あり / gate ありの比較 | [evaluation.md](../docs/evaluation.md)（grammar、gate） |
| [`m5_quant_on_m4/`](m5_quant_on_m4/) | v0 のモデルの INT8 / INT4（group 64）の比較 | [evaluation.md](../docs/evaluation.md)（量子化） |
| [`m6_parity/`](m6_parity/) | C runtime と PyTorch の一致（3M / 5M × FP32 / INT8 / INT4、tokenizer） | [evaluation.md](../docs/evaluation.md)、[runtime/host/README.md](../runtime/host/README.md) |
| [`b4_device/`](b4_device/) | 実機（CoreS3）での速度、メモリ、host との一致（3M / 5M × FP32 / INT8 / INT4 と、v0.4 の 3M INT4 + gate の全 1,189件） | [hardware.md](../docs/hardware.md)、[evaluation.md](../docs/evaluation.md) |
| [`a1_device/`](a1_device/README.md) | 画面と dispatcher を載せた firmware での実機の速度とメモリ（data v0.4 の 3M INT4、200件） | [hardware.md](../docs/hardware.md) |
| [`v03_action/`](v03_action/) | データ v0.3 で学習した 3M / 5M / 20M の比較 | [evaluation.md](../docs/evaluation.md)（版ごとの改善、モデルサイズ） |
| [`v04_action/`](v04_action/) | データ v0.4 で学習した 3M / 5M / 20M の比較 | [evaluation.md](../docs/evaluation.md)（版ごとの改善、モデルサイズ） |
| [`v04_quant/`](v04_quant/) | v0.4 の 3M の INT8 / INT4 + grammar | [evaluation.md](../docs/evaluation.md)（量子化、TinyLM-Bench） |
| [`v04_gate/`](v04_gate/) | v0.4 の 3M INT4 + grammar + gate（閾値 0.97004） | [evaluation.md](../docs/evaluation.md)（gate、TinyLM-Bench） |
| [`human_v1/`](human_v1/) | v0.4 の 3M INT4 を人が書いた評価セット（1,159件）で評価。ルールベース、grammar、gate の比較 | [evaluation.md](../docs/evaluation.md)（gate） |
| [`suite_v04/`](suite_v04/) | v0.4 の 3M INT4 + grammar + gate を全評価セットで評価 | [evaluation.md](../docs/evaluation.md)（版ごとの改善） |
| [`v05_action/`](v05_action/) | データ v0.5 で学習した 3M（seed 0 / 1）/ 5M の比較と、全評価セットの表 | [evaluation.md](../docs/evaluation.md)（版ごとの改善） |
| [`v051_action/`](v051_action/) | **採用モデル**（データ v0.5.1 の 3M）。seed 0 / 1 の比較、全評価セットの表、bootstrap 区間（`ci_3m.md`）、5 seed の平均（`seeds_3m.md`）、v0.4・v0.5 との差（`diff_*.md`）、実機での実行（[`device/`](v051_action/device/README.md)。300件、出力の一致と応答時間） | [evaluation.md](../docs/evaluation.md)、[hardware.md](../docs/hardware.md)、[roadmap.md](../docs/roadmap.md) |
