gate threshold 0.86172

| set | n | exact | requests exact | false action rate | false actions | critical | numeric gated |
|---|---:|---:|---:|---:|---:|---:|---:|
| Stack-chan v1 | 140 | 95.0 | 90.7 | 0.0 | 0/65 | 0.0 | 0.0 |
| eval v3 (LLM) | 1816 | 96.0 | 94.4 | 0.4 | 2/555 | 0.1 | 2.6 |
| v0 eval (LLM) | 1189 | 92.4 | 84.9 | 0.3 | 2/605 | 0.2 | — |
| human v1 | 1157 | 99.2 | 89.2 | 0.2 | 2/1092 | 0.2 | — |
| v2/amount_words | 278 | 86.3 | 86.3 | — | 0/0 | 0.4 | — |
| v2/center_phrasing | 223 | 90.6 | 90.6 | — | 0/0 | 0.0 | — |
| v2/correction | 44 | 86.4 | 86.4 | — | 0/0 | 0.0 | — |
| v2/english | 70 | 47.1 | 2.6 | 0.0 | 0/32 | 0.0 | — |
| v2/fragments | 182 | 100.0 | — | 0.0 | 0/182 | 0.0 | — |
| v2/long_preface | 247 | 89.1 | 89.1 | — | 0/0 | 0.0 | — |
| v2/negation_forms | 168 | 100.0 | — | 0.0 | 0/168 | 0.0 | — |
| v2/numbers | 167 | 88.6 | 71.4 | 1.0 | 1/104 | 0.6 | — |
| v2/order_words | 296 | 97.3 | 97.3 | — | 0/0 | 0.0 | — |
| v2/orthography | 282 | 84.0 | 82.4 | 0.0 | 0/27 | 0.0 | — |
| v2/question_forms | 203 | 86.2 | 86.2 | — | 0/0 | 0.0 | — |
| v2/unexecutable | 286 | 99.0 | 0.0 | 0.7 | 2/285 | 0.7 | — |

Stack-chan v1 source=user: n=4 exact=100.0

Stack-chan v1 source=verbatim: n=97 exact=93.8

Stack-chan v1 source=paraphrase: n=39 exact=97.4

Stack-chan v1 tool=look: n=52 exact=94.2
