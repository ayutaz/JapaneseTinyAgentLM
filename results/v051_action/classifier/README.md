# Small classifier baseline (v0.5.1 data)

`jtalm.model.classifier`: character 1- to 3-grams of the NFKC-normalized, lowercased prompt,
hashed into 65,536 embeddings of 40 values, averaged, one linear layer; 2,627,467 parameters
(f32, PC only, not quantized or run on the device). Each class is a whole canonical call
sequence seen in the training data (147 classes, `[]` included), so the output is always valid
but no unseen combination can be produced. Every expected output of the evaluation sets occurs
in the training data, so this does not cost it anything here. Trained on the same data as the
LM (v0.5.1 train, 66,809 rows), 10 epochs, epoch chosen on validation exact; the confidence gate
(largest softmax probability) is chosen on validation with the LM's rule (thresholds 0.556 to
0.693). Seeds 0 to 4.

Files: `suite_seed0.md` (seed 0, all sets), `seeds.md` (5 seeds), `diff_lm_seed0.md` (paired
bootstrap, LM seed 0 = A, classifier seed 0 = B), `paraphrase_seeds.md`
(jtalm.eval.consistency), `runs.json` (gates, configuration, training logs).

Five seeds each, mean ± SD (LM: `../seeds_3m.md`, 3M INT4 + grammar + gate):

| | LM: requests exact | classifier: requests exact | LM: false actions | classifier: false actions |
|---|---:|---:|---:|---:|
| human v1 | 85.2 ± 6.4 | **91.0 ± 1.4** | **0.0 ± 0.0** | 0.3 ± 0.1 |
| v0 eval (LLM) | 88.1 ± 1.2 | 87.8 ± 0.7 | **0.4 ± 0.2** | 1.2 ± 0.6 |
| v2/correction | **85.5 ± 3.4** | 80.9 ± 4.7 | — | — |
| v2/question_forms | 91.9 ± 2.9 | **97.6 ± 0.4** | — | — |
| v2/orthography | 81.5 ± 0.8 | 82.3 ± 1.2 | 0.0 ± 0.0 | 0.0 ± 0.0 |
| v2/unexecutable | — | — | **0.3 ± 0.3** | 2.5 ± 0.8 |
| v2/english | 5.8 ± 2.9 | 16.3 ± 1.2 | **5.0 ± 6.5** | 16.9 ± 6.8 |

- On requests the classifier is as accurate as the LM or better (human-written requests 91.0%
  against 85.2%, with a much smaller seed spread; question forms +5.7 points).
- The LM moves by mistake less often: the classifier's false actions are higher on most sets
  with non-requests (v0 eval 1.2% against 0.4%, unexecutable 2.5% against 0.3%, human v1 0.3%
  against 0.0%); v2/numbers is the exception (1.0% against 1.2%).
- The LM is better at corrections ("A ではなく B"), where the order of words matters.
