# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""servo_test.stop_during_bow with a scripted fake device (no hardware, no pyserial)."""

import sys
import types
from pathlib import Path

import pytest

sys.modules.setdefault("serial", types.ModuleType("serial"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware" / "tools"))

import servo_test  # noqa: E402

PLAN = {"t": "act", "steps": [{"k": "move", "ms": 400}, {"k": "pause", "ms": 500}]}
STOP = {"t": "stop", "vm_off": 0}


def done(aborted=1, ms=650, planned=1300):
    return {"t": "act_done", "aborted": aborted, "ms": ms, "planned_ms": planned}


class FakeDev:
    def __init__(self, after_stop):
        self.after_stop = list(after_stop)
        self.queue = [PLAN]
        self.sent = []

    def send(self, line):
        self.sent.append(line)
        if line == "!stop":
            self.queue += self.after_stop

    def wait_for(self, kind, timeout, keep=None):
        while self.queue:
            rec = self.queue.pop(0)
            if keep is not None:
                keep.append(rec)
            if rec["t"] == kind:
                return rec
        raise TimeoutError(kind)


def run(after_stop):
    dev = FakeDev(after_stop)
    return servo_test.stop_during_bow(dev, [], now=lambda: 0.0, sleep=lambda s: None), dev


@pytest.mark.parametrize("order", [[STOP, done()], [done(), STOP]])
def test_ok_in_either_order(order):
    r, dev = run(order)
    assert r["act_done"]["aborted"] == 1 and dev.sent[-1] == "!stop"


@pytest.mark.parametrize(
    "order",
    [
        [STOP, done(aborted=0)],
        [{"t": "stop", "vm_off": 1}, done()],
        [STOP, done(ms=300)],  # still in the down move
        [STOP, done(ms=1000)],  # past the hold
        [STOP, done(ms=1300, planned=1300)],
    ],
)
def test_failures(order):
    with pytest.raises(servo_test.Stopped):
        run(order)


def test_missing_act_done_times_out():
    with pytest.raises(TimeoutError):
        run([STOP])
