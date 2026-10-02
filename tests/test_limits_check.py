# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""limits_check.judge: strict on the tested axis, looser on the untouched one."""

import sys
import types
from pathlib import Path

sys.modules.setdefault("serial", types.ModuleType("serial"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware" / "tools"))

import limits_check  # noqa: E402


def test_k151_first_pose_is_ok():
    ng, tested, other = limits_check.judge("yaw", (28.75, 2.81), (30, 0))
    assert not ng and tested < 2.0 and other < 4.0


def test_tested_axis_beyond_2deg_is_ng():
    assert limits_check.judge("yaw", (27.5, 0.0), (30, 0))[0]
    assert limits_check.judge("pitch", (0.0, 32.5), (0, 30))[0]


def test_other_axis_beyond_4deg_is_ng():
    assert limits_check.judge("yaw", (30.0, 4.5), (30, 0))[0]
    assert limits_check.judge("pitch", (-3.0, 30.0), (0, 30))[0] is False
    assert limits_check.judge("pitch", (-4.5, 30.0), (0, 30))[0]


def test_other_axis_ok_for_pitch_axis_with_yaw_drift():
    assert not limits_check.judge("pitch", (-3.5, 29.0), (0, 30))[0]
