import time
from typing import Any

from PIL import Image


WIDTH = 320
HEIGHT = 240


class ILI9341:
    def __init__(self, speed_hz: int = 16_000_000):
        import RPi.GPIO as GPIO
        import spidev

        self.gpio = GPIO
        self.dc = 25
        self.reset = 24
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
        if image.size != (WIDTH, HEIGHT):
            raise ValueError(f"image must be {WIDTH}x{HEIGHT}")
        self._write(0x2A, b"\x00\x00\x01\x3f")
        self._write(0x2B, b"\x00\x00\x00\xef")
        self._command(0x2C)
        self._data(rgb565(image))

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


def rgb565(image: Image.Image) -> bytearray:
    source = image.convert("RGB").tobytes()
    output = bytearray(len(source) // 3 * 2)
    for source_offset in range(0, len(source), 3):
        red, green, blue = source[source_offset : source_offset + 3]
        value = (red & 0xF8) << 8 | (green & 0xFC) << 3 | blue >> 3
        target = source_offset // 3 * 2
        output[target : target + 2] = value.to_bytes(2, "big")
    return output
