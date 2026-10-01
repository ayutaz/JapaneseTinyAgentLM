// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
/* SentencePiece-compatible unigram tokenizer (encode and decode), following sentencepiece 0.2:
 * normalizer.cc (Normalize / NormalizePrefix), unigram_model.cc (EncodeOptimized),
 * sentencepiece_processor.cc (byte fallback in PopulateSentencePieceText, Decode). */
#include <string.h>

#include "jtalm.h"

#define FLAG_DUMMY_PREFIX 1u
#define FLAG_REMOVE_WS 2u
#define FLAG_ESCAPE_WS 4u
#define FLAG_BYTE_FALLBACK 8u

static const char SPACE_SYMBOL[] = "\xe2\x96\x81"; /* U+2581 */
static const char REPLACEMENT[] = "\xef\xbf\xbd"; /* U+FFFD */
static const char UNK_SURFACE[] = " \xe2\x81\x87 "; /* " U+2047 " */

/* -- UTF-8 (string_util.h) --------------------------------------------------------------------- */

static int is_trail(uint8_t c) { return (c & 0xc0) == 0x80; }
static int valid_cp(uint32_t c) { return c < 0xd800 || (c >= 0xe000 && c <= 0x10ffff); }

/* DecodeUTF8 + IsValidDecodeUTF8: returns 1 when valid; *mblen is 1 for invalid input. */
static int decode_utf8(const uint8_t *s, size_t n, size_t *mblen) {
    uint32_t cp;
    if (s[0] < 0x80) {
        *mblen = 1;
        return 1;
    } else if (n >= 2 && (s[0] & 0xe0) == 0xc0) {
        cp = (uint32_t)(s[0] & 0x1f) << 6 | (s[1] & 0x3f);
        if (is_trail(s[1]) && cp >= 0x80 && valid_cp(cp)) {
            *mblen = 2;
            return 1;
        }
    } else if (n >= 3 && (s[0] & 0xf0) == 0xe0) {
        cp = (uint32_t)(s[0] & 0x0f) << 12 | (uint32_t)(s[1] & 0x3f) << 6 | (s[2] & 0x3f);
        if (is_trail(s[1]) && is_trail(s[2]) && cp >= 0x800 && valid_cp(cp)) {
            *mblen = 3;
            return 1;
        }
    } else if (n >= 4 && (s[0] & 0xf8) == 0xf0) {
        cp = (uint32_t)(s[0] & 0x07) << 18 | (uint32_t)(s[1] & 0x3f) << 12 |
             (uint32_t)(s[2] & 0x3f) << 6 | (s[3] & 0x3f);
        if (is_trail(s[1]) && is_trail(s[2]) && is_trail(s[3]) && cp >= 0x10000 && valid_cp(cp)) {
            *mblen = 4;
            return 1;
        }
    }
    *mblen = 1;
    return 0;
}

/* OneCharLen: the length announced by the lead byte. */
static size_t one_char_len(uint8_t c) {
    static const uint8_t len[16] = {1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 3, 4};
    return len[c >> 4];
}

/* -- normalizer -------------------------------------------------------------------------------- */

/* Longest prefix of s in the charsmap (Darts-clone commonPrefixSearch); returns its length and
 * sets *value to the offset of the replacement in the normalized-string blob. */
static size_t charsmap_match(const jtlm_tokenizer *t, const uint8_t *s, size_t n, uint32_t *value) {
    const uint32_t *a = t->trie;
    if (!a || !t->trie_units) return 0;
#define OFFSET(u) (((u) >> 10) << (((u) & (1u << 9)) >> 6))
#define LABEL(u) ((u) & ((1u << 31) | 0xffu))
#define HAS_LEAF(u) (((u) >> 8) & 1u)
#define VALUE(u) ((u) & ((1u << 31) - 1))
    size_t best = 0, found = 0;
    uint32_t pos = 0, unit = a[0];
    pos ^= OFFSET(unit);
    for (size_t i = 0; i < n; i++) {
        pos ^= s[i];
        if (pos >= t->trie_units) break;
        unit = a[pos];
        if (LABEL(unit) != s[i]) break;
        pos ^= OFFSET(unit);
        if (pos >= t->trie_units) break;
        if (HAS_LEAF(unit)) {
            /* Normalizer keeps the longest of the first 32 results. */
            if (found++ < 32) {
                best = i + 1;
                *value = VALUE(a[pos]);
            }
        }
    }
#undef OFFSET
#undef LABEL
#undef HAS_LEAF
#undef VALUE
    return best;
}

static int piece_is(const jtlm_tokenizer *t, int id, int type) { return t->types[id] == type; }

/* Longest user-defined piece that is a prefix of s (PrefixMatcher); 0 when none. */
static size_t user_defined_match(const jtlm_tokenizer *t, const uint8_t *s, size_t n) {
    size_t best = 0;
    for (int k = t->buckets[s[0]]; k < t->buckets[s[0] + 1]; k++) {
        int id = t->sorted[k];
        if (!piece_is(t, id, JTLM_USER_DEFINED)) continue;
        size_t len = t->offsets[id + 1] - t->offsets[id];
        if (len <= n && len > best && memcmp(t->bytes + t->offsets[id], s, len) == 0) best = len;
    }
    return best;
}

/* NormalizePrefix: the normalized form of the next unit of input and the bytes it consumes. */
static void normalize_prefix(const jtlm_tokenizer *t, const uint8_t *s, size_t n,
                             const char **out, size_t *out_len, size_t *consumed) {
    size_t len = user_defined_match(t, s, n);
    if (len) {
        *out = (const char *)s;
        *out_len = *consumed = len;
        return;
    }
    uint32_t value = 0;
    len = charsmap_match(t, s, n, &value);
    if (len && value < t->norm_size) {
        const char *end = memchr(t->norm + value, 0, t->norm_size - value);
        *out = t->norm + value;
        *out_len = end ? (size_t)(end - *out) : t->norm_size - value;
        *consumed = len;
        return;
    }
    size_t mblen;
    if (decode_utf8(s, n, &mblen)) {
        *out = (const char *)s;
        *out_len = *consumed = mblen;
    } else {
        *out = REPLACEMENT;
        *out_len = 3;
        *consumed = 1;
    }
}

typedef struct {
    char *buf;
    size_t len, cap;
    int overflow;
} sink;

static void put(sink *o, const char *s, size_t n) {
    if (o->len + n > o->cap) {
        o->overflow = 1;
        return;
    }
    memcpy(o->buf + o->len, s, n);
    o->len += n;
}

/* Normalizer::Normalize (without the offset mapping). */
static int normalize(const jtlm_tokenizer *t, const uint8_t *s, size_t n, sink *o) {
    int remove_ws = (t->flags & FLAG_REMOVE_WS) != 0, escape = (t->flags & FLAG_ESCAPE_WS) != 0;
    const char *p;
    size_t plen, used;
    if (remove_ws) { /* heading spaces */
        while (n) {
            normalize_prefix(t, s, n, &p, &plen, &used);
            if (!(plen == 1 && p[0] == ' ')) break;
            s += used;
            n -= used;
        }
    }
    if (!n) return JTLM_OK;
    if (t->flags & FLAG_DUMMY_PREFIX) {
        if (escape) put(o, SPACE_SYMBOL, 3);
        else put(o, " ", 1);
    }
    int prev_space = remove_ws;
    while (n) {
        normalize_prefix(t, s, n, &p, &plen, &used);
        if (prev_space)
            while (plen && p[0] == ' ') p++, plen--;
        if (plen) {
            for (size_t i = 0; i < plen; i++) {
                if (escape && p[i] == ' ') put(o, SPACE_SYMBOL, 3);
                else put(o, p + i, 1);
            }
            prev_space = p[plen - 1] == ' ';
        }
        s += used;
        n -= used;
        if (!remove_ws) prev_space = 0;
    }
    if (remove_ws) { /* trailing spaces */
        const char *sp = escape ? SPACE_SYMBOL : " ";
        size_t sl = escape ? 3 : 1;
        while (!o->overflow && o->len >= sl && memcmp(o->buf + o->len - sl, sp, sl) == 0) o->len -= sl;
    }
    return o->overflow ? JTLM_ERR_SPACE : JTLM_OK;
}

/* -- unigram Viterbi (EncodeOptimized) --------------------------------------------------------- */

typedef struct {
    float score;
    int32_t start, id, next;
} node;

int jtlm_encode(const jtlm_tokenizer *t, const char *text, size_t len, int *ids, int max_ids,
                void *work, size_t work_bytes) {
    sink o = {work, 0, work_bytes, 0};
    int rc = normalize(t, (const uint8_t *)text, len, &o);
    if (rc) return rc;
    const uint8_t *s = (const uint8_t *)o.buf;
    size_t size = o.len, at = (o.len + 15) / 16 * 16;
    if (at + (size + 1) * sizeof(node) > work_bytes) return JTLM_ERR_SPACE;
    node *best = (node *)((char *)work + at);
    for (size_t i = 0; i <= size; i++) best[i] = (node){0.0f, -1, -1, -1};
    const float unk_score = t->min_score - 10.0f; /* kUnkPenalty */

    for (size_t start = 0; start < size;) {
        float till_here = best[start].score;
        int has_single = 0;
        size_t mblen = one_char_len(s[start]);
        if (mblen > size - start) mblen = size - start;
        for (int k = t->buckets[s[start]]; k < t->buckets[s[start] + 1]; k++) {
            int id = t->sorted[k], type = t->types[id];
            if (type != JTLM_NORMAL && type != JTLM_USER_DEFINED) continue; /* not in the trie, or unused */
            size_t plen = t->offsets[id + 1] - t->offsets[id];
            if (plen > size - start || memcmp(t->bytes + t->offsets[id], s + start, plen) != 0) continue;
            node *target = &best[start + plen];
            /* User-defined symbols get length * max_score - 0.1 so they always win; the
             * candidate is computed in double as in the C++ (the ternary promotes to double). */
            double score = type == JTLM_USER_DEFINED
                               ? (double)((float)plen * t->max_score) - 0.1
                               : (double)t->scores[id];
            double cand = score + (double)till_here;
            if (target->start == -1 || cand > (double)target->score) {
                target->score = (float)cand;
                target->start = (int32_t)start;
                target->id = id;
            }
            if (plen == mblen) has_single = 1;
        }
        if (!has_single) {
            node *target = &best[start + mblen];
            float cand = unk_score + till_here;
            if (target->start == -1 || cand > target->score) {
                target->score = cand;
                target->start = (int32_t)start;
                target->id = t->unk;
            }
        }
        start += mblen;
    }

    /* Link the best path forward, then emit ids (unknown pieces become bytes). */
    int32_t next = -1;
    for (int32_t end = (int32_t)size; end > 0; end = best[end].start) {
        best[end].next = next;
        next = end;
    }
    int n = 0;
    int fallback = (t->flags & FLAG_BYTE_FALLBACK) != 0;
    for (int32_t end = next; end != -1; end = best[end].next) {
        const node *nd = &best[end];
        if (nd->id == t->unk && fallback) {
            for (int32_t i = nd->start; i < end; i++) {
                if (n < max_ids) ids[n] = t->byte_ids[s[i]];
                n++;
            }
        } else {
            if (n < max_ids) ids[n] = nd->id;
            n++;
        }
    }
    return n;
}

/* -- decode ------------------------------------------------------------------------------------ */

static void put_trunc(sink *o, const char *s, size_t n) {
    for (size_t i = 0; i < n; i++) {
        if (o->len + 1 < o->cap) o->buf[o->len] = s[i];
        o->len++;
    }
}

static int byte_value(const jtlm_tokenizer *t, int id) {
    const uint8_t *p = t->bytes + t->offsets[id]; /* "<0xXX>" */
    int v = 0;
    for (int i = 3; i < 5; i++) v = v * 16 + (p[i] <= '9' ? p[i] - '0' : (p[i] | 0x20) - 'a' + 10);
    return v;
}

size_t jtlm_decode(const jtlm_tokenizer *t, const int *ids, int n, char *out, size_t cap) {
    sink o = {out, 0, cap, 0};
    int bos_ws = 1; /* strip one leading U+2581 until the first non-empty surface */
    int strip = (t->flags & (FLAG_DUMMY_PREFIX | FLAG_REMOVE_WS)) != 0;
    for (int i = 0; i < n;) {
        int id = ids[i];
        if (id < 0 || id >= t->n_pieces) {
            i++;
            continue;
        }
        int type = t->types[id];
        if (type == JTLM_BYTE) { /* a run of byte pieces, one surface per UTF-8 character */
            int j = i;
            while (j < n && ids[j] >= 0 && ids[j] < t->n_pieces && t->types[ids[j]] == JTLM_BYTE) j++;
            uint8_t window[4];
            for (int k = i; k < j;) {
                size_t w = 0, mblen;
                for (; w < 4 && k + (int)w < j; w++) window[w] = (uint8_t)byte_value(t, ids[k + (int)w]);
                if (decode_utf8(window, w, &mblen)) put_trunc(&o, (const char *)window, mblen);
                else put_trunc(&o, REPLACEMENT, 3);
                k += (int)mblen;
            }
            bos_ws = 0;
            i = j;
            continue;
        }
        if (type == JTLM_CONTROL) {
            i++;
            continue;
        }
        if (type == JTLM_UNKNOWN) {
            put_trunc(&o, UNK_SURFACE, sizeof(UNK_SURFACE) - 1);
            bos_ws = 0;
            i++;
            continue;
        }
        const char *p = (const char *)t->bytes + t->offsets[id];
        size_t plen = t->offsets[id + 1] - t->offsets[id];
        if (bos_ws && strip && plen >= 3 && memcmp(p, SPACE_SYMBOL, 3) == 0) p += 3, plen -= 3;
        for (size_t k = 0; k < plen;) {
            if (plen - k >= 3 && memcmp(p + k, SPACE_SYMBOL, 3) == 0) {
                put_trunc(&o, " ", 1);
                k += 3;
            } else {
                put_trunc(&o, p + k, 1);
                k++;
            }
        }
        if (plen) bos_ws = 0;
        i++;
    }
    if (cap) out[o.len < cap ? o.len : cap - 1] = '\0';
    return o.len;
}
