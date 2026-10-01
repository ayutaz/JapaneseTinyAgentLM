# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""F2: widen the head limits step by step with someone watching (jtalm_action "!pose").

    uv run --no-project --with pyserial python firmware/tools/limits_check.py \
        --port COM3 --axis yaw --out runs/fw/f2_yaw.jsonl
    uv run --no-project --with pyserial python firmware/tools/limits_check.py \
        --port COM3 --axis pitch --max 45 --out runs/fw/f2_pitch45.jsonl

THE HEAD MOVES. The script turns servo output on, goes through the poses of one axis in small
steps (pausing on each), compares the servo's present position with the target, and centers
and turns the servos off at the end. A touch on the screen or Ctrl+C stops at once.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from lm_serial import Device

STEP_DEG = 5
TOLERANCE_DEG = 2.0  # present vs target; more means the head did not get there
YAW_RAW_ZERO, PITCH_RAW_ZERO, DEG_PER_RAW = 460, 620, 5 / 16


def poses(axis: str, limit: int) -> list[tuple[int, int]]:
    if axis == "yaw":
        right = list(range(30, limit + 1, STEP_DEG))
        return [(y, 0) for y in right] + [(0, 0)] + [(-y, 0) for y in right] + [(0, 0)]
    up = list(range(15, limit + 1, STEP_DEG if limit <= 45 else 10))
    return [(0, p) for p in up] + [(0, -10), (0, 0)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--axis", choices=["yaw", "pitch"], required=True)
    ap.add_argument("--max", type=int, default=None, help="largest angle to try (default: target)")
    ap.add_argument("--pause", type=float, default=2.0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    limit = args.max or (45 if args.axis == "yaw" else 85)
    sys.stdout.reconfigure(encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dev = Device(args.port, args.out.with_suffix(".log"))
    keep: list[dict] = []
    rc = 0
    with args.out.open("w", encoding="utf-8") as f:
        try:
            dev.reset()
            dev.wait_for("ready", 30.0, keep)
            dev.send("!servo on")
            if dev.wait_for("servo", 10.0, keep).get("state") != "on":
                raise RuntimeError("servo on failed")
            dev.wait_for("act_done", 15.0, keep)
            for yaw, pitch in poses(args.axis, limit):
                dev.send(f"!pose {yaw} {pitch}")
                a = dev.wait_for("act", 10.0, keep)
                done = dev.wait_for("act_done", a["total_ms"] / 1000 + 10, keep)
                if any(r.get("t") in ("fault", "stop") for r in keep):
                    raise RuntimeError("stopped (touch, watchdog or servo error)")
                py, pp = done["present"]
                got = ((YAW_RAW_ZERO - py) * DEG_PER_RAW, (pp - PITCH_RAW_ZERO) * DEG_PER_RAW)
                target = a["steps"][0]["yaw"], a["steps"][0]["pitch"]
                off = max(abs(got[0] - target[0]), abs(got[1] - target[1]))
                note = "" if off <= TOLERANCE_DEG else "  NG: did not reach the target"
                clamp = " (clamped)" if a["steps"][0]["clamped"] else ""
                print(f"yaw {target[0]:+d} pitch {target[1]:+d}{clamp}: present "
                      f"({got[0]:+.1f}, {got[1]:+.1f}){note}", flush=True)  # fmt: skip
                f.write(json.dumps({"target": target, "present_deg": got, "act": a,
                                    "done": done}, ensure_ascii=False) + "\n")  # fmt: skip
                rc |= 0 if not note else 1
                keep.clear()
                time.sleep(args.pause)
        except (RuntimeError, TimeoutError, KeyboardInterrupt) as e:
            print(f"STOPPED: {e!r}", flush=True)
            rc = 2
        finally:
            dev.send("!center")
            time.sleep(1.5)
            dev.send("!servo off")
            time.sleep(0.5)
            dev.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
