# v0.5.1 3M INT4 on the device (M5Stack Stack-chan K151 / CoreS3)

`eval300.summary.json` is the summary written by `firmware/tools/lm_serial.py` for the first 300
cases of the v0 evaluation set sent to the `jtalm_action` firmware (gate 0.868, grammar on,
batched prefill, dual-core matmul):

- latency per request: median 1,276 ms, p90 1,860 ms, max 2,456 ms (decode 105 ms/token, prefill 46 ms/token)
- the `device` list holds the firmware's `heap`, `load` and `info` records

Parity with PyTorch: for all 300 prompts the device's `output` and `raw` (output before the gate)
equal those of the INT4 checkpoint evaluated with `jtalm.model.eval_suite` (grammar + gate):
300 / 300.
