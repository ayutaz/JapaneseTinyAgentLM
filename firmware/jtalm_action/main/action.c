// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 JapaneseTinyAgentLM contributors
//
// Action schema v0 validator and planner (see action.h).
//
// The validator parses any JSON the way Python's json.loads does (duplicate object keys keep
// the last value; 2.0 is an integer for the schema, as in jsonschema) and then applies the
// schema, so that it accepts exactly what jtalm.action.parse_output(...).schema_valid does.

#include "action.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

const char *const act_dir_names[5] = {"left", "right", "up", "down", "center"};
const char *const act_amount_names[3] = {"slight", "normal", "large"};
const char *const act_expr_names[EXPR_COUNT] = {"happy", "sad", "surprised", "neutral"};

static const int kYawDeg[3] = {10, 20, 30};   // mapping.YAW_DEG
static const int kPitchDeg[3] = {5, 10, 15};  // mapping.PITCH_DEG

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
  if (len >= sizeof(buf)) len = sizeof(buf) - 1;  // only 1..3 can be valid anyway
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

static const char *js_call(const js_t *j, int item, act_call_t *call, uint8_t *count_float) {
  static const char *const kCallKeys[2] = {"name", "arguments"};
  static const char *const kTools[3] = {"look", "set_expression", "nod"};
  static const char *const kLookKeys[2] = {"direction", "amount"};
  static const char *const kExprKeys[1] = {"expression"};
  static const char *const kNodKeys[1] = {"count"};
  int v[2], a[2];
  if (j->nodes[item].type != JS_OBJ) return "call is not an object";
  if (js_members(j, item, kCallKeys, 2, v)) return "call keys";
  int kind = js_enum(j, v[0], kTools, 3);
  if (kind < 0) return "unknown tool";
  int args = v[1];
  if (j->nodes[args].type != JS_OBJ) return "arguments is not an object";
  memset(call, 0, sizeof(*call));
  call->kind = (uint8_t)kind;
  *count_float = 0;
  if (kind == ACT_LOOK) {
    if (js_members(j, args, kLookKeys, 2, a)) return "look arguments";
    int dir = js_enum(j, a[0], act_dir_names, 5);
    int amount = js_enum(j, a[1], act_amount_names, 3);
    if (dir < 0 || amount < 0) return "look enum";
    call->dir = (uint8_t)dir;
    call->amount = (uint8_t)amount;
  } else if (kind == ACT_EXPR) {
    if (js_members(j, args, kExprKeys, 1, a)) return "set_expression arguments";
    int expr = js_enum(j, a[0], act_expr_names, EXPR_COUNT);
    if (expr < 0) return "expression enum";
    call->expr = (uint8_t)expr;
  } else {
    if (js_members(j, args, kNodKeys, 1, a)) return "nod arguments";
    const js_node_t *c = &j->nodes[a[0]];
    if (c->type != JS_NUM || c->num != floor(c->num)) return "count is not an integer";
    if (c->num < 1 || c->num > 3) return "count out of range";
    call->count = (uint8_t)c->num;
    *count_float = c->is_float;
  }
  return NULL;
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
  uint8_t count_float[ACT_MAX_CALLS];
  int k = 0;
  for (int item = j.nodes[root].child; item >= 0; item = j.nodes[item].next) {
    if (k == ACT_MAX_CALLS) {
      *err = "more than 2 calls";
      return -1;
    }
    const char *e = js_call(&j, item, &calls[k], &count_float[k]);
    if (e) {
      *err = e;
      return -1;
    }
    for (int i = 0; i < k; i++) {
      if (!memcmp(&calls[i], &calls[k], sizeof(calls[k])) && count_float[i] == count_float[k]) {
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

// Soft limits: the Action limits (mapping.py) intersected with the servo soft limits.
#define YAW_MIN (-ACT_YAW_LIMIT_DEG > HW_YAW_MIN_DEG ? -ACT_YAW_LIMIT_DEG : HW_YAW_MIN_DEG)
#define YAW_MAX (ACT_YAW_LIMIT_DEG < HW_YAW_MAX_DEG ? ACT_YAW_LIMIT_DEG : HW_YAW_MAX_DEG)
#define PITCH_MIN \
  (-ACT_PITCH_LIMIT_DEG > HW_PITCH_MIN_DEG ? -ACT_PITCH_LIMIT_DEG : HW_PITCH_MIN_DEG)
#define PITCH_MAX \
  (ACT_PITCH_LIMIT_DEG < HW_PITCH_MAX_DEG ? ACT_PITCH_LIMIT_DEG : HW_PITCH_MAX_DEG)

uint16_t act_move_ms(double deg) {
  if (deg <= 0) return 0;
  // Cosine ease over T: peak speed pi*D/(2T), peak acceleration pi^2*D/(2T^2).
  double t_v = M_PI * deg / (2.0 * MOTION_VMAX_DPS);
  double t_a = M_PI * sqrt(deg / (2.0 * MOTION_AMAX_DPS2));
  double t = t_v > t_a ? t_v : t_a;
  return (uint16_t)(ceil(t * 1000.0 / MOTION_TICK_MS - 1e-9) * MOTION_TICK_MS);
}

uint16_t act_yaw_raw(double deg) { return (uint16_t)lround(SERVO_YAW_ZERO - deg * 16.0 / 5.0); }

uint16_t act_pitch_raw(double deg) {
  return (uint16_t)lround(SERVO_PITCH_ZERO + deg * 16.0 / 5.0);
}

double act_yaw_deg(int raw) { return (SERVO_YAW_ZERO - raw) * 5.0 / 16.0; }

double act_pitch_deg(int raw) { return (raw - SERVO_PITCH_ZERO) * 5.0 / 16.0; }

static void add_move(act_plan_t *p, int call, int yaw_req, int pitch_req, int *yaw,
                     int *pitch) {
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
  s->ms = act_move_ms(dy > dp ? dy : dp);
  p->total_ms += s->ms;
  *yaw = s->yaw;
  *pitch = s->pitch;
}

void act_plan(act_plan_t *p, int yaw, int pitch) {
  p->n_steps = 0;
  p->total_ms = 0;
  p->yaw0 = yaw;
  p->pitch0 = pitch;
  for (int c = 0; c < p->n_calls; c++) {
    const act_call_t *call = &p->calls[c];
    if (c > 0) p->total_ms += MOTION_CALL_GAP_MS;
    if (call->kind == ACT_EXPR) {
      if (p->n_steps >= ACT_MAX_STEPS) continue;
      act_step_t *s = &p->steps[p->n_steps++];
      memset(s, 0, sizeof(*s));
      s->kind = STEP_EXPR;
      s->call = (uint8_t)c;
      s->expr = call->expr;
      s->yaw = (int16_t)yaw;
      s->pitch = (int16_t)pitch;
    } else if (call->kind == ACT_LOOK) {
      // mapping.look_target: center sets both axes; the others set one and keep the other.
      int y = yaw, pt = pitch;
      switch (call->dir) {
        case DIR_CENTER: y = 0, pt = 0; break;
        case DIR_RIGHT: y = kYawDeg[call->amount]; break;
        case DIR_LEFT: y = -kYawDeg[call->amount]; break;
        case DIR_UP: pt = kPitchDeg[call->amount]; break;
        case DIR_DOWN: pt = -kPitchDeg[call->amount]; break;
      }
      add_move(p, c, y, pt, &yaw, &pitch);
    } else {
      // mapping.nod_targets: down by NOD_PITCH_DEG and back, `count` times. On the device
      // the nod is around the current pitch (so "look up, then nod" nods while looking up).
      // Near the lower limit the down point is clamped; if less than half the amplitude is
      // left, the nod goes up from the limit instead. It always ends at the pitch it began.
      int start = pitch;
      int low = start - ACT_NOD_PITCH_DEG, high = start;
      if (low < PITCH_MIN) low = PITCH_MIN;
      if (high - low < ACT_NOD_PITCH_DEG / 2) high = low + ACT_NOD_PITCH_DEG;
      for (int i = 0; i < call->count; i++) {
        add_move(p, c, yaw, low, &yaw, &pitch);
        add_move(p, c, yaw, high, &yaw, &pitch);
      }
      if (high != start) add_move(p, c, yaw, start, &yaw, &pitch);
    }
  }
  p->yaw1 = yaw;
  p->pitch1 = pitch;
}
