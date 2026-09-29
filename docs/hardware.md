# 対象ハードウェアと実機調査記録

最終更新: 2026-09-29

本文書は、開発に使う実機の構成と、初回調査（B0。Phase 0 の一部）で取得した情報を記録します。ラベルは [`README.md`](README.md) §7 の「記述の確度」に従います。

## 1. 対象機

| 項目 | 内容 | 確度 |
|---|---|---|
| 製品 | M5Stack 公式「M5 スタックチャン」、SKU **K151**（2026-05-08 発売） | 確認済み |
| 識別の根拠 | 本体ラベルの FCC ID `2AN3WM5STACKCHAN`（`2AN3W` は M5Stack Technology の grantee code）と、番号 `219-269152`（書式から技適番号と判断） | 確認済み（FCC の個別登録ページは未確認） |
| Main controller | M5Stack CoreS3 | 確認済み |
| 公式 firmware | [`m5stack/StackChan`](https://github.com/m5stack/StackChan)（ESP-IDF 系、`firmware/` は MIT License） | 確認済み |

有志が組み立てる SG90（PWM servo）版の Stack-chan ではありません。Servo はシリアルバス型です。

## 2. SoC / Flash / PSRAM（実機読み取り）

2026-09-29 に `esptool` v5.4.0 で読み取りました。

| 項目 | 値 | 確度 |
|---|---|---|
| Chip | ESP32-S3 (QFN56) revision v0.2、Dual Core + LP Core、240MHz、水晶 40MHz | 実測 |
| USB | Native USB-Serial/JTAG（VID `303A` / PID `1001`） | 実測 |
| Flash | 16MB、quad（4 data lines）、manufacturer `0x46` / device `0x4018`、3.3V | 実測 |
| PSRAM | Chip 内蔵なし。起動直後に PSRAM heap の空き 8,386,296 B を観測したため、外付け 8MB と判断 | 実測 |

### 操作上の注意

- 開発 PC から serial port を開くと、`rst:0x15 (USB_UART_CHIP_RESET)` で chip が reset されることがある。
- `esptool` は読み取りだけでも、接続時と終了時に chip を reset する。書き込みはしない。
- Firmware を書き込む前には、必ず §6 の手順で Flash 全体をバックアップする。

## 3. 胴体（K151）の構成

[M5Stack 公式資料](https://docs.m5stack.com/en/StackChan) と公式 firmware の `firmware/main/hal/hal_servo.cpp` から整理しました。

### Servo

| 項目 | Yaw（左右） | Pitch（上下） |
|---|---|---|
| 型番 | Feetech SCS0009 | Feetech SCS0009 |
| Servo ID | 1 | 2 |
| 公式 firmware の角度制限（0.1° 単位） | -1280〜1280（±128°） | 30〜870（3°〜87°） |
| 特記事項 | 連続回転（PWM mode）に対応 | Stall protection あり |

共通の仕様:

- 通信: UART1、1,000,000 bps、TX=`G6`、RX=`G7`、`SCSCL`（SCS protocol）
- Raw position は 0〜1000。1 step = 0.3125°。
- Servo の zero position は firmware が NVS に保存して較正する。
- Servo 電源は IO expander（PY32L020）の `VM_EN` で制御する。
- **符号規約:** 公式コードのコメントでは、yaw は -1.0 が左端、+1.0 が右端である。本プロジェクトの Action schema でも **yaw の正の値は右**とする。実機で確かめたところ（2026-09-29、§10）、**首をロボット自身の右へ回すと yaw の raw は減り**、上を向くと pitch の raw は増えた。中立（正面・水平）は yaw 460 / pitch 620（stackchan-idf の既定値）。

### その他の周辺機器

| 機能 | 部品 / 接続 |
|---|---|
| I2C | SCL=`G11`、SDA=`G12` |
| IO expander | PY32L020、`0x6F`（ADD_SEL=low、既定値） |
| バッテリー監視 | INA226、`0x41` |
| NFC | ST25R3916、`0x50` |
| タッチ（3 zone） | Si12T、`0x68` |
| 赤外線 | IR_SEND=`G5`、IR_REC=`G10` |
| その他 | RGB LED 12個、550mAh バッテリー |

## 4. 受領時の firmware（参考記録）

受領時に入っていた firmware は、sanoTTS-jp（TTS）の benchmark でした。TTS は本計画の対象外なので（[`roadmap.md`](roadmap.md) §1）、ここでは記録として最小限だけ残します。LM の開発には使いません。

### Firmware の識別

| 項目 | 値 |
|---|---|
| Project | `wifi`、version 1 |
| Build | 2026-09-27 23:03、ESP-IDF 5.5.5 |
| Framework | PlatformIO（macOS）の Arduino core と M5Unified |
| 内容 | sanoTTS-jp と Wi-Fi を同時に動かす heap benchmark。Servo 関連のコードは含まない |

### Partition table

| Name | Type / Subtype | Offset | Size |
|---|---|---:|---:|
| nvs | data / nvs | `0x9000` | 24 KiB |
| phy_init | data / phy | `0xF000` | 4 KiB |
| factory | app / factory | `0x10000` | 2,816 KiB（うち app image は 1,834 KiB） |
| dict | data / `0x41` | `0x2D0000` | 13,504 KiB（TTS 用の漢字読み辞書） |

LM の評価には自前の最小 firmware を使い、partition も自分で設計します（[`roadmap.md`](roadmap.md) §12 の B3）。

### Heap の推移（firmware の log 出力、単位 B）

| 段階 | 内部 SRAM の空き | 内部 SRAM の最大連続ブロック | 内部 SRAM の最小空き | PSRAM の空き |
|---|---:|---:|---:|---:|
| 起動直後 | 154,788 | 98,292 | 149,392 | 8,386,296 |
| `M5.begin` 後 | 149,408 | 98,292 | 143,980 | 8,384,940 |
| `tts.begin` 後 | 140,824 | 98,292 | 138,376 | 8,372,256 |
| `WiFi.mode(STA)` 後 | 92,588 | 51,188 | 92,168 | 8,367,620 |
| Wi-Fi scan 後 | 90,704 | 47,092 | 88,072 | 8,367,620 |
| 音声合成後 | 90,032 | 47,092 | 88,072 | 8,367,620 |

- 起動直後の値は、M5 の基本的な初期化だけの状態に近いので、LM の runtime が使える内部 SRAM の目安になります。
- Wi-Fi を有効にすると、内部 SRAM が約 48KB 減ります。LM の評価用 firmware では Wi-Fi を使いません。

## 5. 設計への影響

1. **内部 SRAM:** 受領時の firmware では、起動直後の空きは約 155KB、最大連続ブロックは約 98KB でした。当初は、重みを Flash から mmap し、KV cache と activation を PSRAM に置いて、内部 SRAM は数十 KB 以下に抑える計画でした。**実装（B4、§11）では、速さのために activation（3M で約 126KB）と tokenizer の作業領域（32KB）を内部 SRAM に置き、KV cache（f32、3M で 458,752 B）を PSRAM に置きました。** 自前の firmware では起動直後の内部 SRAM の空きが約 328KB あり（§8）、3M を読み込んだ後も約 140KB 残ります（[`architecture.md`](architecture.md) §10）。画面（M5Unified / M5GFX）と dispatcher を載せると、200件の処理の後で約 99KB（最大連続ブロック 57KB）になりました（§12）。
2. **Action:** Action schema は K151 の servo 仕様に合わせます。
   - LM はカテゴリ（`direction` / `amount`）だけを出力し、firmware の dispatcher が角度に変換する（[`architecture.md`](architecture.md) §7）。
   - yaw の正の値を右とする。実機では右へ回すと yaw の raw が減るので、dispatcher で符号を反転する（§10、2026-09-29 に確認）。
   - pitch は公式の 3°〜87° を中立位置からの相対値に変換する。
   - 連続回転は Action LM から使わせない。
3. **Firmware の基盤:** K151 では servo が SCS0009、電源制御が PY32L020 経由です。次の2つは、どちらもこの構成に対応しています。
   - 公式の `m5stack/StackChan`（ESP-IDF v5.5.4、MIT）
   - `stackchan-idf`（ESP-IDF v5.5.5 で検証、BSL-1.0）。README に、PY32 の Pin 0 で servo の VM 電源を入れ、200ms 待ってから bus を使う手順が記載されている。

   LM の評価には、自前の最小 firmware を使います（B3 の `jtalm_eval`、B4 の `jtalm_action`）。Action から servo を動かす dispatcher（A1）では、stackchan-idf の register の仕様を参考にして、SCS の driver を自前で書きました（§12）。

## 6. Flash のバックアップ

受領時の Flash 16MB 全体を、2026-09-29 に読み出しました。

| 項目 | 値 |
|---|---|
| ファイル | `backups/cores3/coreS3_full_backup_20260929.bin`（`.gitignore` で除外） |
| Size | 16,777,216 B |
| SHA-256 | `05abdb21deb07121377cdaeeacb85346c8f7007feac1b2935f94a35972e564c5` |
| 同じ場所に保存したもの | `partitions.bin`、serial log |
| NVS の中身 | `M5GFX`、`nvs.net80211`（`ap.sndchan`、`opmode`）、`phy` の較正データだけ。Wi-Fi の認証情報のキーは含まれていない |

バックアップの取得と書き戻しの手順:

```sh
# バックアップ（読み取りのみ）
uvx --from esptool esptool --chip esp32s3 -p <PORT> -b 921600 read-flash 0 0x1000000 <file>.bin

# 書き戻し
uvx --from esptool esptool --chip esp32s3 -p <PORT> write-flash 0 <file>.bin
```

バックアップには第三者のデータ（TTS の辞書）が含まれるため、Git や公開 artifact には含めません。

## 7. ESP-IDF の build 環境（B1、2026-09-29）

| 項目 | 内容 | 確度 |
|---|---|---|
| Image | `espressif/idf:v5.5.5`（digest `sha256:a9231d0697ab8f7517cc072e93b7c83e04907bfbfba80b6440d7dbbf90665cf2`、14.3GB） | 確認済み |
| `idf.py --version` | `ESP-IDF v5.5.5` | 実測 |
| Host | Windows 11、Docker Desktop（Engine 29.2.1） | 確認済み |
| 書き込み | Windows から `uvx --from esptool esptool`（v5 系）。Image 内の esptool（v4.12）は使わない | 確認済み |

Build は、`firmware/` を container に mount して行います。Git Bash から実行するときは、path の変換を止めるために `MSYS_NO_PATHCONV=1` を付けます。

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "C:/Users/<user>/.../JapaneseTinyAgentLM/firmware:/fw" -w /fw/jtalm_eval \
  espressif/idf:v5.5.5 idf.py build

# 書き込み（Windows 側。ファイルの一覧は build/flasher_args.json と同じ）
cd firmware/jtalm_eval/build
uvx --from esptool esptool --chip esp32s3 -p COM3 -b 921600 write-flash \
  --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x10000 jtalm_eval.bin
```

- `--flash-mode dio` は image header の値です。2nd stage bootloader が起動時に QIO へ切り替えます（log の `SPI Mode : QIO`、`flash io: qio`）。
- Serial log は `firmware/tools/serial_capture.py` で取ります（`uv run --no-project --with pyserial python firmware/tools/serial_capture.py --port COM3 --reset --seconds 30 --out <log>`）。`--reset` は DTR=low、RTS=high→low で chip を reset します。Port を開くだけでは reset されないことがありました。

## 8. LM 評価用の最小 firmware（B3、2026-09-29）

`firmware/jtalm_eval/`（Apache-2.0）。Wi-Fi、画面、servo は使いません。I/O は USB-Serial/JTAG の console だけです。GPIO は一切操作しません。

- 起動時に、device 情報、partition table、段階ごとの heap、PSRAM と Flash mmap の読み出し帯域を `JTALM {json}` の1行形式で出力する。
- Serial から `b` を送ると帯域の計測をやり直し、`h` を送ると heap を出力する。60秒ごとに heap を出力する。
- 設定: ESP32-S3 240MHz、Flash QIO 80MHz 16MB、PSRAM Quad 80MHz 8MB、data cache 64KB / line 64B、instruction cache 32KB、`-O2`（`CONFIG_COMPILER_OPTIMIZATION_PERF`）、FreeRTOS 100Hz。Cache の設定は esp32-llm と同じにした。

### Flash map（実測）

| Name | Type / Subtype | Offset | Size | 中身 |
|---|---|---:|---:|---|
| （bootloader） | — | `0x0` | — | 22,288 B |
| （partition table） | — | `0x8000` | — | 3,072 B |
| nvs | data / nvs | `0x9000` | 24 KiB | |
| phy_init | data / phy | `0xF000` | 4 KiB | |
| factory | app / factory | `0x10000` | 1,984 KiB | app image 193,376 B（9.5%） |
| model | data / `0x40` | `0x200000` | 14,336 KiB | LM の重み。`esp_partition_mmap` で読む |

- `model` の 14MB 全体を1回の `esp_partition_mmap` で map できた（48µs、仮想 address `0x3C830000`）。PSRAM 8MB を heap に入れた状態でも、仮想 address 空間は足りている。
- `model` partition は `0x200000`（64KB の MMU page 境界）に置いた。

### Heap（実測、単位 B）

内部 SRAM は `MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT` の値です。

| 段階 | 内部 SRAM の空き | 内部 SRAM の最大連続ブロック | 内部 SRAM の最小空き | PSRAM の空き | PSRAM の最大連続ブロック |
|---|---:|---:|---:|---:|---:|
| `app_main` の開始直後 | 335,663 | 270,336 | 303,632 | 8,386,192 | 8,257,536 |
| 計測用 buffer の確保後（内部 32KB、PSRAM 4MB） | 302,307 | 237,568 | 270,044 | 4,191,884 | 4,128,768 |
| Model partition の mmap 後 | 301,995 | 237,568 | 269,964 | 4,191,884 | 4,128,768 |
| 計測後の idle（buffer を解放） | 334,847 | 270,336 | 269,964 | 8,386,192 | 8,257,536 |

- 起動直後の内部 SRAM の空きは約 328KB、最大連続ブロックは約 264KB。§4 の受領時 firmware（Arduino + M5Unified、約 155KB / 98KB）より大きいのは、Arduino、M5Unified、TTS の常駐分がないためと考えられる（推測）。
- 画面、servo、M5Unified を載せると、この値から減る。載せた状態の値は §12（A1〜A3）にある。
- Flash の mmap は heap を消費しない（312 B の差は計測コードの誤差の範囲）。
- Main task の stack（8KB）の high-water mark は 6,404 B の余り。

### 読み出し帯域（実測）

32-bit の word を4本の累積和で順に読む loop（`sum_words`）。Stream は 4MB（data cache 64KB を大きく超える）を4回、hot は 32KB を繰り返し読む。

| 計測 | MB/s |
|---|---:|
| PSRAM の順次読み出し（4MB × 4） | **32.8** |
| Flash mmap の順次読み出し（4MB × 4） | **31.2** |
| PSRAM → 内部 SRAM の `memcpy`（32KB 単位、4MB） | 32.8 |
| Flash mmap → 内部 SRAM の `memcpy`（32KB 単位、4MB） | 31.4 |
| Cache に載る 32KB の繰り返し（内部 SRAM、PSRAM、Flash mmap のいずれも） | 425.5 |

- 別の起動で2回測り直しても、差は 0.01% 以下だった（`runs/device/b3_rerun_20260929T065653Z.log`）。
- Quad PSRAM（80MHz）と QIO Flash（80MHz）の順次読み出しは、どちらも約 31〜33 MB/s で、ほぼ同じ。理論値（4bit × 80MHz = 40 MB/s）の約 8割。
- ESP32-S3 では Flash と PSRAM が同じ MSPI bus を共有するので、2つを同時に読んでも帯域は足し算にならない（推測。未計測）。
- **設計への示唆:** 重みは Flash から mmap して読んでも、PSRAM に copy して読むのとほぼ同じ速さになる。PSRAM を KV cache に空けられるので、重みは mmap で読む方針（[`architecture.md`](architecture.md) §10）でよい（B4 で採用。activation は速さのために内部 SRAM に置いた）。
- 重みを毎 token 全部読む前提では、速度の上限は「32 MB/s ÷ 重みの byte 数」になる。例: INT8 で 3.35MB なら約 9.8 tok/s、INT4 の 5M（約 2.6MB）なら約 12 tok/s。

計測の生 log は `runs/device/b3_boot_20260929T064117Z.log`（Git の管理外）。Firmware の ELF SHA-256 の先頭は `19b3d95c6`。

## 9. 既存 runtime による基準値（B2.5、2026-09-29）

[doryiii/esp32-llm](https://github.com/doryiii/esp32-llm)（commit `c6c647f7bfbb`、2026-03-19）を CoreS3 向けに調整して動かしました。Clone は `firmware/third_party/`（Git の管理外）に置き、CoreS3 向けの差分は `firmware/baselines/esp32_llm/` に置いています。

### License

| 対象 | License | 確度 |
|---|---|---|
| Source（`main/*.c`、`*.h`） | MIT（各ファイルの header。Copyright 2023 Andrej Karpathy、2026 Dory） | 確認済み |
| Repository 全体 | LICENSE ファイルはない | 確認済み |
| Model / tokenizer（`spiffs_data/` の4ファイル） | Repository に同梱。別途の download は不要。個別の license 表記はない。stories260K は karpathy/tinyllamas 由来（README の記載） | 確認済み |

LICENSE ファイルがなく、model の license も明記されていないので、本プロジェクトの成果物には取り込みません。基準値の計測だけに使います。

### CoreS3 向けの変更

| 変更 | 理由 |
|---|---|
| PSRAM を Octal から Quad に変更（`sdkconfig.cores3`） | 上流は Waveshare ESP32-S3-LCD-1.9（Octal PSRAM）向け。CoreS3 は Quad |
| Flash mode を QIO に変更 | CoreS3 の Flash は quad |
| `main.c` の GPIO14 の操作（上流の board の LCD backlight）を削除 | CoreS3 では GPIO14 は mic codec の I2S data 入力なので、出力に設定しない |
| `generate()` に forward だけの時間の計測を追加 | 上流の tok/s は、token ごとの `vTaskDelay(1)`（100Hz で最大 10ms）と serial 出力を含むため |

Servo（UART1、`G6` / `G7`）を触るコードは、上流にも変更後にもないことを source で確認しました。

### 結果（stories3M INT8、実測）

Model: `stories3M-q80.bin`（dim 192、hidden 512、6 layer、6 head / 2 KV head、vocab 4,096、seq_len 512、group size 64、3,352,576 B、SHA-256 `7d761c87…c0376d`）。Prompt は空、temperature 1.0、top-p 0.9、生成は BOS まで（最大 512）。重みは SPIFFS から PSRAM に読み込んで使う（mmap ではない）。

| Run | 生成 token 数 | 上流の tok/s（loop 全体） | Forward だけの tok/s | ms/token（forward） |
|---|---:|---:|---:|---:|
| 1 | 200 | 6.25 | 6.74 | 148.3 |
| 2 | 174 | 6.59 | 7.15 | 139.9 |
| 3 | 217 | 6.04 | 6.50 | 153.8 |

| 項目 | 値 |
|---|---|
| Model の読み込み（SPIFFS → PSRAM） | 約 1.5 s |
| 内部 SRAM の使用量（activation、attention score、logits など） | 40,396 B（空き 337,663 → 297,267） |
| PSRAM の使用量（重み 3.35MB と、FP32 の KV cache 1.57MB） | 4,925,452 B（空き 8,386,160 → 3,460,708） |
| 生成文 | 英語の短い物語として自然（3回とも） |

- **上流の約 12 tok/s（Octal PSRAM）に対し、CoreS3（Quad PSRAM）では約 6.0〜6.6 tok/s で、約半分。**
- 帯域の上限（§8 の 32.8 MB/s ÷ 3.35MB ≒ 9.8 tok/s）の約 7割。残りは attention などの計算と見られる（推測）。生成が長くなるほど ms/token が増える傾向がある。
- 生 log は `runs/device/b25_int8_20260929T064951Z.log`（Git の管理外）。

### 結果（stories260K FP32、実測）

起動と 100 token 以上の連続生成を確認するための run です。Model: `stories260K.bin`（dim 64、hidden 172、5 layer、8 head / 4 KV head、vocab 512、seq_len 512、1,056,540 B、SHA-256 `b0a507e7…9f2696`）。FP32 の engine（`llm.c`）は `espressif/esp-dsp` の matmul を使う。条件は INT8 と同じ。

| Run | 生成 token 数 | 上流の tok/s（loop 全体） | Forward だけの tok/s | ms/token（forward） |
|---|---:|---:|---:|---:|
| 1 | 406 | 12.40 | 13.36 | 74.9 |
| 2 | 330 | 15.18 | 16.62 | 60.2 |
| 3 | 453 | 11.14 | 11.90 | 84.0 |

| 項目 | 値 |
|---|---|
| Model の読み込み（SPIFFS → PSRAM） | 約 0.5 s |
| 内部 SRAM の使用量 | 20,984 B（空き 337,919 → 316,935） |
| PSRAM の使用量（重み 1.06MB と、FP32 の KV cache 0.66MB） | 1,736,716 B（空き 8,386,160 → 6,649,444） |
| 生成文 | 英語の物語の形は保つが、内容の破綻が多い（model の規模どおり） |

- 上流の約 30 tok/s に対し、11〜15 tok/s。生成長が長い run ほど遅く、長さへの依存が INT8 より強い。KV cache（seq_len 512 で約 650KB）は PSRAM にある（PSRAM の使用量の内訳から確認）。生成が進むほど PSRAM 上の attention の読み出しが増え、それが律速になっていると見られる（推測）。
- 生 log は `runs/device/b25_fp32_20260929T071140Z.log`（Git の管理外）。
- `espressif/esp-dsp` は Component Registry から build 時に取得した（ユーザーの承認済み、Apache-2.0）。

### 本プロジェクトへの示唆

- 3M 級の INT8 で、CoreS3 の実用速度は **約 6〜7 tok/s**。本プロジェクトの tokenizer（M4）では、JSON の固定の断片を1 token にまとめているので、出力は `look` 1個で 7 token、`[]` で 1 token（平均 4.7 token）になる。生成だけなら約 0.2〜2 秒、入力（約 10 token）を1 token ずつ処理する場合は合計で約 2〜3 秒と見積もれる（推測）。→ B4 の実測では、入力のまとめ処理と2 core の併用により、3M INT4 で1件の中央値 1.08〜1.15 秒になった（§11）。
- 5M を INT8 で載せると、重みの読み出しだけで上限が約 6 tok/s まで下がる。**INT4 化と、重みの読み出し量を減らす工夫（語彙の縮小、embedding と出力層の共有）が速度に直結する。**
- esp32-llm は KV cache を FP32 で PSRAM に置く（3M、seq_len 512 で 1.57MB）。Action の入出力は短い（M4 の系列は最大 52 token）ので、seq_len を実際の長さに合わせて小さくし、KV cache を INT8 / FP16 にすれば、内部 SRAM に置ける可能性がある（推測）。
- Prompt（発話）部分の処理は、1 token ずつ forward するのではなく、まとめて処理（batch prefill）して重みの読み出しを共有しないと、入力長に比例して遅くなる。

## 10. Servo の確認（B2、2026-09-29 に実施）

[ciniml/stackchan-idf](https://github.com/ciniml/stackchan-idf)（commit `419385ef1b87`、v0.15.0-alpha.2、2026-09-24）を使いました。**起動するとすぐ servo が動くので、書き込みはユーザーの立ち会いのもとで行いました。** 2026-09-29 に、ユーザーの立ち会いのもとで書き込んで確認し、確認の後は LM の firmware に書き戻しています（下の「結果」）。

### Build（2026-09-29、確認済み）

| 項目 | 値 |
|---|---|
| 構成 | `BOARD=cores3`（`sdkconfig.defaults;sdkconfig.defaults.esp32s3;sdkconfig.defaults.cores3`）。PSRAM Quad、Flash 16MB、partition table は `partitions_main_16mb.csv` |
| App | `stackchan_idf.bin` 3,737,680 B（`main` 領域 5MiB の 71%）、SHA-256 `82639eb8…1d65704` |
| 書き込むもの（`build-cores3/flash_args`） | `0x0` bootloader（独自。bootctl を読んで起動先を選ぶ）、`0x8000` partition table、`0xD000` bootctl（起動先 = main）、`0x190000` exttab（拡張 partition table）、`0x1A0000` app |
| 所要時間 | 約 10分（Docker、初回） |

上流の build 手順との違いは2点です。

1. 上流の README の手順どおり、`tools/apply-m5-patches.sh` で M5Unified に1行の patch を当てた。
2. Build の途中で Node.js（18 以上）を2回使う（avatar DSL の bytecode 化と、設定 page への埋め込み）。ESP-IDF の image には Node.js がなく、上流の CI は `apt-get install nodejs` で入れている。今回は新たな取得を避けるため、Windows 側の Node v24 でこの2つを先に実行し、container 内では結果を copy するだけの shim（`firmware/baselines/stackchan_idf/node`）を `node` として使った。改行コードが CRLF でも LF でも bytecode が一致することは確認した。

### License と依存（確認済み）

| 対象 | Version | License |
|---|---|---|
| 自前のソース（`components/board`、`components/scs_servo`、`main` など） | — | BSL-1.0（`LICENSE`、README、各ファイルの SPDX header） |
| Submodule: m5stack/M5Unified | 0.2.17 | MIT |
| Submodule: m5stack/M5GFX | 0.2.23 | MIT |
| Submodule: TartanLlama/expected | v1.3.1 | CC0 1.0 |
| Managed components（Component Registry、cores3 の build で取得した13個） | — | Apache-2.0: cmake_utilities、esp_jpeg、esp_websocket_client、esp32-camera、esp-dsp、esp-now、led_strip、mdns。MIT: cjson、dl_fft。Espressif MIT: esp-sr、esp_audio_codec（Espressif Modified MIT）。ISC: quirc |
| HMM voice "Mei"、hts_engine API | — | CC BY 3.0、Modified BSD（`THIRD_PARTY_NOTICES.md`）。今回は voice の data を書き込まない |

Submodule と managed components は、ユーザーの承認を得て取得しました（2026-09-29）。いずれも `firmware/third_party/`（Git の管理外）にあります。

### stackchan-idf の servo まわりの仕様（source で確認済み）

| 項目 | 値 |
|---|---|
| 角度と raw の変換 | `raw = zero + deg × 16 / 5`（1 step = 0.3125°）。**deg が正なら raw が増える** |
| 既定の zero | yaw 460、pitch 620（M5 の base 向け。NVS の `servo-limits` で変更可能） |
| 既定の soft limit | yaw −40〜+40°、pitch −10〜+25°（zero からの相対） |
| 起動時の動き | Servo の電源を入れて ping したあと、(yaw, pitch) = (0°, 0°) へ移動する。その後、10〜20秒ごとに soft limit 内の random な姿勢へ動く |
| 画面の UI | 画面の右上を tap すると tab が出る。「操作」tab の1行目は torque の脱力 / 復帰、2行目は (0°, 0°) への centering |
| 「範囲」tab | この tab を開いている間は **torque が切れ**、手で首を動かせる。Yaw と pitch の現在値が `Y: <raw> (<±deg>°) z=<zero> [min, max]°` の形で表示される。「保存（再起動）」を押さない限り NVS は変わらない |
| その他の起動時の動作 | 起動音（アルペジオ）、random な babble 音声、BLE advertising。Wi-Fi は SSID を設定しない限り接続しない |

### 確認の手順（所要 5〜10分）

目的は2つです。

1. 首を**ロボット自身の右**に向けたとき、yaw の raw が増えるか減るかを知る。
2. 顔が正面を向いて水平になるときの、yaw と pitch の raw を知る。

**準備（ユーザー）:** 本体を平らな机に置き、首の周りに物を置かない。USB で PC につなぐ。非常時は、画面右上を tap →「操作」→「サーボ（脱力/復帰）」で torque を切る。それでも止まらなければ USB を抜き、電源 button を長押しして電源を切る。

**1. 書き込み（Claude Code が実行）**

```sh
# バックアップの確認
sha256sum backups/cores3/coreS3_full_backup_20260929.bin   # 05abdb21…e564c5 であること

# Flash 全体を消す。前の firmware の NVS や、esp32-llm の SPIFFS が
# stackchan-idf の storage / voice の領域に残らないようにする
uvx --from esptool esptool --chip esp32s3 -p COM3 erase-flash

# 書き込む（ファイルとアドレスは build-cores3/flash_args と同じ）
cd firmware/third_party/stackchan-idf/build-cores3
uvx --from esptool esptool --chip esp32s3 -p COM3 -b 921600 write-flash \
  --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin \
  0xd000 bootctl_main.bin 0x190000 exttab.bin 0x1a0000 stackchan_idf.bin
```

書き込みが終わると chip が reset され、**すぐに servo が動き始める**。そのため、ユーザーが本体の前にいることを確認してから書き込む。

**2. Log の取得を開始（Claude Code）**

```sh
uv run --no-project --with pyserial python firmware/tools/serial_capture.py \
  --port COM3 --reset --seconds 600 --out runs/device/b2_servo_check.log
```

Log に `yaw (id=1) ping OK` と `pitch (id=2) ping OK` が出ることを確認する。

**3. 起動直後の姿勢を見る（ユーザー）**

起動音のあと、首が (0°, 0°)、つまり raw (460, 620) に動く。次を記録する。

- 顔が正面を向いているか。右か左にずれているなら、どちらに何度くらいか。
- 顔が水平か。上か下を向いているなら、どちらに何度くらいか。

**4. 「範囲」tab で手で動かす（ユーザー）**

10〜20秒たつと random な動きが始まる。画面の右上を tap し、「範囲」tab を開く。この tab を開くと torque が切れる。

1. 首をゆっくり**ロボット自身の右**（ロボットと向かい合った人から見ると左）へ回す。`Y:` の raw と deg が増えるか減るかを記録する。
2. 左へ回し、逆向きに変わることを確認する。
3. 顔を上に向ける。`P:` の raw が増えるか減るかを記録する。
4. 顔が正面を向き、画面が垂直（水平な視線）になる位置で手を止める。そのときの `Y:` と `P:` の raw を記録する。
5. **「保存（再起動）」は押さない。** 別の tab に移ると torque が戻り、首が目標の姿勢へ動く。

**5. 元の firmware に戻す（Claude Code）**

NVS と bootctl の領域を消し、B3 の firmware（§8）を書き込みます。bootloader も標準のものに戻ります。（2026-09-29 の実施では、Flash 全体を `erase-flash` で消してから、B4 の `jtalm_action` と v0.4 の 3M INT4 を書き込みました。手順は [`firmware/README.md`](../firmware/README.md)。）

```sh
uvx --from esptool esptool --chip esp32s3 -p COM3 erase-region 0x9000 0x6000
cd firmware/jtalm_eval/build
uvx --from esptool esptool --chip esp32s3 -p COM3 -b 921600 write-flash \
  --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x10000 jtalm_eval.bin
```

### 結果（2026-09-29、ユーザーの立ち会いのもとで実施）

| 項目 | 結果 | 確度 |
|---|---|---|
| Servo の応答 | `yaw (id=1) ping OK`、`pitch (id=2) ping OK`（log は `runs/device/b2_servo_check.log`） | 実測 |
| 起動直後の姿勢（raw 460 / 620） | 正面で水平 | 実測（目視） |
| 首をロボット自身の右へ回したとき | yaw の raw が**減る** | 実測（目視） |
| 顔を上に向けたとき | pitch の raw が**増える** | 実測（目視） |
| 中立（正面・水平）の raw | yaw 460、pitch 620（既定値のまま） | 実測（目視） |

- **dispatcher での変換:** Action の「右」は yaw の raw を減らす向き、「上」は pitch の raw を増やす向きになる。1 step は 0.3125° なので、yaw は `raw = 460 − deg × 16 / 5`（deg は右が正）、pitch は `raw = 620 + deg × 16 / 5`（deg は上が正）で求める。
- 確認の後、Flash 全体を消して `jtalm_action`（v0.4 の 3M INT4、confidence gate 0.970）に書き戻した。3つの依頼文で正しく応答することを確認した。NVS は消したので、stackchan-idf の設定は残っていない。

### 結果の使い方（確定）

- 右へ回すと raw が**減った**ので、dispatcher で yaw の符号を反転する。Action schema の「yaw の正 = 右」（[`architecture.md`](architecture.md) §7）は変えない。
- この個体の中立位置（yaw の中央、pitch の水平）は yaw 460 / pitch 620（stackchan-idf の既定値）。公式 firmware の pitch の範囲（3°〜87°）との対応は、この raw を基準にして換算する。
- 変換式は上の「dispatcher での変換」のとおり。dispatcher は A1 で実装した（§12）。実機で首を動かす確認は、まだ行っていない（§12 の手順。ユーザーの立ち会いが必要）。

## 11. Action LM の実機での実行（B4、2026-09-29）

M6 の C runtime（`runtime/host/`）を、firmware `firmware/jtalm_action/`（Apache-2.0）で CoreS3 に載せました。LM の source は copy せず、`runtime/host/` の `model.c`、`tokenizer.c`、`grammar.c` をそのまま build します（`-DJTLM_ACC=float -ffp-contract=off`）。Wi-Fi、画面、servo は使いません。GPIO も操作しません。作業は 09:55〜11:53 UTC。

### 構成

| 項目 | 内容 | 確度 |
|---|---|---|
| Firmware | `jtalm_action`（ELF SHA-256 の先頭 `12c755445`。confidence gate を加えた版は `bf5d82461`）。ESP-IDF v5.5.5、gcc 14.2（`esp-14.2.0_20260121`）、`-O2`。Cache と clock は §8 と同じ（240MHz、data cache 64KB / line 64B、Flash QIO 80MHz、PSRAM Quad 80MHz） | 確認済み |
| Flash map | §8 と同じ partition table。app は `0x10000`（246KB）、`.jtlm` は `model` partition（`0x200000`、14MB）に esptool で直接書く。起動時に partition 全体を1回で mmap（`0x3C830000`）し、image をそのまま `jtlm_model_init` に渡す。起動時に image の SHA-256 を計算して log に出す | 実測 |
| 入出力 | USB-Serial/JTAG の console（driver 経由）。1行の UTF-8 が1件の発話。応答は `JTALM {"t":"gen",...}` の1行（出力、生成した id、prompt の id、tokenize / prefill / decode / 合計の時間）。`!` で始まる行は command（`firmware/README.md`） | 確認済み |
| 生成 | Action schema v0 の grammar 付きの greedy（host の `--grammar` と同じ）。その後に confidence gate（既定 0.970）をかける | 確認済み |
| Task | LM の task を core 1、行列積を半分受け持つ worker を core 0 に置く | 確認済み |
| 状態の置き場所 | KV cache（f32、`max_seq_len` 128 の分）は PSRAM、残り（16 token 分の activation、attention の score、logits）は内部 SRAM | 実測 |
| 5M の FP32 | 20.5MB で `model` partition（14MB）に入らないので測っていない | 確認済み |

### 実機と host の一致（実測）

評価セット（`datasets/action/v0/eval.jsonl`）の先頭 200件を送り、host の runtime（`runtime/host/build/jtalm --grammar`、`double` の累積。Python と 1,189件すべてで一致することを確認済み）の出力と比べました。

| model | 重み | 生成した id が一致 | 出力の文字列が一致 |
|---|---|---:|---:|
| 3M | FP32 | 200 / 200 | 200 / 200 |
| 3M | INT8 | 200 / 200 | 200 / 200 |
| 3M | INT4 | 200 / 200 | 200 / 200 |
| 5M | INT8 | 200 / 200 | 200 / 200 |
| 5M | INT4 | 200 / 200 | 200 / 200 |

- 実機の出力は host の C、Python（`jtalm.model.decode.greedy`）と1件残らず同じなので、完全一致の率も [`runtime/host/README.md`](../runtime/host/README.md) の表の値（3M INT4 で 84.78% など）がそのまま実機の値になる。
- 200件のうち 21件は prompt が 16 token を超え、prefill を2回に分けて処理する経路も通った。
- 使った model は M4 の checkpoint（`runs/vast/train_action_v0-20260929T054319Z/artifacts/m4/{3m,5m}/best.pt`）。Image の SHA-256 の先頭は、3M が FP32 `de127de6c45ccb4e`、INT8 `a082374abf978e43`、INT4 `692604ceab4edd88`、5M が INT8 `18b912ffe5a76846`、INT4 `9645841b3a3b1fe1`。

### 採用モデル（v0.4 の 3M）と confidence gate（実測）

採用した v0.4 の 3M（`runs/vast/train_action_v04-20260929T095441Z/artifacts/v04/3m/best.pt`。構成と tokenizer は M4 と同じ）を INT4 / INT8 で書き出し、confidence gate を入れた firmware で確かめました。

- **Confidence gate:** 生成した token の確率の最小値（`min_prob`。grammar で制約する前の確率）が閾値より小さいと、出力を `[]` にする（`jtalm.model.evaluate` の `gate` と同じ比較）。閾値は既定 0.970 で、`CONFIG_JTALM_GATE_PERMILLE`（千分率）で変えられる。応答の行には、gate の後の `output` と、前の `raw` の両方を出す。

| 対象 | 件数 | 生成した id | gate 前の出力 | gate 後の出力 | gate で `[]` にした件数 |
|---|---:|---:|---:|---:|---:|
| INT4（image `11e80a93ac791c60`） | 評価セット全体 1,189 | 1,189 一致 | 1,189 一致 | 1,189 一致 | 71 |
| INT8（image `1237ab25a85fab54`） | 先頭 200 | 200 一致 | 200 一致 | 200 一致 | 12 |

- 比較相手は host の C（`double` の累積）。host の C の出力は、Python（`best_q4_g64.pt` / `best_q8_g64.pt` の `grammar`）と 1,189件すべてで一致した（`-DJTLM_ACC=float` でも同じ）。
- **実機の INT4 ＋ gate の出力を評価すると、完全一致 94.45%、critical error 0.59%。** Python（`jtalm.model.evaluate --modes gate`）の 94.4% / 0.6% と同じ値。Gate をかけない場合は 94.28% / 2.02%。
- 実機の出力を Python の `gate` の予測（`v04/3m/best_q4_g64.pt`）と直接比べても、gate 後の出力と gate 前の出力は 1,189件すべて一致した（先頭 200件では 200 / 200、gate で `[]` にしたのは 11件）。実機と host の `min_prob` の差は最大 1.4e-5 で、gate の判定が host（`double`）や Python と食い違った例はない。0.970 に最も近い値は 0.970307。
- `min_prob` が 0.970 から 1e-4 以内の例は1件もなく、C と Python の確率のわずかな差（最大 1e-5 程度）で gate の判定が変わるおそれはない。Python が validation で選んだ閾値（INT4 で 0.97004）と 0.970 のどちらでも、評価セットの結果は同じ。
- 速度は M4 の 3M INT4 と同じ（decode 105.4 ms/token、prefill 45.4 ms/token）。評価セット全体（prompt 平均 14.8 token、生成 平均 5.5 token）で、1件の latency は中央値 1,075ms、p90 1,859ms、最大 4,134ms。出力が `[]` の件は中央値 724ms。先頭 200件だけでは中央値 1,222ms、p90 1,434ms。
- 作業の終わりに、実機はこの firmware（`bf5d82461`）と v0.4 の 3M INT4 の状態にした（その後、A1〜A3 の firmware に更新した。§12）。

### 速度（実測）

評価セットの先頭 200件。1件あたりの prompt は平均 11.97 token（`<s>`、`<act>`、`<out>` を含む。最小 4、最大 27）、生成は平均 6.2〜6.8 token（`</s>` を含む。最大 14）。Prefill は prompt の全 token の処理、decode は生成の2 token 目以降の処理（1 token ずつ）。「帯域の上限」は、重みの byte 数を §8 の 31.2 MB/s で読むのにかかる時間です。

| model | 重み | 重みの byte 数 | decode（ms/token） | decode（tok/s） | 帯域の上限（ms/token） | prefill（ms/token） | 1件の latency の中央値（ms） | p90（ms） | 最大（ms） |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 3M | FP32 | 12.6MB | 410.7 | 2.4 | 404 | 62.8 | 3,488 | 4,107 | 6,618 |
| 3M | INT8 | 3.26MB | 115.3 | 8.7 | 104 | 49.3 | 1,273 | 1,762 | 2,511 |
| **3M** | **INT4** | **1.68MB** | **104.5** | **9.6** | 54 | **45.8** | **1,153** | **1,532** | 2,288 |
| 5M | INT8 | 5.22MB | 178.7 | 5.6 | 167 | 78.0 | 1,991 | 2,409 | 3,659 |
| 5M | INT4 | 2.69MB | 161.1 | 6.2 | 86 | 72.0 | 1,793 | 2,234 | 3,359 |

- **3M INT4 で、1件の応答は中央値 1.15 秒、p90 1.53 秒。** 何もしない（`[]`）応答は中央値 0.65 秒。内訳の目安は、prefill（約 12 token をまとめて）が約 0.5 秒、生成が 1 token あたり約 0.1 秒。
- Tokenize は1件あたり平均 2.2ms、state の初期化は 1ms 未満で、どちらも無視できる。
- FP32 と INT8 の decode は帯域の上限に近い（FP32 は 98%、INT8 は 90%）。INT4 は上限の約 2倍かかっていて、演算（INT4 の復元と積和で 1 weight あたり約 11 命令。disassembly で確認）が律速になっている。そのため INT4 の decode は INT8 より約 10% 速いだけ。
- **esp32-llm（§9、stories3M INT8、3.35MB）の forward だけで 6.5〜7.1 tok/s（140〜154 ms/token）に対し、3M INT8 の decode は 8.7 tok/s（115 ms/token）で、約 1.2〜1.3倍。** 重みの byte 数はほぼ同じ（3.26MB と 3.35MB）。Prompt も含めた forward 全体（prompt と生成の token の合計 ÷ 時間）では、3M INT8 が 14.1 tok/s、INT4 が 15.4 tok/s。
- 5M は 3M より 1件あたり約 0.6〜0.7 秒遅い。M4 の時点の精度も 3M の方が高い（[`roadmap.md`](roadmap.md) §12）。

### メモリ（実測、単位 B）

内部 SRAM は `MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT` の値です。

| 段階 | 内部 SRAM の空き | 内部 SRAM の最大連続ブロック | 内部 SRAM の最小空き | PSRAM の空き |
|---|---:|---:|---:|---:|
| `app_main` の開始直後 | 317,899 | 262,144 | 285,868 | 8,386,192 |
| LM task の開始（task 2つの stack、計 22KB の確保後） | 294,651 | 245,760 | 262,620 | 8,386,192 |
| 3M の読み込み後 | 140,219 | 90,112 | 108,188 | 7,919,240 |
| 5M の読み込み後 | 90,043 | 39,936 | 58,012 | 7,984,776 |

| 確保するもの | 3M | 5M | 置き場所 |
|---|---:|---:|---|
| KV cache（f32、128 token 分） | 458,752 | 393,216 | PSRAM |
| Activation（16 token 分）、attention の score、logits | 125,952 | 176,128 | 内部 SRAM |
| Tokenizer の作業領域 | 32,768 | 32,768 | 内部 SRAM |
| 最初の step の logits の控え（診断用） | 8,192 | 8,192 | PSRAM |
| 重み（`.jtlm`） | 0（mmap） | 0（mmap） | Flash |

- 1件目の処理の後は、空きと最小空きが読み込み直後より 220 B 減っただけで、その後は変わらない（token ごとの確保はない）。最小空きが空きより約 32KB 少ないのは、起動直後からの値（`app_main` の開始時点ですでに 32KB 少ない）で、LM の処理によるものではない。
- LM task の stack（16KB）の余りは 13.5KB。
- 5M は内部 SRAM の最大連続ブロックが約 40KB まで減る。画面や servo を載せるなら、`-DJTLM_BATCH=8` で activation を半分（5M で約 82KB 減）にできる（結果は変わらない。速度への影響は未計測）。

### 速くするために行ったこと（3M、実測）

どの変更も、計算の値を1 bit も変えないものに限りました（host の 200件 × 6 model の出力が byte 単位で同じであること、実機の出力が host と同じであることを、変更のたびに確かめた）。3M INT8、評価セットの先頭 20件（移植直後だけは 10件）。

| 段階 | prefill（ms/token） | decode（ms/token） | 1件の中央値（ms） | p90（ms） |
|---|---:|---:|---:|---:|
| 移植直後（host の code のまま、1 core、1 token ずつ。arena はすべて PSRAM）※10件 | 423 | 428 | 4,899 | 7,248 |
| 内積の kernel の修正、activation を内部 SRAM へ | 166 | 171 | 2,425 | 3,702 |
| ＋ prefill のまとめ処理 | 88 | 171 | 1,393 | 2,456 |
| ＋ 2 core（まとめ処理なし） | 110 | 116 | 1,616 | 2,475 |
| **＋ まとめ処理と 2 core（採用）** | **49** | **116** | **794** | **1,507** |

- **内積の kernel:** 移植直後は、部分和の配列が入力と alias しうるため、積和のたびに部分和を memory に書き戻していた（disassembly で確認）。部分和を local 変数に移し、量子化した重みは1個ずつ f32 に戻してすぐ掛けるようにした。
- **Prefill のまとめ処理:** prompt を最大 16 token まとめ、重みの各行を1回読んで全 token に掛ける。Prompt の途中の token では出力 head を計算しない。
- **2 core:** 行列積の出力の行を、core 1（LM task）と core 0（worker）で半分ずつ計算する。同期は task notification。
- 試して採用しなかったもの:

| 試したこと | 結果 | 判断 |
|---|---|---|
| INT4 の復元を、group ごとの 16 値の表引きにする（命令数は約 11 → 7.5 / weight） | decode が 105 → 113 ms/token（1 core では 191 → 202）で、かえって遅い（表の load の待ちと見られる。推測） | 戻した |
| DCache の autoload（連続した line の先読み。ESP-IDF の既定では off）を model の領域で有効にする | 1 step の forward が、3M INT4 で 109 → 104ms（1 core では 198 → 189ms）。FP32 は 407 → 407ms で変わらない | 効果が約 5% と小さく、ESP-IDF が公開していない cache の register を直接書くので、既定は off のまま（`!autoload` で試せる） |

- `expf`（SiLU と softmax で使う）は1回 1.12µs で、3M の decode では1 token あたり約 6ms（約 6%）。newlib の `expf` は内部で double を使い、ESP32-S3 では double がソフトウェアで計算されるため。値を変えずに速くする方法はないので、そのままにした。
- 試していないもの: `-O3`、hot な関数の IRAM への配置、FMA（`madd.s`。丸めが1回になり PyTorch と値が変わる）、PIE の SIMD（整数だけなので activation の量子化が必要になり、値が変わる）。

### 本プロジェクトへの示唆

- **3M（INT4 または INT8）なら、実機で1件あたり約 1.1〜1.3 秒（p90 約 1.5〜1.9 秒）で応答できる。** 採用した v0.4 の 3M INT4 と gate の組み合わせで、実機でも完全一致 94.45%、critical error 0.59%（Python と同じ）。 実用の目安としては使える範囲（推測）。
- 3M の decode は、INT8 では flash の帯域、INT4 では演算が律速で、どちらも約 0.1 秒 / token。これ以上は、生成する token 数を減らす（Action の表現を短くする）か、層や語彙を小さくするのが効く（推測）。
- 5M は 3M より約 0.6 秒遅く、内部 SRAM にも余裕がない。精度でも 3M を上回らなかったので、**Action LM は 3M INT4 に決定した**（2026-09-29、[`roadmap.md`](roadmap.md) §12）。
- 最も効いたのは prefill のまとめ処理で、prefill は 166 → 88 ms/token、2 core と合わせて 49 ms/token（約 1/3.4）になった。発話が長いほど効果が大きい。
- 生 log と JSONL は `runs/device/b4/`（Git の管理外）。`full_*.jsonl` が各 model の 200件、`abl_*.jsonl` が上の段階ごとの計測。

## 12. Action の実行: dispatcher と表情（A1〜A3、2026-09-29）

`firmware/jtalm_action/` に、LM の出力を実行する dispatcher（A1）と、画面の顔（A2）を加え、実機で確かめました（A3）。LM の処理と `gen` の行は B4（§11）と同じです。**servo の出力は起動時に off（dry-run）**で、今回の作業では servo の電源（VM_EN）を一度も入れていません。首を実際に動かす確認は、下の「Servo の動作確認の手順」で、ユーザーの立ち会いのもとで行います。作業は 14:47〜15:35 UTC。

### 構成

| 項目 | 内容 | 確度 |
|---|---|---|
| 流れ | LM の task（core 1）が `gen` の行を出した後、gate の後の `output` を実機で検査し、今の姿勢から計画を立てて `act` の行を出し、待ち行列（4件）に入れる。dispatcher の task（core 0、priority 6）が、計画の手順を順に実行する（顔の切り替え、首の移動）。LM は次の依頼の処理に進める | 確認済み |
| 実機の validator（`main/action.c`） | JSON を Python の `json.loads` と同じ規則で読み（同じ key が重なると後の値、`2.0` も整数）、Action schema v0 と重複の禁止を検査する。`jtalm.action.parse_output(...).schema_valid` と同じものだけを通す。通らない出力と `[]` は何もしない | 実測（下の検査） |
| 角度 | `src/jtalm/action/mapping.py` と同じ（yaw は slight 10° / normal 20° / large 30°、pitch は 5° / 10° / 15°）。`left` / `right` は yaw だけ、`up` / `down` は pitch だけを変え、もう一方の軸はそのまま。`center` は両軸を 0° にする | 実測（照合） |
| 可動域 | mapping.py の上限（yaw ±30°、pitch ±15°）と stackchan-idf の soft limit（yaw −40〜+40°、pitch −10〜+25°）の重なり、つまり **yaw −30〜+30°、pitch −10〜+15°** に制限する。`down` の `large`（−15°）は −10° になる（`act` の行に `clamped` を出す） | 確認済み |
| raw への変換 | yaw は `460 − deg × 16 / 5`、pitch は `620 + deg × 16 / 5`（§10）を四捨五入。可動域の中では yaw 364〜556、pitch 588〜668 | 確認済み |
| 動きの滑らかさ | 1回の移動は cosine の加減速（始めと終わりの速度が 0）。時間は、最大速度 90°/s と最大加速度 360°/s² を超えない最短の長さを 20ms 単位に切り上げる（10° で 380ms、20° で 540ms、30° で 660ms、60° で 1,060ms）。20ms ごとに目標位置を送り、SCS の goal time を 20ms にする | 実測（dry-run の時間） |
| 2つの call | 書かれた順に実行し、間に 200ms 置く | 確認済み |
| うなずき（`nod`） | mapping.py の `nod_targets` の変位（下へ 8°、戻る）を、**今の pitch を中心に** `count` 回くり返す。下の限界（−10°）に近いときは下の点を −10° にし、余地が 4° 未満なら限界から上へ 8° 往復する。最後は始めの pitch に戻る。mapping.py の値は中立からの相対なので、正面を向いているときは同じ動きになる。上を向いているときは、上を向いたままうなずく | 確認済み |
| Torque | 計画を始める直前に、今の位置を目標にしてから torque を入れる（跳ねない）。今の位置が計画の始点から 1° 以上ずれていれば、まず始点へ同じ滑らかさで動く（`sync_ms`）。計画の 0.5 秒後に torque を切る（止まっている間は torque を切るのは stackchan-idf と同じ） | 未実測（servo を動かしていない） |
| 停止 | `!stop` / `!servo off`、**画面への touch**、servo の通信の error、watchdog で、実行中と待ち行列の計画を捨て、torque を切り（broadcast と各 ID）、VM_EN を切って dry-run に戻る。`!relax` は torque だけを切る。これらは LM の処理中でもすぐに効く（serial の読み取りを別の task にした） | dry-run で確認済み（touch は未確認） |
| Watchdog | 監視の task（core 1、priority 7、50ms ごと）が、計画の予定時間 + 2 秒（始点への移動の時間を足す）を過ぎても終わらない実行と、計画がないのに torque が 3 秒以上入っている状態を止める | dry-run で確認済み（`!wdtest`） |
| Servo の driver（`main/servo.c`） | 自前（Apache-2.0）。UART1、TX=G6、RX=G7、1Mbps。ping、torque、goal（位置、時間）、今の位置の読み取り。応答は checksum と ID を確かめる。register と byte の順（big-endian）は stackchan-idf の `components/scs_servo`（BSL-1.0）を参考にした。UART は `!servo on` まで開かない | 未実測（servo を動かしていない） |
| Servo の電源 | 起動時に PY32L020 の VM_EN（pin 0）を、出力の値を 0 にしてから出力にする（一瞬も on にならない順序）。起動時に読んだ値は mode 1 / output 0 で、もともと off だった。`!servo on` で on、200ms 待って ping | 実測（読み返し） |
| 画面（A2） | M5Unified 0.2.17 / M5GFX 0.2.23（MIT、stackchan-idf の submodule をそのまま build）。320×240 の RGB565 の frame（153,600 B）を PSRAM に置き、描いてから全体を転送する。起動時は neutral。顔は白い線で、neutral（丸い目、横一文字の口）、happy（`^ ^` の目、笑った口）、sad（小さい目、内側が上がった眉、への字の口）、surprised（大きい目、開いた口） | 実測（CRC と時間）。**見た目は未確認** |

- Command と `act` / `face` / `act_done` の行の形式は [`firmware/README.md`](../firmware/README.md) にあります。
- M5GFX の自動判別は、この個体を `board_M5StackChan` と判定しました（CoreS3 と同じ扱い）。M5Unified は speaker、mic、IMU、RTC を使わない設定で初期化します（`M5.begin` は 189ms）。

### 確認の結果（servo は dry-run、実測）

| 確認 | 結果 |
|---|---|
| LM の出力（評価セットの先頭 200件。host の C と比較） | 生成した id、gate の前、gate の後の出力がすべて 200 / 200 一致（gate で `[]` にしたのは 11件）。B4 と同じ |
| 計画（`firmware/tools/dispatch_check.py`。Python の `parse_output` と `mapping` で計算し直し、姿勢も1件ずつ引き継ぐ） | 200 / 200 一致（valid 200、実行した計画 183、`[]` 17） |
| 実行（serial log） | `act_done` 183 / 183。中断、error、fault はなし。20ms ごとの更新の間隔は最大 20.0ms で、LM の処理と並行しても遅れなかった。予定との差は最大 +53ms（顔の描画の時間） |
| Validator（`!act` で 400件） | valid / invalid の判定と計画が 400 / 400 で Python と一致。valid 251、invalid 149（JSON でない、配列でない、3個以上、重複、未知の tool や key、enum の外、`count` が 0 / 4 / 1.5 / `true` / `"2"` など） |
| 顔 | 4種類とも frame の CRC-32 が毎回同じで、互いに異なる（neutral `b799fb2a`、happy `0005cc0b`、sad `4fee8a51`、surprised `24d9d978`）。描画 8〜10ms、転送 34ms |
| 停止 | `!stop` と `!relax` で、実行中の計画が次の 20ms の区切りで中断した。`!wdtest`（期限 100ms の計画が 1 秒止まる）で watchdog が `fault` を出し、停止した |
| Servo の電源と UART | 作業の間ずっと `vm_en` 0、UART は未使用（`uart` 0） |
| `firmware/tools/servo_test.py`（dry-run） | 下の手順の 28項目を最後まで流せた（停止なし。最後は `state` off、`vm_en` 0） |

生 log と JSONL は `runs/device/a1/`（Git の管理外）にあります（`eval200.*`、`eval200_dispatch.summary.json`、`fuzz.*`、`servo_test_dry.*`、`commands.log`）。

### メモリと速度（画面あり、servo は dry-run、実測）

内部 SRAM は `MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT` の値です（単位 B。括弧内は B4 の値、§11）。

| 段階 | 内部 SRAM の空き | 最大連続ブロック | 最小空き | PSRAM の空き |
|---|---:|---:|---:|---:|
| `app_main` の開始直後 | 294,731（317,899） | 241,664（262,144） | 262,700 | 8,381,876 |
| 3M の読み込み後 | 116,831（140,219） | 65,536（90,112） | 84,800 | 7,914,924 |
| 画面と dispatcher の初期化後 | 102,843 | 60,416 | 70,812 | 7,756,968 |
| 200件の処理の後 | 99,039 | 57,344 | 67,008 | 7,756,968 |

- M5Unified / M5GFX と dispatcher で、静的な内部 RAM が約 23KB 増えた（IRAM の code +13.3KB、`.data` と `.bss` +9.7KB）。画面の初期化と、dispatcher と監視の task（stack 6KB と 4KB）で約 14KB、serial の読み取りの task（stack 3KB）と1件目の処理で、さらに約 3.4KB 使う。App は 246KB から 494KB になった。
- LM の state の置き場所は B4 と同じ（activation 125,952 B は内部 SRAM、KV cache は PSRAM）。顔の frame と待ち行列は PSRAM（約 158KB）。
- **速度は変わらない。** 評価セットの先頭 200件で、1件の latency は中央値 1,226ms、p90 1,439ms（B4 は 1,222ms / 1,434ms）。Prefill 45.8 ms/token、decode 104.8 ms/token。Dispatcher は LM と並行して計画を実行していた。PC 側で測った送信から応答までは中央値 1,299ms。
- 5M（読み込み後の空きが B4 で約 90KB）に画面を載せると、空きは約 50KB になる見込み（推測）。

### Servo の動作確認の手順（ユーザーの立ち会いが必要。未実施）

目的は、実機の首が計画どおりに動くこと（向き、量、うなずきの回数、2つの依頼の順序）と、動いてはいけない依頼で動かないこと、止める手段が効くことを、目で確かめることです。所要 10〜15分。

**準備（ユーザー）:** 本体を平らな机に置き、首の周りに物や手を置かない。USB で PC につなぐ。本体は battery で動き続けるので、USB を抜いても止まりません。

**非常時の止め方（強い順）:**

1. **画面に触れる。** どこに触れても、torque を切り、servo の電源（VM_EN）を切る（`stop` の行、`src` は `touch`）。
2. Claude Code が `!stop` を送る（`servo_test.py` は Ctrl+C でも `!stop` を送る）。
3. 電源 button を長押しして電源を切る。

**1. 準備の確認（Claude Code、servo は off のまま）**

```sh
# バックアップの確認
sha256sum backups/cores3/coreS3_full_backup_20260929.bin   # 05abdb21…e564c5 であること
# 今の firmware で dry-run の手順を最後まで流す（首は動かない）
uv run --no-project --with pyserial python firmware/tools/servo_test.py --port COM3 \
  --out runs/device/a1/servo_test_dry2.jsonl
```

**2. 画面の確認と touch による停止（ユーザー）:** 画面に neutral の顔が出ていることを見る。画面に触れて、log に `{"t":"stop","src":"touch",...}` が出ることを確かめる（serial の log は `uv run --no-project --with pyserial python firmware/tools/serial_capture.py --port COM3 --seconds 20` で見る）。**この停止が効かないときは、先に進まない。**

**3. 動作確認（Claude Code が実行し、ユーザーが見る）**

```sh
uv run --no-project --with pyserial python firmware/tools/servo_test.py --port COM3 --servo \
  --pause 3 --out runs/device/a1/servo_test.jsonl
```

- 始めに `!servo on` で servo の電源を入れ、今の位置から正面（raw 460 / 620）へゆっくり戻る。
- 1項目ごとに、依頼、LM の出力、計画（角度、raw、時間）を表示し、動き終わってから 3 秒待つ。ユーザーは、表示と実際の動きが合っているかを見る。
- `stop` や `fault` の行が出る（画面に触れた、watchdog、servo の通信の error）か Ctrl+C で、`!stop` を送って終わる。最後は正面に戻し、`!servo off` で dry-run に戻して、`vm_en` が 0 であることを確かめる。

| # | 依頼 | 計画（dry-run で確認済み。yaw / pitch、右と上が正） | 見ること |
|---:|---|---|---|
| 1〜3 | `!act`: 右 slight → normal → large | yaw +10° → +20° → +30°（raw 428 → 396 → 364）、各 380ms | ロボット自身の右（向かい合った人から見て左）へ、3段階で回る |
| 4 | `!act`: 左 large | yaw −30°（raw 556）、1,060ms | 右端から左端へ、ゆっくり加速して減速する |
| 5 | `!act`: 正面 | (0°, 0°)、660ms | 正面に戻る |
| 6 | `!act`: 上 slight → 上 large | pitch +5° → +15°（raw 636 → 668）、間に 200ms | 2段階で上を向く |
| 7 | `!act`: 下 normal | pitch −10°（raw 588）、600ms | 下を向く |
| 8 | `!act`: 下 large | −15° は −10° に制限（`clamped`）。すでに −10° なので動かない | 動かないこと |
| 9 | `!act`: 正面 | 380ms | 正面に戻る |
| 10〜12 | `!act`: うなずき 1 / 2 / 3回 | pitch −8° と 0° の往復（raw 594 / 620）、片道 340ms | 回数が合っていること |
| 13〜14 | `!act`: 表情 happy → sad、surprised → neutral | 顔だけ（首は動かない） | 顔の見た目（4種類） |
| 15 | `!act`: 上 normal → うなずき 2回 | pitch +10° へ、+2° と +10° の往復を2回 | 上を向いたままうなずく |
| 16 | `!act`: 正面 | 380ms | 正面に戻る |
| 17 | 「右を向いて」 | LM: look right normal。yaw +20°、540ms | 右を向く |
| 18 | 「少し左を向いて」 | LM: look left slight。yaw −10°、660ms | 少し左 |
| 19 | 「上を向いて」 | LM: look up normal。pitch +10°（yaw は −10° のまま） | 上を向く（左右はそのまま） |
| 20 | 「正面を向いて」 | LM: look center | 正面に戻る |
| 21 | 「2回うなずいて」 | LM: nod 2 | 2回うなずく |
| 22 | 「笑って」 | LM: set_expression happy | 顔だけ |
| 23 | 「右を向いて、ちょっと嬉しそうにして」（2つの依頼） | LM: look right **slight**、set_expression happy。右を向いてから 200ms 後に顔 | 順序どおり（LM は「ちょっと」を向きの量と解釈した） |
| 24 | 「右を向かないで」（否定） | LM: `[]` | **動かないこと** |
| 25 | 「今日はいい天気だね」（雑談） | LM: `[]` | **動かないこと** |
| 26 | 「富士山について長く説明して」（範囲外） | LM: `[]` | **動かないこと** |
| 27 | 「普通の顔に戻して」 | LM: set_expression neutral | 顔だけ |
| 28 | 「正面を向いて」 | LM: look center | 正面に戻る |

- 24〜26 で計画に移動が含まれていたら、`servo_test.py` はその場で `!stop` を送って終わる。
- 記録すること: 各項目の向きと量が表示と合っていたか、動きが滑らかか（がくつき、うなり、首が当たる音がないか）、torque を切った後に首が垂れないか（計画の 0.5 秒後に切る）、顔の見た目、touch による停止が効いたか。
- 結果が良ければ、角度の初期値（[`architecture.md`](architecture.md) §7）を確定値として扱う。首が当たる、または量が大きすぎる場合は、`main/action.h` の制限か速度を下げて、同じ手順をやり直す。
- 終わったら、実機は dry-run（servo の電源 off）のままにしておく。

## 13. 未確認事項

- 実機で実際に首を動かす確認（§12 の手順。ユーザーの立ち会いが必要）。SCS の driver、torque の入れ方と切り方、touch による停止は、まだ実機で試していない。
- 顔の見た目（§12。CRC と時間は測った）。
- `-DJTLM_BATCH=8` にしたときの速度（5M の内部 SRAM を約 82KB 減らせる）。
- 消費電流と温度（LM を連続で動かしたとき）。
- INT8 の KV cache（未実装。今は f32 で PSRAM に置いている）。
- FCC ID `2AN3WM5STACKCHAN` の個別登録内容。

音声認識や TTS と同時に動かしたときの速度は、本計画の対象外です（LLM だけを作る。[`roadmap.md`](roadmap.md) §1）。

解消した事項:

- `stackchan-idf` が K151 に対応しているかどうか（2026-09-29 に README で確認。§5）。
- Yaw の符号と、pitch の中立位置（2026-09-29 に B2 で確認。§10）。
- 画面、M5Unified、dispatcher を載せた状態での SRAM / PSRAM と速度（2026-09-29 に A3 で測定。§12）。
