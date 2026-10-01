# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import pytest

from jtalm.action import AMOUNTS
from jtalm.action.mapping import (
    BOW_HOLD_MS,
    DEFAULT_LIMITS,
    PITCH_LIMIT_DEG,
    YAW_LIMIT_DEG,
    Limits,
    ServoTarget,
    look_target,
    plan_v1,
    servo_targets,
    to_firmware_tenths,
)


def test_yaw_positive_is_right() -> None:
    assert look_target("right", "normal").yaw_deg > 0
    assert look_target("left", "normal").yaw_deg < 0


def test_pitch_positive_is_up() -> None:
    assert look_target("up", "normal").pitch_deg > 0
    assert look_target("down", "normal").pitch_deg < 0


def test_horizontal_look_keeps_pitch_and_vertical_look_keeps_yaw() -> None:
    assert look_target("right", "slight").pitch_deg is None
    assert look_target("down", "slight").yaw_deg is None


def test_center_returns_to_neutral() -> None:
    assert look_target("center", "large") == ServoTarget(0, 0)


@pytest.mark.parametrize("amount", AMOUNTS)
def test_angles_grow_with_amount_and_stay_within_limits(amount: str) -> None:
    yaw = look_target("right", amount).yaw_deg
    pitch = look_target("up", amount).pitch_deg
    assert 0 < yaw <= YAW_LIMIT_DEG
    assert 0 < pitch <= PITCH_LIMIT_DEG


def test_amount_order() -> None:
    yaws = [look_target("right", a).yaw_deg for a in ("slight", "normal", "large")]
    assert yaws == sorted(yaws) and len(set(yaws)) == 3


def test_nod_repeats_count_times_and_returns_to_neutral() -> None:
    targets = servo_targets({"name": "nod", "arguments": {"count": 2}})
    assert len(targets) == 4
    assert targets[-1].pitch_deg == 0
    assert all(t.yaw_deg is None for t in targets)


def test_expression_does_not_move_servos() -> None:
    assert servo_targets({"name": "set_expression", "arguments": {"expression": "happy"}}) == []


def test_firmware_units_are_tenths_of_degree() -> None:
    assert to_firmware_tenths(20) == 200


def test_nod_is_around_the_current_pitch_and_accepts_integral_floats() -> None:
    from jtalm.action.mapping import NOD_PITCH_DEG, nod_targets

    up = nod_targets(2.0, base_pitch=10)
    assert [t.pitch_deg for t in up] == [10 - NOD_PITCH_DEG, 10] * 2
    near_limit = nod_targets(1, base_pitch=0, pitch_min=-10, pitch_max=15)
    assert [t.pitch_deg for t in near_limit] == [-10, -10 + NOD_PITCH_DEG]  # full swing, shifted
    capped = nod_targets(1, base_pitch=-10, pitch_min=-10, pitch_max=2)
    assert [t.pitch_deg for t in capped] == [-10, 2]


def c(name: str, **arguments: object) -> dict:
    return {"name": name, "arguments": arguments}


def moves(steps: list[dict]) -> list[tuple[float, float]]:
    return [(s["yaw"], s["pitch"]) for s in steps if s["kind"] == "move"]


def test_look_degrees_is_absolute_and_clamped() -> None:
    steps = plan_v1([c("look", direction="up", degrees=90)], start=(10, 0))
    assert steps == [{"kind": "move", "yaw": 10, "pitch": 85, "clamped": True}]
    steps = plan_v1([c("look", direction="right", degrees=45)], start=(-20, 5))
    assert steps == [{"kind": "move", "yaw": 45, "pitch": 5, "clamped": False}]


def test_look_amount_keeps_the_v0_angles_and_diagonals_move_both_axes() -> None:
    assert moves(plan_v1([c("look", direction="right", amount="normal")], (0, 7))) == [(20, 7)]
    assert moves(plan_v1([c("look", direction="up_left", amount="large")], (0, 0))) == [(-30, 15)]
    assert moves(plan_v1([c("look", direction="center", amount="normal")], (30, 9))) == [(0, 0)]


def test_turn_is_relative_to_the_current_pose_and_carries_between_calls() -> None:
    calls = [
        c("turn", direction="right", amount="slight"),
        c("turn", direction="right", degrees=30),
    ]
    assert moves(plan_v1(calls, start=(10, 0))) == [(20, 0), (45, 0)]  # 50 clamped to 45


def test_shake_bow_and_nod() -> None:
    assert moves(plan_v1([c("shake", count=2)], (40, 0))) == [(45, 0), (25, 0), (45, 0), (25, 0),
                                                            (40, 0)]  # fmt: skip
    bow = plan_v1([c("bow")], (0, 10))
    assert moves(bow) == [(0, -10), (0, 10)]
    assert {"kind": "pause", "ms": BOW_HOLD_MS} in bow
    assert moves(plan_v1([c("nod", count=1)], (0, 0))) == [(0, -10), (0, 4), (0, 0)]
    # the final return is added only when the last target differs from the start (v0 firmware)
    assert moves(plan_v1([c("nod", count=1)], (0, 10))) == [(0, -4), (0, 10)]


def test_state_steps() -> None:
    calls = [c("set_led", color="blue"), c("adjust_volume", direction="down", amount="large")]
    steps = plan_v1(calls, (0, 0))
    assert steps == [{"kind": "led", "color": "blue"}, {"kind": "volume", "delta": -30}]
    assert plan_v1([c("set_brightness", level=0)], (0, 0)) == [{"kind": "brightness", "level": 0}]
    assert plan_v1([c("adjust_brightness", direction="up", by=15)], (0, 0)) == [
        {"kind": "brightness", "delta": 15}
    ]
    assert plan_v1([c("set_expression", expression="doubt")], (0, 0)) == [
        {"kind": "expr", "expression": "doubt"}
    ]


def test_default_limits_match_the_spec_target() -> None:
    assert DEFAULT_LIMITS == Limits(-45, 45, -10, 85)
