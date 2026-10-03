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
- A confidence gate (0.88506, chosen on validation only) turns low-confidence outputs into `[]`.
- The `.jtlm` file (INT4 weights + tokenizer) is 2.0 MB (1,970,720 bytes); the weights alone are 1.68 MB. The median latency on the device is 1.04 s per request.
- The previous release (Action schema v0: `look`, `set_expression`, `nod` only) is in the Git history and [`results/v051_action/`](results/v051_action/).

## Results

INT4 + grammar + gate, mean ± standard deviation over five training seeds (the released model is seed 0, fixed before evaluation):

| Evaluation | Cases | Result |
|---|---:|---|
| The user's four everyday requests (「LEDライトの色を青にして」 etc.) | 4 | **4 / 4** (all seeds) |
| Everyday Stack-chan phrasings (public examples and paraphrases, exact match) | 140 | **94.4 ± 0.9%** (seed 0: 92.9%) |
| False actions on its confusable non-requests (room light, air conditioner, ...) | 65 | **0** (all seeds) |
| Human-written requests | 65 | **91.7 ± 2.1%** (seed 0: 93.8%) |
| False actions on human-written non-requests | 1,092 | **0.1 ± 0.1%** |
| LLM-written evaluation set eval v3 (exact match) | 1,816 | **95.3 ± 0.5%** |
| Device (ESP32-S3) vs. PC (PyTorch) output | 300 | 300 / 300 identical (motion plans too) |

Weak spots: relative `turn` (84.3% vs. 97.4% for `look` on single-action eval v3 cases), numeric requests stopped by the gate (7.3 ± 4.1% of them on the Stack-chan set), 「首を振って」 (nod or shake), and English (about 7% of requests correct; Japanese only). Details: [`docs/evaluation.md`](docs/evaluation.md) and [`results/v1_action/comparison.md`](results/v1_action/comparison.md); device measurements: [`results/v1_action/device/`](results/v1_action/device/README.md). The documents in `docs/` are written in Japanese.

## Quick start

**Try it in the browser:** [demo (Hugging Face Space)](https://huggingface.co/spaces/ayousanz/JapaneseTinyAgentLM-Action-3M-demo), no install; the same C runtime as the device (WebAssembly) with the INT4 weights runs in the page.

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
