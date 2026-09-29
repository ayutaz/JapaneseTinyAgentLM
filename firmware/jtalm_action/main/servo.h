// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 JapaneseTinyAgentLM contributors
//
// Action dispatcher: runs planned steps (face changes and head moves) in order in its own
// task, drives the two SCS0009 servos when servo output is on, and guards them.
//
// Servo output is OFF after every boot ("dry-run"): plans are computed, timed and reported
// exactly as they would run, and the face changes, but the servo UART is not even opened and
// VM_EN stays low. Only "!servo on" turns output on; "!servo off" / "!stop", a touch on the
// screen, a servo error or the watchdog turn it off again (torque off, then VM_EN low).

#pragma once

#include <stdint.h>

#include "action.h"

// Output lock for "JTALM" lines printed from more than one task (out_init first).
void out_init(void);
void out_lock(void);
void out_unlock(void);

// Starts the dispatcher and guard tasks.
int servo_start(void);

// Queues a plan (seq numbers the request). Returns 0, or -1 if the queue is full.
int servo_submit(const act_plan_t *plan, uint32_t seq);

// "!servo on": power, ping, torque on at the present pose (queued behind earlier plans).
int servo_request_on(void);

// "!wdtest": a dry-run plan that overruns its deadline, to exercise the watchdog.
int servo_request_wdtest(void);

// Immediate: abort the running plan, drop queued ones; torque off. power_off also drops
// VM_EN and returns to dry-run (emergency stop). src names the trigger in the log.
void servo_stop(const char *src, int power_off);

// 1 when servo output is on.
int servo_output_on(void);

// Prints a "servo" status line.
void servo_status(void);
