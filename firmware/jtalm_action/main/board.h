// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
//
// CoreS3 / K151 board glue on top of M5Unified + M5GFX (MIT): display (the face), touch,
// and the servo power switch (VM_EN, pin 0 of the PY32L020 IO expander at 0x6F on the
// Stack-chan base, as in stackchan-idf components/board).

#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  int board;          // m5::board_t
  int py32;           // the IO expander answered
  int py32_version;   // its version register
  int vm_mode_before, vm_out_before;  // GPIO mode / output registers (low byte) at boot
  int vm_mode_after, vm_out_after;    // after forcing VM_EN to a low output
  uint32_t begin_ms;  // M5.begin() time
  int led_init;       // the base LEDs were set up (PY32 pin 13, 12 LEDs)
} board_info_t;

typedef struct {
  uint32_t crc;  // CRC-32 of the 320x240 RGB565 frame
  uint32_t draw_us, push_us;
} face_info_t;

// Initializes M5Unified (display, touch, power; no speaker, mic, IMU or RTC), makes sure the
// servo power is off, and allocates the face frame in PSRAM. Returns 0 on success.
int board_init(board_info_t *info);

// Draws expression `expr` (EXPR_* in action.h) and pushes it to the panel.
int board_face(int expr, face_info_t *info);

// VM_EN on the IO expander: 1 powers the servos. Returns 0 on success.
int board_servo_power(int on);

// VM_EN as read back from the IO expander: 1 on, 0 off, -1 unknown.
int board_servo_power_state(void);

// Raw registers for diagnostics: PY32L020 0..n_py32-1 and AW9523 0..n_aw9523-1.
void board_regs(uint8_t *py32, int n_py32, uint8_t *aw9523, int n_aw9523);

// The 12 RGB LEDs on the back of the base (WS2812 driven by the PY32): all set to one color,
// each channel 0..168 (larger values are clamped to 168, the official firmware's safe range).
// Returns 0 on success.
int board_led(uint8_t r, uint8_t g, uint8_t b);

// REG_LED_CFG of the PY32 read back (LED count in bits 0-5), -1 without the PY32. Diagnostics.
int board_led_cfg(void);

// 1 while the screen is touched (polls the touch controller).
int board_touched(void);

#ifdef __cplusplus
}
#endif
