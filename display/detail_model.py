from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class ScaleMode(Enum):
    FIXED = "fixed"
    DYNAMIC_ZERO_BASED = "dynamic_zero_based"
    DYNAMIC_RANGE = "dynamic_range"


class ThresholdTone(Enum):
    WARNING = "warning"
    CRITICAL = "critical"


class ValueTone(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ScaleDefinition:
    mode: ScaleMode
    minimum: float
    maximum: float | None
    step: float = 10.0

    def __post_init__(self) -> None:
        if self.mode is ScaleMode.FIXED:
            if self.maximum is None or self.maximum <= self.minimum:
                raise ValueError("fixed scale maximum must be greater than minimum")
        elif self.mode is ScaleMode.DYNAMIC_ZERO_BASED:
            if self.minimum != 0.0 or self.maximum is not None or self.step <= 0:
                raise ValueError("invalid dynamic zero-based scale")
        elif self.step <= 0:
            raise ValueError("scale step must be greater than zero")


@dataclass(frozen=True)
class Threshold:
    value: float
    tone: ThresholdTone


@dataclass(frozen=True)
class ValuesLayout:
    row_y_positions: tuple[int, ...]
    title: str | None = None
    title_y: int | None = None

    def __post_init__(self) -> None:
        if not self.row_y_positions:
            raise ValueError("row positions must not be empty")
        if (self.title is None) != (self.title_y is None):
            raise ValueError("title and title_y must be provided together")
        if any(y < 0 or y > 239 for y in self.row_y_positions):
            raise ValueError("row positions must be inside the display")
        if self.title_y is not None and not 0 <= self.title_y <= 239:
            raise ValueError("title_y must be inside the display")


Node = dict[str, Any]
ValueTextGetter = Callable[[Node, int, str], str]
ValueToneGetter = Callable[[Node, int, str], ValueTone]


def normal_value_tone(
    node: Node,
    resource_index: int,
    age: str,
) -> ValueTone:
    return ValueTone.NORMAL


@dataclass(frozen=True)
class ValueRow:
    id: str
    title: str
    text: ValueTextGetter
    tone: ValueToneGetter = normal_value_tone
    fit_width: int | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("value row id must not be empty")
        if not self.title:
            raise ValueError("value row title must not be empty")
        if self.fit_width is not None and self.fit_width <= 0:
            raise ValueError("fit width must be greater than zero")


ChartValueGetter = Callable[[Node, int], Any]


@dataclass(frozen=True)
class ChartMetric:
    id: str
    title: str
    unit: str
    value: ChartValueGetter
    scale: ScaleDefinition
    thresholds: tuple[Threshold, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("chart metric id must not be empty")
        if not self.title:
            raise ValueError("chart metric title must not be empty")
        if any(
            left.value >= right.value
            for left, right in zip(self.thresholds, self.thresholds[1:])
        ):
            raise ValueError("threshold values must be strictly increasing")
        if self.scale.mode is ScaleMode.DYNAMIC_RANGE:
            raise ValueError("dynamic range scale is not implemented")

    @property
    def key(self) -> str:
        return self.id
