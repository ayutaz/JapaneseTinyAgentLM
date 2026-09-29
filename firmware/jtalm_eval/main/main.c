// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 JapaneseTinyAgentLM contributors
//
// Minimal LM evaluation firmware for M5Stack CoreS3 (StackChan K151).
//
// Prints device info, the partition table, heap stats at each stage and
// PSRAM / flash-mmap read bandwidth as one-line telemetry records:
//
//   JTALM {"t":"<record type>", ...}
//
// No Wi-Fi, no display, no servo: the only I/O is the USB-Serial/JTAG console.
// Serial commands: 'b' reruns the benchmark, 'h' prints heap stats.

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_image_format.h"
#include "esp_partition.h"
#include "esp_psram.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#define MODEL_PARTITION_SUBTYPE 0x40

#define STREAM_BYTES (4 * 1024 * 1024)  // well above the 64KB data cache
#define HOT_BYTES (32 * 1024)           // fits in the data cache
#define COPY_CHUNK (32 * 1024)
#define REPEAT 4

static volatile uint32_t g_sink;

static int64_t now_us(void) { return esp_timer_get_time(); }

static void emit_heap(const char *stage) {
  const uint32_t internal = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
  printf(
      "JTALM {\"t\":\"heap\",\"stage\":\"%s\",\"ms\":%" PRId64
      ",\"int_free\":%u,\"int_largest\":%u,\"int_min\":%u"
      ",\"ps_free\":%u,\"ps_largest\":%u,\"ps_min\":%u,\"stack_hwm\":%u}\n",
      stage, now_us() / 1000,
      (unsigned)heap_caps_get_free_size(internal),
      (unsigned)heap_caps_get_largest_free_block(internal),
      (unsigned)heap_caps_get_minimum_free_size(internal),
      (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
      (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM),
      (unsigned)heap_caps_get_minimum_free_size(MALLOC_CAP_SPIRAM),
      (unsigned)uxTaskGetStackHighWaterMark(NULL)
  );
}

static void emit_info(void) {
  const esp_app_desc_t *app = esp_app_get_description();
  char elf_sha[17];
  esp_app_get_elf_sha256(elf_sha, sizeof(elf_sha));

  esp_chip_info_t chip;
  esp_chip_info(&chip);

  uint32_t flash_size = 0;
  esp_flash_get_size(NULL, &flash_size);

  printf(
      "JTALM {\"t\":\"info\",\"app\":\"%s\",\"ver\":\"%s\",\"idf\":\"%s\""
      ",\"elf_sha\":\"%s\",\"built\":\"%s %s\",\"cores\":%d,\"rev\":%d"
      ",\"cpu_mhz\":%d,\"flash\":%" PRIu32 ",\"psram\":%u}\n",
      app->project_name, app->version, app->idf_ver, elf_sha, app->date,
      app->time, chip.cores, chip.revision, CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ,
      flash_size, (unsigned)esp_psram_get_size()
  );
}

static void emit_partitions(void) {
  esp_partition_iterator_t it =
      esp_partition_find(ESP_PARTITION_TYPE_ANY, ESP_PARTITION_SUBTYPE_ANY, NULL);
  for (; it != NULL; it = esp_partition_next(it)) {
    const esp_partition_t *p = esp_partition_get(it);
    uint32_t image_len = 0;
    if (p->type == ESP_PARTITION_TYPE_APP) {
      const esp_partition_pos_t pos = {.offset = p->address, .size = p->size};
      esp_image_metadata_t meta;
      if (esp_image_verify(ESP_IMAGE_VERIFY_SILENT, &pos, &meta) == ESP_OK) {
        image_len = meta.image_len;
      }
    }
    printf(
        "JTALM {\"t\":\"part\",\"label\":\"%s\",\"type\":%d,\"subtype\":%d"
        ",\"addr\":%" PRIu32 ",\"size\":%" PRIu32 ",\"image_len\":%" PRIu32 "}\n",
        p->label, p->type, p->subtype, p->address, p->size, image_len
    );
  }
  esp_partition_iterator_release(it);
}

static uint32_t sum_words(const uint32_t *p, size_t bytes) {
  uint32_t a = 0, b = 0, c = 0, d = 0;
  for (size_t i = 0; i < bytes / 4; i += 4) {
    a += p[i];
    b += p[i + 1];
    c += p[i + 2];
    d += p[i + 3];
  }
  return a + b + c + d;
}

static void emit_bw(const char *name, size_t bytes, int64_t us) {
  printf(
      "JTALM {\"t\":\"bw\",\"name\":\"%s\",\"bytes\":%u,\"us\":%" PRId64
      ",\"MBps\":%.1f}\n",
      name, (unsigned)bytes, us, us > 0 ? (double)bytes / (double)us : 0.0
  );
}

// Sequential read of `bytes` from `p`, REPEAT times.
static void bench_read(const char *name, const void *p, size_t bytes) {
  g_sink += sum_words(p, bytes);  // warm-up pass
  int64_t us = 0;
  for (int r = 0; r < REPEAT; r++) {
    int64_t t0 = now_us();
    g_sink += sum_words(p, bytes);
    us += now_us() - t0;
    vTaskDelay(1);  // let the idle task feed the watchdog
  }
  emit_bw(name, bytes * REPEAT, us);
}

// Hot read: the same small block over and over, so it stays in the data cache.
static void bench_read_hot(const char *name, const void *p) {
  const int loops = STREAM_BYTES / HOT_BYTES;
  g_sink += sum_words(p, HOT_BYTES);
  int64_t t0 = now_us();
  for (int i = 0; i < loops; i++) g_sink += sum_words(p, HOT_BYTES);
  int64_t t1 = now_us();
  emit_bw(name, (size_t)HOT_BYTES * loops, t1 - t0);
}

// memcpy from `src` into a small internal-SRAM buffer, chunk by chunk.
static void bench_copy_to_internal(
    const char *name, const uint8_t *src, uint8_t *dst, size_t bytes
) {
  int64_t t0 = now_us();
  for (size_t off = 0; off < bytes; off += COPY_CHUNK) {
    memcpy(dst, src + off, COPY_CHUNK);
  }
  int64_t t1 = now_us();
  g_sink += dst[0];
  emit_bw(name, bytes, t1 - t0);
}

static void run_benchmark(void) {
  emit_heap("bench_start");

  uint8_t *internal = heap_caps_malloc(COPY_CHUNK, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  uint8_t *psram = heap_caps_malloc(STREAM_BYTES, MALLOC_CAP_SPIRAM);
  if (internal == NULL || psram == NULL) {
    printf("JTALM {\"t\":\"error\",\"msg\":\"bench alloc failed\"}\n");
    heap_caps_free(internal);
    heap_caps_free(psram);
    return;
  }
  for (size_t i = 0; i < STREAM_BYTES; i++) psram[i] = (uint8_t)(i * 31u);
  memset(internal, 0x5a, COPY_CHUNK);
  emit_heap("bench_alloc");

  bench_read_hot("sram_read_hot", internal);
  bench_read("psram_read", psram, STREAM_BYTES);
  bench_read_hot("psram_read_hot", psram);
  bench_copy_to_internal("psram_memcpy_to_sram", psram, internal, STREAM_BYTES);

  const esp_partition_t *model = esp_partition_find_first(
      ESP_PARTITION_TYPE_DATA, MODEL_PARTITION_SUBTYPE, NULL
  );
  if (model == NULL) {
    printf("JTALM {\"t\":\"error\",\"msg\":\"model partition not found\"}\n");
  } else {
    const void *map = NULL;
    esp_partition_mmap_handle_t handle;
    int64_t t0 = now_us();
    esp_err_t err = esp_partition_mmap(
        model, 0, model->size, ESP_PARTITION_MMAP_DATA, &map, &handle
    );
    int64_t t1 = now_us();
    printf(
        "JTALM {\"t\":\"mmap\",\"label\":\"%s\",\"size\":%" PRIu32
        ",\"err\":\"%s\",\"us\":%" PRId64 ",\"ptr\":\"%p\"}\n",
        model->label, model->size, esp_err_to_name(err), t1 - t0, map
    );
    if (err == ESP_OK) {
      emit_heap("model_mmap");
      bench_read("flash_mmap_read", map, STREAM_BYTES);
      bench_read_hot("flash_mmap_read_hot", map);
      bench_copy_to_internal(
          "flash_mmap_memcpy_to_sram", map, internal, STREAM_BYTES
      );
      esp_partition_munmap(handle);
    }
  }

  heap_caps_free(psram);
  heap_caps_free(internal);
  emit_heap("bench_end");
}

void app_main(void) {
  emit_heap("boot");
  emit_info();
  emit_partitions();
  run_benchmark();
  emit_heap("idle");
  printf("JTALM {\"t\":\"ready\",\"cmds\":\"b=bench h=heap\"}\n");

  int64_t last = now_us();
  for (;;) {
    int c = getchar();
    if (c == 'b') {
      run_benchmark();
    } else if (c == 'h') {
      emit_heap("cmd");
    }
    if (now_us() - last > 60 * 1000 * 1000) {
      emit_heap("idle");
      last = now_us();
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
