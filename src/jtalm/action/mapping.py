# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Map categorical Action calls to K151 servo targets (firmware dispatcher reference).

Conventions (docs/architecture.md, docs/hardware.md):
- yaw: 0 is straight ahead, positive is RIGHT. The official firmware takes 0.1 degree units.
- pitch: relative to the neutral angle, positive is UP.
The directions were confirmed on the K151 (docs/hardware.md); the
firmware converts degrees to raw servo positions (yaw raw decreases to the robot's right).
"""

from dataclasses import dataclass

YAW_DEG = {"slight": 10, "normal": 20, "large": 30}
PITCH_DEG = {"slight": 5, "normal": 10, "large": 15}
NOD_PITCH_DEG = 14  # 8 was too small to notice on the K151 (motion test, 2026-09-30)


@dataclass(frozen=True)
class ServoTarget:
    """Target pose relative to neutral. An axis set to None keeps its current angle."""

    yaw_deg: int | None
    pitch_deg: int | None


def nod_targets(
    count: int, base_pitch: int = 0, pitch_min: int | None = None, pitch_max: int | None = None
) -> list[ServoTarget]:
    """A nod is a down-and-back pitch swing of ``NOD_PITCH_DEG``, repeated ``count`` times.

    This matches firmware/jtalm_action: the swing starts from the current pitch, so a nod while
    looking up stays looking up. Near the lower limit the swing keeps its full amplitude by
    moving up (from the floor, base 0 with a 0 limit, it swings between 0 and +14); the firmware
    then returns to ``base_pitch``. The schema accepts an integral float count (2.0); it is read
    as the integer.
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


# -- schema v1 (docs/superpowers/specs/2026-10-02-action-schema-v1-design.md, section 6) --------


@dataclass(frozen=True)
class Limits:
    """Soft limits of the head in degrees (yaw positive right, pitch positive up)."""

    yaw_min: float = -45
    yaw_max: float = 45
    pitch_min: float = 0  # the K151 head rests on the floor at about +2.5 deg (2026-10-02)
    pitch_max: float = 85


DEFAULT_LIMITS = Limits()  # measured on the K151 (F2, 2026-10-02; docs/hardware.md)
SHAKE_YAW_DEG = 15
BOW_LIFT_DEG = 20  # a bow from below this pitch first lifts the head here, then lowers it
BOW_HOLD_MS = 500
ADJUST_STEP = {"slight": 10, "normal": 20, "large": 30}
BRIGHTNESS_MIN = 5  # the firmware floor; level 0 would hide the face

_YAW_SIGN = {"left": -1, "right": 1, "up_left": -1, "up_right": 1, "down_left": -1,
             "down_right": 1}  # fmt: skip
_PITCH_SIGN = {"up": 1, "down": -1, "up_left": 1, "up_right": 1, "down_left": -1,
               "down_right": -1}  # fmt: skip


def _deltas(args: dict) -> tuple[float | None, float | None]:
    """Yaw and pitch offsets of a look / turn call (None: the axis is not named)."""
    d = args["direction"]
    if "degrees" in args:
        yaw_mag = pitch_mag = float(args["degrees"])
    else:
        yaw_mag, pitch_mag = float(YAW_DEG[args["amount"]]), float(PITCH_DEG[args["amount"]])
    yaw = _YAW_SIGN[d] * yaw_mag if d in _YAW_SIGN else None
    pitch = _PITCH_SIGN[d] * pitch_mag if d in _PITCH_SIGN else None
    return yaw, pitch


def _move(yaw: float, pitch: float, limits: Limits) -> dict:
    y = min(max(yaw, limits.yaw_min), limits.yaw_max)
    p = min(max(pitch, limits.pitch_min), limits.pitch_max)
    return {"kind": "move", "yaw": y, "pitch": p, "clamped": (y, p) != (yaw, pitch)}


def plan_v1(
    calls: list[dict], start: tuple[float, float], limits: Limits = DEFAULT_LIMITS
) -> list[dict]:
    """Steps for one validated v1 output, starting from the pose ``start`` = (yaw, pitch).

    The firmware dispatcher (firmware/jtalm_action) must produce the same targets; it adds the
    motion timing and 200 ms between the two calls itself.
    """
    yaw, pitch = start
    steps: list[dict] = []

    def move(y: float, p: float) -> None:
        nonlocal yaw, pitch
        step = _move(y, p, limits)
        steps.append(step)
        yaw, pitch = step["yaw"], step["pitch"]

    def back_to(y: float, p: float) -> None:
        """The final return of nod / shake / bow, only when the pose differs (as in v0)."""
        if (yaw, pitch) != (y, p):
            move(y, p)

    for call in calls:
        name, args = call["name"], call["arguments"]
        if name in ("look", "turn"):
            if args["direction"] == "center":
                move(0, 0)
                continue
            dy, dp = _deltas(args)
            if name == "look":
                move(yaw if dy is None else dy, pitch if dp is None else dp)
            else:
                move(yaw + (dy or 0), pitch + (dp or 0))
        elif name == "nod":
            base = pitch
            for t in nod_targets(int(args["count"]), base, int(limits.pitch_min),
                                 int(limits.pitch_max)):  # fmt: skip
                move(yaw, float(t.pitch_deg))
            back_to(yaw, base)
        elif name == "shake":
            base = yaw
            for _ in range(int(args["count"])):
                move(base + SHAKE_YAW_DEG, pitch)
                move(base - SHAKE_YAW_DEG, pitch)
            back_to(base, pitch)
        elif name == "bow":
            base = pitch
            if pitch < BOW_LIFT_DEG:  # from the floor a bow would not move: lift first
                move(yaw, BOW_LIFT_DEG)
            move(yaw, limits.pitch_min)
            steps.append({"kind": "pause", "ms": BOW_HOLD_MS})
            back_to(yaw, base)
        elif name == "set_expression":
            steps.append({"kind": "expr", "expression": args["expression"]})
        elif name == "set_led":
            steps.append({"kind": "led", "color": args["color"]})
        elif name in ("set_volume", "set_brightness"):
            steps.append({"kind": name.removeprefix("set_"), "level": int(args["level"])})
        elif name in ("adjust_volume", "adjust_brightness"):
            size = int(args["by"]) if "by" in args else ADJUST_STEP[args["amount"]]
            sign = 1 if args["direction"] == "up" else -1
            steps.append({"kind": name.removeprefix("adjust_"), "delta": sign * size})
        else:
            raise ValueError(f"unknown tool: {name}")
    return steps
