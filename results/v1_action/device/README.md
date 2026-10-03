# v1 3M INT4 on the device (M5Stack Stack-chan K151 / CoreS3)

Firmware Task 8 (F4), 2026-10-03. The `jtalm_action` firmware for Action schema v1 (v1 grammar,
validator and planner; faces, base LEDs, volume, brightness, settings in NVS), built as
`firmware/jtalm_action/build_release` (app SHA-256 `4a1e1f52…b35c`, 536,128 B), with the v1
model in the `model` partition at `0x200000`:

- model: seed 0 of the 3M x5 seeds,
  `runs/vast/train_action_v1-20261002T133903Z/artifacts/v1/3m-s0/best_q4_g64.pt`, INT4 (group 64,
  fp16 scales), exported as `3m-s0_q4_g64.jtlm` (1,970,720 B, SHA-256
  `e38499f7276c77ba04e3a26ed76640d3e3d6c3058b109a658fd6e53e48ef155d`; the device's `info` record
  shows `model_sha` `e38499f7276c77ba`), tokenizer `action_v1_sp2048`
- grammar on, confidence gate **0.88506** (the threshold chosen on validation,
  `../suite_3m-s0/suite.json`; the firmware's default is now `CONFIG_JTALM_GATE_PPM=885060`)
- servo output off for every run here (plans run with their timing as a dry run); display,
  dispatcher, LEDs, speaker and NVS on

## Cases

`cases300.jsonl`: all 140 prompts of the Stack-chan v1 set, plus a seeded sample
(`random.Random(0)`, kept in file order) of 100 prompts of eval v3 and 60 of human v1 (relabeled
under schema v1). The PyTorch reference is `jtalm.model.decode.greedy` with the v1 grammar on the
INT4 checkpoint above (the model `jtalm.model.eval_suite` scored); its raw output, gated output
and `min_prob` equal the suite's prediction files for all 300 prompts.

## Parity with PyTorch (`parity300.summary.json`, `parity300.dispatch.json`)

    uv run --no-project --with pyserial python firmware/tools/lm_serial.py --port COM3 --reset --act \
        --cases cases300.jsonl --limit 300 --ref <PyTorch ids/output/min_prob> --out t8_parity.jsonl
    uv run python firmware/tools/dispatch_check.py --results t8_parity.jsonl --log t8_parity.log

- **Outputs: 300 / 300.** Generated ids, the output before the gate (`raw`) and the output after
  the gate all equal PyTorch (13 gated, none within 1e-4 of the threshold).
- `min_prob`: largest difference to the model read back from the `.jtlm` 1.8e-5 (float
  accumulation, as in `../parity/`); to the checkpoint 4.9e-4, which is the fp16-scale rounding of
  the export (the read-back model and the checkpoint give the same ids on all 300).
- **Plans: 300 / 300** equal `jtalm.action.mapping.plan_v1` (all 300 outputs valid; 130 non-empty
  plans with 150 calls: look 86, turn 21, set_expression 10, nod 8, set_volume 6, adjust_volume 5,
  set_brightness 4, set_led 3, adjust_brightness 3, shake 2, bow 2; 20 outputs with two calls;
  32 plans with a clamped move). Serial log: 130 `act_done`, no aborted plan, no `fault`, no
  `error`, `n_problems` 0, face CRCs stable per expression, largest plan overrun 61 ms.

## Latency (`parity300.summary.json`, `latency.json`)

Per request on the device (`total_ms`, tokenize to detokenize):

| run | n | median | p90 | max | prefill ms/token | decode ms/token | prompt / generated tokens (mean) |
|---|---:|---:|---:|---:|---:|---:|---|
| v1, these 300 cases | 300 | 1,042 ms | 1,746 ms | 2,753 ms | 45.9 | 105.4 | 14.3 / 5.2 |
| v1, long run (5 x 300) | 1,500 | 1,047 ms | 1,745 ms | 2,754 ms | 45.9 | 105.4 | 14.3 / 5.2 |
| v0.5.1, first 300 of v0 eval (`../../v051_action/device/`) | 300 | 1,276 ms | 1,860 ms | 2,456 ms | 45.8 | 105.2 | 12.5 / 8.4 |

The v1 tokenizer writes the JSON in fewer tokens (5.2 generated tokens per reply on these cases),
so the median is lower than v0.5.1's on a different case set. At equal token counts there is no
slowdown from the speaker, the LEDs and NVS: for the v1 requests whose (prompt tokens, generated
tokens) pair also occurs in the v0.5.1 runs, the per-pair median differs by -0.1 ms on average
against v0.5.1's 300 (156 requests, 32 pairs) and by +1.1 ms (+0.11%) against v0.5.1's long run
(1,170 of the 1,500 long-run requests, 55 pairs). The prefill and decode costs per token are the
same as v0.5.1's. The median meets the 2,000 ms target of the spec (section 2, criterion 6).

## Long run (`long1500.summary.json`, `long1500.dispatch.json`)

The same 300 cases five times in a row, 1,500 requests in 29 minutes (servos off), with a `heap`
record every 100 requests:

    uv run --no-project --with pyserial python firmware/tools/lm_serial.py --port COM3 --reset --act \
        --cases cases300.jsonl --limit 300 --repeat 5 --heap-every 100 --ref <PyTorch> --out t8_long.jsonl

- **Outputs:** all 1,500 equal PyTorch (ids, `raw`, gated output; 65 gated). Every reply had its
  plan; 1,500 valid, 650 queued and run, none dropped; plans 1,500 / 1,500 equal `plan_v1`;
  `dispatch_check` `n_problems` 0. No `error` or `fault` record, no aborted plan, no reset or
  panic in the serial log (the only `rst:` is the reset at the start).
- **Memory:** internal SRAM free 89,891 B after boot (`board_ready`), 86,467 B after the first
  request, 86,099 B after 100 requests, then 85,915 B (request 200) and 85,783 B from request 400
  to the end, with two readings of 85,651 B (requests 1,000 and 1,300) that came back to
  85,783 B: no steady leak. The smallest free block stayed at 45,056 B and the low-water mark at
  53,548 B; PSRAM free did not change (7,755,648 B); the LM task's stack kept 13,324 B free.
  (Internal SRAM free is about 13 KB lower than v0.5.1's 98,7xx B, from the speaker and the v1
  dispatcher.)
- **Temperature:** the chip's internal sensor read 45.6 °C at boot, 47.6 °C after the first
  request and 50.6 to 51.6 °C from request 100 to the end, on a desk at room temperature.
- **Clock:** 240 MHz in every record.
- **Latency per pass of 300:** median 1,049 / 1,048 / 1,048 / 1,047 / 1,047 ms, p90 1,744 to
  1,745 ms, max 2,752 to 2,754 ms (no drift over the run).

## A `.jtlm` that does not match the grammar

The v1 firmware with the v0 release `.jtlm` (`jtalm_action_3m_q4_g64.jtlm`, v0 tokenizer) in the
`model` partition prints, right after the LM task starts (`task_start` at 8 ms),

    JTALM {"t":"error","msg":"the tokenizer lacks the Action grammar pieces"}

and then nothing else (no `info`, no `ready`, no reset or panic in 15 s): the cause is named and
the board does not start a half-working LM. Writing the v1 `.jtlm` back at `0x200000` gives
`info` with `model_sha` `e38499f7276c77ba` and `ready`.

## Head limits (F2)

yaw -45 to +45 deg, pitch 0 to +85 deg, checked on this K151 with someone watching (2026-10-02).
Below horizontal the head rests on the floor (about +2.5 deg), so the lower pitch limit is 0; a
bow from below 20 deg first lifts the head to 20 deg. Requests beyond the limits stop at the edge
and the plan marks the move `clamped`.

## The user's four sentences (`user4.summary.json`)

Run before this firmware build (same LM and dispatcher code, gate 0.868 at that time; every
`min_prob` is 0.9997 or higher, so the 0.88506 gate gives the same outputs):

| prompt | output | plan | min_prob | total_ms |
|---|---|---|---:|---:|
| LEDライトの色を青にして | `set_led blue` | LED blue | 0.99975 | 1,063 |
| 音声の音量を50にして | `set_volume 50` | volume 50 | 0.99996 | 1,128 |
| 頭を90度上に向けて | `look up 90` | move to pitch 85, `clamped` | 0.99992 | 1,297 |
| 顔を右に45度向いて | `look right 45` | move to yaw 45 | 0.99978 | 1,258 |

All four equal the outputs of spec section 4.4.

## Raw logs

Raw records and serial logs stay in `runs/fw/` (not tracked): `t8_mismatch.log`,
`t8_boot_v1.log`, `t8_parity.{jsonl,log}`, `t8_long.{jsonl,log}`, `t8_user4.{jsonl,log}`.
