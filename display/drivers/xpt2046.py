import statistics
from typing import Any


class XPT2046:
    def __init__(self, speed_hz: int = 2_000_000):
        import RPi.GPIO as GPIO
        import spidev

        self.gpio = GPIO
        self.irq = 17
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.irq, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self.spi: Any = spidev.SpiDev()
        self.spi.open(0, 1)
        self.spi.mode = 0
        self.spi.max_speed_hz = speed_hz

    @property
    def pressed(self) -> bool:
        return self.gpio.input(self.irq) == self.gpio.LOW

    def read(self, samples: int = 7) -> tuple[int, int]:
        xs = [self._channel(0xD0) for _ in range(samples)]
        ys = [self._channel(0x90) for _ in range(samples)]
        return int(statistics.median(xs)), int(statistics.median(ys))

    def close(self) -> None:
        self.spi.close()
        self.gpio.cleanup(self.irq)

    def _channel(self, command: int) -> int:
        result = self.spi.xfer2([command, 0, 0])
        return ((result[1] << 8) | result[2]) >> 3
