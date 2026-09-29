// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 JapaneseTinyAgentLM contributors
//
// Board glue (see board.h). M5Unified and M5GFX (MIT, (c) M5Stack Technology / lovyan03)
// are compiled from firmware/third_party; nothing of them is copied here. The PY32L020
// register map (version 0x02, GPIO mode 0x03, output 0x05; VM_EN is pin 0) is the one used
// by stackchan-idf components/board/io_expander_py32.cpp (BSL-1.0, (c) Kenta IDA); this file
// only reads and writes those registers through M5Unified's I2C class.

#include "board.h"

#include <M5Unified.h>

#include "action.h"
#include "esp_rom_crc.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

namespace {

constexpr uint8_t kPy32Addr = 0x6F;
constexpr uint32_t kPy32Freq = 100000;
constexpr uint8_t kPy32RegVersion = 0x02;
constexpr uint8_t kPy32RegModeLow = 0x03;  // 1 = output
constexpr uint8_t kPy32RegOutLow = 0x05;
constexpr uint8_t kVmEnMask = 1u << 0;

constexpr int kW = 320, kH = 240;

M5Canvas *g_canvas;
SemaphoreHandle_t g_gfx_lock;  // display and touch (M5.update) are used from two tasks
int g_py32;

// White features on black. Eyes at (100, 100) and (220, 100), mouth around (160, 170).
void draw_face(M5Canvas &c, int expr) {
  const uint16_t fg = TFT_WHITE;
  c.fillScreen(TFT_BLACK);
  const int ex[2] = {100, 220};
  switch (expr) {
    case EXPR_HAPPY:
      for (int x : ex) c.fillArc(x, 112, 22, 15, 200, 340, fg);  // "^ ^"
      c.fillArc(160, 150, 46, 38, 20, 160, fg);                  // smile
      break;
    case EXPR_SAD:
      for (int x : ex) c.fillCircle(x, 108, 12, fg);
      c.drawWideLine(78, 84, 118, 70, 3.0f, fg);   // eyebrows, raised at the inner ends
      c.drawWideLine(202, 70, 242, 84, 3.0f, fg);
      c.fillArc(160, 206, 40, 33, 205, 335, fg);   // frown
      break;
    case EXPR_SURPRISED:
      for (int x : ex) c.fillCircle(x, 98, 20, fg);
      c.fillEllipse(160, 180, 18, 24, fg);  // open mouth
      c.fillEllipse(160, 180, 10, 16, TFT_BLACK);
      break;
    default:  // EXPR_NEUTRAL
      for (int x : ex) c.fillCircle(x, 100, 14, fg);
      c.fillRoundRect(120, 166, 80, 8, 4, fg);
      break;
  }
}

}  // namespace

extern "C" int board_init(board_info_t *info) {
  memset(info, 0, sizeof(*info));
  int64_t t0 = esp_timer_get_time();
  auto cfg = M5.config();
  cfg.clear_display = true;
  cfg.output_power = true;  // as stackchan-idf: the base (PY32) is fed from the bus
  cfg.internal_imu = false;
  cfg.internal_rtc = false;
  cfg.internal_mic = false;
  cfg.internal_spk = false;
  cfg.led_brightness = 0;
  M5.begin(cfg);
  M5.Display.setRotation(1);  // landscape, as stackchan-idf on CoreS3
  info->begin_ms = (uint32_t)((esp_timer_get_time() - t0) / 1000);
  info->board = (int)M5.getBoard();
  g_gfx_lock = xSemaphoreCreateMutex();

  // Servo power off. The PY32 can take ~1.2 s after a cold reset to answer (stackchan-idf).
  // The output latch is cleared before the pin becomes an output, so it never drives high.
  for (int attempt = 0; attempt < 7 && !g_py32; attempt++) {
    if (attempt) vTaskDelay(pdMS_TO_TICKS(200));
    uint8_t v = M5.In_I2C.readRegister8(kPy32Addr, kPy32RegVersion, kPy32Freq);
    if (v != 0x00 && v != 0xFF) {
      g_py32 = 1;
      info->py32_version = v;
    }
  }
  info->py32 = g_py32;
  if (g_py32) {
    info->vm_mode_before = M5.In_I2C.readRegister8(kPy32Addr, kPy32RegModeLow, kPy32Freq);
    info->vm_out_before = M5.In_I2C.readRegister8(kPy32Addr, kPy32RegOutLow, kPy32Freq);
    M5.In_I2C.bitOff(kPy32Addr, kPy32RegOutLow, kVmEnMask, kPy32Freq);
    M5.In_I2C.bitOn(kPy32Addr, kPy32RegModeLow, kVmEnMask, kPy32Freq);
    info->vm_mode_after = M5.In_I2C.readRegister8(kPy32Addr, kPy32RegModeLow, kPy32Freq);
    info->vm_out_after = M5.In_I2C.readRegister8(kPy32Addr, kPy32RegOutLow, kPy32Freq);
  }

  // The face is drawn into a PSRAM frame and pushed whole: no flicker, no internal SRAM.
  g_canvas = new M5Canvas(&M5.Display);
  g_canvas->setPsram(true);
  g_canvas->setColorDepth(16);
  if (g_canvas->createSprite(kW, kH) == nullptr) return -1;
  return 0;
}

extern "C" int board_face(int expr, face_info_t *info) {
  if (g_canvas == nullptr) return -1;
  xSemaphoreTake(g_gfx_lock, portMAX_DELAY);
  int64_t t0 = esp_timer_get_time();
  draw_face(*g_canvas, expr);
  int64_t t1 = esp_timer_get_time();
  info->crc = esp_rom_crc32_le(0, (const uint8_t *)g_canvas->getBuffer(), kW * kH * 2);
  int64_t t2 = esp_timer_get_time();
  g_canvas->pushSprite(0, 0);
  int64_t t3 = esp_timer_get_time();
  xSemaphoreGive(g_gfx_lock);
  info->draw_us = (uint32_t)(t1 - t0);
  info->push_us = (uint32_t)(t3 - t2);
  return 0;
}

extern "C" int board_servo_power(int on) {
  if (!g_py32) return -1;
  bool ok = on ? M5.In_I2C.bitOn(kPy32Addr, kPy32RegOutLow, kVmEnMask, kPy32Freq)
               : M5.In_I2C.bitOff(kPy32Addr, kPy32RegOutLow, kVmEnMask, kPy32Freq);
  uint8_t out = M5.In_I2C.readRegister8(kPy32Addr, kPy32RegOutLow, kPy32Freq);
  return ok && ((out & kVmEnMask) != 0) == (on != 0) ? 0 : -1;
}

extern "C" int board_servo_power_state(void) {
  if (!g_py32) return -1;
  uint8_t mode = M5.In_I2C.readRegister8(kPy32Addr, kPy32RegModeLow, kPy32Freq);
  uint8_t out = M5.In_I2C.readRegister8(kPy32Addr, kPy32RegOutLow, kPy32Freq);
  return (mode & kVmEnMask) && (out & kVmEnMask) ? 1 : 0;
}

extern "C" int board_touched(void) {
  if (g_gfx_lock == nullptr) return 0;
  if (xSemaphoreTake(g_gfx_lock, pdMS_TO_TICKS(100)) != pdTRUE) return 0;
  M5.update();
  int n = M5.Touch.getCount();
  xSemaphoreGive(g_gfx_lock);
  return n > 0;
}
