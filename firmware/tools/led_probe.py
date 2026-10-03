# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""F1: light the 12 base LEDs of the K151 in a few colors (jtalm_action, "!led r g b").

    uv run --no-project --with pyserial python firmware/tools/led_probe.py \
        --port COM3 --out runs/fw/f1_led.jsonl

Someone watches the back of the base and says which colors appeared. Servo output stays off.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from lm_serial import Device

COLORS = [
    ("赤", 168, 0, 0),
    ("緑", 0, 168, 0),
    ("青", 0, 0, 168),
    ("白（弱め）", 100, 100, 100),
    ("消灯", 0, 0, 0),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--pause", type=float, default=3.0, help="seconds per color")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dev = Device(args.port, args.out.with_suffix(".log"))
    keep: list[dict] = []
    rc = 0
    with args.out.open("w", encoding="utf-8") as f:
        try:
            dev.reset()
            dev.wait_for("ready", 30.0, keep)
            board = next(r for r in keep if r.get("t") == "board")
            print(f"board: led_init={board.get('led_init')} led_cfg={board.get('led_cfg')}")
            f.write(json.dumps(board, ensure_ascii=False) + "\n")
            for label, r, g, b in COLORS:
                dev.send(f"!led {r} {g} {b}")
                rec = dev.wait_for("led", 5.0)
                print(f"{label}: ok={rec['ok']} cfg={rec['cfg']}", flush=True)
                f.write(json.dumps({"label": label, **rec}, ensure_ascii=False) + "\n")
                rc |= 0 if rec["ok"] else 1
                time.sleep(args.pause)
        finally:
            dev.send("!led 0 0 0")
            time.sleep(0.3)
            dev.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
