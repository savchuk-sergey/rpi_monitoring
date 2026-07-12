import time
from typing import Any


NAV_WIDTH = 64


def move(index: int, count: int, delta: int) -> int:
    return (index + delta) % count if count else 0


def touch_action(x: int) -> int:
    if x < NAV_WIDTH:
        return -1
    if x >= 320 - NAV_WIDTH:
        return 1
    return 0


def map_touch(raw_x: int, raw_y: int, calibration: dict[str, Any]) -> tuple[int, int]:
    if calibration.get("swap_xy"):
        raw_x, raw_y = raw_y, raw_x
    x = _scale(raw_x, calibration["raw_x_min"], calibration["raw_x_max"], 319)
    y = _scale(raw_y, calibration["raw_y_min"], calibration["raw_y_max"], 239)
    if calibration.get("invert_x"):
        x = 319 - x
    if calibration.get("invert_y"):
        y = 239 - y
    return x, y


class TouchDebouncer:
    def __init__(self, debounce_seconds: float = 0.25):
        self.debounce_seconds = debounce_seconds
        self.was_pressed = False
        self.last_event = 0.0

    def update(self, pressed: bool, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        event = pressed and not self.was_pressed and now - self.last_event >= self.debounce_seconds
        self.was_pressed = pressed
        if event:
            self.last_event = now
        return event


def _scale(value: int, low: int, high: int, output_max: int) -> int:
    if high <= low:
        raise ValueError("invalid calibration range")
    return max(0, min(output_max, round((value - low) * output_max / (high - low))))
