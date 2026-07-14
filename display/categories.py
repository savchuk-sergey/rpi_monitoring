from dataclasses import dataclass
from typing import Any, Callable

from PIL import ImageDraw


Icon = Callable[[ImageDraw.ImageDraw, tuple[int, int, int, int], str], None]
ValueGetter = Callable[[dict[str, Any], int], Any]


@dataclass(frozen=True)
class Metric:
    id: str
    title: str
    unit: str
    minimum: float
    maximum: float | None
    value: ValueGetter

    @property
    def key(self) -> str:
        return self.id


@dataclass(frozen=True)
class Category:
    id: str
    title: str
    icon: Icon
    available: Callable[[dict[str, Any]], bool]
    metrics: tuple[Metric, ...]


def _nested(*path: str) -> ValueGetter:
    def get(node: dict[str, Any], _: int) -> Any:
        value: Any = node
        for part in path:
            value = value.get(part, {}) if isinstance(value, dict) else None
        return value if value != {} else None

    return get


def _gpu(field: str) -> ValueGetter:
    def get(node: dict[str, Any], index: int) -> Any:
        devices = node.get("gpu") or []
        return devices[index % len(devices)].get(field) if devices else None

    return get


def _errors(node: dict[str, Any], _: int) -> int:
    return len(node.get("collector", {}).get("errors") or [])


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


PERCENT = (0.0, 100.0)
CATEGORIES = (
    Category("cpu", "CPU", draw_cpu, lambda node: bool(node.get("cpu")), (
        Metric("load", "LOAD", "%", *PERCENT, _nested("cpu", "usage_percent")),
        Metric("temperature", "TEMP", "C", 20.0, 100.0, _nested("cpu", "temperature_c")),
        Metric("clock", "CLOCK", "MHz", 0.0, None, _nested("cpu", "clock_mhz")),
        Metric("power", "PWR", "W", 0.0, None, _nested("cpu", "power_w")),
    )),
    Category("memory", "MEMORY", draw_memory, lambda node: bool(node.get("memory")), (
        Metric("ram", "RAM", "%", *PERCENT, _nested("memory", "usage_percent")),
        Metric("swap", "SWAP", "%", *PERCENT, _nested("memory", "swap_usage_percent")),
        Metric("psi", "PSI", "%", *PERCENT, _nested("memory", "pressure_some_percent")),
    )),
    Category("gpu", "GRAPHICS", draw_gpu, lambda node: bool(node.get("gpu")), (
        Metric("load", "LOAD", "%", *PERCENT, _gpu("usage_percent")),
        Metric("temperature", "TEMP", "C", 20.0, 100.0, _gpu("temperature_c")),
        Metric("vram", "VRAM", "%", *PERCENT, _gpu("memory_usage_percent")),
        Metric("power", "PWR", "W", 0.0, None, _gpu("power_w")),
    )),
    Category("storage", "STORAGE", draw_storage,
             lambda node: node.get("storage", {}).get("usage_percent") is not None, (
        Metric("used", "USED", "%", *PERCENT, _nested("storage", "usage_percent")),
        Metric("read", "READ", "B/s", 0.0, None, _nested("storage", "read_bytes_per_second")),
        Metric("write", "WRITE", "B/s", 0.0, None, _nested("storage", "write_bytes_per_second")),
        Metric("temperature", "TEMP", "C", 20.0, 100.0, _nested("storage", "temperature_c")),
    )),
    Category("network", "NETWORK", draw_network,
             lambda node: bool(node.get("network", {}).get("interface")), (
        Metric("down", "DOWN", "B/s", 0.0, None, _nested("network", "down_bytes_per_second")),
        Metric("up", "UP", "B/s", 0.0, None, _nested("network", "up_bytes_per_second")),
    )),
    Category("health", "HEALTH", draw_health, lambda node: True, (
        Metric("temperature", "TEMP", "C", 20.0, 100.0, _nested("cpu", "temperature_c")),
        Metric("power", "PWR", "W", 0.0, None, _nested("device", "power_w")),
        Metric("errors", "ERRORS", "", 0.0, None, _errors),
    )),
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


def metric_at(category_id: str, x: int, y: int) -> Metric | None:
    metrics = category(category_id).metrics
    if not metrics or not 32 <= y < 56 or not 0 <= x < 320:
        return None
    return metrics[min(len(metrics) - 1, x * len(metrics) // 320)]

def detail_view_at(x: int, y: int) -> str | None:
    if not 56 <= y < 80 or not 0 <= x < 320:
        return None
    return "values" if x < 160 else "graph"
