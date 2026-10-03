gate threshold 0.90821

| set | n | exact | requests exact | false action rate | false actions | critical | numeric gated |
|---|---:|---:|---:|---:|---:|---:|---:|
| Stack-chan v1 | 140 | 94.3 | 89.3 | 0.0 | 0/65 | 0.0 | 9.1 |
| eval v3 (LLM) | 1816 | 94.7 | 92.5 | 0.4 | 2/555 | 0.1 | 3.8 |
| v0 eval (LLM) | 1189 | 92.0 | 84.2 | 0.5 | 3/605 | 0.3 | — |
| human v1 | 1157 | 99.6 | 93.8 | 0.1 | 1/1092 | 0.1 | — |
| v2/amount_words | 278 | 88.1 | 88.1 | — | 0/0 | 0.0 | — |
| v2/center_phrasing | 223 | 96.4 | 96.4 | — | 0/0 | 0.0 | — |
| v2/correction | 44 | 86.4 | 86.4 | — | 0/0 | 0.0 | — |
| v2/english | 70 | 50.0 | 13.2 | 6.2 | 2/32 | 2.9 | — |
| v2/fragments | 182 | 100.0 | — | 0.0 | 0/182 | 0.0 | — |
| v2/long_preface | 247 | 89.1 | 89.1 | — | 0/0 | 0.0 | — |
| v2/negation_forms | 168 | 100.0 | — | 0.0 | 0/168 | 0.0 | — |
| v2/numbers | 167 | 81.4 | 52.4 | 1.0 | 1/104 | 0.6 | — |
| v2/order_words | 296 | 97.0 | 97.0 | — | 0/0 | 0.0 | — |
| v2/orthography | 282 | 83.3 | 81.6 | 0.0 | 0/27 | 0.0 | — |
| v2/question_forms | 203 | 86.7 | 86.7 | — | 0/0 | 0.0 | — |
| v2/unexecutable | 286 | 98.6 | 0.0 | 1.1 | 3/285 | 1.0 | — |

Stack-chan v1 source=user: n=4 exact=100.0

Stack-chan v1 source=verbatim: n=97 exact=94.8

Stack-chan v1 source=paraphrase: n=39 exact=92.3

Stack-chan v1 tool=look: n=52 exact=92.3
