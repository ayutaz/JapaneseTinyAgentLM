# INT8 KV cache (v0.5.1 3M INT4)

The C runtime built with `-DJTLM_KV_INT8=1` (firmware: `CONFIG_JTLM_KV_INT8=y`) keeps the KV
cache in int8 with one f32 scale per position and KV head (max|x| / 127, round half to even).
The PyTorch reference is `jtalm.model.transformer.set_kv_int8`. The default build keeps the f32
cache; its outputs did not change (4,794 prompts, byte-identical with `double` and `float`
accumulators).

Accuracy (`suite_pytorch.md`, `jtalm.model.eval_suite --kv-int8`, INT4 checkpoint, grammar,
gate 0.86808): every set has the same exact / requests exact / false actions / critical as the
f32 cache (`../suite_3m/suite.md`). Over all 4,794 prompts the gated output is the same for every
prompt; the output before the gate differs on 2 prompts, both gated to `[]`. min_prob moves by up
to 0.019.

C against PyTorch (`parity.json`, `jtalm.model.parity --kv-int8`, v0 eval 1,189 prompts, both
with the INT8 cache): token sequences 1,189 / 1,189 for FP32 and INT4 weights, with and without
the grammar. min_prob differs by up to 4.2e-3 (f32 cache: about 1e-5): a key or value that lies
near a rounding boundary can get a different int8 code from a tiny difference, so a gate decision
very close to the threshold can flip between C and PyTorch.

Device (`device_eval300.summary.json`, `jtalm_action` with `CONFIG_JTLM_KV_INT8=y`, first 300
prompts of v0 eval, `firmware/tools/lm_serial.py`):

| | f32 cache (`../device/`) | INT8 cache |
|---|---:|---:|
| KV cache (PSRAM) | 458,752 B | 129,024 B |
| rest of the state (internal SRAM) | 125,952 B | 134,144 B |
| internal free after the first request | 99,395 B | 91,187 B |
| latency median / p90 | 1,276 / 1,860 ms | 1,306 / 1,912 ms |
| decode / prefill per token | 105 / 46 ms | 107 / 48 ms |
| outputs equal to the host C runtime (same build options) | 300 / 300 | 300 / 300 |
| outputs equal to PyTorch (same KV cache) | 300 / 300 | 300 / 300 |

The INT8 cache saves 330 KB of PSRAM at about 2% more latency, and needs 8 KB more internal SRAM
(the keys and values of the tokens being run, before quantization). For the 3M Action LM the
PSRAM is not short, so the release keeps the f32 cache.
