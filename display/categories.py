from dataclasses import dataclass
from typing import Any, Callable

from PIL import ImageDraw

from display.detail_model import (
    ChartMetric,
    ChartValueGetter,
    ScaleDefinition,
    ScaleMode,
    Threshold,
    ThresholdTone,
    ValueRow,
    ValueToneGetter,
    ValuesLayout,
    ValueTone,
)
from display.formatting import boolean, bytes_pair, clock, percent, power, rate, temperature, uptime


Icon = Callable[[ImageDraw.ImageDraw, tuple[int, int, int, int], str], None]


@dataclass(frozen=True)
class Category:
    id: str
    title: str
    icon: Icon
    available: Callable[[dict[str, Any]], bool]
    value_rows: tuple[ValueRow, ...]
    values_layout: ValuesLayout
    chart_metrics: tuple[ChartMetric, ...]

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("category id must not be empty")
        if not self.title:
            raise ValueError("category title must not be empty")
        if not self.value_rows:
            raise ValueError("category value rows must not be empty")
        if len({row.id for row in self.value_rows}) != len(self.value_rows):
            raise ValueError("value row ids must be unique")
        if len({metric.id for metric in self.chart_metrics}) != len(self.chart_metrics):
            raise ValueError("chart metric ids must be unique")
        if len(self.value_rows) > len(self.values_layout.row_y_positions):
            raise ValueError("category layout has too few row positions")


def _nested(*path: str) -> ChartValueGetter:
    def get(node: dict[str, Any], _: int) -> Any:
        value: Any = node
        for part in path:
            value = value.get(part, {}) if isinstance(value, dict) else None
        return value if value != {} else None

    return get


def _gpu_device(node: dict[str, Any], index: int) -> dict[str, Any]:
    devices = node.get("gpu") or []
    return devices[index % len(devices)] if devices else {}


def _gpu(field: str) -> ChartValueGetter:
    return lambda node, index: _gpu_device(node, index).get(field)


def _errors(node: dict[str, Any], _: int) -> int:
    return len(node.get("collector", {}).get("errors") or [])


def _collector_text(node: dict[str, Any], _: int, __: str) -> str:
    count = _errors(node, 0)
    return f"ERR {count}" if count else "OK"


def _collector_tone(node: dict[str, Any], _: int, __: str) -> ValueTone:
    return ValueTone.WARNING if _errors(node, 0) else ValueTone.NORMAL


def _health_tone(field: str) -> ValueToneGetter:
    return lambda node, _, __: (
        ValueTone.CRITICAL
        if node.get("health", {}).get(field) is True
        else ValueTone.NORMAL
    )


def draw_cpu(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str) -> None:
    left, top, right, bottom = box
    draw.rectangle((left + 7, top + 7, right - 7, bottom - 7), outline=fill, width=2)
    for offset in (10, 16, 22):
        draw.line((left + offset, top + 2, left + offset, top + 7), fill=fill, width=2)
        draw.line((left + offset, bottom - 7, left + offset, bottom - 2), fill=fill, width=2)
        draw.line((left + 2, top + offset, left + 7, top + offset), fill=fill, width=2)
        draw.line((right - 7, top + offset, right - 2, top + offset), fill=fill, width=2)


def draw_memory(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str) -> None:
    left, top, right, bottom = box
    draw.rectangle((left + 2, top + 8, right - 2, bottom - 7), outline=fill, width=2)
    for x in range(left + 7, right - 4, 7):
        draw.rectangle((x, top + 12, x + 4, bottom - 12), outline=fill)
        draw.line((x, bottom - 7, x, bottom - 3), fill=fill)


def draw_gpu(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str) -> None:
    left, top, right, bottom = box
    draw.rectangle((left + 2, top + 7, right - 5, bottom - 5), outline=fill, width=2)
    center = (left + 17, top + 17)
    draw.ellipse((center[0] - 7, center[1] - 7, center[0] + 7, center[1] + 7), outline=fill, width=2)
    draw.line((right - 5, top + 12, right, top + 12), fill=fill, width=2)
    draw.line((right - 5, top + 20, right, top + 20), fill=fill, width=2)


def draw_storage(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str) -> None:
    left, top, right, bottom = box
    draw.ellipse((left + 4, top + 2, right - 4, top + 12), outline=fill, width=2)
    draw.rectangle((left + 4, top + 7, right - 4, bottom - 5), outline=fill, width=2)
    draw.ellipse((left + 4, bottom - 13, right - 4, bottom - 3), outline=fill, width=2)


def draw_network(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str) -> None:
    left, top, right, bottom = box
    draw.line((left + 3, top + 10, right - 6, top + 10), fill=fill, width=2)
    draw.line((right - 11, top + 5, right - 5, top + 10, right - 11, top + 15), fill=fill, width=2)
    draw.line((right - 3, bottom - 10, left + 6, bottom - 10), fill=fill, width=2)
    draw.line((left + 11, bottom - 15, left + 5, bottom - 10, left + 11, bottom - 5), fill=fill, width=2)


def draw_health(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str) -> None:
    left, top, right, bottom = box
    points = ((left + 16, top + 2), (right - 3, top + 7), (right - 6, bottom - 8), (left + 16, bottom - 2), (left + 3, bottom - 8), (left + 1, top + 7))
    draw.polygon(points, outline=fill)
    draw.line((left + 6, top + 18, left + 11, top + 18, left + 14, top + 12, left + 18, top + 23, left + 21, top + 18, right - 6, top + 18), fill=fill, width=2)


def _available(node: dict[str, Any], prefix: str, fallback: bool) -> bool:
    capabilities = node.get("capabilities")
    if not isinstance(capabilities, dict):
        return fallback
    matches = [value for key, value in capabilities.items() if key.startswith(prefix)]
    return fallback if not matches else any(value.get("supported") is True for value in matches)


STANDARD_VALUES_LAYOUT = ValuesLayout(
    row_y_positions=(91, 112, 133, 154, 175),
)

HEALTH_VALUES_LAYOUT = ValuesLayout(
    title="SYSTEM HEALTH",
    title_y=54,
    row_y_positions=(80, 103, 126, 149, 172),
)

PERCENT_SCALE = ScaleDefinition(
    ScaleMode.FIXED,
    minimum=0.0,
    maximum=100.0,
)

TEMPERATURE_SCALE = ScaleDefinition(
    ScaleMode.FIXED,
    minimum=20.0,
    maximum=100.0,
)

DYNAMIC_SCALE = ScaleDefinition(
    ScaleMode.DYNAMIC_ZERO_BASED,
    minimum=0.0,
    maximum=None,
    step=10.0,
)

PERCENT_THRESHOLDS = (
    Threshold(80.0, ThresholdTone.WARNING),
    Threshold(95.0, ThresholdTone.CRITICAL),
)

TEMPERATURE_THRESHOLDS = (
    Threshold(80.0, ThresholdTone.WARNING),
    Threshold(90.0, ThresholdTone.CRITICAL),
)


CATEGORIES = (
    Category(
        "cpu",
        "CPU",
        draw_cpu,
        lambda node: _available(node, "cpu.", bool(node.get("cpu"))),
        (
            ValueRow("load", "LOAD", lambda node, _, __: percent(node.get("cpu", {}).get("usage_percent"))),
            ValueRow("temperature", "TEMP", lambda node, _, __: temperature(node.get("cpu", {}).get("temperature_c"), unsupported=True)),
            ValueRow("power", "POWER", lambda node, _, __: power(node.get("cpu", {}).get("power_w"), unsupported=True)),
            ValueRow("clock", "CLOCK", lambda node, _, __: clock(node.get("cpu", {}).get("clock_mhz"))),
        ),
        STANDARD_VALUES_LAYOUT,
        (
            ChartMetric("load", "LOAD", "%", _nested("cpu", "usage_percent"), PERCENT_SCALE, PERCENT_THRESHOLDS),
            ChartMetric("temperature", "TEMP", "C", _nested("cpu", "temperature_c"), TEMPERATURE_SCALE, TEMPERATURE_THRESHOLDS),
            ChartMetric("clock", "CLOCK", "MHz", _nested("cpu", "clock_mhz"), DYNAMIC_SCALE),
            ChartMetric("power", "PWR", "W", _nested("cpu", "power_w"), DYNAMIC_SCALE),
        ),
    ),
    Category(
        "memory",
        "MEMORY",
        draw_memory,
        lambda node: _available(node, "memory.", bool(node.get("memory"))),
        (
            ValueRow("ram_load", "RAM LOAD", lambda node, _, __: percent(node.get("memory", {}).get("usage_percent"))),
            ValueRow("used", "USED", lambda node, _, __: bytes_pair(node.get("memory", {}).get("used_bytes"), node.get("memory", {}).get("total_bytes"))),
            ValueRow("swap", "SWAP", lambda node, _, __: bytes_pair(node.get("memory", {}).get("swap_used_bytes"), node.get("memory", {}).get("swap_total_bytes"), zero_is_off=True)),
            ValueRow("psi", "PSI", lambda node, _, __: percent(node.get("memory", {}).get("pressure_some_percent"))),
        ),
        STANDARD_VALUES_LAYOUT,
        (
            ChartMetric("ram", "RAM", "%", _nested("memory", "usage_percent"), PERCENT_SCALE, PERCENT_THRESHOLDS),
            ChartMetric("swap", "SWAP", "%", _nested("memory", "swap_usage_percent"), PERCENT_SCALE, PERCENT_THRESHOLDS),
            ChartMetric("psi", "PSI", "%", _nested("memory", "pressure_some_percent"), PERCENT_SCALE, PERCENT_THRESHOLDS),
        ),
    ),
    Category(
        "gpu",
        "GRAPHICS",
        draw_gpu,
        lambda node: _available(node, "gpu.", bool(node.get("gpu"))),
        (
            ValueRow("gpu_name", "GPU NAME", lambda node, index, __: str(_gpu_device(node, index).get("name") or "N/A"), fit_width=205),
            ValueRow("load", "LOAD", lambda node, index, __: percent(_gpu_device(node, index).get("usage_percent"))),
            ValueRow("temperature_power", "TEMP / PWR", lambda node, index, __: f"{temperature(_gpu_device(node, index).get('temperature_c'))} / {power(_gpu_device(node, index).get('power_w'))}"),
            ValueRow("vram", "VRAM", lambda node, index, __: bytes_pair(_gpu_device(node, index).get("memory_used_bytes"), _gpu_device(node, index).get("memory_total_bytes"))),
            ValueRow("fan_clock", "FAN / CLK", lambda node, index, __: f"{percent(_gpu_device(node, index).get('fan_percent'))} / {clock(_gpu_device(node, index).get('clock_mhz'))}"),
        ),
        STANDARD_VALUES_LAYOUT,
        (
            ChartMetric("load", "LOAD", "%", _gpu("usage_percent"), PERCENT_SCALE, PERCENT_THRESHOLDS),
            ChartMetric("temperature", "TEMP", "C", _gpu("temperature_c"), TEMPERATURE_SCALE, TEMPERATURE_THRESHOLDS),
            ChartMetric("vram", "VRAM", "%", _gpu("memory_usage_percent"), PERCENT_SCALE, PERCENT_THRESHOLDS),
            ChartMetric("power", "PWR", "W", _gpu("power_w"), DYNAMIC_SCALE),
        ),
    ),
    Category(
        "storage",
        "STORAGE",
        draw_storage,
        lambda node: _available(node, "storage.", node.get("storage", {}).get("usage_percent") is not None),
        (
            ValueRow("volume", "VOLUME", lambda node, _, __: str(node.get("storage", {}).get("name") or "N/A")),
            ValueRow("used", "USED", lambda node, _, __: percent(node.get("storage", {}).get("usage_percent"))),
            ValueRow("capacity", "CAPACITY", lambda node, _, __: bytes_pair(node.get("storage", {}).get("used_bytes"), node.get("storage", {}).get("total_bytes"))),
            ValueRow("read_write", "READ / WRITE", lambda node, _, __: f"{rate(node.get('storage', {}).get('read_bytes_per_second'))} / {rate(node.get('storage', {}).get('write_bytes_per_second'))}"),
            ValueRow("temperature", "TEMP", lambda node, _, __: temperature(node.get("storage", {}).get("temperature_c"), unsupported=True)),
        ),
        STANDARD_VALUES_LAYOUT,
        (
            ChartMetric("used", "USED", "%", _nested("storage", "usage_percent"), PERCENT_SCALE, PERCENT_THRESHOLDS),
            ChartMetric("read", "READ", "B/s", _nested("storage", "read_bytes_per_second"), DYNAMIC_SCALE),
            ChartMetric("write", "WRITE", "B/s", _nested("storage", "write_bytes_per_second"), DYNAMIC_SCALE),
            ChartMetric("temperature", "TEMP", "C", _nested("storage", "temperature_c"), TEMPERATURE_SCALE, TEMPERATURE_THRESHOLDS),
        ),
    ),
    Category(
        "network",
        "NETWORK",
        draw_network,
        lambda node: _available(node, "network.", bool(node.get("network", {}).get("interface"))),
        (
            ValueRow("interface", "INTERFACE", lambda node, _, __: str(node.get("network", {}).get("interface") or "N/A")),
            ValueRow("link", "LINK", lambda node, _, __: boolean(node.get("network", {}).get("link_up"))),
            ValueRow("down", "DOWN", lambda node, _, __: rate(node.get("network", {}).get("down_bytes_per_second"))),
            ValueRow("up", "UP", lambda node, _, __: rate(node.get("network", {}).get("up_bytes_per_second"))),
        ),
        STANDARD_VALUES_LAYOUT,
        (
            ChartMetric("down", "DOWN", "B/s", _nested("network", "down_bytes_per_second"), DYNAMIC_SCALE),
            ChartMetric("up", "UP", "B/s", _nested("network", "up_bytes_per_second"), DYNAMIC_SCALE),
        ),
    ),
    Category(
        "health",
        "HEALTH",
        draw_health,
        lambda node: True,
        (
            ValueRow("collector", "COLLECTOR", _collector_text, _collector_tone),
            ValueRow("undervoltage", "UNDERVOLTAGE", lambda node, _, __: boolean(node.get("health", {}).get("undervoltage")), _health_tone("undervoltage")),
            ValueRow("throttling", "THROTTLING", lambda node, _, __: boolean(node.get("health", {}).get("throttled")), _health_tone("throttled")),
            ValueRow("data_age", "DATA AGE", lambda _, __, age: age),
            ValueRow("uptime", "UPTIME", lambda node, _, __: uptime(node.get("health", {}).get("uptime_seconds"))),
        ),
        HEALTH_VALUES_LAYOUT,
        (
            ChartMetric("temperature", "TEMP", "C", _nested("cpu", "temperature_c"), TEMPERATURE_SCALE, TEMPERATURE_THRESHOLDS),
            ChartMetric("power", "PWR", "W", _nested("device", "power_w"), DYNAMIC_SCALE),
            ChartMetric("errors", "ERRORS", "", _errors, DYNAMIC_SCALE),
        ),
    ),
)


def category(category_id: str) -> Category:
    return next((item for item in CATEGORIES if item.id == category_id), CATEGORIES[0])


def default_category(node: dict[str, Any]) -> Category:
    cpu = category("cpu")
    return cpu if cpu.available(node) else next(item for item in CATEGORIES if item.available(node))


def category_at(x: int, y: int) -> Category | None:
    if not 32 <= y < 192 or not 0 <= x < 320:
        return None
    return CATEGORIES[(y - 32) // 80 * 3 + min(2, x // 107)]


def metric_at(category_id: str, x: int, y: int) -> ChartMetric | None:
    metrics = category(category_id).chart_metrics
    if not metrics or not 32 <= y < 56 or not 0 <= x < 320:
        return None
    return metrics[min(len(metrics) - 1, x * len(metrics) // 320)]


def detail_view_at(x: int, y: int) -> str | None:
    if not 56 <= y < 80 or not 0 <= x < 320:
        return None
    return "values" if x < 160 else "graph"
