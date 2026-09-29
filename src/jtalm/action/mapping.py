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


def nod_targets(count: int, base_pitch: int = 0, pitch_min: int | None = None) -> list[ServoTarget]:
    """A nod is a small down-and-back pitch motion around the current pitch, ``count`` times.

    This matches firmware/jtalm_action: the head dips ``NOD_PITCH_DEG`` below ``base_pitch``
    (not below ``pitch_min``) and comes back, so a nod while looking up stays looking up. When the
    lower limit leaves less than half a nod of travel, the nod goes up from the limit instead.
    The schema accepts an integral float count (2.0); it is read as the integer.
    """
    low = base_pitch - NOD_PITCH_DEG
    if pitch_min is not None:
        low = max(low, pitch_min)
    high = base_pitch
    if high - low < NOD_PITCH_DEG // 2:
        high = low + NOD_PITCH_DEG
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
