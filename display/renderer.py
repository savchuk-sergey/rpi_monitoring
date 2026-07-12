from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


SIZE = (320, 240)
BACKGROUND = "#000400"
GREEN = "#43ff6b"
BRIGHT = "#c4ffcf"
MUTED = "#438d50"
RED = "#ff5c5c"
AMBER = "#ffb84d"
FONT_PATH = Path(__file__).with_name("assets") / "ShareTechMono-Regular.ttf"


def render(
    node: dict[str, Any] | None,
    position: tuple[int, int] = (0, 0),
    hub_online: bool = True,
) -> Image.Image:
    image = Image.new("RGB", SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    fonts = {
        "small": _font(13),
        "label": _font(18),
        "title": _font(22),
        "value": _font(42),
    }
    if node is None:
        _empty_state(draw, fonts, hub_online)
        return image

    online = bool(node.get("online"))
    gpu = node.get("gpu", [])
    first_gpu = gpu[0] if gpu else {}
    cpu = node.get("cpu", {})
    status, status_color = (
        ("STALE", AMBER)
        if not hub_online
        else (("ONLINE", GREEN) if online else ("OFFLINE", RED))
    )
    _header(draw, fonts, node)

    metrics = (
        ("CPU", cpu.get("usage_percent")),
        (f"GPU{f'1/{len(gpu)}' if len(gpu) > 1 else ''}", first_gpu.get("usage_percent")),
        ("RAM", node.get("memory", {}).get("usage_percent")),
    )
    for y, (label, value) in zip((72, 122, 172), metrics):
        draw.text((18, y), label, font=fonts["label"], fill=MUTED, anchor="lm")
        draw.text(
            (302, y),
            _value(value, "%"),
            font=fonts["value"],
            fill=BRIGHT if value is not None else MUTED,
            anchor="rm",
        )

    power_label = "DEV PWR" if "device" in node else "CPU PWR"
    power_value = (
        node.get("device", {}).get("power_w")
        if "device" in node
        else cpu.get("power_w")
    )
    details = _details(
        cpu.get("temperature_c"),
        power_label,
        power_value,
        first_gpu.get("temperature_c"),
        first_gpu.get("power_w"),
    )
    if details:
        draw.text((160, 204), details, font=fonts["small"], fill=MUTED, anchor="mm")

    draw.ellipse((14, 222, 20, 228), fill=status_color)
    draw.text((27, 225), status, font=fonts["small"], fill=status_color, anchor="lm")
    if not hub_online:
        draw.text((160, 225), "LINK LOST", font=fonts["small"], fill=AMBER, anchor="mm")
    navigation_color = GREEN if position[1] > 1 else MUTED
    draw.text(
        (308, 225),
        f"< {position[0]:02}/{position[1]:02} >",
        font=fonts["small"],
        fill=navigation_color,
        anchor="rm",
    )
    return image


def _header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
) -> None:
    name = _fit(
        draw,
        str(node.get("display_name", node["node_id"])).upper(),
        fonts["title"],
        270,
    )
    draw.text((16, 25), f"> {name}_", font=fonts["title"], fill=GREEN, anchor="lm")


def _details(
    cpu_temperature: Any,
    power_label: str,
    power: Any,
    gpu_temperature: Any,
    gpu_power: Any,
) -> str:
    values = []
    cpu_values = []
    if cpu_temperature is not None:
        cpu_values.append(f"{_number(cpu_temperature)}C")
    if power is not None and power_label == "CPU PWR":
        cpu_values.append(f"{_number(power)}W")
    if cpu_values:
        values.append(f"C:{'/'.join(cpu_values)}")
    if power is not None and power_label == "DEV PWR":
        values.append(f"D:{_number(power)}W")
    gpu_values = []
    if gpu_temperature is not None:
        gpu_values.append(f"{_number(gpu_temperature)}C")
    if gpu_power is not None:
        gpu_values.append(f"{_number(gpu_power)}W")
    if gpu_values:
        values.append(f"G:{'/'.join(gpu_values)}")
    return "  ".join(values)


def _empty_state(
    draw: ImageDraw.ImageDraw, fonts: dict[str, Any], hub_online: bool
) -> None:
    color = GREEN if hub_online else AMBER
    title = "WAITING_FOR_SIGNAL" if hub_online else "HUB_DISCONNECTED"
    detail = "HUB ONLINE" if hub_online else "RETRYING"
    draw.text((160, 108), f"> {title}_", font=fonts["title"], fill=color, anchor="mm")
    draw.text((160, 139), detail, font=fonts["small"], fill=MUTED, anchor="mm")


def _value(value: Any, unit: str) -> str:
    return "N/A" if value is None else f"{_number(value)} {unit}"


def _number(value: Any) -> str:
    return f"{value:05.2f}"


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
