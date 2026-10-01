# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 JapaneseTinyAgentLM contributors
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
"""

import argparse
import json
import sys
import threading
import time

import serial

PREFIX = "JTALM "


def show(rec: dict, verbose: bool) -> None:
    t = rec.get("t")
    if t == "ready":
        print("準備ができました。依頼を入力してください（終了は Ctrl+C）。", flush=True)
    elif t == "gen":
        gated = "（確信度が低いので何もしない）" if rec.get("gated") else ""
        print(f"→ {rec.get('output')}  {rec.get('total_ms', 0):.0f} ms{gated}", flush=True)
    elif t == "act" and not rec.get("valid", True):
        print(f"  実行しない: {rec.get('err')}", flush=True)
    elif t == "servo" and "ping_ms" in rec:
        print(f"  servo: {rec.get('state')}", flush=True)
    elif t == "stop":
        print("  止めました（servo の電源を切りました）", flush=True)
    elif t in ("error", "fault"):
        print(f"  {t}: {json.dumps(rec, ensure_ascii=False)}", flush=True)
    elif verbose:
        print(f"  {json.dumps(rec, ensure_ascii=False)}", flush=True)


def reader(port: serial.Serial, verbose: bool, stop: threading.Event, ready: threading.Event):
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
