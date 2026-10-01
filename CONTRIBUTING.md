# Contributing / 貢献のしかた

Issue と Pull Request を歓迎します。不具合の報告、評価で見つけた誤り、ほかのロボットへの移植、ドキュメントの改善など、どれも助かります。
Issues and pull requests are welcome, in Japanese or English.

## Issue

- 不具合: 再現の手順、入力した文、期待した出力と実際の出力、環境（OS、Python、実機の場合は機種と firmware）を書いてください。
- モデルの誤り: 入力文と出力をそのまま貼ってください。評価セットに足すべき言い回しの提案も歓迎します。
- セキュリティの問題は Issue に書かず、[`SECURITY.md`](SECURITY.md) の方法で連絡してください。

## 開発環境

Python 3.13 と [uv](https://docs.astral.sh/uv/) を使います。

```bash
uv sync --group train          # PyTorch などの学習用の依存も入れる
uv run --group train pytest -q # テスト
uv run ruff check src tests firmware/tools
uv run ruff format src tests firmware/tools
```

- 依存を追加するときは `uv add`（開発用は `uv add --dev`、学習用は `uv add --group train`）を使い、`uv.lock` も commit してください。
- C の runtime は `runtime/host/`（`make`）、firmware は `firmware/`（ESP-IDF v5.5.5）です。手順はそれぞれの README にあります。
- 学習とデータ生成の再現は [`docs/training.md`](docs/training.md) を見てください。GPU を借りる runner（`jtalm.infra.job`）は任意で、使わなくても開発できます。

## Pull Request

- 1つの PR では1つの変更にしてください。テストを追加・更新し、`pytest` と `ruff` が通ることを確かめてください（CI でも確かめます）。
- 新しいソースファイルには、ほかのファイルと同じ SPDX ヘッダーを付けてください。
- 送っていただいたコードは、このリポジトリのライセンス（Apache-2.0）で公開されます。

## 学習データと評価データのルール

モデルの重みとデータセットは CC BY-SA 4.0 で公開しています。それと両立させるため、次を守ってください。

- 学習・評価データの文章と正解は、ライセンス上問題のないオープンなモデル（Apache-2.0 / MIT など）、人が書いた公開コーパス（ライセンスが両立するもの）、またはプログラムで作ります。利用規約で出力の利用が制限されるサービス（ChatGPT、Claude など）の出力は使いません。
- 評価セットの文を学習データに入れないでください（`jtalm.data.build` の除外を通してください）。
- 出典とライセンスは manifest（`datasets/manifests/`）に記録します。詳しくは [`docs/data.md`](docs/data.md)。

## 実機（servo）を扱う変更

- servo を動かすコードを変えるときは、可動域の制限（firmware の soft limit）と、画面に触れると止まる動作を保ってください。
- 起動時に servo が off（dry-run）である既定は変えないでください。

## 行動規範

参加するすべての人に [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) を守っていただきます。
