## Evaluation set (1159 cases, exact match %)

| model | exact_rate | single | multi_action | negation | no_action | correction | en | no_action_precision | no_action_recall | critical_error_rate | pair_accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule baseline | 96.2 | 40.3 | — | 100.0 | 99.4 | — | — | 96.7 | 99.4 | 0.6 | — |
| 3m-q4_g64 (3.15M) +grammar | 95.6 | 93.5 | — | 100.0 | 95.7 | — | — | 99.9 | 95.7 | 4.1 | — |
| 3m-q4_g64 (3.15M) +gate | 98.4 | 88.7 | — | 100.0 | 98.9 | — | — | 99.5 | 98.9 | 1.0 | — |

## TinyLM-Bench 16 cases (exact match %)

| model | exact_rate | no_action_precision | critical_error_rate |
|---|---:|---:|---:|
| rule baseline | 100.0 | 100.0 | 0.0 |
| Needle 2 official | 18.8 | 33.3 | 50.0 |
| FunctionGemma 270M | 37.5 | 100.0 | 50.0 |
| MimiModel C | 6.2 | 100.0 | 68.8 |
| 3m-q4_g64 (3.15M) +grammar | 87.5 | 100.0 | 6.2 |
| 3m-q4_g64 (3.15M) +gate | 75.0 | 71.4 | 6.2 |
