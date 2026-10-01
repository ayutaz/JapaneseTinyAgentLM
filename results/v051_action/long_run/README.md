# Long run on the device (v0.5.1 3M INT4)

`long3567.summary.json`: the `jtalm_action` firmware (display and dispatcher on, servos off, so
plans run as a dry run; gate 0.868, grammar on) answered the 1,189 prompts of v0 eval three
times in a row, 3,567 requests in 72 minutes, sent by

    uv run --no-project --with pyserial python firmware/tools/lm_serial.py --port <PORT> --reset \
        --act --cases <v0 eval prompts> --repeat 3 --heap-every 100 \
        --ref <host runtime output, -DJTLM_ACC=float> --out long3567.jsonl

The firmware is the release build plus the chip temperature and CPU clock in the `heap` record
(the LM code is the same). `health` holds a `heap` record every 100 requests.

- **Outputs:** all 3,567 equal to the host C runtime (ids, output before the gate, output after
  the gate); 222 gated. Every reply had its dispatcher plan (`act`); no `error` record, no
  aborted plan, no reset or panic in the serial log (the only `rst:` is the reset at the start).
- **Memory:** internal SRAM free 98,867 B after 100 requests; it fell by 120 B before request
  300 and by 32 B before request 1,900, then stayed at 98,715 B for the last 1,650 requests (no
  steady leak). PSRAM free did not change (7,756,848 B). The LM task's stack kept 13,260 B free.
- **Temperature:** the chip's internal sensor (die temperature, about 1 °C steps; for relative
  changes) read 48.6 °C at boot, 54.6 °C after 100 requests and 56.6 to 57.6 °C from about
  request 600 to the end, on a desk at room temperature.
- **Clock:** 240 MHz in every record (no frequency scaling is configured).
- **Latency:** median per pass of 1,189 requests 1,046 / 1,058 / 1,062 ms, p90 1,871 ms in all
  three passes. (These are over all of v0 eval; `../device/` is over its first 300 prompts.)
