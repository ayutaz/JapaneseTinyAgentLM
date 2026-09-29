# 対象ハードウェアと実機調査記録

最終更新: 2026-09-29

本文書は、開発に使う実機の構成と、初回調査（B0。Phase 0 の一部）で取得した情報を記録します。ラベルは [`README.md`](README.md) の「記述の確度」に従います。

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

## 7. 未確認事項

- Yaw の符号と、pitch の中立角度を、実機を動かして確認する（[`roadmap.md`](roadmap.md) §12 の B2）。
- 自前の最小 firmware での Flash map と、状態ごとの SRAM / PSRAM の最大値（Phase 0 の本測定、B3）。
- FCC ID `2AN3WM5STACKCHAN` の個別登録内容。

`stackchan-idf` が K151 に対応しているかどうかは、2026-09-29 に README で確認し、解消しました（§5）。
