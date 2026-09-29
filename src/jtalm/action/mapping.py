"""Map categorical Action calls to K151 servo targets (firmware dispatcher reference).

Conventions (docs/architecture.md section 7, docs/hardware.md section 3):
- yaw: 0 is straight ahead, positive is RIGHT. The official firmware takes 0.1 degree units.
- pitch: relative to the neutral angle, positive is UP.
The degree values are initial design targets and are confirmed on the device in milestone B2.
"""

from dataclasses import dataclass

from jtalm.action.schema import Call

YAW_DEG = {"slight": 10, "normal": 20, "large": 30}
PITCH_DEG = {"slight": 5, "normal": 10, "large": 15}
YAW_LIMIT_DEG = 30
PITCH_LIMIT_DEG = 15
NOD_PITCH_DEG = 8


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


def nod_targets(count: int) -> list[ServoTarget]:
    """A nod is a small down-and-back pitch motion, repeated ``count`` times."""
    return [ServoTarget(None, -NOD_PITCH_DEG), ServoTarget(None, 0)] * count


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
