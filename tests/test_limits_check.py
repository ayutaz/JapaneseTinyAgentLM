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


def test_pitch_poses_end_at_the_firmware_lower_limit():
    from jtalm.action.mapping import DEFAULT_LIMITS

    assert limits_check.PITCH_MIN_DEG == DEFAULT_LIMITS.pitch_min == 0
    pitch = limits_check.poses("pitch", 85)
    assert pitch[0] == (0, 15) and pitch[-2:] == [(0, 85), (0, 0)]
    assert pitch.count((0, 0)) == 1  # the floor is also the center: the run ends there
    assert min(p for _, p in pitch) == limits_check.PITCH_MIN_DEG


def test_floor_pose_on_the_k151_is_ok():
    # 2026-10-02: the head rests on the floor at raw 626..629 (+1.9..+2.8 deg) for pitch 0
    for got in ((-0.31, 2.5), (-0.31, 1.88), (0.0, 2.81)):
        assert not limits_check.judge("pitch", got, (0, 0))[0]
    assert limits_check.judge("pitch", (0.0, 3.5), (0, 0))[0]  # more than the floor explains
    assert limits_check.judge("pitch", (0.0, 32.5), (0, 30))[0]  # not at the floor: strict
