# v1.1 3M INT4 on the device (M5Stack Stack-chan K151 / CoreS3)

2026-10-04. The release image of the `jtalm_action` firmware, rebuilt with the v1.1 gate
(`CONFIG_JTALM_GATE_PPM=836730`, `firmware/jtalm_action/build_release`) and the v1.1 model
(seed 1, `3m-s1_q4_g64.jtlm`, 1,970,720 B) at `0x200000`, written at `0x0` as one file
(`stackchan_k151_jtalm_action.bin`). The firmware source is the same as v1.0's; only the gate
default and the weights changed. Servo output was off (plans run as a dry run).

## Cases

`cases400.jsonl`: the 300 prompts of the v1.0 run (`../../v1_action/device/cases300.jsonl`: all of
Stack-chan v1, 100 of eval v3, 60 of human v1) and 100 prompts of the LED v1.1 set
(`random.Random(0).sample`, kept in file order). The PyTorch reference is
`jtalm.model.decode.greedy` with the v1 grammar on `3m-s1/best_q4_g64.pt`.

    uv run --no-project --with pyserial python firmware/tools/lm_serial.py --port COM3 --reset --act \
        --cases cases400.jsonl --limit 400 --ref <PyTorch ids/output/min_prob> --out parity400.jsonl
    uv run python firmware/tools/dispatch_check.py --results parity400.jsonl --log parity400.log

## Results

- **Outputs: 400 / 400.** Generated ids, the output before the gate and the output after the gate
  all equal PyTorch (23 gated, none within 1e-4 of the threshold). `parity400.summary.json`.
- **Plans: 400 / 400** equal `jtalm.action.mapping.plan_v1` (204 non-empty plans with 237
  calls); no `fault`, no `error`, `n_problems` 0, face CRCs stable, largest plan overrun 63 ms.
  `parity400.dispatch.json`.
- **Latency** (`total_ms`, tokenize to detokenize): median 1,069 ms, p90 1,746 ms, max 2,753 ms;
  prefill 45.8 ms/token, decode 105.2 ms/token; 14.2 prompt / 5.4 generated tokens on average.
  The v1.0 run on its 300 cases had a median of 1,042 ms; the per-token times are the same.
- The 1,500-prompt long run was done with v1.0 only (`../../v1_action/device/`); v1.1 uses the
  same firmware with different weights.
- A visual check of the LED colours on the device is recorded below once it is done.
