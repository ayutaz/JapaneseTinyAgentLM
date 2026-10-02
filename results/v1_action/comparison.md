# Action schema v1: 3M x5 seeds on data v1.0 (INT4 g64 + grammar + gate)

Checkpoints: `runs/vast/train_action_v1-20261002T133903Z/artifacts/v1/3m-s{0..4}/best.pt` (job `train_action_v1`, RTX 3090, 0.426 h, ~$0.091; see run.json), quantized locally to INT4 group 64 (`best_q4_g64.pt`). Decoding: grammar + confidence gate; the gate threshold is chosen per seed on `datasets/action/v1.0/val.jsonl` only (never on an evaluation set). Evaluated on CPU with `jtalm.model.eval_suite`; per-seed tables in `suite_3m-s{N}/suite.md`. Mean ± sd is over the 5 seeds' rates (as `jtalm.eval.bootstrap seeds`); seed 0 intervals are 95% bootstrap (2,000 resamples, as `jtalm.eval.bootstrap ci`). Per-case predictions stay local (`runs/local/v1_action/`, not committed, as for v0.5.1).

Gate thresholds (seed 0..4): 0.885, 0.908, 0.862, 0.940, 0.904; val exact gated: 97.8, 97.7, 97.6, 97.7, 97.6

## Completion criteria (spec section 2)

| # | criterion | target | seed 0 | mean ± sd (5 seeds) | seeds passing | verdict (seed 0) |
|---|---|---|---|---|---|---|
| 1 | user's 4 sentences exact | 4/4 | 4/4 | 4.0/4 | 5/5 | pass |
| 2a | Stack-chan v1 exact | ≥ 90% | 92.9 [88.6, 96.4] | 94.4 ± 0.9 | 5/5 | pass |
| 2b | Stack-chan v1 false actions on `[]` (n=65) | 0 | 0 | 0.0 (per seed 0, 0, 0, 0, 0) | 5/5 | pass |
| 3 | human v1 negatives false-action rate (n=1092) | ≤ 0.5% | 0.3 [0.0, 0.6] | 0.1 ± 0.1 | 5/5 | pass |
| 4 | human v1 positives exact (n=65) | not below v0.5.1 85.2 ± 6.4 | 93.8 [87.7, 98.5] | 91.7 ± 2.1 | 5/5 (≥ 85.2) | pass (mean pass) |
| 5 | device (INT4, ESP32-S3) = PyTorch | match | — | — | — | Task 14 / firmware F4 |
| 6 | device median latency | ≤ 2 s | — | — | — | firmware F4 |

Review Focus (details below): numeric gated rate, seed 0 / mean ± sd — Stack-chan v1 9.1 / 7.3 ± 4.1, eval v3 3.5 / 3.3 ± 0.5; eval v3 single look exact 97.4 ± 1.3 vs turn 84.3 ± 2.0.

Notes:

- Criterion 4 compares against v0.5.1's 85.2 ± 6.4 measured on the v0 labels of human v1 (62 positives); under the v1 relabel the set has 65 positives, so the sets differ slightly.
- Stack-chan v1 has no `turn` case; eval v3 has no single-action level/by cases and no out-of-range case (see Review Focus).
- Training data covers 40 distinct `degrees` values and 18 distinct `level` values; unseen values are not measured by any evaluation set (sc-048 「18度」 → raw 180, gated).

## 1. The user's 4 sentences

| id | prompt | expected | seed 0 output | seed 0 min prob | exact per seed (0..4) |
|---|---|---|---|---|---|
| sc-u1 | LEDライトの色を青にして | `[{"name":"set_led","arguments":{"color":"blue"}}]` | `[{"name":"set_led","arguments":{"color":"blue"}}]` | 1.000 | Y Y Y Y Y |
| sc-u2 | 音声の音量を50にして | `[{"name":"set_volume","arguments":{"level":50}}]` | `[{"name":"set_volume","arguments":{"level":50}}]` | 1.000 | Y Y Y Y Y |
| sc-u3 | 頭を90度上に向けて | `[{"name":"look","arguments":{"direction":"up","degrees":90}}]` | `[{"name":"look","arguments":{"direction":"up","degrees":90}}]` | 1.000 | Y Y Y Y Y |
| sc-u4 | 顔を右に45度向いて | `[{"name":"look","arguments":{"direction":"right","degrees":45}}]` | `[{"name":"look","arguments":{"direction":"right","degrees":45}}]` | 1.000 | Y Y Y Y Y |

## 2. Stack-chan v1 (140 cases: 75 actions, 65 `[]`)

| breakdown | n | seed 0 | mean ± sd |
|---|---:|---:|---:|
| all | 140 | 92.9 | 94.4 ± 0.9 |
| source=verbatim | 97 | 94.8 | 94.4 ± 0.6 |
| source=user | 4 | 100.0 | 100.0 ± 0.0 |
| source=paraphrase | 39 | 87.2 | 93.8 ± 4.3 |
| expected has look | 52 | 86.5 | 92.3 ± 3.3 |
| expected has turn | 0 | — | — |
| numeric gated rate | — | 9.1 | 7.3 ± 4.1 |

The Stack-chan v1 set has no `turn` case (no relative-move sentence), so look vs turn can only be read on eval v3.

False actions on `[]` cases, seed 0: 0 of 65. Per seed: s0 none; s1 none; s2 none; s3 none; s4 none

### Every Stack-chan v1 case seed 0 gets wrong (10)

`gated` = the gate turned a non-empty output into `[]` (raw output shown). `wrong in` = how many of the 5 seeds also get it wrong.

| id | prompt | expected | seed 0 output | raw (un-gated) | min prob | gated | wrong in |
|---|---|---|---|---|---:|---|---:|
| sc-002 | 左に頭を回して。 | `[{"name":"look","arguments":{"direction":"left","amount":"normal"}}]` | `[]` | `[{"name":"look","arguments":{"direction":"left","amount":"normal"}}]` | 0.652 | yes | 1/5 |
| sc-021 | 首をかしげて | `[{"name":"set_expression","arguments":{"expression":"doubt"}}]` | `[]` | `[{"name":"look","arguments":{"direction":"down","amount":"normal"}}]` | 0.849 | yes | 5/5 |
| sc-025 | 少し大きくして | `[{"name":"adjust_volume","arguments":{"direction":"up","amount":"slight"}}]` | `[]` | `[{"name":"look","arguments":{"direction":"up","amount":"large"}}]` | 0.767 | yes | 5/5 |
| sc-048 | 頭を左に18度動かして | `[{"name":"look","arguments":{"direction":"left","degrees":18}}]` | `[]` | `[{"name":"look","arguments":{"direction":"left","degrees":180}}]` | 0.507 | yes | 5/5 |
| sc-052 | 興味津々な顔して | `[{"name":"set_expression","arguments":{"expression":"doubt"}}]` | `[{"name":"set_expression","arguments":{"expression":"surprised"}}]` | `[{"name":"set_expression","arguments":{"expression":"surprised"}}]` | 0.956 | no | 5/5 |
| sc-p-d4c660290552 | 左下方向に少し首を傾けてもらえますか。 | `[{"name":"look","arguments":{"direction":"down_left","amount":"slight"}}]` | `[]` | `[{"name":"turn","arguments":{"direction":"down_left","amount":"slight"}}]` | 0.673 | yes | 1/5 |
| sc-p-ffdbf47c2082 | ひだりうえをむく | `[{"name":"look","arguments":{"direction":"up_left","amount":"normal"}}]` | `[{"name":"look","arguments":{"direction":"left","amount":"normal"}}]` | `[{"name":"look","arguments":{"direction":"left","amount":"normal"}}]` | 0.997 | no | 2/5 |
| sc-p-5ec50c040fd7 | 左下の方へちょっとだけ首を動かしてごらん。 | `[{"name":"look","arguments":{"direction":"down_left","amount":"slight"}}]` | `[{"name":"turn","arguments":{"direction":"down_left","amount":"slight"}}]` | `[{"name":"turn","arguments":{"direction":"down_left","amount":"slight"}}]` | 1.000 | no | 5/5 |
| sc-p-c0a9f466af98 | 左上をちょっと眺める感じで動かしてみて | `[{"name":"look","arguments":{"direction":"up_left","amount":"slight"}}]` | `[]` | `[{"name":"look","arguments":{"direction":"up_left","amount":"slight"}}]` | 0.823 | yes | 1/5 |
| sc-p-a4290ee88d51 | ひだりうえをむいて | `[{"name":"look","arguments":{"direction":"up_left","amount":"normal"}}]` | `[{"name":"look","arguments":{"direction":"left","amount":"normal"}}]` | `[{"name":"look","arguments":{"direction":"left","amount":"normal"}}]` | 0.997 | no | 2/5 |

## 3–4. human v1

Negatives (n=1092): false actions per seed 3, 1, 2, 2, 0 → rate 0.1 ± 0.1%. Seed 0 (ids only; human v1 texts come from third-party corpora and are not quoted here): human-39062fdddcb0 (human:yj_ambig) → `[{"name":"look","arguments":{"direction":"up","amount":"slight"}}]`; human-3fe44f3e2396 (human:jcre3) → `[{"name":"set_volume","arguments":{"level":50}}]`; human-415740180240 (human:jcre3) → `[{"name":"set_expression","arguments":{"expression":"sad"}}]`

Positives (n=65): exact per seed 93.8, 93.8, 89.2, 90.8, 90.8 → 91.7 ± 2.1 (v0.5.1: 85.2 ± 6.4). Seed 0 errors (4):

| id (source) | expected | seed 0 output | raw | min prob |
|---|---|---|---|---:|
| human-86c1770b2c92 (human:jesc) | `[{"name":"look","arguments":{"direction":"center","amount":"normal"}}]` | `[]` | `[{"name":"look","arguments":{"direction":"down","amount":"normal"}}]` | 0.509 |
| human-657c7ccdbe1a (human:jesc) | `[{"name":"set_expression","arguments":{"expression":"happy"}}]` | `[]` | `[{"name":"set_expression","arguments":{"expression":"happy"}}]` | 0.770 |
| human-b2a162d9aa43 (human:jesc) | `[{"name":"look","arguments":{"direction":"center","amount":"normal"}}]` | `[]` | `[]` | 0.554 |
| human-76c46889282f (human:yj_ambig+relabel:v1) | `[{"name":"adjust_volume","arguments":{"direction":"up","amount":"normal"}}]` | `[]` | `[{"name":"adjust_volume","arguments":{"direction":"up","amount":"large"}}]` | 0.609 |

## Every evaluation set

Mean ± sd over 5 seeds (%). `numeric gated` = share of cases whose expected calls carry degrees/level/by that the gate turned into `[]` (raw output non-empty).

| set | n | exact | requests exact | false-action rate | numeric gated |
|---|---:|---:|---:|---:|---:|
| Stack-chan v1 | 140 | 94.4 ± 0.9 | 89.6 ± 1.7 | 0.0 ± 0.0 | 7.3 ± 4.1 |
| eval v3 (LLM) | 1816 | 95.3 ± 0.5 | 93.3 ± 0.7 | 0.3 ± 0.1 | 3.3 ± 0.5 |
| v0 eval (LLM) | 1189 | 91.9 ± 0.6 | 83.9 ± 1.0 | 0.4 ± 0.3 | — |
| human v1 | 1157 | 99.4 ± 0.1 | 91.7 ± 2.1 | 0.1 ± 0.1 | — |
| v2/amount_words | 278 | 85.8 ± 2.0 | 85.8 ± 2.0 | — | — |
| v2/center_phrasing | 223 | 94.1 ± 2.3 | 94.1 ± 2.3 | — | — |
| v2/correction | 44 | 85.9 ± 1.9 | 85.9 ± 1.9 | — | — |
| v2/english | 70 | 47.1 ± 3.4 | 6.8 ± 4.8 | 5.0 ± 5.2 | — |
| v2/fragments | 182 | 100.0 ± 0.0 | — | 0.0 ± 0.0 | — |
| v2/long_preface | 247 | 87.9 ± 1.7 | 87.9 ± 1.7 | — | — |
| v2/negation_forms | 168 | 100.0 ± 0.0 | — | 0.0 ± 0.0 | — |
| v2/numbers | 167 | 85.3 ± 2.9 | 62.5 ± 7.6 | 1.0 ± 0.0 | — |
| v2/order_words | 296 | 96.6 ± 1.1 | 96.6 ± 1.1 | — | — |
| v2/orthography | 282 | 82.9 ± 1.3 | 81.1 ± 1.4 | 0.0 ± 0.0 | — |
| v2/question_forms | 203 | 86.2 ± 0.3 | 86.2 ± 0.3 | — | — |
| v2/unexecutable | 286 | 99.1 ± 0.3 | 0.0 ± 0.0 | 0.6 ± 0.3 | — |

### bootstrap: seeds

Mean ± standard deviation over 5 runs: suite_3m-s0, suite_3m-s1, suite_3m-s2, suite_3m-s3, suite_3m-s4

| set | exact | requests exact | false actions |
|---|---|---|---|
| eval_v3_LLM | 95.3 ± 0.5 | 93.3 ± 0.7 | 0.3 ± 0.1 |
| human_v1 | 99.4 ± 0.1 | 91.7 ± 2.1 | 0.1 ± 0.1 |
| Stack-chan_v1 | 94.4 ± 0.9 | 89.6 ± 1.7 | 0.0 ± 0.0 |
| v0_eval_LLM | 91.9 ± 0.6 | 83.9 ± 1.0 | 0.4 ± 0.3 |
| v2_amount_words | 85.8 ± 2.0 | 85.8 ± 2.0 | — |
| v2_center_phrasing | 94.1 ± 2.3 | 94.1 ± 2.3 | — |
| v2_correction | 85.9 ± 1.9 | 85.9 ± 1.9 | — |
| v2_english | 47.1 ± 3.4 | 6.8 ± 4.8 | 5.0 ± 5.2 |
| v2_fragments | 100.0 ± 0.0 | — | 0.0 ± 0.0 |
| v2_long_preface | 87.9 ± 1.7 | 87.9 ± 1.7 | — |
| v2_negation_forms | 100.0 ± 0.0 | — | 0.0 ± 0.0 |
| v2_numbers | 85.3 ± 2.9 | 62.5 ± 7.6 | 1.0 ± 0.0 |
| v2_order_words | 96.6 ± 1.1 | 96.6 ± 1.1 | — |
| v2_orthography | 82.9 ± 1.3 | 81.1 ± 1.4 | 0.0 ± 0.0 |
| v2_question_forms | 86.2 ± 0.3 | 86.2 ± 0.3 | — |
| v2_unexecutable | 99.1 ± 0.3 | 0.0 ± 0.0 | 0.6 ± 0.3 |

### bootstrap: seed 0 intervals

95% bootstrap intervals (2000 resamples) for suite_3m-s0

| set | exact | requests exact | false actions |
|---|---|---|---|
| eval_v3_LLM | 95.2 [94.2, 96.1] | 93.2 [91.8, 94.5] | 0.2 [0.0, 0.5] |
| human_v1 | 99.4 [98.9, 99.7] | 93.8 [87.7, 98.5] | 0.3 [0.0, 0.6] |
| Stack-chan_v1 | 92.9 [88.6, 97.1] | 86.7 [77.3, 93.3] | 0.0 [0.0, 0.0] |
| v0_eval_LLM | 90.9 [89.3, 92.4] | 82.4 [79.1, 85.4] | 0.8 [0.2, 1.5] |
| v2_amount_words | 84.9 [80.6, 88.8] | 84.9 [80.6, 88.8] | — |
| v2_center_phrasing | 94.6 [91.5, 97.3] | 94.6 [91.5, 97.3] | — |
| v2_correction | 84.1 [72.7, 93.2] | 84.1 [72.7, 93.2] | — |
| v2_english | 48.6 [37.1, 61.4] | 10.5 [2.6, 23.7] | 6.2 [0.0, 15.6] |
| v2_fragments | 100.0 [100.0, 100.0] | — | 0.0 [0.0, 0.0] |
| v2_long_preface | 87.4 [83.4, 91.5] | 87.4 [83.4, 91.5] | — |
| v2_negation_forms | 100.0 [100.0, 100.0] | — | 0.0 [0.0, 0.0] |
| v2_numbers | 87.4 [82.0, 92.2] | 68.3 [55.6, 79.4] | 1.0 [0.0, 2.9] |
| v2_order_words | 94.6 [91.9, 97.0] | 94.6 [91.9, 97.0] | — |
| v2_orthography | 84.0 [79.4, 88.3] | 82.4 [78.0, 87.1] | 0.0 [0.0, 0.0] |
| v2_question_forms | 86.2 [81.8, 90.6] | 86.2 [81.3, 90.6] | — |
| v2_unexecutable | 99.3 [98.3, 100.0] | 0.0 [0.0, 0.0] | 0.4 [0.0, 1.1] |

## Review Focus (eval v3, LLM-written, 1,816 cases)

Spec ids and the pre-normalization text come from the raw eval rows (`runs/vast/gen_action_v1b-20261002T113414Z/artifacts/gen_action_v1/raw1_eval/eval_raw.jsonl`, joined on the case id; 0 cases unmatched). Eval prompts are NFKC-normalized (and the tokenizer applies nmt_nfkc), so full-width digits reach the model as ASCII digits; the notation below is taken from the raw text. Groups are cases whose expected calls carry degrees/level/by (any category) unless stated. `gated` = share turned into `[]` by the gate.

**Coverage gap in eval v3:** its `single` quota (1,600 raw rows) was filled entirely by the look/turn specs (1,072 + 528), so eval v3 has no single-action nod/shake/bow/expression/LED/volume/brightness cases from the v1 specs and **no `v1.single.out_of_range.*` cases**; `set_volume`/`set_brightness` levels appear only inside multi/correction/negation rows (66 calls), `by` in 2 calls. Full-width digits survive in only 16 raw eval rows, and the writer (llm-jp) mostly ignored the kanji hint (s1), so notation evidence in eval v3 is nearly all ASCII digits + 度. The supplementary validation section below fills part of the gap.

### RF1 numeric notation (from the prompt text)

| group | n | exact | gated |
|---|---:|---:|---:|
| ASCII digits | 930 | 94.2 ± 0.3 | 3.3 ± 0.6 |
| full-width digits | 8 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| hiragana / words (no digit or kanji) | 3 | 26.7 ± 14.9 | 26.7 ± 27.9 |
| kanji numerals + 度/% | 24 | 100.0 ± 0.0 | 0.0 ± 0.0 |

### RF1 numeric notation (from the spec's style hint)

s0 ASCII, s1 kanji, s2 full-width, s3 % (levels only); the writer did not always follow it.

| group | n | exact | gated |
|---|---:|---:|---:|
| ASCII (s0) | 262 | 92.0 ± 1.3 | 4.5 ± 1.9 |
| full-width (s2) | 253 | 96.5 ± 0.3 | 1.9 ± 0.7 |
| kanji (s1) | 245 | 95.1 ± 0.6 | 2.2 ± 0.6 |

### RF1 unit in the prompt

| group | n | exact | gated |
|---|---:|---:|---:|
| none | 51 | 91.8 ± 2.6 | 4.3 ± 2.9 |
| 度 | 914 | 94.4 ± 0.3 | 3.2 ± 0.6 |

### numeric cases by tool and argument

| group | n | exact | gated |
|---|---:|---:|---:|
| adjust_brightness.by (in correction) | 2 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| look.degrees (in multi_action) | 158 | 93.2 ± 0.9 | 5.1 ± 1.0 |
| look.degrees (single) | 546 | 97.7 ± 1.2 | 1.5 ± 0.8 |
| set_brightness.level (in correction) | 8 | 97.5 ± 5.6 | 2.5 ± 5.6 |
| set_brightness.level (in multi_action) | 23 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| set_volume.level (in correction) | 5 | 76.0 ± 16.7 | 12.0 ± 17.9 |
| set_volume.level (in multi_action) | 4 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| turn.degrees (in correction) | 5 | 64.0 ± 8.9 | 12.0 ± 11.0 |
| turn.degrees (single) | 214 | 86.4 ± 2.2 | 6.4 ± 1.3 |

### RF2 numeric gated rate per set

See the `numeric gated` column above.

### Stack-chan v1 numeric cases by notation

| group | n | exact | gated |
|---|---:|---:|---:|
| ASCII digits | 8 | 85.0 ± 5.6 | 10.0 ± 5.6 |
| hiragana / words (no digit or kanji) | 3 | 100.0 ± 0.0 | 0.0 ± 0.0 |

### Stack-chan v1 numeric cases by tool and argument

| group | n | exact | gated |
|---|---:|---:|---:|
| look.degrees (single) | 6 | 80.0 ± 7.5 | 13.3 ± 7.5 |
| set_volume.level (single) | 5 | 100.0 ± 0.0 | 0.0 ± 0.0 |

Stack-chan v1 numeric cases, seed 0: 音量を 80% に設定して。 ok; 音量を半分にして ok; 消音して ok; 静かにして ok; 頭を左に18度動かして → `[]`; 音声の音量を50にして ok; 頭を90度上に向けて ok; 顔を右に45度向いて ok; ロボットちゃん、左に15度向くことはできるかな? ok; 左に15度、こちらを向いていただけますか? ok; ロボット、左10度くらいをむいて。 ok

### RF4 out-of-range

eval v3: no `v1.single.out_of_range.*` case (see coverage gap). Validation has 2 (below).

### RF5 look vs turn (single-action cases)

| group | n | exact | gated |
|---|---:|---:|---:|
| look (single) | 603 | 97.4 ± 1.3 | 1.8 ± 0.9 |
| turn (single) | 274 | 84.3 ± 2.0 | 8.0 ± 1.6 |

### RF5 look vs turn (any case containing the tool)

| group | n | exact | gated |
|---|---:|---:|---:|
| look (any) | 840 | 96.3 ± 1.1 | 2.4 ± 0.6 |
| look+turn | 5 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| turn (any) | 347 | 86.4 ± 1.9 | 7.1 ± 1.4 |

RF5 look/turn swaps in single-action cases (output uses the other tool), per seed 0..4: eval v3 look→turn [6, 2, 3, 2, 1] of 603, turn→look [14, 18, 21, 17, 31] of 274; Stack-chan look→turn [1, 1, 1, 1, 1] of 52, turn→look [0, 0, 0, 0, 0] of 0.

## Supplementary: validation cases with numeric answers (not held out from model selection)

`datasets/action/v1.0/val.jsonl` cases whose expected calls carry degrees/level/by, joined to their spec ids via the raw writer rows (n=736, including the 2 out-of-range specs). Validation chose the best epoch and the gate threshold, so these rates are optimistic; they are reported only because eval v3 lacks these cases. Same INT4 models, grammar and per-seed gate.

### val: notation (from the raw prompt text)

| group | n | exact | gated |
|---|---:|---:|---:|
| ASCII digits | 548 | 98.1 ± 0.5 | 1.6 ± 0.4 |
| full-width digits | 62 | 99.0 ± 0.9 | 0.6 ± 0.9 |
| hiragana / words (no digit or kanji) | 2 | 50.0 ± 0.0 | 40.0 ± 22.4 |
| kanji numerals (other) | 29 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| kanji numerals + 度/% | 95 | 96.0 ± 0.9 | 2.9 ± 1.2 |

### val: notation (spec style hint, single-action)

| group | n | exact | gated |
|---|---:|---:|---:|
| % (s3) | 16 | 93.8 ± 4.4 | 3.8 ± 3.4 |
| ASCII (s0) | 176 | 98.3 ± 0.8 | 1.7 ± 0.8 |
| full-width (s2) | 115 | 98.4 ± 0.7 | 0.5 ± 0.8 |
| kanji (s1) | 108 | 96.5 ± 1.2 | 2.6 ± 1.8 |
| no style hint | 57 | 93.3 ± 2.6 | 5.6 ± 2.9 |

### val: unit in the prompt

| group | n | exact | gated |
|---|---:|---:|---:|
| % | 14 | 88.6 ± 6.4 | 7.1 ± 5.1 |
| none | 222 | 98.0 ± 1.0 | 1.8 ± 1.1 |
| ° | 7 | 97.1 ± 6.4 | 2.9 ± 6.4 |
| 度 | 493 | 98.0 ± 0.4 | 1.5 ± 0.4 |

### val: numeric cases by tool and argument

| group | n | exact | gated |
|---|---:|---:|---:|
| adjust_brightness.by (in correction) | 2 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| adjust_brightness.by (single) | 24 | 98.3 ± 2.3 | 1.7 ± 2.3 |
| adjust_volume.by (single) | 28 | 93.6 ± 4.7 | 5.7 ± 5.4 |
| look.degrees (in correction) | 7 | 82.9 ± 12.0 | 14.3 ± 10.1 |
| look.degrees (in multi_action) | 116 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| look.degrees (single) | 256 | 99.1 ± 0.7 | 0.9 ± 0.8 |
| set_brightness.level (in multi_action) | 39 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| set_brightness.level (single) | 21 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| set_volume.level (in correction) | 7 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| set_volume.level (in multi_action) | 88 | 98.4 ± 0.6 | 1.6 ± 0.6 |
| set_volume.level (single) | 33 | 91.5 ± 2.5 | 6.1 ± 2.1 |
| turn.degrees (in correction) | 5 | 100.0 ± 0.0 | 0.0 ± 0.0 |
| turn.degrees (single) | 110 | 94.5 ± 1.4 | 3.6 ± 1.7 |

val out-of-range specs (expected level 100), outputs for seeds 0..4:

- 音量を210%に設定してください、よろしくお願いします。 → expected `[{"name":"set_volume","arguments":{"level":100}}]`; `[{"name":"set_volume","arguments":{"level":100}}]`, `[]`, `[]`, `[{"name":"set_volume","arguments":{"level":100}}]`, `[{"name":"set_volume","arguments":{"level":20}}]`
- 画面の明るさを150%にしてほしい。 → expected `[{"name":"set_brightness","arguments":{"level":100}}]`; `[{"name":"set_brightness","arguments":{"level":100}}]`, `[{"name":"set_brightness","arguments":{"level":100}}]`, `[{"name":"set_brightness","arguments":{"level":100}}]`, `[{"name":"set_brightness","arguments":{"level":100}}]`, `[{"name":"set_brightness","arguments":{"level":100}}]`

