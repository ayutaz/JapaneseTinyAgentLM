// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 JapaneseTinyAgentLM contributors
//
// Action schema v0 on the device: a strict validator for the LM output and the planner
// that turns validated calls into servo targets and face changes. No hardware access here.
//
// The angles follow src/jtalm/action/mapping.py (the canonical mapping); the raw conversion
// and the soft limits are the ones confirmed on the K151 (docs/hardware.md sections 3, 10).
// firmware/tools/dispatch_check.py recomputes every plan in Python and compares.

#pragma once

#include <stddef.h>
#include <stdint.h>

#define ACT_MAX_CALLS 2
#define ACT_MAX_STEPS 16  // nod 3 + nod 2 is 7 + 6 moves

enum { ACT_LOOK, ACT_EXPR, ACT_NOD };
enum { DIR_LEFT, DIR_RIGHT, DIR_UP, DIR_DOWN, DIR_CENTER };
enum { AMT_SLIGHT, AMT_NORMAL, AMT_LARGE };
enum { EXPR_HAPPY, EXPR_SAD, EXPR_SURPRISED, EXPR_NEUTRAL, EXPR_COUNT };

// mapping.py: YAW_DEG, PITCH_DEG, YAW_LIMIT_DEG, PITCH_LIMIT_DEG, NOD_PITCH_DEG
#define ACT_YAW_LIMIT_DEG 30
#define ACT_PITCH_LIMIT_DEG 15
#define ACT_NOD_PITCH_DEG 14  // nod amplitude (8 was too small to notice, 2026-09-30)
// stackchan-idf soft limits (relative to the zero position), docs/hardware.md section 10
#define HW_YAW_MIN_DEG (-40)
#define HW_YAW_MAX_DEG 40
#define HW_PITCH_MIN_DEG (-10)
#define HW_PITCH_MAX_DEG 25
// Raw position of the neutral pose; 1 step = 0.3125 deg. Right (+yaw) lowers the yaw raw,
// up (+pitch) raises the pitch raw.
#define SERVO_YAW_ZERO 460
#define SERVO_PITCH_ZERO 620
// Motion profile: every move is a cosine ease (zero velocity at both ends) whose duration
// keeps the peak speed and acceleration under these limits, rounded up to the servo tick.
#define MOTION_VMAX_DPS 90.0
#define MOTION_AMAX_DPS2 360.0
// Nod strokes are faster. With the cosine ease the acceleration limit decides the time of
// any stroke below 2*v^2/a degrees (here 50 deg): 14 deg takes 280 ms, peaking at ~79 deg/s.
#define MOTION_NOD_VMAX_DPS 150.0
#define MOTION_NOD_AMAX_DPS2 900.0
#define MOTION_TICK_MS 20
#define MOTION_CALL_GAP_MS 200  // pause between the two calls of one request

typedef struct {
  uint8_t kind;  // ACT_*
  uint8_t dir, amount, expr, count;
} act_call_t;

enum { STEP_MOVE, STEP_EXPR };

typedef struct {
  uint8_t kind;     // STEP_*
  uint8_t call;     // index of the call that produced the step
  uint8_t expr;     // STEP_EXPR
  uint8_t clamped;  // the mapped angle was outside the soft limits
  int16_t yaw, pitch;  // target pose in degrees (right / up positive), after clamping
  uint16_t yaw_raw, pitch_raw;
  uint16_t ms;  // move duration (0: already there)
} act_step_t;

typedef struct {
  int n_calls;
  act_call_t calls[ACT_MAX_CALLS];
  int n_steps;
  act_step_t steps[ACT_MAX_STEPS];
  int yaw0, pitch0, yaw1, pitch1;  // pose before and after
  uint32_t total_ms;               // moves plus the pause between calls
} act_plan_t;

extern const char *const act_dir_names[5];
extern const char *const act_amount_names[3];
extern const char *const act_expr_names[EXPR_COUNT];

// Parses and validates an Action JSON string (schema v0 plus the no-duplicate rule, as
// jtalm.action.validate). Returns 0 and fills calls, or -1 and sets *err.
int act_parse(const char *s, size_t n, act_call_t *calls, int *n_calls, const char **err);

// Plans validated calls from the pose (yaw, pitch) in degrees.
void act_plan(act_plan_t *p, int yaw, int pitch);

// Move duration in ms for a distance in degrees (0 for 0): act_move_ms with the general
// limits, act_move_ms_limits with the given peak speed and acceleration.
uint16_t act_move_ms(double deg);
uint16_t act_move_ms_limits(double deg, double vmax_dps, double amax_dps2);
uint16_t act_yaw_raw(double deg);
uint16_t act_pitch_raw(double deg);
double act_yaw_deg(int raw);
double act_pitch_deg(int raw);
