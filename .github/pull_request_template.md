## 変更の内容 / What

## 理由 / Why

## 確認 / Checklist

- [ ] `uv run --group train pytest -q` と `uv run ruff check` / `ruff format --check` が通る
- [ ] 新しいソースファイルに SPDX ヘッダーを付けた
- [ ] 学習・評価データを変えた場合、出典とライセンスが [`CONTRIBUTING.md`](../CONTRIBUTING.md) のルールに合う
- [ ] servo を動かすコードを変えた場合、可動域の制限、touch での停止、起動時の dry-run を保った
