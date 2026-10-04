# ブラウザで動かす（WebAssembly）

[`../host/`](../host/README.md) の C の runtime（`model.c` / `tokenizer.c` / `grammar.c`）を、Emscripten で WebAssembly にしたものです。推論はブラウザの中だけで行います。デモのページは Hugging Face の Static Space で公開し、入力と結果は [`../feedback-worker/`](../feedback-worker/README.md) を通して非公開 R2 に保存します。保存が成功した場合だけ結果を表示します。

| ファイル | 内容 |
|---|---|
| `web.c` | JavaScript から呼ぶ入口（`web_init`、`web_predict`） |
| `build.sh` | `jtalm.js` を作る（wasm を1つのファイルに埋め込む） |
| `index.html` | デモのページ。モデルの `.jtlm` と `config.json` は Hugging Face のモデルの repo から読む |
| `parity.cjs` | host の C runtime と出力が一致するかを Node.js で確かめる |

- 計算は firmware と同じ `-DJTLM_ACC=float -ffp-contract=off` で、重みも実機と同じ INT4 の `.jtlm` です。
- `web_predict` は gate をかける前の出力と確信度（`min_prob`）を返し、gate はページ側でかけます（閾値はページで変えられます）。

## Build

```sh
sh runtime/web/build.sh   # emcc が PATH にあるとき
# Docker で（Windows の Git Bash では先頭に MSYS_NO_PATHCONV=1 を付け、$PWD を $(pwd -W) にする）
docker run --rm -v "$PWD:/src" -w /src emscripten/emsdk:3.1.62 sh runtime/web/build.sh
```

`runtime/web/jtalm.js`（約 63KB）ができます。ページを手元で開くには、`runtime/web/` で `python -m http.server` を実行して `http://localhost:8000/` を開きます（`file://` では動きません）。

## host との一致の確認

```sh
# host の C runtime を、firmware と同じ float の累積で build して、基準の出力を作る
make -C runtime/host BUILD=build/accf CFLAGS="-O2 -DJTLM_ACC=float"
runtime/host/build/accf/jtalm -m model.jtlm --grammar -i prompts.txt > host.jsonl
node runtime/web/parity.cjs model.jtlm prompts.txt host.jsonl
```

schema v1、データ v1.0 の公開モデル（`jtalm_action_3m_q4_g64.jtlm`）と、v1 の評価セットと validation の 11,426 文（Emscripten 3.1.62、Node.js 22〜24）で、出力も確信度も host の C runtime（`float` の累積）と完全に一致しました（[`results/v1_action/parity/`](../../results/v1_action/parity/README.md)）。データ v1.1 の公開モデル（seed 1）でも、Stack-chan v1 と LED v1.1 の 577 文で、出力も確信度も host の C runtime（`float` の累積）と完全に一致しました（[`results/v11_action/parity/web_vs_host_float.json`](../../results/v11_action/parity/web_vs_host_float.json)。host の C runtime と PyTorch の一致も同じフォルダにあります）。Node.js では1文あたり約 50 ms でした。前の版（schema v0）のモデルでも、評価セットの全 4,794 文で一致していました。

- ページの gate の既定値は、Hugging Face のモデルの `config.json` の `gate_threshold` です（読めないときは 0.83673。データ v1.1 の seed 1 の閾値）。
