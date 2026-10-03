// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
//
// Action schema v1 validator and planner (see action.h).
//
// The validator parses any JSON the way Python's json.loads does (duplicate object keys keep
// the last value; 2.0 is an integer for the schema, as in jsonschema) and then applies the
// schema, so that it accepts exactly what jtalm.action.parse_output(...).schema_valid does.

#include "action.h"

#include <inttypes.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

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

// ---------------------------------------------------------------------------------------
// JSON

#define JS_MAX_NODES 96
#define JS_MAX_DEPTH 16
#define JS_STR_BYTES 1024

enum { JS_NULL, JS_FALSE, JS_TRUE, JS_NUM, JS_STR, JS_ARR, JS_OBJ };

typedef struct {
  uint8_t type;
  uint8_t is_float;  // JS_NUM: written with a fraction or exponent (a Python float)
  int16_t child, next, key;  // key: for object members, the node of the key string
  uint16_t str, len;         // JS_STR: decoded bytes in the string pool
  double num;
} js_node_t;

typedef struct {
  const char *p, *end;
  js_node_t nodes[JS_MAX_NODES];
  int n_nodes;
  char strs[JS_STR_BYTES];
  int n_strs;
} js_t;

static void js_ws(js_t *j) {
  while (j->p < j->end && (*j->p == ' ' || *j->p == '\t' || *j->p == '\n' || *j->p == '\r')) {
    j->p++;
  }
}

static int js_new(js_t *j, int type) {
  if (j->n_nodes >= JS_MAX_NODES) return -1;
  js_node_t *n = &j->nodes[j->n_nodes];
  memset(n, 0, sizeof(*n));
  n->type = type;
  n->child = n->next = n->key = -1;
  return j->n_nodes++;
}

static int hexval(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static int js_string(js_t *j) {
  if (j->p >= j->end || *j->p != '"') return -1;
  j->p++;
  int id = js_new(j, JS_STR);
  if (id < 0) return -1;
  j->nodes[id].str = (uint16_t)j->n_strs;
  while (j->p < j->end && *j->p != '"') {
    unsigned char c = (unsigned char)*j->p++;
    if (c < 0x20) return -1;  // json.loads(strict=True) rejects raw control characters
    if (c == '\\') {
      if (j->p >= j->end) return -1;
      char e = *j->p++;
      switch (e) {
        case '"': case '\\': case '/': c = (unsigned char)e; break;
        case 'b': c = '\b'; break;
        case 'f': c = '\f'; break;
        case 'n': c = '\n'; break;
        case 'r': c = '\r'; break;
        case 't': c = '\t'; break;
        case 'u': {
          if (j->end - j->p < 4) return -1;
          int v = 0;
          for (int i = 0; i < 4; i++) {
            int h = hexval(j->p[i]);
            if (h < 0) return -1;
            v = v * 16 + h;
          }
          j->p += 4;
          // Only ASCII can match a schema value; anything else becomes a byte no name has.
          c = v < 0x80 ? (unsigned char)v : 0xFF;
          break;
        }
        default: return -1;
      }
    }
    if (j->n_strs >= JS_STR_BYTES) return -1;
    j->strs[j->n_strs++] = (char)c;
  }
  if (j->p >= j->end) return -1;
  j->p++;
  j->nodes[id].len = (uint16_t)(j->n_strs - j->nodes[id].str);
  return id;
}

static int js_number(js_t *j) {
  const char *s = j->p;
  if (j->p < j->end && *j->p == '-') j->p++;
  if (j->p >= j->end) return -1;
  if (*j->p == '0') {
    j->p++;
  } else if (*j->p >= '1' && *j->p <= '9') {
    while (j->p < j->end && *j->p >= '0' && *j->p <= '9') j->p++;
  } else {
    return -1;
  }
  int is_float = 0;
  if (j->p < j->end && *j->p == '.') {
    j->p++;
    if (j->p >= j->end || *j->p < '0' || *j->p > '9') return -1;
    while (j->p < j->end && *j->p >= '0' && *j->p <= '9') j->p++;
    is_float = 1;
  }
  if (j->p < j->end && (*j->p == 'e' || *j->p == 'E')) {
    j->p++;
    if (j->p < j->end && (*j->p == '+' || *j->p == '-')) j->p++;
    if (j->p >= j->end || *j->p < '0' || *j->p > '9') return -1;
    while (j->p < j->end && *j->p >= '0' && *j->p <= '9') j->p++;
    is_float = 1;
  }
  char buf[64];
  size_t len = (size_t)(j->p - s);
  if (len >= sizeof(buf)) len = sizeof(buf) - 1;  // only 0..180 can be valid anyway
  memcpy(buf, s, len);
  buf[len] = '\0';
  int id = js_new(j, JS_NUM);
  if (id < 0) return -1;
  j->nodes[id].num = strtod(buf, NULL);
  j->nodes[id].is_float = (uint8_t)is_float;
  return id;
}

static int js_literal(js_t *j, const char *word, int type) {
  size_t n = strlen(word);
  if ((size_t)(j->end - j->p) < n || memcmp(j->p, word, n)) return -1;
  j->p += n;
  return js_new(j, type);
}

static int js_value(js_t *j, int depth) {
  if (depth > JS_MAX_DEPTH) return -1;
  js_ws(j);
  if (j->p >= j->end) return -1;
  char c = *j->p;
  if (c == '"') return js_string(j);
  if (c == 't') return js_literal(j, "true", JS_TRUE);
  if (c == 'f') return js_literal(j, "false", JS_FALSE);
  if (c == 'n') return js_literal(j, "null", JS_NULL);
  if (c == '-' || (c >= '0' && c <= '9')) return js_number(j);
  if (c != '[' && c != '{') return -1;
  int obj = c == '{';
  int id = js_new(j, obj ? JS_OBJ : JS_ARR);
  if (id < 0) return -1;
  j->p++;
  js_ws(j);
  if (j->p < j->end && *j->p == (obj ? '}' : ']')) {
    j->p++;
    return id;
  }
  int last = -1;
  for (;;) {
    int key = -1;
    if (obj) {
      js_ws(j);
      key = js_string(j);
      if (key < 0) return -1;
      js_ws(j);
      if (j->p >= j->end || *j->p != ':') return -1;
      j->p++;
    }
    int v = js_value(j, depth + 1);
    if (v < 0) return -1;
    j->nodes[v].key = (int16_t)key;
    if (last < 0) {
      j->nodes[id].child = (int16_t)v;
    } else {
      j->nodes[last].next = (int16_t)v;
    }
    last = v;
    js_ws(j);
    if (j->p >= j->end) return -1;
    if (*j->p == ',') {
      j->p++;
      continue;
    }
    if (*j->p == (obj ? '}' : ']')) {
      j->p++;
      return id;
    }
    return -1;
  }
}

static int js_str_eq(const js_t *j, int id, const char *s) {
  const js_node_t *n = &j->nodes[id];
  size_t len = strlen(s);
  return n->type == JS_STR && n->len == len && !memcmp(j->strs + n->str, s, len);
}

// Index of `s` in `names` if node `id` is that string, else -1.
static int js_enum(const js_t *j, int id, const char *const *names, int n) {
  for (int i = 0; i < n; i++) {
    if (js_str_eq(j, id, names[i])) return i;
  }
  return -1;
}

// Resolves the members of an object against `keys` (Python keeps the last duplicate).
// Returns -1 if a member has another key or a required key is missing.
static int js_members(const js_t *j, int obj, const char *const *keys, int n, int *vals) {
  for (int i = 0; i < n; i++) vals[i] = -1;
  for (int m = j->nodes[obj].child; m >= 0; m = j->nodes[m].next) {
    int k = 0;
    while (k < n && !js_str_eq(j, j->nodes[m].key, keys[k])) k++;
    if (k == n) return -1;
    vals[k] = m;
  }
  for (int i = 0; i < n; i++) {
    if (vals[i] < 0) return -1;
  }
  return 0;
}

// An integer for the schema (integral floats count, as in jsonschema) within lo..hi.
static int js_int(const js_t *j, int id, int lo, int hi, act_call_t *call) {
  const js_node_t *c = &j->nodes[id];
  if (c->type != JS_NUM || c->num != floor(c->num) || c->num < lo || c->num > hi) return -1;
  call->value = (int16_t)c->num;
  // json.dumps writes -0.0 and 0.0 differently, so the duplicate rule tells them apart too.
  call->num_float = c->is_float ? (signbit(c->num) ? 2 : 1) : 0;
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

// ---------------------------------------------------------------------------------------
// Planner

static int clampi(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

#define YAW_MIN ACT_YAW_MIN_DEG
#define YAW_MAX ACT_YAW_MAX_DEG
#define PITCH_MIN ACT_PITCH_MIN_DEG
#define PITCH_MAX ACT_PITCH_MAX_DEG

uint16_t act_move_ms_limits(double deg, double vmax_dps, double amax_dps2) {
  if (deg <= 0) return 0;
  // Cosine ease over T: peak speed pi*D/(2T), peak acceleration pi^2*D/(2T^2).
  double t_v = M_PI * deg / (2.0 * vmax_dps);
  double t_a = M_PI * sqrt(deg / (2.0 * amax_dps2));
  double t = t_v > t_a ? t_v : t_a;
  return (uint16_t)(ceil(t * 1000.0 / MOTION_TICK_MS - 1e-9) * MOTION_TICK_MS);
}

uint16_t act_move_ms(double deg) {
  return act_move_ms_limits(deg, MOTION_VMAX_DPS, MOTION_AMAX_DPS2);
}

uint16_t act_yaw_raw(double deg) { return (uint16_t)lround(SERVO_YAW_ZERO - deg * 16.0 / 5.0); }

uint16_t act_pitch_raw(double deg) {
  return (uint16_t)lround(SERVO_PITCH_ZERO + deg * 16.0 / 5.0);
}

double act_yaw_deg(int raw) { return (SERVO_YAW_ZERO - raw) * 5.0 / 16.0; }

double act_pitch_deg(int raw) { return (raw - SERVO_PITCH_ZERO) * 5.0 / 16.0; }

static void add_move(act_plan_t *p, int call, int yaw_req, int pitch_req, int *yaw,
                     int *pitch, int swing) {
  if (p->n_steps >= ACT_MAX_STEPS) return;
  act_step_t *s = &p->steps[p->n_steps++];
  memset(s, 0, sizeof(*s));
  s->kind = STEP_MOVE;
  s->call = (uint8_t)call;
  s->yaw = (int16_t)clampi(yaw_req, YAW_MIN, YAW_MAX);
  s->pitch = (int16_t)clampi(pitch_req, PITCH_MIN, PITCH_MAX);
  s->clamped = s->yaw != yaw_req || s->pitch != pitch_req;
  s->yaw_raw = act_yaw_raw(s->yaw);
  s->pitch_raw = act_pitch_raw(s->pitch);
  int dy = abs(s->yaw - *yaw), dp = abs(s->pitch - *pitch);
  int d = dy > dp ? dy : dp;
  s->ms = swing ? act_move_ms_limits(d, MOTION_NOD_VMAX_DPS, MOTION_NOD_AMAX_DPS2)
                : act_move_ms(d);
  p->total_ms += s->ms;
  *yaw = s->yaw;
  *pitch = s->pitch;
}

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
      // nod, shake and bow end with a move back to the start pose only when they are not
      // already there (mapping.plan_v1's back_to).
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
        if (pitch != start) add_move(p, c, yaw, start, &yaw, &pitch, 1);
        break;
      }
      case ACT_SHAKE: {
        // mapping.plan_v1: right then left of the current yaw, `count` times, then back.
        int start = yaw;
        for (int i = 0; i < call->value; i++) {
          add_move(p, c, start + ACT_SHAKE_YAW_DEG, pitch, &yaw, &pitch, 1);
          add_move(p, c, start - ACT_SHAKE_YAW_DEG, pitch, &yaw, &pitch, 1);
        }
        if (yaw != start) add_move(p, c, start, pitch, &yaw, &pitch, 1);
        break;
      }
      case ACT_BOW: {
        // mapping.plan_v1: from below ACT_BOW_LIFT_DEG (near the floor) a bow would barely move, so
        // the head lifts there first; then down to the lower limit, a hold, and back.
        int start = pitch;
        if (pitch < ACT_BOW_LIFT_DEG) add_move(p, c, yaw, ACT_BOW_LIFT_DEG, &yaw, &pitch, 0);
        add_move(p, c, yaw, PITCH_MIN, &yaw, &pitch, 0);
        s = add_step(p, c, STEP_PAUSE, yaw, pitch);
        if (s) {
          s->ms = ACT_BOW_HOLD_MS;
          p->total_ms += ACT_BOW_HOLD_MS;
        }
        if (pitch != start) add_move(p, c, yaw, start, &yaw, &pitch, 0);
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

// ---------------------------------------------------------------------------------------
// The "act" record

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
