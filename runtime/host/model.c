// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
/* Model loading, the Transformer forward pass with a KV cache, and greedy decoding.
 *
 * The math follows jtalm.model.transformer step by step (same f32 rounding points; only the
 * summation order of dot products differs, see JTLM_ACC). Build with -ffp-contract=off so no
 * multiply-add is fused where PyTorch rounds twice. */
#include <float.h>
#include <math.h>
#include <string.h>

#include "jtalm.h"

#define ALIGN 32u
#define HEADER_BYTES 128u

static uint32_t rd32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static float rdf32(const uint8_t *p) {
    uint32_t u = rd32(p);
    float f;
    memcpy(&f, &u, 4);
    return f;
}

static size_t align_up(size_t n) { return (n + ALIGN - 1) / ALIGN * ALIGN; }

static float fp16_to_f32(uint16_t h) {
    uint32_t sign = (uint32_t)(h & 0x8000u) << 16, exp = (h >> 10) & 0x1f, man = h & 0x3ffu, u;
    if (exp == 0) {
        if (man == 0) {
            u = sign;
        } else { /* subnormal: normalize */
            exp = 127 - 15 + 1;
            while (!(man & 0x400u)) {
                man <<= 1;
                exp--;
            }
            u = sign | exp << 23 | (man & 0x3ffu) << 13;
        }
    } else if (exp == 31) {
        u = sign | 0x7f800000u | man << 13;
    } else {
        u = sign | (exp + 127 - 15) << 23 | man << 13;
    }
    float f;
    memcpy(&f, &u, 4);
    return f;
}

/* -- loading ----------------------------------------------------------------------------------- */

typedef struct {
    const uint8_t *base;
    size_t pos, end;
    int bad;
} cursor;

static const void *take(cursor *c, size_t bytes) {
    if (c->bad || c->pos + bytes > c->end) {
        c->bad = 1;
        return NULL;
    }
    const void *p = c->base + c->pos;
    c->pos = align_up(c->pos + bytes);
    return p;
}

static jtlm_mat take_mat(cursor *c, const jtlm_config *cfg, int rows, int cols) {
    jtlm_mat w = {0};
    size_t n = (size_t)rows * (size_t)cols;
    w.rows = rows;
    w.cols = cols;
    if (cfg->bits == 0) {
        w.f = take(c, n * 4);
    } else {
        w.q = take(c, cfg->bits == 8 ? n : n / 2);
        w.scale = take(c, n / (size_t)cfg->group * 2);
    }
    return w;
}

static int load_tokenizer(jtlm_tokenizer *t, const uint8_t *s, size_t size) {
    if (size < 64 + 2 * 257 + 2 + 2 * 256) return JTLM_ERR_FORMAT;
    t->n_pieces = (int)rd32(s);
    t->unk = (int)rd32(s + 4);
    t->bos = (int)rd32(s + 8);
    t->eos = (int)rd32(s + 12);
    t->pad = (int)rd32(s + 16);
    t->act = (int)rd32(s + 20);
    t->out = (int)rd32(s + 24);
    t->flags = rd32(s + 28);
    uint32_t off_scores = rd32(s + 32), off_types = rd32(s + 36), off_offsets = rd32(s + 40);
    uint32_t off_bytes = rd32(s + 44), off_sorted = rd32(s + 48), off_charsmap = rd32(s + 52);
    uint32_t n_bytes = rd32(s + 56), n_charsmap = rd32(s + 60);
    size_t n = (size_t)t->n_pieces;
    if (off_scores + 4 * n > size || off_types + n > size || off_offsets + 4 * (n + 1) > size ||
        off_bytes + n_bytes > size || off_sorted + 2 * n > size || off_charsmap + n_charsmap > size)
        return JTLM_ERR_FORMAT;
    t->buckets = (const uint16_t *)(s + 64);
    t->byte_ids = (const uint16_t *)(s + 64 + 2 * 257 + 2);
    t->scores = (const float *)(s + off_scores);
    t->types = s + off_types;
    t->offsets = (const uint32_t *)(s + off_offsets);
    t->bytes = s + off_bytes;
    t->sorted = (const uint16_t *)(s + off_sorted);
    if (t->offsets[n] != n_bytes) return JTLM_ERR_FORMAT;
    t->trie = NULL;
    t->trie_units = 0;
    t->norm = NULL;
    t->norm_size = 0;
    if (n_charsmap) {
        const uint8_t *cm = s + off_charsmap;
        uint32_t trie_bytes = rd32(cm);
        if (n_charsmap < 4 || trie_bytes > n_charsmap - 4 || trie_bytes % 4) return JTLM_ERR_FORMAT;
        t->trie = (const uint32_t *)(cm + 4);
        t->trie_units = trie_bytes / 4;
        t->norm = (const char *)(cm + 4 + trie_bytes);
        t->norm_size = n_charsmap - 4 - trie_bytes;
    }
    /* unigram Model: min over NORMAL scores (from FLT_MAX), max over them (from FLT_MIN). */
    t->min_score = FLT_MAX;
    t->max_score = FLT_MIN;
    for (int i = 0; i < t->n_pieces; i++) {
        if (t->types[i] != JTLM_NORMAL) continue;
        if (t->scores[i] < t->min_score) t->min_score = t->scores[i];
        if (t->scores[i] > t->max_score) t->max_score = t->scores[i];
    }
    return JTLM_OK;
}

int jtlm_model_init(jtlm_model *m, const void *image, size_t size) {
    const uint8_t *b = image;
    memset(m, 0, sizeof(*m));
    if (size < HEADER_BYTES || memcmp(b, "JTLM", 4) != 0 || rd32(b + 4) != 1) return JTLM_ERR_FORMAT;
    uint32_t probe = 1;
    if (*(const uint8_t *)&probe != 1 || ((uintptr_t)image & 3)) return JTLM_ERR_ARG;
    jtlm_config *c = &m->cfg;
    c->vocab_size = (int)rd32(b + 8);
    c->d_model = (int)rd32(b + 12);
    c->n_layers = (int)rd32(b + 16);
    c->n_heads = (int)rd32(b + 20);
    c->n_kv_heads = (int)rd32(b + 24);
    c->d_ff = (int)rd32(b + 28);
    c->max_seq_len = (int)rd32(b + 32);
    c->rope_theta = rdf32(b + 36);
    c->norm_eps = rdf32(b + 40);
    c->bits = (int)rd32(b + 44);
    c->group = (int)rd32(b + 48);
    uint32_t tok_off = rd32(b + 52), tok_len = rd32(b + 56), w_off = rd32(b + 60),
             w_len = rd32(b + 64), rope_off = rd32(b + 68), rope_len = rd32(b + 72);
    m->tokenizer_sha256 = b + 76;
    if (c->n_layers < 1 || c->n_layers > JTLM_MAX_LAYERS || c->n_heads < 1 || c->n_kv_heads < 1 ||
        c->d_model % c->n_heads || c->n_heads % c->n_kv_heads || c->max_seq_len < 1)
        return JTLM_ERR_FORMAT;
    c->head_dim = c->d_model / c->n_heads;
    if (c->head_dim % 2) return JTLM_ERR_FORMAT;
    if (c->bits != 0 && c->bits != 8 && c->bits != 4) return JTLM_ERR_FORMAT;
    if (c->bits && (c->group < 2 || c->group % 2 || c->group > JTLM_MAX_GROUP || c->d_model % c->group ||
                    c->d_ff % c->group || (c->n_heads * c->head_dim) % c->group))
        return JTLM_ERR_FORMAT;
    if ((size_t)tok_off + tok_len > size || (size_t)w_off + w_len > size ||
        (size_t)rope_off + rope_len > size ||
        rope_len != 2u * 4u * (uint32_t)c->max_seq_len * (uint32_t)(c->head_dim / 2))
        return JTLM_ERR_FORMAT;
    if (load_tokenizer(&m->tok, b + tok_off, tok_len) != JTLM_OK) return JTLM_ERR_FORMAT;
    if (m->tok.n_pieces != c->vocab_size) return JTLM_ERR_FORMAT;
    m->rope_cos = (const float *)(b + rope_off);
    m->rope_sin = m->rope_cos + (size_t)c->max_seq_len * (size_t)(c->head_dim / 2);

    cursor cur = {b, w_off, (size_t)w_off + w_len, 0};
    int d = c->d_model, hd = c->head_dim, kv = c->n_kv_heads * hd;
    m->embed = take_mat(&cur, c, c->vocab_size, d);
    for (int l = 0; l < c->n_layers; l++) {
        jtlm_layer *L = &m->layers[l];
        L->attn_norm = take(&cur, (size_t)d * 4);
        L->wq = take_mat(&cur, c, c->n_heads * hd, d);
        L->wk = take_mat(&cur, c, kv, d);
        L->wv = take_mat(&cur, c, kv, d);
        L->wo = take_mat(&cur, c, d, c->n_heads * hd);
        L->mlp_norm = take(&cur, (size_t)d * 4);
        L->w1 = take_mat(&cur, c, c->d_ff, d);
        L->w3 = take_mat(&cur, c, c->d_ff, d);
        L->w2 = take_mat(&cur, c, d, c->d_ff);
    }
    m->norm = take(&cur, (size_t)d * 4);
    return cur.bad ? JTLM_ERR_FORMAT : JTLM_OK;
}

/* -- state ------------------------------------------------------------------------------------- */

static size_t state_floats(const jtlm_config *c, size_t *kv_each) {
    size_t kv = (size_t)c->n_layers * (size_t)c->max_seq_len * (size_t)(c->n_kv_heads * c->head_dim);
    *kv_each = kv;
    size_t per_token = 3 * (size_t)c->d_model + (size_t)(c->n_heads * c->head_dim) + 2 * (size_t)c->d_ff;
    return JTLM_BATCH * per_token + (size_t)c->n_heads * (size_t)c->max_seq_len +
           (size_t)c->vocab_size + 2 * kv;
}

size_t jtlm_state_bytes(const jtlm_config *c) {
    size_t kv;
    return state_floats(c, &kv) * sizeof(float);
}

size_t jtlm_state_kv_bytes(const jtlm_config *c) {
    size_t kv;
    state_floats(c, &kv);
    return 2 * kv * sizeof(float);
}

void jtlm_state_init(jtlm_state *s, const jtlm_config *c, void *arena) {
    size_t small = jtlm_state_bytes(c) - jtlm_state_kv_bytes(c);
    jtlm_state_init_split(s, c, arena, (char *)arena + small);
}

void jtlm_state_init_split(jtlm_state *s, const jtlm_config *c, void *arena, void *kv_cache) {
    size_t kv;
    float *p = arena;
    state_floats(c, &kv);
    /* The KV cache is not cleared: position t is always written before it is read. */
    memset(arena, 0, jtlm_state_bytes(c) - jtlm_state_kv_bytes(c));
    s->x = p, p += JTLM_BATCH * c->d_model;
    s->xb = p, p += JTLM_BATCH * c->d_model;
    s->xb2 = p, p += JTLM_BATCH * c->d_model;
    s->q = p, p += JTLM_BATCH * c->n_heads * c->head_dim;
    s->hb = p, p += JTLM_BATCH * c->d_ff;
    s->hb2 = p, p += JTLM_BATCH * c->d_ff;
    s->att = p, p += (size_t)c->n_heads * (size_t)c->max_seq_len;
    s->logits = p;
    s->key_cache = kv_cache;
    s->value_cache = s->key_cache + kv;
}

/* -- forward ----------------------------------------------------------------------------------- */

/* Integer code k of a quantized matrix (int4: element 2i in the low nibble). */
static int code_at(const jtlm_mat *w, int bits, size_t k) {
    if (bits == 8) return (int8_t)w->q[k];
    int nib = (w->q[k >> 1] >> ((k & 1) * 4)) & 0xf;
    return (nib ^ 8) - 8; /* sign-extend without a branch (weights are random) */
}

/* Row r dequantized: code * f32(fp16 scale) is exact in f32, as in the Python reader. */
static void mat_row(const jtlm_mat *w, int bits, int group, int r, float *out) {
    size_t base = (size_t)r * (size_t)w->cols;
    if (bits == 0) {
        memcpy(out, w->f + base, (size_t)w->cols * sizeof(float));
        return;
    }
    for (int g0 = 0; g0 < w->cols; g0 += group) {
        float sc = fp16_to_f32(w->scale[(base + (size_t)g0) / (size_t)group]);
        for (int j = g0; j < g0 + group; j++) out[j] = (float)code_at(w, bits, base + (size_t)j) * sc;
    }
}

/* Adds a . b to four interleaved partial sums (independent chains keep the FPU busy). The sums
 * are kept in locals: acc may alias a or b, so updating acc[] directly would store and reload
 * it on every step. */
static void dot_acc(const float *a, const float *b, int n, JTLM_ACC acc[4]) {
    JTLM_ACC s0 = acc[0], s1 = acc[1], s2 = acc[2], s3 = acc[3];
    int i = 0;
    for (; i + 4 <= n; i += 4) {
        s0 += (JTLM_ACC)a[i] * (JTLM_ACC)b[i];
        s1 += (JTLM_ACC)a[i + 1] * (JTLM_ACC)b[i + 1];
        s2 += (JTLM_ACC)a[i + 2] * (JTLM_ACC)b[i + 2];
        s3 += (JTLM_ACC)a[i + 3] * (JTLM_ACC)b[i + 3];
    }
    for (; i < n; i++) s0 += (JTLM_ACC)a[i] * (JTLM_ACC)b[i];
    acc[0] = s0, acc[1] = s1, acc[2] = s2, acc[3] = s3;
}

static float dot(const float *a, const float *b, int n) {
    JTLM_ACC acc[4] = {0, 0, 0, 0};
    dot_acc(a, b, n, acc);
    return (float)((acc[0] + acc[1]) + (acc[2] + acc[3]));
}

/* Row r of a quantized W times x. Each weight is dequantized (code * scale, exact in f32) right
 * before its multiply, into the same four partial sums as dot_acc, so the result is identical to
 * dequantizing the row first; this saves storing and reloading it (group % 4 == 0). */
static float qrow_dot(const jtlm_mat *w, int bits, int group, int r, const float *x) {
    size_t base = (size_t)r * (size_t)w->cols;
    JTLM_ACC s0 = 0, s1 = 0, s2 = 0, s3 = 0;
    for (int g0 = 0; g0 < w->cols; g0 += group) {
        size_t k = base + (size_t)g0;
        float sc = fp16_to_f32(w->scale[k / (size_t)group]);
        const float *xg = x + g0;
        if (bits == 8) {
            const int8_t *q = (const int8_t *)w->q + k;
            for (int j = 0; j < group; j += 4) {
                s0 += (JTLM_ACC)((float)q[j] * sc) * (JTLM_ACC)xg[j];
                s1 += (JTLM_ACC)((float)q[j + 1] * sc) * (JTLM_ACC)xg[j + 1];
                s2 += (JTLM_ACC)((float)q[j + 2] * sc) * (JTLM_ACC)xg[j + 2];
                s3 += (JTLM_ACC)((float)q[j + 3] * sc) * (JTLM_ACC)xg[j + 3];
            }
        } else {
            const uint8_t *q = w->q + k / 2;
            for (int j = 0; j < group; j += 4) {
                int b0 = q[j >> 1], b1 = q[(j >> 1) + 1];
                s0 += (JTLM_ACC)((float)(((b0 & 0xf) ^ 8) - 8) * sc) * (JTLM_ACC)xg[j];
                s1 += (JTLM_ACC)((float)(((b0 >> 4) ^ 8) - 8) * sc) * (JTLM_ACC)xg[j + 1];
                s2 += (JTLM_ACC)((float)(((b1 & 0xf) ^ 8) - 8) * sc) * (JTLM_ACC)xg[j + 2];
                s3 += (JTLM_ACC)((float)(((b1 >> 4) ^ 8) - 8) * sc) * (JTLM_ACC)xg[j + 3];
            }
        }
    }
    return (float)((s0 + s1) + (s2 + s3));
}

/* -- matrix products ------------------------------------------------------------------------- */

static jtlm_parallel_fn g_parallel;

void jtlm_set_parallel(jtlm_parallel_fn run) { g_parallel = run; }

/* OUT[t] = W X[t] for t < n (W is rows x cols; X[t] at x + t * xs, OUT[t] at out + t * os). */
typedef struct {
    const jtlm_config *c;
    const jtlm_mat *w;
    const float *x;
    float *out;
    int n, xs, os;
} matmul_job;

/* Rows [r0, r1) of a matmul_job. Every (row, vector) dot product is computed exactly as for a
 * single vector, so the result does not depend on n or on how the rows are split. With several
 * vectors, each weight is read (and dequantized) once for all of them. */
static void matmul_rows(void *ctx, int r0, int r1) {
    const matmul_job *j = ctx;
    const jtlm_mat *w = j->w;
    int bits = j->c->bits, group = j->c->group, cols = w->cols;
    if (bits == 0) {
        for (int r = r0; r < r1; r++)
            for (int t = 0; t < j->n; t++)
                j->out[(size_t)t * (size_t)j->os + (size_t)r] =
                    dot(w->f + (size_t)r * (size_t)cols, j->x + (size_t)t * (size_t)j->xs, cols);
        return;
    }
    if (j->n == 1 && group % 4 == 0) {
        for (int r = r0; r < r1; r++) j->out[r] = qrow_dot(w, bits, group, r, j->x);
        return;
    }
    float wg[JTLM_MAX_GROUP];
    JTLM_ACC acc[JTLM_BATCH][4];
    for (int r = r0; r < r1; r++) {
        size_t base = (size_t)r * (size_t)cols;
        memset(acc, 0, sizeof(acc));
        for (int g0 = 0; g0 < cols; g0 += group) {
            size_t k = base + (size_t)g0;
            float sc = fp16_to_f32(w->scale[k / (size_t)group]);
            if (bits == 8) {
                const int8_t *q = (const int8_t *)w->q + k;
                for (int i = 0; i < group; i++) wg[i] = (float)q[i] * sc;
            } else {
                const uint8_t *q = w->q + k / 2; /* k is even: group is even */
                for (int i = 0; i < group; i += 2) {
                    int b = q[i >> 1];
                    wg[i] = (float)(((b & 0xf) ^ 8) - 8) * sc;
                    wg[i + 1] = (float)(((b >> 4) ^ 8) - 8) * sc;
                }
            }
            for (int t = 0; t < j->n; t++)
                dot_acc(wg, j->x + (size_t)t * (size_t)j->xs + (size_t)g0, group, acc[t]);
        }
        for (int t = 0; t < j->n; t++)
            j->out[(size_t)t * (size_t)j->os + (size_t)r] =
                (float)((acc[t][0] + acc[t][1]) + (acc[t][2] + acc[t][3]));
    }
}

static void matmul(const jtlm_config *c, const jtlm_mat *w, const float *x, int xs, float *out,
                   int os, int n) {
    matmul_job j = {c, w, x, out, n, xs, os};
    if (g_parallel && w->rows > 1) g_parallel(matmul_rows, &j, w->rows);
    else matmul_rows(&j, 0, w->rows);
}

/* RMSNorm: (x * rsqrt(mean(x^2) + eps)) * weight, rounded as in PyTorch. */
static void rmsnorm(float *out, const float *x, const float *w, int n, float eps) {
    JTLM_ACC ss = 0;
    for (int i = 0; i < n; i++) ss += (JTLM_ACC)x[i] * (JTLM_ACC)x[i];
    float mean = (float)(ss / (JTLM_ACC)n);
    float r = 1.0f / sqrtf(mean + eps);
    for (int i = 0; i < n; i++) {
        float y = x[i] * r;
        out[i] = y * w[i];
    }
}

/* Rotate pairs (x[2i], x[2i+1]) of one head. */
static void rope(float *x, const float *cos_row, const float *sin_row, int hd) {
    for (int i = 0; i < hd / 2; i++) {
        float x1 = x[2 * i], x2 = x[2 * i + 1], c = cos_row[i], s = sin_row[i];
        float a = x1 * c, b = x2 * s, e = x1 * s, f = x2 * c;
        x[2 * i] = a - b;
        x[2 * i + 1] = e + f;
    }
}

static void softmax(float *x, int n) {
    float mx = x[0];
    for (int i = 1; i < n; i++)
        if (x[i] > mx) mx = x[i];
    JTLM_ACC sum = 0;
    for (int i = 0; i < n; i++) {
        x[i] = expf(x[i] - mx);
        sum += x[i];
    }
    float inv = 1.0f / (float)sum; /* PyTorch multiplies by the reciprocal */
    for (int i = 0; i < n; i++) x[i] *= inv;
}

/* Runs n tokens (n <= JTLM_BATCH) at positions pos0 .. pos0 + n - 1, reading each weight once
 * for all of them. Token t is processed exactly as if it were run alone, so the result does not
 * depend on the batching. The logits (of the last token) are computed only when want_logits. */
static void forward_batch(const jtlm_model *m, jtlm_state *s, const int *tokens, int n, int pos0,
                          int want_logits) {
    const jtlm_config *c = &m->cfg;
    int d = c->d_model, hd = c->head_dim, kv_dim = c->n_kv_heads * hd, qd = c->n_heads * hd;
    int rep = c->n_heads / c->n_kv_heads, half = hd / 2, ff = c->d_ff;
    float scale = (float)(1.0 / sqrt((double)hd));

    for (int t = 0; t < n; t++) mat_row(&m->embed, c->bits, c->group, tokens[t], s->x + t * d);
    for (int l = 0; l < c->n_layers; l++) {
        const jtlm_layer *L = &m->layers[l];
        size_t loff = (size_t)l * (size_t)c->max_seq_len * (size_t)kv_dim;
        float *kc = s->key_cache + loff, *vc = s->value_cache + loff;
        float *k0 = kc + (size_t)pos0 * (size_t)kv_dim, *v0 = vc + (size_t)pos0 * (size_t)kv_dim;

        for (int t = 0; t < n; t++) rmsnorm(s->xb + t * d, s->x + t * d, L->attn_norm, d, c->norm_eps);
        matmul(c, &L->wq, s->xb, d, s->q, qd, n);
        matmul(c, &L->wk, s->xb, d, k0, kv_dim, n);
        matmul(c, &L->wv, s->xb, d, v0, kv_dim, n);
        for (int t = 0; t < n; t++) {
            int pos = pos0 + t;
            const float *cr = m->rope_cos + (size_t)pos * (size_t)half;
            const float *sr = m->rope_sin + (size_t)pos * (size_t)half;
            float *q = s->q + t * qd, *k = k0 + (size_t)t * (size_t)kv_dim;
            for (int h = 0; h < c->n_heads; h++) rope(q + h * hd, cr, sr, hd);
            for (int h = 0; h < c->n_kv_heads; h++) rope(k + h * hd, cr, sr, hd);
        }

        for (int t = 0; t < n; t++) { /* causal: position pos sees 0 .. pos, all written above */
            int pos = pos0 + t;
            for (int h = 0; h < c->n_heads; h++) {
                const float *qh = s->q + t * qd + h * hd;
                int kh = h / rep; /* repeat_interleave */
                float *att = s->att + (size_t)h * (size_t)c->max_seq_len;
                for (int u = 0; u <= pos; u++)
                    att[u] = dot(qh, kc + (size_t)u * (size_t)kv_dim + (size_t)kh * (size_t)hd, hd) * scale;
                softmax(att, pos + 1);
                float *o = s->xb2 + t * d + h * hd;
                for (int i = 0; i < hd; i++) {
                    JTLM_ACC acc = 0;
                    for (int u = 0; u <= pos; u++)
                        acc += (JTLM_ACC)att[u] * (JTLM_ACC)vc[(size_t)u * (size_t)kv_dim + (size_t)kh * (size_t)hd + (size_t)i];
                    o[i] = (float)acc;
                }
            }
        }
        matmul(c, &L->wo, s->xb2, d, s->xb, d, n);
        for (int i = 0; i < n * d; i++) s->x[i] += s->xb[i];

        for (int t = 0; t < n; t++) rmsnorm(s->xb + t * d, s->x + t * d, L->mlp_norm, d, c->norm_eps);
        matmul(c, &L->w1, s->xb, d, s->hb, ff, n);
        matmul(c, &L->w3, s->xb, d, s->hb2, ff, n);
        for (int i = 0; i < n * ff; i++) {
            float g = s->hb[i];
            float silu = g / (1.0f + expf(-g));
            s->hb[i] = silu * s->hb2[i];
        }
        matmul(c, &L->w2, s->hb, ff, s->xb, d, n);
        for (int i = 0; i < n * d; i++) s->x[i] += s->xb[i];
    }
    if (!want_logits) return;
    rmsnorm(s->xb, s->x + (n - 1) * d, m->norm, d, c->norm_eps);
    matmul(c, &m->embed, s->xb, d, s->logits, c->vocab_size, 1);
}

float *jtlm_forward(const jtlm_model *m, jtlm_state *s, int token, int pos) {
    forward_batch(m, s, &token, 1, pos, 1);
    return s->logits;
}

/* -- decoding ---------------------------------------------------------------------------------- */

int jtlm_prompt_ids(const jtlm_model *m, const char *text, size_t len, int *ids, void *work,
                    size_t work_bytes) {
    int max_body = m->cfg.max_seq_len - JTLM_MAX_NEW_TOKENS - 3;
    if (max_body < 0) return JTLM_ERR_ARG;
    int n = jtlm_encode(&m->tok, text, len, ids + 2, max_body, work, work_bytes);
    if (n < 0) return n;
    if (n > max_body) n = max_body;
    ids[0] = m->tok.bos;
    ids[1] = m->tok.act;
    ids[n + 2] = m->tok.out;
    return n + 3;
}

float *jtlm_prefill(const jtlm_model *m, jtlm_state *s, const int *prompt, int n_prompt) {
    if (n_prompt < 1) return NULL;
    for (int i = 0; i < n_prompt; i += JTLM_BATCH) {
        int n = n_prompt - i < JTLM_BATCH ? n_prompt - i : JTLM_BATCH;
        forward_batch(m, s, prompt + i, n, i, i + n == n_prompt);
    }
    return s->logits;
}

int jtlm_generate(const jtlm_model *m, jtlm_state *s, const jtlm_grammar *grammar,
                  const int *prompt, int n_prompt, jtlm_result *r, float *first_logits) {
    if (n_prompt < 1 || n_prompt >= m->cfg.max_seq_len) {
        r->n = 0;
        r->min_prob = 1.0f;
        return JTLM_ERR_ARG;
    }
    float *logits = jtlm_prefill(m, s, prompt, n_prompt);
    return jtlm_generate_from(m, s, grammar, logits, n_prompt, r, first_logits);
}

int jtlm_generate_from(const jtlm_model *m, jtlm_state *s, const jtlm_grammar *grammar,
                       float *logits, int n_prompt, jtlm_result *r, float *first_logits) {
    const jtlm_config *c = &m->cfg;
    int steps = c->max_seq_len - n_prompt;
    if (steps > JTLM_MAX_NEW_TOKENS) steps = JTLM_MAX_NEW_TOKENS;
    r->n = 0;
    r->min_prob = 1.0f;
    if (n_prompt < 1 || steps <= 0 || !logits) return JTLM_ERR_ARG;
    jtlm_grammar_state st;
    jtlm_grammar_reset(&st);
    for (int step = 0; step < steps; step++) {
        if (step == 0 && first_logits) memcpy(first_logits, logits, (size_t)c->vocab_size * sizeof(float));
        softmax(logits, c->vocab_size); /* now probabilities */
        int next = 0;
        if (grammar) {
            int allowed[8], k = jtlm_grammar_allowed(grammar, &st, allowed);
            next = allowed[0];
            for (int i = 1; i < k; i++) /* highest probability, lowest id on ties */
                if (logits[allowed[i]] > logits[next] ||
                    (logits[allowed[i]] == logits[next] && allowed[i] < next))
                    next = allowed[i];
        } else {
            for (int i = 1; i < c->vocab_size; i++)
                if (logits[i] > logits[next]) next = i;
        }
        float p = logits[next];
        if (p < r->min_prob) r->min_prob = p;
        r->ids[r->n++] = next;
        if (next == m->tok.eos) break;
        if (grammar) jtlm_grammar_advance(grammar, &st, next);
        if (step + 1 < steps) logits = jtlm_forward(m, s, next, n_prompt + step);
    }
    return JTLM_OK;
}
