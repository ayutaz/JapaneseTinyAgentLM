# JapaneseTinyAgentLM

[![CI](https://github.com/ayutaz/JapaneseTinyAgentLM/actions/workflows/ci.yml/badge.svg)](https://github.com/ayutaz/JapaneseTinyAgentLM/actions/workflows/ci.yml)
[![Code: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue.svg)](LICENSE)
[![Model: CC BY-SA 4.0](https://img.shields.io/badge/model-CC%20BY--SA%204.0-lightgrey.svg)](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M)
[![Demo](https://img.shields.io/badge/%F0%9F%A4%97-demo-orange.svg)](https://huggingface.co/spaces/ayousanz/JapaneseTinyAgentLM-Action-3M-demo)

[日本語](README.md)

Tiny Japanese language models that run entirely on a microcontroller (ESP32-S3). The first model, the **Action LM** (3.15M parameters, trained from scratch), turns short Japanese requests into robot action calls (JSON). It runs on the M5Stack Stack-chan (K151, CoreS3) by itself — no NPU, no network — and moves the head and changes the face, the base LED color, the volume and the screen brightness.

```text
input:  顔を右に45度向いて ("Turn your face 45 degrees to the right.")
output: [{"name":"look","arguments":{"direction":"right","degrees":45}}]

input:  LEDライトの色を青にして ("Make the LED light blue.")
output: [{"name":"set_led","arguments":{"color":"blue"}}]
```

## What it does

The output is a list of up to two calls to the 11 tools of Action schema v1: `look` (absolute) and `turn` (relative to the current pose) with a direction (including diagonals) and either an amount or `degrees` (1–180); `nod` / `shake` (count 1–5); `bow`; `set_expression` (happy / sad / surprised / neutral / angry / sleepy / doubt); `set_led` (10 colors); `set_volume` / `set_brightness` (level 0–100); `adjust_volume` / `adjust_brightness` (up / down by an amount or `by` 1–100). Non-requests, negated requests, devices the robot does not have (the room light, the air conditioner) and requests the robot cannot perform give `[]` (do nothing).

- Decoding is constrained by the action schema, so the output is always valid JSON.
- A confidence gate (0.83673, chosen on validation only) turns low-confidence outputs into `[]`.
- The `.jtlm` file (INT4 weights + tokenizer) is 2.0 MB (1,970,720 bytes); the weights alone are 1.68 MB. The median latency on the device is 1.07 s per request.
- This is data v1.1: turning the LED on without naming a color (「ライトをつけて」, 「LEDを点灯して」) now gives white; the data v1.0 model returned nothing or even "off" for these.
- The previous release (Action schema v0: `look`, `set_expression`, `nod` only) is in the Git history and [`results/v051_action/`](results/v051_action/).

## Results

INT4 + grammar + gate, mean ± standard deviation over five training seeds. The chosen model is seed 1, picked after comparing the five seeds on the evaluation sets, so its own numbers are slightly optimistic; use the five-seed means:

| Evaluation | Cases | Result |
|---|---:|---|
| The user's four everyday requests (「LEDライトの色を青にして」 etc.) | 4 | **4 / 4** (all seeds) |
| Everyday Stack-chan phrasings (public examples and paraphrases, exact match) | 140 | **93.1 ± 0.8%** (seed 1: 92.9%) |
| False actions on its confusable non-requests (room light, air conditioner, ...) | 65 | **0** (all seeds) |
| Human-written requests | 65 | **91.7 ± 1.8%** (seed 1: 93.8%) |
| False actions on human-written non-requests | 1,092 | **0.1 ± 0.2%** |
| LLM-written evaluation set eval v3 (exact match) | 1,816 | **95.2 ± 0.5%** |
| LLM-written LED set (LED on, colors, off; exact match) | 437 | **90.7 ± 0.9%** (data v1.0: 41.6%) |
| Device (ESP32-S3) vs. PC (PyTorch) output | 400 | 400 / 400 identical (motion plans too) |

Weak spots: relative `turn` (85.3% vs. 97.3% for `look` on single-action eval v3 cases), numeric requests stopped by the gate (10.9 ± 7.6% of them on the Stack-chan set), 「首を振って」 (nod or shake), LED colors written in hiragana (「あかにして」), and English (about 4% of requests correct; Japanese only). The data v1.0 model (seed 0, fixed before evaluation) had 94.4 ± 0.9% on the Stack-chan set and 91.7 ± 2.1% on human-written requests over five seeds. Details: [`docs/evaluation.md`](docs/evaluation.md) and [`results/v11_action/seeds_3m.md`](results/v11_action/seeds_3m.md); device measurements: [`results/v11_action/device/`](results/v11_action/device/). The documents in `docs/` are written in Japanese.

## Quick start

**Try it in the browser:** [demo (Hugging Face Space)](https://huggingface.co/spaces/ayousanz/JapaneseTinyAgentLM-Action-3M-demo), no install; the same C runtime as the device (WebAssembly) with the INT4 weights runs in the page.

The demo stores every submitted prompt and inference result in a private R2 bucket for quality review and model improvement. It does not display a result if storage fails. Records expire after 90 days and are then deleted by R2 lifecycle processing. Do not enter personal information. See [`runtime/feedback-worker/`](runtime/feedback-worker/README.md) for the implementation.

**Python (CPU is enough)**

```bash
pip install torch numpy sentencepiece safetensors huggingface_hub
hf download ayousanz/JapaneseTinyAgentLM-Action-3M --local-dir JapaneseTinyAgentLM-Action-3M
python JapaneseTinyAgentLM-Action-3M/inference.py 右を向いて
```

**Stack-chan K151** ([this erases the current firmware](firmware/README.md#すぐに試すビルド済みのイメージ); back it up first with step 1 there if you want to restore it)

```bash
pip install esptool pyserial huggingface_hub
hf download ayousanz/JapaneseTinyAgentLM-Action-3M --local-dir JapaneseTinyAgentLM-Action-3M
esptool --chip esp32s3 -p <PORT> -b 921600 write-flash 0x0 JapaneseTinyAgentLM-Action-3M/firmware/stackchan_k151_jtalm_action.bin
python JapaneseTinyAgentLM-Action-3M/firmware/stackchan_chat.py <PORT>            # servos stay off (the head does not move)
python JapaneseTinyAgentLM-Action-3M/firmware/stackchan_chat.py <PORT> --servo    # the head moves
```

`<PORT>` is the serial port of the robot, e.g. `COM3` on Windows or `/dev/ttyACM0` on Linux.

The servos are off at boot. Touching the screen or sending `!stop` stops the motion and powers the servos off; the firmware limits the angles (yaw ±45°, pitch 0 to +85°; the head rests on the floor below horizontal). Keep fingers and cables clear of the neck.

Building from source: [`firmware/README.md`](firmware/README.md), [`runtime/host/README.md`](runtime/host/README.md), [`docs/training.md`](docs/training.md). The C runtime in `runtime/host` is also an ESP-IDF component (`git: https://github.com/ayutaz/JapaneseTinyAgentLM.git`, `path: runtime/host` in `idf_component.yml`). [`runtime/web/`](runtime/web/README.md) builds the same runtime as WebAssembly for an in-browser demo.

## Contributing

Issues and pull requests are welcome (Japanese or English). See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

- Code: [Apache-2.0](LICENSE) (see [`NOTICE`](NOTICE)).
- Model weights ([Hugging Face](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M)) and the dataset ([Hugging Face](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth)): CC BY-SA 4.0.
- Training text was written by Apache-2.0 / MIT open models and taken from public human-written corpora (Tatoeba, JESC, MASSIVE). Built with Claude Code (Anthropic).
- Citation: [`CITATION.cff`](CITATION.cff).
