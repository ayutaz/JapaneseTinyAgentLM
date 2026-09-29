## Evaluation set (1189 cases, exact match %)

| model | exact_rate | single | multi_action | negation | no_action | correction | en | no_action_precision | no_action_recall | critical_error_rate | pair_accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule baseline | 76.4 | 60.9 | 46.9 | 88.1 | 99.1 | 76.4 | 77.1 | 79.8 | 94.2 | 2.9 | 83.8 |
| 3m (3.15M) | 91.3 | 85.7 | 90.6 | 93.0 | 95.8 | 90.9 | 40.0 | 95.3 | 94.6 | 3.0 | 85.0 |
| 3m-s1 (3.15M) | 92.1 | 86.3 | 91.1 | 91.9 | 99.1 | 89.1 | 57.1 | 95.6 | 95.9 | 2.3 | 85.0 |
| 5m (5.05M) | 89.8 | 82.1 | 84.9 | 94.4 | 98.5 | 78.2 | 51.4 | 93.6 | 96.7 | 2.3 | 83.8 |
| 5m-s1 (5.05M) | 89.4 | 83.0 | 88.0 | 90.0 | 97.9 | 78.2 | 40.0 | 95.5 | 94.4 | 3.4 | 75.0 |
| 20m (19.67M) | 90.7 | 84.8 | 87.0 | 92.6 | 98.2 | 85.5 | 48.6 | 94.6 | 95.7 | 2.6 | 85.0 |

## TinyLM-Bench 16 cases (exact match %)

| model | exact_rate | no_action_precision | critical_error_rate |
|---|---:|---:|---:|
| rule baseline | 100.0 | 100.0 | 0.0 |
| Needle 2 official | 18.8 | 33.3 | 50.0 |
| FunctionGemma 270M | 37.5 | 100.0 | 50.0 |
| MimiModel C | 6.2 | 100.0 | 68.8 |
| 3m (3.15M) | 75.0 | 100.0 | 6.2 |
| 3m-s1 (3.15M) | 68.8 | 83.3 | 6.2 |
| 5m (5.05M) | 68.8 | 100.0 | 6.2 |
| 5m-s1 (5.05M) | 68.8 | 100.0 | 12.5 |
| 20m (19.67M) | 68.8 | 83.3 | 6.2 |
