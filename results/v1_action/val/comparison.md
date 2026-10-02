## Evaluation set (4678 cases, exact match %)

| model | exact_rate | single | multi_action | negation | no_action | correction | en | no_action_precision | no_action_recall | critical_error_rate | pair_accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule baseline | 59.0 | 36.1 | 37.7 | 88.5 | 96.4 | 48.4 | — | 63.2 | 93.9 | 2.4 | — |
| 3m-s0 (3.15M) | 98.2 | 97.4 | 98.4 | 99.5 | 98.7 | 98.0 | — | 98.8 | 98.9 | 0.5 | — |
| 3m-s1 (3.15M) | 98.2 | 96.9 | 98.8 | 99.6 | 98.5 | 98.8 | — | 98.7 | 98.9 | 0.5 | — |
| 3m-s2 (3.15M) | 98.1 | 96.8 | 98.9 | 98.9 | 98.3 | 98.4 | — | 98.9 | 98.5 | 0.6 | — |
| 3m-s3 (3.15M) | 98.2 | 97.1 | 98.4 | 99.3 | 98.4 | 99.6 | — | 98.9 | 98.7 | 0.6 | — |
| 3m-s4 (3.15M) | 98.2 | 96.9 | 98.6 | 99.1 | 98.8 | 98.8 | — | 98.8 | 98.9 | 0.5 | — |

## TinyLM-Bench 16 cases (exact match %)

| model | exact_rate | no_action_precision | critical_error_rate |
|---|---:|---:|---:|
| rule baseline | 100.0 | 100.0 | 0.0 |
| Needle 2 official | 18.8 | 33.3 | 50.0 |
| FunctionGemma 270M | 37.5 | 100.0 | 50.0 |
| MimiModel C | 6.2 | 100.0 | 68.8 |
| 3m-s0 (3.15M) | 81.2 | 71.4 | 6.2 |
| 3m-s1 (3.15M) | 81.2 | 100.0 | 6.2 |
| 3m-s2 (3.15M) | 81.2 | 75.0 | 0.0 |
| 3m-s3 (3.15M) | 93.8 | 100.0 | 0.0 |
| 3m-s4 (3.15M) | 81.2 | 66.7 | 0.0 |
