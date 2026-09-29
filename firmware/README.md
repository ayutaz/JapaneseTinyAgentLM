# firmware

M5Stack CoreS3（StackChan K151）向けの firmware です。実機の構成と計測結果は [`docs/hardware.md`](../docs/hardware.md) を参照してください。

| Directory | 内容 | License |
|---|---|---|
| `jtalm_eval/` | LM 評価用の最小 firmware（B3）。heap、Flash map、PSRAM / Flash mmap の帯域を `JTALM {json}` 形式で出力する。Servo と Wi-Fi は使わない | Apache-2.0 |
| `jtalm_action/` | Action LM の firmware（B4、A1〜A3）。`model` partition の `.jtlm` を mmap し、serial から受けた1行の発話を grammar 付きの greedy と confidence gate で Action JSON にして、時間と一緒に `JTALM {json}` で返す。LM の本体は `runtime/host/` の source をそのまま build する。出力を実機側でもう一度検査し、servo の目標値と表情に変換して実行する（dispatcher）。**servo の出力は起動時に off（dry-run）**で、`!servo on` を送ったときだけ首が動く。画面に顔を出す（M5Unified / M5GFX）。Wi-Fi は使わない | Apache-2.0（M5Unified / M5GFX は MIT。下の「第三者のコード」） |
| `baselines/esp32_llm/` | [doryiii/esp32-llm](https://github.com/doryiii/esp32-llm) を CoreS3 で動かすための sdkconfig の overlay と patch（B2.5） | Apache-2.0（patch の対象は上流の MIT のコード） |
| `baselines/stackchan_idf/` | [ciniml/stackchan-idf](https://github.com/ciniml/stackchan-idf) を Docker で build するための Node.js の shim（B2。servo の確認は 2026-09-29 に実施済み） | Apache-2.0 |
| `tools/serial_capture.py` | Serial log の取得。reset、prompt への自動応答、終了条件を指定できる | Apache-2.0 |
| `tools/lm_serial.py` | `jtalm_action` に prompt を1件ずつ送り、応答を JSONL に保存する。host の runtime の出力と比べ、latency をまとめる。`--act` で dispatcher の計画（`act` の行）も保存する | Apache-2.0 |
| `tools/dispatch_check.py` | dispatcher の計画を、Python（`jtalm.action.parse_output` と `jtalm.action.mapping`）で計算し直して照合する。serial log の `act_done` / `face` / `fault` も確かめる。`--fuzz` で `!act` を使った validator の検査 | Apache-2.0 |
| `tools/servo_test.py` | servo の動作確認の手順を流す（[`docs/hardware.md`](../docs/hardware.md) §12）。`--servo` を付けないと dry-run。**`--servo` は首が動くので、ユーザーが立ち会うときだけ使う** | Apache-2.0 |
| `third_party/` | 第三者の repository の clone。Git の管理外 | 各 upstream |

## Build と書き込み

Build は ESP-IDF v5.5.5 の Docker image で行い、書き込みは Windows から esptool で行います。書き込みの前に、Flash のバックアップの SHA-256 を確認してください（[`docs/development.md`](../docs/development.md) §5）。

```sh
# jtalm_eval の build（Git Bash）
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/firmware:/fw" -w /fw/jtalm_eval \
  espressif/idf:v5.5.5 idf.py build

# 書き込み
cd firmware/jtalm_eval/build
uvx --from esptool esptool --chip esp32s3 -p COM3 -b 921600 write-flash \
  --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x10000 jtalm_eval.bin

# Serial log（reset して30秒）
uv run --no-project --with pyserial python firmware/tools/serial_capture.py \
  --port COM3 --reset --seconds 30 --out runs/device/jtalm_eval.log
```

### jtalm_action（B4、A1〜A3）

**実機の現在の状態（2026-09-29）:** A1〜A3 の `jtalm_action`（app の SHA-256 `125e375c…28f0bf1e3f`）と v0.4 の 3M INT4（`runs/local/b4_v04/3m_q4_g64.jtlm`）を書き込み、confidence gate 0.970 を有効にしてあります。**servo の出力は off（dry-run）で、servo の電源（VM_EN）も切ってあります。** servo の電源を入れて ping と位置の読み取りまでは確かめました（首は動かしていない）。首を動かす確認はまだ行っていません（[`docs/hardware.md`](../docs/hardware.md) §12 の手順で、ユーザーの立ち会いのもとで行う）。

`runtime/host/` を参照するので、repository の root を mount します。画面には M5Unified と M5GFX を使い、`third_party/stackchan-idf` の submodule（下の stackchan-idf の手順で取得したもの）をそのまま build します（`CMakeLists.txt` の `M5UNIFIED_DIR` / `M5GFX_DIR`）。

```sh
# Build（Git Bash、repository の root で）
MSYS_NO_PATHCONV=1 docker run --rm -e IDF_COMPONENT_MANAGER=0 -v "$(pwd -W):/w"   -w /w/firmware/jtalm_action espressif/idf:v5.5.5 idf.py build

# model の書き出し（採用した v0.4 の 3M。runs/local/b4_v04/ に 3m_q4_g64 / 3m_q8_g64 .jtlm ができる）
uv run --group train python -m jtalm.model.export   --ckpt runs/vast/train_action_v04-20260929T095441Z/artifacts/v04/3m/best.pt   --tokenizer tokenizer/out/action_v0_sp2048.model --bits 4 8 --out runs/local/b4_v04

# 書き込み（app と model。model を替えるときは 0x200000 だけを書けばよい）
cd firmware/jtalm_action/build
uvx --from esptool esptool --chip esp32s3 -p COM3 -b 921600 write-flash   --flash-mode dio --flash-size 16MB --flash-freq 80m   0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin   0x10000 jtalm_action.bin 0x200000 ../../../runs/local/b4_v04/3m_q4_g64.jtlm
cd ../../..

# 評価セットの先頭 200件を送り、host の出力（runtime/host/build/jtalm --grammar）と比べる
# （host 側: prompts200.txt に同じ 200件を1行ずつ書き、
#   runtime/host/build/jtalm -m <model>.jtlm -i prompts200.txt --grammar > host_d_v04_3m_q4_g64.jsonl）
uv run --no-project --with pyserial python firmware/tools/lm_serial.py --port COM3 --reset   --cases datasets/action/v0/eval.jsonl --limit 200   --ref runs/device/b4/host_d_v04_3m_q4_g64.jsonl --out runs/device/b4/v04_3m_q4.jsonl
# --limit を省くと評価セットの全 1,189件を送る（結果の例: results/b4_device/v04_3m_q4_g64_all.summary.json）
```

- `model` partition は 14MB なので、5M の FP32（20.5MB）は載りません。3M の FP32（12.9MB）は載ります。
- 起動すると `load`（mmap）、`info`（model の設定、image の SHA-256 の先頭 16 桁、arena の置き場所）、`heap` を出し、`ready` の後に入力を待ちます。
- 1行が1件の発話です（UTF-8、CR / LF の両方を行末とみなす）。応答は `JTALM {"t":"gen","output":...,"raw":...,"gated":0|1,"gate":0.970,"min_prob":...,"ids":[...],"prompt_ids":[...],"n_prompt":...,"n_gen":...,"tok_ms":...,"prefill_ms":...,"decode_ms":...,"total_ms":...,"ms_per_fwd":...,"tok_s":...}` の1行です。最初の要求の後に `heap`（`first_request`）を出します。
- **Confidence gate:** 生成した token の確率の最小値（`min_prob`。grammar で制約する前の確率）が閾値より小さいと、`output` を `[]` にします（`jtalm.model.evaluate` の `gate` と同じ）。`raw` は gate をかける前の出力です。閾値は `sdkconfig.defaults` の `CONFIG_JTALM_GATE_PERMILLE`（千分率、既定 970 = 0.970。`main/Kconfig.projbuild`）で決め、実行中は `!gate 0.97` で変えられます（0 で off）。`lm_serial.py` は、host の出力に同じ gate をかけたものとも比べます。
- `!` で始まる行は command です: `!info`、`!heap`、`!grammar 0|1`、`!gate <閾値>`、`!par 0|1`（行列積を2つの core に分ける。既定は 1）、`!batch 0|1`（prompt のまとめ処理。0 は1 token ずつ）、`!bench`（`expf` と1 step の forward の時間）、`!autoload T S`（DCache の autoload の実験用。既定は off）。
- **Dispatcher（A1〜A3）:** `gen` の行の後に、gate の後の `output` を実機で検査して計画した結果を `JTALM {"t":"act","seq":..,"valid":..,"err":..,"calls":[..],"from":[yaw,pitch],"steps":[..],"to":[..],"total_ms":..,"queued":..,"servo":"dry"|"on"}` の1行で出します（角度は度、右と上が正。`steps` の各 move は目標の角度、raw、時間 ms、soft limit で制限したか）。計画は dispatcher の task が順に実行し、表情を変えるたびに `face`（表情、画面 320×240 の CRC-32、描画と転送の時間）、終わると `act_done`（実際の時間、中断したか、servo の実際の位置）を出します。`gen` の行の中身と LM の処理は B4 と同じです。
- **Servo の command:** `!servo on`（servo の電源を入れて ping し、今の位置から正面へゆっくり戻す。**首が動く**）、`!center`（正面へ）、`!act <json>`（LM を通さずに Action JSON を実行する）。次の3つは LM の処理中でもすぐに効きます: `!stop` と `!servo off`（実行中と待ち行列の計画を捨て、torque を切り、servo の電源を切って dry-run に戻る）、`!relax`（torque だけを切る）、`!servo`（状態。`vm_en` は IO expander から読み返した servo 電源の状態）。**画面に触れても `!stop` と同じになります。** `!wdtest` は dry-run のときだけ、期限を過ぎる計画を流して watchdog を確かめます。`!servo probe` は servo の出力が off のときだけ、電源を入れて ping し、位置を読んで電源を切ります（goal も torque も送らない。IO expander の register も出す）。
- 設計（角度、制限、動きの滑らかさ、うなずき、watchdog）と計測結果は [`docs/hardware.md`](../docs/hardware.md) §12 にあります。

```sh
# 評価セットの先頭 200件: LM の出力の一致（--ref）と、dispatcher の計画（--act）を保存する
uv run --no-project --with pyserial python firmware/tools/lm_serial.py --port COM3 --reset --act \
  --cases datasets/action/v0/eval.jsonl --limit 200 \
  --ref runs/device/b4/host_d_v04_3m_q4_g64.jsonl --out runs/device/a1/eval200.jsonl
# 計画を Python の参照と照合する（log の act_done / face / fault も確かめる）
uv run python firmware/tools/dispatch_check.py --results runs/device/a1/eval200.jsonl \
  --log runs/device/a1/eval200.log --out runs/device/a1/eval200_dispatch
# validator の検査（!act で 400件。valid / invalid と計画を Python と比べる）
uv run --with pyserial python firmware/tools/dispatch_check.py --port COM3 --fuzz 400 \
  --out runs/device/a1/fuzz.jsonl
# servo の動作確認の手順を dry-run で流す（--servo を付けると首が動く。docs/hardware.md §12）
uv run --no-project --with pyserial python firmware/tools/servo_test.py --port COM3 \
  --out runs/device/a1/servo_test_dry.jsonl
```

#### 第三者のコード（jtalm_action）

| 対象 | 使い方 | License |
|---|---|---|
| M5Unified 0.2.17（`8108bfad`）、M5GFX 0.2.23（`27e1ef0f`） | `firmware/third_party/stackchan-idf/` の submodule を、copy せずにそのまま build する（画面、touch、電源の初期化と顔の描画） | MIT（© 2021 M5Stack）。firmware の binary を配布するときは、両者の LICENSE の表示を添える |
| stackchan-idf（`419385ef1b87`）の `components/scs_servo` と `components/board/io_expander_py32.cpp` | コードは copy していない。SCS0009 の register（torque 0x28、goal 0x2A、present 0x38、big-endian）と PY32L020 の register（version 0x02、GPIO mode 0x03、output 0x05、VM_EN は pin 0）を参考にした。SCS の driver（`main/servo.c`）は自前 | BSL-1.0（© Kenta IDA） |

- build に使った M5Unified の checkout には、stackchan-idf の `tools/apply-m5-patches.sh` の patch（Speaker と RTC の2か所）が当たっています。この firmware は speaker と RTC を使わないので影響しません（patch を当てない checkout での build は未確認）。
- M5GFX の自動判別は、この個体を `board_M5StackChan`（CoreS3 と同じ扱い）と判定します。M5Unified は speaker、mic、IMU、RTC を使わない設定で初期化します。

### esp32-llm（B2.5）

```sh
cd firmware/third_party
git clone https://github.com/doryiii/esp32-llm.git
cd esp32-llm && git checkout c6c647f7bfbb74efd2bbfd9a1725da4a903589f4
git apply ../../baselines/esp32_llm/cores3.patch
cd ../../..

# INT8（stories3M）。追加の依存はないので component manager を止める
MSYS_NO_PATHCONV=1 docker run --rm -e IDF_COMPONENT_MANAGER=0 \
  -v "$(pwd -W)/firmware:/fw" -w /fw/third_party/esp32-llm espressif/idf:v5.5.5 bash -c '
  D="sdkconfig.defaults;/fw/baselines/esp32_llm/sdkconfig.cores3"
  idf.py -B build_int8 -D SDKCONFIG=build_int8/sdkconfig -D SDKCONFIG_DEFAULTS="$D" set-target esp32s3 &&
  idf.py -B build_int8 -D SDKCONFIG=build_int8/sdkconfig -D SDKCONFIG_DEFAULTS="$D" build'

cd firmware/third_party/esp32-llm/build_int8
uvx --from esptool esptool --chip esp32s3 -p COM3 -b 921600 write-flash \
  --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin \
  0x10000 llm.bin 0x210000 storage.bin

# 3回生成して log を取る（"Press Enter" に改行を返す）
uv run --no-project --with pyserial python firmware/tools/serial_capture.py \
  --port COM3 --reset --seconds 400 --send-on "Press Enter to" "" --max-sends 3 \
  --until "forward-only" --until-count 3 --out runs/device/esp32_llm_int8.log
```

FP32（stories260K）は `sdkconfig.fp32` も `SDKCONFIG_DEFAULTS` に加え、build dir を `build_fp32` にします。FP32 は `espressif/esp-dsp` を Component Registry から取得するので、`IDF_COMPONENT_MANAGER=0` は付けません。SPIFFS の image（`storage.bin`）は INT8 と同じなので、INT8 の後なら app だけを書き込めば足ります。

### stackchan-idf（B2。書き込むと servo が動く）

**書き込みは、ユーザーが立ち会うときだけ行います。** 2026-09-29 にユーザーの立ち会いのもとで確認を終えました（中立は yaw 460 / pitch 620、ロボット自身の右へ回すと yaw の raw が減る）。手順と結果は [`docs/hardware.md`](../docs/hardware.md) §10 を参照してください。確認の後は Flash 全体を消して `jtalm_action` に戻しました。

```sh
cd firmware/third_party
git clone https://github.com/ciniml/stackchan-idf.git
cd stackchan-idf && git checkout 419385ef1b875137140085bd50d34dee331f30c2
git submodule update --init --recursive
bash tools/apply-m5-patches.sh

# Build 中の Node.js の2工程を Windows 側で先に実行し、container 用の shim を置く
mkdir -p .hostnode
node tools/avatar_dsl/cli.mjs assets/default_face.avdsl .hostnode/default_face.avbc
node tools/avatar_dsl/inject.mjs components/wifi_config_service/web/settings_wifi.html \
  .hostnode/settings_wifi.html default=assets/default_face.avdsl \
  omega=assets/omega_mouth.avdsl aokko=assets/aokko_face.avdsl
cp ../../baselines/stackchan_idf/node .hostnode/node
cd ../../..

MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/firmware:/fw" \
  -w /fw/third_party/stackchan-idf espressif/idf:v5.5.5 bash -c '
  export PATH=/fw/third_party/stackchan-idf/.hostnode:$PATH
  git config --global --add safe.directory "*"
  D="sdkconfig.defaults;sdkconfig.defaults.esp32s3;sdkconfig.defaults.cores3"
  idf.py -B build-cores3 -DSDKCONFIG=build-cores3/sdkconfig -DSDKCONFIG_DEFAULTS="$D" set-target esp32s3 &&
  idf.py -B build-cores3 -DSDKCONFIG=build-cores3/sdkconfig -DSDKCONFIG_DEFAULTS="$D" build'
```
