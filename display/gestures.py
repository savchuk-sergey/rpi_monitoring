from collections import deque
from dataclasses import dataclass
from enum import Enum
from statistics import median


class GestureKind(Enum):
    SHORT = "short"
    LONG = "long"


class GestureState(Enum):
    IDLE = "idle"
    PRESSED = "pressed"
    LONG_EMITTED = "long_emitted"
    WAIT_RELEASE = "wait_release"


@dataclass(frozen=True)
class TouchGesture:
    kind: GestureKind
    x: int
    y: int
    duration_seconds: float


class TouchRecognizer:
    def __init__(
        self,
        long_press_seconds: float = 0.65,
        movement_tolerance_pixels: int = 16,
        release_debounce_seconds: float = 0.15,
        minimum_short_press_seconds: float = 0.05,
    ) -> None:
        self.long_press_seconds = long_press_seconds
        self.movement_tolerance_pixels = movement_tolerance_pixels
        self.release_debounce_seconds = release_debounce_seconds
        self.minimum_short_press_seconds = minimum_short_press_seconds
        self.state = GestureState.IDLE
        self.started_at = 0.0
        self.blocked_until = 0.0
        self.origin = (0, 0)
        self.points: deque[tuple[int, int]] = deque(maxlen=5)

    def update(
        self,
        pressed: bool,
        x: int = 0,
        y: int = 0,
        now: float = 0.0,
    ) -> TouchGesture | None:
        if not pressed:
            return self._release(now)
        if self.state == GestureState.IDLE:
            if now < self.blocked_until:
                return None
            self.state = GestureState.PRESSED
            self.started_at = now
            self.origin = (x, y)
            self.points.clear()
            self.points.append((x, y))
            return None
        if self.state not in {
            GestureState.PRESSED,
            GestureState.LONG_EMITTED,
        }:
            return None

        self.points.append((x, y))
        current = self.position
        if max(abs(current[0] - self.origin[0]), abs(current[1] - self.origin[1])) > self.movement_tolerance_pixels:
            self.state = GestureState.WAIT_RELEASE
            return None
        if self.state == GestureState.LONG_EMITTED:
            return None
        duration = now - self.started_at
        if duration >= self.long_press_seconds:
            self.state = GestureState.LONG_EMITTED
            return TouchGesture(GestureKind.LONG, *current, duration)
        return None

    @property
    def position(self) -> tuple[int, int]:
        return (
            round(median(point[0] for point in self.points)),
            round(median(point[1] for point in self.points)),
        )

    def _release(self, now: float) -> TouchGesture | None:
        gesture = None
        if self.state == GestureState.PRESSED:
            duration = now - self.started_at
            if duration >= self.minimum_short_press_seconds:
                gesture = TouchGesture(GestureKind.SHORT, *self.position, duration)
        if self.state != GestureState.IDLE:
            self.blocked_until = now + self.release_debounce_seconds
        self.state = GestureState.IDLE
        return gesture
