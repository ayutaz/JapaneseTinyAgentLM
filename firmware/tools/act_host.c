// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
//
// Host build of the firmware's Action validator and planner (firmware/jtalm_action/main/
// action.c) for tests: one Action JSON per line on stdin, one record per line on stdout,
//   {"valid":..,"err":..,"calls":[..],"from":[..],"steps":[..],"to":[..],"total_ms":..,
//    "queued":..,"dropped":0}
// with the same fields as the device's "act" record. The pose carries over from a plan with
// steps to the next one, as on the device. Optional arguments: the start pose (yaw pitch).
//
//   cc -std=gnu11 -O1 -I firmware/jtalm_action/main -o act_host
//      firmware/tools/act_host.c firmware/jtalm_action/main/action.c -lm  (one line)

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "action.h"

int main(int argc, char **argv) {
  int yaw = argc > 2 ? atoi(argv[1]) : 0;
  int pitch = argc > 2 ? atoi(argv[2]) : 0;
  static char line[8192];
  static act_plan_t plan;
  while (fgets(line, sizeof(line), stdin)) {
    size_t n = strcspn(line, "\r\n");
    const char *err = NULL;
    int valid = act_parse(line, n, plan.calls, &plan.n_calls, &err) == 0;
    if (!valid) plan.n_calls = 0;
    act_plan(&plan, yaw, pitch);
    int queued = plan.n_steps > 0;
    printf("{\"valid\":%d,\"err\":%s%s%s,", valid, err ? "\"" : "", err ? err : "null",
           err ? "\"" : "");
    act_print_body(stdout, &plan);
    printf(",\"queued\":%d,\"dropped\":0}\n", queued);
    if (queued) {
      yaw = plan.yaw1;
      pitch = plan.pitch1;
    }
  }
  return 0;
}
