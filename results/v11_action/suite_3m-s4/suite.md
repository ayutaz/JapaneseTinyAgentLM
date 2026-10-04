gate threshold 0.9217

| set | n | exact | requests exact | false action rate | false actions | critical | numeric gated |
|---|---:|---:|---:|---:|---:|---:|---:|
| Stack-chan v1 | 140 | 92.9 | 86.7 | 0.0 | 0/65 | 0.0 | 9.1 |
| eval v3 (LLM) | 1816 | 94.3 | 92.1 | 0.5 | 3/555 | 0.2 | 5.0 |
| v0 eval (LLM) | 1189 | 92.2 | 84.6 | 0.5 | 3/605 | 0.3 | — |
| human v1 | 1157 | 99.6 | 92.3 | 0.0 | 0/1092 | 0.0 | — |
| LED v1.1 (LLM) | 437 | 91.1 | 89.4 | 0.0 | 0/69 | 0.0 | 12.5 |
| v2/amount_words | 278 | 88.8 | 88.8 | — | 0/0 | 0.4 | — |
| v2/center_phrasing | 223 | 92.8 | 92.8 | — | 0/0 | 0.0 | — |
| v2/correction | 44 | 79.5 | 79.5 | — | 0/0 | 0.0 | — |
| v2/english | 70 | 47.1 | 2.6 | 0.0 | 0/32 | 0.0 | — |
| v2/fragments | 182 | 100.0 | — | 0.0 | 0/182 | 0.0 | — |
| v2/long_preface | 247 | 85.0 | 85.0 | — | 0/0 | 0.0 | — |
| v2/negation_forms | 168 | 100.0 | — | 0.0 | 0/168 | 0.0 | — |
| v2/numbers | 167 | 87.4 | 68.3 | 1.0 | 1/104 | 0.6 | — |
| v2/order_words | 296 | 94.9 | 94.9 | — | 0/0 | 0.0 | — |
| v2/orthography | 282 | 84.8 | 83.1 | 0.0 | 0/27 | 0.0 | — |
| v2/question_forms | 203 | 87.2 | 87.2 | — | 0/0 | 0.0 | — |
| v2/unexecutable | 286 | 99.7 | 100.0 | 0.4 | 1/285 | 0.3 | — |

Stack-chan v1 source=user: n=4 exact=100.0

Stack-chan v1 source=verbatim: n=97 exact=91.8

Stack-chan v1 source=paraphrase: n=39 exact=94.9

Stack-chan v1 tool=look: n=52 exact=92.3
