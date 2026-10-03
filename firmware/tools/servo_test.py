# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Run the servo motion test sequence on jtalm_action (docs/hardware.md).

Without `--servo` everything runs in dry-run (servo output stays off; plans, timing and
faces only). With `--servo` the script sends `!servo on` and the head MOVES: run it only
with someone watching the robot (docs/hardware.md).

    uv run --no-project --with pyserial python firmware/tools/servo_test.py \
        --port COM3 --out runs/device/a1/servo_test_dry.jsonl            # dry-run
    uv run --no-project --with pyserial python firmware/tools/servo_test.py \
        --port COM3 --servo --out runs/device/a1/servo_test.jsonl        # moves the head

Each item waits for its plan to finish (`act_done`) and then `--pause` seconds, so the
observer can compare the motion with the printed plan. Any `fault` or `stop` record (a touch
on the screen, the watchdog, a servo error) or Ctrl+C ends the run with `!stop`. At the end
the head is centered and servo output is turned off (`!servo off`).
`--only うなずき` runs just the items whose label or line contains the text.
`--section` picks a part: act (v0 head moves and faces), setting (v1 faces, LED, volume and
brightness, no motion; the device's `setting` records must show the expected values), motion
(v1 head moves: degrees, turn, diagonals, shake, bow), lm (utterances through the LM), all.
`--stop-during-bow` (with `--servo`) sends `!stop` in the middle of the bow hold and checks
the abort from `act_done` (aborted, within 500 ms, `vm_off` 0); it runs no other items.
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


def turn(direction: str, amount: str | None = None, degrees: int | None = None) -> dict:
    size = {"degrees": degrees} if degrees is not None else {"amount": amount or "normal"}
    return {"name": "turn", "arguments": {"direction": direction, **size}}


def look_deg(direction: str, degrees: int) -> dict:
    return {"name": "look", "arguments": {"direction": direction, "degrees": degrees}}


def tool(name: str, **arguments: object) -> dict:
    return {"name": name, "arguments": arguments}


# Part A: fixed Action JSON (no LM), every direction, amount and nod count once.
ACT_ITEMS = [
    ("右（slight）", act([look("right", "slight")])),
    ("右（normal）", act([look("right", "normal")])),
    ("右（large）", act([look("right", "large")])),
    ("左（large）: 右端から左端へ 60°", act([look("left", "large")])),
    ("正面", act([look("center")])),
    ("上（slight → large）", act([look("up", "slight"), look("up", "large")])),
    ("下（normal）: -10° は 0°（床）に制限される", act([look("down", "normal")])),
    ("下（large）: -15° も 0° に制限されるので、ここでは動かない", act([look("down", "large")])),
    ("正面", act([look("center")])),
    ("うなずき 1回", act([nod(1)])),
    ("うなずき 2回", act([nod(2)])),
    ("うなずき 3回", act([nod(3)])),
    ("表情: happy → sad", act([expr("happy"), expr("sad")])),
    ("表情: surprised → neutral", act([expr("surprised"), expr("neutral")])),
    ("上を向いてうなずく（上を向いたまま）", act([look("up", "normal"), nod(2)])),
    ("正面", act([look("center")])),
]

# Part C (v1): no motion. Faces, LED, volume (a beep) and brightness; the expected settings
# are checked from the device's "setting" records.
SETTING_ITEMS = [
    ("表情: angry → sleepy", act([expr("angry"), expr("sleepy")]), None),
    ("表情: doubt → neutral", act([expr("doubt"), expr("neutral")]), None),
    ("LED: 青", act([tool("set_led", color="blue")]), {"led": "blue"}),
    (
        "LED: 水色 → ピンク",
        act([tool("set_led", color="light_blue"), tool("set_led", color="pink")]),
        {"led": "pink"},
    ),
    ("LED: 消灯", act([tool("set_led", color="off")]), {"led": "off"}),
    ("音量 50（ピッ）", act([tool("set_volume", level=50)]), {"volume": 50}),
    (
        "音量 +20 → +100 は 100 で止まる",
        act(
            [
                tool("adjust_volume", direction="up", amount="normal"),
                tool("adjust_volume", direction="up", by=100),
            ]
        ),
        {"volume": 100},
    ),
    ("消音（鳴らない）", act([tool("set_volume", level=0)]), {"volume": 0}),
    ("音量 50 に戻す", act([tool("set_volume", level=50)]), {"volume": 50}),
    (
        "明るさ 0 は下限 5 になる（顔は見える）",
        act([tool("set_brightness", level=0)]),
        {"brightness": 5},
    ),
    (
        "明るさ 5 で暗く → 5 のまま",
        act([tool("adjust_brightness", direction="down", amount="large")]),
        {"brightness": 5},
    ),
    ("明るさ 80", act([tool("set_brightness", level=80)]), {"brightness": 80}),
]

# Part D (v1): head motion (look with degrees, turn, diagonals, shake, bow).
MOTION_ITEMS = [
    ("右に 45°（絶対）", act([look_deg("right", 45)])),
    ("さらに右（端なので clamped、動かない）", act([turn("right", "slight")])),
    ("正面", act([look("center")])),
    ("上に 90°（上限で止まる、clamped）", act([look_deg("up", 90)])),
    ("正面", act([look("center")])),
    ("今の向きから左に 20°", act([turn("left", degrees=20)])),
    ("右上（normal）", act([look("up_right")])),
    ("左下に 10°（下は 0° で止まる、clamped）", act([look_deg("down_left", 10)])),
    ("正面", act([look("center")])),
    ("首を横に 2回振る", act([tool("shake", count=2)])),
    ("お辞儀（床からなので、20° に上げてから床まで下げる）", act([tool("bow")])),
    ("うなずき 5回", act([nod(5)])),
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
        elif s["k"] == "led":
            parts.append(f"led {s['color']}")
        elif s["k"] in ("volume", "brightness"):
            parts.append(f"{s['k']} {s['level']}" if "level" in s else f"{s['k']} {s['delta']:+d}")
        elif s["k"] == "pause":
            parts.append(f"hold {s['ms']}ms")
        else:
            clamp = " (clamped)" if s["clamped"] else ""
            parts.append(
                f"yaw {s['yaw']:+d} pitch {s['pitch']:+d} raw ({s['yaw_raw']},{s['pitch_raw']}) "
                f"{s['ms']}ms{clamp}"
            )
    return "; ".join(parts) or "(no action)"


def run_item(
    dev: Device,
    label: str,
    line: str,
    expect: str | None,
    f,
    keep: list,
    want: dict | None = None,
) -> None:
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
        if want:  # before check(keep), which clears keep
            got = {}
            for r in keep + dev.pending:
                if r.get("t") == "setting" and r.get("seq") == a["seq"]:
                    got[r["what"]] = r.get("level", r.get("color"))
            print(f"    settings: {got}", flush=True)
            if any(got.get(k) != v for k, v in want.items()):
                raise Stopped(f"settings: want {want}, got {got}")
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


def stop_during_bow(dev, keep: list, now=time.monotonic, sleep=time.sleep) -> dict:
    """Sends a bow, `!stop` in the middle of its hold; checks the stop was immediate.

    The firmware may print `stop` and `act_done` in either order, so both are waited for and
    the latency is taken at the later one. Raises Stopped when the bow was not stopped at once
    (not aborted, servo power not cut, over 500 ms, or the stop did not land in the hold).
    """
    dev.send(act([tool("bow")]))
    a = dev.wait_for("act", 10.0, keep)
    first = a["steps"][0]
    if first["k"] != "move":
        raise Stopped(f"bow plan does not start with the down move: {first}")
    down_ms = first["ms"]
    sleep((down_ms + 250) / 1000)  # in the 500 ms hold
    t0 = now()
    dev.send("!stop")
    seen: list[dict] = []
    # wait_for passes over (and records in `seen`) any other record, so an act_done printed
    # before the stop record is still found.
    stop = dev.wait_for("stop", 2.0, seen)
    done = next((r for r in seen if r.get("t") == "act_done"), None)
    if done is None:
        done = dev.wait_for("act_done", 2.0, seen)
    ms = (now() - t0) * 1000
    print(f"stop: {stop}\nact_done: aborted={done['aborted']} in {ms:.0f} ms", flush=True)
    if not done["aborted"] or stop.get("vm_off") != 0 or ms > 500:
        raise Stopped("bow was not stopped at once")
    if not (done["ms"] < done["planned_ms"] and down_ms <= done["ms"] < down_ms + 500):
        raise Stopped(f"the stop did not land in the bow hold: {done}, down {down_ms} ms")
    return {"stop": stop, "act_done": done, "ms": ms}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="serial port, e.g. COM3 or /dev/ttyACM0")
    ap.add_argument("--servo", action="store_true", help="turn servo output ON (head moves)")
    ap.add_argument("--section", choices=["act", "lm", "setting", "motion", "all"], default="all")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between items")
    ap.add_argument("--only", help="run only the items whose label or line contains this")
    ap.add_argument(
        "--stop-during-bow",
        action="store_true",
        help="send !stop while the bow holds; checks that the stop is immediate",
    )
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dev = Device(args.port, args.out.with_suffix(".log"))
    keep: list[dict] = []
    items = []
    if args.section in ("act", "all"):
        items += [(label, line, None, None) for label, line in ACT_ITEMS]
    if args.section in ("setting", "all"):
        items += [(label, line, None, want) for label, line, want in SETTING_ITEMS]
    if args.section in ("motion", "all"):
        items += [(label, line, None, None) for label, line in MOTION_ITEMS]
    if args.section in ("lm", "all"):
        items += [(text, text, expect, None) for text, expect in LM_ITEMS]
    if args.only:
        items = [it for it in items if args.only in it[0] or args.only in it[1]]
        if not items:
            ap.error(f"no item matches --only {args.only!r}")
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
                # The device prints the centering plan ('act') before the 'servo' record, so
                # wait_for("servo") has already passed it; wait for its completion instead.
                dev.wait_for("act_done", 15.0, keep)
                check(keep)
            if args.stop_during_bow:
                stop_during_bow(dev, keep)
                keep.clear()  # the stop record is expected here; check() must not raise on it
                print("bow stop OK", flush=True)
                items = []
            for i, (label, line, expect, want) in enumerate(items):
                print(f"[{i + 1}/{len(items)}]", end=" ", flush=True)
                run_item(dev, label, line, expect, f, keep, want)
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
