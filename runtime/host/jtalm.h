// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
/* JapaneseTinyAgentLM reference runtime (M6): portable C11, no dependencies.
 *
 * Loads a .jtlm file written by `python -m jtalm.model.export` (layout documented there),
 * tokenizes UTF-8 text like SentencePiece (nmt_nfkc charsmap + unigram Viterbi + byte fallback),
 * and runs greedy decoding with a KV cache, optionally under the Action schema v0 grammar.
 *
 * Memory: the model struct only points into the (read-only) file image, so the image can be a
 * flash mmap on the ESP32. All mutable state lives in one caller-provided arena sized by
 * jtlm_state_bytes(); nothing is allocated per token.
 */
#ifndef JTALM_H
#define JTALM_H

#include <stddef.h>
#include <stdint.h>

/* Dot-product accumulator. double keeps the host reference close to exact (and to PyTorch);
 * an FPU-only target such as the ESP32-S3 should build with -DJTLM_ACC=float. */
#ifndef JTLM_ACC
#define JTLM_ACC double
#endif

#define JTLM_MAX_LAYERS 32
#define JTLM_MAX_GROUP 256
#define JTLM_MAX_NEW_TOKENS 24 /* jtalm.model.data.MAX_TARGET_TOKENS */

/* Prompt tokens run together by jtlm_prefill, so each weight is read once per JTLM_BATCH tokens
 * instead of once per token. It sizes the activation buffers in the state. */
#ifndef JTLM_BATCH
#define JTLM_BATCH 16
#endif

/* INT8 KV cache: int8 codes with one f32 scale per position and KV head (symmetric, max|x| / 127,
 * round half to even), about 0.28x the bytes of the f32 cache. It changes the numerics, so the
 * outputs can differ from the default f32 cache; the matching PyTorch reference is
 * jtalm.model.transformer.set_kv_int8. Callers must build with the same value (it changes
 * jtlm_state). */
#ifndef JTLM_KV_INT8
#define JTLM_KV_INT8 0
#endif
#define JTLM_MAX_HEAD_DIM 256 /* JTLM_KV_INT8 only */

enum {
    JTLM_OK = 0,
    JTLM_ERR_FORMAT = -1, /* not a valid .jtlm image */
    JTLM_ERR_SPACE = -2,  /* caller buffer too small */
    JTLM_ERR_ARG = -3,
};

/* SentencePiece piece types (sentencepiece_model.proto). */
enum { JTLM_NORMAL = 1, JTLM_UNKNOWN = 2, JTLM_CONTROL = 3, JTLM_USER_DEFINED = 4,
       JTLM_UNUSED = 5, JTLM_BYTE = 6 };

typedef struct {
    int vocab_size, d_model, n_layers, n_heads, n_kv_heads, d_ff, max_seq_len, head_dim;
    float rope_theta, norm_eps;
    int bits, group; /* bits: 0 = f32, 8 or 4 = weight-only with one fp16 scale per group */
} jtlm_config;

typedef struct {
    const float *f;         /* bits == 0 */
    const uint8_t *q;       /* int8 codes, or int4 codes two per byte (low nibble first) */
    const uint16_t *scale;  /* fp16 bits, rows * cols / group */
    int rows, cols;
} jtlm_mat;

typedef struct {
    const float *attn_norm, *mlp_norm;
    jtlm_mat wq, wk, wv, wo, w1, w3, w2;
} jtlm_layer;

typedef struct {
    int n_pieces, unk, bos, eos, pad, act, out;
    uint32_t flags;
    const float *scores;
    const uint8_t *types;
    const uint32_t *offsets; /* n_pieces + 1 offsets into bytes */
    const uint8_t *bytes;
    const uint16_t *sorted;  /* ids sorted by piece bytes */
    const uint16_t *buckets; /* 257 first-byte bucket starts into sorted */
    const uint16_t *byte_ids;
    const uint32_t *trie;    /* charsmap Darts-clone double array */
    uint32_t trie_units;
    const char *norm;        /* charsmap NUL-separated normalized strings */
    uint32_t norm_size;
    float min_score, max_score;
} jtlm_tokenizer;

typedef struct {
    jtlm_config cfg;
    jtlm_tokenizer tok;
    jtlm_mat embed; /* tied: also the output head */
    jtlm_layer layers[JTLM_MAX_LAYERS];
    const float *norm;
    const float *rope_cos, *rope_sin; /* [max_seq_len][head_dim / 2] */
    const uint8_t *tokenizer_sha256;
} jtlm_model;

typedef struct {
    float *x, *xb, *xb2, *q, *hb, *hb2; /* JTLM_BATCH rows each */
    float *att, *logits;
#if JTLM_KV_INT8
    float *k_new, *v_new;            /* JTLM_BATCH rows: keys and values before quantization */
    int8_t *key_cache, *value_cache; /* [n_layers][max_seq_len][n_kv_heads * head_dim] */
    float *key_scale, *value_scale;  /* [n_layers][max_seq_len][n_kv_heads] */
#else
    float *key_cache, *value_cache; /* [n_layers][max_seq_len][n_kv_heads * head_dim] */
#endif
} jtlm_state;

/* Model image (must stay alive and 4-byte aligned; nothing is copied). */
int jtlm_model_init(jtlm_model *m, const void *image, size_t size);

/* Mutable state carved out of one arena of jtlm_state_bytes() bytes (8-byte aligned). */
size_t jtlm_state_bytes(const jtlm_config *c);
void jtlm_state_init(jtlm_state *s, const jtlm_config *c, void *arena);

/* The same state in two buffers: the KV cache (jtlm_state_kv_bytes(), the bulk of the state)
 * and the small, hot rest (jtlm_state_bytes() - jtlm_state_kv_bytes()), e.g. PSRAM and
 * internal SRAM on the ESP32. Both 8-byte aligned. */
size_t jtlm_state_kv_bytes(const jtlm_config *c);
void jtlm_state_init_split(jtlm_state *s, const jtlm_config *c, void *arena, void *kv_cache);

/* Runs one token at position pos (0-based) and returns the logits (vocab_size floats). */
float *jtlm_forward(const jtlm_model *m, jtlm_state *s, int token, int pos);

/* Optional parallel matrix products (e.g. both cores of the ESP32-S3). run(fn, ctx, n) must call
 * fn(ctx, begin, end) on disjoint ranges that cover [0, n) and return when all have finished.
 * Each output row is computed the same way whatever the split, so results do not change.
 * NULL (the default) runs fn(ctx, 0, n) directly. Global: set it before running a model. */
typedef void (*jtlm_range_fn)(void *ctx, int begin, int end);
typedef void (*jtlm_parallel_fn)(jtlm_range_fn fn, void *ctx, int n);
void jtlm_set_parallel(jtlm_parallel_fn run);

/* Encodes UTF-8 text like SentencePieceProcessor::Encode (no <s>/</s>). Writes at most max_ids
 * ids and returns the total count (which may exceed max_ids), or JTLM_ERR_SPACE when work is
 * too small; the normalized text plus 16 bytes per normalized byte is always enough. */
int jtlm_encode(const jtlm_tokenizer *t, const char *text, size_t len, int *ids, int max_ids,
                void *work, size_t work_bytes);

/* Decodes ids like SentencePieceProcessor::Decode. Writes at most cap - 1 bytes plus a NUL and
 * returns the full length. */
size_t jtlm_decode(const jtlm_tokenizer *t, const int *ids, int n, char *out, size_t cap);

/* Action schema v0 grammar (port of jtalm.model.grammar). */
typedef struct {
    int eos;
    int empty, open, close, comma, look, amount_key, expr, nod, close_str, close_obj;
    int dirs[5], amounts[3], exprs[4], counts[3]; /* schema order */
} jtlm_grammar;

typedef struct {
    int step;
    int n_calls, calls[2][3], n_cur, cur[3]; /* token ids: name piece, then values */
} jtlm_grammar_state;

int jtlm_grammar_init(jtlm_grammar *g, const jtlm_tokenizer *t, void *work, size_t work_bytes);
void jtlm_grammar_reset(jtlm_grammar_state *st);
/* Writes the allowed ids (at most 8) after the tokens consumed so far; returns their count. */
int jtlm_grammar_allowed(const jtlm_grammar *g, const jtlm_grammar_state *st, int *ids);
void jtlm_grammar_advance(const jtlm_grammar *g, jtlm_grammar_state *st, int token);

/* The prompt of jtalm.model.data.Codec.prompt_ids: <s> <act> body[:max_seq_len - 27] <out>.
 * Returns the length or a negative error. ids needs max_seq_len entries. */
int jtlm_prompt_ids(const jtlm_model *m, const char *text, size_t len, int *ids, void *work,
                    size_t work_bytes);

typedef struct {
    int ids[JTLM_MAX_NEW_TOKENS]; /* generated ids, ending with </s> when it was produced */
    int n;
    float min_prob; /* minimum unconstrained probability of the chosen tokens */
} jtlm_result;

/* Greedy decoding as in jtalm.model.decode.greedy. grammar may be NULL. first_logits, when
 * not NULL, receives the logits of the first generated step (vocab_size floats). */
int jtlm_generate(const jtlm_model *m, jtlm_state *s, const jtlm_grammar *grammar,
                  const int *prompt, int n_prompt, jtlm_result *r, float *first_logits);

/* The two halves of jtlm_generate, for callers that time them separately: jtlm_prefill runs
 * the prompt (positions 0 .. n_prompt - 1) and returns the logits of its last position, and
 * jtlm_generate_from decodes greedily from them. */
float *jtlm_prefill(const jtlm_model *m, jtlm_state *s, const int *prompt, int n_prompt);
int jtlm_generate_from(const jtlm_model *m, jtlm_state *s, const jtlm_grammar *grammar,
                       float *logits, int n_prompt, jtlm_result *r, float *first_logits);

#endif
