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
