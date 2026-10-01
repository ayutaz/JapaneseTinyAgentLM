# baselines

既存の2つの project を M5Stack CoreS3（スタックチャン K151）で動かすための差分と手順です。どちらも本プロジェクトの firmware には含めず、比較の基準値と servo の仕様の確認だけに使いました。

| Directory | 対象 | 目的 |
|---|---|---|
| `esp32_llm/` | [doryiii/esp32-llm](https://github.com/doryiii/esp32-llm)（commit `c6c647f7bfbb`） | 既存の LLM runtime の CoreS3 での速度とメモリ（基準値） |
| `stackchan_idf/` | [ciniml/stackchan-idf](https://github.com/ciniml/stackchan-idf)（commit `419385ef1b87`、v0.15.0-alpha.2） | K151 の servo の向きと中立位置の確認 |

この directory のファイルは Apache-2.0 です。ただし `esp32_llm/cores3.patch` は、上流の MIT License のコード（`main/llm.c`、`main/llm8.c`、`main/main.c`）を変更する patch です。

Clone 先の `firmware/third_party/` は Git の管理外です。以下のコマンドは repository の root から実行します。Windows の Git Bash では、`docker run` の前に `MSYS_NO_PATHCONV=1` を付け、`$PWD` の代わりに `$(pwd -W)` を使ってください。`<PORT>` は自分の serial port に置き換えてください（例: Windows は `COM3`、Linux は `/dev/ttyACM0`）。

## esp32-llm

### License

| 対象 | License |
|---|---|
| Source（`main/*.c`、`*.h`） | MIT（各ファイルの header。Copyright 2023 Andrej Karpathy、2026 Dory） |
| Repository 全体 | LICENSE ファイルはない |
| Model / tokenizer（`spiffs_data/` の4ファイル） | Repository に同梱。個別の license 表記はない（stories260K は karpathy/tinyllamas 由来と README にある） |

LICENSE ファイルがなく、model の license も明記されていないので、本プロジェクトの成果物には取り込んでいません。

### CoreS3 向けの変更

| 変更 | 理由 |
|---|---|
| PSRAM を Octal から Quad に（`sdkconfig.cores3`） | 上流は Waveshare ESP32-S3-LCD-1.9（Octal PSRAM）向け。CoreS3 は Quad |
| Flash mode を QIO に（`sdkconfig.cores3`） | CoreS3 の flash は quad |
| `main.c` の GPIO14 の操作（上流の board の LCD backlight）を削除（`cores3.patch`） | CoreS3 の GPIO14 は mic codec の I2S data 入力なので、出力にしない |
| `generate()` に forward だけの時間の計測を追加（`cores3.patch`） | 上流の tok/s は、token ごとの `vTaskDelay(1)` と serial 出力を含むため |

Servo の UART（`G6` / `G7`）を触るコードは、上流にも変更後にもありません。

### Build と書き込み

```bash
git clone https://github.com/doryiii/esp32-llm.git firmware/third_party/esp32-llm
cd firmware/third_party/esp32-llm
git checkout c6c647f7bfbb74efd2bbfd9a1725da4a903589f4
git apply ../../baselines/esp32_llm/cores3.patch
cd ../../..

# INT8（stories3M）。追加の依存がないので component manager を止める
docker run --rm -e IDF_COMPONENT_MANAGER=0 \
  -v "$PWD/firmware:/fw" -w /fw/third_party/esp32-llm espressif/idf:v5.5.5 bash -c '
  D="sdkconfig.defaults;/fw/baselines/esp32_llm/sdkconfig.cores3"
  idf.py -B build_int8 -D SDKCONFIG=build_int8/sdkconfig -D SDKCONFIG_DEFAULTS="$D" set-target esp32s3 &&
  idf.py -B build_int8 -D SDKCONFIG=build_int8/sdkconfig -D SDKCONFIG_DEFAULTS="$D" build'

cd firmware/third_party/esp32-llm/build_int8
esptool --chip esp32s3 -p <PORT> -b 921600 write-flash \
  --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin \
  0x10000 llm.bin 0x210000 storage.bin
cd ../../../..

# 3回生成して log を取る（"Press Enter" に改行を返す）
uv run --no-project --with pyserial python firmware/tools/serial_capture.py \
  --port <PORT> --reset --seconds 400 --send-on "Press Enter to" "" --max-sends 3 \
  --until "forward-only" --until-count 3 --out esp32_llm_int8.log
```

FP32（stories260K）は、`SDKCONFIG_DEFAULTS` に `/fw/baselines/esp32_llm/sdkconfig.fp32` も加え、build dir を `build_fp32` にします。FP32 の engine は `espressif/esp-dsp`（Apache-2.0）を Component Registry から取得するので、`IDF_COMPONENT_MANAGER=0` は付けません。SPIFFS の image（`storage.bin`）は INT8 と同じなので、INT8 の後なら app だけを書けば足ります。

### 結果

Prompt は空、temperature 1.0、top-p 0.9、生成は BOS まで（最大 512）。重みは SPIFFS から PSRAM に読み込んで使います（mmap ではない）。

| Model | 3回の生成 token 数 | 上流の tok/s（loop 全体） | Forward だけの tok/s | 内部 SRAM の使用量 | PSRAM の使用量 |
|---|---|---|---|---:|---:|
| stories3M INT8（dim 192、6 layer、vocab 4,096、3,352,576 B） | 200 / 174 / 217 | 6.25 / 6.59 / 6.04 | 6.74 / 7.15 / 6.50 | 40,396 B | 4,925,452 B（重み 3.35MB、FP32 の KV cache 1.57MB） |
| stories260K FP32（dim 64、5 layer、vocab 512、1,056,540 B） | 406 / 330 / 453 | 12.40 / 15.18 / 11.14 | 13.36 / 16.62 / 11.90 | 20,984 B | 1,736,716 B |

- 上流の約 12 tok/s（Octal PSRAM）に対し、CoreS3（Quad PSRAM）の INT8 は約 6.0〜6.6 tok/s で、約半分です。帯域の上限（32.8 MB/s ÷ 3.35MB ≒ 9.8 tok/s）の約 7割です。
- 本プロジェクトの 3M INT8 は decode が 115 ms/token（8.7 tok/s）で、同じくらいの重みの stories3M INT8（forward だけで 140〜154 ms/token）より速いです（[`../../docs/hardware.md`](../../docs/hardware.md) の「実機の性能」）。
- ここから得た方針: 重みの byte 数を減らす（INT4、語彙の縮小、埋め込みの共有）、prompt をまとめて処理する、KV cache を実際の系列長に合わせて小さくする。

## stackchan-idf

K151 で servo の向き（首をロボット自身の右へ回すと yaw の raw が増えるか減るか）と、正面・水平になる raw を確かめるために使いました。結果は [`../../docs/hardware.md`](../../docs/hardware.md) の「座標の規約と raw への変換」にあります（中立は yaw 460 / pitch 620、右へ回すと yaw の raw が減る）。

> **書き込むと、起動してすぐに servo が動きます**（正面へ移動した後、10〜20秒ごとに random な姿勢へ動く）。首のまわりに指やケーブルを近づけないでください。止めるときは、画面右上を tap →「操作」→「サーボ（脱力/復帰）」で torque を切るか、電源ボタンを長押しして電源を切ってください。

### License と依存

| 対象 | Version | License |
|---|---|---|
| stackchan-idf のソース | — | BSL-1.0 |
| Submodule: m5stack/M5Unified | 0.2.17 | MIT |
| Submodule: m5stack/M5GFX | 0.2.23 | MIT |
| Submodule: TartanLlama/expected | v1.3.1 | CC0 1.0 |
| Managed components（cores3 の build で取得する13個） | — | Apache-2.0: cmake_utilities、esp_jpeg、esp_websocket_client、esp32-camera、esp-dsp、esp-now、led_strip、mdns。MIT: cjson、dl_fft。Espressif Modified MIT: esp-sr、esp_audio_codec。ISC: quirc |
| HMM voice "Mei"、hts_engine API | — | CC BY 3.0、Modified BSD（`THIRD_PARTY_NOTICES.md`。voice の data は書き込まない） |

### Build

上流の手順との違いは2点です。

1. 上流の README のとおり、`tools/apply-m5-patches.sh` で M5Unified に patch を当てます。
2. Build の途中で Node.js（18 以上）を2回使います（avatar DSL の bytecode 化と、設定 page への埋め込み）。ESP-IDF の image には Node.js がないので、この2つを host 側で先に実行し、container の中では結果を copy するだけの shim（`stackchan_idf/node`）を `node` として使います。

```bash
git clone https://github.com/ciniml/stackchan-idf.git firmware/third_party/stackchan-idf
cd firmware/third_party/stackchan-idf
git checkout 419385ef1b875137140085bd50d34dee331f30c2
git submodule update --init --recursive
bash tools/apply-m5-patches.sh

# Node.js の2工程を host で先に実行し、container 用の shim を置く
mkdir -p .hostnode
node tools/avatar_dsl/cli.mjs assets/default_face.avdsl .hostnode/default_face.avbc
node tools/avatar_dsl/inject.mjs components/wifi_config_service/web/settings_wifi.html \
  .hostnode/settings_wifi.html default=assets/default_face.avdsl \
  omega=assets/omega_mouth.avdsl aokko=assets/aokko_face.avdsl
cp ../../baselines/stackchan_idf/node .hostnode/node
cd ../../..

docker run --rm -v "$PWD/firmware:/fw" \
  -w /fw/third_party/stackchan-idf espressif/idf:v5.5.5 bash -c '
  export PATH=/fw/third_party/stackchan-idf/.hostnode:$PATH
  git config --global --add safe.directory "*"
  D="sdkconfig.defaults;sdkconfig.defaults.esp32s3;sdkconfig.defaults.cores3"
  idf.py -B build-cores3 -DSDKCONFIG=build-cores3/sdkconfig -DSDKCONFIG_DEFAULTS="$D" set-target esp32s3 &&
  idf.py -B build-cores3 -DSDKCONFIG=build-cores3/sdkconfig -DSDKCONFIG_DEFAULTS="$D" build'
```

構成は `BOARD=cores3` 相当（PSRAM Quad、flash 16MB、partition table は `partitions_main_16mb.csv`）です。初回の build は約 10分かかります。

### 書き込みと戻し方

stackchan-idf は独自の bootloader と拡張 partition table を使うので、前後で flash 全体を消します。前の firmware の NVS や SPIFFS が、stackchan-idf の storage / voice の領域に残らないようにするためです。

```bash
esptool --chip esp32s3 -p <PORT> erase-flash

# ファイルとアドレスは build-cores3/flash_args と同じ
cd firmware/third_party/stackchan-idf/build-cores3
esptool --chip esp32s3 -p <PORT> -b 921600 write-flash \
  --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin \
  0xd000 bootctl_main.bin 0x190000 exttab.bin 0x1a0000 stackchan_idf.bin
```

- 画面右上を tap して出る「範囲」tab を開いている間は torque が切れ、手で首を動かせます。Yaw と pitch の現在値が `Y: <raw> (<±deg>°) z=<zero> [min, max]°` の形で表示されます。「保存（再起動）」を押さない限り NVS は変わりません。
- stackchan-idf の角度と raw の変換は `raw = zero + deg × 16 / 5`（deg が正なら raw が増える）、既定の soft limit は yaw −40〜+40°、pitch −10〜+25° です。本プロジェクトの dispatcher は、この soft limit の内側で動かします。
- 終わったら、もう一度 `erase-flash` してから `jtalm_action` を書き込みます（[`../README.md`](../README.md)）。
