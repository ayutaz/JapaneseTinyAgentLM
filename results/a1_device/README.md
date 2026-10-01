# jtalm_action with display and dispatcher (first 200 v0 eval cases)

`eval200.summary.json` is the `firmware/tools/lm_serial.py` summary for the `jtalm_action`
firmware with the display (M5Unified / M5GFX) and the servo dispatcher running (servos in
dry-run), using the data v0.4 3M INT4 model (same architecture and size as the adopted v0.5.1
model) with gate 0.970:

- output identical to the host runtime on 200 / 200 prompts (ids, output and gated output)
- latency per request: median 1,226 ms, p90 1,439 ms
- the `device` list holds the firmware's `heap` records, e.g. internal SRAM free 116,831 B after
  loading the model and 99,039 B after 200 requests (docs/hardware.md)
