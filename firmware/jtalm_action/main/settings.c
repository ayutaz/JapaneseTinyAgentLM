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
