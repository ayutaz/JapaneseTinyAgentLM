# Host C reference runtime

Action LM の推論を、外部ライブラリに依存しない C11 で実装したものです。PC 上で PyTorch / Python の実装と出力が一致することを確かめる基準（reference）です。実機（ESP32-S3）の firmware [`firmware/jtalm_action/`](../../firmware/jtalm_action/) も、同じ `model.c` / `tokenizer.c` / `grammar.c` を copy せずにそのまま build します（[`../../firmware/README.md`](../../firmware/README.md)）。

- `python -m jtalm.model.export` が書き出した `.jtlm` ファイル（モデルと tokenizer を1つにまとめたもの）を読みます。
- UTF-8 の入力を SentencePiece と同じ手順で token に分けます（`nmt_nfkc` の正規化、unigram の Viterbi、byte fallback）。
- KV cache を使って greedy に生成します。`--grammar` を付けると、Action schema v0 の grammar（`jtalm.model.grammar` の移植）で生成を制約します。
- 重みは FP32、INT8、INT4（どちらも weight-only、64 個ごとに fp16 の scale を1つ）に対応します。

## ファイル

| ファイル | 内容 |
|---|---|
| `jtalm.h` | 公開 API（読み込み、forward、tokenizer、grammar、生成） |
| `model.c` | `.jtlm` の読み込み、Transformer の forward（KV cache）、greedy 生成 |
| `tokenizer.c` | 正規化（precompiled charsmap の Darts double array を直接引く）、unigram の Viterbi、decode |
| `grammar.c` | Action schema v0 の状態機械 |
| `main.c` | コマンドラインの入口 |
| `Makefile` | `make` で `build/jtalm` を作る |

## Build

C11 のコンパイラがあれば build できます。Linux / macOS では、リポジトリのルートで `make -C runtime/host` を実行すると `runtime/host/build/jtalm` ができます。`-ffp-contract=off` は必須です（f32 の乗算と加算を、PyTorch と同じく別々に丸めるため。`Makefile` で付けています）。

ネイティブの C コンパイラがない環境（Windows など）では、ESP-IDF の Docker image に入っている host 向けの gcc 13.3 を使えます（実機向けの firmware は、同じ image の Xtensa 用の cross compiler gcc 14.2 で build します）。

```sh
# リポジトリのルートで。Windows の Git Bash では先頭に MSYS_NO_PATHCONV=1 を付け、$PWD を $(pwd -W) にする
docker run --rm -v "$PWD:/w" -w /w --entrypoint make espressif/idf:v5.5.5 -C runtime/host
```

内積の累積は既定で `double` です（PyTorch との差を小さくするため）。単精度の FPU しかない ESP32-S3 では `-DJTLM_ACC=float` で build します。

## モデルの入手

採用モデルは、データ v0.5.1 で学習した 3M の INT4（group 64）です。`.jtlm` は Hugging Face のモデルの repository から取得できます（1,971,456 B）。

```sh
hf download ayousanz/JapaneseTinyAgentLM-Action-3M jtalm_action_3m_q4_g64.jtlm --local-dir models
```

自分で学習した checkpoint からは、次のコマンドで書き出します（学習の手順は [`../../docs/training.md`](../../docs/training.md)）。

```sh
uv run --group train python -m jtalm.model.export \
    --ckpt <best.pt> --tokenizer <tokenizer.model> --bits 0 8 4 --out <出力先>
```

`--out` の下に、checkpoint の親 directory の名前（例: `3m`）を付けた `3m_fp32.jtlm`（12.9MB）、`3m_q8_g64.jtlm`（3.5MB）、`3m_q4_g64.jtlm`（2.0MB）ができます。どれも tokenizer（約 0.27MB。うち正規化の表が 0.24MB）を含みます。

## 実行

日本語の入力は、UTF-8 のファイルか標準入力で渡します（コマンドライン引数では渡しません。Windows の console の code page に左右されないようにするためです）。1行に1件です。先頭の BOM と、行末の CR / LF は取り除きます。

```sh
printf '左を見て\nうなずいてから笑って\n今日はいい天気だね\n' > models/prompts.txt
runtime/host/build/jtalm -m models/jtalm_action_3m_q4_g64.jtlm -i models/prompts.txt --grammar
# Docker の gcc で build した場合
docker run --rm -v "$PWD:/w" -w /w --entrypoint runtime/host/build/jtalm espressif/idf:v5.5.5 \
    -m models/jtalm_action_3m_q4_g64.jtlm -i models/prompts.txt --grammar
```

出力は1件につき1行の JSON です（例は初期のチェックポイントのものです）。

```json
{"output":"[{\"name\":\"look\",\"arguments\":{\"direction\":\"left\",\"amount\":\"normal\"}}]","min_prob":0.999994159,"tokens":8,"ids":[7,10,16,11,22,14,8,2]}
```

| 項目 | 内容 |
|---|---|
| `output` | 生成した文字列（`</s>` の手前まで）。Python の `Prediction.text` と同じ |
| `min_prob` | 選んだ token の確率の最小値。`--grammar` のときも、制約をかける前の確率を使う（`jtalm.model.decode` と同じ）。confidence gate に使う |
| `tokens` | 生成した token 数（`</s>` を含む） |
| `ids` | 生成した token id |

この runtime は confidence gate をかけません。採用モデルと同じ判定にするには、`min_prob` が 0.868 未満の出力を `[]` として扱ってください（firmware と `jtalm.model.evaluate` の `gate` と同じ比較）。

処理した件数と速度（tok/s）は標準エラーに出します。

| オプション | 内容 |
|---|---|
| `-m FILE` | `.jtlm` ファイル（必須） |
| `-i FILE` | 入力ファイル。省略するか `-` のときは標準入力 |
| `--grammar` | Action schema v0 の grammar で生成を制約する |
| `--tokenize` | 生成せず、各行の token id（`sp.encode` と同じ）を JSON の配列で出す |
| `--decode` | 各行の空白区切りの token id を文字列に戻す（`sp.decode` と同じ） |
| `--first-logits` | 最初の生成 step の logits を `logits0` として出力に加える（golden vector の比較用） |

## 設計

### ファイル形式（`.jtlm`）

little-endian の1ファイルです。header（128 byte）、tokenizer、RoPE の cos / sin の表、重みの順に並び、各区画と各 tensor は 32 byte 境界に揃えます。詳細は `src/jtalm/model/export.py` の docstring にあります。

- **重み:** 順番は固定です（embedding、層ごとに attn_norm、wq、wk、wv、wo、mlp_norm、w1、w3、w2、最後に norm）。embedding は1回だけ格納し、入力の埋め込みと出力 head の両方に使います（weight tying）。
- **量子化:** 行ごとに 64 個ずつの group で、対称の round-to-nearest です。整数の値は `jtalm.model.quantize.quantize_tensor` と完全に同じです（`torch.round` なので、ちょうど 0.5 のときは偶数に丸める）。scale だけを fp16 にして保存します。復元した重み（整数 × fp16 の scale）は f32 で誤差なく表せるので、C と Python で同じ値になります。INT4 は1 byte に2個を詰めます（偶数番目が下位 4 bit、2の補数）。RMSNorm の重みは f32 のままです。
- **RoPE:** PyTorch が計算した f32 の表をそのまま格納します。C 側で `pow` / `cos` / `sin` を計算すると、最後の bit がずれることがあるためです（3M で 16KB）。

### Tokenizer

SentencePiece 0.2 の処理を、そのまま C に移しました。

1. **正規化:** model の `normalizer_spec` にある precompiled charsmap（`nmt_nfkc`）を、そのまま `.jtlm` に入れます。中身は Darts-clone の double array（trie）と、正規化後の文字列を NUL で区切って並べたものです。入力の先頭から、最も長く一致する規則を trie で引いて置き換えます。一致しなければ UTF-8 の1文字をそのまま使い、不正な byte は U+FFFD にします。
2. **user-defined symbol**（出力の JSON の断片と enum の値）は、正規化より先に、最も長く一致するものを1つの単位としてそのまま通します。
3. **空白:** 先頭と末尾の空白を取り除き、連続する空白を1つにまとめ（`remove_extra_whitespaces`）、空白を U+2581 に置き換えます。先頭の `▁` は付けません（`add_dummy_prefix=false`）。
4. **分割:** unigram の Viterbi です（`EncodeOptimized` と同じ手順。user-defined symbol には `長さ × max_score − 0.1` の点を与え、未知の文字には `min_score − 10` を与える。点の比較も C++ と同じく double で行う）。語彙の trie の代わりに、piece を先頭の byte ごとに分けた表を引きます。
5. **byte fallback:** 未知の文字は、UTF-8 の各 byte を `<0xXX>` の token にします。

decode（id → 文字列）も SentencePiece と同じ規則です（制御用の token は空文字、`<unk>` は ` ⁇ `、byte の token は UTF-8 の1文字ごとにまとめ、不正な byte は U+FFFD、先頭の `▁` を1つ取り除く）。

### 数値計算

`jtalm.model.transformer` と同じ順序で、同じところで f32 に丸めます（RMSNorm は `(x × rsqrt(mean(x²) + eps)) × weight`、SiLU は `x / (1 + exp(−x))`、softmax は最大値を引いて exp、和の逆数を掛ける）。違うのは内積の和を取る順序だけです。PyTorch（MKL）は f32 のまま区切って足しますが、C は既定で double の4本の部分和で足します。そのため logits には 1e-5 程度の差が出ます。

### メモリ（ESP32 への移植を想定）

- モデルの構造体は、読み込んだファイルの中を指すだけで、何も複製しません。ESP32 では flash を mmap した領域をそのまま渡せます（4 byte 境界に揃っていること）。
- 書き換える状態は、`jtlm_state_bytes()` の大きさの arena 1つにまとめます。KV cache は `max_seq_len` の分を最初に確保します。token ごとの malloc はありません。
- `jtlm_state_init_split()` を使うと、KV cache（`jtlm_state_kv_bytes()`）と残りの小さな buffer を別々の領域に置けます。ESP32 では、KV cache を PSRAM に、よく使う activation を内部 SRAM に置きます。KV cache は、読む前に必ずその位置を書くので、初期化しません。
- 大きさ（`JTLM_BATCH` = 16 のとき）:

| model | KV cache | 残り（activation × 16 token、attention の score、logits） | 合計 |
|---|---:|---:|---:|
| 3M（d192 × 7層、KV head 2） | 458,752 B | 125,952 B | 584,704 B |
| 5M（d256 × 6層、KV head 2） | 393,216 B | 176,128 B | 569,344 B |

- KV cache は `層数 × 128 × 2 × kv_heads × head_dim × 4 byte` です。残りの大部分は、prompt をまとめて処理するための activation（`JTLM_BATCH × (3 × d_model + d_model + 2 × d_ff) × 4 byte`）です。`-DJTLM_BATCH=8` などで小さくできます（結果は変わりません）。
- tokenizer の作業領域は呼び出し側が渡します（正規化後の byte 数 + 1 byte あたり 16 byte）。

### Prefill のまとめ処理と並列化

実機では、重みを flash から読む速さ（約 31 MB/s）と、1 core の演算の速さの両方が律速になります。どちらも、**計算の値を1 bit も変えずに**速くしています。

- **Prefill のまとめ処理:** `jtlm_prefill()` は、prompt を最大 `JTLM_BATCH` token ずつまとめて処理します。重みの各行を1回読み（量子化なら1回 f32 に戻し）、まとめた全 token に掛けます。token ごとの内積の足し方は1 token ずつ処理する場合と同じなので、結果は変わりません。Prompt の途中の token では、出力 head（語彙 × d_model）の計算を省きます（最後の token の logits しか使わないため）。
- **並列化の hook:** `jtlm_set_parallel()` に関数を渡すと、行列積の出力の行を、その関数が分割して実行します（firmware では2つの core に半分ずつ）。行ごとの計算は分割の仕方によらないので、結果は変わりません。既定（`NULL`）では1 thread で実行します。
- **内積の kernel:** 部分和を local 変数に持つ（`acc[]` が入力と alias しうるので、配列のままだと毎回 memory に書き戻される）。量子化した重みは、1個ずつ f32 に戻してすぐ掛けます（行を一度 buffer に戻してから掛けるのと同じ値）。
- `jtlm_prefill()` と `jtlm_generate_from()` は `jtlm_generate()` を2つに分けたもので、呼び出し側が prefill と decode の時間を別々に測れます。

これらの変更の前後で、評価セットの先頭 200件の出力（`--grammar`、6つの model、`double` と `float` の累積、`JTLM_BATCH` = 16 と 3）は byte 単位で同じでした。

## Python との一致の確認

```sh
uv run --group train python -m jtalm.model.parity \
    --ckpt <best.pt> --tokenizer <tokenizer.model> \
    --out <出力先> --docker espressif/idf:v5.5.5 --build
```

Checkpoint は自分で学習したもの（[`../../docs/training.md`](../../docs/training.md)）を使います。`--out` の下に `parity.json`（すべての数値と、一致しなかった例）と `golden.jsonl`（評価セットの先頭 32 件の prompt の id、生成した id、最初の step の上位 5 個の logits。実機への移植で比べる golden vector）を書きます。ネイティブのコンパイラがある環境では `--docker` の代わりに `--jtalm runtime/host/build/jtalm` を使います。

### 結果

同じ構造の初期のチェックポイント（データ v0 で学習した 3M と 5M）と、LLM が書いた評価セット（v0 eval）1,189件で確かめました。下の完全一致の率は、この初期のチェックポイントの値です（採用モデルの精度は [`../../docs/evaluation.md`](../../docs/evaluation.md)）。

**Tokenizer:** `sentencepiece` 0.2.2 と token id が完全に一致しました。

| 対象 | 一致 |
|---|---:|
| 学習データの入力文 | 9,067 / 9,067 |
| validation | 477 / 477 |
| 評価セット | 1,189 / 1,189 |
| ランダムな文字列（全角・半角、合成用の濁点、`①` や `㍻` などの NFKC 展開、空白、絵文字、user-defined symbol） | 20,000 / 20,000 |
| decode（ランダムな id 列。制御用、`<unk>`、byte、`▁` を多く含む） | 20,000 / 20,000 |

**生成:** どの条件でも、生成した token 列と出力の文字列が Python（`jtalm.model.decode.greedy`）と1件残らず一致しました。したがって `jtalm.eval` の完全一致も同じです。

| model | 重み | ファイル | grammar なし | grammar あり | 最初の step の logits の差（最大） | min_prob の差（最大） |
|---|---|---:|---:|---:|---:|---:|
| 3M | FP32 | 12.9MB | 84.36% | 84.44% | 2.0e-5 | 7.9e-6 |
| 3M | INT8 | 3.5MB | 84.52% | 84.61% | 1.1e-5 | 7.2e-6 |
| 3M | INT4 | 2.0MB | 84.78% | 84.78% | 1.4e-5 | 4.4e-6 |
| 5M | FP32 | 20.5MB | 79.56% | 79.98% | 1.3e-5 | 3.5e-6 |
| 5M | INT8 | 5.5MB | 79.56% | 79.98% | 2.4e-5 | 5.7e-6 |
| 5M | INT4 | 3.0MB | 79.48% | 79.90% | 1.8e-5 | 7.0e-6 |

- 完全一致の率は、C と Python で同じ値です（表の値）。token 列の一致は、どの行も 1,189 / 1,189 です。logits の絶対値は最大で約 19 です。
- INT8 / INT4 の比較相手は、`.jtlm` から読み戻した重み（fp16 の scale）で作った Python のモデルです。`jtalm.model.quantize` の fake quant（f32 の scale）で評価した出力とも、1,189件すべてで一致しました。scale を fp16 にしても結果は変わりません。
- `-DJTLM_ACC=float`（ESP32 向けの設定）で build した場合も、3M の6条件すべてで token 列が 1,189件一致しました（logits の差は最大 3.2e-5）。
- データ v0.4 の 3M（INT4 / INT8、grammar あり）でも、host の C の出力は Python と評価セット全 1,189件で一致し、実機（`firmware/jtalm_action`）の出力も host と全件一致しました。採用モデル（データ v0.5.1 の 3M INT4、gate 0.868）では、実機の出力が評価セットの先頭 300件で PyTorch と一致しています（gate の前も後も 300 / 300。[`../../docs/hardware.md`](../../docs/hardware.md) の「実機の性能」）。

**速度（参考）:** AMD Ryzen 9 5900X の Docker（WSL2）上で1 thread、評価セット全体（prompt と生成を合わせて約 22,500 token）を処理した値です。3M は FP32 で約 1,000 tok/s、INT8 / INT4 で約 380 tok/s。5M は FP32 で約 470 tok/s、INT8 / INT4 で約 230 tok/s。量子化した重みは group ごとに f32 へ戻してから掛けるので、PC では FP32 より遅くなります。

Prefill のまとめ処理と内積の kernel の変更の後は、評価セットの先頭 200件（約 3,500 token）で、3M が FP32 約 900 tok/s、INT8 / INT4 約 570 tok/s、5M が FP32 約 580 tok/s、INT8 / INT4 約 380 tok/s です（`double` の累積。`-DJTLM_ACC=float` ではそれぞれ約 1.5倍）。実機の速度は [`../../docs/hardware.md`](../../docs/hardware.md) の「実機の性能」にあります。
