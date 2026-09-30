## Evaluation set (1189 cases, exact match %)

| model | exact_rate | single | multi_action | negation | no_action | correction | en | no_action_precision | no_action_recall | critical_error_rate | pair_accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule baseline | 76.4 | 60.9 | 46.9 | 88.1 | 99.1 | 76.4 | 77.1 | 79.8 | 94.2 | 2.9 | 83.8 |
| 3m (3.15M) | 94.7 | 90.1 | 95.8 | 97.0 | 97.3 | 90.9 | 54.3 | 97.0 | 97.2 | 1.5 | 98.8 |
| 3m-s1 (3.15M) | 94.7 | 89.3 | 95.3 | 97.0 | 98.8 | 89.1 | 51.4 | 96.4 | 98.0 | 1.3 | 95.0 |

## TinyLM-Bench 16 cases (exact match %)

| model | exact_rate | no_action_precision | critical_error_rate |
|---|---:|---:|---:|
| rule baseline | 100.0 | 100.0 | 0.0 |
| Needle 2 official | 18.8 | 33.3 | 50.0 |
| FunctionGemma 270M | 37.5 | 100.0 | 50.0 |
| MimiModel C | 6.2 | 100.0 | 68.8 |
| 3m (3.15M) | 68.8 | 80.0 | 12.5 |
| 3m-s1 (3.15M) | 68.8 | 60.0 | 0.0 |
