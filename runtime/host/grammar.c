// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
/* Action schema v1 grammar: a port of jtalm.model.grammar.ActionGrammar.
 *
 *     [] </s>  |  [ CALL ] </s>  |  [ CALL , CALL ] </s>   (the second call differs from the first)
 *     CALL = HEAD first [ KEY second ] CLOSE  |  BOW
 *
 * Enum values are one token; numbers are one token per digit, without a leading zero and inside
 * the argument's range. The Python version walks a trie of every call; this one applies the same
 * rules directly. tests/test_export.py::test_c_grammar_matches_python compares the two on every
 * single call, on duplicate-prone pairs, and on random walks. */
#include <string.h>

#include "jtalm.h"

enum { START, CALL, AFTER_CALL, EMPTY, END, DONE };
enum { P_HEAD, P_FIRST, P_KEY, P_SECOND, P_CLOSE_STR, P_NUM };

static const char *const DIRS[9] = {"left", "right", "up", "down", "up_left", "up_right",
                                    "down_left", "down_right", "center"};
static const char *const AMOUNTS[3] = {"slight", "normal", "large"};
static const char *const EXPRS[7] = {"happy", "sad", "surprised", "neutral", "angry", "sleepy",
                                     "doubt"};
static const char *const COLORS[10] = {"red", "orange", "yellow", "green", "light_blue", "blue",
                                       "purple", "pink", "white", "off"};
static const char *const UPDOWN[2] = {"up", "down"};

/* Same order and values as jtalm.action.schema.TOOLS. */
static const struct {
    const char *head;
    const char *const *values;
    int n_values, lo, hi, second;
} TOOLS[JTLM_N_TOOLS] = {
    {"{\"name\":\"look\",\"arguments\":{\"direction\":\"", DIRS, 9, 0, 0, 1},
    {"{\"name\":\"turn\",\"arguments\":{\"direction\":\"", DIRS, 8, 0, 0, 1},
    {"{\"name\":\"nod\",\"arguments\":{\"count\":", NULL, 0, 1, 5, 0},
    {"{\"name\":\"shake\",\"arguments\":{\"count\":", NULL, 0, 1, 5, 0},
    {"{\"name\":\"bow\",\"arguments\":{}}", NULL, 0, 1, 0, 0},
    {"{\"name\":\"set_expression\",\"arguments\":{\"expression\":\"", EXPRS, 7, 0, 0, 0},
    {"{\"name\":\"set_led\",\"arguments\":{\"color\":\"", COLORS, 10, 0, 0, 0},
    {"{\"name\":\"set_volume\",\"arguments\":{\"level\":", NULL, 0, 0, 100, 0},
    {"{\"name\":\"adjust_volume\",\"arguments\":{\"direction\":\"", UPDOWN, 2, 0, 0, 2},
    {"{\"name\":\"set_brightness\",\"arguments\":{\"level\":", NULL, 0, 0, 100, 0},
    {"{\"name\":\"adjust_brightness\",\"arguments\":{\"direction\":\"", UPDOWN, 2, 0, 0, 2},
};

/* The id of a piece that must encode to exactly one token (ActionGrammar.tid). */
static int tid(const jtlm_tokenizer *t, const char *piece, void *work, size_t work_bytes) {
    int ids[2];
    int n = jtlm_encode(t, piece, strlen(piece), ids, 2, work, work_bytes);
    return n == 1 ? ids[0] : -1;
}

int jtlm_grammar_init(jtlm_grammar *g, const jtlm_tokenizer *t, void *work, size_t work_bytes) {
    static const char *const digits[10] = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"};
    int ok = 1;
#define TID(dst, piece) ok &= ((dst) = tid(t, (piece), work, work_bytes)) >= 0
    g->eos = t->eos;
    TID(g->empty, "[]");
    TID(g->open, "[");
    TID(g->close, "]");
    TID(g->comma, ",");
    TID(g->close_str, "\"}}");
    TID(g->close_num, "}}");
    TID(g->key_amount, "\",\"amount\":\"");
    TID(g->key_degrees, "\",\"degrees\":");
    TID(g->key_by, "\",\"by\":");
    for (int i = 0; i < 3; i++) TID(g->amounts[i], AMOUNTS[i]);
    for (int i = 0; i < 10; i++) TID(g->digits[i], digits[i]);
    TID(g->center, "center");
    TID(g->normal, "normal");
    for (int i = 0; i < JTLM_N_TOOLS; i++) {
        jtlm_tool *tool = &g->tools[i];
        TID(tool->head, TOOLS[i].head);
        tool->n_values = TOOLS[i].n_values;
        for (int k = 0; k < tool->n_values; k++) TID(tool->values[k], TOOLS[i].values[k]);
        tool->lo = TOOLS[i].lo;
        tool->hi = TOOLS[i].hi;
        tool->second = TOOLS[i].second;
    }
    g->look = g->tools[0].head;
#undef TID
    return ok ? JTLM_OK : JTLM_ERR_FORMAT;
}

void jtlm_grammar_reset(jtlm_grammar_state *st) { memset(st, 0, sizeof(*st)); }

static int digit_of(const jtlm_grammar *g, int token) {
    for (int d = 0; d < 10; d++)
        if (g->digits[d] == token) return d;
    return -1;
}

static void complete_call(jtlm_grammar_state *st) {
    if (st->n_calls < 2) {
        memcpy(st->calls[st->n_calls], st->cur, (size_t)st->n_cur * sizeof(int));
        st->call_len[st->n_calls] = st->n_cur;
        st->n_calls++;
    }
    st->n_cur = 0;
    st->phase = P_HEAD;
    st->step = AFTER_CALL;
}

static void start_number(jtlm_grammar_state *st, int lo, int hi) {
    st->phase = P_NUM;
    st->lo = lo;
    st->hi = hi;
    st->value = 0;
    st->n_digits = 0;
}

void jtlm_grammar_advance(const jtlm_grammar *g, jtlm_grammar_state *st, int token) {
    switch (st->step) {
    case START:
        st->step = token == g->empty ? EMPTY : CALL;
        st->phase = P_HEAD;
        break;
    case CALL: {
        if (st->n_cur < JTLM_CALL_MAX) st->cur[st->n_cur++] = token;
        const jtlm_tool *tool = &g->tools[st->tool];
        switch (st->phase) {
        case P_HEAD:
            for (int i = 0; i < JTLM_N_TOOLS; i++)
                if (g->tools[i].head == token) st->tool = i;
            tool = &g->tools[st->tool];
            if (tool->n_values) st->phase = P_FIRST;
            else if (tool->lo > tool->hi) complete_call(st); /* bow */
            else start_number(st, tool->lo, tool->hi);
            break;
        case P_FIRST:
            st->phase = tool->second ? P_KEY : P_CLOSE_STR;
            break;
        case P_KEY:
            if (token == g->key_amount) st->phase = P_SECOND;
            else start_number(st, 1, token == g->key_degrees ? 180 : 100);
            break;
        case P_SECOND:
            st->phase = P_CLOSE_STR;
            break;
        case P_CLOSE_STR:
            complete_call(st);
            break;
        default: /* P_NUM */
            if (token == g->close_num) complete_call(st);
            else {
                st->value = st->value * 10 + digit_of(g, token);
                st->n_digits++;
            }
            break;
        }
        break;
    }
    case AFTER_CALL:
        st->step = token == g->comma ? CALL : END;
        st->phase = P_HEAD;
        break;
    default: /* EMPTY, END, DONE */
        st->step = DONE;
        break;
    }
}

static int pow10i(int n) {
    int p = 1;
    while (n-- > 0) p *= 10;
    return p;
}

static int n_digits_of(int v) {
    int n = 1;
    while (v >= 10) {
        v /= 10;
        n++;
    }
    return n;
}

/* 1 when v, written without leading zeros, starts with the len digits of p. */
static int has_prefix(int v, int p, int len) {
    int n = n_digits_of(v);
    return n >= len && v / pow10i(n - len) == p;
}

/* The digits (and the closer) that keep the number inside [lo, hi] with a completion other than
 * dup (dup < 0: no duplicate to avoid). */
static int number_options(const jtlm_grammar *g, const jtlm_grammar_state *st, int dup, int *ids) {
    int k = 0;
    for (int d = 0; d <= 9; d++) {
        int p = st->value * 10 + d;
        for (int v = st->lo; v <= st->hi; v++)
            if (v != dup && has_prefix(v, p, st->n_digits + 1)) {
                ids[k++] = g->digits[d];
                break;
            }
    }
    if (st->n_digits > 0 && st->value >= st->lo && st->value <= st->hi && st->value != dup)
        ids[k++] = g->close_num;
    return k;
}

/* The first call's number when the call being built equals it up to here, else -1. */
static int duplicate_number(const jtlm_grammar *g, const jtlm_grammar_state *st, int same) {
    if (!same) return -1;
    const int *first = st->calls[0];
    int start = st->n_cur - st->n_digits, v = 0;
    for (int i = start; i < st->call_len[0] && first[i] != g->close_num; i++)
        v = v * 10 + digit_of(g, first[i]);
    return v;
}

static void sort_ids(int *ids, int k) {
    for (int i = 1; i < k; i++)
        for (int j = i; j > 0 && ids[j - 1] > ids[j]; j--) {
            int tmp = ids[j];
            ids[j] = ids[j - 1];
            ids[j - 1] = tmp;
        }
}

static int call_options(const jtlm_grammar *g, const jtlm_grammar_state *st, int *ids) {
    const int *first = st->calls[0];
    /* same: the call being built equals the first call so far (the first call is longer) */
    int same = st->n_calls >= 1 && st->call_len[0] > st->n_cur &&
               memcmp(first, st->cur, (size_t)st->n_cur * sizeof(int)) == 0;
    const jtlm_tool *tool = &g->tools[st->tool];
    int k = 0;
    switch (st->phase) {
    case P_HEAD:
        for (int i = 0; i < JTLM_N_TOOLS; i++) {
            const jtlm_tool *t = &g->tools[i];
            int whole = t->n_values == 0 && t->lo > t->hi; /* bow is one piece */
            if (whole && same && st->call_len[0] == 1 && first[0] == t->head) continue;
            ids[k++] = t->head;
        }
        return k;
    case P_FIRST:
        for (int i = 0; i < tool->n_values; i++) {
            int v = tool->values[i];
            int only_one = !tool->second || (tool->head == g->look && v == g->center);
            if (only_one && same && first[1] == v) continue;
            ids[k++] = v;
        }
        return k;
    case P_KEY:
        ids[k++] = g->key_amount;
        if (!(tool->head == g->look && st->cur[1] == g->center))
            ids[k++] = tool->second == 1 ? g->key_degrees : g->key_by;
        return k;
    case P_SECOND:
        if (tool->head == g->look && st->cur[1] == g->center) {
            ids[k++] = g->normal; /* the first call cannot be look center: P_FIRST dropped it */
            return k;
        }
        for (int i = 0; i < 3; i++)
            if (!(same && first[st->n_cur] == g->amounts[i])) ids[k++] = g->amounts[i];
        return k;
    case P_CLOSE_STR:
        ids[k++] = g->close_str;
        return k;
    default: /* P_NUM */
        return number_options(g, st, duplicate_number(g, st, same), ids);
    }
}

int jtlm_grammar_allowed(const jtlm_grammar *g, const jtlm_grammar_state *st, int *ids) {
    int k;
    switch (st->step) {
    case START:
        ids[0] = g->empty;
        ids[1] = g->open;
        k = 2;
        break;
    case CALL:
        k = call_options(g, st, ids);
        break;
    case AFTER_CALL:
        if (st->n_calls == 1) {
            ids[0] = g->comma;
            ids[1] = g->close;
            k = 2;
        } else {
            ids[0] = g->close;
            k = 1;
        }
        break;
    default:
        ids[0] = g->eos;
        k = 1;
        break;
    }
    sort_ids(ids, k);
    return k;
}
