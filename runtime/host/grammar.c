// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
/* Action schema v0 grammar: a port of jtalm.model.grammar.ActionGrammar.
 *
 *     [] </s>  |  [ CALL ] </s>  |  [ CALL , CALL ] </s>   (the second call differs from the first)
 *     CALL = LOOK direction ","amount":" amount "}}  (amount is normal when direction is center)
 *          | EXPRESSION expression "}}  |  NOD count }}   (count is 1..3)
 *
 * The Python version re-parses the generated tokens every step; this one keeps the same parser
 * state incrementally. */
#include <string.h>

#include "jtalm.h"

enum { START, CALL, DIRECTION, AMOUNT_KEY, AMOUNT, EXPRESSION, COUNT, CLOSE, AFTER_CALL, EMPTY,
       END, DONE };

/* The id of a piece that must encode to exactly one token (ActionGrammar.tid). */
static int tid(const jtlm_tokenizer *t, const char *piece, void *work, size_t work_bytes) {
    int ids[2];
    int n = jtlm_encode(t, piece, strlen(piece), ids, 2, work, work_bytes);
    return n == 1 ? ids[0] : -1;
}

int jtlm_grammar_init(jtlm_grammar *g, const jtlm_tokenizer *t, void *work, size_t work_bytes) {
    static const char *dirs[5] = {"left", "right", "up", "down", "center"};
    static const char *amounts[3] = {"slight", "normal", "large"};
    static const char *exprs[4] = {"happy", "sad", "surprised", "neutral"};
    static const char *counts[3] = {"1", "2", "3"};
    int ok = 1;
#define TID(dst, piece) ok &= ((dst) = tid(t, (piece), work, work_bytes)) >= 0
    g->eos = t->eos;
    TID(g->empty, "[]");
    TID(g->open, "[");
    TID(g->close, "]");
    TID(g->comma, ",");
    TID(g->look, "{\"name\":\"look\",\"arguments\":{\"direction\":\"");
    TID(g->amount_key, "\",\"amount\":\"");
    TID(g->expr, "{\"name\":\"set_expression\",\"arguments\":{\"expression\":\"");
    TID(g->nod, "{\"name\":\"nod\",\"arguments\":{\"count\":");
    TID(g->close_str, "\"}}");
    TID(g->close_obj, "}}");
    for (int i = 0; i < 5; i++) TID(g->dirs[i], dirs[i]);
    for (int i = 0; i < 3; i++) TID(g->amounts[i], amounts[i]);
    for (int i = 0; i < 4; i++) TID(g->exprs[i], exprs[i]);
    for (int i = 0; i < 3; i++) TID(g->counts[i], counts[i]);
#undef TID
    return ok ? JTLM_OK : JTLM_ERR_FORMAT;
}

void jtlm_grammar_reset(jtlm_grammar_state *st) { memset(st, 0, sizeof(*st)); }

void jtlm_grammar_advance(const jtlm_grammar *g, jtlm_grammar_state *st, int token) {
    switch (st->step) {
    case START:
        st->step = token == g->empty ? EMPTY : CALL;
        break;
    case CALL:
        st->n_cur = 0;
        st->cur[st->n_cur++] = token;
        st->step = token == g->look ? DIRECTION : token == g->expr ? EXPRESSION : COUNT;
        break;
    case DIRECTION:
        st->cur[st->n_cur++] = token;
        st->step = AMOUNT_KEY;
        break;
    case AMOUNT_KEY:
        st->step = AMOUNT;
        break;
    case AMOUNT:
    case EXPRESSION:
    case COUNT:
        st->cur[st->n_cur++] = token;
        st->step = CLOSE;
        break;
    case CLOSE:
        if (st->n_calls < 2) {
            memset(st->calls[st->n_calls], -1, sizeof(st->calls[0]));
            memcpy(st->calls[st->n_calls], st->cur, (size_t)st->n_cur * sizeof(int));
            st->n_calls++;
        }
        st->n_cur = 0;
        st->step = AFTER_CALL;
        break;
    case AFTER_CALL:
        st->step = token == g->comma ? CALL : END;
        break;
    default: /* EMPTY, END, DONE */
        st->step = DONE;
        break;
    }
}

/* Options minus the last value of the first call when the call being built matches it so far. */
static int not_duplicate(const jtlm_grammar_state *st, const int *options, int n, int *ids) {
    int drop = -1;
    if (st->n_calls >= 1) {
        const int *first = st->calls[0];
        int first_len = first[2] >= 0 ? 3 : first[1] >= 0 ? 2 : 1;
        if (first_len - 1 == st->n_cur && memcmp(first, st->cur, (size_t)st->n_cur * sizeof(int)) == 0)
            drop = first[first_len - 1];
    }
    int k = 0;
    for (int i = 0; i < n; i++)
        if (options[i] != drop) ids[k++] = options[i];
    return k;
}

int jtlm_grammar_allowed(const jtlm_grammar *g, const jtlm_grammar_state *st, int *ids) {
    switch (st->step) {
    case START:
        ids[0] = g->empty;
        ids[1] = g->open;
        return 2;
    case CALL:
        ids[0] = g->look;
        ids[1] = g->expr;
        ids[2] = g->nod;
        return 3;
    case DIRECTION: {
        int k = 0;
        const int *first = st->calls[0];
        int skip_center = st->n_calls >= 1 && first[0] == g->look && first[1] == g->dirs[4] &&
                          first[2] == g->amounts[1];
        for (int i = 0; i < 5; i++)
            if (!(skip_center && i == 4)) ids[k++] = g->dirs[i];
        return k;
    }
    case AMOUNT_KEY:
        ids[0] = g->amount_key;
        return 1;
    case AMOUNT:
        if (st->cur[1] == g->dirs[4]) return not_duplicate(st, &g->amounts[1], 1, ids);
        return not_duplicate(st, g->amounts, 3, ids);
    case EXPRESSION:
        return not_duplicate(st, g->exprs, 4, ids);
    case COUNT:
        return not_duplicate(st, g->counts, 3, ids);
    case CLOSE:
        ids[0] = st->cur[0] == g->nod ? g->close_obj : g->close_str;
        return 1;
    case AFTER_CALL:
        if (st->n_calls == 1) {
            ids[0] = g->comma;
            ids[1] = g->close;
            return 2;
        }
        ids[0] = g->close;
        return 1;
    default:
        ids[0] = g->eos;
        return 1;
    }
}
