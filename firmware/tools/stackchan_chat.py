# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Talk to the jtalm_action firmware on a Stack-chan (K151) over USB serial.

    pip install pyserial
    python stackchan_chat.py COM3            # Linux: /dev/ttyACM0, macOS: /dev/cu.usbmodem*
    python stackchan_chat.py COM3 --servo    # also move the head (see below)

Type a Japanese request and press Enter; the device answers with the Action JSON and acts it
out: the face on the screen changes, and with --servo the head moves. Lines starting with "!"
are sent as firmware commands (for example "!servo on", "!stop", "!center", "!info").

The servos are off at boot (dry-run): the plan is computed and shown but the head does not move.
--servo sends "!servo on" first, which powers the servos and slowly centers the head. Keep
fingers and cables clear of the neck. Touching the screen, Ctrl+C or "!stop" stops the motion
and turns the servos off.

    準備ができました。依頼を入力してください（終了は Ctrl+C）。
    顔を右に45度向いて
    → 右を向く（正面から45°）  1350 ms
"""

import argparse
import json
import sys
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import serial

PREFIX = "JTALM "

DIR_JA = {"left": "左", "right": "右", "up": "上", "down": "下", "up_left": "左上",
          "up_right": "右上", "down_left": "左下", "down_right": "右下"}  # fmt: skip
AMOUNT_JA = {"slight": "少し", "normal": "", "large": "大きく"}
EXPR_JA = {"happy": "笑顔", "sad": "悲しい顔", "surprised": "驚いた顔", "neutral": "普通の顔",
           "angry": "怒った顔", "sleepy": "眠そうな顔", "doubt": "不思議そうな顔"}  # fmt: skip
COLOR_JA = {"red": "赤", "orange": "オレンジ", "yellow": "黄色", "green": "緑",
            "light_blue": "水色", "blue": "青", "purple": "紫", "pink": "ピンク",
            "white": "白"}  # fmt: skip
ADJUST_JA = {
    "adjust_volume": ("音量を", {"up": "上げる", "down": "下げる"}),
    "adjust_brightness": ("画面を", {"up": "明るくする", "down": "暗くする"}),
}


def describe_call(call: dict) -> str:
    name, a = call["name"], call["arguments"]
    if name in ("look", "turn"):
        if a["direction"] == "center":
            return "正面を向く"
        where = DIR_JA[a["direction"]]
        if name == "look":
            if "degrees" in a:
                return f"{where}を向く（正面から{a['degrees']}°）"
            return f"{AMOUNT_JA[a['amount']]}{where}を向く"
        if "degrees" in a:
            return f"今の向きから{where}へ{a['degrees']}°"
        return f"今の向きから{AMOUNT_JA[a['amount']]}{where}へ"
    if name == "nod":
        return f"{a['count']}回うなずく"
    if name == "shake":
        return f"{a['count']}回首を横に振る"
    if name == "bow":
        return "お辞儀する"
    if name == "set_expression":
        return f"{EXPR_JA[a['expression']]}にする"
    if name == "set_led":
        return "LED を消す" if a["color"] == "off" else f"LED を{COLOR_JA[a['color']]}にする"
    if name == "set_volume":
        return f"音量を{a['level']}にする"
    if name == "set_brightness":
        return f"画面の明るさを{a['level']}にする"
    head, verbs = ADJUST_JA[name]
    size = f"{a['by']}" if "by" in a else AMOUNT_JA[a["amount"]]
    return f"{head}{size}{verbs[a['direction']]}"


def describe(output: str) -> str:
    """A short Japanese description of an Action output ("何もしない" for [])."""
    try:
        calls = json.loads(output)
        return "、".join(describe_call(c) for c in calls) or "何もしない"
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return output


def show(rec: dict, verbose: bool) -> None:
    t = rec.get("t")
    if t == "ready":
        print("準備ができました。依頼を入力してください（終了は Ctrl+C）。", flush=True)
    elif t == "gen":
        gated = "（確信度が低いので何もしない）" if rec.get("gated") else ""
        output = rec.get("output", "")
        print(f"→ {describe(output)}  {rec.get('total_ms', 0):.0f} ms{gated}", flush=True)
        if verbose:
            print(f"  {output}", flush=True)
    elif t == "act" and not rec.get("valid", True):
        print(f"  実行しない: {rec.get('err')}", flush=True)
    elif t == "act" and any(s.get("clamped") for s in rec.get("steps", [])):
        print("  可動域の端で止めました", flush=True)
    elif t == "setting":
        # The device's record (servo.c): "what" is volume / brightness (with "level") or led
        # (with "color"). Anything else is printed as it came, never raised in the reader.
        kind = rec.get("what")
        what = {"volume": "音量", "brightness": "画面の明るさ", "led": "LED"}.get(kind, kind or "?")
        if kind == "led":
            color = rec.get("color")
            value = "消灯" if color == "off" else COLOR_JA.get(color, color or "?")
        else:
            value = rec.get("level", rec.get("color", "?"))
        failed = "" if rec.get("ok", 1) else "（失敗）"
        print(f"  {what}: {value}{failed}", flush=True)
    elif t == "servo" and "ping_ms" in rec:
        print(f"  servo: {rec.get('state')}", flush=True)
    elif t == "stop":
        print("  止めました（servo の電源を切りました）", flush=True)
    elif t in ("error", "fault"):
        print(f"  {t}: {json.dumps(rec, ensure_ascii=False)}", flush=True)
    elif verbose:
        print(f"  {json.dumps(rec, ensure_ascii=False)}", flush=True)


def reader(port: "serial.Serial", verbose: bool, stop: threading.Event, ready: threading.Event):
    buf = b""
    while not stop.is_set():
        data = port.read(4096)
        if not data:
            continue
        buf += data
        *lines, buf = buf.split(b"\n")
        for raw in lines:
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            if not line.startswith(PREFIX):
                continue
            try:
                rec = json.loads(line[len(PREFIX) :])
            except json.JSONDecodeError:
                continue
            if rec.get("t") == "ready":
                ready.set()
            show(rec, verbose)


def main() -> None:
    import serial  # pyserial: only needed to talk to the device

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("port", help="serial port, e.g. COM3 or /dev/ttyACM0")
    parser.add_argument("--servo", action="store_true", help="turn the servos on (the head moves)")
    parser.add_argument("--no-reset", action="store_true", help="do not reset the device first")
    parser.add_argument("--verbose", action="store_true", help="print every device record")
    args = parser.parse_args()
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    port = serial.Serial(args.port, 115200, timeout=0.1)
    if not args.no_reset:  # USB-Serial/JTAG: RTS pulse with DTR low restarts the app
        port.dtr = False
        port.rts = True
        time.sleep(0.2)
        port.rts = False
    stop, ready = threading.Event(), threading.Event()
    threading.Thread(target=reader, args=(port, args.verbose, stop, ready), daemon=True).start()
    if args.no_reset:
        print("依頼を入力してください（終了は Ctrl+C）。", flush=True)
    elif not ready.wait(30):
        print("起動の合図（ready）が来ません。port と firmware を確かめてください。", flush=True)
    if args.servo:
        port.write(b"!servo on\n")
    try:
        for line in sys.stdin:
            line = line.strip()
            if line:
                port.write(line.encode("utf-8") + b"\n")
    except KeyboardInterrupt:
        pass
    finally:
        port.write(b"!stop\n")  # stops any motion and turns the servos off
        time.sleep(0.3)
        stop.set()
        port.close()


if __name__ == "__main__":
    main()
