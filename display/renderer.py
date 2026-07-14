from pathlib import Path
from typing import Any
from datetime import datetime, timezone
from math import ceil

from PIL import Image, ImageDraw, ImageFont

from display.categories import CATEGORIES, category
from display.history import HistoryStore, Sample
from display.navigation import DetailView, UiState, ViewMode


SIZE = (320, 240)
BACKGROUND = "#000400"
GREEN = "#43ff6b"
BRIGHT = "#c4ffcf"
MUTED = "#438d50"
RED = "#ff5c5c"
AMBER = "#ffb84d"
FONT_PATH = Path(__file__).with_name("assets") / "ShareTechMono-Regular.ttf"
HEADER_BOTTOM = 40
FOOTER_TOP = 192


def render(
    node: dict[str, Any] | None,
    position: tuple[int, int] = (0, 0),
    hub_online: bool = True,
    ui_state: UiState | None = None,
    history: HistoryStore | None = None,
    pressed_action: str | None = None,
    now: datetime | None = None,
) -> Image.Image:
    state = ui_state or UiState()
    image = Image.new("RGB", SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    fonts = {
        "tiny": _font(11),
        "small": _font(13),
        "detail": _font(15),
        "label": _font(18),
        "title": _font(22),
        "value": _font(38),
    }
    if node is None:
        _empty_state(draw, fonts, hub_online)
        _footer(draw, fonts, ViewMode.OVERVIEW, pressed_action)
        return image

    status, status_color = _status(node, hub_online)
    age = _age(node.get("received_at_utc") or node.get("timestamp_utc"), now)
    if state.mode == ViewMode.MENU:
        _menu(draw, fonts, node, state)
    elif state.mode == ViewMode.DETAIL:
        _detail_header(draw, fonts, node, position, state, status_color, age)
        _details(draw, fonts, node, state, history, age, now)
    else:
        _header(draw, fonts, node, position, status, status_color, age)
        cpu = node.get("cpu", {})
        gpu = node.get("gpu") or []
        power = node.get("device", {}).get("power_w")
        if power is None:
            power = cpu.get("power_w")
        if gpu:
            third = ("GPU", gpu[0].get("usage_percent"), "%")
        elif cpu.get("temperature_c") is not None:
            third = ("TEMP", cpu.get("temperature_c"), "C")
        elif node.get("storage", {}).get("usage_percent") is not None:
            third = ("DISK", node["storage"]["usage_percent"], "%")
        elif power is not None:
            third = ("PWR", power, "W")
        else:
            third = ("GPU", None, "%")
        metrics = (
            ("CPU", cpu.get("usage_percent"), "%"),
            ("RAM", node.get("memory", {}).get("usage_percent"), "%"),
            third,
        )
        for top, (label, value, unit) in zip((40, 91, 142), metrics):
            _metric_row(draw, fonts, top, label, value, unit)

    _footer(draw, fonts, state.mode, pressed_action)
    return image


def _header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    position: tuple[int, int],
    status: str,
    status_color: str,
    age: str,
) -> None:
    draw.ellipse((10, 8, 18, 16), fill=status_color)
    draw.text((24, 12), status, font=fonts["small"], fill=status_color, anchor="lm")
    draw.text(
        (310, 12),
        f"{position[0]}/{position[1]}",
        font=fonts["small"],
        fill=MUTED,
        anchor="rm",
    )
    name = _fit(
        draw,
        str(node.get("display_name", node["node_id"])).upper(),
        fonts["title"],
        250,
    )
    draw.text((10, 31), name, font=fonts["title"], fill=GREEN, anchor="lm")
    draw.text((310, 31), age, font=fonts["small"], fill=MUTED, anchor="rm")


def _details(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    state: UiState,
    history: HistoryStore | None,
    age: str,
    now: datetime | None,
) -> None:
    category_id = state.category_id(node)
    selected_category = category(category_id)
    if category_id == "health":
        _health_detail(draw, fonts, node, age)
        return
    metrics = selected_category.metrics
    selected_metric_id = state.metric_id(node)
    selected_metric = next(
        (metric for metric in metrics if metric.id == selected_metric_id),
        metrics[0],
    )
    for index, metric in enumerate(metrics):
        left = round(index * 320 / len(metrics))
        right = round((index + 1) * 320 / len(metrics))
        selected = metric.id == selected_metric.id
        color = BRIGHT if selected else (
            GREEN if metric.value(node, state.selected_gpu_index) is not None else MUTED
        )
        draw.text(
            ((left + right) // 2, 43),
            metric.title,
            font=fonts["small"],
            fill=color,
            anchor="mm",
        )
        if selected:
            draw.line((left + 8, 54, right - 8, 54), fill=BRIGHT, width=2)

    for view, x in ((DetailView.VALUES, 80), (DetailView.GRAPH, 240)):
        selected = state.detail_view == view
        draw.text(
            (x, 68),
            view.value.upper(),
            font=fonts["small"],
            fill=BRIGHT if selected else GREEN,
            anchor="mm",
        )
        if selected:
            draw.line((x - 48, 78, x + 48, 78), fill=BRIGHT, width=2)

    if state.detail_view == DetailView.VALUES:
        _values_detail(draw, fonts, node, state)
        return
    samples = (
        history.series(node["node_id"], category_id, selected_metric.id)
        if history
        else ()
    )
    _chart(
        draw,
        fonts,
        samples,
        selected_metric,
        selected_metric.value(node, state.selected_gpu_index),
        now,
    )

def _values_detail(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    state: UiState,
) -> None:
    category_id = state.category_id(node)
    if category_id == "cpu":
        cpu = node.get("cpu", {})
        rows = (
            ("LOAD", _format_percent(cpu.get("usage_percent"))),
            ("TEMP", _format_temperature(cpu.get("temperature_c"), True)),
            ("POWER", _format_power(cpu.get("power_w"), True)),
            ("CLOCK", _format_clock(cpu.get("clock_mhz"))),
        )
    elif category_id == "memory":
        memory = node.get("memory", {})
        rows = (
            ("RAM LOAD", _format_percent(memory.get("usage_percent"))),
            ("USED", _format_bytes_pair(memory.get("used_bytes"), memory.get("total_bytes"))),
            ("SWAP", _format_bytes_pair(memory.get("swap_used_bytes"), memory.get("swap_total_bytes"), True)),
            ("PSI", _format_percent(memory.get("pressure_some_percent"))),
        )
    elif category_id == "gpu":
        devices = node.get("gpu") or []
        gpu = devices[state.selected_gpu_index % len(devices)] if devices else {}
        name = _fit(draw, str(gpu.get("name", "N/A")), fonts["detail"], 205)
        rows = (
            ("GPU NAME", name),
            ("LOAD", _format_percent(gpu.get("usage_percent"))),
            (
                "TEMP / PWR",
                f"{_format_temperature(gpu.get('temperature_c'))} / {_format_power(gpu.get('power_w'))}",
            ),
            ("VRAM", _format_bytes_pair(gpu.get("memory_used_bytes"), gpu.get("memory_total_bytes"))),
            (
                "FAN / CLK",
                f"{_format_percent(gpu.get('fan_percent'))} / {_format_clock(gpu.get('clock_mhz'))}",
            ),
        )
    elif category_id == "storage":
        storage = node.get("storage", {})
        rows = (
            ("VOLUME", str(storage.get("name") or "N/A")),
            ("USED", _format_percent(storage.get("usage_percent"))),
            ("CAPACITY", _format_bytes_pair(storage.get("used_bytes"), storage.get("total_bytes"))),
            (
                "READ / WRITE",
                f"{_format_rate(storage.get('read_bytes_per_second'))} / {_format_rate(storage.get('write_bytes_per_second'))}",
            ),
            ("TEMP", _format_temperature(storage.get("temperature_c"), True)),
        )
    else:
        network = node.get("network", {})
        rows = (
            ("INTERFACE", str(network.get("interface") or "N/A")),
            ("LINK", _format_bool(network.get("link_up"))),
            ("DOWN", _format_rate(network.get("down_bytes_per_second"))),
            ("UP", _format_rate(network.get("up_bytes_per_second"))),
        )
    positions = (91, 112, 133, 154, 175)
    for y, (label, value) in zip(positions, rows):
        draw.text((10, y), label, font=fonts["detail"], fill=MUTED, anchor="lm")
        draw.text((310, y), value, font=fonts["detail"], fill=BRIGHT, anchor="rm")

def _detail_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    position: tuple[int, int],
    state: UiState,
    status_color: str,
    age: str,
) -> None:
    selected = category(state.category_id(node))
    name = _fit(
        draw,
        str(node.get("display_name", node["node_id"])).upper(),
        fonts["detail"],
        135,
    )
    draw.ellipse((8, 11, 16, 19), fill=status_color)
    draw.text((22, 15), name, font=fonts["detail"], fill=GREEN, anchor="lm")
    draw.text(
        (205, 15),
        f"/ {selected.title}",
        font=fonts["detail"],
        fill=GREEN,
        anchor="mm",
    )
    draw.text(
        (310, 15),
        f"{position[0]}/{position[1]}  {age}",
        font=fonts["small"],
        fill=MUTED,
        anchor="rm",
    )


def _menu(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    state: UiState,
) -> None:
    draw.text((10, 16), "METRICS", font=fonts["detail"], fill=GREEN, anchor="lm")
    name = _fit(
        draw,
        str(node.get("display_name", node["node_id"])).upper(),
        fonts["small"],
        180,
    )
    draw.text((310, 16), name, font=fonts["small"], fill=MUTED, anchor="rm")
    selected_id = state.category_id(node)
    errors = node.get("collector", {}).get("errors") or []
    for index, item in enumerate(CATEGORIES):
        column, row = index % 3, index // 3
        left, top = column * 107, 32 + row * 80
        right = 320 if column == 2 else left + 107
        available = item.available(node)
        color = (
            BRIGHT
            if item.id == selected_id
            else (
                AMBER
                if item.id == "health" and errors
                else GREEN if available else MUTED
            )
        )
        if item.id == selected_id:
            draw.rectangle((left + 3, top + 3, right - 4, top + 76), outline=MUTED)
        icon_left = (left + right) // 2 - 16
        item.icon(draw, (icon_left, top + 9, icon_left + 32, top + 41), color)
        draw.text(
            ((left + right) // 2, top + 55),
            item.title,
            font=fonts["small"],
            fill=color,
            anchor="mm",
        )
        draw.text(
            ((left + right) // 2, top + 69),
            "READY" if available else "NO DATA",
            font=fonts["tiny"],
            fill=color,
            anchor="mm",
        )


def _chart(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    samples: tuple[Sample, ...],
    metric: Any,
    current: Any,
    now: datetime | None,
) -> None:
    left, top, right, bottom = 28, 82, 310, 160
    values = [sample.value for sample in samples if sample.value is not None]
    maximum = metric.maximum
    if maximum is None:
        observed = max(values + ([float(current)] if current is not None else [1.0]))
        maximum = max(1.0, ceil(observed / 10) * 10)
    minimum = metric.minimum
    for y in (top, (top + bottom) // 2, bottom):
        draw.line((left, y, right, y), fill=MUTED)
    if metric.unit == "%":
        for threshold, color in ((80, AMBER), (95, RED)):
            y = round(bottom - (threshold - minimum) / (maximum - minimum) * (bottom - top))
            draw.line((right - 18, y, right, y), fill=color)
    elif metric.unit == "C":
        for threshold, color in ((80, AMBER), (90, RED)):
            y = round(bottom - (threshold - minimum) / (maximum - minimum) * (bottom - top))
            draw.line((right - 18, y, right, y), fill=color)
    draw.text((24, top), _number(maximum), font=fonts["tiny"], fill=MUTED, anchor="rm")
    draw.text((24, bottom), _number(minimum), font=fonts["tiny"], fill=MUTED, anchor="rm")

    end = (
        (now or datetime.now(timezone.utc)).timestamp()
        if not samples
        else max(samples[-1].timestamp, (now or datetime.now(timezone.utc)).timestamp())
    )
    start = end - 300
    segment: list[tuple[int, int]] = []
    last_point = None
    for sample in samples:
        if sample.value is None or sample.timestamp < start:
            if len(segment) > 1:
                draw.line(segment, fill=GREEN, width=2)
            segment = []
            continue
        x = round(left + (sample.timestamp - start) / 300 * (right - left))
        ratio = (float(sample.value) - minimum) / (maximum - minimum)
        y = round(bottom - min(1.0, max(0.0, ratio)) * (bottom - top))
        segment.append((x, y))
        last_point = (x, y)
    if len(segment) > 1:
        draw.line(segment, fill=GREEN, width=2)
    elif len(segment) == 1:
        draw.point(segment[0], fill=GREEN)
    if last_point:
        x, y = last_point
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=BRIGHT)
    elif not values:
        draw.text((169, 121), "COLLECTING HISTORY", font=fonts["small"], fill=MUTED, anchor="mm")

    valid = [value for value in values]
    now_value = _format_metric(current, metric.unit)
    minimum_value = _format_metric(min(valid), metric.unit) if valid else "—"
    maximum_value = _format_metric(max(valid), metric.unit) if valid else "—"
    draw.text((10, 177), f"NOW {now_value}", font=fonts["small"], fill=BRIGHT, anchor="lm")
    draw.text((160, 177), f"MIN {minimum_value}", font=fonts["small"], fill=MUTED, anchor="mm")
    draw.text((310, 177), f"MAX {maximum_value}", font=fonts["small"], fill=MUTED, anchor="rm")


def _health_detail(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    age: str,
) -> None:
    errors = node.get("collector", {}).get("errors") or []
    health = node.get("health", {})
    rows = (
        ("COLLECTOR", "OK" if not errors else f"ERR {len(errors)}"),
        ("UNDERVOLTAGE", _format_bool(health.get("undervoltage"))),
        ("THROTTLING", _format_bool(health.get("throttled"))),
        ("DATA AGE", age),
        ("UPTIME", _format_uptime(health.get("uptime_seconds"))),
    )
    draw.text((10, 54), "SYSTEM HEALTH", font=fonts["detail"], fill=GREEN, anchor="lm")
    for y, (label, value) in zip((80, 103, 126, 149, 172), rows):
        color = RED if value == "YES" else AMBER if label == "COLLECTOR" and errors else BRIGHT
        draw.text((10, y), label, font=fonts["detail"], fill=MUTED, anchor="lm")
        draw.text((310, y), value, font=fonts["detail"], fill=color, anchor="rm")


def _format_metric(value: Any, unit: str) -> str:
    if unit == "%":
        return _format_percent(value)
    if unit == "C":
        return _format_temperature(value)
    if unit == "W":
        return _format_power(value)
    if unit == "MHz":
        return _format_clock(value)
    if unit == "B/s":
        return _format_rate(value)
    return "—" if value is None else _number(value)


def _format_clock(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) / 1000:.2f}G"


def _format_bytes_pair(used: Any, total: Any, zero_is_off: bool = False) -> str:
    if used is None or total is None:
        return "N/A"
    if zero_is_off and not total:
        return "OFF"
    gib = 1024 ** 3
    return f"{float(used) / gib:.1f}/{float(total) / gib:.1f}GiB"


def _format_bool(value: Any) -> str:
    return "N/A" if value is None else "YES" if value else "NO"


def _format_uptime(value: Any) -> str:
    if value is None:
        return "N/A"
    days, remainder = divmod(max(0, int(value)), 86400)
    hours = remainder // 3600
    return f"{days}d{hours:02d}h"


def _format_rate(value: Any) -> str:
    if value is None:
        return "N/A"
    number = float(value)
    for divisor, suffix in ((1024 ** 2, "M"), (1024, "K")):
        if number >= divisor:
            return f"{number / divisor:.1f}{suffix}/s"
    return f"{number:.0f}B/s"


def _empty_state(
    draw: ImageDraw.ImageDraw, fonts: dict[str, Any], hub_online: bool
) -> None:
    color = GREEN if hub_online else AMBER
    title = "WAITING FOR SIGNAL" if hub_online else "LINK LOST"
    detail = "HUB ONLINE" if hub_online else "RETRYING"
    draw.text((160, 101), title, font=fonts["title"], fill=color, anchor="mm")
    draw.text((160, 130), detail, font=fonts["small"], fill=MUTED, anchor="mm")


def _value(value: Any, unit: str) -> str:
    if unit == "%":
        return _format_percent(value)
    if unit == "C":
        return _format_temperature(value)
    if unit == "W":
        return _format_power(value)
    return "—" if value is None else f"{_number(value)}{unit}"


def _number(value: Any) -> str:
    number = float(value)
    return f"{number:.0f}" if number.is_integer() else f"{number:.1f}"

def _status(node: dict[str, Any], hub_online: bool) -> tuple[str, str]:
    if not hub_online:
        return "LINK LOST", AMBER
    if node.get("waiting"):
        return "WAITING", AMBER
    if not node.get("online"):
        return "OFFLINE", RED
    errors = node.get("collector", {}).get("errors") or []
    if errors:
        return f"DEGRADED ERR {len(errors)}", AMBER
    return "ONLINE", GREEN


def _age(timestamp: Any, now: datetime | None = None) -> str:
    if not timestamp:
        return "—"
    try:
        then = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "—"
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _format_percent(value: Any) -> str:
    return "—" if value is None else f"{float(value):.0f}%"


def _format_temperature(value: Any, unsupported: bool = False) -> str:
    if value is None:
        return "N/A" if unsupported else "—"
    number = float(value)
    return f"{number:.0f}°C" if number.is_integer() else f"{number:.1f}°C"


def _format_power(value: Any, unsupported: bool = False) -> str:
    if value is None:
        return "N/A" if unsupported else "—"
    number = float(value)
    return f"{number:.1f}W" if abs(number) < 10 else f"{number:.0f}W"


def _metric_row(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    top: int,
    label: str,
    value: Any,
    unit: str,
) -> None:
    draw.text((12, top + 22), label, font=fonts["label"], fill=MUTED, anchor="lm")
    draw.text(
        (308, top + 22),
        _value(value, unit),
        font=fonts["value"],
        fill=BRIGHT if value is not None else MUTED,
        anchor="rm",
    )
    if unit == "%" and value is not None:
        draw.line((76, top + 46, 308, top + 46), fill=MUTED, width=1)
        width = round(232 * min(100.0, max(0.0, float(value))) / 100)
        draw.line((76, top + 46, 76 + width, top + 46), fill=GREEN, width=2)


def _footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    mode: ViewMode,
    pressed_action: str | None,
) -> None:
    center_label = {
        ViewMode.OVERVIEW: "HOLD: MENU",
        ViewMode.DETAIL: "TAP: OVERVIEW",
        ViewMode.MENU: "SELECT",
    }[mode]
    buttons = (
        ("previous", (0, FOOTER_TOP, 63, 239), "<"),
        ("center", (64, FOOTER_TOP, 255, 239), center_label),
        ("next", (256, FOOTER_TOP, 319, 239), ">"),
    )
    draw.line((0, FOOTER_TOP, 319, FOOTER_TOP), fill=MUTED)
    for action, box, label in buttons:
        pressed = action == pressed_action
        if pressed:
            draw.rectangle(box, fill=MUTED)
        draw.text(
            ((box[0] + box[2]) // 2, 216),
            label,
            font=fonts["label"] if action != "center" else fonts["small"],
            fill=BACKGROUND if pressed else GREEN,
            anchor="mm",
        )


def _font(size: int):
    for path in (
        FONT_PATH,
        "DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _fit(draw: ImageDraw.ImageDraw, text: str, font: Any, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > width:
        text = text[:-1]
    return text + suffix if text else "?"
