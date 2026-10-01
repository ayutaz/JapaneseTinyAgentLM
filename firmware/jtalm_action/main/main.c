// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
//
// Action LM firmware for M5Stack CoreS3 (StackChan K151), milestones B4 and A1-A3.
//
// Runs the M6 reference runtime (runtime/host, compiled with -DJTLM_ACC=float) on the
// .jtlm image in the "model" partition, which is read in place through esp_partition_mmap.
// Each UTF-8 line received on the USB-Serial/JTAG console is one utterance; the reply is
// one telemetry line with the greedy (grammar-constrained) output and its timings:
//
//   JTALM {"t":"gen","output":"[...]","raw":"[...]","gated":0,"ids":[...],...}
//
// "raw" is the decoded output; "output" is it after the confidence gate (CONFIG_JTALM_GATE_
// PERMILLE): "[]" when the minimum token probability is below the threshold.
// Lines starting with '!' are commands: "!heap", "!info", "!grammar 0|1", "!gate <threshold>"
// (0 turns it off), "!par 0|1" (split
// matrix products across both cores), "!batch 0|1" (batched prefill; 0 runs the prompt one
// token at a time through jtlm_forward, as a baseline).
//
// Action dispatch (A1-A3): "output" is validated again (action.c), planned from the pose left
// by the previous plan, reported as JTALM {"t":"act",...} and queued to the dispatcher
// (servo.c), which changes the face on the display (board.cpp) and moves the head. Servo
// output is off after boot (dry-run: plans run with their timing but nothing is sent to the
// servos). Commands: "!act <json>" (dispatch an Action JSON without the LM), "!center",
// "!servo on" (power the servos and center the head), and, handled at once even while the
// LM is busy, "!stop" / "!servo off" (torque off and servo power off), "!relax" (torque
// off), "!servo" (status). A touch on the screen also stops. "!wdtest" (dry-run only) runs a
// plan that overruns its deadline, to check the watchdog. No Wi-Fi.

#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "action.h"
#include "board.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_app_desc.h"
#include "esp_heap_caps.h"
#include "esp_partition.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "jtalm.h"
#include "mbedtls/sha256.h"
#include "sdkconfig.h"
#include "servo.h"
#include "soc/extmem_reg.h"

#define MODEL_PARTITION_SUBTYPE 0x40
#define LM_TASK_STACK (16 * 1024)
#define LM_TASK_CORE 1
#define WORKER_TASK_STACK (6 * 1024)
#define WORKER_TASK_CORE 0
#define READER_TASK_STACK (3 * 1024)
#define READER_TASK_CORE 0
#define LINE_QUEUE_LEN 4
#define LINE_MAX_BYTES 1024
#define WORK_BYTES (32 * 1024)  // tokenizer workspace: 16 B per normalized byte + text
#define OUT_BYTES 1024

typedef struct {
  jtlm_model model;
  jtlm_state state;
  jtlm_grammar grammar;
  void *arena, *kv;  // hot state and KV cache (kv == NULL: both in arena)
  const char *arena_where;
  size_t arena_bytes, kv_bytes, image_bytes;
  const void *map;
  int autoload;  // DCache autoload: -1 off, else the trigger (0 miss, 1 hit, 2 both)
  char sha[17];
  void *work;
  int ids[512];
  float *logits0;
  char out[OUT_BYTES];
  int use_grammar, use_par, use_batch;
  double gate;  // confidence gate threshold (0: off)
  long n_requests;
  uint32_t act_seq;
  int pose_yaw, pose_pitch;  // pose after the last queued plan (degrees)
} lm_t;

static lm_t g_lm;

typedef struct {
  size_t len;
  char text[LINE_MAX_BYTES];
} line_t;

static QueueHandle_t g_lines;  // console lines for the LM task

// Second core for jtlm_set_parallel: the LM task (core 1) runs the first half of the rows of
// each matrix product and a worker task on core 0 the second half.
typedef struct {
  jtlm_range_fn fn;
  void *ctx;
  int begin, end;
} par_job_t;

static par_job_t g_job;
static TaskHandle_t g_worker, g_lm_task;

static void worker_task(void *arg) {
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    g_job.fn(g_job.ctx, g_job.begin, g_job.end);
    xTaskNotifyGive(g_lm_task);
  }
}

static void run_parallel(jtlm_range_fn fn, void *ctx, int n) {
  int mid = n / 2;
  g_job = (par_job_t){fn, ctx, mid, n};
  xTaskNotifyGive(g_worker);
  fn(ctx, 0, mid);
  ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
}

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

static void emit_error(const char *msg) {
  printf("JTALM {\"t\":\"error\",\"msg\":\"%s\"}\n", msg);
}

static void print_json_string(const char *s, size_t n) {
  putchar('"');
  for (size_t i = 0; i < n; i++) {
    unsigned char c = (unsigned char)s[i];
    if (c == '"' || c == '\\') {
      printf("\\%c", c);
    } else if (c < 0x20) {
      printf("\\u%04x", c);
    } else {
      putchar(c);
    }
  }
  putchar('"');
}

static void print_ids(const int *ids, int n) {
  putchar('[');
  for (int i = 0; i < n; i++) printf(i ? ",%d" : "%d", ids[i]);
  putchar(']');
}

static uint32_t rd32(const uint8_t *p) {
  return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 |
         (uint32_t)p[3] << 24;
}

// Bytes actually used by the image: the end of its furthest section (header offsets 52..75).
static size_t image_bytes(const uint8_t *b) {
  size_t end = 0;
  for (int off = 52; off < 76; off += 8) {
    size_t e = (size_t)rd32(b + off) + rd32(b + off + 4);
    if (e > end) end = e;
  }
  return end;
}

static void emit_info(const lm_t *lm) {
  const esp_app_desc_t *app = esp_app_get_description();
  char elf_sha[17];
  esp_app_get_elf_sha256(elf_sha, sizeof(elf_sha));
  const jtlm_config *c = &lm->model.cfg;
  printf(
      "JTALM {\"t\":\"info\",\"app\":\"%s\",\"idf\":\"%s\",\"elf_sha\":\"%s\""
      ",\"built\":\"%s %s\",\"cpu_mhz\":%d,\"model_sha\":\"%s\",\"image_bytes\":%u"
      ",\"vocab\":%d,\"d_model\":%d,\"n_layers\":%d,\"n_heads\":%d,\"n_kv_heads\":%d"
      ",\"d_ff\":%d,\"max_seq_len\":%d,\"bits\":%d,\"group\":%d"
      ",\"arena\":\"%s\",\"arena_bytes\":%u,\"kv_bytes\":%u,\"batch\":%d"
      ",\"grammar\":%d,\"gate\":%.3f,\"par\":%d,\"batch_prefill\":%d,\"core\":%d}\n",
      app->project_name, app->idf_ver, elf_sha, app->date, app->time,
      CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ, lm->sha, (unsigned)lm->image_bytes,
      c->vocab_size, c->d_model, c->n_layers, c->n_heads, c->n_kv_heads, c->d_ff,
      c->max_seq_len, c->bits, c->group, lm->arena_where, (unsigned)lm->arena_bytes,
      (unsigned)lm->kv_bytes, JTLM_BATCH, lm->use_grammar, lm->gate, lm->use_par,
      lm->use_batch, xPortGetCoreID()
  );
}

static int lm_init(lm_t *lm) {
  const esp_partition_t *part = esp_partition_find_first(
      ESP_PARTITION_TYPE_DATA, MODEL_PARTITION_SUBTYPE, NULL
  );
  if (part == NULL) {
    emit_error("model partition not found");
    return -1;
  }
  const void *map = NULL;
  esp_partition_mmap_handle_t handle;
  if (esp_partition_mmap(part, 0, part->size, ESP_PARTITION_MMAP_DATA, &map, &handle) !=
      ESP_OK) {
    emit_error("model partition mmap failed");
    return -1;
  }
  int64_t t0 = now_us();
  if (jtlm_model_init(&lm->model, map, part->size) != JTLM_OK) {
    emit_error("model partition does not hold a valid .jtlm image");
    return -1;
  }
  lm->image_bytes = image_bytes(map);
  lm->map = map;
  int64_t t1 = now_us();

  // SHA-256 of the image, so each log names the exact weights it ran.
  uint8_t digest[32];
  mbedtls_sha256(map, lm->image_bytes, digest, 0);
  for (int i = 0; i < 8; i++) sprintf(lm->sha + 2 * i, "%02x", digest[i]);
  int64_t t2 = now_us();

  const jtlm_config *c = &lm->model.cfg;
  // The whole state in internal SRAM if it fits; else only the KV cache goes to PSRAM.
  const uint32_t internal = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
  lm->arena_bytes = jtlm_state_bytes(c);
  lm->arena = heap_caps_aligned_alloc(8, lm->arena_bytes, internal);
  lm->arena_where = "internal";
  if (lm->arena == NULL) {
    lm->kv_bytes = jtlm_state_kv_bytes(c);
    lm->arena_bytes -= lm->kv_bytes;
    lm->arena = heap_caps_aligned_alloc(8, lm->arena_bytes, internal);
    lm->kv = heap_caps_aligned_alloc(8, lm->kv_bytes, MALLOC_CAP_SPIRAM);
    lm->arena_where = "internal+kv_psram";
    if (lm->kv == NULL) lm->arena = NULL;
  }
  lm->work = heap_caps_malloc(WORK_BYTES, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  lm->logits0 = heap_caps_malloc((size_t)c->vocab_size * sizeof(float), MALLOC_CAP_SPIRAM);
  if (lm->arena == NULL || lm->work == NULL || lm->logits0 == NULL) {
    emit_error("out of memory");
    return -1;
  }
  if (jtlm_grammar_init(&lm->grammar, &lm->model.tok, lm->work, WORK_BYTES) != JTLM_OK) {
    emit_error("the tokenizer lacks the Action grammar pieces");
    return -1;
  }
  lm->use_grammar = 1;
  lm->gate = CONFIG_JTALM_GATE_PERMILLE / 1000.0;
  lm->use_batch = 1;
  lm->use_par = 1;
  jtlm_set_parallel(run_parallel);
  printf(
      "JTALM {\"t\":\"load\",\"part_addr\":%" PRIu32 ",\"part_size\":%" PRIu32
      ",\"ptr\":\"%p\",\"init_us\":%" PRId64 ",\"sha_us\":%" PRId64 "}\n",
      part->address, part->size, map, t1 - t0, t2 - t1
  );
  return 0;
}

static void reset_state(lm_t *lm) {
  if (lm->kv) {
    jtlm_state_init_split(&lm->state, &lm->model.cfg, lm->arena, lm->kv);
  } else {
    jtlm_state_init(&lm->state, &lm->model.cfg, lm->arena);
  }
}

static void print_call(const act_call_t *c) {
  if (c->kind == ACT_LOOK) {
    printf(
        "{\"name\":\"look\",\"arguments\":{\"direction\":\"%s\",\"amount\":\"%s\"}}",
        act_dir_names[c->dir], act_amount_names[c->amount]
    );
  } else if (c->kind == ACT_EXPR) {
    printf(
        "{\"name\":\"set_expression\",\"arguments\":{\"expression\":\"%s\"}}",
        act_expr_names[c->expr]
    );
  } else {
    printf("{\"name\":\"nod\",\"arguments\":{\"count\":%d}}", c->count);
  }
}

// Validates an Action JSON string, plans it from the current pose, queues it and prints
//   JTALM {"t":"act","seq":..,"valid":..,"calls":[..],"from":[yaw,pitch],"steps":[..],...}
// Only "output" (after the gate) is dispatched; "[]" and invalid outputs do nothing.
static void dispatch(lm_t *lm, const char *src, const char *json, size_t len) {
  static act_plan_t plan;
  int64_t t0 = now_us();
  const char *err = NULL;
  int valid = act_parse(json, len, plan.calls, &plan.n_calls, &err) == 0;
  if (!valid) plan.n_calls = 0;
  act_plan(&plan, lm->pose_yaw, lm->pose_pitch);
  uint32_t seq = ++lm->act_seq;
  int queued = 0, dropped = 0;
  if (plan.n_steps > 0) {
    queued = servo_submit(&plan, seq) == 0;
    dropped = !queued;
    if (queued) {
      lm->pose_yaw = plan.yaw1;
      lm->pose_pitch = plan.pitch1;
    }
  }
  int64_t t1 = now_us();
  out_lock();
  printf(
      "JTALM {\"t\":\"act\",\"seq\":%" PRIu32 ",\"src\":\"%s\",\"valid\":%d,\"err\":%s%s%s"
      ",\"calls\":[",
      seq, src, valid, err ? "\"" : "", err ? err : "null", err ? "\"" : ""
  );
  for (int i = 0; i < plan.n_calls; i++) {
    if (i) putchar(',');
    print_call(&plan.calls[i]);
  }
  printf("],\"from\":[%d,%d],\"steps\":[", plan.yaw0, plan.pitch0);
  for (int i = 0; i < plan.n_steps; i++) {
    const act_step_t *s = &plan.steps[i];
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
      plan.yaw1, plan.pitch1, plan.total_ms, queued, dropped,
      servo_output_on() ? "on" : "dry", t1 - t0
  );
  out_unlock();
}

static void run_prompt(lm_t *lm, const char *text, size_t len) {
  const jtlm_model *m = &lm->model;
  int64_t t0 = now_us();
  int n = jtlm_prompt_ids(m, text, len, lm->ids, lm->work, WORK_BYTES);
  int64_t t1 = now_us();
  if (n < 0) {
    printf("JTALM {\"t\":\"error\",\"msg\":\"tokenizer error %d\"}\n", n);
    return;
  }
  reset_state(lm);
  int64_t t2 = now_us();
  float *logits = NULL;
  if (lm->use_batch) {
    logits = jtlm_prefill(m, &lm->state, lm->ids, n);
  } else {
    for (int i = 0; i < n; i++) logits = jtlm_forward(m, &lm->state, lm->ids[i], i);
  }
  int64_t t3 = now_us();
  jtlm_result r;
  int err = jtlm_generate_from(
      m, &lm->state, lm->use_grammar ? &lm->grammar : NULL, logits, n, &r, NULL
  );
  int64_t t4 = now_us();
  if (err != JTLM_OK) {
    printf("JTALM {\"t\":\"error\",\"msg\":\"generation failed %d\"}\n", err);
    return;
  }
  int n_text = r.n && r.ids[r.n - 1] == m->tok.eos ? r.n - 1 : r.n;
  size_t olen = jtlm_decode(&m->tok, r.ids, n_text, lm->out, OUT_BYTES);
  int64_t t5 = now_us();

  int n_decode_fwd = r.n - 1;  // the last token is never fed back
  int n_fwd = n + n_decode_fwd;
  double prefill_ms = (t3 - t2) / 1000.0, decode_ms = (t4 - t3) / 1000.0;
  double total_ms = (t5 - t0) / 1000.0;
  // Same comparison as jtalm.model.evaluate (a float probability against a double threshold).
  int gated = (double)r.min_prob < lm->gate;
  if (olen >= OUT_BYTES) olen = OUT_BYTES - 1;
  out_lock();
  fputs("JTALM {\"t\":\"gen\",\"output\":", stdout);
  print_json_string(gated ? "[]" : lm->out, gated ? 2 : olen);
  fputs(",\"raw\":", stdout);
  print_json_string(lm->out, olen);
  printf(
      ",\"gated\":%d,\"gate\":%.3f,\"min_prob\":%.9g,\"ids\":", gated, lm->gate,
      (double)r.min_prob
  );
  print_ids(r.ids, r.n);
  fputs(",\"prompt_ids\":", stdout);
  print_ids(lm->ids, n);
  printf(
      ",\"n_prompt\":%d,\"n_gen\":%d,\"n_fwd\":%d,\"tok_ms\":%.3f,\"init_ms\":%.3f"
      ",\"prefill_ms\":%.3f,\"decode_ms\":%.3f,\"detok_ms\":%.3f,\"total_ms\":%.3f"
      ",\"ms_per_fwd\":%.3f,\"tok_s\":%.3f}\n",
      n, r.n, n_fwd, (t1 - t0) / 1000.0, (t2 - t1) / 1000.0, prefill_ms, decode_ms,
      (t5 - t4) / 1000.0, total_ms, (prefill_ms + decode_ms) / n_fwd,
      n_fwd * 1000.0 / (prefill_ms + decode_ms)
  );
  out_unlock();
  dispatch(lm, "lm", gated ? "[]" : lm->out, gated ? 2 : olen);
  if (lm->n_requests++ == 0) emit_heap("first_request");
}

// Micro-benchmarks for profiling: libm expf (SiLU, softmax) and one decode-step forward.
static void run_bench(lm_t *lm) {
  const int n = 4096;
  int64_t t0 = now_us();
  float acc = 0;
  for (int i = 0; i < n; i++) acc += expf(-8.0f + 16.0f * (float)i / (float)n);
  int64_t t1 = now_us();
  reset_state(lm);
  for (int pos = 0; pos < 12; pos++) jtlm_forward(&lm->model, &lm->state, 100 + pos, pos);
  int64_t t2 = now_us();
  jtlm_forward(&lm->model, &lm->state, 7, 12);
  int64_t t3 = now_us();
  printf(
      "JTALM {\"t\":\"bench\",\"expf_ns\":%.1f,\"fwd_ms_pos12\":%.3f,\"par\":%d"
      ",\"sum\":%g}\n",
      (t1 - t0) * 1000.0 / n, (t3 - t2) / 1000.0, lm->use_par, (double)acc
  );
}

// DCache autoload (hardware sequential prefetch) over the model image. It is off after boot
// (cpu_start.c enables the DCache without it). trigger: -1 off, 0 on miss, 1 on hit, 2 both;
// size: blocks per autoload request (register field, 0..3).
static void set_autoload(lm_t *lm, int trigger, int size) {
  uint32_t ctrl = REG_READ(EXTMEM_DCACHE_AUTOLOAD_CTRL_REG);
  ctrl &= ~(EXTMEM_DCACHE_AUTOLOAD_ENA | EXTMEM_DCACHE_AUTOLOAD_SCT0_ENA |
            EXTMEM_DCACHE_AUTOLOAD_SCT1_ENA | EXTMEM_DCACHE_AUTOLOAD_ORDER |
            EXTMEM_DCACHE_AUTOLOAD_RQST_M | EXTMEM_DCACHE_AUTOLOAD_SIZE_M);
  REG_WRITE(EXTMEM_DCACHE_AUTOLOAD_CTRL_REG, ctrl);
  if (trigger >= 0) {
    REG_WRITE(EXTMEM_DCACHE_AUTOLOAD_SCT0_ADDR_REG, (uint32_t)lm->map);
    REG_WRITE(EXTMEM_DCACHE_AUTOLOAD_SCT0_SIZE_REG, (uint32_t)lm->image_bytes);
    ctrl |= EXTMEM_DCACHE_AUTOLOAD_SCT0_ENA |
            ((uint32_t)trigger << EXTMEM_DCACHE_AUTOLOAD_RQST_S) |
            ((uint32_t)size << EXTMEM_DCACHE_AUTOLOAD_SIZE_S) | EXTMEM_DCACHE_AUTOLOAD_ENA;
    REG_WRITE(EXTMEM_DCACHE_AUTOLOAD_CTRL_REG, ctrl);
  }
  lm->autoload = trigger;
  printf(
      "JTALM {\"t\":\"ok\",\"autoload\":%d,\"size\":%d,\"ctrl\":%" PRIu32 "}\n",
      trigger, size, REG_READ(EXTMEM_DCACHE_AUTOLOAD_CTRL_REG)
  );
}

static const char kCenter[] =
    "[{\"name\":\"look\",\"arguments\":{\"direction\":\"center\",\"amount\":\"normal\"}}]";

static void run_command(lm_t *lm, const char *line) {
  if (!strcmp(line, "!bench")) {
    run_bench(lm);
  } else if (!strcmp(line, "!heap")) {
    emit_heap("cmd");
  } else if (!strcmp(line, "!info")) {
    emit_info(lm);
  } else if (!strncmp(line, "!grammar ", 9)) {
    lm->use_grammar = line[9] == '1';
    printf("JTALM {\"t\":\"ok\",\"grammar\":%d}\n", lm->use_grammar);
  } else if (!strncmp(line, "!gate ", 6)) {
    lm->gate = atof(line + 6);
    printf("JTALM {\"t\":\"ok\",\"gate\":%.3f}\n", lm->gate);
  } else if (!strncmp(line, "!par ", 5)) {
    lm->use_par = line[5] == '1';
    jtlm_set_parallel(lm->use_par ? run_parallel : NULL);
    printf("JTALM {\"t\":\"ok\",\"par\":%d}\n", lm->use_par);
  } else if (!strncmp(line, "!autoload ", 10)) {
    int trigger = -1, size = 0;
    sscanf(line + 10, "%d %d", &trigger, &size);
    set_autoload(lm, trigger, size & 3);
  } else if (!strncmp(line, "!batch ", 7)) {
    lm->use_batch = line[7] == '1';
    printf("JTALM {\"t\":\"ok\",\"batch_prefill\":%d}\n", lm->use_batch);
  } else if (!strncmp(line, "!act ", 5)) {
    dispatch(lm, "cmd", line + 5, strlen(line + 5));
  } else if (!strcmp(line, "!center")) {
    dispatch(lm, "center", kCenter, strlen(kCenter));
  } else if (!strcmp(line, "!servo on")) {
    // Power up and read the present pose, then a center plan: the dispatcher first moves
    // from wherever the head is to the plan's start (0, 0).
    if (servo_request_on() != 0) {
      emit_error("dispatcher queue full");
      return;
    }
    lm->pose_yaw = lm->pose_pitch = 0;
    dispatch(lm, "servo_on", kCenter, strlen(kCenter));
  } else if (!strcmp(line, "!servo probe")) {
    if (servo_output_on() || servo_request_probe() != 0) emit_error("probe: servo output off only");
  } else if (!strcmp(line, "!wdtest")) {
    if (servo_output_on() || servo_request_wdtest() != 0) emit_error("wdtest: dry-run only");
  } else {
    emit_error("unknown command");
  }
}

// Commands that must not wait for the LM: handled in the reader task. Returns 1 if handled.
static int run_urgent_command(const char *line) {
  if (!strcmp(line, "!stop") || !strcmp(line, "!servo off")) {
    servo_stop(line + 1, 1);
  } else if (!strcmp(line, "!relax")) {
    servo_stop("relax", 0);
  } else if (!strcmp(line, "!servo")) {
    servo_status();
  } else {
    return 0;
  }
  return 1;
}

// Reads one line (without CR/LF) from the console, blocking; empty lines are skipped.
static size_t read_line(char *buf, size_t cap) {
  size_t n = 0;
  for (;;) {
    uint8_t c;
    if (usb_serial_jtag_read_bytes(&c, 1, portMAX_DELAY) != 1) continue;
    if (c == '\n' || c == '\r') {
      if (n) break;
      continue;
    }
    if (n + 1 < cap) buf[n++] = (char)c;
  }
  buf[n] = '\0';
  return n;
}

// Console reader: urgent commands run here at once; every other line goes to the LM task.
static void reader_task(void *arg) {
  static line_t line;
  for (;;) {
    line.len = read_line(line.text, sizeof(line.text));
    if (line.len >= 3 && !memcmp(line.text, "\xef\xbb\xbf", 3)) {
      memmove(line.text, line.text + 3, line.len - 2);  // with the terminating NUL
      line.len -= 3;
    }
    if (line.text[0] == '!' && run_urgent_command(line.text)) continue;
    if (xQueueSend(g_lines, &line, 0) != pdTRUE) {
      out_lock();
      emit_error("busy: line dropped");
      out_unlock();
    }
  }
}

static void boot_board(void) {
  board_info_t b;
  int err = board_init(&b);
  face_info_t f = {0};
  int face_err = err ? -1 : board_face(EXPR_NEUTRAL, &f);
  printf(
      "JTALM {\"t\":\"board\",\"ok\":%d,\"board\":%d,\"begin_ms\":%" PRIu32
      ",\"py32\":%d,\"py32_version\":%d,\"vm_mode\":[%d,%d],\"vm_out\":[%d,%d]"
      ",\"servo\":\"dry\"}\n",
      err == 0, b.board, b.begin_ms, b.py32, b.py32_version, b.vm_mode_before,
      b.vm_mode_after, b.vm_out_before, b.vm_out_after
  );
  printf(
      "JTALM {\"t\":\"face\",\"seq\":0,\"expr\":\"neutral\",\"ok\":%d,\"crc\":\"%08" PRIx32
      "\",\"draw_us\":%" PRIu32 ",\"push_us\":%" PRIu32 "}\n",
      face_err == 0, f.crc, f.draw_us, f.push_us
  );
  if (servo_start() != 0) emit_error("dispatcher start failed");
}

static void lm_task(void *arg) {
  lm_t *lm = arg;
  static line_t line;
  g_lm_task = xTaskGetCurrentTaskHandle();
  emit_heap("task_start");
  if (lm_init(lm) != 0) {
    for (;;) vTaskDelay(portMAX_DELAY);
  }
  emit_info(lm);
  emit_heap("model_ready");
  // After the LM state, so that its internal SRAM arena is placed exactly as before.
  boot_board();
  emit_heap("board_ready");
  xTaskCreatePinnedToCore(reader_task, "reader", READER_TASK_STACK, NULL, 6, NULL,
                          READER_TASK_CORE);
  printf("JTALM {\"t\":\"ready\"}\n");
  fflush(stdout);
  for (;;) {
    xQueueReceive(g_lines, &line, portMAX_DELAY);
    if (line.text[0] == '!') {
      run_command(lm, line.text);
    } else if (line.len) {
      run_prompt(lm, line.text, line.len);
    }
    fflush(stdout);
  }
}

void app_main(void) {
  usb_serial_jtag_driver_config_t cfg = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
  cfg.rx_buffer_size = 4096;
  cfg.tx_buffer_size = 4096;
  ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&cfg));
  usb_serial_jtag_vfs_use_driver();
  out_init();
  g_lines = xQueueCreateWithCaps(LINE_QUEUE_LEN, sizeof(line_t), MALLOC_CAP_SPIRAM);
  emit_heap("boot");
  xTaskCreatePinnedToCore(worker_task, "lm_worker", WORKER_TASK_STACK, NULL, 5, &g_worker,
                          WORKER_TASK_CORE);
  xTaskCreatePinnedToCore(lm_task, "lm", LM_TASK_STACK, &g_lm, 5, &g_lm_task, LM_TASK_CORE);
}
