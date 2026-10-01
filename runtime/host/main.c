// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
/* jtalm: command-line front end of the reference runtime.
 *
 *     jtalm -m model.jtlm [-i prompts.txt] [--grammar] [--first-logits]
 *     jtalm -m model.jtlm --tokenize [-i texts.txt]
 *     jtalm -m model.jtlm --decode [-i ids.txt]
 *     jtalm -m model.jtlm --grammar-trace [-i ids.txt]
 *
 * Input is UTF-8, one item per line, from a file or stdin (never argv, so Japanese text does not
 * depend on the console code page). A UTF-8 BOM on the first line and CR/LF line ends are
 * removed. Output is one JSON object per line on stdout; a timing summary goes to stderr. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "jtalm.h"

static double now_seconds(void) {
    struct timespec ts;
    if (timespec_get(&ts, TIME_UTC) != TIME_UTC) return (double)clock() / CLOCKS_PER_SEC;
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static void *read_file(const char *path, size_t *size) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    size_t cap = 1 << 20, n = 0;
    char *buf = malloc(cap);
    for (size_t got; buf && (got = fread(buf + n, 1, cap - n, f)) > 0;) {
        n += got;
        if (n == cap) {
            char *bigger = realloc(buf, cap *= 2);
            if (!bigger) free(buf);
            buf = bigger;
        }
    }
    fclose(f);
    *size = n;
    return buf;
}

/* Reads one line into *buf (grown as needed) without the line end; returns its length or -1. */
static long read_line(FILE *f, char **buf, size_t *cap) {
    size_t n = 0;
    for (;;) {
        if (n + 2 > *cap) {
            char *bigger = realloc(*buf, *cap = *cap ? *cap * 2 : 1024);
            if (!bigger) return -1;
            *buf = bigger;
        }
        if (!fgets(*buf + n, (int)(*cap - n), f)) {
            if (n == 0) return -1;
            break;
        }
        n += strlen(*buf + n);
        if (n && (*buf)[n - 1] == '\n') break;
    }
    while (n && ((*buf)[n - 1] == '\n' || (*buf)[n - 1] == '\r')) n--;
    (*buf)[n] = '\0';
    return (long)n;
}

static void print_json_string(const char *s, size_t n) {
    putchar('"');
    for (size_t i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c == '"' || c == '\\') printf("\\%c", c);
        else if (c == '\n') fputs("\\n", stdout);
        else if (c == '\r') fputs("\\r", stdout);
        else if (c == '\t') fputs("\\t", stdout);
        else if (c < 0x20) printf("\\u%04x", c);
        else putchar(c);
    }
    putchar('"');
}

static void print_ids(const int *ids, int n) {
    putchar('[');
    for (int i = 0; i < n; i++) printf(i ? ",%d" : "%d", ids[i]);
    putchar(']');
}

static void usage(void) {
    fprintf(stderr,
            "usage: jtalm -m MODEL.jtlm [-i FILE] [--grammar] [--first-logits]\n"
            "       jtalm -m MODEL.jtlm --tokenize [-i FILE]   (text -> ids)\n"
            "       jtalm -m MODEL.jtlm --decode [-i FILE]     (space-separated ids -> text)\n"
            "       jtalm -m MODEL.jtlm --grammar-trace [-i FILE]"
            "   (id lines -> allowed ids per prefix)\n"
            "Reads UTF-8 lines from FILE or stdin and prints one JSON value per line.\n");
}

int main(int argc, char **argv) {
    const char *model_path = NULL, *input_path = NULL;
    int use_grammar = 0, tokenize = 0, decode = 0, first_logits = 0, trace = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-m") && i + 1 < argc) model_path = argv[++i];
        else if (!strcmp(argv[i], "-i") && i + 1 < argc) input_path = argv[++i];
        else if (!strcmp(argv[i], "--grammar")) use_grammar = 1;
        else if (!strcmp(argv[i], "--tokenize")) tokenize = 1;
        else if (!strcmp(argv[i], "--decode")) decode = 1;
        else if (!strcmp(argv[i], "--first-logits")) first_logits = 1;
        else if (!strcmp(argv[i], "--grammar-trace")) trace = 1;
        else {
            usage();
            return 2;
        }
    }
    if (!model_path) {
        usage();
        return 2;
    }

    size_t size;
    void *image = read_file(model_path, &size);
    if (!image) {
        fprintf(stderr, "cannot read %s\n", model_path);
        return 1;
    }
    jtlm_model model;
    if (jtlm_model_init(&model, image, size) != JTLM_OK) {
        fprintf(stderr, "%s: not a valid .jtlm file\n", model_path);
        return 1;
    }
    const jtlm_config *c = &model.cfg;

    jtlm_state state;
    void *arena = malloc(jtlm_state_bytes(c));
    float *logits0 = malloc((size_t)c->vocab_size * sizeof(float));
    int *ids = malloc((size_t)(c->max_seq_len > 4096 ? c->max_seq_len : 4096) * sizeof(int));
    size_t work_bytes = 1 << 16, out_cap = 1 << 16;
    void *work = malloc(work_bytes);
    char *out = malloc(out_cap);
    if (!arena || !logits0 || !ids || !work || !out) {
        fprintf(stderr, "out of memory\n");
        return 1;
    }
    jtlm_grammar grammar;
    if ((use_grammar || trace) &&
        jtlm_grammar_init(&grammar, &model.tok, work, work_bytes) != JTLM_OK) {
        fprintf(stderr, "the tokenizer lacks the Action grammar pieces\n");
        return 1;
    }

    FILE *in = stdin;
    if (input_path && strcmp(input_path, "-") != 0 && !(in = fopen(input_path, "rb"))) {
        fprintf(stderr, "cannot read %s\n", input_path);
        return 1;
    }

    char *line = NULL;
    size_t line_cap = 0;
    long len;
    long n_lines = 0, n_forward = 0, n_generated = 0;
    double t0 = now_seconds();
    while ((len = read_line(in, &line, &line_cap)) >= 0) {
        char *text = line;
        if (n_lines++ == 0 && len >= 3 && !memcmp(text, "\xef\xbb\xbf", 3)) text += 3, len -= 3;

        if (trace) { /* allowed ids before each token of the line and after the last one */
            int n = 0;
            for (char *p = text, *end; n < 4096; p = end) {
                long v = strtol(p, &end, 10);
                if (end == p) break;
                ids[n++] = (int)v;
            }
            jtlm_grammar_state st;
            jtlm_grammar_reset(&st);
            fputs("{\"allowed\":[", stdout);
            for (int i = 0; i <= n; i++) {
                int allowed[JTLM_MAX_ALLOWED], k = jtlm_grammar_allowed(&grammar, &st, allowed);
                if (i) putchar(',');
                print_ids(allowed, k);
                if (i < n) jtlm_grammar_advance(&grammar, &st, ids[i]);
            }
            fputs("]}\n", stdout);
            continue;
        }

        if (decode) {
            int n = 0;
            for (char *p = text, *end; n < 4096; p = end) {
                long v = strtol(p, &end, 10);
                if (end == p) break;
                ids[n++] = (int)v;
            }
            size_t need = jtlm_decode(&model.tok, ids, n, out, out_cap);
            if (need >= out_cap) {
                free(out);
                out = malloc(out_cap = need + 1);
                if (!out) return 1;
                jtlm_decode(&model.tok, ids, n, out, out_cap);
            }
            print_json_string(out, need);
            putchar('\n');
            continue;
        }

        int n;
        for (;;) { /* grow the tokenizer workspace for unusually long or expanding lines */
            n = tokenize ? jtlm_encode(&model.tok, text, (size_t)len, ids, 4096, work, work_bytes)
                         : jtlm_prompt_ids(&model, text, (size_t)len, ids, work, work_bytes);
            if (n != JTLM_ERR_SPACE) break;
            free(work);
            work = malloc(work_bytes *= 4);
            if (!work) return 1;
        }
        if (n < 0) {
            fprintf(stderr, "line %ld: tokenizer error %d\n", n_lines, n);
            return 1;
        }
        if (tokenize) {
            print_ids(ids, n < 4096 ? n : 4096);
            putchar('\n');
            continue;
        }

        jtlm_state_init(&state, c, arena);
        jtlm_result r;
        if (jtlm_generate(&model, &state, use_grammar ? &grammar : NULL, ids, n, &r,
                          first_logits ? logits0 : NULL) != JTLM_OK) {
            fprintf(stderr, "line %ld: generation failed\n", n_lines);
            return 1;
        }
        n_forward += n + r.n - 1;
        n_generated += r.n;
        int n_text = r.n && r.ids[r.n - 1] == model.tok.eos ? r.n - 1 : r.n;
        size_t olen = jtlm_decode(&model.tok, r.ids, n_text, out, out_cap);
        fputs("{\"output\":", stdout);
        print_json_string(out, olen < out_cap ? olen : out_cap - 1);
        printf(",\"min_prob\":%.9g,\"tokens\":%d,\"ids\":", (double)r.min_prob, r.n);
        print_ids(r.ids, r.n);
        if (first_logits) {
            fputs(",\"logits0\":[", stdout);
            for (int i = 0; i < c->vocab_size; i++) printf(i ? ",%.9g" : "%.9g", (double)logits0[i]);
            putchar(']');
        }
        fputs("}\n", stdout);
    }
    double dt = now_seconds() - t0;
    if (!tokenize && !decode && !trace && n_lines)
        fprintf(stderr, "%ld prompts, %ld forward tokens (%ld generated) in %.3f s: %.1f tok/s\n",
                n_lines, n_forward, n_generated, dt, dt > 0 ? (double)n_forward / dt : 0.0);
    if (in != stdin) fclose(in);
    free(line);
    free(out);
    free(work);
    free(ids);
    free(logits0);
    free(arena);
    free(image);
    return 0;
}
