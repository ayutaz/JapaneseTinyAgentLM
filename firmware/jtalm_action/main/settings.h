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
