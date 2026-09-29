## Evaluation set (1189 cases, exact match %)

| model | exact_rate | single | multi_action | negation | no_action | correction | en | no_action_precision | no_action_recall | critical_error_rate | pair_accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule baseline | 76.4 | 60.9 | 46.9 | 88.1 | 99.1 | 76.4 | 77.1 | 79.8 | 94.2 | 2.9 | 83.8 |
| 3m (3.15M) | 84.4 | 62.1 | 79.7 | 98.5 | 99.1 | 76.4 | 54.3 | 86.1 | 98.8 | 2.6 | 58.8 |
| 5m (5.05M) | 79.6 | 54.9 | 68.2 | 98.1 | 98.5 | 61.8 | 54.3 | 79.5 | 98.4 | 2.6 | 40.0 |
| 20m (19.67M) | 83.9 | 63.0 | 77.6 | 97.0 | 99.1 | 74.5 | 54.3 | 83.2 | 98.2 | 1.4 | 52.5 |
| 5m-s1 (5.05M) | 82.0 | 59.1 | 73.4 | 98.9 | 99.7 | 60.0 | 54.3 | 81.9 | 99.3 | 1.8 | 51.2 |
| 5m-s2 (5.05M) | 81.3 | 55.8 | 74.5 | 98.9 | 99.4 | 63.6 | 54.3 | 81.4 | 99.2 | 2.0 | 43.8 |

## TinyLM-Bench 16 cases (exact match %)

| model | exact_rate | no_action_precision | critical_error_rate |
|---|---:|---:|---:|
| rule baseline | 100.0 | 100.0 | 0.0 |
| Needle 2 official | 18.8 | 33.3 | 50.0 |
| FunctionGemma 270M | 37.5 | 100.0 | 50.0 |
| MimiModel C | 6.2 | 100.0 | 68.8 |
| 3m (3.15M) | 62.5 | 54.5 | 6.2 |
| 5m (5.05M) | 62.5 | 54.5 | 6.2 |
| 20m (19.67M) | 62.5 | 54.5 | 0.0 |
| 5m-s1 (5.05M) | 68.8 | 54.5 | 0.0 |
| 5m-s2 (5.05M) | 68.8 | 54.5 | 0.0 |
