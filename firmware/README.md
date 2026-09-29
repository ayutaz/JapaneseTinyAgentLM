# firmware

M5Stack CoreS3（StackChan K151）向けの firmware です。実機の構成と計測結果は [`docs/hardware.md`](../docs/hardware.md) を参照してください。

| Directory | 内容 | License |
|---|---|---|
| `jtalm_eval/` | LM 評価用の最小 firmware（B3）。heap、Flash map、PSRAM / Flash mmap の帯域を `JTALM {json}` 形式で出力する。Servo と Wi-Fi は使わない | Apache-2.0 |
| `baselines/esp32_llm/` | [doryiii/esp32-llm](https://github.com/doryiii/esp32-llm) を CoreS3 で動かすための sdkconfig の overlay と patch（B2.5） | Apache-2.0（patch の対象は上流の MIT のコード） |
| `baselines/stackchan_idf/` | [ciniml/stackchan-idf](https://github.com/ciniml/stackchan-idf) を Docker で build するための Node.js の shim（B2） | Apache-2.0 |
| `tools/serial_capture.py` | Serial log の取得。reset、prompt への自動応答、終了条件を指定できる | Apache-2.0 |
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

### stackchan-idf（B2 の準備。書き込むと servo が動く）

**書き込みは、ユーザーが立ち会うときだけ行います。** 手順は [`docs/hardware.md`](../docs/hardware.md) §10 を参照してください。

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
