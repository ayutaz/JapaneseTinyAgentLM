## Evaluation set (1189 cases, exact match %)

| model | exact_rate | single | multi_action | negation | no_action | correction | en | no_action_precision | no_action_recall | critical_error_rate | pair_accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule baseline | 76.4 | 60.9 | 46.9 | 88.1 | 99.1 | 76.4 | 77.1 | 79.8 | 94.2 | 2.9 | 83.8 |
| 3m-f025 (3.15M) | 75.9 | 45.7 | 64.1 | 97.4 | 98.8 | 54.5 | 54.3 | 77.3 | 98.2 | 2.5 | 40.0 |
| 3m-f025-s1 (3.15M) | 73.3 | 43.3 | 57.3 | 94.4 | 97.6 | 58.2 | 54.3 | 78.6 | 96.2 | 3.0 | 45.0 |
| 3m-f050 (3.15M) | 81.1 | 60.0 | 72.4 | 94.1 | 98.2 | 70.9 | 54.3 | 82.9 | 96.4 | 3.9 | 51.2 |
| 3m-f050-s1 (3.15M) | 84.0 | 64.2 | 81.8 | 96.7 | 95.8 | 78.2 | 54.3 | 84.8 | 96.2 | 3.2 | 60.0 |
| 3m-f100-s1 (3.15M) | 83.3 | 57.3 | 81.8 | 98.5 | 98.5 | 80.0 | 54.3 | 81.4 | 98.5 | 1.7 | 46.2 |

## TinyLM-Bench 16 cases (exact match %)

| model | exact_rate | no_action_precision | critical_error_rate |
|---|---:|---:|---:|
| rule baseline | 100.0 | 100.0 | 0.0 |
| Needle 2 official | 18.8 | 33.3 | 50.0 |
| FunctionGemma 270M | 37.5 | 100.0 | 50.0 |
| MimiModel C | 6.2 | 100.0 | 68.8 |
| 3m-f025 (3.15M) | 62.5 | 54.5 | 0.0 |
| 3m-f025-s1 (3.15M) | 62.5 | 54.5 | 0.0 |
| 3m-f050 (3.15M) | 68.8 | 54.5 | 0.0 |
| 3m-f050-s1 (3.15M) | 68.8 | 54.5 | 0.0 |
| 3m-f100-s1 (3.15M) | 68.8 | 54.5 | 0.0 |
