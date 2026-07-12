import argparse
import json
import statistics
import time
from pathlib import Path

from PIL import Image, ImageDraw

from display.drivers.ili9341 import ILI9341
from display.drivers.xpt2046 import XPT2046


TARGETS = {
    "left": (20, 120),
    "right": (299, 120),
    "top": (160, 20),
    "bottom": (160, 219),
}


def collect(lcd: ILI9341, touch: XPT2046, label: str) -> tuple[int, int]:
    image = Image.new("RGB", (320, 240), "#101418")
    draw = ImageDraw.Draw(image)
    x, y = TARGETS[label]
    draw.ellipse((x - 12, y - 12, x + 12, y + 12), outline="white", width=3)
    draw.line((x - 18, y, x + 18, y), fill="yellow", width=2)
    draw.line((x, y - 18, x, y + 18), fill="yellow", width=2)
    lcd.show(image)

    deadline = time.monotonic() + 20
    while not touch.pressed and time.monotonic() < deadline:
        time.sleep(0.02)
    if not touch.pressed:
        raise TimeoutError(f"no touch for {label}")
    points = []
    while touch.pressed and len(points) < 25:
        points.append(touch.read())
        time.sleep(0.03)
    if len(points) < 5:
        raise RuntimeError(f"not enough samples for {label}")
    while touch.pressed:
        time.sleep(0.02)
    return int(statistics.median(x for x, _ in points)), int(
        statistics.median(y for _, y in points)
    )


def calculate(points: dict[str, tuple[int, int]]) -> dict:
    left, right = points["left"], points["right"]
    top, bottom = points["top"], points["bottom"]
    swap = abs(right[1] - left[1]) > abs(right[0] - left[0])
    if swap:
        points = {name: (y, x) for name, (x, y) in points.items()}
        left, right, top, bottom = (
            points["left"], points["right"], points["top"], points["bottom"]
        )
    raw_x_start, raw_x_end = _bounds(left[0], right[0], 20, 299, 319)
    raw_y_start, raw_y_end = _bounds(top[1], bottom[1], 20, 219, 239)
    return {
        "swap_xy": swap,
        "invert_x": raw_x_end < raw_x_start,
        "invert_y": raw_y_end < raw_y_start,
        "raw_x_min": round(min(raw_x_start, raw_x_end)),
        "raw_x_max": round(max(raw_x_start, raw_x_end)),
        "raw_y_min": round(min(raw_y_start, raw_y_end)),
        "raw_y_max": round(max(raw_y_start, raw_y_end)),
    }


def _bounds(start: int, end: int, start_pixel: int, end_pixel: int, maximum: int):
    slope = (end - start) / (end_pixel - start_pixel)
    return start - slope * start_pixel, start + slope * (maximum - start_pixel)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lcd = ILI9341(4_000_000)
    touch = XPT2046()
    try:
        lcd.initialize()
        points = {
            name: collect(lcd, touch, name)
            for name in ("left", "right", "top", "bottom")
        }
        calibration = calculate(points)
        args.output.write_text(json.dumps(calibration, indent=2) + "\n")
        print(json.dumps(calibration, indent=2))
    finally:
        touch.close()
        lcd.close()


if __name__ == "__main__":
    main()
