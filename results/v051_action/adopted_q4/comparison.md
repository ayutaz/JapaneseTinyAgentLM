## Evaluation set (1189 cases, exact match %)

| model | exact_rate | single | multi_action | negation | no_action | correction | en | no_action_precision | no_action_recall | critical_error_rate | pair_accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule baseline | 76.4 | 60.9 | 46.9 | 88.1 | 99.1 | 76.4 | 77.1 | 79.8 | 94.2 | 2.9 | 83.8 |
| 3m-q4_g64 (3.15M) | 94.6 | 89.6 | 95.8 | 97.0 | 97.6 | 90.9 | 57.1 | 97.0 | 97.4 | 1.5 | 97.5 |
| 3m-q4_g64 (3.15M) +grammar | 94.6 | 89.6 | 95.8 | 97.0 | 97.6 | 90.9 | 57.1 | 97.0 | 97.4 | 1.3 | 97.5 |
| 3m-q4_g64 (3.15M) +gate | 93.8 | 86.3 | 92.7 | 100.0 | 99.1 | 80.0 | 57.1 | 91.5 | 99.5 | 0.3 | 98.8 |

## TinyLM-Bench 16 cases (exact match %)

| model | exact_rate | no_action_precision | critical_error_rate |
|---|---:|---:|---:|
| rule baseline | 100.0 | 100.0 | 0.0 |
| Needle 2 official | 18.8 | 33.3 | 50.0 |
| FunctionGemma 270M | 37.5 | 100.0 | 50.0 |
| MimiModel C | 6.2 | 100.0 | 68.8 |
| 3m-q4_g64 (3.15M) | 75.0 | 83.3 | 6.2 |
| 3m-q4_g64 (3.15M) +grammar | 75.0 | 83.3 | 6.2 |
| 3m-q4_g64 (3.15M) +gate | 62.5 | 55.6 | 6.2 |
