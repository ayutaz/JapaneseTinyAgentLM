# 対象ハードウェア

Action LM を動かす実機、M5Stack のスタックチャン（K151）の構成、servo と座標の規約、firmware の dispatcher の設計、実機での速度とメモリをまとめます。firmware の書き込みと使い方は [`../firmware/README.md`](../firmware/README.md)、モデルと `.jtlm` の形式は [`architecture.md`](architecture.md) を参照してください。

## 対象機

| 項目 | 内容 |
|---|---|
| 製品 | M5Stack のスタックチャン、SKU **K151**（M5Stack の公式製品） |
| Main controller | M5Stack CoreS3（ESP32-S3） |
| Servo | Feetech SCS0009 × 2（シリアルバス型） |
| 公式 firmware | [`m5stack/StackChan`](https://github.com/m5stack/StackChan)（ESP-IDF、`firmware/` は MIT License） |

有志が組み立てる SG90（PWM servo）版のスタックチャンとは servo も電源の回路も違うので、この firmware はそのままでは動きません。

## SoC・Flash・PSRAM

| 項目 | 値 |
|---|---|
| Chip | ESP32-S3（QFN56）、Dual Core + LP Core、240MHz、水晶 40MHz |
| USB | Native USB-Serial/JTAG（VID `303A` / PID `1001`） |
| Flash | 16MB、quad（QIO 80MHz で使用） |
| PSRAM | 外付け 8MB、quad（80MHz で使用） |
| firmware の設定 | data cache 64KB / line 64B、instruction cache 32KB、`-O2`、FreeRTOS 100Hz |
| 使わないもの | Wi-Fi、BLE、NPU（ESP32-S3 には NPU がない） |

### Flash の配置

`firmware/jtalm_action/partitions.csv` の配置です。

| Name | Type / Subtype | Offset | Size | 中身 |
|---|---|---:|---:|---|
| （bootloader） | — | `0x0` | — | ESP-IDF の 2nd stage bootloader |
| （partition table） | — | `0x8000` | — | |
| nvs | data / nvs | `0x9000` | 24 KiB | |
| phy_init | data / phy | `0xF000` | 4 KiB | |
| factory | app / factory | `0x10000` | 1,984 KiB | app（Action schema v1 の firmware で 536,128 B） |
| model | data / `0x40` | `0x200000` | 14,336 KiB | `.jtlm`（v1 の 3M INT4 で 1,970,720 B） |

- `model` partition は 64KB の MMU page 境界（`0x200000`）に置き、起動時に全体を1回の `esp_partition_mmap` で map します。重みは flash から直接読み、heap を使いません。
- 14MB に入るのは、3M の FP32（12.9MB）まで、5M の INT8 / INT4 までです。5M の FP32（20.5MB）は入りません。
- Hugging Face で配布している書き込み用のイメージは、上の4つ（bootloader、partition table、app、`.jtlm`）を1つにまとめたもので、`0x0` に書きます。

## 周辺機器

| 機能 | 部品 / 接続 |
|---|---|
| servo のバス | UART1、TX=`G6`、RX=`G7`、1,000,000 bps |
| I2C（内部） | SCL=`G11`、SDA=`G12` |
| IO expander（胴体） | PY32L020、`0x6F`。pin 0 が servo の電源（`VM_EN`） |
| IO expander（CoreS3） | AW9523、`0x58`（`BUS_EN`、`BOOST_EN`） |
| 画面とタッチ | 320×240 の LCD とタッチパネル（M5Unified / M5GFX で使う）。明るさ（backlight）は M5GFX の `setBrightness` で変える |
| 台座の RGB LED | 12個（WS2812）。胴体の PY32L020 の pin 13 が駆動し、firmware は PY32 の LED の register（個数 `0x24`、色 `0x30` から RGB565）に書く。12個を同じ色で点け、各成分は **168 以下**（公式 firmware の `set_led_color` の説明にある安全な範囲）にする |
| Speaker | CoreS3 の内蔵 speaker（AW88298）。M5Unified の Speaker で、音量を変えたときの確認音（1kHz、80ms）を鳴らす |
| その他（使わない） | バッテリー監視 INA226（`0x41`）、NFC ST25R3916（`0x50`）、胴体のタッチ Si12T（`0x68`、3 zone）、赤外線（IR_SEND=`G5`、IR_REC=`G10`）、mic、550mAh バッテリー |

M5GFX の自動判別は、K151 を `board_M5StackChan`（CoreS3 と同じ扱い）と判定します。firmware は M5Unified を mic、IMU、RTC を使わない設定で初期化します（speaker は使う）。I2C で firmware が自分で書くのは PY32L020（`0x6F`）だけで、電源 IC の AXP2101（`0x34`）には直接書かず、I2C の scan もしません（stackchan-idf で LCD の backlight が消えた記録があるため）。backlight の明るさは M5GFX を通して変えます。

## Servo

| 項目 | Yaw（左右） | Pitch（上下） |
|---|---|---|
| 型番 | Feetech SCS0009 | Feetech SCS0009 |
| Servo ID | 1 | 2 |
| 公式 firmware の角度制限（0.1° 単位） | −1280〜1280（±128°） | 30〜870（3°〜87°） |
| 特記事項 | 連続回転（PWM mode）に対応（この firmware では使わない） | Stall protection あり |

- protocol は Feetech の SCS（SCSCL）です。packet は `FF FF id len inst params… checksum`。register は big-endian で、torque enable `0x28`、goal（位置、時間 ms、速度）`0x2A`、現在位置 `0x38` を使います。
- raw position は 0〜1000、1 step = 0.3125° です。
- **電源:** servo の電源は、胴体の PY32L020 の `VM_EN`（pin 0）で入れます。firmware は起動時に、出力の値を 0 にしてから pin を出力に切り替えるので、電源が一瞬も入りません。pin の設定は stackchan-idf と同じ（pull-down off、pull-up on）です。
- **電源を入れてからの待ち:** SCS0009 は `VM_EN` を入れてから**約 0.85 秒**たたないと ping に答えません（stackchan-idf の README は電源を入れてから 200ms 待つと書いていますが、この実機ではそれより長くかかりました）。firmware は固定の時間を待たず、電源を入れた後、両方の servo が答えるまで 50ms ごとに ping します（最大 3 秒）。

## 座標の規約と raw への変換

Action LM はカテゴリ（`direction` / `amount`）だけを出力し、firmware の dispatcher が角度と raw に変換します。

- **yaw:** 正の値が**ロボット自身の右**（向かい合った人から見て左）。
- **pitch:** 中立位置からの相対値で、正の値が上。
- **中立（正面・水平）:** yaw raw 460、pitch raw 620（stackchan-idf の既定値。K151 の実機で正面・水平になることを確かめています）。
- 首をロボット自身の右へ回すと yaw の raw は**減り**、上を向くと pitch の raw は増えます。そのため yaw だけ符号を反転します。

```text
yaw_raw   = round(460 − yaw_deg   × 16 / 5)    # yaw_deg は右が正
pitch_raw = round(620 + pitch_deg × 16 / 5)    # pitch_deg は上が正
```

可動域（下の soft limit）の中では、yaw raw は 316〜604、pitch raw は 620〜892 です。

## Dispatcher

LM の出力を首の動き、表情、LED、音量、明るさに変える部分です（`firmware/jtalm_action/main/action.c`、`servo.c`、`settings.c`）。

| 項目 | 内容 |
|---|---|
| 流れ | LM の task（core 1）が `gen` の行を出した後、確信度の gate（confidence gate）をかけた後の出力を検査し、今の姿勢から計画を立てて `act` の行を出し、待ち行列（4件）に入れる。dispatcher の task（core 0）が計画の手順を順に実行する。LM はその間に次の依頼を処理できる |
| 検査（validator） | JSON を Python の `json.loads` と同じ規則で読み（同じ key が重なると後の値、`2.0` も整数）、**Action schema v1**（11 の tool、call は2つまで）と重複の禁止を検査する。`jtalm.action.parse_output(...).schema_valid` と同じものだけを通す。通らない出力と `[]` は何もしない |
| 角度（`look` / `turn`） | `src/jtalm/action/mapping.py` の `plan_v1` と同じ。量は `amount`（yaw は slight 10° / normal 20° / large 30°、pitch は slight 5° / normal 10° / large 15°）か、`degrees`（1〜180 の度。そのまま使い、範囲を超えれば下の soft limit で止める）。`look` は正面からの向き（`left` / `right` は yaw だけ、`up` / `down` は pitch だけを決め、もう一方の軸はそのまま）、`turn` は今の向きからの相対。斜め（`up_left`、`up_right`、`down_left`、`down_right`）は両方の軸を動かす（`amount` なら上の各軸の角度、`degrees` なら両軸に同じ角度）。`look` の `center` は両軸を 0° にする |
| Soft limit | **yaw −45〜+45°、pitch 0〜+85°**（2026-10-02 に K151 の実機で確かめた。下は頭が床に当たるため水平まで。`firmware/tools/limits_check.py`）。範囲を超える指示は端で止め、`act` の行に `clamped` が付く（`down` は水平より下へ行かないので、正面からの `down` は動かない） |
| 滑らかさ | 1回の移動は cosine の加減速（始めと終わりの速度が 0）。最大速度 90°/s と最大加速度 360°/s² を超えない最短の時間を 20ms 単位に切り上げる（10° で 380ms、20° で 540ms、30° で 660ms、60° で 1,060ms）。20ms ごとに目標位置を送り、SCS の goal time を 20ms にする |
| 2つの call | 書かれた順に実行し、間に 200ms 置く |
| うなずき（`nod`） | **今の pitch から** 14° 下へ振って戻す往復を `count` 回くり返し、最後は始めの pitch に戻る。下の限界（0°、床）に近いときは、振れ幅を保ったまま上へずらす（low = max(基準 − 14, 0)、high = min(low + 14, +85)）。正面（床）からは 0° と +14° の間で上へ振る。上を向いているときは、上を向いたままうなずく。往復だけは最大速度 150°/s、最大加速度 900°/s² で、14° の片道は 280ms（ピーク約 79°/s） |
| 首振り（`shake`） | 今の yaw から右へ 15°、左へ 15° の往復を `count` 回（1〜5）くり返し、最後は始めの yaw に戻る（pitch はそのまま）。端が soft limit を超えるときは端で止める。速度と加速度はうなずきと同じ（150°/s、900°/s²） |
| お辞儀（`bow`） | 今の pitch が 20° より下なら、まず 20° まで上げる（yaw はそのまま）。そこから下の限界（0°、床）まで下げ、0.5 秒止めてから、始めの pitch に戻る（始めの pitch が床なら戻る動きはない）。20° 以上を向いているときは、上げずにそのまま下げる。速度と加速度は通常の移動と同じ |
| LED（`set_led`） | 台座の 12個を同じ色にする。red、orange、yellow、green、light_blue、blue、purple、pink、white、off の 10色で、各成分は 168 以下（white は 100, 100, 100）。`setting` の行を出す |
| 音量（`set_volume` / `adjust_volume`） | speaker の音量（0〜100）。`set_volume` は値をそのまま、`adjust_volume` は今の値に `by`（1〜100）か `amount`（slight ±10 / normal ±20 / large ±30）を足し、0〜100 に収める。変えた後に新しい音量で確認音（1kHz、80ms）を鳴らす（0 のときは鳴らさない） |
| 明るさ（`set_brightness` / `adjust_brightness`） | 画面の backlight（0〜100）。音量と同じ計算で、**下限は 5**（0 にすると backlight の電源が切れて顔が見えなくなるため、`set_brightness 0` も 5 になる） |
| 設定の保存 | 音量、明るさ、LED の色は、計画が終わった後に NVS（`nvs` partition）へ保存し、再起動しても残る。保存は計画の watchdog の期限の外で、停止（torque off と `VM_EN` off）を待たせない。NVS が空のときの既定値は、音量 50、明るさは起動時の backlight の値、LED は off。起動時に `settings` の行で今の値を出す |
| Torque | 計画を始める直前に、今の位置を目標にしてから torque を入れる（跳ねない）。今の位置が計画の始点から 1° 以上ずれていれば、まず始点へ同じ滑らかさで動く。計画が終わって 0.5 秒後に torque を切る |
| 起動時（dry-run） | **servo の出力は起動時に off**。計画は時間どおりに実行されるが、servo には何も送らず、UART も開かない。`!servo on` で電源を入れ、今の位置から正面へゆっくり戻ってから、首が動くようになる |
| 停止 | `!stop` / `!servo off`、**画面へのタッチ**、servo の通信の error、watchdog で、実行中と待ち行列の計画を捨て、torque を切り（broadcast と各 ID）、`VM_EN` を切って dry-run に戻る。`!relax` は torque だけを切る。serial の読み取りは別の task なので、LM の処理中でもすぐに効く |
| Watchdog | 監視の task（core 1、LM より高い優先度、50ms ごと）が、計画の予定時間 + 2 秒（始点への移動の時間を足す）を過ぎても終わらない実行と、計画がないのに torque が 3 秒以上入っている状態を止める。タッチは 100ms ごとに見る |
| servo の driver | 自前（Apache-2.0）。ping、torque、goal、現在位置の読み取り。応答は checksum と ID を確かめる。register と byte の順は stackchan-idf の `components/scs_servo`（BSL-1.0）を参考にした（コードは copy していない） |

firmware の計画は、`firmware/tools/dispatch_check.py` が Python（`jtalm.action.parse_output` と `jtalm.action.mapping.plan_v1`）で計算し直したものと一致することを確かめています。Action schema v1 では、host で build した validator と planner（`firmware/tools/act_host.c`）で 3,000件、実機の `!act` で 600件の validator の判定と計画、v1 のモデルの実機の出力 300件の計画（[`results/v1_action/device/`](../results/v1_action/device/README.md)）がすべて一致しました。実機で首を動かし、向き、量（`degrees` と斜めを含む）、うなずき、首振り、お辞儀、2つの依頼の順序、否定や雑談で動かないこと、タッチと `!stop` で止まること（首振りの途中のタッチ、お辞儀の 0.5 秒の静止中の `!stop`）、顔、LED の色、確認音と明るさを目で確かめました（2026-10-02〜03）。

## 表情

M5GFX で、320×240 の RGB565 の frame（153,600 B、PSRAM）に描いてから全体を転送します。顔は黒地に白い線で、次の7種類です。起動時は neutral です。

| 表情 | 描き方 |
|---|---|
| neutral | 丸い目、横一文字の口 |
| happy | `^ ^` の目、笑った口 |
| sad | 小さい目、内側が上がった眉、への字の口 |
| surprised | 大きい目、開いた口 |
| angry | 小さい目、内側が下がった眉、小さなへの字の口 |
| sleepy | 閉じた目（横線）、小さな「o」の口 |
| doubt | 片方の目が小さく高い、片方だけ上がった眉、傾いた口 |

描画は 8〜12ms、転送は 34ms です。`face` の行に frame の CRC-32 を出すので、描画が毎回同じかを serial だけで確かめられます。

## 実機の性能

### 速度

Action schema v1 の 3M（seed 0、INT4、grammar と gate 0.88506）を、v1 の firmware（LED、speaker、NVS を含む）で動かした結果です。スタックチャン実例セット v1 の 140件と、eval v3 と human v1 から選んだ 160件、合わせて 300件で、gate の前の出力も後の出力も PC の PyTorch と 300 / 300 一致し、dispatcher の計画も Python の `plan_v1` と 300 / 300 一致しました。計測の記録は [`results/v1_action/device/`](../results/v1_action/device/README.md) にあります。

| 項目 | v1（300件） | v0.5.1（v0 の評価セットの先頭 300件） |
|---|---:|---:|
| 1件の応答時間（中央値） | 1,042 ms | 1,276 ms |
| 1件の応答時間（p90） | 1,746 ms | 1,860 ms |
| 1件の応答時間（最大） | 2,753 ms | 2,456 ms |
| Decode（生成の2 token 目以降、1 token ずつ） | 105.4 ms/token | 105.2 ms/token |
| Prefill（prompt の全 token をまとめて） | 45.9 ms/token | 45.8 ms/token |
| 生成する token 数（平均） | 5.2 | 8.4 |

内訳の目安は、prefill（約 14 token）が約 0.6 秒、生成が 1 token あたり約 0.1 秒です。v1 の tokenizer は JSON を少ない token で書くので、v0.5.1 より中央値が短くなりました。何もしない（`[]`）応答は短く、生成も 1〜2 token で終わります。speaker、LED、NVS を足しても速度は変わりません（prompt と生成の token 数が同じ依頼どうしで比べた差は平均 +1.1 ms、+0.11%）。画面と dispatcher は LM と並行して動きます。

v0.5.1 の 3M（データ v0.5.1、gate 0.868）の記録は [`results/v051_action/device/`](../results/v051_action/device/README.md) にあります。

モデルの大きさと量子化による違いです（同じ構造の初期の checkpoint、[`results/b4_device/`](../results/b4_device/)、評価セットの先頭 200件。prompt は平均 12 token）。「帯域の上限」は、重みを下の flash の読み出し帯域（31.2 MB/s）で1回読むのにかかる時間です。

| model | 重み | 重みの byte 数 | decode（ms/token） | 帯域の上限（ms/token） | prefill（ms/token） | 中央値（ms） | p90（ms） |
|---|---|---:|---:|---:|---:|---:|---:|
| 3M | FP32 | 12.6MB | 410.7 | 404 | 62.8 | 3,488 | 4,107 |
| 3M | INT8 | 3.26MB | 115.3 | 104 | 49.3 | 1,273 | 1,762 |
| **3M** | **INT4** | **1.68MB** | **104.5** | 54 | **45.8** | **1,153** | **1,532** |
| 5M | INT8 | 5.22MB | 178.7 | 167 | 78.0 | 1,991 | 2,409 |
| 5M | INT4 | 2.69MB | 161.1 | 86 | 72.0 | 1,793 | 2,234 |

- FP32 と INT8 の decode は flash の帯域で決まります（上限の 98% と 90%）。INT4 は上限の約2倍かかり、演算（INT4 の復元と積和で 1 weight あたり約 11 命令）で決まります。そのため INT4 は INT8 より約 10% 速いだけです。
- 3M INT8 の decode（115 ms/token）は、同じくらいの重み（stories3M INT8、3.35MB）を esp32-llm で動かしたとき（forward だけで 140〜154 ms/token）より速いです（[`../firmware/baselines/README.md`](../firmware/baselines/README.md)）。

### 速くするために行ったこと

どの変更も計算の値を1 bit も変えないものに限り、変更のたびに host の出力が変わらないこと（評価セットの先頭 200件、6つの model で byte 単位）と、実機の出力が host と同じであることを確かめました。下の表は 3M INT8、評価セットの先頭 20件（移植直後だけは 10件）の値です。

| 段階 | prefill（ms/token） | decode（ms/token） | 1件の中央値（ms） |
|---|---:|---:|---:|
| 移植直後（1 core、1 token ずつ、arena はすべて PSRAM） | 423 | 428 | 4,899 |
| 内積の kernel の修正、activation を内部 SRAM へ | 166 | 171 | 2,425 |
| ＋ prefill のまとめ処理（最大 16 token） | 88 | 171 | 1,393 |
| ＋ 2 core（行列積の出力の行を core 0 と 1 で半分ずつ） | **49** | **116** | **794** |

- 試して採用しなかったもの: INT4 の復元の表引き（かえって遅い）、DCache の autoload（約 5% 速いが、ESP-IDF が公開していない register を書くので既定は off。`!autoload` で試せる）。
- `expf`（SiLU と softmax）は newlib が内部で double を使うので1回 1.12µs かかり、decode の約 6% を占めます。値を変えずに速くする方法がないので、そのままです。

### メモリ

画面と dispatcher を載せた状態の値です（単位 B。内部 SRAM は `MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT`）。モデルは data v0.4 の 3M INT4 で、採用した v0.5.1 の 3M と構造も大きさも同じです（出典: [`results/a1_device/`](../results/a1_device/README.md)）。

| 段階 | 内部 SRAM の空き | 最大連続ブロック | 最小空き | PSRAM の空き |
|---|---:|---:|---:|---:|
| `app_main` の開始直後 | 294,731 | 241,664 | 262,700 | 8,381,876 |
| 3M の読み込み後 | 116,831 | 65,536 | 84,800 | 7,914,924 |
| 画面と dispatcher の初期化後 | 102,843 | 60,416 | 70,812 | 7,756,968 |
| 200件の処理の後 | 99,039 | 57,344 | 67,008 | 7,756,968 |

| 確保するもの（3M） | B | 置き場所 |
|---|---:|---|
| 重み（`.jtlm`） | 0 | Flash（mmap） |
| KV cache（f32、128 token 分。INT8 の KV cache にすると 129,024） | 458,752 | PSRAM |
| activation（16 token 分）、attention の score、logits | 125,952 | 内部 SRAM |
| tokenizer の作業領域 | 32,768 | 内部 SRAM |
| 最初の step の logits の控え（診断用） | 8,192 | PSRAM |
| 顔の frame と待ち行列 | 約 158KB | PSRAM |
| task の stack（LM 16KB、行列積の worker 6KB、dispatcher 6KB、監視 4KB、serial の読み取り 3KB） | 約 35KB | 内部 SRAM |

- token ごとの確保はありません。1件目の処理の後は、空きが変わりません。
- Action schema v1 の firmware（speaker、LED、NVS を含む）では、画面と dispatcher の初期化後の内部 SRAM の空きが 89,891 B、1,500件の連続実行の後が 85,783 B で、上の表より約 13KB 少なくなります。100件目以降はほぼ一定で（85,651〜86,099 B）、減り続けません（[`results/v1_action/device/`](../results/v1_action/device/README.md)）。
- 5M は読み込み後の内部 SRAM の空きが約 90KB（画面なし）まで減ります。`-DJTLM_BATCH=8` で activation を半分にできます（結果は変わりません。速度への影響は未計測）。

### 読み出し帯域

32-bit の word を順に読む loop で測った値です（4MB を4回。data cache 64KB を大きく超える量）。

| 計測 | MB/s |
|---|---:|
| PSRAM の順次読み出し | 32.8 |
| Flash mmap の順次読み出し | 31.2 |
| cache に載る 32KB の繰り返し（内部 SRAM、PSRAM、flash mmap のいずれも） | 425.5 |

quad の PSRAM と QIO の flash はほぼ同じ速さで、理論値（4 bit × 80MHz = 40 MB/s）の約 8割です。重みを PSRAM に copy しても速くならないので、重みは flash から mmap で読み、PSRAM は KV cache に使います。

## 設計への影響

- **重みの byte 数が速度を決めます。** 重みを毎 token すべて読むので、速度の上限は「約 31 MB/s ÷ 重みの byte 数」です。INT4 化、語彙の縮小、入出力の埋め込みの共有が速度に直結します。3M INT4 では演算が律速なので、さらに速くするには生成する token 数か層を減らすのが効きます。
- **prompt はまとめて処理します。** 1 token ずつ forward すると、入力の長さに比例して重みを読み直すことになります。prefill のまとめ処理と 2 core の並列化を合わせて、prefill は 166 から 49 ms/token（約 1/3.4）になりました（上の表、3M INT8）。
- **LM は角度を出しません。** LM はカテゴリだけを出し、firmware が検査、角度への変換、制限をします。LM がどんな出力をしても、首は soft limit の外へ出ません。
- **連続回転は使いません。** Action LM からは使えないようにしています。
- **Wi-Fi は使いません。** Wi-Fi を有効にすると内部 SRAM が約 48KB 減ります。

## 安全のための注意

- **首が動くので、指やケーブルを首のまわりに近づけないでください。** 本体は平らな机に置き、首のまわりに物を置かないでください。
- 起動直後は servo が off（dry-run）です。首を動かすのは `!servo on`（または `stackchan_chat.py --servo`）を送ったときだけです。
- 止めるときは、**画面のどこかに触れてください**（torque と servo の電源が切れます）。serial から `!stop` を送っても止まります。それでも止まらないときは、電源ボタンを長押しして電源を切ってください。本体はバッテリーで動くので、USB を抜いても止まりません。
- 角度の制限や速度を変えるときは、`main/action.h` の値を変え、`firmware/tools/servo_test.py` を `--servo` なしの dry-run で流して計画を確かめてから、首を動かしてください。
- 開発用の PC から serial port を開くと、chip が reset されることがあります（`rst:0x15 (USB_UART_CHIP_RESET)`）。`esptool` は読み取りだけでも、接続時と終了時に chip を reset します。
- 書き込むと、今入っている firmware（公式のスタックチャンの firmware など）は消えます。元に戻したい場合は、先に flash 全体をバックアップしてください（[`../firmware/README.md`](../firmware/README.md)）。

## 未確認の事項

- 消費電流（LM を連続で動かしたとき、servo を動かしたとき）。
- 数時間以上の連続実行と、servo を動かしながらの連続実行（72分・3,567件の連続実行では、出力がすべて PC と一致し、reset もエラーもなく、chip の温度は 57.6℃ で頭打ちでした。[`results/v051_action/long_run/`](../results/v051_action/long_run/README.md)。v1 の firmware とモデルでは 29分・1,500件で、出力と計画がすべて PC と一致し、reset もエラーもなく、温度は 50.6〜51.6℃ でした。[`results/v1_action/device/`](../results/v1_action/device/README.md)）。
- `-DJTLM_BATCH=8` にしたときの速度。
