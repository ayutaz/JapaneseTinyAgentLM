## Evaluation set (1189 cases, exact match %)

| model | exact_rate | single | multi_action | negation | no_action | correction | en | no_action_precision | no_action_recall | critical_error_rate | pair_accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule baseline | 76.4 | 60.9 | 46.9 | 88.1 | 99.1 | 76.4 | 77.1 | 79.8 | 94.2 | 2.9 | 83.8 |
| 3m (3.15M) | 94.2 | 89.0 | 96.9 | 95.2 | 97.0 | 94.5 | 31.4 | 98.2 | 96.2 | 2.2 | 92.5 |
| 3m-s1 (3.15M) | 94.4 | 90.4 | 96.9 | 94.4 | 96.4 | 98.2 | 45.7 | 98.6 | 95.6 | 2.4 | 88.8 |
| 5m (5.05M) | 93.4 | 90.1 | 91.7 | 95.9 | 96.4 | 87.3 | 42.9 | 97.8 | 96.2 | 2.2 | 95.0 |
| 5m-s1 (5.05M) | 93.2 | 88.7 | 91.7 | 96.3 | 97.0 | 87.3 | 42.9 | 98.0 | 96.7 | 2.0 | 91.2 |
| 20m (19.67M) | 95.0 | 90.4 | 97.4 | 96.7 | 98.5 | 85.5 | 57.1 | 98.0 | 97.7 | 1.5 | 95.0 |

## TinyLM-Bench 16 cases (exact match %)

| model | exact_rate | no_action_precision | critical_error_rate |
|---|---:|---:|---:|
| rule baseline | 100.0 | 100.0 | 0.0 |
| Needle 2 official | 18.8 | 33.3 | 50.0 |
| FunctionGemma 270M | 37.5 | 100.0 | 50.0 |
| MimiModel C | 6.2 | 100.0 | 68.8 |
| 3m (3.15M) | 87.5 | 100.0 | 6.2 |
| 3m-s1 (3.15M) | 87.5 | 100.0 | 6.2 |
| 5m (5.05M) | 81.2 | 100.0 | 12.5 |
| 5m-s1 (5.05M) | 68.8 | 100.0 | 12.5 |
| 20m (19.67M) | 81.2 | 100.0 | 6.2 |
