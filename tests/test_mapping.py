import pytest

from jtalm.action import AMOUNTS
from jtalm.action.mapping import (
    PITCH_LIMIT_DEG,
    YAW_LIMIT_DEG,
    ServoTarget,
    look_target,
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
