# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Capture the device's serial log, optionally resetting it and answering prompts.

Run without adding a project dependency:

    uv run --no-project --with pyserial python firmware/tools/serial_capture.py \
        --port COM3 --reset --seconds 30 --out log.txt

`--send-on PATTERN TEXT` writes TEXT (with "\\r\\n") each time PATTERN appears in
the log, up to `--max-sends` times in total. `--until PATTERN` stops the capture
after PATTERN has appeared `--until-count` times.
"""

import argparse
import sys
import time

import serial


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="serial port, e.g. COM3 or /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--reset", action="store_true", help="hard reset via RTS first")
    ap.add_argument("--send-on", nargs=2, action="append", default=[], metavar=("PATTERN", "TEXT"))
    ap.add_argument("--max-sends", type=int, default=1)
    ap.add_argument("--until", default=None)
    ap.add_argument("--until-count", type=int, default=1)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    port = serial.Serial(args.port, args.baud, timeout=0.1)
    if args.reset:
        # USB-Serial/JTAG: DTR low + RTS high, then RTS low resets the chip
        # into the app (same sequence as esptool's hard reset).
        port.dtr = False
        port.rts = True
        time.sleep(0.2)
        port.rts = False

    out = open(args.out, "w", encoding="utf-8", newline="") if args.out else None
    buf = ""
    sends = 0
    hits = 0
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            data = port.read(4096)
            if not data:
                continue
            text = data.decode("utf-8", errors="replace")
            sys.stdout.write(text)
            sys.stdout.flush()
            if out:
                out.write(text)
                out.flush()
            buf += text
            # Only whole lines are matched, so a pattern is never seen twice.
            *lines, buf = buf.split("\n")
            for line in lines:
                for pattern, reply in args.send_on:
                    if pattern in line and sends < args.max_sends:
                        time.sleep(0.2)
                        port.write((reply + "\r\n").encode())
                        sends += 1
                if args.until and args.until in line:
                    hits += 1
            if args.until and hits >= args.until_count:
                break
    finally:
        port.close()
        if out:
            out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
