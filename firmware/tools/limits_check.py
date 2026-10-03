# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""F2: widen the head limits step by step with someone watching (jtalm_action "!pose").

    uv run --no-project --with pyserial python firmware/tools/limits_check.py \
        --port COM3 --axis yaw --out runs/fw/f2_yaw.jsonl
    uv run --no-project --with pyserial python firmware/tools/limits_check.py \
        --port COM3 --axis pitch --max 45 --out runs/fw/f2_pitch45.jsonl

THE HEAD MOVES. The script turns servo output on, goes through the poses of one axis in small
steps (pausing on each), compares the servo's present position with the target, and centers
and turns the servos off at the end. A touch on the screen stops at once. Ctrl+C lets the
current move finish, then the head is centered and the servo power turned off. The run also
stops (centers, powers off) when a pose is NG, a plan is aborted or reports an error, the servo
output is not on, or a servo position cannot be read.

Watch for the head sagging ~0.5 s after each high pose: torque is released 0.5 s after each
plan. The next plan's sync_ms (non-zero: the head drifted while limp) is printed as SAG?.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from lm_serial import Device

STEP_DEG = 5
TOLERANCE_DEG = 2.0  # tested axis: present vs target; more means the head did not get there
OTHER_AXIS_TOLERANCE_DEG = 4.0  # untouched axis: gravity/backlash drift (2.8 deg seen on the K151)
FLOOR_REST_DEG = 3.0  # at the lower pitch limit the head rests on the floor (~+2.5 deg seen)
YAW_RAW_ZERO, PITCH_RAW_ZERO, DEG_PER_RAW = 460, 620, 5 / 16
ACTION_H = Path(__file__).resolve().parents[1] / "jtalm_action" / "main" / "action.h"


def pitch_min_deg(path: Path = ACTION_H) -> int:
    """The firmware's lower pitch limit (ACT_PITCH_MIN_DEG; 0 on the K151, 2026-10-02)."""
    m = re.search(r"^#define ACT_PITCH_MIN_DEG \(?(-?\d+)\)?", path.read_text("utf-8"), re.M)
    if m is None:
        raise RuntimeError(f"ACT_PITCH_MIN_DEG not found in {path}")
    return int(m.group(1))


PITCH_MIN_DEG = pitch_min_deg()


def poses(axis: str, limit: int) -> list[tuple[int, int]]:
    if axis == "yaw":
        right = list(range(30, limit + 1, STEP_DEG))
        return [(y, 0) for y in right] + [(0, 0)] + [(-y, 0) for y in right] + [(0, 0)]
    up = list(range(15, limit + 1, STEP_DEG))
    low = [(0, PITCH_MIN_DEG)] + ([(0, 0)] if PITCH_MIN_DEG != 0 else [])
    return [(0, p) for p in up] + low


def judge(
    axis: str, got: tuple[float, float], target: tuple[int, int]
) -> tuple[bool, float, float]:
    """(ng, tested-axis offset, other-axis offset) in degrees.

    On the pitch axis at the lower limit, a head up to FLOOR_REST_DEG above the target counts as
    there: it rests on the floor (pitch raw ~628 for a target of 0 on the K151, 2026-10-02).
    """
    d_yaw, d_pitch = abs(got[0] - target[0]), abs(got[1] - target[1])
    tested, other = (d_yaw, d_pitch) if axis == "yaw" else (d_pitch, d_yaw)
    tol = TOLERANCE_DEG
    if axis == "pitch" and target[1] == PITCH_MIN_DEG and got[1] > target[1]:
        tol = FLOOR_REST_DEG
    return tested > tol or other > OTHER_AXIS_TOLERANCE_DEG, tested, other


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--axis", choices=["yaw", "pitch"], required=True)
    ap.add_argument("--max", type=int, default=None, help="largest angle to try (default: target)")
    ap.add_argument("--pause", type=float, default=2.0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    limit = args.max if args.max is not None else (45 if args.axis == "yaw" else 85)
    sys.stdout.reconfigure(encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dev = Device(args.port, args.out.with_suffix(".log"))
    keep: list[dict] = []
    rc = 0
    recs: list[dict] = []
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
                if recs:  # the head was limp after the previous pose; sync_ms is its drift
                    recs[-1]["sag_ms"] = done.get("sync_ms", 0)
                    if recs[-1]["sag_ms"]:
                        print(f"  SAG? previous pose drifted while limp (sync_ms "
                              f"{recs[-1]['sag_ms']})", flush=True)  # fmt: skip
                if done.get("aborted") or done.get("err") is not None:
                    raise RuntimeError(f"plan aborted or failed: {done}")
                if done.get("servo") != "on":
                    raise RuntimeError(f"servo output not on: {done}")
                py, pp = done["present"]
                if py == -1 or pp == -1:
                    raise RuntimeError(f"servo position unreadable: {done}")
                got = ((YAW_RAW_ZERO - py) * DEG_PER_RAW, (pp - PITCH_RAW_ZERO) * DEG_PER_RAW)
                target = a["steps"][0]["yaw"], a["steps"][0]["pitch"]
                ng, _, other = judge(args.axis, got, target)
                other_name = "pitch" if args.axis == "yaw" else "yaw"
                note = "  NG: did not reach the target" if ng else ""
                clamp = " (clamped)" if a["steps"][0]["clamped"] else ""
                print(f"yaw {target[0]:+d} pitch {target[1]:+d}{clamp}: present "
                      f"({got[0]:+.1f}, {got[1]:+.1f}) "
                      f"{other_name} off {other:.1f}{note}", flush=True)  # fmt: skip
                recs.append({"target": target, "present_deg": got, "act": a, "done": done})
                if note:
                    raise RuntimeError(f"NG at {target}: the head did not reach the target")
                keep.clear()
                time.sleep(args.pause)
        except (RuntimeError, TimeoutError, KeyboardInterrupt) as e:
            print(f"STOPPED: {e!r}", flush=True)
            rc = 2
        finally:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            dev.send("!center")
            time.sleep(1.5)
            dev.send("!servo off")
            time.sleep(0.5)
            dev.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
