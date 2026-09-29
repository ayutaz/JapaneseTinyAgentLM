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
- **符号規約:** 公式コードのコメントでは、yaw は -1.0 が左端、+1.0 が右端である。つまり **yaw の正の値は右**。ただし実機を動かしての確認はまだ行っていない。

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

1. **内部 SRAM:** 起動直後の空きは約 155KB、最大連続ブロックは約 98KB です。LM の runtime は、重みを Flash から mmap し、KV cache と activation を PSRAM に置きます。内部 SRAM は GEMV の scratch などに限り、数十 KB 以下に抑えます（[`architecture.md`](architecture.md) §10）。
2. **Action:** Action schema は K151 の servo 仕様に合わせます。
   - LM はカテゴリ（`direction` / `amount`）だけを出力し、firmware の dispatcher が角度に変換する（[`architecture.md`](architecture.md) §7）。
   - yaw の正の値を右とする。
   - pitch は公式の 3°〜87° を中立位置からの相対値に変換する。
   - 連続回転は Action LM から使わせない。
3. **Firmware の基盤:** K151 では servo が SCS0009、電源制御が PY32L020 経由です。次の2つは、どちらもこの構成に対応しています。
   - 公式の `m5stack/StackChan`（ESP-IDF v5.5.4、MIT）
   - `stackchan-idf`（ESP-IDF v5.5.5 で検証、BSL-1.0）。README に、PY32 の Pin 0 で servo の VM 電源を入れ、200ms 待ってから bus を使う手順が記載されている。

   LM の評価には、これらの servo driver を流用した自前の最小 firmware を使います。

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
- 画面、servo、M5Unified を載せると、この値から減る。LM の予算は、B4 でそれらを載せた状態で再度測る。
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
- **設計への示唆:** 重みは Flash から mmap して読んでも、PSRAM に copy して読むのとほぼ同じ速さになる。PSRAM を KV cache と activation に空けられるので、重みは mmap で読む方針（[`architecture.md`](architecture.md) §10）でよい。
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

- 3M 級の INT8 で、CoreS3 の実用速度は **約 6〜7 tok/s**。本プロジェクトの tokenizer（M4）では、JSON の固定の断片を1 token にまとめているので、出力は `look` 1個で 7 token、`[]` で 1 token（平均 4.7 token）になる。生成だけなら約 0.2〜2 秒、入力（約 10 token）を1 token ずつ処理する場合は合計で約 2〜3 秒と見積もれる（推測。自前 runtime での実測は B4）。
- 5M を INT8 で載せると、重みの読み出しだけで上限が約 6 tok/s まで下がる。**INT4 化と、重みの読み出し量を減らす工夫（語彙の縮小、embedding と出力層の共有）が速度に直結する。**
- esp32-llm は KV cache を FP32 で PSRAM に置く（3M、seq_len 512 で 1.57MB）。Action の入出力は短い（M4 の系列は最大 52 token）ので、seq_len を実際の長さに合わせて小さくし、KV cache を INT8 / FP16 にすれば、内部 SRAM に置ける可能性がある（推測）。
- Prompt（発話）部分の処理は、1 token ずつ forward するのではなく、まとめて処理（batch prefill）して重みの読み出しを共有しないと、入力長に比例して遅くなる。

## 10. Servo の確認の準備（B2）

[ciniml/stackchan-idf](https://github.com/ciniml/stackchan-idf)（commit `419385ef1b87`、v0.15.0-alpha.2、2026-09-24）を使います。**起動するとすぐ servo が動くので、書き込みはユーザーの立ち会いのもとで行います。** Build まで済ませ、まだ書き込んでいません。

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

NVS と bootctl の領域を消し、B3 の firmware（§8）を書き込みます。bootloader も標準のものに戻ります。

```sh
uvx --from esptool esptool --chip esp32s3 -p COM3 erase-region 0x9000 0x6000
cd firmware/jtalm_eval/build
uvx --from esptool esptool --chip esp32s3 -p COM3 -b 921600 write-flash \
  --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x10000 jtalm_eval.bin
```

### 結果の使い方

- 右へ回したときに raw が**増える**なら、「yaw の正 = 右」（[`architecture.md`](architecture.md) §7）は stackchan-idf の deg の符号とそのまま一致する。**減る**なら、dispatcher で符号を反転する。
- 手順 4-4 の raw を、この個体の中立位置（yaw の中央、pitch の水平）とする。公式 firmware の pitch の範囲（3°〜87°）との対応は、この raw を基準にして換算する。

## 11. 未確認事項

- Yaw の符号と、pitch の中立角度を、実機を動かして確認する（[`roadmap.md`](roadmap.md) §12 の B2。手順は §10）。
- 画面、servo、M5Unified を載せた状態での SRAM / PSRAM（B4 で測る）。
- FCC ID `2AN3WM5STACKCHAN` の個別登録内容。

`stackchan-idf` が K151 に対応しているかどうかは、2026-09-29 に README で確認し、解消しました（§5）。
