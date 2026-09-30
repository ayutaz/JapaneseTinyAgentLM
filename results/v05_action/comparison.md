## Evaluation set (1189 cases, exact match %)

| model | exact_rate | single | multi_action | negation | no_action | correction | en | no_action_precision | no_action_recall | critical_error_rate | pair_accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule baseline | 76.4 | 60.9 | 46.9 | 88.1 | 99.1 | 76.4 | 77.1 | 79.8 | 94.2 | 2.9 | 83.8 |
| 3m (3.15M) | 96.0 | 92.5 | 96.4 | 96.3 | 99.1 | 94.5 | 71.4 | 98.0 | 97.9 | 1.1 | 96.2 |
| 3m-s1 (3.15M) | 94.9 | 90.4 | 95.8 | 95.2 | 98.8 | 92.7 | 57.1 | 97.2 | 97.2 | 1.4 | 91.2 |
| 5m (5.05M) | 93.8 | 88.7 | 94.3 | 94.1 | 98.8 | 90.9 | 51.4 | 96.5 | 96.7 | 1.8 | 91.2 |

## TinyLM-Bench 16 cases (exact match %)

| model | exact_rate | no_action_precision | critical_error_rate |
|---|---:|---:|---:|
| rule baseline | 100.0 | 100.0 | 0.0 |
| Needle 2 official | 18.8 | 33.3 | 50.0 |
| FunctionGemma 270M | 37.5 | 100.0 | 50.0 |
| MimiModel C | 6.2 | 100.0 | 68.8 |
| 3m (3.15M) | 81.2 | 85.7 | 0.0 |
| 3m-s1 (3.15M) | 93.8 | 100.0 | 0.0 |
| 5m (5.05M) | 81.2 | 100.0 | 6.2 |
