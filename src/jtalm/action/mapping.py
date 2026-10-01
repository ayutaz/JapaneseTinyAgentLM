# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Map categorical Action calls to K151 servo targets (firmware dispatcher reference).

Conventions (docs/architecture.md section 7, docs/hardware.md section 3):
- yaw: 0 is straight ahead, positive is RIGHT. The official firmware takes 0.1 degree units.
- pitch: relative to the neutral angle, positive is UP.
The directions were confirmed on the K151 in milestone B2 (docs/hardware.md section 10); the
firmware converts degrees to raw servo positions (yaw raw decreases to the robot's right).
"""

from dataclasses import dataclass

from jtalm.action.schema import Call

YAW_DEG = {"slight": 10, "normal": 20, "large": 30}
PITCH_DEG = {"slight": 5, "normal": 10, "large": 15}
YAW_LIMIT_DEG = 30
PITCH_LIMIT_DEG = 15
NOD_PITCH_DEG = 14  # 8 was too small to notice on the K151 (motion test, 2026-09-30)


@dataclass(frozen=True)
class ServoTarget:
    """Target pose relative to neutral. An axis set to None keeps its current angle."""

    yaw_deg: int | None
    pitch_deg: int | None


def look_target(direction: str, amount: str) -> ServoTarget:
    if direction == "center":
        return ServoTarget(yaw_deg=0, pitch_deg=0)
    if direction in ("left", "right"):
        sign = 1 if direction == "right" else -1
        return ServoTarget(yaw_deg=sign * YAW_DEG[amount], pitch_deg=None)
    if direction in ("up", "down"):
        sign = 1 if direction == "up" else -1
        return ServoTarget(yaw_deg=None, pitch_deg=sign * PITCH_DEG[amount])
    raise ValueError(f"unknown direction: {direction}")


def nod_targets(
    count: int, base_pitch: int = 0, pitch_min: int | None = None, pitch_max: int | None = None
) -> list[ServoTarget]:
    """A nod is a down-and-back pitch swing of ``NOD_PITCH_DEG``, repeated ``count`` times.

    This matches firmware/jtalm_action: the swing starts from the current pitch, so a nod while
    looking up stays looking up. Near the lower limit the swing keeps its full amplitude by
    moving up (base 0 with a -10 limit swings between -10 and +4); the firmware then returns to
    ``base_pitch``. The schema accepts an integral float count (2.0); it is read as the integer.
    """
    low = base_pitch - NOD_PITCH_DEG
    if pitch_min is not None:
        low = max(low, pitch_min)
    high = low + NOD_PITCH_DEG
    if pitch_max is not None:
        high = min(high, pitch_max)
    return [ServoTarget(None, low), ServoTarget(None, high)] * int(count)


def to_firmware_tenths(deg: int) -> int:
    """The official StackChan firmware takes angles in 0.1 degree units."""
    return deg * 10


def servo_targets(call: Call) -> list[ServoTarget]:
    """Servo targets for one validated call (``set_expression`` does not move servos)."""
    name, args = call["name"], call["arguments"]
    if name == "look":
        return [look_target(args["direction"], args["amount"])]
    if name == "nod":
        return nod_targets(args["count"])
    return []
