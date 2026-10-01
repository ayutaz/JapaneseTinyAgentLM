# JapaneseTinyAgentLM

[![CI](https://github.com/ayutaz/JapaneseTinyAgentLM/actions/workflows/ci.yml/badge.svg)](https://github.com/ayutaz/JapaneseTinyAgentLM/actions/workflows/ci.yml)
[![Code: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue.svg)](LICENSE)
[![Model: CC BY-SA 4.0](https://img.shields.io/badge/model-CC%20BY--SA%204.0-lightgrey.svg)](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M)

[日本語](README.md)

Tiny Japanese language models that run entirely on a microcontroller (ESP32-S3). The first model, the **Action LM** (3.15M parameters, trained from scratch), turns short Japanese requests into robot action calls (JSON). It runs on the M5Stack Stack-chan (K151, CoreS3) by itself — no NPU, no network — and moves the head and changes the face.

```text
input:  左を見て、真ん中に戻ってきて。 ("Look left, then come back to the middle.")
output: [{"name":"look","arguments":{"direction":"left","amount":"normal"}},
         {"name":"look","arguments":{"direction":"center","amount":"normal"}}]
```

## What it does

The output is a list of up to two calls to three actions: `look` (direction, amount), `set_expression` (happy / sad / surprised / neutral) and `nod` (count 1–3). Non-requests, negated requests and requests the robot cannot perform give `[]` (do nothing).

- Decoding is constrained by the action schema, so the output is always valid JSON.
- A confidence gate (0.868) turns low-confidence outputs into `[]`.
- The `.jtlm` file (INT4 weights + tokenizer) is 2.0 MB (1,971,456 bytes); the weights alone are 1.68 MB. The median latency on the device is 1.3 s per request.

## Results

INT4 + grammar + gate, mean ± standard deviation over five training seeds (the released model is seed 0):

| Evaluation | Cases | Result |
|---|---:|---|
| Human-written requests | 62 | **85.2 ± 6.4%** (seed 0: 91.9%) |
| False actions on human-written non-requests | 1,097 | **0.0 ± 0.0%** |
| LLM-written evaluation set (exact match) | 1,189 | **94.0 ± 0.6%** |
| Device (ESP32-S3) vs. PC (PyTorch) output | 300 | 300 / 300 identical |

Japanese only (English requests are about 5% correct). Details: [`docs/evaluation.md`](docs/evaluation.md); device measurements: [`results/v051_action/device/`](results/v051_action/device/README.md). The documents in `docs/` are written in Japanese.

## Quick start

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

The servos are off at boot. Touching the screen or sending `!stop` stops the motion and powers the servos off; the firmware limits the angles (yaw ±30°, pitch −10 to +15°). Keep fingers and cables clear of the neck.

Building from source: [`firmware/README.md`](firmware/README.md), [`runtime/host/README.md`](runtime/host/README.md), [`docs/training.md`](docs/training.md). The C runtime in `runtime/host` is also an ESP-IDF component (`git: https://github.com/ayutaz/JapaneseTinyAgentLM.git`, `path: runtime/host` in `idf_component.yml`).

## Contributing

Issues and pull requests are welcome (Japanese or English). See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

- Code: [Apache-2.0](LICENSE) (see [`NOTICE`](NOTICE)).
- Model weights ([Hugging Face](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M)) and the dataset ([Hugging Face](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth)): CC BY-SA 4.0.
- Training text was written by Apache-2.0 / MIT open models and taken from public human-written corpora (Tatoeba, JESC, MASSIVE). Built with Claude Code (Anthropic).
- Citation: [`CITATION.cff`](CITATION.cff).
