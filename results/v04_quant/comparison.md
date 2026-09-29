## Evaluation set (1189 cases, exact match %)

| model | exact_rate | single | multi_action | negation | no_action | correction | en | no_action_precision | no_action_recall | critical_error_rate | pair_accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule baseline | 76.4 | 60.9 | 46.9 | 88.1 | 99.1 | 76.4 | 77.1 | 79.8 | 94.2 | 2.9 | 83.8 |
| 3m (3.15M) +grammar | 94.2 | 89.0 | 96.9 | 95.2 | 97.0 | 94.5 | 31.4 | 98.2 | 96.2 | 2.0 | 92.5 |
| 3m-q8_g64 (3.15M) +grammar | 94.2 | 89.0 | 96.9 | 95.2 | 97.0 | 94.5 | 31.4 | 98.2 | 96.2 | 2.0 | 92.5 |
| 3m-q4_g64 (3.15M) +grammar | 94.3 | 89.3 | 97.4 | 95.2 | 97.0 | 92.7 | 34.3 | 98.0 | 96.2 | 2.0 | 92.5 |
| 3m-s1-q4_g64 (3.15M) +grammar | 94.4 | 91.0 | 96.9 | 94.1 | 96.1 | 98.2 | 42.9 | 98.6 | 95.2 | 2.4 | 90.0 |

## TinyLM-Bench 16 cases (exact match %)

| model | exact_rate | no_action_precision | critical_error_rate |
|---|---:|---:|---:|
| rule baseline | 100.0 | 100.0 | 0.0 |
| Needle 2 official | 18.8 | 33.3 | 50.0 |
| FunctionGemma 270M | 37.5 | 100.0 | 50.0 |
| MimiModel C | 6.2 | 100.0 | 68.8 |
| 3m (3.15M) +grammar | 87.5 | 100.0 | 6.2 |
| 3m-q8_g64 (3.15M) +grammar | 87.5 | 100.0 | 6.2 |
| 3m-q4_g64 (3.15M) +grammar | 87.5 | 100.0 | 6.2 |
| 3m-s1-q4_g64 (3.15M) +grammar | 87.5 | 100.0 | 6.2 |
