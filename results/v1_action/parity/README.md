# v1 parity: C runtime (double and float accumulation) and WebAssembly vs PyTorch INT4

Task 14. Model: seed 0 of the 3M x5 seeds (`runs/vast/train_action_v1-20261002T133903Z/artifacts/v1/3m-s0/best.pt`), INT4 weight-only (group 64, fp16 scales), exported by `jtalm.model.export`, tokenizer `action_v1_sp2048`. PyTorch side: `jtalm.model.decode.greedy` on the model read back from the exported `.jtlm` (the dequantized weights), with and without the v1 grammar.

## Result

**Every case matches in every build: 11426 cases x 2 builds x 2 modes (plain, grammar), 0 mismatches.** Token sequences and output strings are identical to PyTorch INT4, and the WebAssembly build is identical to the host float build in output and in `min_prob` (bit-exact).

- Builds: host `double` accumulation (`make -C runtime/host`, gcc 13.3 in `espressif/idf:v5.5.5`), host `float` accumulation (`CFLAGS="-O2 -DJTLM_ACC=float"`, the setting used on the device), both with `-ffp-contract=off`.
- Tokenization (`jtalm --tokenize` vs `sentencepiece`) was also checked on every prompt of each set: all match (column "tok").
- `datasets/action/relabel_v1/overrides.jsonl` (13 rows) is a list of label overrides without prompts, so it is not a case set and was skipped. Sets under `relabel_v1` are the relabeled older sets (human_v1, v0_eval, the eval_v2 sets).
- The `jtalm.eval` exact rate of the C output equals PyTorch's in every row (`exact_c` and `exact_python` in the JSON).

## C runtime vs PyTorch INT4 (grammar on)

| set | n | tok | double: tokens | double: outputs | double: max abs min_prob diff | float: tokens | float: outputs | float: max abs min_prob diff |
|---|---|---|---|---|---|---|---|---|
| stackchan_v1 | 140 | 140/140 | 140/140 | 140/140 | 2.50e-06 | 140/140 | 140/140 | 1.78e-05 |
| eval_v3 | 1816 | 1816/1816 | 1816/1816 | 1816/1816 | 4.47e-06 | 1816/1816 | 1816/1816 | 2.81e-05 |
| val_v1.0 | 4678 | 4678/4678 | 4678/4678 | 4678/4678 | 4.17e-06 | 4678/4678 | 4678/4678 | 2.60e-05 |
| relabel_eval_v2_amount_words | 278 | 278/278 | 278/278 | 278/278 | 2.09e-06 | 278/278 | 278/278 | 1.13e-05 |
| relabel_eval_v2_center_phrasing | 223 | 223/223 | 223/223 | 223/223 | 2.74e-06 | 223/223 | 223/223 | 1.52e-05 |
| relabel_eval_v2_correction | 44 | 44/44 | 44/44 | 44/44 | 3.22e-06 | 44/44 | 44/44 | 1.91e-05 |
| relabel_eval_v2_english | 70 | 70/70 | 70/70 | 70/70 | 1.85e-06 | 70/70 | 70/70 | 8.29e-06 |
| relabel_eval_v2_fragments | 182 | 182/182 | 182/182 | 182/182 | 2.50e-06 | 182/182 | 182/182 | 6.32e-06 |
| relabel_eval_v2_long_preface | 247 | 247/247 | 247/247 | 247/247 | 1.85e-06 | 247/247 | 247/247 | 1.14e-05 |
| relabel_eval_v2_negation_forms | 168 | 168/168 | 168/168 | 168/168 | 1.55e-06 | 168/168 | 168/168 | 7.51e-06 |
| relabel_eval_v2_numbers | 167 | 167/167 | 167/167 | 167/167 | 2.09e-06 | 167/167 | 167/167 | 1.00e-05 |
| relabel_eval_v2_order_words | 296 | 296/296 | 296/296 | 296/296 | 2.62e-06 | 296/296 | 296/296 | 2.23e-05 |
| relabel_eval_v2_orthography | 282 | 282/282 | 282/282 | 282/282 | 2.03e-06 | 282/282 | 282/282 | 1.11e-05 |
| relabel_eval_v2_question_forms | 203 | 203/203 | 203/203 | 203/203 | 1.19e-06 | 203/203 | 203/203 | 7.93e-06 |
| relabel_eval_v2_unexecutable | 286 | 286/286 | 286/286 | 286/286 | 1.55e-06 | 286/286 | 286/286 | 1.29e-05 |
| relabel_human_v1 | 1157 | 1157/1157 | 1157/1157 | 1157/1157 | 2.21e-06 | 1157/1157 | 1157/1157 | 1.01e-05 |
| relabel_v0_eval | 1189 | 1189/1189 | 1189/1189 | 1189/1189 | 2.92e-06 | 1189/1189 | 1189/1189 | 1.54e-05 |
| **total** | 11426 | all | 11426/11426 | 11426/11426 | 4.47e-06 | 11426/11426 | 11426/11426 | 2.81e-05 |

Without the grammar (`plain`) the numbers are the same: tokens and outputs 11426/11426 in both builds; max min_prob diff 4.47e-06 (double) and 2.81e-05 (float). Per-set numbers for both modes are in `double/<set>.json` and `float/<set>.json` (`generation.int4.{plain,grammar}`, with `first_logits` max abs diff as well).

The min_prob difference is the PyTorch float32-vs-C accumulation difference in the probability of the least likely generated token: about 1e-6 for double accumulation and about 1e-5 for float accumulation. It never changed a greedy choice in these sets.

## Mismatches

None, so there are no competing-token probabilities to report (the parity module would list the Python probabilities of both tokens at the first differing step in `mismatches`; every list is empty).

## WebAssembly vs host float

`runtime/web/jtalm.js` rebuilt with `emscripten/emsdk:3.1.62` (`runtime/web/build.sh`), then `node runtime/web/parity.cjs <INT4 .jtlm> <prompts> <host float output>` per set (same prompts, host output from `build/v1f/jtalm -m ... --grammar`). `sameOutput` compares the raw (pre-gate) action list; `sameProb` compares `min_prob` with `===`.

| set | prompts | sameOutput | sameProb |
|---|---|---|---|
| stackchan_v1 | 140 | 140 | 140 |
| eval_v3 | 1816 | 1816 | 1816 |
| val_v1.0 | 4678 | 4678 | 4678 |
| relabel_eval_v2_amount_words | 278 | 278 | 278 |
| relabel_eval_v2_center_phrasing | 223 | 223 | 223 |
| relabel_eval_v2_correction | 44 | 44 | 44 |
| relabel_eval_v2_english | 70 | 70 | 70 |
| relabel_eval_v2_fragments | 182 | 182 | 182 |
| relabel_eval_v2_long_preface | 247 | 247 | 247 |
| relabel_eval_v2_negation_forms | 168 | 168 | 168 |
| relabel_eval_v2_numbers | 167 | 167 | 167 |
| relabel_eval_v2_order_words | 296 | 296 | 296 |
| relabel_eval_v2_orthography | 282 | 282 | 282 |
| relabel_eval_v2_question_forms | 203 | 203 | 203 |
| relabel_eval_v2_unexecutable | 286 | 286 | 286 |
| relabel_human_v1 | 1157 | 1157 | 1157 |
| relabel_v0_eval | 1189 | 1189 | 1189 |
| **total** | 11426 | 11426 | 11426 |

Raw log: `web_vs_host_float.log`. Node.js 22-24 speed is about 50 ms per prompt.

## Notes

- `runtime/web/jtalm.js` is listed in `.gitignore` (it is a build product, never tracked), so it is rebuilt but not committed.
- The same `.jtlm` file was used for the host and the web runs: `3m-s0_q4_g64.jtlm` exported from the checkpoint above.
