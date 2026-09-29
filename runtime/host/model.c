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
    return 3 * (size_t)c->d_model + (size_t)(c->n_heads * c->head_dim) + 2 * (size_t)c->d_ff +
           (size_t)c->n_heads * (size_t)c->max_seq_len + (size_t)c->vocab_size + 2 * kv;
}

size_t jtlm_state_bytes(const jtlm_config *c) {
    size_t kv;
    return state_floats(c, &kv) * sizeof(float);
}

void jtlm_state_init(jtlm_state *s, const jtlm_config *c, void *arena) {
    size_t kv;
    float *p = arena;
    memset(arena, 0, jtlm_state_bytes(c));
    state_floats(c, &kv);
    s->x = p, p += c->d_model;
    s->xb = p, p += c->d_model;
    s->xb2 = p, p += c->d_model;
    s->q = p, p += c->n_heads * c->head_dim;
    s->hb = p, p += c->d_ff;
    s->hb2 = p, p += c->d_ff;
    s->att = p, p += (size_t)c->n_heads * (size_t)c->max_seq_len;
    s->logits = p, p += c->vocab_size;
    s->key_cache = p, p += kv;
    s->value_cache = p;
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

/* Adds a . b to four interleaved partial sums (independent chains keep the FPU busy). */
static void dot_acc(const float *a, const float *b, int n, JTLM_ACC acc[4]) {
    int i = 0;
    for (; i + 4 <= n; i += 4) {
        acc[0] += (JTLM_ACC)a[i] * (JTLM_ACC)b[i];
        acc[1] += (JTLM_ACC)a[i + 1] * (JTLM_ACC)b[i + 1];
        acc[2] += (JTLM_ACC)a[i + 2] * (JTLM_ACC)b[i + 2];
        acc[3] += (JTLM_ACC)a[i + 3] * (JTLM_ACC)b[i + 3];
    }
    for (; i < n; i++) acc[0] += (JTLM_ACC)a[i] * (JTLM_ACC)b[i];
}

static float dot(const float *a, const float *b, int n) {
    JTLM_ACC acc[4] = {0, 0, 0, 0};
    dot_acc(a, b, n, acc);
    return (float)((acc[0] + acc[1]) + (acc[2] + acc[3]));
}

/* out = W x (W is rows x cols). Quantized rows are dequantized one group at a time. */
static void matvec(const jtlm_config *c, const jtlm_mat *w, const float *x, float *out) {
    if (c->bits == 0) {
        for (int r = 0; r < w->rows; r++) out[r] = dot(w->f + (size_t)r * (size_t)w->cols, x, w->cols);
        return;
    }
    float wg[JTLM_MAX_GROUP];
    int group = c->group;
    for (int r = 0; r < w->rows; r++) {
        size_t base = (size_t)r * (size_t)w->cols;
        JTLM_ACC acc[4] = {0, 0, 0, 0};
        for (int g0 = 0; g0 < w->cols; g0 += group) {
            size_t k = base + (size_t)g0;
            float sc = fp16_to_f32(w->scale[k / (size_t)group]);
            if (c->bits == 8) {
                const int8_t *q = (const int8_t *)w->q + k;
                for (int j = 0; j < group; j++) wg[j] = (float)q[j] * sc;
            } else {
                const uint8_t *q = w->q + k / 2; /* k is even: group is even */
                for (int j = 0; j < group; j += 2) {
                    int b = q[j >> 1];
                    wg[j] = (float)(((b & 0xf) ^ 8) - 8) * sc;
                    wg[j + 1] = (float)(((b >> 4) ^ 8) - 8) * sc;
                }
            }
            dot_acc(wg, x + g0, group, acc);
        }
        out[r] = (float)((acc[0] + acc[1]) + (acc[2] + acc[3]));
    }
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

float *jtlm_forward(const jtlm_model *m, jtlm_state *s, int token, int pos) {
    const jtlm_config *c = &m->cfg;
    int d = c->d_model, hd = c->head_dim, kv_dim = c->n_kv_heads * hd;
    int rep = c->n_heads / c->n_kv_heads, half = hd / 2;
    float scale = (float)(1.0 / sqrt((double)hd));
    const float *cr = m->rope_cos + (size_t)pos * (size_t)half;
    const float *sr = m->rope_sin + (size_t)pos * (size_t)half;

    mat_row(&m->embed, c->bits, c->group, token, s->x);
    for (int l = 0; l < c->n_layers; l++) {
        const jtlm_layer *L = &m->layers[l];
        size_t loff = (size_t)l * (size_t)c->max_seq_len * (size_t)kv_dim;
        float *kc = s->key_cache + loff, *vc = s->value_cache + loff;
        float *k = kc + (size_t)pos * (size_t)kv_dim, *v = vc + (size_t)pos * (size_t)kv_dim;

        rmsnorm(s->xb, s->x, L->attn_norm, d, c->norm_eps);
        matvec(c, &L->wq, s->xb, s->q);
        matvec(c, &L->wk, s->xb, k);
        matvec(c, &L->wv, s->xb, v);
        for (int h = 0; h < c->n_heads; h++) rope(s->q + h * hd, cr, sr, hd);
        for (int h = 0; h < c->n_kv_heads; h++) rope(k + h * hd, cr, sr, hd);

        for (int h = 0; h < c->n_heads; h++) {
            const float *qh = s->q + h * hd;
            int kh = h / rep; /* repeat_interleave */
            float *att = s->att + (size_t)h * (size_t)c->max_seq_len;
            for (int t = 0; t <= pos; t++)
                att[t] = dot(qh, kc + (size_t)t * (size_t)kv_dim + (size_t)kh * (size_t)hd, hd) * scale;
            softmax(att, pos + 1);
            float *o = s->xb2 + h * hd;
            for (int i = 0; i < hd; i++) {
                JTLM_ACC acc = 0;
                for (int t = 0; t <= pos; t++)
                    acc += (JTLM_ACC)att[t] * (JTLM_ACC)vc[(size_t)t * (size_t)kv_dim + (size_t)kh * (size_t)hd + (size_t)i];
                o[i] = (float)acc;
            }
        }
        matvec(c, &L->wo, s->xb2, s->xb);
        for (int i = 0; i < d; i++) s->x[i] += s->xb[i];

        rmsnorm(s->xb, s->x, L->mlp_norm, d, c->norm_eps);
        matvec(c, &L->w1, s->xb, s->hb);
        matvec(c, &L->w3, s->xb, s->hb2);
        for (int i = 0; i < c->d_ff; i++) {
            float g = s->hb[i];
            float silu = g / (1.0f + expf(-g));
            s->hb[i] = silu * s->hb2[i];
        }
        matvec(c, &L->w2, s->hb, s->xb);
        for (int i = 0; i < d; i++) s->x[i] += s->xb[i];
    }
    rmsnorm(s->xb, s->x, m->norm, d, c->norm_eps);
    matvec(c, &m->embed, s->xb, s->logits);
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

int jtlm_generate(const jtlm_model *m, jtlm_state *s, const jtlm_grammar *grammar,
                  const int *prompt, int n_prompt, jtlm_result *r, float *first_logits) {
    const jtlm_config *c = &m->cfg;
    int steps = c->max_seq_len - n_prompt;
    if (steps > JTLM_MAX_NEW_TOKENS) steps = JTLM_MAX_NEW_TOKENS;
    r->n = 0;
    r->min_prob = 1.0f;
    if (n_prompt < 1 || steps <= 0) return JTLM_ERR_ARG;
    float *logits = NULL;
    for (int i = 0; i < n_prompt; i++) logits = jtlm_forward(m, s, prompt[i], i);
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
