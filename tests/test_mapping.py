# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import pytest

from jtalm.action import AMOUNTS
from jtalm.action.mapping import (
    BOW_HOLD_MS,
    BOW_LIFT_DEG,
    DEFAULT_LIMITS,
    PITCH_DEG,
    YAW_DEG,
    Limits,
    plan_v1,
    to_firmware_tenths,
)


def look(direction: str, amount: str, start: tuple[float, float] = (0, 0)) -> tuple[float, float]:
    (step,) = plan_v1([{"name": "look", "arguments": {"direction": direction, "amount": amount}}],
                      start)  # fmt: skip
    return step["yaw"], step["pitch"]


def test_yaw_positive_is_right_and_pitch_positive_is_up() -> None:
    assert look("right", "normal")[0] > 0
    assert look("left", "normal")[0] < 0
    assert look("up", "normal")[1] > 0
    assert look("down", "normal", start=(0, 30))[1] < 30


def test_horizontal_look_keeps_pitch_and_vertical_look_keeps_yaw() -> None:
    assert look("right", "slight", start=(0, 7))[1] == 7
    assert look("up", "slight", start=(-12, 0))[0] == -12


@pytest.mark.parametrize("amount", AMOUNTS)
def test_amount_angles_stay_within_the_limits(amount: str) -> None:
    assert 0 < YAW_DEG[amount] <= DEFAULT_LIMITS.yaw_max
    assert 0 < PITCH_DEG[amount] <= DEFAULT_LIMITS.pitch_max


def test_amount_order() -> None:
    yaws = [look("right", a)[0] for a in ("slight", "normal", "large")]
    assert yaws == sorted(yaws) and len(set(yaws)) == 3


def test_firmware_units_are_tenths_of_degree() -> None:
    assert to_firmware_tenths(20) == 200


def test_nod_is_around_the_current_pitch_and_accepts_integral_floats() -> None:
    from jtalm.action.mapping import NOD_PITCH_DEG, nod_targets

    up = nod_targets(2.0, base_pitch=10)
    assert [t.pitch_deg for t in up] == [10 - NOD_PITCH_DEG, 10] * 2
    near_limit = nod_targets(1, base_pitch=0, pitch_min=-10, pitch_max=15)
    assert [t.pitch_deg for t in near_limit] == [-10, -10 + NOD_PITCH_DEG]  # full swing, shifted
    floor = nod_targets(1, base_pitch=0, pitch_min=0, pitch_max=85)  # the K151 limits
    assert [t.pitch_deg for t in floor] == [0, NOD_PITCH_DEG]  # from the floor: upward
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
    # from the floor (pitch 0) the swing keeps its amplitude by going up, then returns
    assert moves(plan_v1([c("nod", count=1)], (0, 0))) == [(0, 0), (0, 14), (0, 0)]
    assert moves(plan_v1([c("nod", count=1)], (0, 10))) == [(0, 0), (0, 14), (0, 10)]
    # the final return is added only when the last target differs from the start (v0 firmware)
    assert moves(plan_v1([c("nod", count=1)], (0, 20))) == [(0, 6), (0, 20)]


def test_bow_lifts_first_when_below_the_lift_pitch() -> None:
    pause = {"kind": "pause", "ms": BOW_HOLD_MS}
    assert BOW_LIFT_DEG == 20
    # from the floor: lift, down to the floor, hold; the base equals the floor, so no return
    assert plan_v1([c("bow")], (0, 0)) == [
        {"kind": "move", "yaw": 0, "pitch": 20, "clamped": False},
        {"kind": "move", "yaw": 0, "pitch": 0, "clamped": False},
        pause,
    ]
    # already at or above the lift pitch: straight down, hold, back
    assert plan_v1([c("bow")], (0, 30)) == [
        {"kind": "move", "yaw": 0, "pitch": 0, "clamped": False},
        pause,
        {"kind": "move", "yaw": 0, "pitch": 30, "clamped": False},
    ]
    assert moves(plan_v1([c("bow")], (0, 20))) == [(0, 0), (0, 20)]
    # below the lift pitch: the yaw stays
    bow = plan_v1([c("bow")], (10, 10))
    assert moves(bow) == [(10, 20), (10, 0), (10, 10)]
    assert bow[2] == pause


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


def test_default_limits_are_the_k151_measurement() -> None:
    # 2026-10-02: the head rests on the floor at about +2.5 deg, so pitch stops at 0
    assert DEFAULT_LIMITS == Limits(-45, 45, 0, 85)
