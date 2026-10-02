gate threshold 0.93985

| set | n | exact | requests exact | false action rate | false actions | critical | numeric gated |
|---|---:|---:|---:|---:|---:|---:|---:|
| Stack-chan v1 | 140 | 95.0 | 90.7 | 0.0 | 0/65 | 0.0 | 9.1 |
| eval v3 (LLM) | 1816 | 95.3 | 93.4 | 0.4 | 2/555 | 0.1 | 3.5 |
| v0 eval (LLM) | 1189 | 91.8 | 83.6 | 0.3 | 2/605 | 0.2 | — |
| human v1 | 1157 | 99.3 | 90.8 | 0.2 | 2/1092 | 0.2 | — |
| v2/amount_words | 278 | 82.7 | 82.7 | — | 0/0 | 0.0 | — |
| v2/center_phrasing | 223 | 93.3 | 93.3 | — | 0/0 | 0.0 | — |
| v2/correction | 44 | 88.6 | 88.6 | — | 0/0 | 0.0 | — |
| v2/english | 70 | 41.4 | 2.6 | 12.5 | 4/32 | 5.7 | — |
| v2/fragments | 182 | 100.0 | — | 0.0 | 0/182 | 0.0 | — |
| v2/long_preface | 247 | 85.0 | 85.0 | — | 0/0 | 0.0 | — |
| v2/negation_forms | 168 | 100.0 | — | 0.0 | 0/168 | 0.0 | — |
| v2/numbers | 167 | 83.8 | 58.7 | 1.0 | 1/104 | 0.6 | — |
| v2/order_words | 296 | 97.0 | 97.0 | — | 0/0 | 0.0 | — |
| v2/orthography | 282 | 81.2 | 79.2 | 0.0 | 0/27 | 0.0 | — |
| v2/question_forms | 203 | 85.7 | 85.7 | — | 0/0 | 0.0 | — |
| v2/unexecutable | 286 | 99.3 | 0.0 | 0.4 | 1/285 | 0.3 | — |

Stack-chan v1 source=user: n=4 exact=100.0

Stack-chan v1 source=verbatim: n=97 exact=93.8

Stack-chan v1 source=paraphrase: n=39 exact=97.4

Stack-chan v1 tool=look: n=52 exact=94.2
