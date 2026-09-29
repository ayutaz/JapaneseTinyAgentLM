# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 JapaneseTinyAgentLM contributors
"""Run the servo motion test sequence on jtalm_action (docs/hardware.md section 12).

Without `--servo` everything runs in dry-run (servo output stays off; plans, timing and
faces only). With `--servo` the script sends `!servo on` and the head MOVES: run it only
with the user watching the robot (docs/hardware.md section 12, "Servo の動作確認").

    uv run --no-project --with pyserial python firmware/tools/servo_test.py \
        --port COM3 --out runs/device/a1/servo_test_dry.jsonl            # dry-run
    uv run --no-project --with pyserial python firmware/tools/servo_test.py \
        --port COM3 --servo --out runs/device/a1/servo_test.jsonl        # moves the head

Each item waits for its plan to finish (`act_done`) and then `--pause` seconds, so the
observer can compare the motion with the printed plan. Any `fault` or `stop` record (a touch
on the screen, the watchdog, a servo error) or Ctrl+C ends the run with `!stop`. At the end
the head is centered and servo output is turned off (`!servo off`).
"""

import argparse
import json
import sys
import time
from pathlib import Path

from lm_serial import Device


def act(calls: list[dict]) -> str:
    return "!act " + json.dumps(calls, separators=(",", ":"))


def look(direction: str, amount: str = "normal") -> dict:
    return {"name": "look", "arguments": {"direction": direction, "amount": amount}}


def nod(count: int) -> dict:
    return {"name": "nod", "arguments": {"count": count}}


def expr(name: str) -> dict:
    return {"name": "set_expression", "arguments": {"expression": name}}


# Part A: fixed Action JSON (no LM), every direction, amount and nod count once.
ACT_ITEMS = [
    ("右（slight）", act([look("right", "slight")])),
    ("右（normal）", act([look("right", "normal")])),
    ("右（large）", act([look("right", "large")])),
    ("左（large）: 右端から左端へ 60°", act([look("left", "large")])),
    ("正面", act([look("center")])),
    ("上（slight → large）", act([look("up", "slight"), look("up", "large")])),
    ("下（normal、-10°）", act([look("down", "normal")])),
    ("下（large）: -15° は -10° に制限されるので、ここでは動かない", act([look("down", "large")])),
    ("正面", act([look("center")])),
    ("うなずき 1回", act([nod(1)])),
    ("うなずき 2回", act([nod(2)])),
    ("うなずき 3回", act([nod(3)])),
    ("表情: happy → sad", act([expr("happy"), expr("sad")])),
    ("表情: surprised → neutral", act([expr("surprised"), expr("neutral")])),
    ("上を向いてうなずく（上を向いたまま）", act([look("up", "normal"), nod(2)])),
    ("正面", act([look("center")])),
]

# Part B: utterances through the LM (greedy + grammar + gate). "still": must not move.
LM_ITEMS = [
    ("右を向いて", None),
    ("少し左を向いて", None),
    ("上を向いて", None),
    ("正面を向いて", None),
    ("2回うなずいて", None),
    ("笑って", None),
    ("右を向いて、ちょっと嬉しそうにして", None),
    ("右を向かないで", "still"),
    ("今日はいい天気だね", "still"),
    ("富士山について長く説明して", "still"),
    ("普通の顔に戻して", None),
    ("正面を向いて", None),
]


class Stopped(Exception):
    pass


def check(keep: list[dict]) -> None:
    for r in keep:
        if r.get("t") in ("fault", "stop"):
            raise Stopped(json.dumps(r, ensure_ascii=False))
    keep.clear()


def describe(a: dict) -> str:
    parts = []
    for s in a["steps"]:
        if s["k"] == "expr":
            parts.append(f"face {s['expr']}")
        else:
            clamp = " (clamped)" if s["clamped"] else ""
            parts.append(
                f"yaw {s['yaw']:+d} pitch {s['pitch']:+d} raw ({s['yaw_raw']},{s['pitch_raw']}) "
                f"{s['ms']}ms{clamp}"
            )
    return "; ".join(parts) or "(no action)"


def run_item(dev: Device, label: str, line: str, expect: str | None, f, keep: list) -> None:
    dev.send(line)
    gen = None
    if not line.startswith("!"):
        gen = dev.wait_for("gen", 30.0, keep)
    a = dev.wait_for("act", 30.0, keep)
    check(keep)
    output = gen["output"] if gen else line[5:]
    print(f"- {label}\n    output: {output}\n    plan:   {describe(a)}", flush=True)
    moves = [s for s in a["steps"] if s["k"] == "move"]
    if expect == "still" and moves:
        print("    NG: this request must not move the head", flush=True)
        raise Stopped("unexpected motion")
    done = None
    if a["queued"]:
        done = dev.wait_for("act_done", a["total_ms"] / 1000.0 + 10.0, keep)
        check(keep)
        print(
            f"    done:   {done['ms']:.0f} ms (planned {done['planned_ms']}), servo "
            f"{done['servo']}, present raw {done['present']}",
            flush=True,
        )
        if done["aborted"] or done["err"]:
            raise Stopped(json.dumps(done, ensure_ascii=False))
    f.write(
        json.dumps(
            {"label": label, "line": line, "gen": gen, "act": a, "done": done}, ensure_ascii=False
        )
        + "\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--servo", action="store_true", help="turn servo output ON (head moves)")
    ap.add_argument("--section", choices=["act", "lm", "all"], default="all")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between items")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dev = Device(args.port, args.out.with_suffix(".log"))
    keep: list[dict] = []
    items = []
    if args.section in ("act", "all"):
        items += [(label, line, None) for label, line in ACT_ITEMS]
    if args.section in ("lm", "all"):
        items += [(text, text, expect) for text, expect in LM_ITEMS]
    rc = 0
    with args.out.open("w", encoding="utf-8") as f:
        try:
            dev.reset()
            dev.wait_for("ready", 30.0, keep)
            keep.clear()
            if args.servo:
                dev.send("!servo on")
                s = dev.wait_for("servo", 10.0, keep)
                print(f"servo on: {s}", flush=True)
                if s.get("state") != "on":
                    raise Stopped(f"servo on failed: {s}")
                a = dev.wait_for("act", 10.0, keep)
                dev.wait_for("act_done", a["total_ms"] / 1000.0 + 10.0, keep)
                check(keep)
            for i, (label, line, expect) in enumerate(items):
                print(f"[{i + 1}/{len(items)}]", end=" ", flush=True)
                run_item(dev, label, line, expect, f, keep)
                time.sleep(args.pause)
                dev._read()
                check(keep + [r for r in dev.pending if r.get("t") in ("fault", "stop")])
            dev.send("!center")
            a = dev.wait_for("act", 10.0, keep)
            if a["queued"]:
                dev.wait_for("act_done", a["total_ms"] / 1000.0 + 10.0, keep)
            check(keep)
            print("sequence finished", flush=True)
        except (Stopped, TimeoutError, RuntimeError, KeyboardInterrupt) as e:
            print(f"STOPPED: {e!r}", flush=True)
            rc = 2
        finally:
            dev.send("!servo off")
            time.sleep(0.5)
            dev.send("!servo")
            try:
                status = dev.wait_for("servo", 5.0)
                print(f"final: {status}", flush=True)
                if status.get("state") != "off" or status.get("vm_en") == 1:
                    rc = 3
            except (TimeoutError, RuntimeError) as e:
                print(f"final status unknown: {e!r}", flush=True)
                rc = 3
            dev.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
