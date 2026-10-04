# firmware

M5Stack のスタックチャン（K151。CoreS3 と SCS0009 の servo × 2）で Action LM を動かす firmware です。実機の構成、座標の規約、dispatcher の設計、速度とメモリは [`../docs/hardware.md`](../docs/hardware.md) にあります。

## この firmware がすること

`jtalm_action` は次のことを本体だけで行います。Wi-Fi、NPU、外付けのモジュールは使いません。

1. Flash の `model` partition（`0x200000`）にある `.jtlm`（モデルと tokenizer）を mmap で読む。
2. USB serial から受けた1行の日本語の依頼を、grammar 付きの greedy と確信度の gate（confidence gate）で Action JSON にする。LM の本体は [`../runtime/host/`](../runtime/host/) の C のコードをそのまま build したもので、PC の PyTorch と同じ出力になる。
3. 出力を Action schema v1 でもう一度検査し、計画を立てて実行する。首（servo）の向き（`look` / `turn`。量か角度、斜めも）、うなずき、首振り、お辞儀は角度に変換して可動域に制限し、画面の顔（M5GFX、7種類）、台座の RGB LED の色、speaker の音量（確認音を鳴らす）、画面の明るさを変える。音量、明るさ、LED の色は NVS に保存し、再起動しても残る。
4. 結果を `JTALM {json}` の1行ずつで serial に返す。

**servo の出力は起動時に off（dry-run）です。** 首が動くのは `!servo on` を送った後だけです。

| Directory / ファイル | 内容 | License |
|---|---|---|
| `jtalm_action/` | Action LM の firmware | Apache-2.0（第三者のコードは下の「第三者のコードとライセンス」） |
| `jtalm_action/licenses/` | 配布する firmware の binary に含まれる第三者のコードのライセンス | 各 upstream |
| `jtalm_eval/` | heap、flash map、PSRAM / flash mmap の帯域を測る最小の firmware | Apache-2.0 |
| `tools/` | 実機と話す、計測する、照合するための Python のスクリプト | Apache-2.0 |
| `baselines/` | 既存の runtime（esp32-llm）と stackchan-idf を CoreS3 で動かすための差分（[`baselines/README.md`](baselines/README.md)） | Apache-2.0 |

## すぐに試す（ビルド済みのイメージ）

Hugging Face の [ayousanz/JapaneseTinyAgentLM-Action-3M](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M) に、firmware とモデルを1つにした書き込み用のイメージ（`firmware/stackchan_k151_jtalm_action.bin`）と、対話用の `firmware/stackchan_chat.py` があります。

> **書き込むと、今入っている firmware（公式のスタックチャンの firmware など）は消えます。** 元に戻したい場合は、先に手順 1 でバックアップを取ってください。

**0. 準備**

```bash
pip install esptool pyserial huggingface_hub
hf download ayousanz/JapaneseTinyAgentLM-Action-3M --local-dir JapaneseTinyAgentLM-Action-3M
```

USB-C で PC につなぎ、port の名前を確かめます。以下の `<PORT>` は自分の port に置き換えてください（例: Windows は `COM3`、Linux は `/dev/ttyACM0`、macOS は `/dev/cu.usbmodem…`）。

**1. バックアップ（任意。16MB、数分かかります）**

```bash
esptool --chip esp32s3 -p <PORT> -b 921600 read-flash 0 0x1000000 backup_k151.bin
# 元に戻すとき: esptool --chip esp32s3 -p <PORT> -b 921600 write-flash 0x0 backup_k151.bin
```

**2. 書き込み**（bootloader、partition table、app、モデルを1つにしたイメージを `0x0` に書きます）

```bash
esptool --chip esp32s3 -p <PORT> -b 921600 write-flash 0x0 \
  JapaneseTinyAgentLM-Action-3M/firmware/stackchan_k151_jtalm_action.bin
```

つながらないときは、本体の横のリセットボタンを緑の LED が点くまで約3秒押し続けて書き込みモードにしてから、やり直してください。書き込んだ後は、リセットボタンを1回押します。

**3. 話しかける**

```bash
python JapaneseTinyAgentLM-Action-3M/firmware/stackchan_chat.py <PORT>
```

```text
準備ができました。依頼を入力してください（終了は Ctrl+C）。
LEDライトの色を青にして
→ LED を青にする  1063 ms
  LED: 青
頭を90度上に向けて
→ 上を向く（正面から90°）  1297 ms
  可動域の端で止めました
```

`stackchan_chat.py` は出力を日本語の説明で表示します（`--verbose` を付けると、Action の JSON と firmware の記録も表示します）。

画面に顔が出て、表情の依頼で顔が変わります。LED の色、音量（確認音が鳴ります）、画面の明るさの依頼もこの段階で効きます。servo は off で、首は動きません（動きの計画だけを作ります）。

**4. 首を動かす**

```bash
python JapaneseTinyAgentLM-Action-3M/firmware/stackchan_chat.py <PORT> --servo
```

servo の電源が入り、首がゆっくり正面に戻ってから、依頼に合わせて首が動きます。

- **首のまわりに指やケーブルを近づけないでください。** 本体は平らな机に置いてください。
- **画面に触れる、Ctrl+C を押す、`!stop` を送る、のどれかで、すぐに止まり servo の電源が切れます。** それでも止まらないときは、電源ボタンを長押しして電源を切ってください（USB を抜いてもバッテリーで動き続けます）。
- 角度は firmware が制限します（左右 ±45°、上下 0〜+85°。下は頭が床に当たるので水平まで）。範囲を超える指示は端で止めます。
- お辞儀は、頭が 20° より下にあるときは、まず 20° まで上げてから床（0°）まで下げ、0.5 秒止めてから元の角度に戻ります。

## ソースから build する

### 必要なもの

- Docker と ESP-IDF v5.5.5 の公式 image（`espressif/idf:v5.5.5`）。PC に ESP-IDF を直接入れる必要はありません。
- esptool 5 系（`pip install esptool`、または `uvx --from esptool esptool`）。
- M5Unified 0.2.17 と M5GFX 0.2.23（MIT）。画面、タッチ、電源の初期化に使います。

### M5Unified と M5GFX の取得

`jtalm_action/CMakeLists.txt` は、`firmware/third_party/stackchan-idf/` の submodule にある M5Unified と M5GFX を、copy せずにそのまま build します。リポジトリの root で次を実行してください（`firmware/third_party/` は Git の管理外です）。

```bash
git clone https://github.com/ciniml/stackchan-idf.git firmware/third_party/stackchan-idf
cd firmware/third_party/stackchan-idf
git checkout 419385ef1b875137140085bd50d34dee331f30c2
git submodule update --init --recursive   # M5Unified 0.2.17、M5GFX 0.2.23 など
bash tools/apply-m5-patches.sh            # stackchan-idf の M5Unified 向けの小さな patch
cd ../../..
```

- 配布しているイメージは、patch（M5Unified の Speaker と RTC の2か所）を当てた checkout で build しました。この firmware は音量の確認音に speaker を使います（RTC は使いません）。patch なしの build は確かめていません。
- 同じ version の別の checkout を使う場合は、`idf.py -DM5UNIFIED_DIR=<path> -DM5GFX_DIR=<path> build` で場所を指定します（M5GFX のディレクトリ名は `m5gfx` にしてください）。

### Build

`jtalm_action` は `runtime/host/` のコードを参照するので、リポジトリの root を container に mount します。

```bash
# Linux / macOS（リポジトリの root で）
docker run --rm -e IDF_COMPONENT_MANAGER=0 -v "$PWD:/w" -w /w/firmware/jtalm_action \
  espressif/idf:v5.5.5 idf.py build

# Windows の Git Bash では、path の変換を止めて Windows 形式の path を渡します
MSYS_NO_PATHCONV=1 docker run --rm -e IDF_COMPONENT_MANAGER=0 -v "$(pwd -W):/w" \
  -w /w/firmware/jtalm_action espressif/idf:v5.5.5 idf.py build
```

`firmware/jtalm_action/build/` に `bootloader/bootloader.bin`、`partition_table/partition-table.bin`、`jtalm_action.bin` ができます。

### モデル（`.jtlm`）の入手

firmware が読むのは `.jtlm` 形式のファイル（モデルと tokenizer を1つにまとめたもの。形式は [`../docs/architecture.md`](../docs/architecture.md)）です。

- **公開モデルを使う:** Hugging Face のモデルのリポジトリにある `jtalm_action_3m_q4_g64.jtlm`（3M、INT4）。Hugging Face のモデルは Action schema v1 のモデル（`.jtlm` は 1,970,720 B）で上書きして公開します。上書きの前の v0 の `.jtlm`（1,971,456 B。Hugging Face の commit 履歴に残ります）は、この firmware では動きません（下の「`.jtlm` と firmware の Action schema の版を合わせてください」）。

  ```bash
  hf download ayousanz/JapaneseTinyAgentLM-Action-3M jtalm_action_3m_q4_g64.jtlm --local-dir .
  ```

- **自分で学習したモデルを使う:** checkpoint から書き出します（学習の手順は [`../docs/training.md`](../docs/training.md)）。`--out` の下に `<checkpoint の親ディレクトリ名>_q4_g64.jtlm` ができます。

  ```bash
  uv run --group train python -m jtalm.model.export \
    --ckpt <best.pt> --tokenizer <tokenizer.model> --bits 4 --out <出力先>
  ```

`model` partition は 14MB なので、3M なら FP32（12.9MB）まで入ります。5M の FP32（20.5MB）は入りません。

### 書き込み

app とモデルを、それぞれの offset に書きます（flash の配置は [`../docs/hardware.md`](../docs/hardware.md) の「Flash の配置」）。

```bash
cd firmware/jtalm_action/build
esptool --chip esp32s3 -p <PORT> -b 921600 write-flash \
  --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin \
  0x10000 jtalm_action.bin 0x200000 <path>/jtalm_action_3m_q4_g64.jtlm

# モデルだけを替えるときは 0x200000 だけを書けば足ります
esptool --chip esp32s3 -p <PORT> -b 921600 write-flash 0x200000 <model>.jtlm
```

- `--flash-mode dio` は image header の値です。2nd stage bootloader が起動時に QIO へ切り替えます。
- ESP-IDF の image に入っている esptool（4 系）ではなく、5 系を使ってください（`write-flash` のような hyphen の付いた subcommand は 5 系の書き方です）。
- 起動時にモデルの SHA-256 の先頭 16 桁を `info` の行に出すので、どのモデルが動いているかを serial で確かめられます。
- **`.jtlm` と firmware の Action schema の版を合わせてください。** この firmware（schema v1 の grammar）は、v1 の tokenizer（`action_v1_sp2048`）で作った `.jtlm` だけを読みます。v0 の `.jtlm` を書いたまま起動すると、`JTALM {"t":"error","msg":"the tokenizer lacks the Action grammar pieces"}` を出して LM が止まり、画面と dispatcher も起動しません（`ready` は出ません）。v1 の `.jtlm` を `0x200000` に書き直せば直ります。

## Serial の protocol

USB-Serial/JTAG の console を使います。PC 側は 115200 bps で開いてください（USB なので実際の速度は baud rate によりません）。

- **入力:** UTF-8 の1行が1件の依頼です（CR と LF のどちらも行末。空行は無視。先頭の BOM は取り除く。最大 1,023 byte）。`!` で始まる行は command です。待ち行列（4行）があふれると、`error`（`busy: line dropped`）を返して捨てます。
- **出力:** 機械が読む行は、すべて `JTALM ` に続く1行の JSON です。`t` が種類を表します。それ以外の行（ESP-IDF の log など）は無視してください。

起動すると `heap`、`load`（mmap した partition）、`info`（firmware、モデルの設定と SHA-256、arena の置き場所、gate）、`board`（画面、IO expander、LED の初期化、servo は `dry`）、`face`（neutral）、`settings`（NVS から読んだ音量、明るさ、LED の色）を出し、`ready` の後に入力を待ちます。

| `t` | いつ | 主な項目 |
|---|---|---|
| `gen` | 依頼を1件処理した後 | `output`（gate の後の出力。dispatcher が実行するのはこれ）、`raw`（gate の前の出力）、`gated`、`gate`、`min_prob`、`ids`、`prompt_ids`、`n_prompt`、`n_gen`、`tok_ms`、`prefill_ms`、`decode_ms`、`total_ms`、`tok_s` |
| `act` | `gen` の直後と `!act` / `!center` / `!pose` / `!servo on` の後 | `seq`、`src`（`lm` / `cmd` / `center` / `pose` / `servo_on`）、`valid`、`err`、`calls`、`from` と `to`（[yaw, pitch] の度。右と上が正）、`steps`（`k` が種類。`move` は目標の角度、raw、時間 ms、`clamped`。`expr` は表情、`led` は色、`volume` / `brightness` は `level`（`adjust_*` では `delta`）、`pause` はお辞儀の静止 ms）、`total_ms`、`queued`、`servo`（`dry` / `on`） |
| `face` | 表情を変えたとき | `seq`、`expr`、`crc`（画面 320×240 の CRC-32）、`draw_us`、`push_us` |
| `setting` | LED、音量、明るさを変えたとき | `seq`、`what`（`led` / `volume` / `brightness`）、`color` または `level`（変えた後の値）、`ok` |
| `settings` | 起動時 | `volume`、`brightness`、`led`、`nvs`（NVS を使えたか） |
| `led` | `!led` の後 | `r`、`g`、`b`（168 以下に制限した値）、`ok`、`cfg`（PY32 から読み返した LED の個数） |
| `act_done` | 計画の実行が終わったとき | `seq`、`planned_ms`、`ms`、`sync_ms`（始点への移動）、`aborted`、`err`、`pose`、`present`（servo から読んだ raw。dry-run では −1） |
| `stop` | 止めたとき | `src`（`stop` / `servo off` / `relax` / `touch` / `watchdog` など）、`power_off`、`torque_off`、`vm_off` |
| `fault` | watchdog、servo の通信の error | `why`。続けて `stop` を出す |
| `servo` | `!servo on` の後、`!servo` | 状態（`on` / `off`）、ping の応答時間、`vm_en`（IO expander から読み返した servo の電源）、`pose` |
| `heap` | 起動の各段階、最初の依頼の後、`!heap` | 内部 SRAM と PSRAM の空き、最大連続ブロック、最小空き、chip の温度（`temp_c`。内蔵センサーの値で、相対的な変化を見るもの）、CPU の clock（`cpu_mhz`） |
| `ok` / `error` | 設定の command の後 / 失敗したとき | 変えた値 / `msg` |

`gen` の行の形（値は省略）:

```text
JTALM {"t":"gen","output":"[{\"name\":\"look\",\"arguments\":{\"direction\":\"right\",\"amount\":\"normal\"}}]","raw":"…","gated":0,"gate":0.83673,"min_prob":…,"ids":[…],"prompt_ids":[…],"n_prompt":…,"n_gen":…,…,"total_ms":…}
```

### Command

| Command | 内容 |
|---|---|
| `!servo on` | servo の電源を入れ、両方が ping に答えるまで待ち（約 0.85 秒）、今の位置から正面へゆっくり戻す。**首が動く** |
| `!stop`、`!servo off` | 実行中と待ち行列の計画を捨て、torque を切り、servo の電源を切って dry-run に戻る。**LM の処理中でもすぐに効く** |
| `!relax` | torque だけを切る（すぐに効く） |
| `!servo` | servo の状態を出す（すぐに効く） |
| `!center` | 正面を向く |
| `!pose <yaw> <pitch>` | 指定した角度（度。右と上が正）へ1回で動く。可動域の外は端で止める（保守と可動域の確認用。例: `!pose 30 20`）。servo が on なら**首が動く** |
| `!led <r> <g> <b>` | 台座の LED を12個とも指定した色にする（診断用。各成分は 0〜168 に制限。設定としては保存しない） |
| `!act <json>` | LM を通さずに Action JSON を検査して実行する（例: `!act [{"name":"nod","arguments":{"count":2}}]`） |
| `!gate <閾値>` | gate の閾値を変える（例: `!gate 0.9`。0 で off） |
| `!grammar 0\|1` | grammar による制約の off / on（既定 on） |
| `!info`、`!heap` | firmware とモデルの情報、メモリ |
| `!par 0\|1`、`!batch 0\|1` | 行列積を2つの core に分ける / prompt をまとめて処理する（どちらも既定 on。計測用） |
| `!bench` | `expf` と1 step の forward の時間 |
| `!autoload <trigger> <size>` | DCache の autoload の実験（既定 off。`-1` で off） |
| `!servo probe` | dry-run のときだけ。電源を入れて ping し、位置を読んで電源を切る（goal も torque も送らない） |
| `!wdtest` | dry-run のときだけ。期限を過ぎる計画を流して watchdog を確かめる |

**画面に触れても `!stop` と同じになります。**

## Confidence gate

生成した token の確率の最小値（`min_prob`。grammar で制約する前の確率）が閾値より小さいと、`output` を `[]` にします（`jtalm.model.evaluate` の `gate` と同じ比較）。`raw` には gate の前の出力が残ります。

- 既定値は `CONFIG_JTALM_GATE_PPM=836730`（100万分率。0.83673）です。採用モデル（Action schema v1、データ v1.1 の 3M INT4、seed 1）の validation だけで選んだ閾値 0.83673（[`results/v11_action/suite_3m-s1/`](../results/v11_action/suite_3m-s1/suite.md)）と同じ値です。データ v1.0 のモデル（seed 0）のときは `885060`（0.88506）、v0 の firmware は千分率の `CONFIG_JTALM_GATE_PERMILLE=868` でした。
- 定義は `jtalm_action/main/Kconfig.projbuild`（menu「JapaneseTinyAgentLM」）、既定値は `jtalm_action/sdkconfig.defaults` にあります。`idf.py menuconfig` で変えるか、`sdkconfig.defaults` を変えて生成済みの `sdkconfig` を消してから build し直します。
- 実行中は `!gate <閾値>` で変えられます（再起動で既定値に戻ります）。
- 別のモデルを書き込むときは、そのモデルの validation で選んだ閾値にしてください。

## INT8 の KV cache

`CONFIG_JTLM_KV_INT8=y`（menu「JapaneseTinyAgentLM runtime」、定義は [`../runtime/host/Kconfig`](../runtime/host/Kconfig)）で build すると、KV cache を int8 で持ちます（3M で PSRAM 458,752 B → 129,024 B）。3M では評価セットの gate 後の出力は f32 と同じで、応答は約 2% 遅くなります（[`results/v051_action/kv_int8/`](../results/v051_action/kv_int8/README.md)）。公開しているビルド済みの image は f32 です。起動時の `info` の `kv_int8` でどちらかがわかります。

```sh
printf 'CONFIG_JTLM_KV_INT8=y\n' > kv8.defaults
idf.py -B build_kv8 -D SDKCONFIG=build_kv8/sdkconfig -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;kv8.defaults" build
```

## ツール

`firmware/tools/` のスクリプトです。pyserial だけが必要なものは、`uv run --no-project --with pyserial python …` で project の依存を足さずに動きます（`pip install pyserial` でも構いません）。

| ファイル | 内容 |
|---|---|
| `stackchan_chat.py` | 対話。1行入力するごとに Action JSON と時間を表示する。`--servo` で首も動かす。終了時に `!stop` を送る。Hugging Face のモデルにも同梱 |
| `lm_serial.py` | 依頼を1件ずつ送り、応答を JSONL に保存し、latency をまとめる。`--ref` で host の runtime（`runtime/host/build/jtalm --grammar`）の出力と比べる。`--act` で dispatcher の計画（`act` の行）も保存する。長時間の実行には `--repeat K`（依頼を K 周送る）と `--heap-every N`（N 件ごとに `heap` を記録）を使う |
| `dispatch_check.py` | dispatcher の計画を Python（`jtalm.action.parse_output` と `jtalm.action.mapping`）で計算し直して照合する。serial log の `act_done` / `face` / `fault` も確かめる。`--fuzz N` で `!act` を使った validator の検査 |
| `led_probe.py` | 台座の LED を赤、緑、青、白、消灯の順に点ける（`!led`）。人が見て色を確かめる。servo は off のまま |
| `limits_check.py` | 可動域を 5° ずつ広げながら、servo から読んだ位置と目標を比べる（`!pose`）。**首が動く**ので、人が見ているときだけ使う。NG、fault、タッチで止まり、最後は正面に戻して servo を切る |
| `act_host.c` | firmware の validator と planner（`action.c`）を PC で build したもの。標準入力の Action JSON 1行ごとに、`act` の行と同じ形の計画を出す。`dispatch_check.py --host-results` で Python と照合する（Docker の `espressif/idf:v5.5.5` の gcc で build できる） |
| `servo_test.py` | 首の動作確認の手順（`!act` の 16項目と、LM を通す 12項目。否定や雑談で動かないことを含む）を流す。`--servo` を付けないと dry-run。`--only <文字列>` で一部だけ |
| `serial_capture.py` | serial log の取得。`--reset`、prompt への自動応答（`--send-on`）、終了条件（`--until`）を指定できる |

```bash
# 依頼を送って保存する（prompts.txt は1行1件。.jsonl なら "prompt" の項目を使う）
uv run --no-project --with pyserial python firmware/tools/lm_serial.py --port <PORT> --reset --act \
  --cases prompts.txt --out out/device.jsonl
# 計画を Python の参照と照合する（jtalm を import するので project の環境で動かす）
uv run python firmware/tools/dispatch_check.py --results out/device.jsonl --log out/device.log
# validator の検査（!act で 400件）
uv run --with pyserial python firmware/tools/dispatch_check.py --port <PORT> --fuzz 400 --out out/fuzz.jsonl
# 動作確認の手順を dry-run で流す（--servo を付けると首が動く）
uv run --no-project --with pyserial python firmware/tools/servo_test.py --port <PORT> --out out/servo_test.jsonl
# serial log を 30 秒取る
uv run --no-project --with pyserial python firmware/tools/serial_capture.py --port <PORT> --reset --seconds 30 --out out/boot.log
```

- 首を動かす前に、同じ手順を `--servo` なしで流して、計画（角度、raw、時間）を確かめてください。
- `servo_test.py --servo` は、1項目ごとに計画を表示し、動き終わってから `--pause` 秒待ちます。`stop` や `fault` の行が出るか Ctrl+C で `!stop` を送って終わり、最後は正面に戻して `!servo off` にします。

## jtalm_eval（計測用）

LM を含まない最小の firmware です。Wi-Fi、画面、servo は使わず、GPIO も操作しません。起動時に device の情報、partition table、段階ごとの heap、PSRAM と flash mmap の読み出し帯域を `JTALM {json}` で出します。serial から `b` を送ると帯域を測り直し、`h` で heap を出します。partition table は `jtalm_action` と同じです。

```bash
docker run --rm -v "$PWD/firmware:/fw" -w /fw/jtalm_eval espressif/idf:v5.5.5 idf.py build
cd firmware/jtalm_eval/build
esptool --chip esp32s3 -p <PORT> -b 921600 write-flash \
  --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x10000 jtalm_eval.bin
```

## 第三者のコードとライセンス

このディレクトリのコードは Apache-2.0 です。配布する firmware の binary には次の第三者のコードが含まれ、ライセンスの全文は [`jtalm_action/licenses/`](jtalm_action/licenses/README.md) にあります。binary を配布するときは、このディレクトリを添えてください。`0x200000` に書くモデルのデータは CC BY-SA 4.0 です。

| 対象 | 使い方 | License |
|---|---|---|
| ESP-IDF v5.5.5（newlib、FreeRTOS を含む） | bootloader、driver、C library、task | Apache-2.0 ほか（`licenses/README.md`） |
| M5Unified 0.2.17、M5GFX 0.2.23（M5GFX が同梱する Adafruit GFX の font を含む） | 画面、タッチ、電源の初期化と顔の描画。stackchan-idf の submodule をそのまま build する | MIT（font は BSD-2-Clause） |
| stackchan-idf の `components/scs_servo`、`components/board/io_expander_py32.cpp` | コードは copy していない。SCS0009 の register（torque `0x28`、goal `0x2A`、現在位置 `0x38`、big-endian）と PY32L020 の register（version `0x02`、GPIO mode `0x03`、output `0x05`、`VM_EN` は pin 0）を参考にした。SCS の driver（`main/servo.c`）は自前 | BSL-1.0 |

既存の runtime（esp32-llm）と stackchan-idf を CoreS3 で動かした手順は [`baselines/README.md`](baselines/README.md) にあります。
