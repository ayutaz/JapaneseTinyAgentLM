// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
//
// Action dispatcher and a minimal Feetech SCS (SCSCL) driver for the two SCS0009 servos of
// the K151 (UART1, TX=G6, RX=G7, 1 Mbps; yaw ID 1, pitch ID 2; docs/hardware.md).
//
// SCS packet: FF FF id len inst params... checksum, len = params + 2, checksum = ~(id + len +
// inst + params) & 0xFF. SCSCL registers are big-endian (high byte first): torque enable 0x28,
// goal position 0x2A (position, time in ms, speed; the servo ignores speed when time > 0),
// present position 0x38. Written from the Feetech protocol; stackchan-idf's scs_servo
// (BSL-1.0) was used as the reference for the register map and byte order.
//
// Tasks: the dispatcher (core 0) runs one plan at a time from a queue; the guard (core 1,
// above the LM task) runs the watchdog, the torque backstop and the touch stop.

#include "servo.h"

#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "board.h"
#include "driver/uart.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "settings.h"

#define SCS_UART UART_NUM_1
#define SCS_TX_PIN 6
#define SCS_RX_PIN 7
#define SCS_BAUD 1000000
#define SCS_TIMEOUT_MS 20  // at least one full FreeRTOS tick (100 Hz)
#define SCS_ID_YAW 1
#define SCS_ID_PITCH 2
#define SCS_BROADCAST 0xFE
#define SCS_PING 0x01
#define SCS_READ 0x02
#define SCS_WRITE 0x03
#define SCS_REG_TORQUE 0x28
#define SCS_REG_GOAL 0x2A
#define SCS_REG_PRESENT 0x38

#define QUEUE_LEN 4
#define POWER_ON_TIMEOUT_MS 3000  // SCS0009 answers ~1 s after VM comes up (stackchan-idf)
#define POWER_POLL_MS 50
#define HOLD_MS 500             // torque stays on this long after a plan, then is released
#define WATCHDOG_MARGIN_MS 2000  // allowed overrun of a plan (the sync move is added)
#define TORQUE_IDLE_MAX_MS 3000  // backstop: torque on without a running plan
#define SYNC_DEG 1.0             // re-sync to the plan's start pose when further than this
#define GUARD_PERIOD_MS 50
#define TOUCH_PERIOD_MS 100

enum { MSG_PLAN, MSG_ON, MSG_WDTEST, MSG_PROBE };

typedef struct {
  uint8_t type;
  uint32_t seq, gen;
  act_plan_t plan;
} msg_t;

static QueueHandle_t g_q;
static SemaphoreHandle_t g_bus, g_print;
static volatile uint32_t g_gen;  // bumped by servo_stop: the running and queued plans end
static volatile int g_output, g_torque, g_active, g_uart_open, g_faults;
static volatile int64_t g_deadline_us, g_release_us, g_torque_idle_us;
static double g_yaw, g_pitch;          // commanded (or, in dry-run, simulated) pose, degrees
static int g_last_raw[2] = {-1, -1};   // last goal written to yaw, pitch

static int g_rx_got;           // bytes received by the last scs_txrx (diagnostics)
static uint8_t g_rx_last[12];

static settings_t g_settings;  // dispatcher task only (after servo_set_settings)

static int64_t now_us(void) { return esp_timer_get_time(); }

void out_lock(void) { xSemaphoreTake(g_print, portMAX_DELAY); }

void out_unlock(void) {
  fflush(stdout);
  xSemaphoreGive(g_print);
}

// ---------------------------------------------------------------------------------------
// SCS bus (callers hold g_bus)

static int scs_open(void) {
  if (g_uart_open) return 0;
  const uart_config_t cfg = {
      .baud_rate = SCS_BAUD,
      .data_bits = UART_DATA_8_BITS,
      .parity = UART_PARITY_DISABLE,
      .stop_bits = UART_STOP_BITS_1,
      .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
      .source_clk = UART_SCLK_DEFAULT,
  };
  if (uart_driver_install(SCS_UART, 256, 0, 0, NULL, 0) != ESP_OK) return -1;
  if (uart_param_config(SCS_UART, &cfg) != ESP_OK ||
      uart_set_pin(SCS_UART, SCS_TX_PIN, SCS_RX_PIN, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE) !=
          ESP_OK) {
    uart_driver_delete(SCS_UART);
    return -1;
  }
  g_uart_open = 1;
  return 0;
}

static int scs_send(uint8_t id, uint8_t inst, const uint8_t *prm, int n) {
  uint8_t tx[16];
  if (n > (int)sizeof(tx) - 6) return -1;
  tx[0] = tx[1] = 0xFF;
  tx[2] = id;
  tx[3] = (uint8_t)(n + 2);
  tx[4] = inst;
  memcpy(tx + 5, prm, n);
  uint32_t sum = 0;
  for (int i = 2; i < 5 + n; i++) sum += tx[i];
  tx[5 + n] = (uint8_t)~sum;
  uart_flush_input(SCS_UART);
  if (uart_write_bytes(SCS_UART, tx, 6 + n) != 6 + n) return -1;
  return uart_wait_tx_done(SCS_UART, pdMS_TO_TICKS(SCS_TIMEOUT_MS)) == ESP_OK ? 0 : -1;
}

// Sends and reads the status packet; `data` gets its n_data parameter bytes.
// Returns 0, -1 (no or bad reply) or the servo's error byte (> 0).
static int scs_txrx(uint8_t id, uint8_t inst, const uint8_t *prm, int n, uint8_t *data,
                    int n_data) {
  if (scs_send(id, inst, prm, n)) return -1;
  uint8_t rx[12];
  int want = 6 + n_data;  // FF FF id len err data... checksum
  if (want > (int)sizeof(rx)) return -1;
  int got = uart_read_bytes(SCS_UART, rx, want, pdMS_TO_TICKS(SCS_TIMEOUT_MS));
  g_rx_got = got;
  if (got > 0) memcpy(g_rx_last, rx, got);
  if (got != want || rx[0] != 0xFF || rx[1] != 0xFF || rx[2] != id || rx[3] != n_data + 2) {
    return -1;
  }
  uint32_t sum = 0;
  for (int i = 2; i < want - 1; i++) sum += rx[i];
  if ((uint8_t)~sum != rx[want - 1]) return -1;
  if (n_data) memcpy(data, rx + 5, n_data);
  return rx[4] & 0x7F;
}

static int scs_torque(uint8_t id, int on) {
  const uint8_t p[2] = {SCS_REG_TORQUE, (uint8_t)(on ? 1 : 0)};
  return scs_txrx(id, SCS_WRITE, p, 2, NULL, 0);
}

static int scs_goal(uint8_t id, int raw, int time_ms) {
  const uint8_t p[7] = {SCS_REG_GOAL, (uint8_t)(raw >> 8), (uint8_t)raw,
                        (uint8_t)(time_ms >> 8), (uint8_t)time_ms, 0, 0};
  return scs_txrx(id, SCS_WRITE, p, 7, NULL, 0);
}

static int scs_present(uint8_t id, int *raw) {
  const uint8_t p[2] = {SCS_REG_PRESENT, 2};
  uint8_t d[2];
  int r = scs_txrx(id, SCS_READ, p, 2, d, 2);
  if (r == 0) *raw = d[0] << 8 | d[1];
  return r;
}

static int scs_ping(uint8_t id) { return scs_txrx(id, SCS_PING, NULL, 0, NULL, 0); }

// ---------------------------------------------------------------------------------------
// Stop

void servo_stop(const char *src, int power_off) {
  g_gen++;  // from here on the dispatcher writes nothing more for the current plan
  xQueueReset(g_q);
  int was_on = g_output;
  if (power_off) g_output = 0;
  int torque = -2, power = -2;  // -2: not attempted
  if (g_uart_open && (was_on || g_torque)) {
    int locked = xSemaphoreTake(g_bus, pdMS_TO_TICKS(100)) == pdTRUE;
    // Broadcast (no reply) first so both servos let go even if one stops answering.
    const uint8_t p[2] = {SCS_REG_TORQUE, 0};
    scs_send(SCS_BROADCAST, SCS_WRITE, p, 2);
    torque = scs_torque(SCS_ID_YAW, 0) | scs_torque(SCS_ID_PITCH, 0);
    g_last_raw[0] = g_last_raw[1] = -1;
    if (locked) xSemaphoreGive(g_bus);
  }
  g_torque = 0;
  if (power_off) power = board_servo_power(0);
  out_lock();
  printf(
      "JTALM {\"t\":\"stop\",\"src\":\"%s\",\"power_off\":%d,\"output_was\":%d"
      ",\"torque_off\":%d,\"vm_off\":%d}\n",
      src, power_off, was_on, torque, power
  );
  out_unlock();
}

static void fault(const char *why) {
  g_faults++;
  out_lock();
  printf("JTALM {\"t\":\"fault\",\"why\":\"%s\",\"output\":%d}\n", why, g_output);
  out_unlock();
  servo_stop(why, 1);
}

// ---------------------------------------------------------------------------------------
// Dispatcher

typedef struct {
  const msg_t *m;
  int real, aborted, ticks;
  const char *err;
  int64_t tick_max_us;  // longest interval between two goal updates (jitter check)
} run_t;

static int still_current(const run_t *r) { return r->m->gen == g_gen; }

static void write_goals(run_t *r, double yaw, double pitch) {
  if (!r->real || r->err) return;
  const int raw[2] = {act_yaw_raw(yaw), act_pitch_raw(pitch)};
  const uint8_t ids[2] = {SCS_ID_YAW, SCS_ID_PITCH};
  if (xSemaphoreTake(g_bus, pdMS_TO_TICKS(50)) != pdTRUE) {
    r->err = "bus busy";
    return;
  }
  for (int i = 0; i < 2 && !r->err; i++) {
    if (!still_current(r)) break;  // a stop took over: write nothing more
    if (raw[i] == g_last_raw[i]) continue;
    if (scs_goal(ids[i], raw[i], MOTION_TICK_MS)) {
      r->err = "servo write failed";
    } else {
      g_last_raw[i] = raw[i];
    }
  }
  xSemaphoreGive(g_bus);
}

// Cosine-eased move from the current pose to (yaw, pitch) over ms, one goal per tick.
static void move_to(run_t *r, double yaw, double pitch, int ms) {
  double y0 = g_yaw, p0 = g_pitch;
  int n = ms / MOTION_TICK_MS;
  TickType_t wake = xTaskGetTickCount();
  int64_t prev = 0;
  for (int k = 1; k <= n; k++) {
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(MOTION_TICK_MS));
    if (!still_current(r)) {
      r->aborted = 1;
      return;
    }
    int64_t t = now_us();
    if (k > 1 && t - prev > r->tick_max_us) r->tick_max_us = t - prev;
    prev = t;
    double s = 0.5 - 0.5 * cos(M_PI * k / n);
    g_yaw = y0 + (yaw - y0) * s;
    g_pitch = p0 + (pitch - p0) * s;
    write_goals(r, g_yaw, g_pitch);
    r->ticks++;
    if (r->err) return;
  }
  g_yaw = yaw;
  g_pitch = pitch;
}

static void pause_ms(run_t *r, int ms) {
  int64_t end = now_us() + (int64_t)ms * 1000;
  while (!r->aborted && now_us() < end) {
    vTaskDelay(pdMS_TO_TICKS(10));
    if (!still_current(r)) r->aborted = 1;
  }
}

// Torque on at the present pose (goal = present first, so nothing jumps).
static void engage(run_t *r) {
  if (g_torque) return;
  if (xSemaphoreTake(g_bus, pdMS_TO_TICKS(50)) != pdTRUE) {
    r->err = "bus busy";
    return;
  }
  int raw[2];
  if (!still_current(r)) {
    r->aborted = 1;
  } else if (scs_present(SCS_ID_YAW, &raw[0]) || scs_present(SCS_ID_PITCH, &raw[1])) {
    r->err = "servo read failed";
  } else if (scs_goal(SCS_ID_YAW, raw[0], 0) || scs_goal(SCS_ID_PITCH, raw[1], 0) ||
             scs_torque(SCS_ID_YAW, 1) || scs_torque(SCS_ID_PITCH, 1)) {
    r->err = "servo torque on failed";
  } else {
    g_last_raw[0] = raw[0];
    g_last_raw[1] = raw[1];
    g_yaw = act_yaw_deg(raw[0]);
    g_pitch = act_pitch_deg(raw[1]);
    g_torque = 1;
  }
  xSemaphoreGive(g_bus);
}

static void run_plan(const msg_t *m) {
  const act_plan_t *p = &m->plan;
  run_t r = {.m = m, .real = g_output};
  int64_t t0 = now_us();
  g_deadline_us = t0 + (int64_t)(p->total_ms + WATCHDOG_MARGIN_MS) * 1000;
  g_active = 1;
  int sync_ms = 0;
  int changed = 0;  // a setting step ran: the settings are stored after the plan
  if (r.real) {
    engage(&r);
    double d = fmax(fabs(g_yaw - p->yaw0), fabs(g_pitch - p->pitch0));
    if (!r.err && !r.aborted && d > SYNC_DEG) {
      sync_ms = act_move_ms(d);
      g_deadline_us = now_us() + (int64_t)(sync_ms + p->total_ms + WATCHDOG_MARGIN_MS) * 1000;
      move_to(&r, p->yaw0, p->pitch0, sync_ms);
    }
  } else {
    g_yaw = p->yaw0;  // dry-run: the simulated pose follows the plan
    g_pitch = p->pitch0;
  }
  for (int i = 0; i < p->n_steps && !r.err && !r.aborted; i++) {
    const act_step_t *s = &p->steps[i];
    if (i > 0 && s->call != p->steps[i - 1].call) pause_ms(&r, MOTION_CALL_GAP_MS);
    if (r.aborted) break;
    switch (s->kind) {
      case STEP_MOVE:
        move_to(&r, s->yaw, s->pitch, s->ms);
        break;
      case STEP_PAUSE:  // hold the pose (bow); a stop still ends it, the watchdog covers it
        pause_ms(&r, s->ms);
        break;
      case STEP_EXPR: {
        face_info_t f;
        int err = board_face(s->arg, &f);
        out_lock();
        printf(
            "JTALM {\"t\":\"face\",\"seq\":%" PRIu32 ",\"expr\":\"%s\",\"ok\":%d"
            ",\"crc\":\"%08" PRIx32 "\",\"draw_us\":%" PRIu32 ",\"push_us\":%" PRIu32 "}\n",
            m->seq, act_expr_names[s->arg], err == 0, f.crc, f.draw_us, f.push_us
        );
        out_unlock();
        break;
      }
      case STEP_LED: {
        const uint8_t *rgb = act_led_rgb[s->arg];
        int err = board_led(rgb[0], rgb[1], rgb[2]);  // board_led keeps each channel <= 168
        g_settings.led = s->arg;
        changed = 1;
        out_lock();
        printf(
            "JTALM {\"t\":\"setting\",\"seq\":%" PRIu32 ",\"what\":\"led\",\"color\":\"%s\""
            ",\"ok\":%d}\n",
            m->seq, act_color_names[s->arg], err == 0
        );
        out_unlock();
        break;
      }
      case STEP_VOLUME:
      case STEP_BRIGHTNESS: {
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
        printf(
            "JTALM {\"t\":\"setting\",\"seq\":%" PRIu32 ",\"what\":\"%s\",\"level\":%d"
            ",\"ok\":%d}\n",
            m->seq, bright ? "brightness" : "volume", level, err == 0
        );
        out_unlock();
        break;
      }
      default:  // a step kind this dispatcher does not know: nothing is done
        out_lock();
        printf(
            "JTALM {\"t\":\"error\",\"seq\":%" PRIu32 ",\"msg\":\"unknown step kind %d\"}\n",
            m->seq, s->kind
        );
        out_unlock();
        break;
    }
  }
  int present[2] = {-1, -1};
  if (r.real && !r.err && xSemaphoreTake(g_bus, pdMS_TO_TICKS(50)) == pdTRUE) {
    if (still_current(&r)) {
      scs_present(SCS_ID_YAW, &present[0]);
      scs_present(SCS_ID_PITCH, &present[1]);
    }
    xSemaphoreGive(g_bus);
  }
  g_release_us = now_us() + (int64_t)HOLD_MS * 1000;
  g_active = 0;
  int64_t t1 = now_us();
  out_lock();
  printf(
      "JTALM {\"t\":\"act_done\",\"seq\":%" PRIu32 ",\"servo\":\"%s\",\"planned_ms\":%" PRIu32
      ",\"ms\":%.1f,\"sync_ms\":%d,\"ticks\":%d,\"tick_max_ms\":%.1f,\"aborted\":%d"
      ",\"err\":%s%s%s,\"pose\":[%.1f,%.1f],\"present\":[%d,%d]}\n",
      m->seq, r.real ? "on" : "dry", p->total_ms, (t1 - t0) / 1000.0, sync_ms, r.ticks,
      r.tick_max_us / 1000.0, r.aborted, r.err ? "\"" : "", r.err ? r.err : "null",
      r.err ? "\"" : "", g_yaw, g_pitch, present[0], present[1]
  );
  out_unlock();
  // A fault first: torque off and VM_EN low never wait for the NVS write (a page erase can
  // take tens of ms). NVS is written after the plan, outside its watchdog deadline.
  if (r.err) fault(r.err);
  if (changed && settings_save(&g_settings) != 0) {
    out_lock();
    printf("JTALM {\"t\":\"error\",\"msg\":\"settings save failed\"}\n");
    out_unlock();
  }
}

// VM_EN on, then ping both servos every POWER_POLL_MS until they answer (the SCS0009 needs
// about 1 s after its supply comes up), then read their positions. Caller holds g_bus.
// ping_ms gets the time from VM_EN on to the first answer of yaw and pitch (-1: none).
static const char *power_up(int raw[2], int ping_ms[2], int *attempts) {
  raw[0] = raw[1] = ping_ms[0] = ping_ms[1] = -1;
  *attempts = 0;
  if (scs_open()) return "uart init failed";
  if (board_servo_power(1)) return "VM_EN on failed (no IO expander?)";
  int64_t t0 = now_us();
  const uint8_t ids[2] = {SCS_ID_YAW, SCS_ID_PITCH};
  while ((ping_ms[0] < 0 || ping_ms[1] < 0) && now_us() - t0 < POWER_ON_TIMEOUT_MS * 1000LL) {
    vTaskDelay(pdMS_TO_TICKS(POWER_POLL_MS));
    ++*attempts;
    for (int i = 0; i < 2; i++) {
      if (ping_ms[i] < 0 && scs_ping(ids[i]) == 0) ping_ms[i] = (int)((now_us() - t0) / 1000);
    }
  }
  if (ping_ms[0] < 0 || ping_ms[1] < 0) return "servo does not answer";
  for (int i = 0; i < 2; i++) {
    int r = -1;
    for (int k = 0; k < 3 && r != 0; k++) r = scs_present(ids[i], &raw[i]);
    if (r != 0) return "servo position read failed";
  }
  return NULL;
}

static void servo_on(const msg_t *m) {
  const char *err = NULL;
  int raw[2] = {-1, -1}, ping_ms[2] = {-1, -1}, attempts = 0;
  if (g_output) {
    err = "already on";
  } else if (xSemaphoreTake(g_bus, pdMS_TO_TICKS(100)) != pdTRUE) {
    err = "bus busy";
  } else {
    err = power_up(raw, ping_ms, &attempts);
    if (err) {
      board_servo_power(0);
    } else if (m->gen == g_gen) {
      g_torque = 0;
      g_last_raw[0] = g_last_raw[1] = -1;
      g_yaw = act_yaw_deg(raw[0]);
      g_pitch = act_pitch_deg(raw[1]);
      g_output = 1;
    } else {
      board_servo_power(0);  // a stop came in while powering up
      err = "stopped";
    }
    xSemaphoreGive(g_bus);
  }
  out_lock();
  printf(
      "JTALM {\"t\":\"servo\",\"state\":\"%s\",\"err\":%s%s%s,\"ping_ms\":[%d,%d],\"polls\":%d"
      ",\"present\":[%d,%d],\"deg\":[%.1f,%.1f]}\n",
      g_output ? "on" : "off", err ? "\"" : "", err ? err : "null", err ? "\"" : "", ping_ms[0],
      ping_ms[1], attempts, raw[0], raw[1], raw[0] < 0 ? 0.0 : act_yaw_deg(raw[0]),
      raw[1] < 0 ? 0.0 : act_pitch_deg(raw[1])
  );
  out_unlock();
}

static void print_regs(const char *step) {
  uint8_t py[16], aw[8];
  board_regs(py, 16, aw, 8);
  out_lock();
  printf("JTALM {\"t\":\"probe\",\"step\":\"%s\",\"vm_en\":%d,\"py32\":[", step,
         board_servo_power_state());
  for (int i = 0; i < 16; i++) printf(i ? ",%d" : "%d", py[i]);
  fputs("],\"aw9523\":[", stdout);
  for (int i = 0; i < 8; i++) printf(i ? ",%d" : "%d", aw[i]);
  fputs("]}\n", stdout);
  out_unlock();
}

// "!servo probe" (servo output off only): power up, ping, read the positions, power off.
// Never writes a goal or enables torque.
static void probe(void) {
  if (g_output || xSemaphoreTake(g_bus, pdMS_TO_TICKS(100)) != pdTRUE) {
    out_lock();
    printf("JTALM {\"t\":\"probe\",\"step\":\"skipped\",\"output\":%d}\n", g_output);
    out_unlock();
    return;
  }
  print_regs("before");
  int raw[2], ping_ms[2], attempts;
  const char *err = power_up(raw, ping_ms, &attempts);
  print_regs("powered");
  int off = board_servo_power(0);
  xSemaphoreGive(g_bus);
  out_lock();
  printf(
      "JTALM {\"t\":\"probe\",\"step\":\"result\",\"err\":%s%s%s,\"ping_ms\":[%d,%d]"
      ",\"polls\":%d,\"present\":[%d,%d],\"deg\":[%.1f,%.1f],\"rx_got\":%d,\"rx\":[",
      err ? "\"" : "", err ? err : "null", err ? "\"" : "", ping_ms[0], ping_ms[1], attempts,
      raw[0], raw[1], raw[0] < 0 ? 0.0 : act_yaw_deg(raw[0]),
      raw[1] < 0 ? 0.0 : act_pitch_deg(raw[1]), g_rx_got
  );
  for (int i = 0; i < g_rx_got && i < (int)sizeof(g_rx_last); i++) {
    printf(i ? ",%d" : "%d", g_rx_last[i]);
  }
  printf("],\"vm_off\":%d}\n", off);
  out_unlock();
  print_regs("after");
}

static void release_if_idle(void) {
  if (!g_torque || g_active || now_us() < g_release_us) return;
  if (xSemaphoreTake(g_bus, pdMS_TO_TICKS(50)) != pdTRUE) return;
  int err = scs_torque(SCS_ID_YAW, 0) | scs_torque(SCS_ID_PITCH, 0);
  g_last_raw[0] = g_last_raw[1] = -1;
  g_torque = 0;
  xSemaphoreGive(g_bus);
  if (err) fault("torque release failed");
}

// "!wdtest" (dry-run only): a plan that overruns its deadline and ignores stops, so that the
// guard's watchdog fires (a "fault" and a "stop" record follow).
static void wdtest(void) {
  int64_t t0 = now_us();
  if (!g_output) {
    g_deadline_us = t0 + 100 * 1000;
    g_active = 1;
    vTaskDelay(pdMS_TO_TICKS(1000));
    g_active = 0;
  }
  out_lock();
  printf(
      "JTALM {\"t\":\"wdtest\",\"ran\":%d,\"ms\":%.1f,\"faults\":%d}\n", !g_output,
      (now_us() - t0) / 1000.0, g_faults
  );
  out_unlock();
}

static void dispatcher_task(void *arg) {
  static msg_t m;
  for (;;) {
    if (xQueueReceive(g_q, &m, pdMS_TO_TICKS(GUARD_PERIOD_MS)) != pdTRUE) {
      release_if_idle();
      continue;
    }
    if (m.gen != g_gen) continue;  // dropped by a stop
    if (m.type == MSG_ON) {
      servo_on(&m);
    } else if (m.type == MSG_WDTEST) {
      wdtest();
    } else if (m.type == MSG_PROBE) {
      probe();
    } else {
      run_plan(&m);
    }
  }
}

// Watchdog (a plan past its deadline), torque backstop, and the touch stop.
static void guard_task(void *arg) {
  int64_t next_touch = 0;
  int touched = 0;
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(GUARD_PERIOD_MS));
    int64_t t = now_us();
    if (g_active && t > g_deadline_us) {
      g_active = 0;
      fault("watchdog");
    }
    if (g_torque && !g_active) {
      if (!g_torque_idle_us) g_torque_idle_us = t;
      if (t - g_torque_idle_us > (int64_t)TORQUE_IDLE_MAX_MS * 1000) fault("torque idle");
    } else {
      g_torque_idle_us = 0;
    }
    if (t >= next_touch) {
      next_touch = t + (int64_t)TOUCH_PERIOD_MS * 1000;
      int now_touched = board_touched();
      if (now_touched && !touched) servo_stop("touch", 1);
      touched = now_touched;
    }
  }
}

int servo_start(void) {
  g_q = xQueueCreateWithCaps(QUEUE_LEN, sizeof(msg_t), MALLOC_CAP_SPIRAM);
  g_bus = xSemaphoreCreateMutex();
  if (g_q == NULL || g_bus == NULL) return -1;
  if (xTaskCreatePinnedToCore(dispatcher_task, "dispatch", 6 * 1024, NULL, 6, NULL, 0) !=
      pdPASS) {
    return -1;
  }
  return xTaskCreatePinnedToCore(guard_task, "guard", 4 * 1024, NULL, 7, NULL, 1) == pdPASS
             ? 0
             : -1;
}

int servo_submit(const act_plan_t *plan, uint32_t seq) {
  static msg_t m;  // only the LM task submits
  m.type = MSG_PLAN;
  m.seq = seq;
  m.gen = g_gen;
  m.plan = *plan;
  return xQueueSend(g_q, &m, 0) == pdTRUE ? 0 : -1;
}

static int request(int type) {
  static msg_t m;  // only the LM task requests
  memset(&m, 0, sizeof(m));
  m.type = (uint8_t)type;
  m.gen = g_gen;
  return xQueueSend(g_q, &m, 0) == pdTRUE ? 0 : -1;
}

int servo_request_on(void) { return request(MSG_ON); }

int servo_request_wdtest(void) { return request(MSG_WDTEST); }

int servo_request_probe(void) { return request(MSG_PROBE); }

int servo_output_on(void) { return g_output; }

void servo_status(void) {
  out_lock();
  printf(
      "JTALM {\"t\":\"servo\",\"state\":\"%s\",\"torque\":%d,\"uart\":%d,\"active\":%d"
      ",\"queued\":%d,\"faults\":%d,\"vm_en\":%d,\"pose\":[%.1f,%.1f]}\n",
      g_output ? "on" : "off", g_torque, g_uart_open, g_active,
      (int)uxQueueMessagesWaiting(g_q), g_faults, board_servo_power_state(), g_yaw, g_pitch
  );
  out_unlock();
}

void out_init(void) { g_print = xSemaphoreCreateMutex(); }

void servo_set_settings(const settings_t *s) { g_settings = *s; }
