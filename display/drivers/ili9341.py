import time
from typing import Any

from PIL import Image, ImageChops


WIDTH = 320
HEIGHT = 240


class ILI9341:
    def __init__(self, speed_hz: int = 16_000_000):
        import RPi.GPIO as GPIO
        import spidev

        self.gpio = GPIO
        self.dc = 25
        self.reset = 24
        self.last_timing_ms = (0.0, 0.0)
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup((self.dc, self.reset), GPIO.OUT, initial=GPIO.HIGH)
        self.spi: Any = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.mode = 0
        self.spi.max_speed_hz = speed_hz

    def initialize(self) -> None:
        self.gpio.output(self.reset, self.gpio.LOW)
        time.sleep(0.02)
        self.gpio.output(self.reset, self.gpio.HIGH)
        time.sleep(0.12)
        for command, data in (
            (0x01, b""),
            (0x28, b""),
            (0xEF, b"\x03\x80\x02"),
            (0xCF, b"\x00\xc1\x30"),
            (0xED, b"\x64\x03\x12\x81"),
            (0xE8, b"\x85\x00\x78"),
            (0xCB, b"\x39\x2c\x00\x34\x02"),
            (0xF7, b"\x20"),
            (0xEA, b"\x00\x00"),
            (0xC0, b"\x23"),
            (0xC1, b"\x10"),
            (0xC5, b"\x3e\x28"),
            (0xC7, b"\x86"),
            (0x36, b"\x28"),
            (0x3A, b"\x55"),
            (0xB1, b"\x00\x18"),
            (0xB6, b"\x08\x82\x27"),
            (0xF2, b"\x00"),
            (0x26, b"\x01"),
            (0xE0, bytes.fromhex("0f312b0c0e084e f13707100e0900")),
            (0xE1, bytes.fromhex("000e1403110731 c148080f0c310f")),
            (0x11, b""),
        ):
            self._write(command, data)
            if command in (0x01, 0x11):
                time.sleep(0.12)
        self._write(0x29)
        time.sleep(0.02)

    def show(self, image: Image.Image) -> None:
        self.show_region(image, (0, 0, WIDTH, HEIGHT))

    def show_region(
        self, image: Image.Image, box: tuple[int, int, int, int]
    ) -> None:
        if image.size != (WIDTH, HEIGHT):
            raise ValueError(f"image must be {WIDTH}x{HEIGHT}")
        left, top, right, bottom = box
        if not (0 <= left < right <= WIDTH and 0 <= top < bottom <= HEIGHT):
            raise ValueError("region is outside the display")

        conversion_start = time.perf_counter()
        data = rgb565(image.crop(box))
        conversion_ms = (time.perf_counter() - conversion_start) * 1000
        transfer_start = time.perf_counter()
        self._write(
            0x2A,
            left.to_bytes(2, "big") + (right - 1).to_bytes(2, "big"),
        )
        self._write(
            0x2B,
            top.to_bytes(2, "big") + (bottom - 1).to_bytes(2, "big"),
        )
        self._command(0x2C)
        self._data(data)
        self.last_timing_ms = (
            conversion_ms,
            (time.perf_counter() - transfer_start) * 1000,
        )

    def close(self) -> None:
        # The module has no reset pull-up; releasing RESET blanks the panel.
        self.gpio.output((self.dc, self.reset), self.gpio.HIGH)
        self.spi.close()

    def _write(self, command: int, data: bytes = b"") -> None:
        self._command(command)
        if data:
            self._data(data)

    def _command(self, value: int) -> None:
        self.gpio.output(self.dc, self.gpio.LOW)
        self.spi.xfer2([value])

    def _data(self, data: bytes | bytearray) -> None:
        self.gpio.output(self.dc, self.gpio.HIGH)
        for offset in range(0, len(data), 4096):
            self.spi.writebytes2(data[offset : offset + 4096])


def rgb565(image: Image.Image) -> bytes:
    red, green, blue = image.convert("RGB").split()
    high = ImageChops.add(
        red.point(lambda value: value & 0xF8),
        green.point(lambda value: value >> 5),
    )
    low = ImageChops.add(
        green.point(lambda value: (value & 0x1C) << 3),
        blue.point(lambda value: value >> 3),
    )
    return Image.merge("LA", (high, low)).tobytes()
