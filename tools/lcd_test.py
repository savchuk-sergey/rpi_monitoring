import argparse
import time

from PIL import Image, ImageDraw

from display.drivers.ili9341 import HEIGHT, WIDTH, ILI9341
from display.renderer import render


def pattern() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 20):
        draw.line((x, 0, x, HEIGHT - 1), fill="#555555")
    for y in range(0, HEIGHT, 20):
        draw.line((0, y, WIDTH - 1, y), fill="#555555")
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline="white", width=3)
    draw.line((0, 0, WIDTH - 1, HEIGHT - 1), fill="yellow", width=2)
    draw.line((0, HEIGHT - 1, WIDTH - 1, 0), fill="cyan", width=2)
    return image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speed-hz", type=int, default=16_000_000)
    parser.add_argument("--seconds", type=float, default=2)
    args = parser.parse_args()
    lcd = ILI9341(args.speed_hz)
    try:
        lcd.initialize()
        for name, image in (
            ("red", Image.new("RGB", (WIDTH, HEIGHT), "red")),
            ("green", Image.new("RGB", (WIDTH, HEIGHT), "green")),
            ("blue", Image.new("RGB", (WIDTH, HEIGHT), "blue")),
            ("white", Image.new("RGB", (WIDTH, HEIGHT), "white")),
            ("black", Image.new("RGB", (WIDTH, HEIGHT), "black")),
            ("pattern", pattern()),
            ("text", render(None)),
        ):
            print(name, flush=True)
            lcd.show(image)
            time.sleep(args.seconds)
        lcd.show(pattern())
    finally:
        lcd.close()


if __name__ == "__main__":
    main()
