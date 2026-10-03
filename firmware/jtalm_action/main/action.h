// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
//
// Action schema v1 on the device: a strict validator for the LM output and the planner
// that turns validated calls into servo targets and face changes. No hardware access here.
//
// The angles follow src/jtalm/action/mapping.py (the canonical mapping); the raw conversion
// and the soft limits are the ones confirmed on the K151 (docs/hardware.md).
// firmware/tools/dispatch_check.py recomputes every plan in Python and compares.

#pragma once

#include <stddef.h>
#include <stdio.h>
#include <stdint.h>

#define ACT_MAX_CALLS 2
#define ACT_MAX_STEPS 24  // nod 5 and nod 5.0: 2 x (10 swings + 1 return); bow: 4 at most
#define ACT_NONE 0xFF      // act_call_t.amount when the call has a number instead

// The order of the names in jtalm.action.schema (TOOL_NAMES, DIRECTIONS, ...).
enum { ACT_LOOK, ACT_TURN, ACT_NOD, ACT_SHAKE, ACT_BOW, ACT_EXPR, ACT_LED, ACT_SET_VOLUME,
       ACT_ADJUST_VOLUME, ACT_SET_BRIGHTNESS, ACT_ADJUST_BRIGHTNESS, ACT_KIND_COUNT };
enum { DIR_LEFT, DIR_RIGHT, DIR_UP, DIR_DOWN, DIR_UP_LEFT, DIR_UP_RIGHT, DIR_DOWN_LEFT,
       DIR_DOWN_RIGHT, DIR_CENTER, DIR_COUNT };  // turn takes the first DIR_CENTER only
enum { AMT_SLIGHT, AMT_NORMAL, AMT_LARGE, AMT_COUNT };
enum { EXPR_HAPPY, EXPR_SAD, EXPR_SURPRISED, EXPR_NEUTRAL, EXPR_ANGRY, EXPR_SLEEPY, EXPR_DOUBT,
       EXPR_COUNT };
enum { COLOR_RED, COLOR_ORANGE, COLOR_YELLOW, COLOR_GREEN, COLOR_LIGHT_BLUE, COLOR_BLUE,
       COLOR_PURPLE, COLOR_PINK, COLOR_WHITE, COLOR_OFF, COLOR_COUNT };
enum { ADJ_UP, ADJ_DOWN, ADJ_COUNT };

// Soft limits of the head in degrees from the neutral pose (right / up positive). F2 widened
// them from the v0 values (yaw -30..+30, pitch -10..+15) towards the official firmware's
// recommended range, checked on the K151 with someone watching (2026-10-02, docs/hardware.md):
// yaw +-45 and pitch +85 are reached; below horizontal the head rests on the floor (about
// +2.5 deg, raw ~628), so pitch stops at 0.
// mapping.DEFAULT_LIMITS holds the same values (firmware/tools/dispatch_check.py checks it).
#define ACT_YAW_MIN_DEG (-45)
#define ACT_YAW_MAX_DEG 45
#define ACT_PITCH_MIN_DEG 0
#define ACT_PITCH_MAX_DEG 85
#define ACT_NOD_PITCH_DEG 14  // nod amplitude (8 was too small to notice, 2026-09-30)
// mapping.py: SHAKE_YAW_DEG, BOW_LIFT_DEG, BOW_HOLD_MS, ADJUST_STEP, BRIGHTNESS_MIN
#define ACT_SHAKE_YAW_DEG 15
#define ACT_BOW_LIFT_DEG 20  // a bow from below this pitch lifts the head here first
#define ACT_BOW_HOLD_MS 500
#define ACT_ADJUST_SLIGHT 10
#define ACT_ADJUST_NORMAL 20
#define ACT_ADJUST_LARGE 30
#define ACT_LEVEL_MAX 100
#define ACT_BRIGHTNESS_MIN 5  // 0 would hide the face
// Raw position of the neutral pose; 1 step = 0.3125 deg. Right (+yaw) lowers the yaw raw,
// up (+pitch) raises the pitch raw.
#define SERVO_YAW_ZERO 460
#define SERVO_PITCH_ZERO 620
// Motion profile: every move is a cosine ease (zero velocity at both ends) whose duration
// keeps the peak speed and acceleration under these limits, rounded up to the servo tick.
#define MOTION_VMAX_DPS 90.0
#define MOTION_AMAX_DPS2 360.0
// Nod and shake strokes are faster. With the cosine ease the acceleration limit decides the
// time of any stroke below 2*v^2/a degrees (here 50 deg): 14 deg takes 280 ms.
#define MOTION_NOD_VMAX_DPS 150.0
#define MOTION_NOD_AMAX_DPS2 900.0
#define MOTION_TICK_MS 20
#define MOTION_CALL_GAP_MS 200  // pause between the two calls of one request

typedef struct {
  uint8_t kind;       // ACT_*
  uint8_t dir;        // DIR_* (look, turn) or ADJ_* (adjust_*)
  uint8_t amount;     // AMT_*, or ACT_NONE when the call has a number (degrees, by)
  uint8_t expr;       // EXPR_* (set_expression)
  uint8_t color;      // COLOR_* (set_led)
  uint8_t num_float;  // the number was written as a float (2.0): Python's duplicate rule
                      // (json.dumps) tells 2 and 2.0 apart
  int16_t value;      // degrees, count, level or by; 0 when the call has none
} act_call_t;         // 8 bytes without padding: duplicates are found with memcmp

enum { STEP_MOVE, STEP_EXPR, STEP_LED, STEP_VOLUME, STEP_BRIGHTNESS, STEP_PAUSE };

typedef struct {
  uint8_t kind;     // STEP_*
  uint8_t call;     // index of the call that produced the step
  uint8_t arg;      // STEP_EXPR: EXPR_*, STEP_LED: COLOR_*, STEP_VOLUME / STEP_BRIGHTNESS:
                    // 1 when level is a change of the stored value (adjust_*)
  uint8_t clamped;  // STEP_MOVE: the target was outside the soft limits
  int16_t yaw, pitch;  // STEP_MOVE: target pose in degrees (right / up positive), clamped
  uint16_t yaw_raw, pitch_raw;
  uint16_t ms;    // STEP_MOVE: duration (0: already there); STEP_PAUSE: hold
  int16_t level;  // STEP_VOLUME / STEP_BRIGHTNESS: the level, or the change when arg is 1
} act_step_t;

typedef struct {
  int n_calls;
  act_call_t calls[ACT_MAX_CALLS];
  int n_steps;
  act_step_t steps[ACT_MAX_STEPS];
  int yaw0, pitch0, yaw1, pitch1;  // pose before and after
  uint32_t total_ms;               // moves, holds and the pause between calls
} act_plan_t;

extern const char *const act_tool_names[ACT_KIND_COUNT];
extern const char *const act_dir_names[DIR_COUNT];
extern const char *const act_amount_names[AMT_COUNT];
extern const char *const act_expr_names[EXPR_COUNT];
extern const char *const act_color_names[COLOR_COUNT];
extern const char *const act_adjust_names[ADJ_COUNT];
// RGB of each LED color, every channel 168 or less (the official firmware's safe range).
extern const uint8_t act_led_rgb[COLOR_COUNT][3];

// Parses and validates an Action JSON string (schema v1 plus the no-duplicate rule, as
// jtalm.action.validate). Returns 0 and fills calls, or -1 and sets *err.
int act_parse(const char *s, size_t n, act_call_t *calls, int *n_calls, const char **err);

// Plans validated calls from the pose (yaw, pitch) in degrees.
void act_plan(act_plan_t *p, int yaw, int pitch);

// A single move to (to_yaw, to_pitch) within the soft limits, without calls ("!pose").
void act_plan_pose(act_plan_t *p, int yaw, int pitch, int to_yaw, int to_pitch);

// Move duration in ms for a distance in degrees (0 for 0): act_move_ms with the general
// limits, act_move_ms_limits with the given peak speed and acceleration.
uint16_t act_move_ms(double deg);
uint16_t act_move_ms_limits(double deg, double vmax_dps, double amax_dps2);
uint16_t act_yaw_raw(double deg);
uint16_t act_pitch_raw(double deg);
double act_yaw_deg(int raw);
double act_pitch_deg(int raw);

// Writes "calls":[..],"from":[yaw,pitch],"steps":[..],"to":[yaw,pitch],"total_ms":N for the
// "act" record (firmware/tools/dispatch_check.py reads it).
void act_print_body(FILE *f, const act_plan_t *p);

// The stored volume or brightness after a STEP_VOLUME / STEP_BRIGHTNESS step: the step's level,
// or the current value plus its change, within 0..100 (brightness: ACT_BRIGHTNESS_MIN..100).
int act_apply_level(int current, const act_step_t *s);
