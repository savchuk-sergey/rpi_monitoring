from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont


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
    mode: str = "overview",
    gpu_index: int = 0,
    pressed_action: str | None = None,
    now: datetime | None = None,
) -> Image.Image:
    image = Image.new("RGB", SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    fonts = {
        "small": _font(13),
        "detail": _font(15),
        "label": _font(18),
        "title": _font(22),
        "value": _font(38),
    }
    if node is None:
        _empty_state(draw, fonts, hub_online)
        _footer(draw, fonts, mode, pressed_action)
        return image

    status, status_color = _status(node, hub_online)
    age = _age(node.get("received_at_utc") or node.get("timestamp_utc"), now)
    _header(draw, fonts, node, position, status, status_color, age)

    if mode == "details":
        _details(draw, fonts, node, gpu_index, age)
    else:
        cpu = node.get("cpu", {})
        gpu = node.get("gpu") or []
        power = node.get("device", {}).get("power_w")
        if power is None:
            power = cpu.get("power_w")
        if gpu:
            third = ("GPU", gpu[0].get("usage_percent"), "%")
        elif cpu.get("temperature_c") is not None:
            third = ("TEMP", cpu.get("temperature_c"), "C")
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

    _footer(draw, fonts, mode, pressed_action)
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
    gpu_index: int,
    age: str,
) -> None:
    cpu = node.get("cpu", {})
    gpu = node.get("gpu") or []
    selected_gpu = gpu[gpu_index % len(gpu)] if gpu else {}
    device_power = node.get("device", {}).get("power_w")
    errors = node.get("collector", {}).get("errors") or []
    gpu_name = (
        _fit(draw, str(selected_gpu.get("name", "N/A")), fonts["detail"], 205)
        if gpu
        else "N/A"
    )
    rows = (
        ("CPU", f"{_format_percent(cpu.get('usage_percent'))}  {_format_temperature(cpu.get('temperature_c'), True)}  {_format_power(cpu.get('power_w'), True)}"),
        ("RAM", _format_percent(node.get("memory", {}).get("usage_percent"))),
        (f"GPU {gpu_index % len(gpu) + 1}/{len(gpu)}" if gpu else "GPU", gpu_name),
        ("LOAD", f"{_format_percent(selected_gpu.get('usage_percent'))}  TEMP {_format_temperature(selected_gpu.get('temperature_c'), True)}"),
        ("GPU PWR", _format_power(selected_gpu.get("power_w"), True)),
        ("DEVICE", _format_power(device_power, True)),
        ("COLLECTOR", f"{'OK' if not errors else f'ERR {len(errors)}'}  AGE {age}"),
    )
    for y, (label, value) in zip((51, 72, 93, 114, 135, 156, 177), rows):
        draw.text((10, y), label, font=fonts["detail"], fill=MUTED, anchor="lm")
        draw.text((310, y), value, font=fonts["detail"], fill=BRIGHT, anchor="rm")


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
    mode: str,
    pressed_action: str | None,
) -> None:
    buttons = (
        ("previous", (0, FOOTER_TOP, 63, 239), "<"),
        ("mode", (64, FOOTER_TOP, 255, 239), mode.upper()),
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
            font=fonts["label"],
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
