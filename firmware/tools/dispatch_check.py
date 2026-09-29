# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 JapaneseTinyAgentLM contributors
"""Check the jtalm_action dispatcher (firmware A1-A3) against a Python reference.

The reference validates with `jtalm.action.parse_output` and maps with
`jtalm.action.mapping`; the device policy on top of it (soft limits, raw conversion,
motion timing, nod around the current pitch) is recomputed here from the constants in
`firmware/jtalm_action/main/action.h`. Every `JTALM {"t":"act"}` plan must match exactly.

Offline, on the output of `lm_serial.py --act` and its serial log:

    uv run python firmware/tools/dispatch_check.py \
        --results runs/device/a1/eval200.jsonl --log runs/device/a1/eval200.log

The log is also checked for the dispatcher's own records: each queued plan has an
`act_done` (not aborted, no error, on time), each face change a `face` record with a
stable CRC per expression, and there is no `fault` or `stop`.

On the device, validator fuzzing with `!act <json>` (needs pyserial):

    uv run --with pyserial python firmware/tools/dispatch_check.py \
        --port COM3 --fuzz 400 --out runs/device/a1/fuzz.jsonl
"""

import argparse
import json
import math
import random
import re
import sys
import time
from pathlib import Path

from jtalm.action import mapping
from jtalm.action.schema import AMOUNTS, DIRECTIONS, EXPRESSIONS, parse_output

ROOT = Path(__file__).resolve().parents[2]
ACTION_H = ROOT / "firmware" / "jtalm_action" / "main" / "action.h"
PREFIX = "JTALM "


def load_defines(path: Path = ACTION_H) -> dict[str, float]:
    """Numeric #defines of action.h (values like 30, (-40), 90.0)."""
    out: dict[str, float] = {}
    for m in re.finditer(r"^#define (\w+) \(?(-?[\d.]+)\)?", path.read_text("utf-8"), re.M):
        out[m.group(1)] = float(m.group(2))
    return out


class Policy:
    """Device policy constants, taken from action.h and cross-checked with mapping.py."""

    def __init__(self, d: dict[str, float]) -> None:
        assert d["ACT_YAW_LIMIT_DEG"] == mapping.YAW_LIMIT_DEG
        assert d["ACT_PITCH_LIMIT_DEG"] == mapping.PITCH_LIMIT_DEG
        assert d["ACT_NOD_PITCH_DEG"] == mapping.NOD_PITCH_DEG
        self.yaw_min = int(max(-mapping.YAW_LIMIT_DEG, d["HW_YAW_MIN_DEG"]))
        self.yaw_max = int(min(mapping.YAW_LIMIT_DEG, d["HW_YAW_MAX_DEG"]))
        self.pitch_min = int(max(-mapping.PITCH_LIMIT_DEG, d["HW_PITCH_MIN_DEG"]))
        self.pitch_max = int(min(mapping.PITCH_LIMIT_DEG, d["HW_PITCH_MAX_DEG"]))
        self.yaw_zero = d["SERVO_YAW_ZERO"]
        self.pitch_zero = d["SERVO_PITCH_ZERO"]
        self.vmax = d["MOTION_VMAX_DPS"]
        self.amax = d["MOTION_AMAX_DPS2"]
        self.nod_vmax = d["MOTION_NOD_VMAX_DPS"]
        self.nod_amax = d["MOTION_NOD_AMAX_DPS2"]
        self.tick = d["MOTION_TICK_MS"]
        self.gap = int(d["MOTION_CALL_GAP_MS"])

    def move_ms(self, deg: float, nod: bool = False) -> int:
        if deg <= 0:
            return 0
        vmax, amax = (self.nod_vmax, self.nod_amax) if nod else (self.vmax, self.amax)
        t = max(math.pi * deg / (2 * vmax), math.pi * math.sqrt(deg / (2 * amax)))
        return int(math.ceil(t * 1000 / self.tick - 1e-9) * self.tick)

    def plan(self, calls: list[dict], yaw: int, pitch: int) -> dict:
        steps: list[dict] = []
        total = 0

        def move(c: int, y: int, p: int, nod: bool = False) -> None:
            nonlocal yaw, pitch, total
            cy = min(max(y, self.yaw_min), self.yaw_max)
            cp = min(max(p, self.pitch_min), self.pitch_max)
            ms = self.move_ms(max(abs(cy - yaw), abs(cp - pitch)), nod)
            steps.append(
                {
                    "c": c,
                    "k": "move",
                    "yaw": cy,
                    "pitch": cp,
                    "yaw_raw": round(self.yaw_zero - cy * 16 / 5),
                    "pitch_raw": round(self.pitch_zero + cp * 16 / 5),
                    "ms": ms,
                    "clamped": int((cy, cp) != (y, p)),
                }
            )
            total += ms
            yaw, pitch = cy, cp

        start_yaw, start_pitch = yaw, pitch
        for c, call in enumerate(calls):
            if c:
                total += self.gap
            name = call["name"]
            if name == "set_expression":
                steps.append({"c": c, "k": "expr", "expr": call["arguments"]["expression"]})
            elif name == "look":
                (t,) = mapping.servo_targets(call)
                move(
                    c,
                    yaw if t.yaw_deg is None else t.yaw_deg,
                    pitch if t.pitch_deg is None else t.pitch_deg,
                )
            else:
                # The swing around the current pitch within the soft limits comes from
                # mapping.nod_targets; the device then returns to the pitch it started from.
                start = pitch
                targets = mapping.nod_targets(
                    call["arguments"]["count"], start, self.pitch_min, self.pitch_max
                )
                for t in targets:
                    move(c, yaw, t.pitch_deg, nod=True)
                if targets and targets[-1].pitch_deg != start:
                    move(c, yaw, start, nod=True)
        return {
            "from": [start_yaw, start_pitch],
            "steps": steps,
            "to": [yaw, pitch],
            "total_ms": total,
        }


def check_act(pol: Policy, act: dict, output: str, pose: list[int]) -> list[str]:
    """Differences between a device plan and the reference for `output` from `pose`."""
    errs = []
    parsed = parse_output(output)
    valid = parsed.schema_valid
    if bool(act["valid"]) != valid:
        errs.append(f"valid: device {act['valid']} python {valid} {parsed.errors}")
    calls = parsed.calls if valid else []
    if valid and act["calls"] != calls:
        errs.append(f"calls: device {act['calls']} python {calls}")
    ref = pol.plan(calls, *pose)
    for key in ("from", "steps", "to", "total_ms"):
        if act[key] != ref[key]:
            errs.append(f"{key}: device {act[key]} python {ref[key]}")
    if bool(act["queued"]) == bool(act["dropped"]) and act["steps"]:
        errs.append("queued/dropped")
    return errs


def next_pose(act: dict, pose: list[int]) -> list[int]:
    return act["to"] if act["queued"] else pose


def read_log(path: Path) -> list[dict]:
    recs = []
    for line in path.read_text("utf-8", errors="replace").splitlines():
        if line.startswith(PREFIX):
            try:
                recs.append(json.loads(line[len(PREFIX) :]))
            except json.JSONDecodeError:
                recs.append({"t": "garbled", "line": line})
    return recs


def check_log(recs: list[dict], acts: list[dict], tol_ms: float) -> dict:
    """Checks act_done / face / fault records in the serial log against the plans."""
    done = {r["seq"]: r for r in recs if r.get("t") == "act_done"}
    faces = [r for r in recs if r.get("t") == "face"]
    crc: dict[str, set[str]] = {}
    for f in faces:
        crc.setdefault(f["expr"], set()).add(f["crc"])
    problems = []
    over = []
    for a in acts:
        if not a["queued"]:
            continue
        d = done.get(a["seq"])
        if d is None:
            problems.append(f"seq {a['seq']}: no act_done")
            continue
        if d["aborted"] or d["err"] is not None or d["planned_ms"] != a["total_ms"]:
            problems.append(f"seq {a['seq']}: {d}")
        over.append(d["ms"] - d["planned_ms"])
        n_expr = sum(s["k"] == "expr" for s in a["steps"])
        n_face = sum(f["seq"] == a["seq"] for f in faces)
        if n_expr != n_face:
            problems.append(f"seq {a['seq']}: {n_expr} expr steps, {n_face} face records")
        if d["ms"] > d["planned_ms"] + tol_ms:
            problems.append(f"seq {a['seq']}: took {d['ms']} ms for {d['planned_ms']} ms")
    per_expr = {k: sorted(v) for k, v in crc.items()}
    all_crcs = [c for v in per_expr.values() for c in v]
    ticks = [d["tick_max_ms"] for d in done.values() if d["ticks"] > 1]
    return {
        "act_done": len(done),
        "faces": len(faces),
        "face_crc": per_expr,
        "face_crc_stable": all(len(v) == 1 for v in per_expr.values())
        and len(set(all_crcs)) == len(all_crcs),
        "face_draw_us_max": max((f["draw_us"] for f in faces), default=None),
        "face_push_us_max": max((f["push_us"] for f in faces), default=None),
        "overrun_ms_max": max(over, default=None),
        "tick_max_ms": max(ticks, default=None),
        "faults": [r for r in recs if r.get("t") in ("fault", "stop", "error", "garbled")],
        "problems": problems[:20],
        "n_problems": len(problems),
    }


def offline(args: argparse.Namespace, pol: Policy) -> dict:
    results = [json.loads(line) for line in args.results.open(encoding="utf-8")]
    pose = [0, 0]
    mism = []
    n_valid = n_queued = n_calls = 0
    for r in results:
        act = r["act"]
        errs = check_act(pol, act, r["output"], pose)
        if errs:
            mism.append({"i": r["i"], "prompt": r["prompt"], "errs": errs})
        pose = next_pose(act, pose)
        n_valid += act["valid"]
        n_queued += act["queued"]
        n_calls += len(act["calls"])
    out = {
        "n": len(results),
        "plans_match": len(results) - len(mism),
        "valid": n_valid,
        "queued": n_queued,
        "calls": n_calls,
        "mismatches": mism[:20],
    }
    if args.log:
        out["log"] = check_log(read_log(args.log), [r["act"] for r in results], args.tol_ms)
    return out


def fuzz_cases(n: int, seed: int) -> list[str]:
    """Valid and invalid Action JSON strings (one line, ASCII) for the validator."""
    rng = random.Random(seed)

    def call() -> dict:
        k = rng.randrange(3)
        if k == 0:
            args = {"direction": rng.choice(DIRECTIONS), "amount": rng.choice(AMOUNTS)}
            return {"name": "look", "arguments": args}
        if k == 1:
            return {"name": "set_expression", "arguments": {"expression": rng.choice(EXPRESSIONS)}}
        return {"name": "nod", "arguments": {"count": rng.randint(1, 3)}}

    def mutate(calls: list[dict]) -> object:
        calls = json.loads(json.dumps(calls))
        m = rng.randrange(14)
        c = calls[0] if calls else call()
        a = c["arguments"]
        if m == 0:
            a[rng.choice(list(a))] = rng.choice(["LEFT", "", "happy ", "center", 1, None])
        elif m == 1:
            c["extra"] = 1
        elif m == 2:
            a["speed"] = "fast"
        elif m == 3:
            del a[rng.choice(list(a))]
        elif m == 4:
            c["name"] = rng.choice(["look_at", "Look", "nod ", "speak"])
        elif m == 5:
            return {"name": "nod", "arguments": {"count": rng.choice([0, 4, -1, 2.0, True, "2"])}}
        elif m == 6:
            return [c, c]
        elif m == 7:
            return [c, call(), call()]
        elif m == 8:
            return c
        elif m == 9:
            return [c, [c]]
        elif m == 10:
            c["arguments"] = [a]
        elif m == 11:
            return {"calls": calls}
        elif m == 12:
            return [{"arguments": a, "name": c["name"]}]
        else:
            c["arguments"] = json.dumps(a)
        return calls

    raw = [
        "[]",
        " [ ] ",
        "[] x",
        "",
        "[",
        "[{}]",
        "null",
        '[{"name":"nod","arguments":{"count":2}},]',
        '[{"name":"nod","arguments":{"count":02}}]',
        '[{"name":"nod","arguments":{"count":2e0}}]',
        '[{"name":"nod","arguments":{"count":1.5}}]',
        '[{"name":"nod","arguments":{"count":3.0}},{"name":"nod","arguments":{"count":3}}]',
        '[{"name":"nod","arguments":{"count":3}},{"name":"nod","arguments":{"count":3}}]',
        '[{"name":"nod","arguments":{"count":1}},{"name":"nod","arguments":{"count":3}}]',
        '[{"name":"nod","arguments":5,"arguments":{"count":1}}]',
        '[{"name":"look","name":"nod","arguments":{"count":1}}]',
        '[{"name":"n\\u006fd","arguments":{"count":1}}]',
        '[{"name":"nod\\u3042","arguments":{"count":1}}]',
        '[{"name":"nod","arguments":{"count":1}}]\t ',
        '[{"name":"look","arguments":{"direction":"center","amount":"large"}}]',
        '[{"name":"look","arguments":{"direction":"center","amount":"large"}},'
        '{"name":"look","arguments":{"direction":"center","amount":"normal"}}]',
        '[{"name":"look","arguments":{"direction":"down","amount":"large"}},'
        '{"name":"nod","arguments":{"count":3}}]',
        '[{"name":"look","arguments":{"direction":"up","amount":"large"}},'
        '{"name":"nod","arguments":{"count":2}}]',
        '[{"name":"look","arguments":{"direction":"down","amount":"slight"}},'
        '{"name":"nod","arguments":{"count":1}}]',
        "[" + ",".join(['{"name":"nod","arguments":{"count":1}}'] * 3) + "]",
        '[{"name":"set_expression","arguments":{"expression":"happy"}},'
        '{"name":"look","arguments":{"direction":"left","amount":"large"}}]',
        '[{"name":"look","arguments":{"direction":"left","amount":"large"}},'
        '{"name":"look","arguments":{"direction":"right","amount":"large"}}]',
        '{"name":"nod","arguments":{"count":1}}',
        "[[[[[[[[[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]]]]]]]]",
        '["look"]',
        "[1,2]",
        "[true]",
        '[{"name":"nod","arguments":{"count":1}} ]',
        '[{"name":"nod","arguments":{"count":1}\n}]',
        '[{"name":"nod","arguments":{"count":1}}]]',
    ]
    cases = [c for c in raw if "\n" not in c]
    while len(cases) < n:
        k = rng.randrange(3)
        calls = [call() for _ in range(k)]
        if rng.random() < 0.5:
            cases.append(json.dumps(calls, separators=(",", ":")))
        else:
            sep = rng.choice([(",", ":"), (", ", ": "), (" ,", " : ")])
            cases.append(json.dumps(mutate(calls), separators=sep))
    return cases[:n]


def fuzz(args: argparse.Namespace, pol: Policy) -> dict:
    import serial  # only needed on the device

    port = serial.Serial(args.port, 115200, timeout=0.1)
    log = open(args.out.with_suffix(".log"), "w", encoding="utf-8", newline="")
    buf = b""
    pending: list[dict] = []

    def wait_for(kind: str, timeout: float = 20.0) -> dict:
        nonlocal buf
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while pending:
                rec = pending.pop(0)
                if rec.get("t") == kind:
                    return rec
            data = port.read(4096)
            if not data:
                continue
            buf += data
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                line = raw.decode("utf-8", errors="replace").rstrip("\r")
                log.write(line + "\n")
                if line.startswith(PREFIX):
                    pending.append(json.loads(line[len(PREFIX) :]))
        raise TimeoutError(kind)

    cases = fuzz_cases(args.fuzz, args.seed)
    pose = None
    mism = []
    n_valid = 0
    with args.out.open("w", encoding="utf-8") as f:
        for i, text in enumerate(cases):
            port.write(("!act " + text + "\n").encode("utf-8"))
            act = wait_for("act")
            if pose is None:
                pose = act["from"]
            errs = check_act(pol, act, text, pose)
            if errs:
                mism.append({"i": i, "json": text, "errs": errs})
            pose = next_pose(act, pose)
            n_valid += act["valid"]
            f.write(json.dumps({"i": i, "json": text, "act": act}, ensure_ascii=False) + "\n")
    port.close()
    log.close()
    return {"n": len(cases), "match": len(cases) - len(mism), "valid": n_valid, "mismatches": mism}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, help="lm_serial.py --act output (.jsonl)")
    ap.add_argument("--log", type=Path, help="serial log of the same run")
    ap.add_argument("--tol-ms", type=float, default=150.0, help="allowed overrun of a plan")
    ap.add_argument("--port", help="device port for --fuzz")
    ap.add_argument("--fuzz", type=int, default=0, help="number of !act cases to send")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, help="fuzz records (.jsonl) / summary path")
    args = ap.parse_args()

    pol = Policy(load_defines())
    if args.fuzz:
        if not args.port or not args.out:
            ap.error("--fuzz needs --port and --out")
        summary = fuzz(args, pol)
    elif args.results:
        summary = offline(args, pol)
    else:
        ap.error("give --results or --fuzz")
    text = json.dumps(summary, ensure_ascii=False, indent=1)
    if args.out:
        args.out.with_suffix(".summary.json").write_text(text, encoding="utf-8")
    print(text)
    bad = summary.get("mismatches") or summary.get("log", {}).get("n_problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
