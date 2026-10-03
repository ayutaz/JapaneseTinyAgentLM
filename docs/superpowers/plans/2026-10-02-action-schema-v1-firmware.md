# Action schema v1 firmware 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** スタックチャン（K151）の firmware `firmware/jtalm_action` が Action schema v1 の出力（look / turn の角度と斜め、nod / shake / bow、7つの表情、台座 LED、音量、画面の明るさ）を実機で実行し、PC の Python 実装と同じ計画を立てるようにする。

**Architecture:** 検査と計画は `action.c`（ハードウェアに触れない純粋な C）に置き、PC でも build できる小さな入口 `firmware/tools/act_host.c` を通して、Python の基準（`jtalm.action.parse_output` と `jtalm.action.mapping.plan_v1`）と数千件で照合する。ハードウェアは `board.cpp`（画面、touch、PY32 の LED と servo 電源、speaker、明るさ）と `settings.c`（NVS）に閉じ込め、`servo.c` の dispatcher が計画の step を順に実行する。

**Tech Stack:** ESP-IDF v5.5.5（Docker image `espressif/idf:v5.5.5`）、M5Unified 0.2.17 / M5GFX 0.2.23、C11 / C++、Python 3.13（uv）、pyserial、pytest。

**Spec:** [`docs/superpowers/specs/2026-10-02-action-schema-v1-design.md`](../specs/2026-10-02-action-schema-v1-design.md)（6章、7章の F1〜F4、8章）。LM 側の計画は [`2026-10-02-action-schema-v1-lm.md`](2026-10-02-action-schema-v1-lm.md)。

## Global Constraints

- build は `espressif/idf:v5.5.5` の Docker image で行う（Windows の Git Bash では `MSYS_NO_PATHCONV=1` と `$(pwd -W)`）。書き込みは esptool 5 系（`uvx --from esptool esptool`）。実機の port は `COM3`。
- **servo の出力は起動時に off のまま。** 首を動かす作業（`--servo`、`!servo on`）は、利用者が実機を見ているときだけ行う。画面へのタッチ、`!stop` で止まることを保つ。
- 速度と加速度の上限は v0 のまま: 通常の移動 90°/s・360°/s²、うなずきと首振り 150°/s・900°/s²、20ms ごとの目標、2つの call の間は 200ms。
- 可動域の目標は **yaw −45〜+45°、pitch −10〜+85°**。最終値は F2 で利用者が動きを見て決める。範囲を超える指示は制限し、`clamped` を付ける。
- `amount` の角度は v0 のまま（yaw 10/20/30°、pitch 5/10/15°）。`adjust_*` の段階は slight ±10 / normal ±20 / large ±30。明るさの下限は 5。
- 台座の RGB LED は 12個を同じ色で点ける。各色の成分は **168 以下**（公式 firmware の `set_led_color` の説明にある安全な範囲）。
- I2C で書くのは PY32（`0x6F`）だけ。**AXP2101（`0x34`）には触れない。I2C の scan はしない**（stackchan-idf で LCD のバックライトが消えた記録がある。`firmware/third_party/stackchan-idf/docs/py32_ioexpander.md` §1、§6.4）。
- 第三者のコードは copy しない。公式 firmware（m5stack/StackChan、MIT）と stackchan-idf（BSL-1.0）は register の仕様を読む参考にだけ使い、出典を comment に書く。
- 新しいファイルには SPDX の header（`Apache-2.0`、`Copyright 2026 ayutaz`）を付ける。comment は英語、文書は日本語。
- `model` partition の `.jtlm` と、firmware に入る runtime の grammar（`runtime/host/grammar.c`）の版を合わせる（v0 の `.jtlm` は v0 の grammar、v1 の `.jtlm` は v1 の grammar）。合わないと起動時に `the tokenizer lacks the Action grammar pieces` で LM が止まり、画面と dispatcher も起動しない（`boot_board` は `lm_init` の後）。Task 5、6 は `!act` で確かめるので、その時点の runtime の grammar が v1 なら、LM 側の学習途中のものでもよいので v1 の `.jtlm` を `0x200000` に書いておく。
- 依存を足すときは `uv add`（pip は使わない）。pyserial は `uv run --no-project --with pyserial` で使う。
- 計測の生のログは `runs/`（Git の管理外）に置き、まとめだけを `results/` に置く。

## Review Focus

1. **値の端での調整:** 音量 100 で「上げて」、明るさ 5 で「暗くして」、`set_brightness 0`。→ 値は 100 / 5 にとどまり、画面は真っ暗にならない。Task 5 の実機の dry-run 検査（`setting` の記録の値）で確かめる。
2. **可動域の端での相対移動の繰り返し:** yaw +45° で「もう少し右」を何度も送る。→ 首は動かず、計画の move は `clamped: 1`、エラーにならない。Task 4 の host の照合（連続する計画で姿勢を持ち越す）と Task 6 の実機の項目で確かめる。
3. **お辞儀の保持中や首振りの途中での停止:** `bow` の 0.5 秒の保持中に画面に触れる、`!stop` を送る。→ すぐに止まり、torque と servo の電源が切れる。Task 6 の項目で確かめる。
4. **NVS が空、または範囲外の値:** 初めて書き込んだ実機、別の firmware が使った後の実機。→ 既定値（音量 50、明るさは起動時の値、LED は消灯）で起動する。Task 5 で NVS の領域を消してから起動して確かめる。
5. **`.jtlm` と grammar の版の不一致:** v1 の firmware に v0 の `.jtlm` を書いた。→ 黙って止まらず、`error` の記録で原因が分かる。Task 8 で確かめる。

---

## ファイル構成

| ファイル | 役割 | 変更 |
|---|---|---|
| `firmware/jtalm_action/main/action.h` / `action.c` | schema v1 の検査（validator）、計画（planner）、`act` の記録の JSON 出力、LED の色の表。ハードウェアに触れない | 変更 |
| `firmware/jtalm_action/main/board.h` / `board.cpp` | 画面（7つの顔、明るさ）、touch、PY32（servo 電源、LED）、speaker | 変更 |
| `firmware/jtalm_action/main/settings.h` / `settings.c` | 音量、明るさ、LED の色を NVS に保存・読み込み | 新規 |
| `firmware/jtalm_action/main/servo.c` / `servo.h` | dispatcher が LED、音量、明るさ、保持（pause）の step も実行し、変わった設定を保存する | 変更 |
| `firmware/jtalm_action/main/main.c` | `!led`、`!pose` の command、起動時の設定の適用、`act` の記録を `action.c` の出力関数で書く | 変更 |
| `firmware/jtalm_action/main/CMakeLists.txt` | `settings.c` と `nvs_flash` を足す | 変更 |
| `firmware/tools/act_host.c` | `action.c` を PC で動かす入口（1行の JSON → 1行の `act` の記録） | 新規 |
| `firmware/tools/dispatch_check.py` | v1 の照合（`plan_v1` を基準にする）、v1 の fuzz、host の出力との照合 | 変更 |
| `firmware/tools/led_probe.py` | F1: LED の点灯確認 | 新規 |
| `firmware/tools/limits_check.py` | F2: 可動域を少しずつ広げて動かす | 新規 |
| `firmware/tools/servo_test.py` | v1 の動作の項目と、設定の値の自動検査 | 変更 |
| `firmware/tools/stackchan_chat.py` | v1 の出力を日本語で表示 | 変更 |
| `tests/test_firmware_action_host.py` | `action.c` と Python の照合（C コンパイラがあれば実行） | 新規 |
| `tests/test_stackchan_chat.py` | 表示の文言 | 新規 |
| `docs/hardware.md`、`firmware/README.md`、`README.md`（安全の行だけ） | 可動域、動作、表情、LED、音量、明るさ、command | 変更 |

## LM 側の計画との接点（Interfaces）

この計画は、LM 側の計画が作る次の Python の API を基準にする（`src/jtalm/action/schema.py`、`src/jtalm/action/mapping.py`）。名前と形はこのとおりに使う。

```python
# jtalm.action.schema (v1)
TOOL_NAMES = ("look", "turn", "nod", "shake", "bow", "set_expression", "set_led",
              "set_volume", "adjust_volume", "set_brightness", "adjust_brightness")
DIRECTIONS = ("left", "right", "up", "down", "up_left", "up_right", "down_left", "down_right",
              "center")
AMOUNTS = ("slight", "normal", "large")
EXPRESSIONS = ("happy", "sad", "surprised", "neutral", "angry", "sleepy", "doubt")
COLORS = ("red", "orange", "yellow", "green", "light_blue", "blue", "purple", "pink", "white", "off")
ADJUST_DIRECTIONS = ("up", "down")
def parse_output(raw: str) -> ParsedOutput   # .schema_valid, .calls, .errors（v0 と同じ形）

# jtalm.action.mapping (v1)
@dataclass(frozen=True)
class Limits:
    yaw_min: float = -45; yaw_max: float = 45; pitch_min: float = -10; pitch_max: float = 85
DEFAULT_LIMITS = Limits()
YAW_DEG = {"slight": 10, "normal": 20, "large": 30}; PITCH_DEG = {"slight": 5, "normal": 10, "large": 15}
NOD_PITCH_DEG = 14; SHAKE_YAW_DEG = 15; BOW_HOLD_MS = 500
ADJUST_STEP = {"slight": 10, "normal": 20, "large": 30}; BRIGHTNESS_MIN = 5
def plan_v1(calls: list[dict], start: tuple[float, float], limits: Limits = DEFAULT_LIMITS) -> list[dict]
```

`plan_v1` の step（時間は pause だけ。移動の時間と call の間の 200ms は firmware の側で決める）:

- `{"kind": "move", "yaw": float, "pitch": float, "clamped": bool}`
- `{"kind": "pause", "ms": int}`
- `{"kind": "expr", "expression": str}`、`{"kind": "led", "color": str}`
- `{"kind": "volume", "level": int}`（`set_volume`）、`{"kind": "volume", "delta": int}`（`adjust_volume`。`±ADJUST_STEP[amount]` か `±by`）。`brightness` も同じ。
- 意味: `look` は正面を基準にした目標（left / right は yaw だけ、up / down は pitch だけ、斜めは両方、center は (0, 0)）。`amount` は `YAW_DEG` / `PITCH_DEG`、`degrees` n は方向が指す軸すべてに n。`turn` は同じ量を今の姿勢に足す。目標は `limits` で制限し、変わったら `clamped=True`。
  - `nod`: v0 の `nod_targets(count, base_pitch, limits.pitch_min, limits.pitch_max)` の移動。最後の目標が base と違えば base に戻る。
  - `shake`: count 回、`yaw=clamp(base+15)` → `yaw=clamp(base−15)` の順。その後 base の yaw に戻る（pitch はそのまま）。
  - `bow`: `pitch=limits.pitch_min` へ動き、`BOW_HOLD_MS` 保持し、base の pitch に戻る（yaw はそのまま）。
  - 1つの依頼の2つの call の間で、姿勢を持ち越す。
- 音量と明るさの `delta` は、firmware が実行時に今の値へ足し、0〜100（明るさは下限 `BRIGHTNESS_MIN`）に制限する。`level` も同じ範囲に制限する。

**順序の依存:**
- Task 1〜3 は LM 側を待たずにできる。
- Task 4 は、LM 側の schema v1（`parse_output`）と `mapping.plan_v1` ができてから行う。
- Task 8 は、LM 側の v1 の `.jtlm` と v1 の C の grammar（`runtime/host/grammar.c`）ができてから行う。

---

### Task 1（F1）: 台座の LED が実機で点くかを確かめる

最も危険が大きい部分なので最初に行う。点かなければ、ここで止めて利用者に相談する（spec 8章）。

**根拠（確認済み）:**
- 公式 firmware（m5stack/StackChan、MIT）の `firmware/main/hal/hal_io_expander.cpp` は、LED を使う前に、PY32 の pin 13 を出力、pull-up、push-pull にし、LED の数を 12 にしている。
- 同じ firmware の `firmware/main/hal/drivers/PY32IOExpander_Class/PY32IOExpander_Class.cpp` の register は次のとおり。
  - `REG_LED_CFG = 0x24`: 下位6 bit が LED の数、bit6 が refresh。refresh は read-modify-write で立てる。
  - `REG_LED_RAM_START = 0x30`: 1個あたり RGB565 の2 byte（下位 byte が先）。
- `firmware/third_party/stackchan-idf/docs/py32_ioexpander.md` §6 の記述とも一致する。stackchan-idf の失敗は、1個を3 byte（GRB888）として書いていたことと、pin 13 の設定がなかったことによる。
- PY32 の GPIO の register は、上位 byte（pin 8〜15）が mode `0x04`、pull-up `0x0A`、pull-down `0x0C`、drive `0x14`（0 が push-pull）（`py32_ioexpander.md` §2）。

**Files:**
- Modify: `firmware/jtalm_action/main/board.h`
- Modify: `firmware/jtalm_action/main/board.cpp`
- Modify: `firmware/jtalm_action/main/main.c`（`!led` の command、`board` の記録に `led_init`）
- Create: `firmware/tools/led_probe.py`

**Interfaces:**
- Produces（C）: `int board_led(uint8_t r, uint8_t g, uint8_t b);`（12個を同じ色にして refresh。0 / −1）、`board_info_t` の `int led_init;`（1 で LED の初期化に成功）、`board_led_cfg()`（`REG_LED_CFG` の読み戻し、診断用）。Task 5 が `board_led` を使う。
- Produces（serial）: `!led <r> <g> <b>` → `JTALM {"t":"led","r":..,"g":..,"b":..,"ok":0|1,"cfg":<REG_LED_CFG>}`。各値は 0〜168 に制限する。

- [ ] **Step 1: `board.h` に宣言を足す**

`board_info_t` の `uint32_t begin_ms;` の次に、次の行を足す。

```c
  int led_init;       // the base LEDs were set up (PY32 pin 13, 12 LEDs)
```

`board_touched` の宣言の前に、次を足す。

```c
// The 12 RGB LEDs on the back of the base (WS2812 driven by the PY32): all set to one color,
// each channel 0..255 (callers keep it at 168 or less, the official firmware's safe range).
// Returns 0 on success.
int board_led(uint8_t r, uint8_t g, uint8_t b);

// REG_LED_CFG of the PY32 read back (LED count in bits 0-5), -1 without the PY32. Diagnostics.
int board_led_cfg(void);
```

- [ ] **Step 2: `board.cpp` に LED の初期化と書き込みを足す**

file 先頭の comment の最後に、出典を1行足す。

```cpp
// The base LED protocol (pin 13 as a push-pull output with pull-up, LED count in 0x24 bits 0-5,
// refresh bit 6, RGB565 little-endian pairs from 0x30) follows the M5Stack StackChan firmware
// (MIT, hal_io_expander.cpp and PY32IOExpander_Class.cpp); no code is copied.
```

`namespace {` の定数に、次を足す（`kVmEnMask` の次）。

```cpp
constexpr uint8_t kPy32RegModeHigh = 0x04;      // pins 8-15
constexpr uint8_t kPy32RegPullUpHigh = 0x0A;
constexpr uint8_t kPy32RegPullDownHigh = 0x0C;
constexpr uint8_t kPy32RegDriveHigh = 0x14;     // 0 = push-pull
constexpr uint8_t kPy32RegLedCfg = 0x24;        // bits 0-5 LED count, bit 6 refresh
constexpr uint8_t kPy32RegLedRam = 0x30;        // RGB565 little-endian, 2 bytes per LED
constexpr uint8_t kLedPinMask = 1u << (13 - 8);  // the LED data line is PY32 pin 13
constexpr uint8_t kLedRefresh = 1u << 6;
constexpr int kLedCount = 12;
```

`draw_face` の後（`}  // namespace` の前）に、次を足す。

```cpp
// Caller holds g_gfx_lock (the internal I2C is also used by the touch controller).
bool led_write(uint8_t r, uint8_t g, uint8_t b) {
  const uint16_t c = (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
  uint8_t buf[2 * kLedCount];
  for (int i = 0; i < kLedCount; i++) {
    buf[2 * i] = (uint8_t)(c & 0xFF);
    buf[2 * i + 1] = (uint8_t)(c >> 8);
  }
  bool ok = M5.In_I2C.writeRegister(kPy32Addr, kPy32RegLedRam, buf, sizeof(buf), kPy32Freq);
  uint8_t cfg = M5.In_I2C.readRegister8(kPy32Addr, kPy32RegLedCfg, kPy32Freq);
  return ok && M5.In_I2C.writeRegister8(kPy32Addr, kPy32RegLedCfg, cfg | kLedRefresh, kPy32Freq);
}

bool led_init() {
  bool ok = M5.In_I2C.bitOn(kPy32Addr, kPy32RegModeHigh, kLedPinMask, kPy32Freq);
  ok = ok && M5.In_I2C.bitOff(kPy32Addr, kPy32RegPullDownHigh, kLedPinMask, kPy32Freq);
  ok = ok && M5.In_I2C.bitOn(kPy32Addr, kPy32RegPullUpHigh, kLedPinMask, kPy32Freq);
  ok = ok && M5.In_I2C.bitOff(kPy32Addr, kPy32RegDriveHigh, kLedPinMask, kPy32Freq);
  ok = ok && M5.In_I2C.writeRegister8(kPy32Addr, kPy32RegLedCfg, kLedCount, kPy32Freq);
  vTaskDelay(pdMS_TO_TICKS(50));
  return ok && led_write(0, 0, 0);
}
```

`board_init` の中で、`g_gfx_lock = xSemaphoreCreateMutex();` は今の位置のまま、PY32 の servo 電源の設定（`info->vm_out_after = ...;`）の直後に次を足す。

```cpp
    info->led_init = led_init() ? 1 : 0;
```

file の最後に、次を足す。

```cpp
extern "C" int board_led(uint8_t r, uint8_t g, uint8_t b) {
  if (!g_py32 || g_gfx_lock == nullptr) return -1;
  xSemaphoreTake(g_gfx_lock, portMAX_DELAY);
  bool ok = led_write(r, g, b);
  xSemaphoreGive(g_gfx_lock);
  return ok ? 0 : -1;
}

extern "C" int board_led_cfg(void) {
  if (!g_py32) return -1;
  return M5.In_I2C.readRegister8(kPy32Addr, kPy32RegLedCfg, kPy32Freq);
}
```

- [ ] **Step 3: `main.c` に `!led` と、`board` の記録の `led_init` を足す**

`boot_board()` の `board` の記録の printf を、`led_init` を含む形に替える。

```c
  printf(
      "JTALM {\"t\":\"board\",\"ok\":%d,\"board\":%d,\"begin_ms\":%" PRIu32
      ",\"py32\":%d,\"py32_version\":%d,\"vm_mode\":[%d,%d],\"vm_out\":[%d,%d]"
      ",\"led_init\":%d,\"led_cfg\":%d,\"servo\":\"dry\"}\n",
      err == 0, b.board, b.begin_ms, b.py32, b.py32_version, b.vm_mode_before,
      b.vm_mode_after, b.vm_out_before, b.vm_out_after, b.led_init, board_led_cfg()
  );
```

`run_command()` の `else if (!strcmp(line, "!center"))` の前に、次を足す。

```c
  } else if (!strncmp(line, "!led ", 5)) {
    // Diagnostics: all 12 base LEDs to one color (each channel limited to 168).
    int r = 0, g = 0, b = 0;
    sscanf(line + 5, "%d %d %d", &r, &g, &b);
    r = r < 0 ? 0 : r > 168 ? 168 : r;
    g = g < 0 ? 0 : g > 168 ? 168 : g;
    b = b < 0 ? 0 : b > 168 ? 168 : b;
    int err = board_led((uint8_t)r, (uint8_t)g, (uint8_t)b);
    printf("JTALM {\"t\":\"led\",\"r\":%d,\"g\":%d,\"b\":%d,\"ok\":%d,\"cfg\":%d}\n", r, g, b,
           err == 0, board_led_cfg());
```

file 先頭の comment の command の一覧に `"!led <r> <g> <b>"`（診断用）を足す。

- [ ] **Step 4: `firmware/tools/led_probe.py` を作る**

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""F1: light the 12 base LEDs of the K151 in a few colors (jtalm_action, "!led r g b").

    uv run --no-project --with pyserial python firmware/tools/led_probe.py \
        --port COM3 --out runs/fw/f1_led.jsonl

Someone watches the back of the base and says which colors appeared. Servo output stays off.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from lm_serial import Device

COLORS = [
    ("赤", 168, 0, 0),
    ("緑", 0, 168, 0),
    ("青", 0, 0, 168),
    ("白（弱め）", 100, 100, 100),
    ("消灯", 0, 0, 0),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--pause", type=float, default=3.0, help="seconds per color")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dev = Device(args.port, args.out.with_suffix(".log"))
    keep: list[dict] = []
    rc = 0
    with args.out.open("w", encoding="utf-8") as f:
        try:
            dev.reset()
            dev.wait_for("ready", 30.0, keep)
            board = next(r for r in keep if r.get("t") == "board")
            print(f"board: led_init={board.get('led_init')} led_cfg={board.get('led_cfg')}")
            f.write(json.dumps(board, ensure_ascii=False) + "\n")
            for label, r, g, b in COLORS:
                dev.send(f"!led {r} {g} {b}")
                rec = dev.wait_for("led", 5.0)
                print(f"{label}: ok={rec['ok']} cfg={rec['cfg']}", flush=True)
                f.write(json.dumps({"label": label, **rec}, ensure_ascii=False) + "\n")
                rc |= 0 if rec["ok"] else 1
                time.sleep(args.pause)
        finally:
            dev.send("!led 0 0 0")
            time.sleep(0.3)
            dev.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: build する**

Run（リポジトリの root、Git Bash）:

```bash
MSYS_NO_PATHCONV=1 docker run --rm -e IDF_COMPONENT_MANAGER=0 -v "$(pwd -W):/w" \
  -w /w/firmware/jtalm_action espressif/idf:v5.5.5 idf.py build
```

Expected: `Project build complete.`、warning なし（`board.cpp`、`main.c`）。

- [ ] **Step 6: app だけを書き込む（`model` partition は書かない）**

実機の flash 全体のバックアップが `backups/cores3/` にあることを先に確かめる。

```bash
cd firmware/jtalm_action/build && uvx --from esptool esptool --chip esp32s3 -p COM3 -b 921600 \
  write-flash --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x10000 jtalm_action.bin
```

Expected: `Hash of data verified.` が3回。

- [ ] **Step 7: 点灯を試す**

Run: `uv run --no-project --with pyserial python firmware/tools/led_probe.py --port COM3 --out runs/fw/f1_led.jsonl`

Expected:
- `board: led_init=1 led_cfg=12`
- 各色で `ok=1 cfg=12`。refresh の bit6 は PY32 が自動で戻すので、`cfg` は 12 のまま。

- [ ] **Step 8: 利用者の確認（チェックポイント）**

利用者に、台座の背面の LED が「赤 → 緑 → 青 → 白 → 消灯」の順に点いたかを聞く。

- **すべて点いた場合:** Task 1 は完了。色の見え方（白が青っぽい、など）の感想を記録しておく。
- **一部だけ点いた、色が違う場合（例: 赤と青が入れ替わる）:** 記録を添えて報告し、`led_write` の byte の順と bit の配置を利用者と確認してから直す。
- **まったく点かない場合:** **ここで作業を止める。** `runs/fw/f1_led.jsonl` と `.log`（`led_init`、`led_cfg`、`ok`）を添えて利用者に報告し、spec 8章の選択肢（`set_led` を schema に残して firmware では無視する、など）を相談する。返事があるまで Task 2 以降の LED に関わる部分に進まない。

- [ ] **Step 9: Commit**

```bash
git add firmware/jtalm_action/main/board.h firmware/jtalm_action/main/board.cpp \
  firmware/jtalm_action/main/main.c firmware/tools/led_probe.py
git commit -m "firmware: base RGB LEDs through the PY32 (pin 13 push-pull, 12 LEDs, RGB565 LED RAM) and a !led probe; lit on the K151"
```

---

### Task 2（F2）: 可動域を広げる

**Files:**
- Modify: `firmware/jtalm_action/main/action.h`（限界の define を1組にまとめる）
- Modify: `firmware/jtalm_action/main/action.c`（限界の macro、`act_plan_pose`）
- Modify: `firmware/jtalm_action/main/main.c`（`!pose <yaw> <pitch>`）
- Modify: `firmware/tools/dispatch_check.py`（`Policy` が新しい define を読む）
- Create: `firmware/tools/limits_check.py`
- Modify（最終値が目標と違う場合だけ）: `src/jtalm/action/mapping.py` の `DEFAULT_LIMITS`

**Interfaces:**
- Produces（C）: `ACT_YAW_MIN_DEG`、`ACT_YAW_MAX_DEG`、`ACT_PITCH_MIN_DEG`、`ACT_PITCH_MAX_DEG`（`action.h`）、`void act_plan_pose(act_plan_t *p, int yaw, int pitch, int to_yaw, int to_pitch);`。Task 4 はこの define を使い、`dispatch_check.Policy` は `mapping.DEFAULT_LIMITS` と照合する。
- Produces（serial）: `!pose <yaw> <pitch>` → 1つの move を可動域で制限して実行する。記録は `act`（`src: "pose"`）と `act_done`。保守用として残す。

- [ ] **Step 1: `action.h` の限界を1組の define にする**

`// mapping.py: YAW_DEG, ...` から `#define HW_PITCH_MAX_DEG 25` までを、次に替える。

```c
// Soft limits of the head in degrees from the neutral pose (right / up positive). F2 widened
// them from the v0 values (yaw -30..+30, pitch -10..+15) towards the official firmware's
// recommended range, checked on the K151 with someone watching (docs/hardware.md).
// mapping.DEFAULT_LIMITS holds the same values (firmware/tools/dispatch_check.py checks it).
#define ACT_YAW_MIN_DEG (-45)
#define ACT_YAW_MAX_DEG 45
#define ACT_PITCH_MIN_DEG (-10)
#define ACT_PITCH_MAX_DEG 85
#define ACT_NOD_PITCH_DEG 14  // nod amplitude (8 was too small to notice, 2026-09-30)
```

`void act_plan(...)` の宣言の次に、次を足す。

```c
// A single move to (to_yaw, to_pitch) within the soft limits, without calls ("!pose").
void act_plan_pose(act_plan_t *p, int yaw, int pitch, int to_yaw, int to_pitch);
```

- [ ] **Step 2: `action.c` の限界の macro を替え、`act_plan_pose` を足す**

`// Soft limits: the Action limits ...` から `#define PITCH_MAX ...` までの5行を、次に替える。

```c
#define YAW_MIN ACT_YAW_MIN_DEG
#define YAW_MAX ACT_YAW_MAX_DEG
#define PITCH_MIN ACT_PITCH_MIN_DEG
#define PITCH_MAX ACT_PITCH_MAX_DEG
```

file の最後に、次を足す。

```c
void act_plan_pose(act_plan_t *p, int yaw, int pitch, int to_yaw, int to_pitch) {
  p->n_calls = 0;
  p->n_steps = 0;
  p->total_ms = 0;
  p->yaw0 = yaw;
  p->pitch0 = pitch;
  add_move(p, 0, to_yaw, to_pitch, &yaw, &pitch, 0);
  p->yaw1 = yaw;
  p->pitch1 = pitch;
}
```

v0 の `amount` の角度（最大 30° / 15°）は新しい限界の内側にあるので、v0 の出力の計画は変わらない。

- [ ] **Step 3: `main.c` の `dispatch` を、計画の作成と、送信・報告に分ける。`!pose` を足す**

`dispatch()` を次の2つの関数に替える（記録の形は v0 と同じ）。

```c
// Queues a plan and prints
//   JTALM {"t":"act","seq":..,"valid":..,"calls":[..],"from":[yaw,pitch],"steps":[..],...}
static void submit_and_report(lm_t *lm, const char *src, act_plan_t *plan, int valid,
                              const char *err, int64_t t0) {
  uint32_t seq = ++lm->act_seq;
  int queued = 0, dropped = 0;
  if (plan->n_steps > 0) {
    queued = servo_submit(plan, seq) == 0;
    dropped = !queued;
    if (queued) {
      lm->pose_yaw = plan->yaw1;
      lm->pose_pitch = plan->pitch1;
    }
  }
  int64_t t1 = now_us();
  out_lock();
  printf(
      "JTALM {\"t\":\"act\",\"seq\":%" PRIu32 ",\"src\":\"%s\",\"valid\":%d,\"err\":%s%s%s"
      ",\"calls\":[",
      seq, src, valid, err ? "\"" : "", err ? err : "null", err ? "\"" : ""
  );
  for (int i = 0; i < plan->n_calls; i++) {
    if (i) putchar(',');
    print_call(&plan->calls[i]);
  }
  printf("],\"from\":[%d,%d],\"steps\":[", plan->yaw0, plan->pitch0);
  for (int i = 0; i < plan->n_steps; i++) {
    const act_step_t *s = &plan->steps[i];
    if (i) putchar(',');
    if (s->kind == STEP_EXPR) {
      printf("{\"c\":%d,\"k\":\"expr\",\"expr\":\"%s\"}", s->call, act_expr_names[s->expr]);
    } else {
      printf(
          "{\"c\":%d,\"k\":\"move\",\"yaw\":%d,\"pitch\":%d,\"yaw_raw\":%d,\"pitch_raw\":%d"
          ",\"ms\":%d,\"clamped\":%d}",
          s->call, s->yaw, s->pitch, s->yaw_raw, s->pitch_raw, s->ms, s->clamped
      );
    }
  }
  printf(
      "],\"to\":[%d,%d],\"total_ms\":%" PRIu32 ",\"queued\":%d,\"dropped\":%d"
      ",\"servo\":\"%s\",\"plan_us\":%" PRId64 "}\n",
      plan->yaw1, plan->pitch1, plan->total_ms, queued, dropped,
      servo_output_on() ? "on" : "dry", t1 - t0
  );
  out_unlock();
}

// Validates an Action JSON string, plans it from the current pose and queues it.
// Only "output" (after the gate) is dispatched; "[]" and invalid outputs do nothing.
static void dispatch(lm_t *lm, const char *src, const char *json, size_t len) {
  static act_plan_t plan;
  int64_t t0 = now_us();
  const char *err = NULL;
  int valid = act_parse(json, len, plan.calls, &plan.n_calls, &err) == 0;
  if (!valid) plan.n_calls = 0;
  act_plan(&plan, lm->pose_yaw, lm->pose_pitch);
  submit_and_report(lm, src, &plan, valid, err, t0);
}

// "!pose <yaw> <pitch>": one move within the soft limits (limit checks, maintenance).
static void dispatch_pose(lm_t *lm, int yaw, int pitch) {
  static act_plan_t plan;
  int64_t t0 = now_us();
  act_plan_pose(&plan, lm->pose_yaw, lm->pose_pitch, yaw, pitch);
  submit_and_report(lm, "pose", &plan, 1, NULL, t0);
}
```

`run_command()` の `else if (!strcmp(line, "!center"))` の前に、次を足す。

```c
  } else if (!strncmp(line, "!pose ", 6)) {
    int yaw = 0, pitch = 0;
    if (sscanf(line + 6, "%d %d", &yaw, &pitch) != 2) {
      emit_error("usage: !pose <yaw> <pitch>");
      return;
    }
    dispatch_pose(lm, yaw, pitch);
```

file 先頭の comment の command の一覧に `"!pose <yaw> <pitch>"` を足す。

- [ ] **Step 4: `dispatch_check.py` の `Policy` を新しい define に合わせる**

`Policy.__init__` の先頭の3つの assert と、limit の4行を、次に替える。

```python
        assert d["ACT_NOD_PITCH_DEG"] == mapping.NOD_PITCH_DEG
        self.yaw_min = int(d["ACT_YAW_MIN_DEG"])
        self.yaw_max = int(d["ACT_YAW_MAX_DEG"])
        self.pitch_min = int(d["ACT_PITCH_MIN_DEG"])
        self.pitch_max = int(d["ACT_PITCH_MAX_DEG"])
```

- [ ] **Step 5: v0 の計画が変わらないことを、評価セットの記録で確かめる**

v0 の device の記録（`runs/device/` にある `lm_serial.py --act` の出力と log）があれば、それで照合する。

Run: `uv run python firmware/tools/dispatch_check.py --results runs/device/a1/eval200.jsonl --log runs/device/a1/eval200.log`

Expected:
- `"plans_match"` が `"n"` と同じになる。
- `"mismatches": []`。

記録がなければ、Step 8 の後に Task 3 の host の照合で確かめる。

- [ ] **Step 6: `firmware/tools/limits_check.py` を作る**

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""F2: widen the head limits step by step with someone watching (jtalm_action "!pose").

    uv run --no-project --with pyserial python firmware/tools/limits_check.py \
        --port COM3 --axis yaw --out runs/fw/f2_yaw.jsonl
    uv run --no-project --with pyserial python firmware/tools/limits_check.py \
        --port COM3 --axis pitch --max 45 --out runs/fw/f2_pitch45.jsonl

THE HEAD MOVES. The script turns servo output on, goes through the poses of one axis in small
steps (pausing on each), compares the servo's present position with the target, and centers
and turns the servos off at the end. A touch on the screen or Ctrl+C stops at once.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from lm_serial import Device

STEP_DEG = 5
TOLERANCE_DEG = 2.0  # present vs target; more means the head did not get there
YAW_RAW_ZERO, PITCH_RAW_ZERO, DEG_PER_RAW = 460, 620, 5 / 16


def poses(axis: str, limit: int) -> list[tuple[int, int]]:
    if axis == "yaw":
        right = list(range(30, limit + 1, STEP_DEG))
        return [(y, 0) for y in right] + [(0, 0)] + [(-y, 0) for y in right] + [(0, 0)]
    up = list(range(15, limit + 1, STEP_DEG if limit <= 45 else 10))
    return [(0, p) for p in up] + [(0, -10), (0, 0)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--axis", choices=["yaw", "pitch"], required=True)
    ap.add_argument("--max", type=int, default=None, help="largest angle to try (default: target)")
    ap.add_argument("--pause", type=float, default=2.0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    limit = args.max or (45 if args.axis == "yaw" else 85)
    sys.stdout.reconfigure(encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dev = Device(args.port, args.out.with_suffix(".log"))
    keep: list[dict] = []
    rc = 0
    with args.out.open("w", encoding="utf-8") as f:
        try:
            dev.reset()
            dev.wait_for("ready", 30.0, keep)
            dev.send("!servo on")
            if dev.wait_for("servo", 10.0, keep).get("state") != "on":
                raise RuntimeError("servo on failed")
            dev.wait_for("act_done", 15.0, keep)
            for yaw, pitch in poses(args.axis, limit):
                dev.send(f"!pose {yaw} {pitch}")
                a = dev.wait_for("act", 10.0, keep)
                done = dev.wait_for("act_done", a["total_ms"] / 1000 + 10, keep)
                if any(r.get("t") in ("fault", "stop") for r in keep):
                    raise RuntimeError("stopped (touch, watchdog or servo error)")
                py, pp = done["present"]
                got = ((YAW_RAW_ZERO - py) * DEG_PER_RAW, (pp - PITCH_RAW_ZERO) * DEG_PER_RAW)
                target = a["steps"][0]["yaw"], a["steps"][0]["pitch"]
                off = max(abs(got[0] - target[0]), abs(got[1] - target[1]))
                note = "" if off <= TOLERANCE_DEG else "  NG: did not reach the target"
                clamp = " (clamped)" if a["steps"][0]["clamped"] else ""
                print(f"yaw {target[0]:+d} pitch {target[1]:+d}{clamp}: present "
                      f"({got[0]:+.1f}, {got[1]:+.1f}){note}", flush=True)  # fmt: skip
                f.write(json.dumps({"target": target, "present_deg": got, "act": a,
                                    "done": done}, ensure_ascii=False) + "\n")  # fmt: skip
                rc |= 0 if not note else 1
                keep.clear()
                time.sleep(args.pause)
        except (RuntimeError, TimeoutError, KeyboardInterrupt) as e:
            print(f"STOPPED: {e!r}", flush=True)
            rc = 2
        finally:
            dev.send("!center")
            time.sleep(1.5)
            dev.send("!servo off")
            time.sleep(0.5)
            dev.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: build して、app だけを書き込む**

Task 1 の Step 5 と Step 6 と同じ。

Expected: build が通り、`Hash of data verified.` が出る。

- [ ] **Step 8: 利用者の確認（チェックポイント）: 左右**

利用者に「首が左右に最大 45° まで、5° ずつ動きます。配線が引っ張られる、どこかに当たる、音がするなど、気になったらすぐ画面に触れて止めてください」と伝え、見てもらう準備ができてから実行する。

Run: `uv run --no-project --with pyserial python firmware/tools/limits_check.py --port COM3 --axis yaw --out runs/fw/f2_yaw.jsonl`

Expected:
- 各姿勢で `NG` が出ない（今の位置と目標の差が 2° 以内）。
- 最後に正面に戻る。

利用者に、問題なく動いた最大の角度（左右それぞれ）を聞く。

- [ ] **Step 9: 利用者の確認（チェックポイント）: 上下**

上は段階を分けて確かめる。まず `--max 45` で行い、利用者が問題ないと言ったら、`--max 85` で行う。

Run（1回目）: `uv run --no-project --with pyserial python firmware/tools/limits_check.py --port COM3 --axis pitch --max 45 --out runs/fw/f2_pitch45.jsonl`

Run（2回目、利用者の了承の後）: `uv run --no-project --with pyserial python firmware/tools/limits_check.py --port COM3 --axis pitch --out runs/fw/f2_pitch85.jsonl`

Expected:
- `NG` が出ない。
- 下（−10°）は v0 と同じ。

利用者に、問題なく動いた上の最大の角度を聞く。

- [ ] **Step 10: 最終値を書く**

- 利用者が決めた値を `action.h` の4つの define に書く。
- 目標（−45 / 45 / −10 / 85）と違う場合は、`src/jtalm/action/mapping.py` の `Limits` の既定値も同じ値にする（Task 4 の `Policy` がこの2つの一致を確かめる）。
- 決めた値と日付を、`docs/hardware.md` の「Dispatcher」の表の Soft limit の行に書く（Task 8 でまとめて直す文書の、先行の修正）。

```markdown
| Soft limit | **yaw −45〜+45°、pitch −10〜+85°**（2026-10 に実機で確かめて v0 の ±30° / −10〜+15° から広げた。`firmware/tools/limits_check.py`）。範囲を超える指示は制限し、`act` の行に `clamped` が付く |
```

（数値は Step 8 と Step 9 で決めた値にする。）

再 build して書き込み、`limits_check.py` を `--max` なしでもう一度だけ流し、`NG` がないことを確かめる。

- [ ] **Step 11: Commit**

```bash
git add firmware/jtalm_action/main/action.h firmware/jtalm_action/main/action.c \
  firmware/jtalm_action/main/main.c firmware/tools/dispatch_check.py \
  firmware/tools/limits_check.py docs/hardware.md src/jtalm/action/mapping.py
git commit -m "firmware: head soft limits widened to yaw -45..+45 / pitch -10..+85 (checked on the K151 with the user), one set of limit defines, !pose for limit checks"
```

（`mapping.py` を変えていなければ、`git add` から外す。）

---

### Task 3: `action.c` を PC で動かして Python と照合する仕組み（v0 のまま）

v1 に変える前に、照合の仕組みを v0 で作って通しておく。`act` の記録の calls と steps の JSON を書く処理を `action.c` に移し、firmware と PC の入口で同じ関数を使う。

**Files:**
- Modify: `firmware/jtalm_action/main/action.h` / `action.c`（`act_print_body`）
- Modify: `firmware/jtalm_action/main/main.c`（`submit_and_report` が `act_print_body` を使う。`print_call` を消す）
- Create: `firmware/tools/act_host.c`
- Modify: `firmware/tools/dispatch_check.py`（`compare_host`、`--write-cases`、`--host-results`）
- Create: `tests/test_firmware_action_host.py`

**Interfaces:**
- Produces（C）: `void act_print_body(FILE *f, const act_plan_t *p);`。`"calls":[..],"from":[y,p],"steps":[..],"to":[y,p],"total_ms":N` を書く（前後の `{`、`}` と他の key は呼び出し側が書く）。
- Produces（host）: `act_host [yaw pitch]`。stdin の1行（Action JSON）ごとに、stdout に `{"valid":0|1,"err":..,<act_print_body>,"queued":0|1,"dropped":0}` を書く。姿勢は、step のある計画の後に持ち越す（実機と同じ）。
- Produces（Python）: `dispatch_check.compare_host(pol: Policy, cases: list[str], recs: list[dict]) -> dict`（`{"n", "match", "mismatches"}`）。Task 4 も使う。

- [ ] **Step 1: 失敗する test を書く**

`tests/test_firmware_action_host.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""The firmware's Action validator and planner (firmware/jtalm_action/main/action.c), built for
the host, against the Python reference (firmware/tools/dispatch_check.py)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "firmware" / "tools"))
import dispatch_check  # noqa: E402


def _compiler() -> str | None:
    return shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")


@pytest.fixture(scope="module")
def act_host(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if _compiler() is None:
        pytest.skip("no C compiler on PATH")
    exe = tmp_path_factory.mktemp("act_host") / "act_host"
    main = ROOT / "firmware" / "jtalm_action" / "main"
    subprocess.run(
        [_compiler(), "-std=gnu11", "-O1", "-Wall", "-Wextra", "-I", str(main), "-o", str(exe),
         str(ROOT / "firmware" / "tools" / "act_host.c"), str(main / "action.c"), "-lm"],
        check=True,
    )  # fmt: skip
    return exe


def run_host(exe: Path, cases: list[str]) -> list[dict]:
    proc = subprocess.run(
        [str(exe)], input="\n".join(cases) + "\n", capture_output=True, text=True, check=True
    )
    return [json.loads(line) for line in proc.stdout.splitlines()]


def test_firmware_matches_python_on_fuzz_cases(act_host: Path) -> None:
    cases = dispatch_check.fuzz_cases(3000, seed=1)
    recs = run_host(act_host, cases)
    assert len(recs) == len(cases)
    pol = dispatch_check.Policy(dispatch_check.load_defines())
    summary = dispatch_check.compare_host(pol, cases, recs)
    assert summary["mismatches"] == [], summary["mismatches"][:5]
```

- [ ] **Step 2: test が失敗することを確かめる**

この PC（Windows）には C コンパイラがないので、pytest は skip になる。CI（Ubuntu、gcc あり）と同じ確認を、Docker の gcc で行う。

Run:

```bash
uv run python -c "import sys; sys.path.insert(0, 'firmware/tools'); import dispatch_check"
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/w" -w /w --entrypoint sh espressif/idf:v5.5.5 \
  -c "mkdir -p runs/fw && cc -std=gnu11 -O1 -Wall -Wextra -I firmware/jtalm_action/main \
      -o runs/fw/act_host firmware/tools/act_host.c firmware/jtalm_action/main/action.c -lm"
```

Expected: 2つ目の command が `firmware/tools/act_host.c: No such file or directory` で失敗する。

- [ ] **Step 3: `act_print_body` を `action.c` に移す**

`action.h` の先頭の include に `#include <stdio.h>` を足し、file の最後に次の宣言を足す。

```c
// Writes "calls":[..],"from":[yaw,pitch],"steps":[..],"to":[yaw,pitch],"total_ms":N for the
// "act" record (firmware/tools/dispatch_check.py reads it).
void act_print_body(FILE *f, const act_plan_t *p);
```

`action.c` の file の最後に、次を足す（v0 の calls と steps の形のまま）。

```c
// ---------------------------------------------------------------------------------------
// The "act" record

static void print_call(FILE *f, const act_call_t *c) {
  if (c->kind == ACT_LOOK) {
    fprintf(f, "{\"name\":\"look\",\"arguments\":{\"direction\":\"%s\",\"amount\":\"%s\"}}",
            act_dir_names[c->dir], act_amount_names[c->amount]);
  } else if (c->kind == ACT_EXPR) {
    fprintf(f, "{\"name\":\"set_expression\",\"arguments\":{\"expression\":\"%s\"}}",
            act_expr_names[c->expr]);
  } else {
    fprintf(f, "{\"name\":\"nod\",\"arguments\":{\"count\":%d}}", c->count);
  }
}

static void print_step(FILE *f, const act_step_t *s) {
  if (s->kind == STEP_EXPR) {
    fprintf(f, "{\"c\":%d,\"k\":\"expr\",\"expr\":\"%s\"}", s->call, act_expr_names[s->expr]);
  } else {
    fprintf(f,
            "{\"c\":%d,\"k\":\"move\",\"yaw\":%d,\"pitch\":%d,\"yaw_raw\":%d,\"pitch_raw\":%d"
            ",\"ms\":%d,\"clamped\":%d}",
            s->call, s->yaw, s->pitch, s->yaw_raw, s->pitch_raw, s->ms, s->clamped);
  }
}

void act_print_body(FILE *f, const act_plan_t *p) {
  fputs("\"calls\":[", f);
  for (int i = 0; i < p->n_calls; i++) {
    if (i) fputc(',', f);
    print_call(f, &p->calls[i]);
  }
  fprintf(f, "],\"from\":[%d,%d],\"steps\":[", p->yaw0, p->pitch0);
  for (int i = 0; i < p->n_steps; i++) {
    if (i) fputc(',', f);
    print_step(f, &p->steps[i]);
  }
  fprintf(f, "],\"to\":[%d,%d],\"total_ms\":%" PRIu32, p->yaw1, p->pitch1, p->total_ms);
}
```

`action.c` の include に `#include <inttypes.h>` を足す。

`main.c` の `print_call` 関数を消す。`submit_and_report` の `",\"calls\":["` から `printf("],\"to\":...` の直前までを、次に替える。

```c
  printf(
      "JTALM {\"t\":\"act\",\"seq\":%" PRIu32 ",\"src\":\"%s\",\"valid\":%d,\"err\":%s%s%s,",
      seq, src, valid, err ? "\"" : "", err ? err : "null", err ? "\"" : ""
  );
  act_print_body(stdout, plan);
  printf(
      ",\"queued\":%d,\"dropped\":%d,\"servo\":\"%s\",\"plan_us\":%" PRId64 "}\n", queued,
      dropped, servo_output_on() ? "on" : "dry", t1 - t0
  );
```

- [ ] **Step 4: `firmware/tools/act_host.c` を作る**

```c
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
//
// Host build of the firmware's Action validator and planner (firmware/jtalm_action/main/
// action.c) for tests: one Action JSON per line on stdin, one record per line on stdout,
//   {"valid":..,"err":..,"calls":[..],"from":[..],"steps":[..],"to":[..],"total_ms":..,
//    "queued":..,"dropped":0}
// with the same fields as the device's "act" record. The pose carries over from a plan with
// steps to the next one, as on the device. Optional arguments: the start pose (yaw pitch).
//
//   cc -std=gnu11 -O1 -I firmware/jtalm_action/main -o act_host \
//      firmware/tools/act_host.c firmware/jtalm_action/main/action.c -lm

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "action.h"

int main(int argc, char **argv) {
  int yaw = argc > 2 ? atoi(argv[1]) : 0;
  int pitch = argc > 2 ? atoi(argv[2]) : 0;
  static char line[8192];
  static act_plan_t plan;
  while (fgets(line, sizeof(line), stdin)) {
    size_t n = strcspn(line, "\r\n");
    const char *err = NULL;
    int valid = act_parse(line, n, plan.calls, &plan.n_calls, &err) == 0;
    if (!valid) plan.n_calls = 0;
    act_plan(&plan, yaw, pitch);
    int queued = plan.n_steps > 0;
    printf("{\"valid\":%d,\"err\":%s%s%s,", valid, err ? "\"" : "", err ? err : "null",
           err ? "\"" : "");
    act_print_body(stdout, &plan);
    printf(",\"queued\":%d,\"dropped\":0}\n", queued);
    if (queued) {
      yaw = plan.yaw1;
      pitch = plan.pitch1;
    }
  }
  return 0;
}
```

- [ ] **Step 5: `dispatch_check.py` に `compare_host` と CLI を足す**

`offline()` の前に、次を足す。

```python
def compare_host(pol: Policy, cases: list[str], recs: list[dict]) -> dict:
    """Checks act_host records (one per case, pose carried over) against the reference."""
    pose = [0, 0]
    mism = []
    for i, (text, act) in enumerate(zip(cases, recs, strict=True)):
        errs = check_act(pol, act, text, pose)
        if errs:
            mism.append({"i": i, "json": text, "errs": errs})
        pose = next_pose(act, pose)
    return {"n": len(cases), "match": len(cases) - len(mism), "mismatches": mism[:20]}
```

`main()` の引数に、次を足す。

```python
    ap.add_argument("--write-cases", type=Path, help="write --n fuzz cases (one per line)")
    ap.add_argument("--n", type=int, default=3000, help="number of cases for --write-cases")
    ap.add_argument("--host-results", type=Path, help="act_host output for --cases")
    ap.add_argument("--cases", type=Path, help="the cases given to act_host")
```

`if args.fuzz:` の前に、次を足す。

```python
    if args.write_cases:
        cases = fuzz_cases(args.n, args.seed)
        args.write_cases.write_text("\n".join(cases) + "\n", encoding="utf-8", newline="\n")
        print(f"{len(cases)} cases -> {args.write_cases}")
        return 0
    if args.host_results:
        if not args.cases:
            ap.error("--host-results needs --cases")
        cases = args.cases.read_text("utf-8").splitlines()
        recs = [json.loads(x) for x in args.host_results.read_text("utf-8").splitlines()]
        summary = compare_host(pol, cases, recs)
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 1 if summary["mismatches"] else 0
```

module の docstring に、host での照合の手順を足す。

```text
On the host, the same validator and planner built from action.c (firmware/tools/act_host.c;
Windows: the gcc of the ESP-IDF Docker image):

    uv run python firmware/tools/dispatch_check.py --write-cases runs/fw/cases.txt --seed 1
    # cc ... -o runs/fw/act_host firmware/tools/act_host.c firmware/jtalm_action/main/action.c -lm
    runs/fw/act_host < runs/fw/cases.txt > runs/fw/host.jsonl
    uv run python firmware/tools/dispatch_check.py --host-results runs/fw/host.jsonl \
        --cases runs/fw/cases.txt
```

- [ ] **Step 6: host で照合が通ることを確かめる**

Run:

```bash
uv run python firmware/tools/dispatch_check.py --write-cases runs/fw/cases.txt --seed 1
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/w" -w /w --entrypoint sh espressif/idf:v5.5.5 \
  -c "cc -std=gnu11 -O1 -Wall -Wextra -I firmware/jtalm_action/main -o runs/fw/act_host \
      firmware/tools/act_host.c firmware/jtalm_action/main/action.c -lm \
      && runs/fw/act_host < runs/fw/cases.txt > runs/fw/host.jsonl"
uv run python firmware/tools/dispatch_check.py --host-results runs/fw/host.jsonl --cases runs/fw/cases.txt
uv run pytest tests/test_firmware_action_host.py -q
```

Expected:
- compile の warning がない。
- `"match": 3000`、`"mismatches": []`。
- pytest は、この PC では `1 skipped`（CI では pass）。

- [ ] **Step 7: firmware の build が通り、記録の形が変わらないことを確かめる**

- build する（Task 1 の Step 5 と同じ）。
- app を書き込む（Task 1 の Step 6 と同じ）。
- 次を実行する。

Run: `uv run --with pyserial python firmware/tools/dispatch_check.py --port COM3 --fuzz 200 --out runs/fw/t3_fuzz.jsonl`

Expected: `"match": 200`。

- [ ] **Step 8: lint と Commit**

```bash
uv run --only-dev ruff check src tests firmware/tools && uv run --only-dev ruff format --check src tests firmware/tools
git add firmware/jtalm_action/main/action.h firmware/jtalm_action/main/action.c \
  firmware/jtalm_action/main/main.c firmware/tools/act_host.c firmware/tools/dispatch_check.py \
  tests/test_firmware_action_host.py
git commit -m "firmware: act record body written by action.c; act_host runs the validator and planner on the host and dispatch_check compares 3,000 fuzz cases with Python"
```

---

### Task 4（F3）: `action.c` を schema v1 にする（検査と計画）

**前提:** LM 側の計画の schema v1（`parse_output`）と `mapping.plan_v1` が merge 済み。

**Files:**
- Modify: `firmware/jtalm_action/main/action.h`
- Modify: `firmware/jtalm_action/main/action.c`
- Modify: `firmware/jtalm_action/main/servo.c`（`s->expr` を `s->arg` に。新しい step は Task 5）
- Modify: `firmware/tools/dispatch_check.py`（`Policy.plan` を `plan_v1` に、v1 の fuzz）
- Test: `tests/test_firmware_action_host.py`（Task 3 のまま、v1 の fuzz で通す）

**Interfaces:**
- Consumes: 上の「LM 側の計画との接点」の `schema` と `mapping` の名前すべて。
- Produces（C）:
  - `enum { ACT_LOOK, ACT_TURN, ACT_NOD, ACT_SHAKE, ACT_BOW, ACT_EXPR, ACT_LED, ACT_SET_VOLUME, ACT_ADJUST_VOLUME, ACT_SET_BRIGHTNESS, ACT_ADJUST_BRIGHTNESS, ACT_KIND_COUNT }`（`TOOL_NAMES` と同じ順）
  - `DIR_*`（`DIRECTIONS` と同じ順、`DIR_CENTER` が最後）、`EXPR_*`（7つ）、`COLOR_*`（10、`COLOR_OFF` が最後）、`ADJ_UP` / `ADJ_DOWN`
  - `STEP_MOVE, STEP_EXPR, STEP_LED, STEP_VOLUME, STEP_BRIGHTNESS, STEP_PAUSE`
  - `act_step_t.arg`: `STEP_EXPR` は `EXPR_*`、`STEP_LED` は `COLOR_*`、`STEP_VOLUME` / `STEP_BRIGHTNESS` は 1 なら `level` が delta
  - `act_step_t.level`: 音量と明るさの値、または delta
  - `const uint8_t act_led_rgb[COLOR_COUNT][3];`
  - `int act_apply_level(int current, const act_step_t *s);`（実行時に値を決める。Task 5 が使う）
- Produces（`act` の記録の step）:
  - `{"c","k":"move","yaw","pitch","yaw_raw","pitch_raw","ms","clamped"}`
  - `{"c","k":"pause","ms"}`
  - `{"c","k":"expr","expr"}`、`{"c","k":"led","color"}`
  - `{"c","k":"volume"|"brightness","level"}` または `{..,"delta"}`

- [ ] **Step 1: 失敗する照合を作る（`dispatch_check.py` を v1 にする）**

import を次に替える。

```python
from jtalm.action import mapping
from jtalm.action.schema import (
    ADJUST_DIRECTIONS,
    AMOUNTS,
    COLORS,
    DIRECTIONS,
    EXPRESSIONS,
    TOOL_NAMES,
    parse_output,
)
```

`Policy.__init__` を次に替える。

```python
    def __init__(self, d: dict[str, float]) -> None:
        self.limits = mapping.Limits(
            d["ACT_YAW_MIN_DEG"], d["ACT_YAW_MAX_DEG"], d["ACT_PITCH_MIN_DEG"],
            d["ACT_PITCH_MAX_DEG"],
        )  # fmt: skip
        assert self.limits == mapping.DEFAULT_LIMITS, (self.limits, mapping.DEFAULT_LIMITS)
        assert d["ACT_NOD_PITCH_DEG"] == mapping.NOD_PITCH_DEG
        assert d["ACT_SHAKE_YAW_DEG"] == mapping.SHAKE_YAW_DEG
        assert d["ACT_BOW_HOLD_MS"] == mapping.BOW_HOLD_MS
        assert d["ACT_BRIGHTNESS_MIN"] == mapping.BRIGHTNESS_MIN
        steps = [d["ACT_ADJUST_SLIGHT"], d["ACT_ADJUST_NORMAL"], d["ACT_ADJUST_LARGE"]]
        assert steps == [mapping.ADJUST_STEP[a] for a in AMOUNTS]
        self.yaw_zero = d["SERVO_YAW_ZERO"]
        self.pitch_zero = d["SERVO_PITCH_ZERO"]
        self.vmax = d["MOTION_VMAX_DPS"]
        self.amax = d["MOTION_AMAX_DPS2"]
        self.nod_vmax = d["MOTION_NOD_VMAX_DPS"]
        self.nod_amax = d["MOTION_NOD_AMAX_DPS2"]
        self.tick = d["MOTION_TICK_MS"]
        self.gap = int(d["MOTION_CALL_GAP_MS"])
```

`Policy.plan` を次に替える。

```python
    def plan(self, calls: list[dict], yaw: float, pitch: float) -> dict:
        """The device plan from mapping.plan_v1 plus the device's motion timing."""
        steps: list[dict] = []
        total = 0
        start = [yaw, pitch]
        for c, call in enumerate(calls):
            if c:
                total += self.gap
            swing = call["name"] in ("nod", "shake")  # the faster nod profile
            for s in mapping.plan_v1([call], (yaw, pitch), self.limits):
                k = s["kind"]
                if k == "move":
                    y, p = s["yaw"], s["pitch"]
                    ms = self.move_ms(max(abs(y - yaw), abs(p - pitch)), swing)
                    steps.append({
                        "c": c, "k": "move", "yaw": y, "pitch": p,
                        "yaw_raw": round(self.yaw_zero - y * 16 / 5),
                        "pitch_raw": round(self.pitch_zero + p * 16 / 5),
                        "ms": ms, "clamped": int(s["clamped"]),
                    })  # fmt: skip
                    total += ms
                    yaw, pitch = y, p
                elif k == "pause":
                    steps.append({"c": c, "k": "pause", "ms": s["ms"]})
                    total += s["ms"]
                elif k == "expr":
                    steps.append({"c": c, "k": "expr", "expr": s["expression"]})
                elif k == "led":
                    steps.append({"c": c, "k": "led", "color": s["color"]})
                else:  # volume / brightness: "level" or "delta"
                    key = "level" if "level" in s else "delta"
                    steps.append({"c": c, "k": k, key: s[key]})
        return {"from": start, "steps": steps, "to": [yaw, pitch], "total_ms": total}
```

`fuzz_cases` の中の `call()` と `mutate()` と `raw` の前半を、次に替える（`raw` の v0 の行は残し、v1 の行を足す）。

```python
    def call() -> dict:
        name = rng.choice(TOOL_NAMES)
        if name in ("look", "turn"):
            dirs = DIRECTIONS if name == "look" else tuple(d for d in DIRECTIONS if d != "center")
            d = rng.choice(dirs)
            if d == "center" or rng.random() < 0.5:
                return {"name": name, "arguments": {"direction": d, "amount": rng.choice(AMOUNTS)}}
            return {"name": name, "arguments": {"direction": d, "degrees": rng.randint(1, 180)}}
        if name in ("nod", "shake"):
            return {"name": name, "arguments": {"count": rng.randint(1, 5)}}
        if name == "bow":
            return {"name": name, "arguments": {}}
        if name == "set_expression":
            return {"name": name, "arguments": {"expression": rng.choice(EXPRESSIONS)}}
        if name == "set_led":
            return {"name": name, "arguments": {"color": rng.choice(COLORS)}}
        if name in ("set_volume", "set_brightness"):
            return {"name": name, "arguments": {"level": rng.randint(0, 100)}}
        d = rng.choice(ADJUST_DIRECTIONS)
        if rng.random() < 0.5:
            return {"name": name, "arguments": {"direction": d, "amount": rng.choice(AMOUNTS)}}
        return {"name": name, "arguments": {"direction": d, "by": rng.randint(1, 100)}}

    def mutate(calls: list[dict]) -> object:
        calls = json.loads(json.dumps(calls))
        m = rng.randrange(20)
        c = calls[0] if calls else call()
        a = c["arguments"]
        bad_numbers = [0, -1, 6, 101, 181, 2.0, 45.0, 1e2, True, "45", None, 1.5]
        if m == 0 and a:
            a[rng.choice(list(a))] = rng.choice(["LEFT", "", "happy ", "center", 1, None])
        elif m == 1:
            c["extra"] = 1
        elif m == 2:
            a["speed"] = "fast"
        elif m == 3 and a:
            del a[rng.choice(list(a))]
        elif m == 4:
            c["name"] = rng.choice(["look_at", "Look", "nod ", "speak", "set_color", "volume"])
        elif m == 5:
            key = rng.choice(["count", "degrees", "level", "by"])
            for k in ("amount", "count", "degrees", "level", "by"):
                if k in a:
                    del a[k]
                    a[key] = rng.choice(bad_numbers)
                    break
        elif m == 6:
            return [c, c]
        elif m == 7:
            return [c, call(), call()]
        elif m == 8:
            return c
        elif m == 9:
            return [c, [c]]
        elif m == 10:
            c["arguments"] = [a]
        elif m == 11:
            return {"calls": calls}
        elif m == 12:
            return [{"arguments": a, "name": c["name"]}]
        elif m == 13:
            c["arguments"] = json.dumps(a)
        elif m == 14:  # amount and degrees together
            return [{"name": "look", "arguments": {"direction": "right", "amount": "slight",
                                                   "degrees": 30}}]  # fmt: skip
        elif m == 15:  # center with degrees, turn to center
            return [{"name": rng.choice(["look", "turn"]),
                     "arguments": {"direction": "center", "degrees": rng.randint(1, 90)}}]  # fmt: skip
        elif m == 16:  # bow with arguments
            return [{"name": "bow", "arguments": {"count": 1}}]
        elif m == 17:  # adjust with level / set with by
            return [{"name": "adjust_volume", "arguments": {"level": 50}}]
        elif m == 18:  # a number as a float twice: kept apart by the duplicate rule
            return [{"name": "nod", "arguments": {"count": 2}},
                    {"name": "nod", "arguments": {"count": 2.0}}]  # fmt: skip
        else:  # the same relative move twice from the limit
            return [{"name": "turn", "arguments": {"direction": "right", "degrees": 180}},
                    {"name": "turn", "arguments": {"direction": "right", "amount": "large"}}]  # fmt: skip
        return calls
```

`raw` のリストの最後に、次を足す。

```python
        '[{"name":"look","arguments":{"direction":"up","degrees":90}}]',
        '[{"name":"look","arguments":{"direction":"right","degrees":45}}]',
        '[{"name":"turn","arguments":{"direction":"right","amount":"slight"}}]',
        '[{"name":"turn","arguments":{"direction":"up_left","degrees":20}},'
        '{"name":"shake","arguments":{"count":5}}]',
        '[{"name":"bow","arguments":{}}]',
        '[{"name":"bow","arguments":{}},{"name":"bow","arguments":{}}]',
        '[{"name":"set_led","arguments":{"color":"blue"}}]',
        '[{"name":"set_volume","arguments":{"level":50}}]',
        '[{"name":"set_volume","arguments":{"level":0}}]',
        '[{"name":"set_volume","arguments":{"level":-0}}]',
        '[{"name":"set_volume","arguments":{"level":100.0}}]',
        '[{"name":"adjust_volume","arguments":{"direction":"down","by":10}}]',
        '[{"name":"adjust_brightness","arguments":{"direction":"down","amount":"slight"}}]',
        '[{"name":"set_brightness","arguments":{"level":0}}]',
        '[{"name":"nod","arguments":{"count":5}},{"name":"nod","arguments":{"count":5.0}}]',
        '[{"name":"shake","arguments":{"count":5}},{"name":"nod","arguments":{"count":5}}]',
        '[{"name":"look","arguments":{"direction":"down_right","degrees":180}}]',
```

- [ ] **Step 2: 照合が失敗することを確かめる**

Run: Task 3 の Step 6 の4つの command

Expected:
- `--write-cases` は v1 の fuzz を書く。
- `--host-results` は `mismatches` が空にならない（v1 の tool を C が `unknown tool` として扱うため）。

- [ ] **Step 3: `action.h` を v1 にする**

`#define ACT_MAX_CALLS 2` から `extern const char *const act_expr_names[EXPR_COUNT];` までを、次に替える（Task 2 の限界の define はそのまま残す）。

```c
#define ACT_MAX_CALLS 2
#define ACT_MAX_STEPS 24  // nod 5 and nod 5.0: 2 x (10 swings + 1 return)
#define ACT_NONE 0xFF      // act_call_t.amount when the call has a number instead

// The order of the names in jtalm.action.schema (TOOL_NAMES, DIRECTIONS, ...).
enum { ACT_LOOK, ACT_TURN, ACT_NOD, ACT_SHAKE, ACT_BOW, ACT_EXPR, ACT_LED, ACT_SET_VOLUME,
       ACT_ADJUST_VOLUME, ACT_SET_BRIGHTNESS, ACT_ADJUST_BRIGHTNESS, ACT_KIND_COUNT };
enum { DIR_LEFT, DIR_RIGHT, DIR_UP, DIR_DOWN, DIR_UP_LEFT, DIR_UP_RIGHT, DIR_DOWN_LEFT,
       DIR_DOWN_RIGHT, DIR_CENTER, DIR_COUNT };  // turn takes the first DIR_CENTER only
enum { AMT_SLIGHT, AMT_NORMAL, AMT_LARGE, AMT_COUNT };
enum { EXPR_HAPPY, EXPR_SAD, EXPR_SURPRISED, EXPR_NEUTRAL, EXPR_ANGRY, EXPR_SLEEPY, EXPR_DOUBT,
       EXPR_COUNT };
enum { COLOR_RED, COLOR_ORANGE, COLOR_YELLOW, COLOR_GREEN, COLOR_LIGHT_BLUE, COLOR_BLUE,
       COLOR_PURPLE, COLOR_PINK, COLOR_WHITE, COLOR_OFF, COLOR_COUNT };
enum { ADJ_UP, ADJ_DOWN, ADJ_COUNT };

// mapping.py: SHAKE_YAW_DEG, BOW_HOLD_MS, ADJUST_STEP, BRIGHTNESS_MIN
#define ACT_SHAKE_YAW_DEG 15
#define ACT_BOW_HOLD_MS 500
#define ACT_ADJUST_SLIGHT 10
#define ACT_ADJUST_NORMAL 20
#define ACT_ADJUST_LARGE 30
#define ACT_LEVEL_MAX 100
#define ACT_BRIGHTNESS_MIN 5  // 0 would hide the face
// Raw position of the neutral pose; 1 step = 0.3125 deg. Right (+yaw) lowers the yaw raw,
// up (+pitch) raises the pitch raw.
#define SERVO_YAW_ZERO 460
#define SERVO_PITCH_ZERO 620
// Motion profile: every move is a cosine ease (zero velocity at both ends) whose duration
// keeps the peak speed and acceleration under these limits, rounded up to the servo tick.
#define MOTION_VMAX_DPS 90.0
#define MOTION_AMAX_DPS2 360.0
// Nod and shake strokes are faster. With the cosine ease the acceleration limit decides the
// time of any stroke below 2*v^2/a degrees (here 50 deg): 14 deg takes 280 ms.
#define MOTION_NOD_VMAX_DPS 150.0
#define MOTION_NOD_AMAX_DPS2 900.0
#define MOTION_TICK_MS 20
#define MOTION_CALL_GAP_MS 200  // pause between the two calls of one request

typedef struct {
  uint8_t kind;       // ACT_*
  uint8_t dir;        // DIR_* (look, turn) or ADJ_* (adjust_*)
  uint8_t amount;     // AMT_*, or ACT_NONE when the call has a number (degrees, by)
  uint8_t expr;       // EXPR_* (set_expression)
  uint8_t color;      // COLOR_* (set_led)
  uint8_t num_float;  // the number was written as a float (2.0): Python's duplicate rule
                      // (json.dumps) tells 2 and 2.0 apart
  int16_t value;      // degrees, count, level or by; 0 when the call has none
} act_call_t;         // 8 bytes without padding: duplicates are found with memcmp

enum { STEP_MOVE, STEP_EXPR, STEP_LED, STEP_VOLUME, STEP_BRIGHTNESS, STEP_PAUSE };

typedef struct {
  uint8_t kind;     // STEP_*
  uint8_t call;     // index of the call that produced the step
  uint8_t arg;      // STEP_EXPR: EXPR_*, STEP_LED: COLOR_*, STEP_VOLUME / STEP_BRIGHTNESS:
                    // 1 when level is a change of the stored value (adjust_*)
  uint8_t clamped;  // STEP_MOVE: the target was outside the soft limits
  int16_t yaw, pitch;  // STEP_MOVE: target pose in degrees (right / up positive), clamped
  uint16_t yaw_raw, pitch_raw;
  uint16_t ms;    // STEP_MOVE: duration (0: already there); STEP_PAUSE: hold
  int16_t level;  // STEP_VOLUME / STEP_BRIGHTNESS: the level, or the change when arg is 1
} act_step_t;

typedef struct {
  int n_calls;
  act_call_t calls[ACT_MAX_CALLS];
  int n_steps;
  act_step_t steps[ACT_MAX_STEPS];
  int yaw0, pitch0, yaw1, pitch1;  // pose before and after
  uint32_t total_ms;               // moves, holds and the pause between calls
} act_plan_t;

extern const char *const act_tool_names[ACT_KIND_COUNT];
extern const char *const act_dir_names[DIR_COUNT];
extern const char *const act_amount_names[AMT_COUNT];
extern const char *const act_expr_names[EXPR_COUNT];
extern const char *const act_color_names[COLOR_COUNT];
extern const char *const act_adjust_names[ADJ_COUNT];
// RGB of each LED color, every channel 168 or less (the official firmware's safe range).
extern const uint8_t act_led_rgb[COLOR_COUNT][3];
```

`act_parse` の comment の "schema v0" を "schema v1" に替える。`act_print_body` の宣言の後に、次を足す。

```c
// The stored volume or brightness after a STEP_VOLUME / STEP_BRIGHTNESS step: the step's level,
// or the current value plus its change, within 0..100 (brightness: ACT_BRIGHTNESS_MIN..100).
int act_apply_level(int current, const act_step_t *s);
```

- [ ] **Step 4: `action.c` の名前の表を v1 にする**

file 先頭の3つの名前の表と `kYawDeg` / `kPitchDeg` を、次に替える。

```c
const char *const act_tool_names[ACT_KIND_COUNT] = {
    "look", "turn", "nod", "shake", "bow", "set_expression", "set_led", "set_volume",
    "adjust_volume", "set_brightness", "adjust_brightness"};
const char *const act_dir_names[DIR_COUNT] = {"left", "right", "up", "down", "up_left",
                                              "up_right", "down_left", "down_right", "center"};
const char *const act_amount_names[AMT_COUNT] = {"slight", "normal", "large"};
const char *const act_expr_names[EXPR_COUNT] = {"happy", "sad", "surprised", "neutral",
                                                "angry", "sleepy", "doubt"};
const char *const act_color_names[COLOR_COUNT] = {"red", "orange", "yellow", "green",
                                                  "light_blue", "blue", "purple", "pink",
                                                  "white", "off"};
const char *const act_adjust_names[ADJ_COUNT] = {"up", "down"};
const uint8_t act_led_rgb[COLOR_COUNT][3] = {
    {168, 0, 0},   {168, 60, 0}, {168, 140, 0},  {0, 168, 0},     {0, 140, 168},
    {0, 0, 168},   {110, 0, 168}, {168, 50, 100}, {100, 100, 100}, {0, 0, 0}};

static const int kYawDeg[AMT_COUNT] = {10, 20, 30};   // mapping.YAW_DEG
static const int kPitchDeg[AMT_COUNT] = {5, 10, 15};  // mapping.PITCH_DEG
static const int kAdjustStep[AMT_COUNT] = {ACT_ADJUST_SLIGHT, ACT_ADJUST_NORMAL,
                                           ACT_ADJUST_LARGE};  // mapping.ADJUST_STEP
// Sign of the yaw (right +) and pitch (up +) change for each direction; 0 keeps that axis.
static const int8_t kDirYaw[DIR_COUNT] = {-1, 1, 0, 0, -1, 1, -1, 1, 0};
static const int8_t kDirPitch[DIR_COUNT] = {0, 0, 1, -1, 1, 1, -1, -1, 0};
```

`js_number` の `// only 1..3 can be valid anyway` を `// only 0..180 can be valid anyway` に替える。

- [ ] **Step 5: `js_call` と `act_parse` を v1 にする**

`js_call` と `act_parse` を、次に替える（`js_members` は、`n == 0` で引数のない object だけを通す。今の実装のままで正しい）。

```c
// An integer for the schema (integral floats count, as in jsonschema) within lo..hi.
static int js_int(const js_t *j, int id, int lo, int hi, act_call_t *call) {
  const js_node_t *c = &j->nodes[id];
  if (c->type != JS_NUM || c->num != floor(c->num) || c->num < lo || c->num > hi) return -1;
  call->value = (int16_t)c->num;
  call->num_float = c->is_float;
  return 0;
}

// {"direction": <names>, "amount": ...} or {"direction": <names>, <num_key>: lo..hi}.
static const char *js_dir_and_size(const js_t *j, int args, const char *num_key, int lo,
                                   int hi, const char *const *names, int n_names,
                                   act_call_t *call) {
  const char *keys_amount[2] = {"direction", "amount"};
  const char *keys_num[2] = {"direction", num_key};
  int a[2];
  if (!js_members(j, args, keys_amount, 2, a)) {
    int amount = js_enum(j, a[1], act_amount_names, AMT_COUNT);
    if (amount < 0) return "amount enum";
    call->amount = (uint8_t)amount;
  } else if (!js_members(j, args, keys_num, 2, a)) {
    if (js_int(j, a[1], lo, hi, call)) return "number out of range";
  } else {
    return "arguments";
  }
  int dir = js_enum(j, a[0], names, n_names);
  if (dir < 0) return "direction enum";
  call->dir = (uint8_t)dir;
  return NULL;
}

static const char *js_call(const js_t *j, int item, act_call_t *call) {
  static const char *const kCallKeys[2] = {"name", "arguments"};
  static const char *const kExprKeys[1] = {"expression"};
  static const char *const kCountKeys[1] = {"count"};
  static const char *const kColorKeys[1] = {"color"};
  static const char *const kLevelKeys[1] = {"level"};
  int v[2], a[1];
  if (j->nodes[item].type != JS_OBJ) return "call is not an object";
  if (js_members(j, item, kCallKeys, 2, v)) return "call keys";
  int kind = js_enum(j, v[0], act_tool_names, ACT_KIND_COUNT);
  if (kind < 0) return "unknown tool";
  int args = v[1];
  if (j->nodes[args].type != JS_OBJ) return "arguments is not an object";
  memset(call, 0, sizeof(*call));
  call->kind = (uint8_t)kind;
  call->amount = ACT_NONE;
  const char *e = NULL;
  switch (kind) {
    case ACT_LOOK:
      e = js_dir_and_size(j, args, "degrees", 1, 180, act_dir_names, DIR_COUNT, call);
      if (!e && call->dir == DIR_CENTER && call->amount == ACT_NONE) e = "center with degrees";
      break;
    case ACT_TURN:  // relative: no center
      e = js_dir_and_size(j, args, "degrees", 1, 180, act_dir_names, DIR_CENTER, call);
      break;
    case ACT_NOD:
    case ACT_SHAKE:
      if (js_members(j, args, kCountKeys, 1, a) || js_int(j, a[0], 1, 5, call)) e = "count";
      break;
    case ACT_BOW:
      if (js_members(j, args, NULL, 0, a)) e = "bow takes no arguments";
      break;
    case ACT_EXPR: {
      int expr = js_members(j, args, kExprKeys, 1, a) ? -1
                                                      : js_enum(j, a[0], act_expr_names, EXPR_COUNT);
      if (expr < 0) e = "expression";
      call->expr = (uint8_t)(expr < 0 ? 0 : expr);
      break;
    }
    case ACT_LED: {
      int color = js_members(j, args, kColorKeys, 1, a)
                      ? -1
                      : js_enum(j, a[0], act_color_names, COLOR_COUNT);
      if (color < 0) e = "color";
      call->color = (uint8_t)(color < 0 ? 0 : color);
      break;
    }
    case ACT_SET_VOLUME:
    case ACT_SET_BRIGHTNESS:
      if (js_members(j, args, kLevelKeys, 1, a) || js_int(j, a[0], 0, ACT_LEVEL_MAX, call)) {
        e = "level";
      }
      break;
    default:  // ACT_ADJUST_VOLUME, ACT_ADJUST_BRIGHTNESS
      e = js_dir_and_size(j, args, "by", 1, ACT_LEVEL_MAX, act_adjust_names, ADJ_COUNT, call);
      break;
  }
  return e;
}

int act_parse(const char *s, size_t n, act_call_t *calls, int *n_calls, const char **err) {
  static js_t j;  // ~3KB: kept off the task stack (only the LM task parses)
  memset(&j, 0, sizeof(j));
  j.p = s;
  j.end = s + n;
  *n_calls = 0;
  int root = js_value(&j, 0);
  js_ws(&j);
  if (root < 0 || j.p != j.end) {
    *err = "not valid JSON";
    return -1;
  }
  if (j.nodes[root].type != JS_ARR) {
    *err = "top level is not a JSON array";
    return -1;
  }
  int k = 0;
  for (int item = j.nodes[root].child; item >= 0; item = j.nodes[item].next) {
    if (k == ACT_MAX_CALLS) {
      *err = "more than 2 calls";
      return -1;
    }
    const char *e = js_call(&j, item, &calls[k]);
    if (e) {
      *err = e;
      return -1;
    }
    for (int i = 0; i < k; i++) {
      if (!memcmp(&calls[i], &calls[k], sizeof(calls[k]))) {
        *err = "duplicate call";
        return -1;
      }
    }
    k++;
  }
  *n_calls = k;
  return 0;
}
```

注: `center` に `amount` を付けた look（`large` など）は、v0 と同じく有効で、正面 (0, 0) に向く。`center` と `degrees` の組み合わせは無効。この規則が LM 側の `action_schema_v1.json` と違う場合は、Step 8 の照合で `valid` の不一致として現れる。そのときは schema の側（spec 4.1 の「center は amount が normal のときだけ」の扱い）を LM 側の計画の担当と確かめてから、C をそれに合わせる。

- [ ] **Step 6: 計画（planner）を v1 にする**

`add_move` の後ろから `act_plan` の終わりまでを、次に替える（`add_move` は、引数 `nod` の名前を `swing` に替えるだけで、中身は同じ）。

```c
static act_step_t *add_step(act_plan_t *p, int call, int kind, int yaw, int pitch) {
  if (p->n_steps >= ACT_MAX_STEPS) return NULL;
  act_step_t *s = &p->steps[p->n_steps++];
  memset(s, 0, sizeof(*s));
  s->kind = (uint8_t)kind;
  s->call = (uint8_t)call;
  s->yaw = (int16_t)yaw;
  s->pitch = (int16_t)pitch;
  return s;
}

// Size of a look / turn / adjust call: the amount's table entry or its number.
static int call_size(const act_call_t *c, const int *table) {
  return c->amount == ACT_NONE ? c->value : table[c->amount];
}

void act_plan(act_plan_t *p, int yaw, int pitch) {
  p->n_steps = 0;
  p->total_ms = 0;
  p->yaw0 = yaw;
  p->pitch0 = pitch;
  for (int c = 0; c < p->n_calls; c++) {
    const act_call_t *call = &p->calls[c];
    if (c > 0) p->total_ms += MOTION_CALL_GAP_MS;
    act_step_t *s = NULL;
    switch (call->kind) {
      case ACT_LOOK:
      case ACT_TURN: {
        // mapping.plan_v1: look sets the axes the direction names (from the neutral pose),
        // turn adds the same amounts to the current pose; center sets both axes to 0.
        int y = yaw, pt = pitch;
        if (call->dir == DIR_CENTER) {
          y = 0, pt = 0;
        } else {
          int base_y = call->kind == ACT_TURN ? yaw : 0;
          int base_p = call->kind == ACT_TURN ? pitch : 0;
          if (kDirYaw[call->dir]) y = base_y + kDirYaw[call->dir] * call_size(call, kYawDeg);
          if (kDirPitch[call->dir]) {
            pt = base_p + kDirPitch[call->dir] * call_size(call, kPitchDeg);
          }
        }
        add_move(p, c, y, pt, &yaw, &pitch, 0);
        break;
      }
      case ACT_NOD: {
        // mapping.nod_targets: a swing of NOD_PITCH_DEG down from the current pitch and back,
        // `count` times; near the lower limit it keeps its amplitude by moving up. It ends at
        // the start pitch.
        int start = pitch;
        int low = start - ACT_NOD_PITCH_DEG;
        if (low < PITCH_MIN) low = PITCH_MIN;
        int high = low + ACT_NOD_PITCH_DEG;
        if (high > PITCH_MAX) high = PITCH_MAX;
        for (int i = 0; i < call->value; i++) {
          add_move(p, c, yaw, low, &yaw, &pitch, 1);
          add_move(p, c, yaw, high, &yaw, &pitch, 1);
        }
        if (high != start) add_move(p, c, yaw, start, &yaw, &pitch, 1);
        break;
      }
      case ACT_SHAKE: {
        // mapping.plan_v1: right then left of the current yaw, `count` times, then back.
        int start = yaw;
        for (int i = 0; i < call->value; i++) {
          add_move(p, c, start + ACT_SHAKE_YAW_DEG, pitch, &yaw, &pitch, 1);
          add_move(p, c, start - ACT_SHAKE_YAW_DEG, pitch, &yaw, &pitch, 1);
        }
        add_move(p, c, start, pitch, &yaw, &pitch, 1);
        break;
      }
      case ACT_BOW: {
        int start = pitch;
        add_move(p, c, yaw, PITCH_MIN, &yaw, &pitch, 0);
        s = add_step(p, c, STEP_PAUSE, yaw, pitch);
        if (s) {
          s->ms = ACT_BOW_HOLD_MS;
          p->total_ms += ACT_BOW_HOLD_MS;
        }
        add_move(p, c, yaw, start, &yaw, &pitch, 0);
        break;
      }
      case ACT_EXPR:
        s = add_step(p, c, STEP_EXPR, yaw, pitch);
        if (s) s->arg = call->expr;
        break;
      case ACT_LED:
        s = add_step(p, c, STEP_LED, yaw, pitch);
        if (s) s->arg = call->color;
        break;
      case ACT_SET_VOLUME:
      case ACT_SET_BRIGHTNESS:
        s = add_step(p, c, call->kind == ACT_SET_VOLUME ? STEP_VOLUME : STEP_BRIGHTNESS, yaw,
                     pitch);
        if (s) s->level = call->value;
        break;
      default: {  // ACT_ADJUST_VOLUME, ACT_ADJUST_BRIGHTNESS
        int size = call_size(call, kAdjustStep);
        s = add_step(p, c, call->kind == ACT_ADJUST_VOLUME ? STEP_VOLUME : STEP_BRIGHTNESS, yaw,
                     pitch);
        if (s) {
          s->arg = 1;
          s->level = (int16_t)(call->dir == ADJ_UP ? size : -size);
        }
        break;
      }
    }
  }
  p->yaw1 = yaw;
  p->pitch1 = pitch;
}

int act_apply_level(int current, const act_step_t *s) {
  int lo = s->kind == STEP_BRIGHTNESS ? ACT_BRIGHTNESS_MIN : 0;
  return clampi(s->arg ? current + s->level : s->level, lo, ACT_LEVEL_MAX);
}
```

- [ ] **Step 7: `act` の記録の calls と steps を v1 にする**

`action.c` の `print_call` と `print_step` を、次に替える。

```c
static void print_call(FILE *f, const act_call_t *c) {
  fprintf(f, "{\"name\":\"%s\",\"arguments\":{", act_tool_names[c->kind]);
  switch (c->kind) {
    case ACT_LOOK:
    case ACT_TURN:
      fprintf(f, "\"direction\":\"%s\",", act_dir_names[c->dir]);
      if (c->amount == ACT_NONE) {
        fprintf(f, "\"degrees\":%d", c->value);
      } else {
        fprintf(f, "\"amount\":\"%s\"", act_amount_names[c->amount]);
      }
      break;
    case ACT_NOD:
    case ACT_SHAKE:
      fprintf(f, "\"count\":%d", c->value);
      break;
    case ACT_BOW:
      break;
    case ACT_EXPR:
      fprintf(f, "\"expression\":\"%s\"", act_expr_names[c->expr]);
      break;
    case ACT_LED:
      fprintf(f, "\"color\":\"%s\"", act_color_names[c->color]);
      break;
    case ACT_SET_VOLUME:
    case ACT_SET_BRIGHTNESS:
      fprintf(f, "\"level\":%d", c->value);
      break;
    default:
      fprintf(f, "\"direction\":\"%s\",", act_adjust_names[c->dir]);
      if (c->amount == ACT_NONE) {
        fprintf(f, "\"by\":%d", c->value);
      } else {
        fprintf(f, "\"amount\":\"%s\"", act_amount_names[c->amount]);
      }
      break;
  }
  fputs("}}", f);
}

static void print_step(FILE *f, const act_step_t *s) {
  switch (s->kind) {
    case STEP_MOVE:
      fprintf(f,
              "{\"c\":%d,\"k\":\"move\",\"yaw\":%d,\"pitch\":%d,\"yaw_raw\":%d,\"pitch_raw\":%d"
              ",\"ms\":%d,\"clamped\":%d}",
              s->call, s->yaw, s->pitch, s->yaw_raw, s->pitch_raw, s->ms, s->clamped);
      break;
    case STEP_EXPR:
      fprintf(f, "{\"c\":%d,\"k\":\"expr\",\"expr\":\"%s\"}", s->call, act_expr_names[s->arg]);
      break;
    case STEP_LED:
      fprintf(f, "{\"c\":%d,\"k\":\"led\",\"color\":\"%s\"}", s->call, act_color_names[s->arg]);
      break;
    case STEP_PAUSE:
      fprintf(f, "{\"c\":%d,\"k\":\"pause\",\"ms\":%d}", s->call, s->ms);
      break;
    default:
      fprintf(f, "{\"c\":%d,\"k\":\"%s\",\"%s\":%d}", s->call,
              s->kind == STEP_VOLUME ? "volume" : "brightness", s->arg ? "delta" : "level",
              s->level);
      break;
  }
}
```

`servo.c` の `run_plan` の `board_face(s->expr, &f)` と `act_expr_names[s->expr]` を、`s->arg` に替える（新しい step の実行は Task 5）。

- [ ] **Step 8: host で照合が通ることを確かめる**

Run: Task 3 の Step 6 と同じ4つの command

Expected:
- compile の warning がない。
- `"match": 3000`、`"mismatches": []`。

不一致が出たら、`valid` の不一致（schema の解釈の違い）か、`steps` の不一致（計画の違い）かを分け、`mapping.plan_v1` の上の定義と照らして C を直す。Python の側が上の定義と違う場合は、LM 側の計画の担当に知らせる。

- [ ] **Step 9: firmware の build が通ることを確かめる**

Run: Task 1 の Step 5 と同じ

Expected: build が通る。`servo.c` の新しい step は、まだ実行しない（Task 5）。

- [ ] **Step 10: lint と Commit**

```bash
uv run --only-dev ruff check src tests firmware/tools && uv run --only-dev ruff format --check src tests firmware/tools
git add firmware/jtalm_action/main/action.h firmware/jtalm_action/main/action.c \
  firmware/jtalm_action/main/servo.c firmware/tools/dispatch_check.py
git commit -m "firmware: Action schema v1 validator and planner (look/turn with amount or degrees, diagonals, nod/shake 1-5, bow, 7 expressions, LED, volume, brightness); host fuzz 3,000/3,000 equal to mapping.plan_v1"
```

---

### Task 5（F3）: 新しい step を実機で実行する（顔、LED、音量、明るさ、保持、NVS）

**Files:**
- Create: `firmware/jtalm_action/main/settings.h` / `settings.c`
- Modify: `firmware/jtalm_action/main/CMakeLists.txt`
- Modify: `firmware/jtalm_action/main/board.h` / `board.cpp`（3つの顔、speaker、明るさ）
- Modify: `firmware/jtalm_action/main/servo.h` / `servo.c`（step の実行、設定の保存）
- Modify: `firmware/jtalm_action/main/main.c`（起動時の設定、`settings` の記録）
- Modify: `firmware/tools/servo_test.py`（v1 の項目、設定の値の自動検査）
- Modify: `firmware/tools/dispatch_check.py`（`check_log` が `setting` の記録を数える）

**Interfaces:**
- Consumes: `act_led_rgb`、`act_apply_level`、`STEP_*`（Task 4）、`board_led`（Task 1）。
- Produces（C）:
  - `typedef struct { uint8_t volume, brightness, led; } settings_t;`
  - `int settings_init(void);`、`void settings_load(settings_t *s);`（範囲外と、ない key は既定値のまま）、`int settings_save(const settings_t *s);`
  - `int board_volume(int level, int beep);`、`int board_brightness(int level);`、`int board_brightness_level(void);`
  - `void servo_set_settings(const settings_t *s);`
- Produces（serial）:
  - `JTALM {"t":"setting","seq":N,"what":"volume"|"brightness","level":L,"ok":0|1}`
  - `JTALM {"t":"setting","seq":N,"what":"led","color":"blue","ok":0|1}`
  - 起動時の `JTALM {"t":"settings","volume":V,"brightness":B,"led":"off","nvs":0|1}`

- [ ] **Step 1: `settings.h` / `settings.c` を作る**

`firmware/jtalm_action/main/settings.h`:

```c
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
//
// Volume, screen brightness and the base LED color, kept in NVS so that they survive a reset.

#pragma once

#include <stdint.h>

typedef struct {
  uint8_t volume;      // 0..100
  uint8_t brightness;  // ACT_BRIGHTNESS_MIN..100
  uint8_t led;         // COLOR_*
} settings_t;

// nvs_flash_init (erasing the NVS partition if it is full or from a newer format). 0 on success.
int settings_init(void);

// Overwrites the fields of *s that NVS holds with a valid value; the others keep their value.
void settings_load(settings_t *s);

// Stores all fields. 0 on success.
int settings_save(const settings_t *s);
```

`firmware/jtalm_action/main/settings.c`:

```c
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
//
// Settings in NVS (see settings.h): namespace "jtalm", keys "volume", "bright", "led" (u8).

#include "settings.h"

#include "action.h"
#include "nvs.h"
#include "nvs_flash.h"

#define NS "jtalm"

int settings_init(void) {
  esp_err_t e = nvs_flash_init();
  if (e == ESP_ERR_NVS_NO_FREE_PAGES || e == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    nvs_flash_erase();
    e = nvs_flash_init();
  }
  return e == ESP_OK ? 0 : -1;
}

void settings_load(settings_t *s) {
  nvs_handle_t h;
  if (nvs_open(NS, NVS_READONLY, &h) != ESP_OK) return;
  uint8_t v;
  if (nvs_get_u8(h, "volume", &v) == ESP_OK && v <= ACT_LEVEL_MAX) s->volume = v;
  if (nvs_get_u8(h, "bright", &v) == ESP_OK && v >= ACT_BRIGHTNESS_MIN && v <= ACT_LEVEL_MAX) {
    s->brightness = v;
  }
  if (nvs_get_u8(h, "led", &v) == ESP_OK && v < COLOR_COUNT) s->led = v;
  nvs_close(h);
}

int settings_save(const settings_t *s) {
  nvs_handle_t h;
  if (nvs_open(NS, NVS_READWRITE, &h) != ESP_OK) return -1;
  esp_err_t e = nvs_set_u8(h, "volume", s->volume);
  if (e == ESP_OK) e = nvs_set_u8(h, "bright", s->brightness);
  if (e == ESP_OK) e = nvs_set_u8(h, "led", s->led);
  if (e == ESP_OK) e = nvs_commit(h);
  nvs_close(h);
  return e == ESP_OK ? 0 : -1;
}
```

`CMakeLists.txt` の `SRCS` に `"settings.c"` を、`PRIV_REQUIRES` に `nvs_flash` を足す。

```cmake
idf_component_register(SRCS "main.c" "action.c" "servo.c" "board.cpp" "settings.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES jtalm esp_partition esp_psram esp_timer spi_flash mbedtls
                                     esp_driver_usb_serial_jtag esp_driver_uart esp_driver_tsens vfs
                                     esp_app_format nvs_flash M5Unified m5gfx)
```

- [ ] **Step 2: `board.cpp` に3つの顔、speaker、明るさを足す**

`draw_face` の `switch` の `default:` の前に、次を足す。

```cpp
    case EXPR_ANGRY:
      for (int x : ex) c.fillCircle(x, 108, 12, fg);
      c.drawWideLine(78, 76, 118, 90, 3.0f, fg);   // eyebrows, lowered at the inner ends
      c.drawWideLine(202, 90, 242, 76, 3.0f, fg);
      c.fillArc(160, 200, 30, 24, 210, 330, fg);   // small frown
      break;
    case EXPR_SLEEPY:
      for (int x : ex) c.fillRoundRect(x - 18, 104, 36, 6, 3, fg);  // closed eyes
      c.fillEllipse(160, 176, 8, 6, fg);                             // small "o" mouth
      break;
    case EXPR_DOUBT:
      c.fillCircle(ex[0], 104, 14, fg);
      c.fillCircle(ex[1], 98, 9, fg);              // one eye smaller and higher
      c.drawWideLine(204, 74, 240, 66, 3.0f, fg);  // one raised eyebrow
      c.drawWideLine(130, 178, 190, 166, 3.0f, fg);  // tilted mouth
      break;
```

`board_init` の `cfg.internal_spk = false;` を `cfg.internal_spk = true;` に替え、`M5.Display.setRotation(1);` の次に、次を足す。

```cpp
  M5.Speaker.begin();  // CoreS3 speaker (AW88298) for the volume confirmation beep
```

`board.h` の file 先頭の comment の `(no speaker, mic, IMU or RTC)` を `(speaker on; no mic, IMU or RTC)` に替え、`board_touched` の宣言の前に、次を足す。

```c
// Speaker volume 0..100 (M5.Speaker 0..255); beep: a short tone at the new volume (none at 0).
int board_volume(int level, int beep);

// Backlight 0..100 (M5.Display 0..255).
int board_brightness(int level);

// The present backlight as 0..100 (the boot default when NVS has none).
int board_brightness_level(void);
```

`board.cpp` の最後に、次を足す。

```cpp
extern "C" int board_volume(int level, int beep) {
  M5.Speaker.setVolume((uint8_t)lround(level * 255.0 / 100.0));
  if (beep && level > 0) M5.Speaker.tone(1000, 80);
  return 0;
}

extern "C" int board_brightness(int level) {
  if (g_gfx_lock == nullptr) return -1;
  xSemaphoreTake(g_gfx_lock, portMAX_DELAY);
  M5.Display.setBrightness((uint8_t)lround(level * 255.0 / 100.0));
  xSemaphoreGive(g_gfx_lock);
  return 0;
}

extern "C" int board_brightness_level(void) {
  return (int)lround(M5.Display.getBrightness() * 100.0 / 255.0);
}
```

（`board.cpp` の include に `#include <math.h>` を足す。）

- [ ] **Step 3: `servo.c` で新しい step を実行し、設定を保存する**

`servo.h` の `servo_status` の前に、次を足す。

```c
#include "settings.h"

// The settings the dispatcher starts from (applied by the caller); later steps change them and
// the dispatcher stores them in NVS after each plan that changed one.
void servo_set_settings(const settings_t *s);
```

`servo.c` の include に `#include "settings.h"` を足し、static 変数の並びに次を足す。

```c
static settings_t g_settings;  // dispatcher task only (after servo_set_settings)
```

`run_plan` の step の loop の `if (s->kind == STEP_EXPR) { ... } else { move_to(...); }` を、次に替える。

```c
    if (s->kind == STEP_EXPR) {
      face_info_t f;
      int err = board_face(s->arg, &f);
      out_lock();
      printf(
          "JTALM {\"t\":\"face\",\"seq\":%" PRIu32 ",\"expr\":\"%s\",\"ok\":%d"
          ",\"crc\":\"%08" PRIx32 "\",\"draw_us\":%" PRIu32 ",\"push_us\":%" PRIu32 "}\n",
          m->seq, act_expr_names[s->arg], err == 0, f.crc, f.draw_us, f.push_us
      );
      out_unlock();
    } else if (s->kind == STEP_LED) {
      const uint8_t *rgb = act_led_rgb[s->arg];
      int err = board_led(rgb[0], rgb[1], rgb[2]);
      g_settings.led = s->arg;
      changed = 1;
      out_lock();
      printf("JTALM {\"t\":\"setting\",\"seq\":%" PRIu32 ",\"what\":\"led\",\"color\":\"%s\""
             ",\"ok\":%d}\n", m->seq, act_color_names[s->arg], err == 0);
      out_unlock();
    } else if (s->kind == STEP_VOLUME || s->kind == STEP_BRIGHTNESS) {
      int bright = s->kind == STEP_BRIGHTNESS;
      int level = act_apply_level(bright ? g_settings.brightness : g_settings.volume, s);
      int err = bright ? board_brightness(level) : board_volume(level, 1);
      if (bright) {
        g_settings.brightness = (uint8_t)level;
      } else {
        g_settings.volume = (uint8_t)level;
      }
      changed = 1;
      out_lock();
      printf("JTALM {\"t\":\"setting\",\"seq\":%" PRIu32 ",\"what\":\"%s\",\"level\":%d"
             ",\"ok\":%d}\n", m->seq, bright ? "brightness" : "volume", level, err == 0);
      out_unlock();
    } else if (s->kind == STEP_PAUSE) {
      pause_ms(&r, s->ms);
    } else {
      move_to(&r, s->yaw, s->pitch, s->ms);
    }
```

`run_plan` の先頭の `int sync_ms = 0;` の次に `int changed = 0;` を足す。`act_done` の printf と `out_unlock();` の後、`if (r.err) fault(r.err);` の前に、次を足す（NVS への書き込みは watchdog の対象外で、計画の後に行う）。

```c
  if (changed && settings_save(&g_settings) != 0) {
    out_lock();
    printf("JTALM {\"t\":\"error\",\"msg\":\"settings save failed\"}\n");
    out_unlock();
  }
```

file の最後に、次を足す。

```c
void servo_set_settings(const settings_t *s) { g_settings = *s; }
```

- [ ] **Step 4: `main.c` で起動時に設定を読み、適用する**

`boot_board()` の `if (servo_start() != 0) ...` の前に、次を足す。

```c
  // Volume, brightness and LED color from NVS (defaults: 50, the boot backlight, off).
  int nvs = settings_init() == 0;
  settings_t st = {.volume = 50, .brightness = (uint8_t)board_brightness_level(),
                   .led = COLOR_OFF};
  if (st.brightness < ACT_BRIGHTNESS_MIN) st.brightness = ACT_BRIGHTNESS_MIN;
  if (nvs) settings_load(&st);
  board_volume(st.volume, 0);
  board_brightness(st.brightness);
  board_led(act_led_rgb[st.led][0], act_led_rgb[st.led][1], act_led_rgb[st.led][2]);
  servo_set_settings(&st);
  printf("JTALM {\"t\":\"settings\",\"volume\":%d,\"brightness\":%d,\"led\":\"%s\",\"nvs\":%d}\n",
         st.volume, st.brightness, act_color_names[st.led], nvs);
```

`main.c` の include に `#include "settings.h"` を足す。file 先頭の comment に、v1 の動作（7つの顔、LED、音量、明るさ、NVS）を1段落で足す。

- [ ] **Step 5: `dispatch_check.py` の `check_log` に設定の記録を足す**

`check_log` の `for a in acts:` の loop の中、`n_face` の検査の次に、次を足す。

```python
        n_set = sum(s["k"] in ("led", "volume", "brightness") for s in a["steps"])
        n_rec = sum(r.get("t") == "setting" and r.get("seq") == a["seq"] for r in recs)
        if n_set != n_rec:
            problems.append(f"seq {a['seq']}: {n_set} setting steps, {n_rec} setting records")
        bad = [r for r in recs if r.get("t") == "setting" and r.get("seq") == a["seq"]
               and not r.get("ok")]  # fmt: skip
        if bad:
            problems.append(f"seq {a['seq']}: setting failed {bad}")
```

- [ ] **Step 6: `servo_test.py` に v1 の項目と、設定の値の検査を足す**

helper の関数（`expr` の後）に、次を足す。

```python
def turn(direction: str, amount: str | None = None, degrees: int | None = None) -> dict:
    size = {"degrees": degrees} if degrees is not None else {"amount": amount or "normal"}
    return {"name": "turn", "arguments": {"direction": direction, **size}}


def look_deg(direction: str, degrees: int) -> dict:
    return {"name": "look", "arguments": {"direction": direction, "degrees": degrees}}


def tool(name: str, **arguments: object) -> dict:
    return {"name": name, "arguments": arguments}
```

`ACT_ITEMS` の後に、v1 の項目を足す。3つ目の要素は、`setting` の記録で期待する値（ない項目は `None`）。

```python
# Part C (v1): no motion. Faces, LED, volume (a beep) and brightness; the expected settings
# are checked from the device's "setting" records.
SETTING_ITEMS = [
    ("表情: angry → sleepy", act([expr("angry"), expr("sleepy")]), None),
    ("表情: doubt → neutral", act([expr("doubt"), expr("neutral")]), None),
    ("LED: 青", act([tool("set_led", color="blue")]), {"led": "blue"}),
    ("LED: 水色 → ピンク", act([tool("set_led", color="light_blue"),
                               tool("set_led", color="pink")]), {"led": "pink"}),  # fmt: skip
    ("LED: 消灯", act([tool("set_led", color="off")]), {"led": "off"}),
    ("音量 50（ピッ）", act([tool("set_volume", level=50)]), {"volume": 50}),
    ("音量 +20 → +100 は 100 で止まる", act([tool("adjust_volume", direction="up", amount="normal"),
                                          tool("adjust_volume", direction="up", by=100)]),
     {"volume": 100}),  # fmt: skip
    ("消音（鳴らない）", act([tool("set_volume", level=0)]), {"volume": 0}),
    ("音量 50 に戻す", act([tool("set_volume", level=50)]), {"volume": 50}),
    ("明るさ 0 は下限 5 になる（顔は見える）", act([tool("set_brightness", level=0)]),
     {"brightness": 5}),  # fmt: skip
    ("明るさ 5 で暗く → 5 のまま", act([tool("adjust_brightness", direction="down", amount="large")]),
     {"brightness": 5}),  # fmt: skip
    ("明るさ 80", act([tool("set_brightness", level=80)]), {"brightness": 80}),
]

# Part D (v1): head motion (look with degrees, turn, diagonals, shake, bow).
MOTION_ITEMS = [
    ("右に 45°（絶対）", act([look_deg("right", 45)])),
    ("さらに右（端なので clamped、動かない）", act([turn("right", "slight")])),
    ("正面", act([look("center")])),
    ("上に 90°（上限で止まる、clamped）", act([look_deg("up", 90)])),
    ("正面", act([look("center")])),
    ("今の向きから左に 20°", act([turn("left", degrees=20)])),
    ("右上（normal）", act([look("up_right")])),
    ("左下に 10°", act([look_deg("down_left", 10)])),
    ("正面", act([look("center")])),
    ("首を横に 2回振る", act([tool("shake", count=2)])),
    ("お辞儀", act([tool("bow")])),
    ("うなずき 5回", act([nod(5)])),
    ("正面", act([look("center")])),
]
```

`run_item` の引数に `want: dict | None = None` を足し、`done` を待った後（`if done["aborted"] ...` の後）に、次を足す。

```python
        if want:
            got = {}
            for r in keep + dev.pending:
                if r.get("t") == "setting" and r.get("seq") == a["seq"]:
                    got[r["what"]] = r.get("level", r.get("color"))
            print(f"    settings: {got}", flush=True)
            if any(got.get(k) != v for k, v in want.items()):
                raise Stopped(f"settings: want {want}, got {got}")
```

（`keep` は `check(keep)` で消える前に読む必要があるので、`done = dev.wait_for(...)` の直後、`check(keep)` の前に置く。）

`main()` の `--section` の choices を `["act", "lm", "setting", "motion", "all"]` にし、items を作る部分を次に替える。

```python
    if args.section in ("act", "all"):
        items += [(label, line, None, None) for label, line in ACT_ITEMS]
    if args.section in ("setting", "all"):
        items += [(label, line, None, want) for label, line, want in SETTING_ITEMS]
    if args.section in ("motion", "all"):
        items += [(label, line, None, None) for label, line in MOTION_ITEMS]
    if args.section in ("lm", "all"):
        items += [(text, text, expect, None) for text, expect in LM_ITEMS]
```

loop を `for i, (label, line, expect, want) in enumerate(items):` にし、`run_item(dev, label, line, expect, f, keep, want)` を呼ぶ。`--only` の絞り込みは `it[0]` と `it[1]` のままでよい。

- [ ] **Step 7: host の照合と build**

Run:
- Task 3 の Step 6 の4つの command
- Task 1 の Step 5 の build

Expected:
- 照合は 3000 / 3000（計画は Task 4 のまま）。
- build が通る。

- [ ] **Step 8: NVS が空の状態から起動することを確かめる（Review Focus 4）**

NVS の領域だけを消してから、app を書き込む。

```bash
uvx --from esptool esptool --chip esp32s3 -p COM3 -b 921600 erase-region 0x9000 0x6000
cd firmware/jtalm_action/build && uvx --from esptool esptool --chip esp32s3 -p COM3 -b 921600 \
  write-flash --flash-mode dio --flash-size 16MB --flash-freq 80m \
  0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x10000 jtalm_action.bin
cd ../../.. && uv run --no-project --with pyserial python firmware/tools/serial_capture.py \
  --port COM3 --reset --seconds 15 --out runs/fw/t5_boot_blank_nvs.log
```

Expected: log に次の行がある。

- `"t":"settings","volume":50,"brightness":<起動時の値>,"led":"off","nvs":1`
- `"t":"board","ok":1,...,"led_init":1`
- `"t":"ready"`

- [ ] **Step 9: 利用者の確認（チェックポイント）: 顔、LED、音、明るさ（首は動かない）**

利用者に、画面、台座の LED、音を見聞きしてもらう準備ができてから実行する。

Run: `uv run --no-project --with pyserial python firmware/tools/servo_test.py --port COM3 --section setting --pause 3 --out runs/fw/t5_setting.jsonl`

Expected:
- 各項目の `settings:` が期待の値と一致する（違えば `STOPPED`）。
- 最後は `sequence finished`。

利用者に、次の点を聞く。
1. 怒った顔、眠そうな顔、不思議そうな顔が、それぞれそう見えるか。
2. LED が青、水色からピンク、消灯の順に変わったか。
3. 音量 50 と 100 でピッと鳴り、消音では鳴らなかったか。
4. 明るさ 0 の指示でも顔が見えていたか。

直したい点（顔の形、色味、音の大きさ）があれば、`draw_face`、`act_led_rgb`、`board_volume` の tone を直し、この Step をやり直す。`act_led_rgb` を変えた場合も、Python の側の値は持たないので、照合への影響はない。

続けて、再起動しても設定が残ることを確かめる。

Run: `uv run --no-project --with pyserial python firmware/tools/serial_capture.py --port COM3 --reset --seconds 15 --out runs/fw/t5_boot_after.log`

Expected: `"t":"settings","volume":50,"brightness":80,"led":"off","nvs":1`（Part C の最後の値）。

- [ ] **Step 10: lint と Commit**

```bash
uv run --only-dev ruff check src tests firmware/tools && uv run --only-dev ruff format --check src tests firmware/tools
git add firmware/jtalm_action/main firmware/tools/servo_test.py firmware/tools/dispatch_check.py
git commit -m "firmware: v1 steps on the device (angry/sleepy/doubt faces, base LED colors, speaker volume with a beep, backlight with a floor of 5, bow hold), settings kept in NVS; checked with the user"
```

---

### Task 6（F3）: 首の新しい動きを実機で確かめる（turn、斜め、角度、首振り、お辞儀、停止）

**Files:**
- Modify: `firmware/tools/servo_test.py`（停止の確認 `--stop-during-bow`）
- 結果: `runs/fw/`（記録）。まとめは Task 8 で `results/` に書く。

**Interfaces:**
- Consumes: Task 4 の計画、Task 5 の実行、Task 2 の可動域。

- [ ] **Step 1: `servo_test.py` に、お辞儀の保持中に止める確認を足す**

`main()` の引数に、次を足す。

```python
    ap.add_argument("--stop-during-bow", action="store_true",
                    help="send !stop while the bow holds; checks that the stop is immediate")  # fmt: skip
```

`main()` の `try:` の中、`if args.servo:` の処理の後に、次を足す（この flag のときは、他の項目を流さない）。

```python
            if args.stop_during_bow:
                dev.send(act([tool("bow")]))
                a = dev.wait_for("act", 10.0, keep)
                down_ms = a["steps"][0]["ms"]
                time.sleep((down_ms + 250) / 1000)  # in the 500 ms hold
                t0 = time.monotonic()
                dev.send("!stop")
                stop = dev.wait_for("stop", 2.0, keep)
                done = dev.wait_for("act_done", 2.0, keep)
                ms = (time.monotonic() - t0) * 1000
                print(f"stop: {stop}\nact_done: aborted={done['aborted']} in {ms:.0f} ms",
                      flush=True)  # fmt: skip
                if not done["aborted"] or stop.get("vm_off") != 0 or ms > 500:
                    raise Stopped("bow was not stopped at once")
                items = []
```

（`items = []` で、続く項目の loop を空にする。`!stop` の後は servo が off なので、最後の `!center` は dry-run になる。）

- [ ] **Step 2: dry-run で計画を確かめる**

Run: `uv run --no-project --with pyserial python firmware/tools/servo_test.py --port COM3 --section motion --pause 0.5 --out runs/fw/t6_motion_dry.jsonl`

Expected:
- `sequence finished`。
- 「さらに右」と「上に 90°」の項目の plan に `(clamped)` が付く。

- [ ] **Step 3: host と実機で fuzz の照合をする**

Run: `uv run --with pyserial python firmware/tools/dispatch_check.py --port COM3 --fuzz 600 --out runs/fw/t6_fuzz.jsonl`

Expected: `"match": 600`、`"mismatches": []`。

- [ ] **Step 4: 利用者の確認（チェックポイント）: 首の動き**

利用者に「首が、右 45°、上（上限まで）、斜め、首振り、お辞儀、うなずき 5回の順に動きます。気になったら画面に触れて止めてください」と伝え、準備ができてから実行する。

Run: `uv run --no-project --with pyserial python firmware/tools/servo_test.py --port COM3 --servo --section motion --pause 3 --out runs/fw/t6_motion.jsonl`

Expected:
- `sequence finished`。
- 各項目の `done:` で `planned` との差が 150ms 以内。
- `final:` で servo が off。

利用者に、次の点を聞く。
1. 各項目が表示どおりの向き、量に見えたか。
2. 首振りとお辞儀の速さと深さはよいか。
3. 「さらに右」で動かなかったか。

首振りの振れ幅、お辞儀の保持時間を変えたい場合は、`ACT_SHAKE_YAW_DEG` / `ACT_BOW_HOLD_MS` と、LM 側の `mapping.SHAKE_YAW_DEG` / `BOW_HOLD_MS` を同じ値に直し（`Policy` が一致を確かめる）、Task 4 の Step 8 とこの Step をやり直す。

- [ ] **Step 5: 利用者の確認（チェックポイント）: お辞儀の途中での停止（Review Focus 3）**

Run: `uv run --no-project --with pyserial python firmware/tools/servo_test.py --port COM3 --servo --stop-during-bow --out runs/fw/t6_stop_bow.jsonl`

Expected:
- `act_done: aborted=True`、500ms 以内。
- `stop` の `vm_off` が 0（電源を切る処理が成功）。
- 首は下を向いたまま、力が抜けた状態で止まる（利用者が目で確かめる）。

続けて、利用者に画面に触れてもらう確認を、お辞儀の項目で1回行う。

Run: `uv run --no-project --with pyserial python firmware/tools/servo_test.py --port COM3 --servo --section motion --only お辞儀 --out runs/fw/t6_touch_bow.jsonl`

利用者に、お辞儀の最中に画面に触れてもらう。Expected: `STOPPED: ... stop ...` で終わり、`final:` で servo が off。

- [ ] **Step 6: Commit**

```bash
uv run --only-dev ruff check firmware/tools && uv run --only-dev ruff format --check firmware/tools
git add firmware/tools/servo_test.py
git commit -m "servo_test: v1 motion items and a stop during the bow hold; device fuzz 600/600, motion and stops checked with the user"
```

---

### Task 7: `stackchan_chat.py` で v1 の出力を日本語で表示する

**Files:**
- Modify: `firmware/tools/stackchan_chat.py`
- Create: `tests/test_stackchan_chat.py`

**Interfaces:**
- Produces: `stackchan_chat.describe(output: str) -> str`（出力の JSON を日本語の短い説明にする。`[]` は「何もしない」）。`release.py`（LM 側の L6）がこの file を HF の配布物に copy する。

- [ ] **Step 1: 失敗する test を書く**

`tests/test_stackchan_chat.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware" / "tools"))
from stackchan_chat import describe  # noqa: E402


def out(*calls: dict) -> str:
    return json.dumps(list(calls), ensure_ascii=False)


@pytest.mark.parametrize(
    ("calls", "text"),
    [
        ((), "何もしない"),
        (({"name": "look", "arguments": {"direction": "right", "degrees": 45}},),
         "右を向く（正面から45°）"),
        (({"name": "look", "arguments": {"direction": "up", "amount": "slight"}},), "少し上を向く"),
        (({"name": "look", "arguments": {"direction": "center", "amount": "normal"}},),
         "正面を向く"),
        (({"name": "turn", "arguments": {"direction": "up_left", "degrees": 10}},),
         "今の向きから左上へ10°"),
        (({"name": "turn", "arguments": {"direction": "right", "amount": "large"}},),
         "今の向きから大きく右へ"),
        (({"name": "nod", "arguments": {"count": 2}},), "2回うなずく"),
        (({"name": "shake", "arguments": {"count": 1}},), "1回首を横に振る"),
        (({"name": "bow", "arguments": {}},), "お辞儀する"),
        (({"name": "set_expression", "arguments": {"expression": "doubt"}},),
         "不思議そうな顔にする"),
        (({"name": "set_led", "arguments": {"color": "light_blue"}},), "LED を水色にする"),
        (({"name": "set_led", "arguments": {"color": "off"}},), "LED を消す"),
        (({"name": "set_volume", "arguments": {"level": 50}},), "音量を50にする"),
        (({"name": "adjust_volume", "arguments": {"direction": "down", "by": 10}},),
         "音量を10下げる"),
        (({"name": "adjust_brightness", "arguments": {"direction": "up", "amount": "slight"}},),
         "画面を少し明るくする"),
        (({"name": "set_led", "arguments": {"color": "blue"}},
          {"name": "set_volume", "arguments": {"level": 0}}),
         "LED を青にする、音量を0にする"),
    ],
)  # fmt: skip
def test_describe(calls: tuple, text: str) -> None:
    assert describe(out(*calls)) == text


def test_describe_keeps_unparsable_output() -> None:
    assert describe("[{") == "[{"
```

- [ ] **Step 2: test が失敗することを確かめる**

Run: `uv run pytest tests/test_stackchan_chat.py -q`

Expected: FAIL。`ImportError: cannot import name 'describe'`、または `import serial` の `ModuleNotFoundError`。

- [ ] **Step 3: `stackchan_chat.py` に `describe` を足し、`import serial` を `main()` の中に移す**

module の先頭の `import serial` を消し、`main()` の最初の行に `import serial  # pyserial: only needed to talk to the device` を置く。`reader()` の型注釈の `serial.Serial` は `"serial.Serial"`（文字列）にする。`PREFIX = "JTALM "` の後に、次を足す。

```python
DIR_JA = {"left": "左", "right": "右", "up": "上", "down": "下", "up_left": "左上",
          "up_right": "右上", "down_left": "左下", "down_right": "右下"}  # fmt: skip
AMOUNT_JA = {"slight": "少し", "normal": "", "large": "大きく"}
EXPR_JA = {"happy": "笑顔", "sad": "悲しい顔", "surprised": "驚いた顔", "neutral": "普通の顔",
           "angry": "怒った顔", "sleepy": "眠そうな顔", "doubt": "不思議そうな顔"}  # fmt: skip
COLOR_JA = {"red": "赤", "orange": "オレンジ", "yellow": "黄色", "green": "緑",
            "light_blue": "水色", "blue": "青", "purple": "紫", "pink": "ピンク", "white": "白"}  # fmt: skip
ADJUST_JA = {
    "adjust_volume": ("音量を", {"up": "上げる", "down": "下げる"}),
    "adjust_brightness": ("画面を", {"up": "明るくする", "down": "暗くする"}),
}


def describe_call(call: dict) -> str:
    name, a = call["name"], call["arguments"]
    if name in ("look", "turn"):
        if a["direction"] == "center":
            return "正面を向く"
        where = DIR_JA[a["direction"]]
        if name == "look":
            if "degrees" in a:
                return f"{where}を向く（正面から{a['degrees']}°）"
            return f"{AMOUNT_JA[a['amount']]}{where}を向く"
        if "degrees" in a:
            return f"今の向きから{where}へ{a['degrees']}°"
        return f"今の向きから{AMOUNT_JA[a['amount']]}{where}へ"
    if name == "nod":
        return f"{a['count']}回うなずく"
    if name == "shake":
        return f"{a['count']}回首を横に振る"
    if name == "bow":
        return "お辞儀する"
    if name == "set_expression":
        return f"{EXPR_JA[a['expression']]}にする"
    if name == "set_led":
        return "LED を消す" if a["color"] == "off" else f"LED を{COLOR_JA[a['color']]}にする"
    if name == "set_volume":
        return f"音量を{a['level']}にする"
    if name == "set_brightness":
        return f"画面の明るさを{a['level']}にする"
    head, verbs = ADJUST_JA[name]
    size = f"{a['by']}" if "by" in a else AMOUNT_JA[a["amount"]]
    return f"{head}{size}{verbs[a['direction']]}"


def describe(output: str) -> str:
    """A short Japanese description of an Action output ("何もしない" for [])."""
    try:
        calls = json.loads(output)
        return "、".join(describe_call(c) for c in calls) or "何もしない"
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return output
```

`show()` の `t == "gen"` の print を次に替え、`setting` と `clamped` の表示を足す。

```python
    elif t == "gen":
        gated = "（確信度が低いので何もしない）" if rec.get("gated") else ""
        output = rec.get("output", "")
        print(f"→ {describe(output)}  {rec.get('total_ms', 0):.0f} ms{gated}", flush=True)
        if verbose:
            print(f"  {output}", flush=True)
    elif t == "act" and not rec.get("valid", True):
        print(f"  実行しない: {rec.get('err')}", flush=True)
    elif t == "act" and any(s.get("clamped") for s in rec.get("steps", [])):
        print("  可動域の端で止めました", flush=True)
    elif t == "setting":
        what = {"volume": "音量", "brightness": "画面の明るさ", "led": "LED"}[rec["what"]]
        value = COLOR_JA.get(rec.get("color"), "消灯") if rec["what"] == "led" else rec["level"]
        print(f"  {what}: {value}", flush=True)
```

module の docstring の例を v1 にする。

```text
    準備ができました。依頼を入力してください（終了は Ctrl+C）。
    顔を右に45度向いて
    → 右を向く（正面から45°）  1350 ms
```

- [ ] **Step 4: test が通ることを確かめる**

Run: `uv run pytest tests/test_stackchan_chat.py -q`

Expected: `17 passed`。

- [ ] **Step 5: 実機で表示を確かめる**

Run: `(printf '!act [{"name":"set_volume","arguments":{"level":50}}]\n'; sleep 3) | uv run --no-project --with pyserial python firmware/tools/stackchan_chat.py COM3`

Expected:
- `準備ができました。`
- `  音量: 50`

（標準入力が終わると `!stop` を送って終わる。`!stop` は待ち行列の計画を捨てるので、`sleep 3` で計画が終わるまで標準入力を開けておく。）

- [ ] **Step 6: lint と Commit**

```bash
uv run --only-dev ruff check src tests firmware/tools && uv run --only-dev ruff format --check src tests firmware/tools
git add firmware/tools/stackchan_chat.py tests/test_stackchan_chat.py
git commit -m "stackchan_chat: describe v1 outputs in Japanese, show settings and clamped moves; pyserial imported only in main"
```

---

### Task 8（F4）: v1 のモデルで実機の一致、長時間の動作、応答時間を確かめ、文書を直す

**前提:**
- LM 側の v1 の `.jtlm`（INT4）がある。
- v1 の C の grammar が `runtime/host/` に merge 済み。
- PyTorch の評価の出力（`jtalm.model.eval_suite` の gate 付きの出力）が、比べる評価セットについてある。

**Files:**
- Create: `results/v1_action/device/README.md`、`results/v1_action/device/*.summary.json`
- Modify: `docs/hardware.md`、`firmware/README.md`、`README.md`（「対応ハードウェアと安全」の表の角度の行だけ）

**Interfaces:**
- Consumes: v1 の `.jtlm`（以下 `<v1.jtlm>`）、v1 の評価セット（LM 側の計画が作るスタックチャン実例セット v1 と eval v3。以下 `<cases.jsonl>`）、PyTorch の出力（以下 `<ref.jsonl>`）。
- Produces: `results/v1_action/device/`。LM 側の L6（公開）が参照する。

- [ ] **Step 1: `.jtlm` と grammar の版が合わないときのエラーを確かめる（Review Focus 5）**

v1 の firmware を build し、v0 の `.jtlm` が `model` partition に入ったまま起動する。

Run:
- Task 1 の Step 5 と Step 6 で、app だけを書き込む。
- 続けて次を実行する。

```bash
uv run --no-project --with pyserial python firmware/tools/serial_capture.py --port COM3 --reset \
  --seconds 15 --out runs/fw/t8_mismatch.log
```

Expected: log に `JTALM {"t":"error","msg":"the tokenizer lacks the Action grammar pieces"}` がある。黙って止まらない。

- [ ] **Step 2: v1 の `.jtlm` を書き込む**

Run: `uvx --from esptool esptool --chip esp32s3 -p COM3 -b 921600 write-flash 0x200000 <v1.jtlm>`

Expected: `Hash of data verified.`。続けて `serial_capture.py --seconds 15` の log の `info` の行の `model_sha` が、`<v1.jtlm>` の SHA-256 の先頭16桁と一致する。

- [ ] **Step 3: 実機と PyTorch の出力の一致と、計画の照合（300件以上）**

Run:

```bash
uv run --no-project --with pyserial python firmware/tools/lm_serial.py --port COM3 --reset --act \
  --cases <cases.jsonl> --limit 300 --ref <ref.jsonl> --out runs/fw/t8_parity.jsonl
uv run python firmware/tools/dispatch_check.py --results runs/fw/t8_parity.jsonl --log runs/fw/t8_parity.log
```

Expected:
- `lm_serial.py` の summary で、出力の一致が 300 / 300。gate の前の出力（`raw`）も一致する。
- `dispatch_check.py` で、`"plans_match": 300`、`"log": {"n_problems": 0, "faults": []}`。

- [ ] **Step 4: 利用者の4文を実機で確かめる**

`runs/fw/user4.txt` に、次の4行を書く（UTF-8）。

```text
LEDライトの色を青にして
音声の音量を50にして
頭を90度上に向けて
顔を右に45度向いて
```

Run: `uv run --no-project --with pyserial python firmware/tools/lm_serial.py --port COM3 --reset --act --cases runs/fw/user4.txt --out runs/fw/t8_user4.jsonl`

Expected: 4件の `output` が、次の順に spec 4.4 の出力と一致する。
1. `set_led blue`
2. `set_volume 50`
3. `look up 90`（計画は上限で clamped）
4. `look right 45`

- [ ] **Step 5: 長時間の動作と応答時間**

Run:

```bash
uv run --no-project --with pyserial python firmware/tools/lm_serial.py --port COM3 --reset --act \
  --cases <cases.jsonl> --limit 300 --repeat 5 --heap-every 100 --out runs/fw/t8_long.jsonl
uv run python firmware/tools/dispatch_check.py --results runs/fw/t8_long.jsonl --log runs/fw/t8_long.log
```

Expected:
- 1,500件で reset、`fault`、`error` がない。
- 内部 SRAM の空き（`int_free`）が、最初の 100件の後から減り続けない。
- 応答時間の中央値が 2,000 ms 以下（spec 2章の完了の条件 6）。
- `dispatch_check` の `n_problems` が 0。

speaker と NVS を足したことで、v0（中央値 1,276 ms）より遅くなっていないかを、出力の token 数をそろえた件で比べ、差を記録する。

- [ ] **Step 6: 結果をまとめる**

`results/v1_action/device/README.md` に、次を英語で書く（v0 の `results/v051_action/device/README.md` と同じ形）。

- モデルの SHA
- 出力の一致（N / N）
- 計画の一致
- 応答時間の中央値、p90、最大
- decode と prefill の ms/token
- 長時間の動作（件数、heap、温度）
- 可動域（F2 で決めた値）
- 利用者の4文の結果

`lm_serial.py` が書いた `*.summary.json` を、同じ directory に copy する。

- [ ] **Step 7: 文書を直す**

**`docs/hardware.md`:**
- 「周辺機器」の RGB LED と speaker を「使う」に移す。
- 「Dispatcher」の表の、次の行を v1 にする。
  - 検査: schema v1
  - 角度: look / turn、`degrees`、斜め
  - Soft limit: Task 2 の値
  - 首振り、お辞儀の行を足す
  - LED / 音量 / 明るさ / 設定の保存の行を足す
- 「表情」の表に、angry、sleepy、doubt を足す。
- 「実機の性能」に、v1 の応答時間を足す（出典は `results/v1_action/device/`）。

**`firmware/README.md`:**
- 「この firmware がすること」の 3 を v1 の動作にする。
- 「首を動かす」の角度の行（`左右 ±30°、上下 −10〜+15°`）を Task 2 の値にする。
- 「表情」の表に、3つの顔を足す。
- 「周辺機器」の LED と speaker を「使う」に移す。
- `tools/` の表に、`led_probe.py`、`limits_check.py`、`act_host.c` を足す。
- command の一覧に `!led`、`!pose` を足す。

**`README.md`:**
- 「対応ハードウェアと安全」の表の `角度は firmware が制限します（左右 ±30°、上下 −10〜+15°）。` を Task 2 の値にする。
- 他の行は LM 側の計画（L6）が直す。

- [ ] **Step 8: 公開用の build を作る**

LM 側の L6 が `release.py` で使う `build_release` を、v1 の firmware で作る。

Run:

```bash
MSYS_NO_PATHCONV=1 docker run --rm -e IDF_COMPONENT_MANAGER=0 -v "$(pwd -W):/w" \
  -w /w/firmware/jtalm_action espressif/idf:v5.5.5 idf.py -B build_release build
```

Expected: `firmware/jtalm_action/build_release/jtalm_action.bin` ができる。HF への公開は、LM 側の L6 で利用者の確認を取ってから行う（この Task では公開しない）。

- [ ] **Step 9: Commit**

```bash
git add results/v1_action/device docs/hardware.md firmware/README.md README.md
git commit -m "results: v1 3M INT4 on the K151 (parity with PyTorch, plans, long run, latency); docs for the v1 firmware (limits, faces, LED, volume, brightness, !led, !pose)"
```

---

## Self-Review の記録

- **spec の網羅:**

  | spec | Task |
  |---|---|
  | 6章 look / turn | 4、6 |
  | 可動域 | 2 |
  | shake / bow | 4、6 |
  | 表情 | 5 |
  | set_led | 1、5 |
  | 音量 | 5 |
  | 明るさ | 5 |
  | 設定の保存 | 5 |
  | 検査（validator） | 4 |
  | 確認の方法: dispatch_check | 3、4 |
  | 確認の方法: 実機の一致、長時間 | 8 |
  | 確認の方法: 見た目 | 5、6 |
  | 確認の方法: stackchan_chat | 7 |
  | 7章 F1〜F4 | 1、2、4〜6、8 |
  | 8章の LED の危険 | 1 の Step 8 |
  | 8章の可動域の危険 | 2 |

  Web デモの表示は LM 側の計画（L5）。
- **型の一貫性:**
  - `act_call_t.value`、`act_step_t.arg` / `level`、`act_apply_level`、`settings_t`、`board_led` / `board_volume` / `board_brightness` / `board_brightness_level`、`servo_set_settings` は、定義した Task と使う Task で同じ名前。
  - Python の `mapping.Limits`、`DEFAULT_LIMITS`、`plan_v1`、`SHAKE_YAW_DEG`、`BOW_HOLD_MS`、`ADJUST_STEP`、`BRIGHTNESS_MIN` は、LM 側の計画が作る名前と同じ。
- **LM 側と合わせる点:**
  - `nod` の最後に base へ戻る move を、最後の目標が base と同じときは出さない（v0 と同じ）。
  - `look` の `center` に `amount` を付けた場合は有効（v0 と同じ）。

  この2点は LM 側の `plan_v1` / schema v1 と照合で確かめる（Task 4 の Step 8）。
