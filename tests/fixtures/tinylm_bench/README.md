# TinyLM-Bench fixtures

Copied on 2026-09-29 from the separate `TinyLM-Bench` workspace (not a Git repository). Used only
as test fixtures for the evaluator; never as training data.

- `action_cases.json`: `eval/action_cases.json` — 16 common Action cases (8 English, 8 Japanese).
- `action_outputs.json`: model outputs extracted from `results/action_outputs.csv`
  (`model`, `id`, `actual_json`, `exact_match`) for Needle 2 official, FunctionGemma 270M, and
  MimiModel C. The evaluator must reproduce the benchmark's strict-match counts (3 / 6 / 1 of 16).
