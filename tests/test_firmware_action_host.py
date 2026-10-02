# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""The firmware's Action validator and planner (firmware/jtalm_action/main/action.c), built for
the host, against the Python reference (firmware/tools/dispatch_check.py)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "firmware" / "tools"))
import dispatch_check  # noqa: E402


def _compiler() -> str | None:
    return shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")


@pytest.fixture(scope="module")
def act_host(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if _compiler() is None:
        pytest.skip("no C compiler on PATH")
    exe = tmp_path_factory.mktemp("act_host") / "act_host"
    main = ROOT / "firmware" / "jtalm_action" / "main"
    subprocess.run(
        [_compiler(), "-std=gnu11", "-O1", "-Wall", "-Wextra", "-I", str(main), "-o", str(exe),
         str(ROOT / "firmware" / "tools" / "act_host.c"), str(main / "action.c"), "-lm"],
        check=True,
    )  # fmt: skip
    return exe


def run_host(exe: Path, cases: list[str]) -> list[dict]:
    proc = subprocess.run(
        [str(exe)], input="\n".join(cases) + "\n", capture_output=True, text=True, check=True
    )
    return [json.loads(line) for line in proc.stdout.splitlines()]


def test_firmware_matches_python_on_fuzz_cases(act_host: Path) -> None:
    cases = dispatch_check.fuzz_cases(3000, seed=1)
    recs = run_host(act_host, cases)
    assert len(recs) == len(cases)
    pol = dispatch_check.Policy(dispatch_check.load_defines())
    summary = dispatch_check.compare_host(pol, cases, recs)
    assert summary["mismatches"] == [], summary["mismatches"][:5]


def _call(name: str, **arguments: object) -> dict:
    return {"name": name, "arguments": arguments}


# (calls, volume, brightness) after each line; the stored values carry over to the next line,
# starting from volume 50 and brightness 50 (servo.c: act_apply_level per step).
LEVEL_CASES = [
    ([_call("set_volume", level=0)], 0, 50),
    ([_call("adjust_volume", direction="down", amount="slight")], 0, 50),  # floor 0
    ([_call("adjust_volume", direction="up", amount="normal")], 20, 50),
    ([_call("adjust_volume", direction="up", by=100)], 100, 50),  # max 100
    ([_call("adjust_volume", direction="up", amount="large")], 100, 50),
    ([_call("set_volume", level=100)], 100, 50),
    ([_call("adjust_volume", direction="down", amount="large")], 70, 50),
    ([_call("adjust_volume", direction="down", by=25)], 45, 50),
    ([_call("set_volume", level=50.0)], 50, 50),
    ([_call("set_brightness", level=0)], 50, 5),  # floor 5
    ([_call("adjust_brightness", direction="down", amount="large")], 50, 5),
    ([_call("adjust_brightness", direction="up", amount="slight")], 50, 15),
    ([_call("set_brightness", level=4)], 50, 5),
    ([_call("set_brightness", level=5)], 50, 5),
    ([_call("set_brightness", level=100)], 50, 100),
    ([_call("adjust_brightness", direction="up", amount="normal")], 50, 100),  # max 100
    ([_call("adjust_brightness", direction="down", by=90)], 50, 10),
    ([_call("adjust_brightness", direction="down", by=6)], 50, 5),
    # two steps in one request apply in order
    ([_call("set_volume", level=90), _call("adjust_volume", direction="up", amount="normal")],
     100, 5),
    ([_call("set_brightness", level=80), _call("adjust_volume", direction="down", by=30)],
     70, 80),
    # an invalid request changes nothing
    ([_call("set_volume", level=101)], 70, 80),
]  # fmt: skip


def test_firmware_apply_level_set_and_adjust(act_host: Path) -> None:
    cases = [json.dumps(calls, separators=(",", ":")) for calls, _, _ in LEVEL_CASES]
    proc = subprocess.run(
        [str(act_host), "--levels", "50", "50"],
        input="\n".join(cases) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    got = [json.loads(line) for line in proc.stdout.splitlines()]
    want = [
        {"valid": int(i < len(LEVEL_CASES) - 1), "volume": v, "brightness": b}
        for i, (_, v, b) in enumerate(LEVEL_CASES)
    ]
    assert got == want
