/* SPDX-License-Identifier: Apache-2.0
 * Copyright 2026 ayutaz
 *
 * WebAssembly entry points of the C runtime for the browser demo (index.html): the same
 * tokenizer, grammar and forward pass as the firmware, built with -DJTLM_ACC=float.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "jtalm.h"

#define WORK_BYTES (256 * 1024)

static jtlm_model model;
static jtlm_state state;
static jtlm_grammar grammar;
static void *arena, *work;
static char out[1024];
static char reply[2048];

/* Takes ownership of image (malloc'ed by the caller). Returns 0 on success. */
int web_init(void *image, size_t size) {
    if (jtlm_model_init(&model, image, size) != JTLM_OK) return 1;
    arena = malloc(jtlm_state_bytes(&model.cfg));
    work = malloc(WORK_BYTES);
    if (!arena || !work) return 2;
    if (jtlm_grammar_init(&grammar, &model.tok, work, WORK_BYTES) != JTLM_OK) return 3;
    return 0;
}

/* Returns {"raw": <output before the gate>, "min_prob": <confidence>, "tokens": <prompt length>}
 * or {"error": ...}. The gate is applied by the caller. */
const char *web_predict(const char *text) {
    int ids[4096];
    int n = jtlm_prompt_ids(&model, text, strlen(text), ids, work, WORK_BYTES);
    if (n < 0) {
        snprintf(reply, sizeof reply, "{\"error\":\"tokenizer error %d\"}", n);
        return reply;
    }
    jtlm_state_init(&state, &model.cfg, arena);
    jtlm_result r;
    if (jtlm_generate(&model, &state, &grammar, ids, n, &r, NULL) != JTLM_OK) {
        snprintf(reply, sizeof reply, "{\"error\":\"generation failed\"}");
        return reply;
    }
    int n_text = r.n && r.ids[r.n - 1] == model.tok.eos ? r.n - 1 : r.n;
    jtlm_decode(&model.tok, r.ids, n_text, out, sizeof out);
    /* The grammar only lets through Action JSON, which has no characters to escape. */
    snprintf(reply, sizeof reply, "{\"raw\":%s,\"min_prob\":%.9g,\"tokens\":%d}", out,
             (double)r.min_prob, n);
    return reply;
}
