# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 JapaneseTinyAgentLM contributors
"""Send prompts to the jtalm_action firmware over serial and summarize the replies.

Run without adding a project dependency:

    uv run --no-project --with pyserial python firmware/tools/lm_serial.py \
        --port COM3 --reset --cases datasets/action/v0/eval.jsonl --limit 200 \
        --ref runs/device/b4/host_3m_q8.jsonl --out runs/device/b4/dev_3m_q8.jsonl

Each prompt is one line; the device answers with one `JTALM {"t":"gen",...}` record.
`--ref` is the host runtime's output for the same prompts (`runtime/host/build/jtalm
--grammar`, one JSON object per line); generated ids and output text are compared.
The raw serial log goes to `--log` (default: next to `--out`).
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import serial

PREFIX = "JTALM "


class Device:
    def __init__(self, port: str, log: Path) -> None:
        self.port = serial.Serial(port, 115200, timeout=0.1)
        self.log = open(log, "w", encoding="utf-8", newline="")
        self.buf = b""
        self.pending: list[dict] = []  # records read but not yet consumed

    def reset(self) -> None:
        # USB-Serial/JTAG: DTR low + RTS high, then RTS low resets the chip into the app.
        self.port.dtr = False
        self.port.rts = True
        time.sleep(0.2)
        self.port.rts = False

    def _read(self) -> None:
        data = self.port.read(4096)
        if not data:
            return
        self.buf += data
        *lines, self.buf = self.buf.split(b"\n")
        for raw in lines:
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            self.log.write(line + "\n")
            if line.startswith(PREFIX):
                try:
                    self.pending.append(json.loads(line[len(PREFIX) :]))
                except json.JSONDecodeError:
                    pass
        self.log.flush()

    def wait_for(self, kind: str, timeout: float, keep: list | None = None) -> dict:
        """Returns the next record of type `kind`; `timeout` is the allowed silence in s."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.pending:
                self._read()
                continue
            rec = self.pending.pop(0)
            deadline = time.monotonic() + timeout
            if keep is not None:
                keep.append(rec)
            if rec.get("t") == kind:
                return rec
            if rec.get("t") == "error":
                raise RuntimeError(f"device error: {rec}")
        raise TimeoutError(f"no {kind!r} record within {timeout} s")

    def send(self, line: str) -> None:
        self.port.write(line.encode("utf-8") + b"\n")

    def close(self) -> None:
        self.port.close()
        self.log.close()


def load_prompts(path: Path, limit: int) -> list[str]:
    if path.suffix == ".jsonl":
        prompts = [json.loads(line)["prompt"] for line in path.open(encoding="utf-8")]
    else:
        prompts = path.read_text(encoding="utf-8").splitlines()
    prompts = prompts[:limit] if limit else prompts
    for p in prompts:
        if "\n" in p or "\r" in p or p.startswith("!") or not p.strip():
            raise ValueError(f"prompt cannot be sent as one line: {p!r}")
    return prompts


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def summarize(results: list[dict], ref: list[dict] | None) -> dict:
    total = [r["total_ms"] for r in results]
    fwd = sum(r["n_fwd"] for r in results)
    fwd_ms = sum(r["prefill_ms"] + r["decode_ms"] for r in results)
    dec = [r for r in results if r["n_gen"] > 1]
    out = {
        "n": len(results),
        "total_ms_median": statistics.median(total),
        "total_ms_p90": pct(total, 0.9),
        "total_ms_max": max(total),
        "ms_per_fwd": fwd_ms / fwd,
        "tok_s": fwd * 1000.0 / fwd_ms,
        "prefill_ms_per_tok": sum(r["prefill_ms"] for r in results)
        / sum(r["n_prompt"] for r in results),
        "decode_ms_per_tok": (
            sum(r["decode_ms"] for r in dec) / sum(r["n_gen"] - 1 for r in dec) if dec else None
        ),
        "tok_ms_mean": statistics.mean(r["tok_ms"] for r in results),
        "n_prompt_mean": statistics.mean(r["n_prompt"] for r in results),
        "n_gen_mean": statistics.mean(r["n_gen"] for r in results),
    }
    if ref is not None:
        same_ids = same_out = 0
        mismatches = []
        for i, (d, h) in enumerate(zip(results, ref, strict=False)):
            ok_ids = d["ids"] == h["ids"]
            ok_out = d["output"] == h["output"]
            same_ids += ok_ids
            same_out += ok_out
            if not (ok_ids and ok_out):
                mismatches.append(
                    {"i": i, "prompt": d["prompt"], "device": d["ids"], "host": h["ids"]}
                )
        out.update(same_ids=same_ids, same_output=same_out, mismatches=mismatches[:20])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--reset", action="store_true", help="reset the chip and wait for 'ready'")
    ap.add_argument("--cases", type=Path, required=True, help=".jsonl with 'prompt', or .txt")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-grammar", action="store_true")
    ap.add_argument(
        "--cmd", action="append", default=[], help='device command sent first, e.g. "!par 0"'
    )
    ap.add_argument("--ref", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--log", type=Path, default=None)
    ap.add_argument("--timeout", type=float, default=60.0, help="seconds per reply")
    args = ap.parse_args()

    prompts = load_prompts(args.cases, args.limit)
    ref = None
    if args.ref:
        ref = [json.loads(line) for line in args.ref.open(encoding="utf-8")][: len(prompts)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dev = Device(args.port, args.log or args.out.with_suffix(".log"))
    boot: list[dict] = []
    try:
        if args.reset:
            dev.reset()
            dev.wait_for("ready", 30.0, boot)
        dev.send("!info")
        boot.append(dev.wait_for("info", 10.0))
        for cmd in ["!grammar " + ("0" if args.no_grammar else "1"), *args.cmd]:
            dev.send(cmd)
            boot.append(dev.wait_for("ok", 10.0))
        results = []
        with args.out.open("w", encoding="utf-8") as f:
            for i, prompt in enumerate(prompts):
                dev.send(prompt)
                rec = dev.wait_for("gen", args.timeout, boot)
                rec.update(i=i, prompt=prompt)
                results.append(rec)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if (i + 1) % 25 == 0:
                    print(f"{i + 1}/{len(prompts)}", file=sys.stderr)
        dev.send("!heap")
        boot.append(dev.wait_for("heap", 10.0))
    finally:
        dev.close()

    summary = summarize(results, ref)
    summary["device"] = [r for r in boot if r.get("t") in ("info", "load", "heap", "ok")]
    args.out.with_suffix(".summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    brief = {k: v for k, v in summary.items() if k not in ("device", "mismatches")}
    print(json.dumps(brief, ensure_ascii=False))
    for m in summary.get("mismatches", []):
        print("MISMATCH", json.dumps(m, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
