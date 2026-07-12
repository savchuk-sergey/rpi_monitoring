import time
from typing import Any


NAV_WIDTH = 64
FOOTER_TOP = 192
Rect = tuple[int, int, int, int]
PREVIOUS_HITBOX: Rect = (0, FOOTER_TOP, 61, 240)
MODE_HITBOX: Rect = (67, FOOTER_TOP, 253, 240)
NEXT_HITBOX: Rect = (259, FOOTER_TOP, 320, 240)
GPU_HITBOX: Rect = (64, 82, 256, 146)


def move(index: int, count: int, delta: int) -> int:
    return (index + delta) % count if count else 0

def selected_index(
    nodes: list[dict[str, Any]], node_id: str | None, fallback: int = 0
) -> int:
    if node_id is not None:
        for index, node in enumerate(nodes):
            if node.get("node_id") == node_id:
                return index
    return min(max(0, fallback), max(0, len(nodes) - 1))


def touch_action(x: int, y: int, details: bool = False) -> str | None:
    hitboxes = (
        ("previous", PREVIOUS_HITBOX),
        ("mode", MODE_HITBOX),
        ("next", NEXT_HITBOX),
    )
    if details:
        hitboxes += (("gpu", GPU_HITBOX),)
    for action, (left, top, right, bottom) in hitboxes:
        if left <= x < right and top <= y < bottom:
            return action
    return None


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
